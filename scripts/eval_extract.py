#!/usr/bin/env python3
"""Compare extract.py results with the ground-truth xlsx.

Usage: python3 scripts/eval_extract.py work/extract/results.json templates/medical_record_1_2.json 模擬醫療記錄單30份_資料表.xlsx [--show 5]
"""
import argparse
import json
import re
import unicodedata

import openpyxl

PUNCT = r"[\s—–\-_、，,。：:；;（）()「」]"


def norm(s):
    return re.sub(PUNCT, "", unicodedata.normalize("NFKC", str(s if s is not None else "")))


def cer(pred, gt):
    a, b = norm(pred), norm(gt)
    if not b:
        return 0.0 if not a else 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / len(b)


def gt_str(col, v):
    if v is None:
        return ""
    if isinstance(v, float):
        return str(v) if col == "體溫(°C)" else str(int(v))
    return str(v)


TEXT_FIELDS = {  # field id -> xlsx column
    "ticket_no": "傷票編號", "team": "救護隊", "triage_signature": "醫師簽章", "name": "姓名", "age": "年齡",
    "birthday": "生日", "id_no": "身分證字號欄", "nationality": "國籍(非本國籍)", "gcs": "GCS",
    "temp": "體溫(°C)", "pulse": "脈搏(/min)", "resp": "呼吸次數(/min)", "spo2": "血氧(%)",
}


def decide(field, scores, th):
    if field["type"] == "checkbox_single":
        best = max(scores, key=scores.get)
        return [best] if scores[best] >= th else []
    return [v for v, s in scores.items() if s >= th]


def parse_history(s):
    """'□懷孕；疫苗接種：□破傷風、□其他 未知；過敏史：■無、□有；慢性疾病：■無已知慢性病' -> {section: set(checked)}"""
    out = {"pregnant": set(), "vaccine": set(), "allergy": set(), "chronic": set()}
    names = {"疫苗接種": "vaccine", "過敏史": "allergy", "慢性疾病": "chronic"}
    for part in str(s or "").split("；"):
        sec = "pregnant"
        m = re.match(r"(疫苗接種|過敏史|慢性疾病)：(.*)", part)
        body = part
        if m:
            sec, body = names[m.group(1)], m.group(2)
        for tok in re.findall(r"■([^、□■]+)", body):
            out[sec].add(tok.strip().split(" ")[0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("template")
    ap.add_argument("xlsx")
    ap.add_argument("--th", type=float, default=0.25, help="checkbox score threshold")
    ap.add_argument("--show", type=int, default=6)
    a = ap.parse_args()

    R = json.load(open(a.results))["pages"]
    tpl = json.load(open(a.template))
    F = {f["id"]: f for f in tpl["fields"]}
    ws = openpyxl.load_workbook(a.xlsx)["模擬資料"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = rows[0]
    gt = {int(r[0]): dict(zip(hdr, r)) for r in rows[1:] if r[0] is not None}

    stats, errs = {}, {}

    def rec(name, ok, detail):
        s = stats.setdefault(name, [0, 0])
        s[0] += ok
        s[1] += 1
        if not ok:
            errs.setdefault(name, []).append(detail)

    hpi_cer = []
    for key in sorted(R, key=int):
        page, g = R[key]["fields"], gt[int(key)]
        for fid, col in TEXT_FIELDS.items():
            pv = page[fid].get("value", "")
            if fid == "team" and pv:
                pv += "災難醫療救護隊"
            gv = gt_str(col, g[col])
            ok = norm(pv) == norm(gv)
            rec(col, ok, f"p{key}: {pv!r} ≠ {gv!r}  raw={page[fid].get('raw','')!r} flags={page[fid].get('flags',[])}")
        bp = f"{page['bp_sys'].get('value','')}/{page['bp_dia'].get('value','')}"
        rec("血壓(mmHg)", norm(bp) == norm(g["血壓(mmHg)"]), f"p{key}: {bp!r} ≠ {g['血壓(mmHg)']!r}  raw={page['bp_sys'].get('raw','')!r} / {page['bp_dia'].get('raw','')!r}")
        # checkboxes
        tri = decide(F["triage"], page["triage"]["scores"], a.th)
        rec("檢傷代碼", tri == [str(g["檢傷代碼"])], f"p{key}: {tri} ≠ {g['檢傷代碼']}  {page['triage']['scores']}")
        sex = decide(F["sex"], page["sex"]["scores"], a.th)
        rec("性別", sex == [g["性別"]], f"p{key}: {sex} ≠ {g['性別']}  {page['sex']['scores']}")
        labels = {}
        for fid in ("dx_trauma", "dx_nontrauma"):
            for v in decide(F[fid], page[fid]["scores"], a.th):
                labels[next(o["label"] for o in F[fid]["options"] if o["value"] == v)] = fid
        gdx = {re.sub(r"^其他[:：].*", "其他", x.strip()) for x in str(g["主要初步診斷"] or "").split("；") if x.strip()}
        rec("主要初步診斷(集合)", set(labels) == gdx, f"p{key}: {sorted(labels)} ≠ {sorted(gdx)}")
        hist = parse_history(g["過去重要病史"])
        for fid in ("pregnant", "vaccine", "allergy", "chronic"):
            got = set(decide(F[fid], page[fid]["scores"], a.th))
            want = {x if x in {o["value"] for o in F[fid]["options"]} else "其他" for x in hist[fid]}
            rec(f"病史:{fid}", got == want, f"p{key}: {sorted(got)} ≠ {sorted(want)}  {page[fid]['scores']}")
        # some forms were filled in English: score against whichever language is closer
        gzh = re.sub(r"（本紀錄為合成模擬資料）", "", str(g["現病史（中文）"] or ""))
        gen = str(g.get("Present Illness (English)") or "")
        pv = page["hpi"].get("value", "")
        c, gh = min((cer(pv, gzh), gzh), (cer(pv.lower(), gen.lower()), gen))
        hpi_cer.append((c, key, pv, gh))

    print(f"{'欄位':22s} 正確")
    tot = [0, 0]
    for k, (c, n) in stats.items():
        tot[0] += c
        tot[1] += n
        print(f"  {k:20s} {c:2d}/{n} {c/n:6.1%}")
    print(f"  {'(合計)':20s} {tot[0]}/{tot[1]} {tot[0]/tot[1]:6.1%}")
    m = sum(x[0] for x in hpi_cer) / len(hpi_cer)
    print(f"  現病史 平均 CER {m:.1%}（字元錯誤率，越低越好）")
    if a.show:
        print("\n錯誤樣本：")
        for k, lst in errs.items():
            for d in lst[:a.show]:
                print(f"  [{k}] {d}")
        print("\n現病史最差 3 筆：")
        for c, key, p, g in sorted(hpi_cer, reverse=True)[:3]:
            print(f"  p{key} CER {c:.0%}\n    OCR: {p}\n    GT : {g}")


if __name__ == "__main__":
    main()
