---
name: update-pool
description: Refresh the cumulative 監控股池 (watch pool) tab of the 台股強勢股分析儀表板 dashboard — applies the update/ folder's supplemental per-stock screenshots to the strength history, then re-runs the ❓ missing-data marking and the 5-consecutive-day-without-a-strong-signal removal rule. This tab accumulates over time and is NOT scoped to one date. Use when the user wants to refresh the watch pool independently.
---

# 更新「監控股池」分頁

監控股池是**累加型**分頁：股票一旦透過 `update-super` 被納入，就會持續留在池中，直到連續5個交易日都沒有出現偏強/極強才會被剔除。它不像其他四個分頁那樣對應某個 `screenshots/<日期>/pool/` 截圖資料夾，而是根據每檔股票的歷史強度紀錄自動維護。

## 執行步驟

1.（選用）把個別股票的補漏截圖放進 `screenshots/update/`，檔名須為股票代號開頭（例如 `8358.png`）——用於當某檔股票當天沒有 super 截圖、但你仍想更新它的相對強度歷史時使用。若沒有要補資料，這個資料夾留空即可。
2. 在 `screenshots/` 目錄下執行：
   ```
   python data_processor.py --category pool --date <日期>
   ```
   `<日期>` 預設為今天，格式 `YYYY-MM-DD`；這裡的日期只用來標記「今天沒有資料的股票」該記為❓，不影響監控池成員本身跨日期累積的性質。
3. 這個指令會依序：
   - 掃描 `screenshots/update/` 補漏截圖，更新對應股票的相對強度歷史
   - 對監控池中「今天完全沒有 super/update 截圖」的股票，標記強度為未更新（❓）
   - 套用「連續5個交易日無偏強/極強 → 標示警示，隔天仍未轉強才正式剔除」的規則
   - 重新輸出 `docs/today_summary.json`（監控股池分頁一律用最新狀態，不寫入 `docs/history/`）
4. 執行完畢後，回報：目前監控股池共有幾檔股票、有幾檔本次被標記⚠即將剔除、有幾檔被正式剔除。

## 注意事項

- 建議每天**最後**才執行這個分頁（或直接用 `update-all`），確保套用的是當天最終、完整的強度資料，剔除規則判斷才會準確；若在 `update-super` 之前就執行，尚未處理的股票當天會暫時被記成❓，等 `update-super` 或下次執行 `update-pool` 時會自動修正。
- 這個分頁沒有自己的股票代號清單截圖，新股票只會透過 `update-super` 自動加入，`update-pool` 本身不會新增監控池成員。
