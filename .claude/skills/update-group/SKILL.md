---
name: update-group
description: Parse the group/<date>/overall.jpg sector heatmap screenshot and refresh the 族群 tab of the 台股強勢股分析儀表板 dashboard with sectors ranked by percentage gain (only sectors above 0%). Use when the user says "update-group <date>" or asks to update the sector/group heatmap tab.
---

# 更新「族群」分頁

解析 `screenshots/group/<日期>/overall.jpg`（App 的市場總覽 → 熱力圖畫面截圖），擷取每個族群色塊的名稱與漲跌幅(%)，只保留漲幅 **大於 0%** 的族群並依漲幅由高到低排名，更新台股強勢股分析儀表板中的**族群**分頁。不會動到其他分頁的資料。

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
   - 對熱力圖截圖做 OCR，把辨識出的文字依畫面座標分行，抓出所有「+d.dd%／-d.dd%」格式的漲跌幅文字
   - 針對每個漲跌幅，往上找最接近的一行文字當作該色塊的族群名稱（熱力圖色塊大小不一，用座標就近配對，而非固定切欄）
   - 篩選出漲幅 > 0% 的族群，依漲幅由高到低排序並附上名次
   - 寫回 `docs/history/<日期>.json` 的 `group` 分頁，並重新輸出 `docs/today_summary.json`
4. 執行完畢後，回報：漲幅 > 0% 的族群共有幾個，以及有沒有 `[WARN]`（某個色塊只認出漲跌幅、名稱辨識不出來、已略過該筆）。

## 注意事項

- 這個分頁依日期切換（不像監控股池是累加型），使用者在網頁上切換「資料日期」下拉選單時也會跟著換資料。
- 熱力圖下半部小色塊較密集，族群名稱常被截斷或誤讀（例如「連接元件」可能讀成亂碼、「IC-半導體」可能只讀出「IC-半導」），這是已知限制；上半部大色塊（例如「被動元件」「PCB-材料設備」「ABF」）辨識穩定。若使用者反映某族群名稱明顯錯誤或缺漏，建議請他們對照原始截圖手動確認，而不是重跑就能修正。
- 若當天 `overall.jpg` 不存在，這個分頁會是空的（技能不會報錯，只會輸出 0 筆）。
