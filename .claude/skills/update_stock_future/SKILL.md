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

日期格式須為 `YYYY-MM-DD`；程式雖然支援省略日期（會 fallback 到系統當下日期），但 Claude 執行時一律要明確帶入 `--date <日期>`，不要依賴這個 fallback——尤其午夜前後系統日期可能已經跳到隔天，但使用者説不定還在補前一天的截圖。日期不明確時先問清楚，不要自己假設今天／明天（詳見 README_SKILLS.txt 第7節）。

## 執行步驟

1. 確認排行榜截圖已放進 `screenshots/stock_future_top/<日期>/`（同一天若捲動拍了多張，全部放進同一個日期資料夾即可）。**不要求檔名或拍攝順序等於畫面捲動順序**——程式會直接辨識每張截圖裡每一列印出的「排名」數字，依這個數字排序組出完整排行，所以就算截圖是倒著拍、檔名順序跟畫面順序對不上，結果還是正確的。
2. 在 `screenshots/` 目錄下執行：
   ```
   python data_processor.py --category stock_future --date <日期>
   ```
3. 這個指令會：
   - 抓取當日三大法人買賣超資料，用來驗證截圖 OCR 出的股票代號是否有效，並取得股票中文名稱／上市櫃別
   - 逐張截圖辨識每一列的**排名**、股票代號、與「期漲幅(%)」；同一截圖內排名是連續整數，個別列排名數字辨識失敗時會用相鄰列往前/往後推回；截圖最上/最下緣那一列常因裁切漏抓，會額外外推嘗試一列補救
   - 以代號去重（同一代號重複出現時保留排名較小的那筆），再依排名數字由小到大排序組出完整排行
   - 寫回 `docs/history/<日期>.json` 的 `stock_future` 分頁，並重新輸出 `docs/today_summary.json`
4. 執行完畢後，回報：排行榜共辨識出幾檔股票、有沒有 `[WARN]`（某一列排名/代號/漲幅辨識失敗、已略過）。

## 注意事項

- 這個分頁依日期切換（不像監控股池是累加型），使用者在網頁上切換「資料日期」下拉選單時也會跟著換資料。
- 目前只處理「多方」（上漲方向）畫面；若使用者之後也想收錄「空方」排行，需要另外確認畫面截圖來源與紅/綠字顏色判斷邏輯，目前程式對綠字（下跌）已有基本容錯，但未實際驗證過。
- OCR 對截圖品質敏感，個別股票的期漲幅小數位偶爾會誤讀（例如 4.76 誤讀成 4.6），數字有明顯異常時建議回頭核對原始截圖。
- 代號欄位是小字灰階數字，偶爾會有形近數字誤判（例如 4↔8、4↔9），而且誤判後的代號可能剛好也是別支股票的真實有效代號，驗證有效性也抓不出來，只有排行榜上的公司名稱跟代號對不起來才看得出問題（例如顯示「瑞軒 2489」但代號欄實際上是 2449 京元電子）。用公司名稱 OCR 做交叉比對已測試過不可靠（同樣是這個 App 字型在小尺寸下 Tesseract 辨識率很差），沒有簡單的程式修法。若使用者反映某一列的名稱看起來跟代號兜不起來，**直接用 Read 工具開啟該截圖用視覺核對**，確認正確代號後直接修正 `docs/history/<日期>.json`（與其他日期共用的 `docs/today_summary.json` 若是最新日期也要一併修正，或呼叫 `finalize_summary` 重新輸出），不用整批重跑 OCR。
