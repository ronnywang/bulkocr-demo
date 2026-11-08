#!/usr/bin/env python3
"""Rough baseline: pull a few fields out of raw full-page OCR text with label
regexes (no template, no alignment yet) and compare them with the ground-truth xlsx.
It measures how much PaddleOCR alone gets right before any template work.

Usage: python3 scripts/quick_eval.py ocr_raw/v6-medium 模擬醫療記錄單30份_資料表.xlsx
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import openpyxl


def norm(s):
    s = unicodedata.normalize("NFKC", str(s or ""))
    return re.sub(r"[\s—–\-_、，,。：:（）()]", "", s)


def lines(items):
    # sort roughly top-to-bottom, left-to-right
    return [it["text"] for it in sorted(items, key=lambda i: (i["box"][0][1] // 15, i["box"][0][0]))]


def find(pattern, text):
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""


def extract(items):
    t = "\n".join(lines(items))
    tn = unicodedata.normalize("NFKC", t)
    out = {}
    m = re.search(r"SIM\s*[—–\-_~]*\s*(\d{8})\s*[—–\-_~]*\s*(\d{3})", tn)
    out["傷票編號"] = f"SIM-{m.group(1)}-{m.group(2)}" if m else ""
    out["姓名"] = find(r"姓名[：:]\s*([^\s3]+)", tn)
    out["年齡"] = find(r"年[齡龄][：:]\s*(\d+)", tn)
    m = re.search(r"西元\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", tn)
    out["生日"] = f"西元{m.group(1)}年{int(m.group(2)):02d}月{int(m.group(3)):02d}日" if m else ""
    out["身分證字號欄"] = find(r"([A-Z]\d{9})", tn)
    out["醫師簽章"] = find(r"簽章[：:]\s*(\S+)", tn)
    out["體溫(°C)"] = find(r"體溫[：:]\s*([\d.]+)", tn)
    out["脈搏(/min)"] = find(r"脈[搏博膊][：:]\s*(\d+)", tn)
    out["呼吸次數(/min)"] = find(r"呼吸次數[：:]\s*(\d+)", tn)
    out["血壓(mmHg)"] = find(r"血壓[：:]\s*(\d+\s*/\s*\d+)", tn).replace(" ", "")
    out["血氧(%)"] = find(r"血氧[：:]\s*(\d+)", tn)
    team = find(r"([^\s：:]+)\s*\n?.*?災難醫療救護隊", tn)
    out["救護隊"] = ""
    for it in items:  # team name is a standalone handwritten box near the top
        if it["box"][0][1] < 260 and "隊" not in it["text"] and "：" not in it["text"]:
            out["救護隊"] = it["text"] + "災難醫療救護隊"
    return out, t


def fmt_gt(col, v):
    if v is None:
        return ""
    if isinstance(v, float):
        return str(v) if col == "體溫(°C)" else str(int(v))
    return str(v)


def main():
    ocr_dir, xlsx = Path(sys.argv[1]), sys.argv[2]
    ws = openpyxl.load_workbook(xlsx)["模擬資料"]
    rows = list(ws.iter_rows(values_only=True))
    hdr, data = rows[0], rows[1:]
    gt_by_id = {r[hdr.index("傷票編號")]: dict(zip(hdr, r)) for r in data if r[0] is not None}

    files = sorted(ocr_dir.glob("*.json"))
    fields = ["傷票編號", "救護隊", "醫師簽章", "姓名", "年齡", "生日", "身分證字號欄",
              "體溫(°C)", "脈搏(/min)", "呼吸次數(/min)", "血壓(mmHg)", "血氧(%)"]
    stats = {f: [0, 0] for f in fields}
    present = {f: 0 for f in fields}
    errors = {f: [] for f in fields}
    scores = []
    for i, f in enumerate(files, 1):
        d = json.loads(f.read_text())
        scores += [it["score"] for it in d["items"]]
        got, full = extract(d["items"])
        full_n = norm(full)
        gt = gt_by_id.get(f"SIM-20260720-{i:03d}")  # page N <-> SIM-...-00N per the xlsx notes
        for k in fields:
            g = fmt_gt(k, gt.get(k))
            ok = norm(got[k]) == norm(g) or (k == "體溫(°C)" and norm(got[k]).replace(".", "") == norm(g).replace(".", ""))
            stats[k][0] += ok
            gv = norm(g).replace("災難醫療救護隊", "")
            if k == "體溫(°C)":
                gv = gv  # keep decimal point: OCR dropping it counts as a miss
            if k == "生日":
                m = re.match(r"西元(\d{4})年(\d+)月(\d+)日", g)
                gv = f"西元{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日" if m else gv
                present[k] += ok or (gv in full_n) or (norm(g) in full_n)
            else:
                present[k] += bool(gv) and gv in full_n
            stats[k][1] += 1
            if not ok:
                errors[k].append((i, got[k], g))

    print(f"pages: {len(files)}  boxes: {len(scores)}  mean score: {sum(scores)/len(scores):.3f}  "
          f"score<0.8: {sum(s < 0.8 for s in scores)/len(scores):.1%}\n")
    print("field              regex-parsed   value-present-anywhere-in-OCR-text")
    for k in fields:
        c, n = stats[k]
        print(f"  {k:14s} {c:2d}/{n} {c/n:6.1%}   {present[k]:2d}/{n} {present[k]/n:6.1%}")
    print("\nsample errors (page: OCR -> truth):")
    for k in fields:
        for p, g, t in errors[k][:4]:
            print(f"  [{k}] p{p:02d}: {g!r} -> {t!r}")


if __name__ == "__main__":
    main()
