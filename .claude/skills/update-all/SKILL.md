---
name: update-all
description: Run a full 台股強勢股分析儀表板 refresh — updates all five tabs (焦點監控, α動能, 回檔型, 當日Super, 監控股池) in the correct order in one pass. Equivalent to running update-focus, update-alpha, update-pullback, update-super, update-pool in sequence. Use when the user wants one combined update instead of updating tabs individually.
---

# 一次更新全部五個分頁

依序完整跑過焦點監控、α動能、回檔型、當日Super、監控股池五個分頁的更新，等同於依序執行 `update-focus`、`update-alpha`、`update-pullback`、`update-super`、`update-pool` 這五個技能。順序很重要：Super 必須先跑，才能讓當日 super 截圖辨識出的股票即時納入監控池；監控股池必須最後跑，才能套用當天最終、完整的強度資料做5日剔除判斷。

## 執行步驟

1. 確認當天各截圖資料夾已備妥（依需要放入即可，缺哪個資料夾就代表那個分頁當天沒有新名單）：
   - `screenshots/<日期>/focus/`
   - `screenshots/<日期>/alpha/`
   - `screenshots/<日期>/pullback/`
   - `screenshots/<日期>/super/`
   - `screenshots/update/`（監控股池的補漏截圖，非日期資料夾）
2. 在 `screenshots/` 目錄下執行：
   ```
   python data_processor.py --date <日期>
   ```
   （不加 `--category` 時預設為 `all`，即依序更新全部五個分頁；若處理今天的資料可省略 `--date`。）
3. 這一步在底層依序執行的其實就是 `update-focus` → `update-alpha` → `update-pullback` → `update-super` → `update-pool` 各自的處理邏輯，最後統一寫出 `docs/history/<日期>.json` 與 `docs/today_summary.json`。
4. 執行完畢後，彙整回報五個分頁各自的檔數（焦點監控／α動能／回檔型／當日Super／監控股池），以及過程中出現的 `[WARN]` 警告（OCR 失敗、代號無法辨識等）。

## 何時改用單一分頁技能

若使用者只提到某一類截圖有更新（例如「我剛截了 alpha 的圖，幫我更新」），改叫對應的單一技能（`update-alpha` 等）即可，不需要跑這個全部更新的技能。
