#!/usr/bin/env python3
"""Extract field values from aligned pages using a template.

For every aligned page:
  * checkbox options -> "new ink" score = handwriting pixels (page minus blank form) around the box
  * text-like fields -> crop region; if it holds handwriting, OCR the crop (printed text dropped out)
  * values are normalised per field type and validated; problems become flags for review

Outputs in <out>/:
  crops/<field>/<page>.png          crop for human review (original pixels)
  ocr_cache/<variant>/<field>/<page>.json   cached OCR responses
  results.json                      all pages x fields

Usage:
  PADDLEOCR_API_URL=... python3 scripts/extract.py templates/medical_record_1_2.json work/aligned work/blank.png work/extract
"""
import argparse
import difflib
import json
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).parent))
from ocr_batch import auth_headers, ocr_one  # noqa: E402

INK = 150          # gray level below which a pixel counts as ink
TEXT_PAD = 6       # extra px around text regions
EMPTY_RATIO = 0.004  # new-ink ratio below which a text field is treated as empty
VARIANTS = ("dropout", "raw")  # OCR input with printed text removed / original pixels
GROUP_LABEL_W = 230            # px of printed label kept right of the last box in group crops
CB_TH = 0.04                   # checkbox new-ink score threshold
CB_UNSURE = (0.02, 0.07)       # scores in this band get flagged for review
CB_MARGIN = dict(left=4, right=16, top=18, bottom=4)  # check marks overflow up/right


# ---------------------------------------------------------------- images
def new_ink_mask(page, blank_dark_dil):
    return (page < INK) & ~blank_dark_dil


def crop(a, b, pad=0):
    h, w = a.shape[:2]
    x1, y1, x2, y2 = max(0, b[0] - pad), max(0, b[1] - pad), min(w, b[2] + pad), min(h, b[3] + pad)
    return a[y1:y2, x1:x2]


def checkbox_score(ink, b):
    x1, y1, x2, y2 = b
    region = ink[max(0, y1 - CB_MARGIN["top"]):y2 + CB_MARGIN["bottom"],
                 max(0, x1 - CB_MARGIN["left"]):x2 + CB_MARGIN["right"]]
    return float(region.sum()) / ((x2 - x1) * (y2 - y1))


def decide_checkbox(field, scores):
    flags = []
    checked = [v for v, sc in scores.items() if sc >= CB_TH]
    if any(CB_UNSURE[0] <= sc < CB_UNSURE[1] for sc in scores.values()):
        flags.append("checkbox_unsure")
    if field["type"] == "checkbox_single":
        if len(checked) > 1:
            flags.append("multiple_checked")
        checked = [max(scores, key=scores.get)] if checked else []
        if field.get("required") and not checked:
            flags.append("required_empty")
        return (checked[0] if checked else ""), flags
    return checked, flags


def norm_cmp(v):
    return re.sub(r"[\s\-—/.,、]", "", nfkc(str(v))).upper()


# ---------------------------------------------------------------- OCR text
def join_lines(items):
    """Join OCR boxes into reading order (rows by vertical overlap, then x)."""
    boxes = []
    for it in items:
        xs = [p[0] for p in it["box"]]
        ys = [p[1] for p in it["box"]]
        boxes.append((min(ys), max(ys), min(xs), it))
    boxes.sort(key=lambda b: b[0])
    rows = []
    for b in boxes:
        cy = (b[0] + b[1]) / 2
        for r in rows:
            if r["y1"] <= cy <= r["y2"]:
                r["items"].append(b)
                break
        else:
            rows.append({"y1": b[0], "y2": b[1], "items": [b]})
    lines = []
    for r in rows:
        r["items"].sort(key=lambda b: b[2])
        lines.append("".join(b[3]["text"] for b in r["items"]))
    return lines


DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1", "i": "1",
                           "Z": "2", "z": "2", "S": "5", "s": "5", "B": "8", "g": "9", "q": "9", "G": "6",
                           "b": "6", "T": "7", "A": "4", "n": "7", "a": "9", "+": "1", "」": "1", "〕": "1"})
LETTER_FIX = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "4": "A", "7": "T"}


def fix_digits(t):
    """Map look-alike letters to digits only when they sit between/next to digits."""
    t = re.sub(r"(?<=\d)[OoDQIl|iZzSsBgqGbTAna](?=\d)", lambda m: m.group(0).translate(DIGIT_FIX), t)
    t = re.sub(r"^[OoDIl|ZSBg](?=\d)", lambda m: m.group(0).translate(DIGIT_FIX), t)
    return t


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "")


def normalize(field, text):
    """Return (value, flags)."""
    t = nfkc(text).strip()
    flags = []
    ftype, fid, val = field["type"], field["id"], field.get("validate", {})
    if not t:
        return "", flags

    if fid == "ticket_no":
        u = re.sub(r"[—–_~\s]+", "-", t.upper())
        # drop the "SIM" prefix (often misread as 5IM / SIH) up to the first separator
        body = u.split("-", 1)[1] if "-" in u[:5] else u[3:]
        digits = re.sub(r"\D", "", fix_digits(body))
        if len(digits) >= 11:
            v = f"SIM-{digits[:8]}-{digits[-3:]}"
            if len(digits) != 11:
                flags.append("digits_count")
        else:
            v, _ = u, flags.append("pattern")
        return v, flags

    if fid == "id_no":
        u = re.sub(r"[^0-9A-Za-z]", "", t).upper()
        if not u:
            return t, ["pattern"]
        head = LETTER_FIX.get(u[0], u[0])
        body = u[1:].translate(DIGIT_FIX)
        body = re.sub(r"\D", "", body)
        v = head + body
        if not re.fullmatch(val.get("pattern", ".*"), v):
            flags.append("pattern")
        return v, flags

    if fid == "bp":
        nums = re.findall(r"\d+", fix_digits(t))
        if len(nums) >= 2:
            v = f"{nums[0]}/{nums[1]}"
            if len(nums) > 2:
                flags.append("extra_numbers")
        else:
            v = t
            flags.append("pattern")
        return v, flags

    if fid == "gcs":
        u = t.upper().replace(" ", "").replace("（", "(").replace("）", ")")
        u = re.sub(r"^[、,.]+|[、,.體]+$", "", u)
        u = re.sub(r"(?<=\d)[A-Z]+$", "", u)  # trailing residue like 15C / 15R
        m = re.match(r"(\d{1,2})", fix_digits(u))
        if m and not 3 <= int(m.group(1)) <= 15:
            flags.append("range")
        return u, flags

    if ftype == "number":
        u = fix_digits(t)
        dec = val.get("decimals", 0)
        m = re.search(r"\d+(?:\.\d+)?", u)
        if not m:
            return t, ["not_number"]
        v = m.group(0)
        if dec and "." not in v and len(v) == 3:   # 367 -> 36.7 (decimal point missed)
            v = v[:-1] + "." + v[-1]
            flags.append("auto_decimal")
        try:
            x = float(v)
            if ("min" in val and x < val["min"]) or ("max" in val and x > val["max"]):
                flags.append("range")
        except ValueError:
            flags.append("not_number")
        return v, flags

    if ftype == "date":
        m = re.search(r"(\d{3,4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", fix_digits(t))
        if m:
            y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
            if len(y) == 3:
                flags.append("year_digits")
            if not (1900 <= int(y) <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31):
                flags.append("range")
            return f"西元{y}年{mo:02d}月{d:02d}日", flags
        nums = re.findall(r"\d+", fix_digits(t))
        y = next((n for n in nums if len(n) == 4), None)
        rest = [n for n in nums if n != y][:2] if y else []
        if y and len(rest) == 2:
            mo, d = int(rest[0]), int(rest[1])
            v = f"西元{y}年{mo:02d}月{d:02d}日"
            if not (1900 <= int(y) <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31):
                flags.append("range")
            return v, flags
        return t, ["pattern"]

    # free text: drop stray punctuation at the ends
    v = re.sub(r"^[\s、,.。:：_\-—]+|[\s、,.:：_\-—]+$", "", t)
    if field.get("dictionary"):
        best = max(field["dictionary"], key=lambda w: difflib.SequenceMatcher(None, v, w).ratio())
        r = difflib.SequenceMatcher(None, v, best).ratio()
        if v != best:
            if r >= 0.5:
                flags.append(f"dict:{v}")
                v = best
            else:
                flags.append("not_in_dictionary")
    return v, flags


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("template")
    ap.add_argument("aligned_dir")
    ap.add_argument("blank")
    ap.add_argument("out")
    ap.add_argument("--model", default="v6-medium")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()

    tpl = json.loads(Path(a.template).read_text())
    out = Path(a.out)
    blank = np.asarray(Image.open(a.blank).convert("L"))
    blank_dark_dil = ndi.binary_dilation(blank < 185, iterations=2)
    pages = sorted(Path(a.aligned_dir).glob("*.png"))

    url = os.environ.get("PADDLEOCR_API_URL", "").rstrip("/") + "/"
    headers = auth_headers()

    # ---- collect jobs
    results = {}
    ocr_jobs = []  # (page_key, slot, sub-field, entry, variant, input_png, cache_path)
    for p in pages:
        key = p.stem.rsplit("_", 1)[-1]
        img = np.asarray(Image.open(p).convert("L"))
        ink = new_ink_mask(img, blank_dark_dil)
        res = results[key] = {"page": p.name, "fields": {}}

        for f in tpl["fields"]:
            r = res["fields"][f["id"]] = {"type": f["type"]}
            if f.get("options"):
                sc = {o["value"]: round(checkbox_score(ink, o["bbox"]), 3) for o in f["options"]}
                r["scores"] = sc
                r["value"], cb_flags = decide_checkbox(f, sc)
                if cb_flags:
                    r["flags"] = cb_flags
                # crop of the whole option group (boxes + printed labels) for the review page
                xs1 = min(o["bbox"][0] for o in f["options"]) - 12
                ys1 = min(o["bbox"][1] for o in f["options"]) - 26
                xs2 = max(o["bbox"][2] for o in f["options"]) + GROUP_LABEL_W
                ys2 = max(o["bbox"][3] for o in f["options"]) + 10
                gb = [max(0, xs1), max(0, ys1), min(img.shape[1], xs2), min(img.shape[0], ys2)]
                gdir = out / "crops" / f["id"]
                gdir.mkdir(parents=True, exist_ok=True)
                Image.fromarray(crop(img, gb)).save(gdir / f"{key}.png")
                r["crop"] = f"crops/{f['id']}/{key}.png"
                r["crop_origin"] = gb[:2]
            slots = []
            if f.get("bbox") and f["type"] != "drawing":
                slots.append((f["id"], f["bbox"], f))
            ots = f.get("other_text")
            for o in ([ots] if isinstance(ots, dict) else (ots or [])):
                slots.append((f"{f['id']}.other.{o['option']}", o["bbox"], {"id": "other", "type": "text"}))
            for slot, bbox, sf in slots:
                ratio = float(crop(ink, bbox, TEXT_PAD).mean())
                crop_dir = out / "crops" / slot
                crop_dir.mkdir(parents=True, exist_ok=True)
                cp = crop_dir / f"{key}.png"
                Image.fromarray(crop(img, bbox, TEXT_PAD)).save(cp)
                if slot == f["id"]:
                    entry = r  # write OCR results straight into the field's result
                else:
                    entry = r.setdefault("other", {})[slot.rsplit(".", 1)[-1]] = {}
                entry.update(ink=round(ratio, 4), crop=str(cp.relative_to(out)))
                if ratio < EMPTY_RATIO:
                    entry.update(value="", raw="", conf=1.0, empty=True)
                    continue
                entry["primary"] = "dropout" if sf.get("dropout", True) else "raw"
                for variant in VARIANTS:
                    c = crop(img, bbox, TEXT_PAD).copy()
                    if variant == "dropout":
                        c[crop(blank_dark_dil, bbox, TEXT_PAD)] = 255
                    c = np.pad(c, 24, constant_values=255)
                    ocr_dir = out / "ocr_input" / variant / slot
                    ocr_dir.mkdir(parents=True, exist_ok=True)
                    ip = ocr_dir / f"{key}.png"
                    Image.fromarray(c).save(ip)
                    cache = out / "ocr_cache" / variant / slot / f"{key}.json"
                    ocr_jobs.append((key, slot, sf, entry, variant, ip, cache))

    # ---- OCR (cached)
    def run(job):
        cache, ip = job[6], job[5]
        if cache.exists():
            items = json.loads(cache.read_text())
        else:
            items, _, _ = ocr_one(url, headers, ip, a.model)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(items, ensure_ascii=False))
        return job, items

    todo = sum(not j[6].exists() for j in ocr_jobs)
    print(f"{len(pages)} pages, {len(ocr_jobs)} OCR inputs ({todo} need OCR)", flush=True)
    done = 0
    with ThreadPoolExecutor(a.workers) as ex:
        for (key, slot, sf, entry, variant, ip, cache), items in ex.map(run, ocr_jobs):
            lines = join_lines(items)
            para = sf["type"] == "paragraph"
            raw = "\n".join(lines) if para else "".join(lines)
            v, flags = normalize(sf, raw.replace("\n", "") if para else raw)
            entry.setdefault("variants", {})[variant] = {
                "raw": raw, "value": raw.replace("\n", "") if para else v, "flags": flags,
                "conf": round(min([it["score"] for it in items], default=0.0), 3),
                "ocr_input": str(ip.relative_to(out))}
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(ocr_jobs)}", flush=True)

    # ---- pick primary variant, flag disagreement
    def finish(entry, sf):
        if "variants" not in entry:
            return
        V = entry["variants"]
        prim = V[entry["primary"]]
        entry.update(raw=prim["raw"], value=prim["value"], conf=prim["conf"])
        flags = list(prim["flags"])
        others = [x for k, x in V.items() if k != entry["primary"]]
        if sf["type"] != "paragraph" and any(norm_cmp(o["value"]) != norm_cmp(prim["value"]) for o in others):
            flags.append("variants_disagree")
        if flags:
            entry["flags"] = sorted(set(entry.get("flags", []) + flags))

    F = {f["id"]: f for f in tpl["fields"]}
    for res in results.values():
        for fid, r in res["fields"].items():
            finish(r, F[fid])
            for e in r.get("other", {}).values():
                finish(e, {"type": "text"})

    (out / "results.json").write_text(json.dumps({"template": tpl["form_id"],
                                                   "pages": results}, ensure_ascii=False, indent=1))
    print(f"wrote {out}/results.json")


if __name__ == "__main__":
    main()
