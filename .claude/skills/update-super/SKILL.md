---
name: update-super
description: Reprocess the 當日Super screenshot folder (per-stock detail pages) for a given date. Refreshes the 當日Super tab AND updates every stock's relative-strength history — the single source of truth for the strength badges shown on all tabs — and auto-enrolls newly-seen stocks into 監控股池. Use when the user wants to update the super-list / relative-strength data independently.
---

# 更新「當日Super」分頁

重新掃描 `screenshots/super/<日期>/` 資料夾內的個股詳細頁截圖。這個分頁比較特別：它同時是**強度資料的唯一真實來源**——每次執行都會用截圖裡的「相對強度」歷史表，更新每檔股票的強度紀錄，而焦點監控／α動能／回檔型／監控股池顯示的「當日強度」與「五日強度」星星，全部都是讀這份紀錄，不是各分頁自己算的。

## 執行步驟

1. 確認個股詳細頁截圖已放進 `screenshots/super/<日期>/`（日期資料夾在分類資料夾底下，例如 `screenshots/super/2026-08-30/`；日期預設為今天，格式 `YYYY-MM-DD`，若使用者提到某個日期，就只處理那個日期資料夾內命名為該日期的截圖）。
2. 在 `screenshots/` 目錄下執行：
   ```
   python data_processor.py --category super --date <日期>
   ```
   若處理今天的資料可省略 `--date`。
3. 這個指令會依序：
   - 抓取當日三大法人買賣超資料，作為 OCR 代號有效性驗證與股票名稱/上市櫃別對照
   - 掃描 `super/` 資料夾截圖，辨識股票代號＋OCR 出「相對強度」歷史表
   - 把辨識出的強度逐日 upsert 進每檔股票的歷史紀錄
   - 當日出現在 super 資料夾的股票，若尚未在監控股池中，自動加入監控股池
   - 組出「當日Super」分頁清單，寫回 `docs/history/<日期>.json`，並重新輸出 `docs/today_summary.json`
4. 執行完畢後，回報：辨識出幾檔股票、有沒有 OCR 失敗或「無法辨識股票代號」等 `[WARN]` 警告訊息，以及有幾檔股票新納入監控股池。

## 注意事項

- 由於這裡更新的強度歷史會影響其他分頁的顯示，若當天同時要處理焦點監控／α動能／回檔型，建議**先跑這個分頁**（或直接用 `update-all` 一次跑完），其他分頁的「當日強度」才會是最新的。
- 建議在執行 `update-pool` 之前先執行這個分頁，監控股池的「連續5日無偏強/極強」剔除判斷才會用到當日最新的強度資料。
- 代號辨識已修正一個已知的 OCR 誤判（特定截圖在代號裁切區塊固定放大4倍時會被誤讀，現在會自動改試其他放大倍率），過去被 `[WARN] 無法辨識股票代號` 略過的截圖，重跑後有機會被正確辨識出來。
- 若執行後仍出現 `[WARN] 無法辨識股票代號`：這通常是該截圖代號文字對比度偏低（淺灰字疊深灰底），Tesseract 放大後把筆畫誤判成別的數字，不是裁切位置錯誤，重跑也不會自己修正。**不要請使用者手動改檔名**，改由 Claude 自己處理：
  1. 用 Read 工具直接開啟該張失敗截圖（`screenshots/super/<日期>/` 底下對應檔案），用視覺讀出畫面上公司名稱下方的股票代號（灰階數字，通常在公司名稱正下方、左右翻頁箭頭中間）。
  2. 把該截圖複製一份到 `screenshots/update/<代號>.<原副檔名>`（例如 `update/2449.jpg`）——**必須放進 `update/` 資料夾**，因為 `super/<日期>/` 資料夾的掃描邏輯完全不看檔名、一律重新 OCR，改檔名放在原資料夾沒有作用；只有 `update/` 資料夾才會直接信任檔名代號、略過代號 OCR。
  3. 若同一支股票當天已有其他截圖成功辨識出代號（例如重複拍了兩張同一檔股票的詳細頁），只需複製其中一張即可，不必重複。
  4. 全部處理完後執行一次 `update-pool`（或接下來反正會跑到的 `update-all`），讓 `update/` 補漏機制把這些代號的相對強度資料併入。
  5. 回報時列出每張失敗截圖對應到哪支股票（代號＋名稱），讓使用者可以核對。
