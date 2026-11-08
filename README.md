# bulkocr-demo

這個工具把大量手寫的紙本表單掃描檔，整理成結構化的資料表。

流程是：PaddleOCR 辨識 → 以印刷字對齊頁面 → 依模板裁切欄位、偵測勾選框 → 在純前端的頁面上逐欄人工校正 → 匯出 xlsx。

- 線上展示（使用合成的模擬資料）：<https://ronnywang.github.io/bulkocr-demo/>
- 設計與執行說明：[PLAN.md](PLAN.md)
