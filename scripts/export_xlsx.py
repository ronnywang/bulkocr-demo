#!/usr/bin/env python3
"""Build the final spreadsheet from extraction results + reviewer corrections.

Usage:
  python3 scripts/export_xlsx.py templates/medical_record_1_2.json work/extract/results.json out.xlsx [--corrections corrections.json]

Without --corrections it exports the raw machine output (cells that need checking are highlighted).
"""
import argparse
import json
import re

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

YELLOW = PatternFill("solid", fgColor="FFF3B0")
BLUE = PatternFill("solid", fgColor="DCEBFF")
LOW_CONF = 0.9


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("template")
    ap.add_argument("results")
    ap.add_argument("out")
    ap.add_argument("--corrections")
    a = ap.parse_args()

    tpl = json.load(open(a.template))
    R = json.load(open(a.results))["pages"]
    C = json.load(open(a.corrections))["corrections"] if a.corrections else {}
    F = {f["id"]: f for f in tpl["fields"]}

    def entry(k, slot):
        fid, _, opt = slot.partition(".other.")
        e = R[k]["fields"][fid]
        return (e.get("other") or {}).get(opt, {}) if opt else e

    def final(k, slot):
        """-> (value, state) where state is 'corrected' | 'confirmed' | 'check' | 'auto'"""
        c = C.get(slot, {}).get(k, {})
        e = entry(k, slot)
        machine = e.get("value", "")
        if "value" in c and c["value"] != machine:
            return c["value"], "corrected"
        if c.get("confirmed"):
            return machine, "confirmed"
        flagged = bool(e.get("flags")) or (e.get("conf") is not None and not e.get("empty") and e["conf"] < LOW_CONF
                                           and F[slot.split(".")[0]]["type"] not in ("checkbox_single", "checkbox_multi"))
        return machine, ("check" if flagged else "auto")

    def opt_label(fid, v):
        return next((o["label"] for o in F[fid]["options"] if o["value"] == v), v)

    def other_text(k, fid, opt):
        ots = F[fid].get("other_text")
        ots = [ots] if isinstance(ots, dict) else (ots or [])
        if any(o["option"] == opt for o in ots):
            return final(k, f"{fid}.other.{opt}")
        return "", "auto"

    def as_cell(v):
        if isinstance(v, str) and re.fullmatch(r"-?\d+", v):
            return int(v)
        if isinstance(v, str) and re.fullmatch(r"-?\d+\.\d+", v):
            return float(v)
        return v

    def build(k, spec):
        """-> (cell value, list of states of the inputs used)"""
        op = spec["op"]
        if op == "value":
            v, s = final(k, spec["field"])
            return (as_cell(v) if F[spec["field"]]["type"] == "number" else v), [s]
        if op == "template":
            v, s = final(k, spec["field"])
            return (spec["template"].format(v) if v else ""), [s]
        if op == "option_label":
            v, s = final(k, spec["field"])
            if not v:
                return "", [s]
            lab = opt_label(spec["field"], v)
            return (f"{v} {lab}" if spec.get("with_value") else lab), [s]
        if op == "join":
            parts = [final(k, f) for f in spec["fields"]]
            if not any(v for v, _ in parts):
                return "", [s for _, s in parts]
            return spec.get("sep", "").join(str(v) for v, _ in parts), [s for _, s in parts]
        if op == "checked_labels":
            out, states = [], []
            for fid in spec["fields"]:
                v, s = final(k, fid)
                states.append(s)
                for x in ([v] if isinstance(v, str) else v):
                    if not x:
                        continue
                    t, ts = other_text(k, fid, x)
                    states.append(ts)
                    out.append(f"{opt_label(fid, x)}：{t}" if t else opt_label(fid, x))
            return spec.get("sep", "；").join(out), states
        if op == "checklist_text":
            parts, states = [], []
            for fid in spec["fields"]:
                f = F[fid]
                v, s = final(k, fid)
                states.append(s)
                checked = [v] if isinstance(v, str) else v
                items = []
                for o in f["options"]:
                    on = o["value"] in checked
                    t, ts = other_text(k, fid, o["value"])
                    if t:
                        states.append(ts if on or ts in ("corrected", "confirmed") else "check")
                    items.append(f"{'■' if on else '□'}{o['label']}" + (f" {t}" if t and on else ""))
                name = re.sub(r"^\d+\.", "", f["label"])
                parts.append("、".join(items) if len(f["options"]) == 1 else f"{name}：" + "、".join(items))
            return "；".join(parts), states
        raise ValueError(f"unknown export op {op}")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "資料"
    cols = ["序號", "來源頁"] + [s["column"] for s in tpl["export"]] + ["待確認欄位"]
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True)
    n_check = n_corr = 0
    for i, k in enumerate(sorted(R, key=int), 1):
        row, fills, todo = [i, R[k]["page"]], [None, None], []
        for spec in tpl["export"]:
            v, states = build(k, spec)
            row.append(v)
            if "check" in states:
                fills.append(YELLOW)
                todo.append(spec["column"])
                n_check += 1
            elif "corrected" in states:
                fills.append(BLUE)
                n_corr += 1
            else:
                fills.append(None)
        row.append("、".join(todo))
        fills.append(None)
        ws.append(row)
        for j, fill in enumerate(fills, 1):
            if fill:
                ws.cell(row=ws.max_row, column=j).fill = fill
    for j, col in enumerate(cols, 1):
        width = max(len(str(col)), *(len(str(ws.cell(row=r, column=j).value or "")) for r in range(2, ws.max_row + 1)))
        ws.column_dimensions[get_column_letter(j)].width = min(60, max(8, width * 1.6))
    ws.freeze_panes = "C2"

    log = wb.create_sheet("校正紀錄")
    log.append(["頁", "欄位", "機器辨識", "最終值", "狀態", "旗標"])
    for c in log[1]:
        c.font = Font(bold=True)
    slots = []
    for f in tpl["fields"]:
        if f["type"] == "drawing":
            continue
        slots.append(f["id"])
        ots = f.get("other_text")
        for o in ([ots] if isinstance(ots, dict) else (ots or [])):
            slots.append(f"{f['id']}.other.{o['option']}")
    state_txt = {"corrected": "已修正", "confirmed": "已確認", "check": "待確認", "auto": "未標旗（未人工確認）"}
    for k in sorted(R, key=int):
        for slot in slots:
            v, s = final(k, slot)
            e = entry(k, slot)
            if s == "auto" and not C:
                continue
            fmt = lambda x: "、".join(x) if isinstance(x, list) else str(x)
            log.append([int(k), slot, fmt(e.get("value", "")), fmt(v), state_txt[s], "、".join(e.get("flags", []))])

    note = wb.create_sheet("說明")
    note.append(["黃色", "機器有旗標、尚未人工確認的儲存格"])
    note.append(["藍色", "人工修正過的儲存格"])
    note["A1"].fill, note["A2"].fill = YELLOW, BLUE
    wb.save(a.out)
    print(f"wrote {a.out}: {len(R)} rows, {n_check} cells to check, {n_corr} corrected")


if __name__ == "__main__":
    main()
