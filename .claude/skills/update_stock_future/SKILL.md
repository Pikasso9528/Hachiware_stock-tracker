---
name: update_stock_future
description: Reprocess the stock_future_top screenshot folder for a given date (the "量大股期" leaderboard app screenshots) and refresh the 股期 tab of the 台股強勢股分析儀表板 dashboard with the ranked list. Use when the user says "update_stock_future <date>" or asks to update the stock-futures ranking tab.
---

# 更新「股期」分頁

重新掃描 `screenshots/stock_future_top/<日期>/` 資料夾內的「量大股期」排行榜截圖（App 的市場總覽 → 量大股期 → 多方畫面，可能因往下捲動而拆成好幾張截圖），更新台股強勢股分析儀表板中的**股期**分頁。不會動到其他分頁的資料。

## 用法

使用者輸入 `update_stock_future <日期>`，例如：

```
update_stock_future 2026-08-28
```

日期格式須為 `YYYY-MM-DD`；若使用者沒有帶日期，預設用今天的日期。

## 執行步驟

1. 確認排行榜截圖已放進 `screenshots/stock_future_top/<日期>/`（同一天若捲動拍了多張，全部放進同一個日期資料夾即可，程式會依檔名順序辨識，逐張串接排行）。
2. 在 `screenshots/` 目錄下執行：
   ```
   python data_processor.py --category stock_future --date <日期>
   ```
3. 這個指令會：
   - 抓取當日三大法人買賣超資料，用來驗證截圖 OCR 出的股票代號是否有效，並取得股票中文名稱／上市櫃別
   - 逐張截圖辨識每一列的股票代號與「期漲幅(%)」，以代號去重（保留第一次出現的位置），依出現順序組出完整排行（不是直接讀畫面上的排名數字——那一欄常辨識不穩，改用去重後的順序自己排名，較可靠）
   - 寫回 `docs/history/<日期>.json` 的 `stock_future` 分頁，並重新輸出 `docs/today_summary.json`
4. 執行完畢後，回報：排行榜共辨識出幾檔股票、有沒有 `[WARN]`（某一列代號或漲幅辨識失敗、已略過）。

## 注意事項

- 這個分頁依日期切換（不像監控股池是累加型），使用者在網頁上切換「資料日期」下拉選單時也會跟著換資料。
- 目前只處理「多方」（上漲方向）畫面；若使用者之後也想收錄「空方」排行，需要另外確認畫面截圖來源與紅/綠字顏色判斷邏輯，目前程式對綠字（下跌）已有基本容錯，但未實際驗證過。
- OCR 對截圖品質敏感，個別股票的期漲幅小數位偶爾會誤讀（例如 4.76 誤讀成 4.6），數字有明顯異常時建議回頭核對原始截圖。
