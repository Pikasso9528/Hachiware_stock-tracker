---
name: update-group
description: Parse the group/<date>/overall.jpg sector heatmap screenshot and refresh the 族群 tab of the 台股強勢股分析儀表板 dashboard with the top 6 sectors ranked by percentage gain (only sectors above 0%). Use when the user says "update-group <date>" or asks to update the sector/group heatmap tab.
---

# 更新「族群」分頁

解析 `screenshots/group/<日期>/overall.jpg`（App 的市場總覽 → 熱力圖畫面截圖），擷取每個族群色塊的名稱與漲跌幅(%)，只保留漲幅 **大於 0%** 的族群，依漲幅由高到低排名，取**前 6 名**，更新台股強勢股分析儀表板中的**族群**分頁。不會動到其他分頁的資料。

## 用法

使用者輸入 `update-group <日期>`，例如：

```
update-group 2026-08-28
```

日期格式須為 `YYYY-MM-DD`；若使用者沒有帶日期，預設用今天的日期。

## 執行步驟

1. 確認熱力圖截圖已放進 `screenshots/group/<日期>/`，且檔名必須是 `overall.jpg`（只處理這一個檔案；同資料夾內其他檔名的截圖會被忽略，那些是族群個別頁面截圖，非本技能處理範圍）。
2. 在 `screenshots/` 目錄下執行：
   ```
   python data_processor.py --category group --date <日期>
   ```
3. 這個指令會：
   - 對熱力圖截圖做 OCR，把辨識出的文字依畫面座標分行，抓出所有漲跌幅(%)文字（含全形符號的變體也會正規化，例如 `﹢3﹒57%%` 會還原成 `+3.57%`）
   - 針對每個漲跌幅，往上（限制搜尋範圍內）找最接近、且 x 座標對得上的一行文字當作該色塊的族群名稱（熱力圖色塊大小不一，用座標就近配對，而非固定切欄）
   - 把辨識出的名稱與程式內建的已知族群名稱表（`GROUP_SECTOR_WHITELIST`）做模糊比對校正；比對信心不足時，會單獨重新裁切放大該色塊再辨識一次並再比對一次，兩次都對不上才保留原始 OCR 文字
   - 篩選出漲幅 > 0% 的族群，依漲幅由高到低排序，只取前 6 名並附上名次
   - 寫回 `docs/history/<日期>.json` 的 `group` 分頁，並重新輸出 `docs/today_summary.json`
4. 執行完畢後，回報：族群分頁最終有幾筆（正常應為 6 筆，若當天漲幅 > 0% 的族群不到 6 個則會較少），以及有沒有 `[WARN]`（某個色塊名稱與已知族群表比對信心不足、或完全辨識不出名稱而略過該筆——這些通常發生在漲幅較低、排不進前 6 名的色塊，可忽略）。

## 注意事項

- 這個分頁依日期切換（不像監控股池是累加型），使用者在網頁上切換「資料日期」下拉選單時也會跟著換資料。
- 若使用者反映某族群名稱明顯錯誤，先確認它是否真的落在前 6 名內；若是，代表 `GROUP_SECTOR_WHITELIST` 可能少了這個族群名稱（例如熱力圖改版新增了分類），需要把正確名稱加進 `data_processor.py` 裡的 `GROUP_SECTOR_WHITELIST` 常數，而不是單純重跑就能修正。
- 若當天 `overall.jpg` 不存在，這個分頁會是空的（技能不會報錯，只會輸出 0 筆）。
