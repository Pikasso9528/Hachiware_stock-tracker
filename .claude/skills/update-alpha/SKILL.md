---
name: update-alpha
description: Reprocess the α動能 (alpha momentum) screenshot folder for a given date and refresh only that one tab in the 台股強勢股分析儀表板 dashboard, leaving 焦點監控/回檔型/當日Super/監控股池 untouched. Use when the user wants to update just the alpha-list data.
---

# 更新「α動能」分頁

只重新掃描 `screenshots/<日期>/alpha/` 資料夾內的截圖，更新台股強勢股分析儀表板中的**α動能**分頁。不會動到焦點監控、回檔型、當日Super、監控股池既有的資料。

## 執行步驟

1. 確認股票截圖已放進 `screenshots/<日期>/alpha/`（日期預設為今天，格式 `YYYY-MM-DD`；若使用者要處理別的日期，改用那個日期）。
2. 在 `screenshots/` 目錄下執行：
   ```
   python data_processor.py --category alpha --date <日期>
   ```
   若處理今天的資料可省略 `--date`。
3. 這個指令會依序：
   - 抓取當日三大法人買賣超資料，作為 OCR 代號有效性驗證與股票名稱/上市櫃別對照
   - 掃描 `alpha/` 資料夾內截圖，OCR 出當日名單
   - 依股票既有歷史強度資料（來自先前的 `update-super` / `update-pool`）組出「α動能」分頁清單
   - 寫回 `docs/history/<日期>.json`，並重新輸出 `docs/today_summary.json`（其餘分頁資料原封不動）
4. 執行完畢後，回報：辨識出幾檔股票、有沒有 OCR 失敗或「無法辨識股票代號 / 找不到有效股票代號」等 `[WARN]` 警告訊息。

## 注意事項

- 這個分頁只提供「當日名單」，強度徽章／五日星星是**沿用**股票歷史資料，不是這裡算出來的；若當天尚未執行 `update-super`，強度會顯示上一次已知的資料。
- 若系統找不到可用的 Tesseract OCR，截圖將無法辨識，指令會印出 `[WARN]` 警告。
