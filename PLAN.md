# bulkocr — 大量手寫紙本表單整理工具

目標：已知表單（目前是「1.2醫療記錄單」）的大量手寫掃描檔 → 結構化資料表（xlsx），由人工做最後校正。
規模假設：一次處理數百份；校正用的介面都是純前端頁面，不需要後端。

## 流程

```
掃描檔 ──OCR(整頁)──▶ 印刷字錨點 ──仿射對齊──▶ 對齊後頁面 ──┬─▶ 勾選框：新增墨水比例
                                    │                         └─▶ 文字欄位：裁切 → OCR(去印刷字/原圖 兩版) → 正規化 + 驗證 → 旗標
                                    └─▶ 30 頁取中位數 = 空白表單（模板底圖）
模板 JSON（AI 起草 → 人工在編輯器確認）定義欄位位置、類型、驗證規則、匯出對應
```

1. **對齊**（`scripts/align.py`）：同一張表單的印刷字在每份上都相同，所以在多數頁面都出現、且文字完全一樣的 OCR 框就是錨點。用 RANSAC 擬合仿射轉換，把每頁對到參考頁。目前 30 頁的誤差都 < 2px。對齊後取中位數影像，手寫字會消失，得到乾淨的空白表單。
2. **模板**（`templates/medical_record_1_2.json`）：欄位、類型（text / number / date / paragraph / checkbox_single / checkbox_multi / drawing）、bbox、選項框、「勾選後補充文字」框、驗證規則、字典、`dropout` 設定、xlsx 匯出對應。初稿由 `scripts/draft_template_1_2.py` 產生（勾選框用連通元件自動偵測，文字區由 AI 依標籤位置放置）。
3. **模板編輯器**（`editor/template_editor.html`）：人工確認或調整每個框，逐欄標記「已確認」，最後匯出 JSON。
4. **抽取**（`scripts/extract.py`）
   - 勾選框：對齊頁減去空白表單後，算框內與框外延（勾常超出框，往右上方）的手寫墨水比例。分數 ≥ 0.04 算有勾；0.02–0.07 之間會標 `checkbox_unsure`。
   - 文字：bbox 裁切後，「去印刷字（dropout）」和「原圖」兩版都送 OCR。依欄位的 `dropout` 設定選主要版本；兩版結果不一致就標 `variants_disagree`。
   - 正規化：形近字母轉數字（只轉夾在數字中間的）、體溫自動補小數點、日期解析、傷票編號格式、字典比對（隊名）。超出範圍或格式不符都會標旗。
5. **評估**（`scripts/eval_extract.py`）：跟 `模擬醫療記錄單30份_資料表.xlsx` 比對。
6. **欄位校正頁**（`review/review.html`）：一次校正同一個欄位的所有份數。
   - 每列顯示裁切圖、可編輯的值、旗標、另一版 OCR 的建議值（點一下就採用）。預設「需檢查」的排前面。
   - 勾選欄位：在裁切圖上直接點框切換，或按數字鍵 1–9。
   - Enter 確認並跳到下一筆（中文輸入法選字時的 Enter 不會觸發），Shift+Enter 回上一筆；可以一鍵「確認所有無旗標項」。
   - 點頁碼會開整張對齊後的頁面，並標出欄位位置。
   - 進度存在瀏覽器 localStorage；「匯出校正結果」會下載 `corrections_<form_id>.json`，也可以再匯入（換電腦或多人分工時用）。
7. **匯出 xlsx**（`scripts/export_xlsx.py`）：合併機器結果和校正結果，依模板的 `export` 規則產生欄位。
   - 黃色＝有旗標但還沒確認，藍色＝人工修正過；最後一欄列出該列待確認的欄位。
   - 另外有「校正紀錄」工作表，逐欄列出機器值、最終值和狀態。

## 執行

OCR 服務的網址從環境變數 `PADDLEOCR_API_URL` 讀取；認證用 `PADDLEOCR_API_KEY`，或 `~/.config/bulkocr/token.json`。只需要 macOS 內建 Python 3 加上 numpy / Pillow / scipy / openpyxl，不需要另外安裝。

```bash
python3 scripts/ocr_batch.py 模擬醫療記錄單30份_手寫掃描檔 --model v6-medium      # 整頁 OCR → ocr_raw/
python3 scripts/align.py 模擬醫療記錄單30份_手寫掃描檔 ocr_raw/v6-medium work        # 對齊 + 空白表單
python3 scripts/draft_template_1_2.py work/anchors.json templates/medical_record_1_2.json
python3 scripts/extract.py templates/medical_record_1_2.json work/aligned work/blank.png work/extract
python3 scripts/eval_extract.py work/extract/results.json templates/medical_record_1_2.json 模擬醫療記錄單30份_資料表.xlsx
python3 scripts/export_xlsx.py templates/medical_record_1_2.json work/extract/results.json output/result.xlsx --corrections ~/Downloads/corrections_medical_record_1_2.json
python3 scripts/build_ocr_viewer.py 模擬醫療記錄單30份_手寫掃描檔 ocr_raw/v6-medium ocr_viewer.html
```

前端頁面：在專案根目錄執行 `python3 -m http.server 8765`，然後開啟：
- 模板編輯器：`http://localhost:8765/editor/template_editor.html`（也可以直接用瀏覽器開檔案，再手動選擇 JSON 和底圖）
- 欄位校正：`http://localhost:8765/review/review.html`（要透過 http 開啟；可以用 `?results=…&template=…&aligned=…` 指定其他批次）

線上展示（gh-pages）：<https://ronnywang.github.io/bulkocr-demo/>。這是一個單一 HTML 檔，資料都已經內嵌，不會連線到 OCR 服務。重新產生：

```bash
python3 scripts/build_demo.py output/demo.html --pages 10    # 圖片轉成 4 階灰度 PNG，約 5MB
```

本 repo 只放程式和模板，不含掃描檔、答案表和中間產物（`work/`、`ocr_raw/`、`output/`）。

## 目前結果（30 份模擬資料，v6-medium）

| 方法 | 欄位正確率 |
|---|---|
| 整頁 OCR + 文字規則（無模板） | 約 40–50%（長字串欄位） |
| 模板 + 對齊 + 裁切 OCR + 正規化 | **68.6%**（21 欄 × 30 份） |

- 勾選框：檢傷 100%、性別 97%、懷孕 100%、過敏 97%、診斷集合 87%。疫苗「其他」0% 是 **xlsx 答案本身的錯誤**：紙本是有勾的，xlsx 卻記為 □。慢性疾病「其他」也有同樣的情況。
- 數字和名字是主要的錯誤來源（脈搏、體溫、血壓、姓名、簽章約 37–57%）。
- **旗標品質**：錯誤值有 95%（132/139）被旗標或低信心（< 0.9）抓到；未標旗的值 96% 正確。目前約 59% 的文字值需要人工看一眼。
- 現病史：平均 CER 約 20%。有幾份是用英文寫的，對答案時取中、英文兩欄中較接近的一欄。

## 已知問題 / 下一步

- [x] 欄位校正頁、匯出 xlsx
- [ ] 人形圖（drawing）目前不進校正頁，之後可以把裁切圖附在匯出結果中。
- [ ] 一條指令跑完整個流程（`run_batch.py`：整頁 OCR → 對齊 → 抽取）。
- [ ] 答案表清理：疫苗 / 慢性病「其他」的勾選、現病史結尾的「（本紀錄為合成模擬資料）」字樣、英文書寫的現病史。
- [ ] 傷票編號：同一批通常連號而且日期相同，可以用批次一致性來校正或標旗。
- [ ] 姓名 / 簽章：如果有人員名冊，可以加字典比對。
- [ ] 本機 PaddleOCR（Apple Silicon）評估，取代遠端 API。
- [ ] 以後表單改版：加上四角定位標記 + QR code（表單 ID / 頁碼）。
