---
name: pin-stock
description: Manually add a stock code to 監控股池 (watchout pool) and mark it as pinned/observation so it is exempt from the 5-consecutive-day-without-a-strong-signal auto-removal rule. Use when the user says "pin <code>" or asks to keep watching a stock in the pool even though it's underperforming.
---

# 手動加入監控股池並標記為觀察中（pin）

把一檔股票加入監控股池，並標記為「觀察中（pinned）」——之後即使它連續 5 個交易日都沒有出現偏強/極強，也**不會**被自動剔除規則移除。適合用在使用者想持續盯著某檔股票、但不希望系統因為它一時弱勢就自動清掉的情境。

## 用法

使用者輸入 `pin <股票代號>`，例如：

```
pin 8358
```

日期為選用參數（`--date YYYY-MM-DD`），只影響「若這是全新加入的股票，納入日期要記成哪一天」；沒帶就用今天。

## 執行步驟

1. 在 `screenshots/` 目錄下執行：
   ```
   python data_processor.py --pin <股票代號>
   ```
   （或 `--pin <股票代號> --date <日期>` 指定納入日期）
2. 這個指令會：
   - 抓取當日三大法人買賣超資料，補上股票中文名稱與上市/上櫃別（若這檔股票之前從沒出現過）
   - 若該股票尚未在監控股池中，直接建立池成員紀錄（**不需要**它先出現在 super 截圖中）；若已在池中，只是補上觀察中標記
   - 清掉既有的「⚠ 即將剔除」警示（觀察中股票不適用剔除規則）
   - 重新輸出 `docs/today_summary.json`，前端監控股池分頁會立刻顯示「🔭 觀察中」徽章取代剔除警示
3. 執行完畢後，回報：這檔股票是新加入的還是原本就在池中、只是補上標記。

## 注意事項

- pin 這個動作本身**不會**提供每日強度資料——觀察中的股票，強度歷史還是要靠平常的 `update-super`（若它剛好出現在 super 截圖中）或把個股截圖放進 `screenshots/update/` 執行 `update-pool` 來更新，跟一般監控池股票的資料來源完全一樣，只是不會被剔除規則清掉。截圖檔名建議以代號開頭（例如 `2308.png`），但也可以直接用手機截圖預設檔名，程式會自動從截圖內容 OCR 辨識代號。
- 觀察中的股票如果好幾天完全沒有任何截圖來源可更新強度，當日強度會顯示❓（未更新），但依然會保留在池中。
- 若使用者想取消觀察標記、恢復一般剔除規則，改用 `unpin-stock` 技能。
