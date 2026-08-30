---
name: update-group
description: Parse the group/<date>/overall.jpg sector heatmap screenshot (top 6 sectors by percentage gain) plus any other group/<date>/*.jpg per-sector detail heatmaps found in that folder, and refresh the 族群 tab of the 台股強勢股分析儀表板 dashboard. Each sector row can be clicked/expanded in the UI to show its top 6 component stocks, sourced from the matching detail screenshot. Use when the user says "update-group <date>" or asks to update the sector/group heatmap tab.
---

# 更新「族群」分頁

解析 `screenshots/group/<日期>/overall.jpg`（App 的市場總覽 → 熱力圖畫面截圖），擷取每個族群色塊的名稱與漲跌幅(%)，只保留漲幅 **大於 0%** 的族群，依漲幅由高到低排名，取**前 6 名**。接著再掃描同資料夾內其他截圖（點進某個族群後看到的「該族群成分股」熱力圖），依標題辨識出所屬族群，附上該族群前 6 大個股排行——前端點擊某個族群列時會展開顯示。更新台股強勢股分析儀表板中的**族群**分頁，不會動到其他分頁的資料。

## 用法

使用者輸入 `update-group <日期>`，例如：

```
update-group 2026-08-28
```

日期格式須為 `YYYY-MM-DD`；若使用者沒有帶日期，預設用今天的日期。

## 執行步驟

1. 確認截圖已放進 `screenshots/group/<日期>/`：
   - `overall.jpg`：整體族群熱力圖（必要，檔名固定）
   - 其他任意檔名的截圖：個別族群明細熱力圖（選用，每張對應「點進某一個族群」後看到的畫面，畫面最上方會顯示該族群名稱作為標題）。**不必每個族群都有明細截圖**——沒有的族群，前端會顯示「尚無資料」。
2. 在 `screenshots/` 目錄下執行：
   ```
   python data_processor.py --category group --date <日期>
   ```
3. 這個指令會：
   - 對 `overall.jpg` 做 OCR，正規化全形符號與偶發雜訊數字後的漲跌幅(%)，用座標就近配對找出每個色塊的族群名稱，與內建的 `GROUP_SECTOR_WHITELIST` 模糊比對校正，篩出漲幅 > 0% 的前 6 名族群
   - 抓取當日三大法人買賣超資料，取得全市場股票中文名稱主檔，用來校正個股名稱
   - 對每張非 `overall.jpg` 的截圖：辨識標題文字比對出所屬族群，再掃描色塊本體（改用藍色版二值化以因應白字＋大小混合字體），擷取該族群內個股名稱與漲跌幅(%)，個股名稱與三大法人主檔模糊比對校正、取得代號；比對不出來的股票色塊背景紅/綠色分量會用來校正漲跌正負號（比截圖上的 +/- 小符號更可靠），取前 6 名附到對應族群
   - 寫回 `docs/history/<日期>.json` 的 `group` 分頁（每個族群項目多一個 `stocks` 陣列），並重新輸出 `docs/today_summary.json`
4. 執行完畢後，回報：族群分頁最終有幾筆（正常應為 6 筆）、其中幾筆有成分股明細，以及有沒有 `[WARN]`（族群或個股名稱比對信心不足、某張明細截圖辨識不出所屬族群等，通常發生在辨識信心較低的色塊，可忽略）。

## 注意事項

- 這個分頁依日期切換（不像監控股池是累加型），使用者在網頁上切換「資料日期」下拉選單時也會跟著換資料。
- 前端點擊族群列展開時，若該族群沒有對應明細截圖（`stocks` 為空陣列），會顯示「No more Information, please update」提示使用者補上該族群的明細截圖再重跑。
- 個股名稱與代號的比對信心不足時會保留原始 OCR 文字、不附代號（前端不會顯示可點擊連結），這是刻意設計，避免顯示錯誤但看起來煞有介事的股票連結。
- 若使用者反映某族群名稱明顯錯誤，先確認它是否真的落在前 6 名內；若是，代表 `GROUP_SECTOR_WHITELIST` 可能少了這個族群名稱（例如熱力圖改版新增了分類），需要把正確名稱加進 `data_processor.py` 裡的 `GROUP_SECTOR_WHITELIST` 常數，而不是單純重跑就能修正。
- 若當天 `overall.jpg` 不存在，這個分頁會是空的（技能不會報錯，只會輸出 0 筆）。
