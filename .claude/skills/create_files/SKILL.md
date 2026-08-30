---
name: create_files
description: Create today's (or a given) date subfolder under each of the six category screenshot folders — screenshots/focus/<日期>/, screenshots/alpha/<日期>/, screenshots/pullback/<日期>/, screenshots/super/<日期>/, screenshots/stock_future_top/<日期>/, screenshots/group/<日期>/ — so screenshots for that date have somewhere to be dropped in before running update-focus/update-alpha/update-pullback/update-super/update_stock_future/update-group/update-all. Use when the user says "create_files <date>" or asks to set up folders for a new day's screenshots.
---

# 建立當日截圖資料夾

在 `screenshots/focus/`、`screenshots/alpha/`、`screenshots/pullback/`、`screenshots/super/`、`screenshots/stock_future_top/`、`screenshots/group/` 六個分類資料夾底下，各自建立一個以指定日期命名的空資料夾，供使用者把當天的截圖放進去，之後再用 `update-focus` / `update-alpha` / `update-pullback` / `update-super` / `update_stock_future` / `update-group` / `update-all` 處理。

## 用法

使用者輸入 `create_files <日期>`，例如：

```
create_files 2026-08-29
```

日期格式須為 `YYYY-MM-DD`；若使用者沒有帶日期，預設用今天的日期。

## 執行步驟

1. 從使用者的指令取出日期（`YYYY-MM-DD`），沒帶日期就用今天。
2. 在 `screenshots/` 目錄下，建立以下六個資料夾（若已存在則略過，不要覆蓋或清空既有內容）：
   ```
   mkdir -p focus/<日期> alpha/<日期> pullback/<日期> super/<日期> stock_future_top/<日期> group/<日期>
   ```
3. 完成後列出這六個資料夾確認建立成功，並回報給使用者：哪些是新建的、哪些原本就已經存在。

## 注意事項

- 這個技能只建立空資料夾，不會建立或搬動任何截圖檔案。
- `group/<日期>/` 資料夾建立後，使用者要把熱力圖截圖存成 `overall.jpg` 放進去，`update-group` 只會讀取這個檔名。
- 不要建立 `screenshots/update/` 的日期子資料夾——`update/` 資料夾是監控股池補漏截圖專用的，本身不分日期。檔名建議以股票代號命名（例如 `8358.png`），但不是手機截圖預設檔名也沒關係，`update-pool` 會自動從截圖內容 OCR 辨識代號。
- 建立的資料夾是本機個人截圖來源，`.gitignore` 已經設定會忽略 `focus|alpha|pullback|super|stock_future_top|group/<日期>/`，不需要額外處理版本控制。
