---
name: update-pullback
description: Reprocess the 回檔型 (pullback) screenshot folder for a given date and refresh only that one tab in the 台股強勢股分析儀表板 dashboard, leaving 焦點監控/α動能/當日Super/監控股池 untouched. Use when the user wants to update just the pullback-list data.
---

# 更新「回檔型」分頁

只重新掃描 `screenshots/pullback/<日期>/` 資料夾內的截圖，更新台股強勢股分析儀表板中的**回檔型**分頁。不會動到焦點監控、α動能、當日Super、監控股池既有的資料。

## 執行步驟

1. 確認股票截圖已放進 `screenshots/pullback/<日期>/`（日期資料夾在分類資料夾底下，例如 `screenshots/pullback/2026-08-30/`；日期預設為今天，格式 `YYYY-MM-DD`，若使用者提到某個日期，就只處理那個日期資料夾內命名為該日期的截圖）。
2. 在 `screenshots/` 目錄下執行：
   ```
   python data_processor.py --category pullback --date <日期>
   ```
   若處理今天的資料可省略 `--date`。
3. 這個指令會依序：
   - 抓取當日三大法人買賣超資料，作為 OCR 代號有效性驗證與股票名稱/上市櫃別對照
   - 掃描 `pullback/` 資料夾內截圖，OCR 出當日名單
   - 依股票既有歷史強度資料（來自先前的 `update-super` / `update-pool`）組出「回檔型」分頁清單
   - 寫回 `docs/history/<日期>.json`，並重新輸出 `docs/today_summary.json`（其餘分頁資料原封不動）
4. 執行完畢後，回報：辨識出幾檔股票、有沒有 OCR 失敗或「無法辨識股票代號 / 找不到有效股票代號」等 `[WARN]` 警告訊息。

## 注意事項

- 這個分頁只提供「當日名單」，強度徽章／五日星星是**沿用**股票歷史資料，不是這裡算出來的；若當天尚未執行 `update-super`，強度會顯示上一次已知的資料。
- 若系統找不到可用的 Tesseract OCR，截圖將無法辨識，指令會印出 `[WARN]` 警告。
- 這種清單型截圖是一次抓出一整批候選代號、逐一跟當日有效代號比對，比對不到的候選會直接被丟棄、不會逐檔印出 `[WARN]`（只有整張截圖完全辨識失敗才會有警告），所以「某檔股票明明有截圖卻沒出現在清單裡」這種問題不會自動被抓到，通常是使用者發現才知道。若使用者反映某檔股票被漏掉：**不要請使用者確認截圖或改檔名**，改由 Claude 自己處理：
  1. 用 Read 工具開啟該截圖，在左側股票名稱/代號欄用視覺讀出該股票的正確代號。
  2. 用 `python` 呼叫 `data_processor.py` 的 `load_date_tabs(日期)` 讀出當天分頁快照，把該代號加進 `pullback` 清單對應的代號集合，呼叫 `build_tab_list(codes, db)` 重新組出清單，再用 `save_date_tabs` 存回（會一併重新輸出 `docs/today_summary.json`，不用整批重跑 OCR）。
  3. 回報時說明是哪張截圖、哪支股票被漏辨識、已經補上。
