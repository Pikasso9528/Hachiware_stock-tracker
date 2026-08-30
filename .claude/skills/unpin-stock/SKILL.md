---
name: unpin-stock
description: Remove the pinned/observation flag from a stock in 監控股池 (watchout pool), so it goes back to the normal 5-consecutive-day-without-a-strong-signal auto-removal rule. Use when the user says "unpin <code>" or asks to stop specially protecting a stock from removal.
---

# 取消監控股池股票的觀察中標記（unpin）

取消某檔股票的「觀察中（pinned）」標記，讓它恢復套用一般的『連續 5 個交易日無偏強/極強 → 剔除』規則。**不會**把這檔股票從監控股池中直接移除——只是拿掉特殊保護；如果它目前的強度已經連續多日不強，之後執行 `update-pool` 或 `update-all` 時，就會依一般規則被標記警示、隔天仍未轉強才正式剔除。

## 用法

使用者輸入 `unpin <股票代號>`，例如：

```
unpin 8358
```

## 執行步驟

1. 在 `screenshots/` 目錄下執行：
   ```
   python data_processor.py --unpin <股票代號>
   ```
2. 這個指令會：
   - 找到該股票在監控股池中的紀錄，把觀察中標記拿掉
   - 重新輸出 `docs/today_summary.json`，前端監控股池分頁的「🔭 觀察中」徽章會消失
   - 若該股票目前根本不在監控股池中，會印出 `[WARN]` 並不做任何事
3. 執行完畢後，回報：是否成功取消標記，並提醒使用者這檔股票之後會恢復受一般 5 日剔除規則影響。

## 注意事項

- 這個技能只是拿掉「不受剔除規則影響」的保護，不會立刻把股票踢出池子；實際會不會被剔除，仍要看它接下來的強度表現與既有的剔除規則邏輯。
- 若想重新加回觀察中保護，改用 `pin-stock` 技能。
