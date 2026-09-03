---
name: update-group
description: Parse the group/<date>/overall.jpg sector list screenshot (top 10 sectors by percentage gain, from the app's "list mode" view) plus any other group/<date>/*.jpg per-sector detail list screenshots found in that folder, and refresh the 族群 tab of the 台股強勢股分析儀表板 dashboard. Each sector row can be clicked/expanded in the UI to show its top 10 component stocks, sourced from the matching detail screenshot. Use when the user says "update-group <date>" or asks to update the sector/group tab.
---

# 更新「族群」分頁

解析 `screenshots/group/<日期>/overall.jpg`（App 市場總覽 → 熱力圖 → **清單模式**畫面截圖，畫面左上角切換成「☰」清單圖示那個版本，不是色塊拼接的熱力圖模式），擷取每個族群列的名稱與日漲跌幅(%)，只保留漲幅 **大於 0%** 的族群，依漲幅由高到低排名，取**前 10 名**。接著再掃描同資料夾內其他截圖（點進某個族群後看到的「該族群成分股」清單，同樣要切換成清單模式），依標題辨識出所屬族群，附上該族群前 **10** 大個股排行——前端點擊某個族群列時會展開顯示。更新台股強勢股分析儀表板中的**族群**分頁，不會動到其他分頁的資料。

## 用法

使用者輸入 `update-group <日期>`，例如：

```
update-group 2026-08-28
```

日期格式須為 `YYYY-MM-DD`；程式雖然支援省略日期（會 fallback 到系統當下日期），但 Claude 執行時一律要明確帶入 `--date <日期>`，不要依賴這個 fallback——尤其午夜前後系統日期可能已經跳到隔天，但使用者説不定還在補前一天的截圖。日期不明確時先問清楚，不要自己假設今天／明天（詳見 README_SKILLS.txt 第7節）。

## 執行步驟

1. 確認截圖已放進 `screenshots/group/<日期>/`，且每張都要是 App 的**清單模式**畫面（不是熱力圖色塊模式，清單模式排版固定、辨識穩定很多）：
   - `overall.jpg`：市場總覽 → 熱力圖 → 清單模式（必要，檔名固定；欄位為「產業名稱／成交金額／日漲跌幅」）
   - 其他任意檔名的截圖：點進某一個族群後的成分股清單模式（選用，畫面最上方會顯示該族群名稱作為標題；欄位為「個股名稱／收盤價／成交金額／日漲跌幅」）。**不必每個族群都有明細截圖**——沒有的族群，前端會顯示「尚無資料」。
2. 在 `screenshots/` 目錄下執行：
   ```
   python data_processor.py --category group --date <日期>
   ```
   這個指令 OCR 呼叫次數比其他分頁多（每張截圖要逐列辨識名稱＋漲跌幅），單一日期全部跑完可能需要 1–2 分鐘，屬正常現象。
3. 這個指令會：
   - 對 `overall.jpg` 依固定列高逐列擷取族群名稱與日漲跌幅(%)（清單模式排版規則，用固定間距推算每列位置，比熱力圖色塊拼接可靠很多）；漲跌幅副行為紅字（漲）或綠字（跌），會先試紅色版再試綠色版二值化辨識並據此判斷正負號；名稱與內建的 `GROUP_SECTOR_WHITELIST` 模糊比對校正；篩出漲幅 > 0% 的前 10 名族群
   - 抓取當日三大法人買賣超資料，取得全市場股票中文名稱主檔，用來校正個股名稱
   - 對每張非 `overall.jpg` 的截圖：辨識標題文字比對出所屬族群，再依同樣的固定列高邏輯逐列擷取個股名稱與漲跌幅(%)，個股名稱與三大法人主檔模糊比對校正、取得代號，取前 10 名附到對應族群
   - 寫回 `docs/history/<日期>.json` 的 `group` 分頁（每個族群項目多一個 `stocks` 陣列），並重新輸出 `docs/today_summary.json`
4. 執行完畢後，回報：族群分頁最終有幾筆（若當天漲幅 > 0% 的族群不到 10 個則會較少）、其中幾筆有成分股明細，以及有沒有 `[WARN]`（族群或個股名稱比對信心不足、某張明細截圖辨識不出所屬族群等，通常發生在辨識信心較低的列，可忽略）。

## 注意事項

- 這個分頁依日期切換（不像監控股池是累加型），使用者在網頁上切換「資料日期」下拉選單時也會跟著換資料。
- 前端點擊族群列展開時，若該族群沒有對應明細截圖（`stocks` 為空陣列），會顯示「No more Information, please update」提示使用者補上該族群的明細截圖再重跑。
- 個股名稱與代號的比對信心不足時會保留原始 OCR 文字、不附代號（前端不會顯示可點擊連結），這是刻意設計，避免顯示錯誤但看起來煞有介事的股票連結。
- 每張截圖最下面幾列常被 App 內的直播/推播浮動小徽章擋住名稱（截圖本身的限制，非程式問題），該列漲跌幅仍會正確擷取，但名稱可能是亂碼——這種情況無法單靠重跑修正，需要使用者截圖時往上滑一點避開遮擋，或忽略該筆。
- 若使用者反映某族群名稱明顯錯誤，先確認它是否真的落在前 10 名內；若是，代表 `GROUP_SECTOR_WHITELIST` 可能少了這個族群名稱（例如新增了分類，如「照明」「散熱零組件」），需要把正確名稱加進 `data_processor.py` 裡的 `GROUP_SECTOR_WHITELIST` 常數，而不是單純重跑就能修正。
- 執行後若出現 `[WARN] 族群清單有一列...名稱與已知族群表比對信心不足` 或 `[WARN] 族群明細截圖...無法辨識所屬族群`：先看 OCR 辨識出的原始文字是不是一個合理、看得懂的真實產業/族群名稱（不是亂碼）。若是，直接視為白名單漏收錄，**不用另外詢問使用者**，把這個名稱加進 `data_processor.py` 的 `GROUP_SECTOR_WHITELIST` 常數，然後重跑一次 `update-group` 讓它套用；只有當 OCR 文字明顯是亂碼、無法判斷應該是哪個名稱時才需要請使用者確認或補截圖。
- 若當天 `overall.jpg` 不存在，這個分頁會是空的（技能不會報錯，只會輸出 0 筆）。
