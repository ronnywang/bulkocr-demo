#!/usr/bin/env python3
"""AI-drafted template for 1.2醫療記錄單 (the first version, before human review in the editor).

Coordinates are pixels in the reference frame (work/blank.png, 1646x2331, ~200dpi).
Checkbox boxes come from connected-component detection on the median blank form;
value regions were placed from the blank-form OCR label boxes and the table lines.

Usage: python3 scripts/draft_template_1_2.py work/anchors.json templates/medical_record_1_2.json
"""
import json
import sys

S = 25  # checkbox side, px


def cb(x, y, s=S):
    return [x, y, x + s, y + s]


def opts(pairs):
    return [{"value": v, "label": l, "bbox": cb(x, y)} for v, l, x, y in pairs]


trauma = [  # 7.1 創傷: (no, label, x, y)
    (1, "撕裂傷", 425, 1547), (2, "表淺損傷", 425, 1581), (3, "鈍挫傷、拉扭傷", 425, 1616),
    (4, "中軸骨折", 425, 1650), (5, "骨盆骨折", 425, 1685), (6, "四肢閉鎖性骨折", 425, 1720),
    (7, "四肢開放性骨折", 425, 1754),
    (8, "截肢", 858, 1545), (9, "脫臼", 858, 1579), (10, "壓砸傷", 858, 1613), (11, "輕度頭部外傷", 858, 1648),
    (12, "中重度頭部外傷", 858, 1683), (13, "脊髓損傷", 858, 1718), (14, "氣血胸", 858, 1752),
    (15, "心血管損傷", 1232, 1543), (16, "腹部臟器損傷", 1232, 1577), (17, "燒傷", 1232, 1612),
    (18, "環境急症", 1233, 1646), (19, "其他外科", 1233, 1681),
]
nontrauma = [  # 7.2 非創傷
    (1, "發燒", 426, 1792), (2, "肺炎", 426, 1826), (3, "氣喘或慢性阻塞性肺病", 426, 1878), (4, "急性腹痛", 426, 1930),
    (5, "腸胃炎", 426, 1965), (6, "出血性腹瀉", 426, 2000), (7, "上呼吸道感染", 426, 2034), (8, "泌尿道感染", 426, 2069),
    (9, "暈眩", 858, 1789), (10, "頭痛", 858, 1824), (11, "糖尿病相關病症", 859, 1876), (12, "消化道出血", 859, 1928),
    (13, "高血壓", 859, 1963), (14, "蜂窩性組織炎", 859, 1997), (15, "過敏或濕疹", 859, 2032), (16, "其他皮膚病", 859, 2067),
    (17, "急性冠心症", 1233, 1788), (18, "心衰竭", 1233, 1822), (19, "呼吸衰竭", 1233, 1857), (20, "腦中風", 1233, 1892),
    (21, "焦慮症", 1234, 1926), (22, "其他精神疾病", 1234, 1961), (23, "中毒", 1234, 1995), (24, "婦產科急症", 1234, 2030),
    (25, "其他", 1234, 2065),
]

fields = [
    {"id": "team", "label": "隊名（災難醫療救護隊）", "type": "text", "bbox": [245, 140, 665, 245],
     "dictionary": ["北區", "中區", "南區", "東區"]},
    {"id": "triage", "label": "1.檢傷分類", "type": "checkbox_single", "required": True, "options": opts([
        ("1", "復甦急救(重傷)", 344, 413), ("2", "緊急(中傷)", 659, 412), ("3", "非緊急(輕傷)", 884, 411),
        ("4", "死亡", 344, 452), ("4-1", "緩和治療", 660, 451)])},
    {"id": "triage_signature", "label": "1.檢傷分類 簽章", "type": "text", "bbox": [972, 488, 1145, 552]},
    {"id": "sex", "label": "2.性別", "type": "checkbox_single", "required": True, "options": opts([
        ("男", "男", 1291, 421), ("女", "女", 1369, 421), ("其他", "其他", 1449, 421)])},
    {"id": "name", "label": "3.1 姓名", "type": "text", "required": True, "bbox": [492, 540, 758, 612]},
    {"id": "age", "label": "3.2 年齡", "type": "number", "required": True, "bbox": [912, 546, 1002, 612],
     "validate": {"min": 0, "max": 120}},
    {"id": "ticket_no", "label": "3.3 編號（傷票編號）", "type": "text", "required": True, "bbox": [1003, 598, 1605, 672],
     "validate": {"pattern": "^SIM-\\d{8}-\\d{3}$"}},
    {"id": "birthday", "dropout": False, "label": "3.4 生日（西元）", "type": "date", "bbox": [515, 598, 835, 668]},
    {"id": "id_no", "label": "3.5 身分證字號", "type": "text", "bbox": [712, 662, 1002, 726],
     "validate": {"pattern": "^[A-Z]\\d{9}$"}},
    {"id": "nationality", "label": "3.6 國籍(非本國籍)", "type": "text", "bbox": [1305, 662, 1578, 726]},
    {"id": "gcs", "dropout": False, "label": "4.意識(GCS)", "type": "text", "bbox": [460, 720, 642, 780]},
    {"id": "temp", "dropout": False, "label": "4.體溫", "type": "number", "bbox": [740, 720, 852, 780],
     "validate": {"min": 30, "max": 43, "decimals": 1}},
    {"id": "pulse", "label": "4.脈搏", "type": "number", "bbox": [968, 720, 1080, 780], "validate": {"min": 20, "max": 250}},
    {"id": "resp", "dropout": False, "label": "4.呼吸次數", "type": "number", "bbox": [1268, 720, 1382, 780], "validate": {"min": 4, "max": 60}},
    {"id": "bp_sys", "label": "4.血壓 收縮壓", "type": "number", "bbox": [460, 768, 596, 826],
     "validate": {"min": 50, "max": 260}},
    {"id": "bp_dia", "label": "4.血壓 舒張壓", "type": "number", "bbox": [603, 768, 740, 826],
     "validate": {"min": 20, "max": 160}},
    {"id": "spo2", "dropout": False, "label": "4.血氧", "type": "number", "bbox": [956, 768, 1075, 826], "validate": {"min": 50, "max": 100}},
    {"id": "pregnant", "label": "5.懷孕", "type": "checkbox_multi", "options": opts([("懷孕", "懷孕", 365, 829)])},
    {"id": "vaccine", "label": "5.疫苗接種", "type": "checkbox_multi", "options": opts([
        ("破傷風", "破傷風", 532, 872), ("其他", "其他", 695, 871)]),
     "other_text": {"option": "其他", "bbox": [785, 848, 1062, 906]}},
    {"id": "allergy", "label": "5.過敏史", "type": "checkbox_single", "options": opts([
        ("無", "無", 498, 915), ("有", "有", 595, 915)]),
     "other_text": {"option": "有", "bbox": [655, 893, 942, 950]}},
    {"id": "chronic", "label": "5.慢性疾病", "type": "checkbox_multi", "options": opts([
        ("糖尿病", "糖尿病", 532, 958), ("高血壓", "高血壓", 695, 958), ("長期透析", "長期透析", 857, 957),
        ("心衰竭", "心衰竭", 1049, 956), ("氣喘", "氣喘", 1212, 956), ("慢性阻塞性肺病", "慢性阻塞性肺病", 1340, 955),
        ("其他", "其他", 465, 1002)]),
     "other_text": {"option": "其他", "bbox": [556, 984, 962, 1044]}},
    {"id": "hpi", "label": "6.現病史", "type": "paragraph", "bbox": [350, 1040, 1040, 1472]},
    {"id": "body_map", "label": "6.人形圖標記", "type": "drawing", "bbox": [1042, 1040, 1562, 1470]},
    {"id": "dx_trauma", "label": "7.1 創傷", "type": "checkbox_multi",
     "options": opts([(str(n), l, x, y) for n, l, x, y in trauma])},
    {"id": "dx_nontrauma", "label": "7.2 非創傷", "type": "checkbox_multi",
     "options": opts([(str(n), l, x, y) for n, l, x, y in nontrauma]),
     "other_text": [{"option": "24", "bbox": [1420, 2018, 1562, 2064]},
                    {"option": "25", "bbox": [1345, 2052, 1562, 2100]}]},
]

# How the xlsx columns are produced from fields (see scripts/assemble.py for the ops).
export = [
    {"column": "傷票編號", "op": "value", "field": "ticket_no"},
    {"column": "救護隊", "op": "template", "field": "team", "template": "{}災難醫療救護隊"},
    {"column": "檢傷代碼", "op": "value", "field": "triage"},
    {"column": "檢傷分類", "op": "option_label", "field": "triage", "with_value": True},
    {"column": "醫師簽章", "op": "value", "field": "triage_signature"},
    {"column": "姓名", "op": "value", "field": "name"},
    {"column": "性別", "op": "value", "field": "sex"},
    {"column": "年齡", "op": "value", "field": "age"},
    {"column": "生日", "op": "value", "field": "birthday"},
    {"column": "身分證字號欄", "op": "value", "field": "id_no"},
    {"column": "國籍(非本國籍)", "op": "value", "field": "nationality"},
    {"column": "GCS", "op": "value", "field": "gcs"},
    {"column": "體溫(°C)", "op": "value", "field": "temp"},
    {"column": "脈搏(/min)", "op": "value", "field": "pulse"},
    {"column": "呼吸次數(/min)", "op": "value", "field": "resp"},
    {"column": "血壓(mmHg)", "op": "join", "fields": ["bp_sys", "bp_dia"], "sep": "/"},
    {"column": "血氧(%)", "op": "value", "field": "spo2"},
    {"column": "過去重要病史", "op": "checklist_text", "fields": ["pregnant", "vaccine", "allergy", "chronic"]},
    {"column": "現病史（中文）", "op": "value", "field": "hpi"},
    {"column": "主要初步診斷", "op": "checked_labels", "fields": ["dx_trauma", "dx_nontrauma"], "sep": "；"},
]

anchors = json.load(open(sys.argv[1]))
tpl = {
    "form_id": "medical_record_1_2",
    "name": "1.2醫療記錄單",
    "version": 1,
    "status": "draft",
    "reference_image": "blank.png",
    "size": [1646, 2331],
    "anchors": anchors,
    "fields": fields,
    "export": export,
}
open(sys.argv[2], "w").write(json.dumps(tpl, ensure_ascii=False, indent=1))
n_opts = sum(len(f.get("options", [])) for f in fields)
print(f"wrote {sys.argv[2]}: {len(fields)} fields, {n_opts} checkbox options, {len(anchors)} anchors")
