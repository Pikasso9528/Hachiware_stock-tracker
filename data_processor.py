# -*- coding: utf-8 -*-
"""
台股強勢股分析 - 資料處理核心
讀取每日分類截圖 -> OCR 辨識股票代號與清單 -> 從 super/update 個股詳細頁 OCR 出的
『相對強度』表作為強度唯一真實來源 -> 更新 tracker_db.json
-> 輸出瘦身後的 docs/today_summary.json 供 GitHub Pages 儀表板使用。

三大法人買賣超（外資/主力）資料僅用於：(1) 交叉驗證清單型截圖 OCR 出的候選代號是否為
當日真實有效的股票代號，(2) 提供股票中文名稱與上市/上櫃別對照。
"""
import argparse
import difflib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
# 專案根目錄本身即為「./screenshots」容器：YYYY-MM-DD 日期資料夾直接位於 ROOT 之下
SCREENSHOTS_DIR = ROOT
UPDATE_DIR = ROOT / "update"
DOCS_DIR = ROOT / "docs"
HISTORY_DIR = DOCS_DIR / "history"
TRACKER_DB_PATH = ROOT / "tracker_db.json"
SUMMARY_PATH = DOCS_DIR / "today_summary.json"

CATEGORIES = ["focus", "alpha", "pullback", "super"]
LIST_CATEGORIES = ["focus", "alpha", "pullback"]  # 清單型截圖（多檔股票／頁），僅用於辨識當日名單
# 股期／族群為排行榜型分頁（依日期切換，但沒有強度／五日星星欄位，
# 不納入 refresh_tab_strengths 的重算範圍）
RANKED_CATEGORIES = ["stock_future", "group"]
IMAGE_EXTS = (".png", ".jpg", ".jpeg")

STRONG_LEVELS = {"極強", "偏強"}
UNKNOWN_LEVEL = "未更新"

# 「強度」完全以 super / update 截圖內來源 App 自己算出的『相對強度』欄位為準，
# 不再用三大法人買賣超數字自行估算等級。
STRENGTH_LABELS = ["極強", "偏強", "中立", "偏弱", "弱"]
# 常見 OCR 誤判字元對照（依實測截圖校準）
_STRENGTH_CHAR_FIX = {"椏": "極", "偶": "偏", "便": "偏", "彊": "強", "弼": "弱"}


def nearest_strength_label(raw_text):
    """將 OCR 讀到的『相對強度指標』文字，校正並對應到五個標準等級之一。"""
    s = (raw_text or "").strip()
    if not s:
        return None
    for bad, good in _STRENGTH_CHAR_FIX.items():
        s = s.replace(bad, good)
    s = re.sub(r"[^極偏中立弱強]", "", s)
    if not s:
        return None
    if s in STRENGTH_LABELS:
        return s
    for lbl in STRENGTH_LABELS:
        if lbl in s or s in lbl:
            return lbl
    best = difflib.get_close_matches(s, STRENGTH_LABELS, n=1, cutoff=0)
    return best[0] if best else None

UA_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockTrackerBot/1.0"}

# ---------------------------------------------------------------------------
# OCR 初始化（優先使用 PATH 上的 tesseract，找不到則嘗試常見 Windows 安裝路徑）
# ---------------------------------------------------------------------------
OCR_AVAILABLE = False
try:
    import pytesseract
    from PIL import Image, ImageOps

    _TESSERACT_CANDIDATES = [
        "tesseract",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for _cmd in _TESSERACT_CANDIDATES:
        try:
            pytesseract.pytesseract.tesseract_cmd = _cmd
            pytesseract.get_tesseract_version()
            OCR_AVAILABLE = True
            break
        except Exception:
            continue
except ImportError:
    pass

if not OCR_AVAILABLE:
    print("[WARN] 找不到可用的 Tesseract OCR，將無法從截圖自動辨識股票代號。"
          "請安裝 https://github.com/UB-Mannheim/tesseract/wiki 或確認已加入 PATH。",
          file=sys.stderr)


# ---------------------------------------------------------------------------
# 三大法人買賣超資料（外資 / 主力）
# ---------------------------------------------------------------------------
def _num(v):
    if v is None:
        return 0
    s = str(v).replace(",", "").strip()
    if s in ("", "--", "nan", "None"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def fetch_twse_institutional(date_str):
    """上市 (TWSE) 三大法人買賣超日報。回傳 {code: {name, market, foreign_lots, main_lots}}"""
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    params = {"response": "json", "date": date_str, "selectType": "ALL"}
    out = {}
    try:
        r = requests.get(url, params=params, headers=UA_HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("stat") != "OK":
            return out
        fields = [f.strip() for f in data.get("fields", [])]
        idx = {name: i for i, name in enumerate(fields)}
        f_idx = idx.get("外陸資買賣超股數(不含外資自營商)")
        fd_idx = idx.get("外資自營商買賣超股數")
        trust_idx = idx.get("投信買賣超股數")
        dealer_idx = idx.get("自營商買賣超股數")
        for row in data.get("data", []):
            code = row[0].strip()
            name = row[1].strip()
            foreign = 0
            if f_idx is not None:
                foreign += _num(row[f_idx])
            if fd_idx is not None:
                foreign += _num(row[fd_idx])
            main = 0
            if trust_idx is not None:
                main += _num(row[trust_idx])
            if dealer_idx is not None:
                main += _num(row[dealer_idx])
            out[code] = {
                "name": name,
                "market": "TW",
                "foreign_lots": round(foreign / 1000),
                "main_lots": round(main / 1000),
            }
    except Exception as e:
        print(f"[WARN] TWSE 三大法人資料抓取失敗: {e}", file=sys.stderr)
    return out


def fetch_tpex_institutional():
    """上櫃 (TPEX) 三大法人買賣超（僅提供當日最新資料，無日期參數）。"""
    url = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
    out = {}
    try:
        r = requests.get(url, headers=UA_HEADERS, timeout=20)
        r.raise_for_status()
        rows = r.json()
        for row in rows:
            code = str(row.get("SecuritiesCompanyCode", "")).strip()
            name = str(row.get("CompanyName", "")).strip()
            if not code:
                continue
            foreign1 = foreign2 = trust = dealer = 0
            for k, v in row.items():
                nk = k.lower().replace(" ", "")
                if nk.endswith("difference"):
                    if "foreign" in nk and "mainland" in nk and "dealers" not in nk:
                        foreign1 = _num(v)
                    elif nk == "foreigndealers-difference":
                        foreign2 = _num(v)
                    elif "investmenttrust" in nk:
                        trust = _num(v)
                    elif nk == "dealers-difference":
                        dealer = _num(v)
            out[code] = {
                "name": name,
                "market": "TWO",
                "foreign_lots": round((foreign1 + foreign2) / 1000),
                "main_lots": round((trust + dealer) / 1000),
            }
    except Exception as e:
        print(f"[WARN] TPEX 三大法人資料抓取失敗: {e}", file=sys.stderr)
    return out


def fetch_institutional_master(date_str):
    """合併上市/上櫃三大法人買賣超資料，回傳當日有效股票代號主檔。"""
    master = fetch_twse_institutional(date_str.replace("-", ""))
    tpex = fetch_tpex_institutional()
    for code, info in tpex.items():
        master.setdefault(code, info)
    return master


# ---------------------------------------------------------------------------
# OCR：清單型截圖（focus / alpha / pullback）－ 從左側「股票名稱/代號」欄位擷取股票代號
# ---------------------------------------------------------------------------
def ocr_extract_codes(image_path):
    """回傳截圖中辨識出的候選股票代號集合（未經有效代號過濾）。"""
    if not OCR_AVAILABLE:
        return set()
    try:
        img = Image.open(image_path).convert("L")
        w, h = img.size
        left_col = img.crop((0, 0, max(1, int(w * 0.25)), h))
        inv = ImageOps.invert(left_col)
        inv = inv.point(lambda p: 255 if p > 90 else 0)
        inv = inv.resize((inv.width * 3, inv.height * 3), Image.LANCZOS)
        txt = pytesseract.image_to_string(
            inv, lang="eng", config="--psm 4 -c tessedit_char_whitelist=0123456789"
        )
        candidates = set()
        for line in txt.splitlines():
            line = line.strip()
            if re.fullmatch(r"\d{4,6}", line):
                candidates.add(line)
        return candidates
    except Exception as e:
        print(f"[WARN] OCR 失敗 ({image_path.name}): {e}", file=sys.stderr)
        return set()


def scan_category_folder(category, date_str, valid_codes):
    """截圖資料夾佈局為 screenshots/<分類>/<日期>/，例如 screenshots/focus/2026-08-30/。"""
    folder = SCREENSHOTS_DIR / category / date_str
    codes = set()
    if not folder.exists():
        return codes
    for img_path in sorted(folder.iterdir()):
        if img_path.suffix.lower() not in IMAGE_EXTS:
            continue
        raw = ocr_extract_codes(img_path)
        if valid_codes:
            codes |= {c for c in raw if c in valid_codes}
        else:
            # 三大法人資料抓取失敗時的保底：僅信任 4 碼候選
            codes |= {c for c in raw if len(c) == 4}
    return codes


# ---------------------------------------------------------------------------
# OCR：個股詳細頁截圖（super / update）－ 擷取股票代號 + 「相對強度」歷史表
# ---------------------------------------------------------------------------
def ocr_super_detail(image_path, valid_codes=None):
    """解析單檔股票的『相對強度』詳細頁截圖。
    回傳 (code, {"YYYY-MM-DD": 強度標籤, ...})，失敗則回傳 (None, {})。

    數字 OCR 對某些字型的「3」「2」等偶爾會誤判，因此擷取到的代號候選一律需與
    valid_codes（當日三大法人資料的真實代號主檔）比對，非有效代號則視為辨識失敗，
    避免將強度資料誤植到錯誤的股票上。
    """
    if not OCR_AVAILABLE:
        return None, {}
    try:
        img = Image.open(image_path)
        w, h = img.size

        code = None
        for x0, x1 in ((0.42, 0.58), (0.35, 0.65), (0.30, 0.70)):
            crop = img.crop((int(w * x0), int(h * 0.085), int(w * x1), int(h * 0.105))).convert("L")
            inv = ImageOps.invert(crop)
            # 4x 放大是最常見的最佳解析度，但少數截圖在剛好 4x 時會被 Tesseract 誤判
            # 多插入一個數字（依實測校準），故失敗時改試 3x／5x 再放棄。
            for scale in (4, 3, 5):
                scaled = inv.resize((inv.width * scale, inv.height * scale), Image.LANCZOS)
                txt = pytesseract.image_to_string(
                    scaled, lang="eng", config="--psm 6 -c tessedit_char_whitelist=0123456789"
                )
                candidates = re.findall(r"\d{4,6}", txt)
                if valid_codes:
                    match = next((c for c in candidates if c in valid_codes), None)
                else:
                    match = candidates[0] if candidates else None
                if match:
                    code = match
                    break
            if code:
                break

        table_crop = img.crop((0, int(h * 0.52), int(w * 0.62), h)).convert("L")
        inv2 = ImageOps.invert(table_crop)
        inv2 = inv2.point(lambda p: 255 if p > 90 else 0)
        inv2 = inv2.resize((inv2.width * 2, inv2.height * 2), Image.LANCZOS)
        table_txt = pytesseract.image_to_string(inv2, lang="chi_tra+eng", config="--psm 6")

        labels = {}
        for line in table_txt.splitlines():
            m = re.search(r"(20\d{6})", line)
            if not m:
                continue
            raw_date = m.group(1)
            date_str = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
            rest = re.sub(r"[\d.\s,%\-]", "", line[m.end():])
            label = nearest_strength_label(rest)
            if label:
                labels[date_str] = label

        if code is None:
            print(f"[WARN] 無法辨識股票代號 ({image_path.name})，請確認截圖或改放到 update/代號.png",
                  file=sys.stderr)
        return code, labels
    except Exception as e:
        print(f"[WARN] 個股詳細頁 OCR 失敗 ({image_path.name}): {e}", file=sys.stderr)
        return None, {}


def scan_super_folder(date_str, valid_codes):
    """回傳 (codes, detail)：codes 為當日 super 資料夾辨識出的股票代號集合，
    detail 為 {code: {date: 強度標籤}} 的相對強度歷史表彙整結果。
    截圖資料夾佈局為 screenshots/super/<日期>/，例如 screenshots/super/2026-08-30/。"""
    folder = SCREENSHOTS_DIR / "super" / date_str
    codes = set()
    detail = {}
    if not folder.exists():
        return codes, detail
    for img_path in sorted(folder.iterdir()):
        if img_path.suffix.lower() not in IMAGE_EXTS:
            continue
        code, labels = ocr_super_detail(img_path, valid_codes)
        if not code or not labels:
            continue
        codes.add(code)
        detail.setdefault(code, {}).update(labels)
    return codes, detail


def scan_update_folder(valid_codes=None):
    """補漏資料夾：內容比照 super 的個股詳細頁格式。檔名若已是股票代號開頭
    （例如 8358.png）就直接採信檔名，只取相對強度表；檔名不是代號格式時
    （例如手機截圖預設檔名 S__12345678_0.jpg），改用截圖內容 OCR 辨識代號
    （與 valid_codes 比對降低誤判），讓使用者不需要手動改檔名。
    同一個代號若出現在多張截圖（例如同一支股票拍了新舊兩張），會把各自的
    相對強度表合併（同一天以較晚處理到的那張為準），而不是整份覆蓋，避免
    其中一張涵蓋的日期範圍被另一張蓋掉；並印出提醒，讓使用者知道有重複。
    回傳 (paths, detail)：paths 為 {code: Path}（多張時取最後處理到的那張），
    detail 為 {code: {date: 強度標籤}}。"""
    paths = {}
    detail = {}
    if not UPDATE_DIR.exists():
        return paths, detail
    for img_path in sorted(UPDATE_DIR.iterdir()):
        if img_path.suffix.lower() not in IMAGE_EXTS:
            continue
        m = re.match(r"(\d{4,6})", img_path.stem)
        if m:
            code = m.group(1)
            _, labels = ocr_super_detail(img_path)  # 檔名已是代號，這裡僅取相對強度表
        else:
            code, labels = ocr_super_detail(img_path, valid_codes)  # 檔名非代號格式，改由截圖內容辨識代號
            if not code:
                print(f"[WARN] update/ 補漏截圖 {img_path.name} 檔名非股票代號格式，"
                      f"且無法從截圖內容辨識出代號，已略過（也可手動將檔名改為代號.副檔名，例如 2308.jpg）",
                      file=sys.stderr)
                continue
        if code in paths:
            print(f"[WARN] update/ 補漏截圖 {img_path.name} 與 {paths[code].name} 都對應到代號 {code}，"
                  f"兩張的相對強度表會合併，建議確認是否為重複截圖，只留其中一張", file=sys.stderr)
        paths[code] = img_path
        if labels:
            detail.setdefault(code, {}).update(labels)
    return paths, detail


# ---------------------------------------------------------------------------
# OCR：股期排行榜截圖（stock_future_top）－ 擷取排行、股票代號、期漲幅(%)
# ---------------------------------------------------------------------------
def _threshold_channel(crop, channel=None, thresh=150, scale=4):
    """裁切後二值化＋放大，供單行數字/文字辨識使用。
    channel=None 取灰階（白字，用於排名/代號欄）；channel=0/1/2 取 R/G/B 單一色版
    （用於紅字＝多方上漲、綠字＝空方下跌的期漲幅(%)欄，避免與深色背景灰階值太接近）。"""
    band = crop.convert("L") if channel is None else crop.split()[channel]
    th = band.point(lambda p: 255 if p > thresh else 0)
    return th.resize((th.width * scale, th.height * scale), Image.LANCZOS)


def _ocr_single_line(img, whitelist):
    """先試 psm7（單行），若辨識不到再退而試 psm6，依實測截圖校準。"""
    for psm in (7, 6):
        txt = pytesseract.image_to_string(
            img, lang="eng", config=f"--psm {psm} -c tessedit_char_whitelist={whitelist}"
        ).strip()
        if txt:
            return txt
    return ""


def _future_row_centers(img, w, h):
    """量大股期排行榜每一列的「期量比」欄固定顯示 100.00，以此定位每列中心 y 座標，
    比直接辨識排名數字更穩定（實測排名欄在整欄一次 OCR 時常漏掉最後一列）。"""
    band = img.crop((int(w * 0.42), int(h * 0.15), int(w * 0.60), int(h * 0.95)))
    g = band.convert("L")
    inv = ImageOps.invert(g)
    inv = inv.point(lambda p: 255 if p > 90 else 0)
    inv = inv.resize((inv.width * 4, inv.height * 4), Image.LANCZOS)
    data = pytesseract.image_to_data(
        inv, lang="eng", config="--psm 6 -c tessedit_char_whitelist=0123456789.",
        output_type=pytesseract.Output.DICT,
    )
    centers = []
    for i, t in enumerate(data["text"]):
        t = t.strip()
        if re.fullmatch(r"\d{2,3}\.\d{2}", t):
            top = data["top"][i] / 4 + int(h * 0.15)
            height = data["height"][i] / 4
            centers.append(top + height / 2)
    centers.sort()
    return centers


def _future_row_fields(img, w, center, row_h):
    """在單一列的 y 範圍內，分別裁切「排名」「代號」與「期漲幅(%)」三個欄位辨識。
    排名欄以截圖上實際印出的數字為準（而非掃描順序），避免多張截圖的拍攝／檔名順序
    與畫面捲動順序不一致時，把排行順序完全打亂。"""
    y0, y1 = int(center - row_h * 0.42), int(center + row_h * 0.42)
    rank_crop = img.crop((int(w * 0.02), y0, int(w * 0.17), y1))
    code_crop = img.crop((int(w * 0.20), int(center - 5), int(w * 0.34), y1))
    pct_crop = img.crop((int(w * 0.60), y0, int(w * 0.84), y1))

    rank_txt = _ocr_single_line(_threshold_channel(rank_crop), "0123456789")
    code = _ocr_single_line(_threshold_channel(code_crop), "0123456789")

    pct_txt = _ocr_single_line(_threshold_channel(pct_crop, channel=0), "0123456789.")  # 紅字：上漲
    sign = 1
    if not pct_txt:
        pct_txt = _ocr_single_line(_threshold_channel(pct_crop, channel=1), "0123456789.")  # 綠字：下跌
        sign = -1

    pct = sign * float(pct_txt) if re.fullmatch(r"\d{1,3}\.\d{1,2}", pct_txt) else None
    code = code if re.fullmatch(r"\d{4,6}", code) else None
    rank = int(rank_txt) if re.fullmatch(r"\d{1,3}", rank_txt) else None
    return rank, code, pct


def scan_stock_future_folder(date_str, valid_codes):
    """掃描 stock_future_top/<日期>/ 內的「量大股期」排行榜截圖（可能為捲動後的多張截圖，
    不保證檔名／拍攝順序等於畫面捲動順序）。逐張辨識每一列的排名、股票代號與期漲幅(%)，
    以代號去重（同一代號重複出現時保留排名較小的那筆），再依排名數字由小到大排序，
    回傳 [(code, pct_change), ...]。"""
    folder = SCREENSHOTS_DIR / "stock_future_top" / date_str
    rows = {}  # code -> (rank, pct)
    if not folder.exists():
        return []
    for img_path in sorted(folder.iterdir()):
        if img_path.suffix.lower() not in IMAGE_EXTS:
            continue
        img = Image.open(img_path)
        w, h = img.size
        centers = _future_row_centers(img, w, h)
        if len(centers) < 2:
            continue
        diffs = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]
        row_h = sum(diffs) / len(diffs)
        # 螢幕邊緣（截圖最上/最下）那一列常因裁切／解析度差異，「期量比」欄位的
        # 固定格式數字沒被完整偵測到，導致整列漏抓；用列高外推補一列上緣／下緣
        # 候選位置，只要落在圖片範圍內就一併嘗試辨識——這只是「猜測可能還有一列」，
        # 猜測位置經常根本沒有列（已經是畫面第一列/最後一列），辨識不到東西是正常情況。
        extrapolated = set()
        if centers[0] - row_h > h * 0.05:
            centers.insert(0, centers[0] - row_h)
            extrapolated.add(0)
        if centers[-1] + row_h < h * 0.98:
            centers.append(centers[-1] + row_h)
            extrapolated.add(len(centers) - 1)

        raw = [list(_future_row_fields(img, w, c, row_h)) for c in centers]
        # 同一張截圖內排名是連續整數，個別列的排名數字辨識失敗時，用相鄰列的排名
        # 往前/往後推回（避免整列因為單一欄位辨識失敗而被捨棄）。
        for i, (rank, code, pct) in enumerate(raw):
            if rank is not None:
                continue
            for j in range(i + 1, len(raw)):
                if raw[j][0] is not None:
                    raw[i][0] = raw[j][0] - (j - i)
                    break
            else:
                for j in range(i - 1, -1, -1):
                    if raw[j][0] is not None:
                        raw[i][0] = raw[j][0] + (i - j)
                        break

        for i, (rank, code, pct) in enumerate(raw):
            if not code or pct is None or rank is None:
                if i not in extrapolated:
                    print(f"[WARN] 股期排行截圖 {img_path.name} 有一列無法辨識排名/代號/期漲幅，已略過",
                          file=sys.stderr)
                continue
            if valid_codes and code not in valid_codes:
                continue
            if code in rows and rows[code][0] <= rank:
                continue
            rows[code] = (rank, pct)
    return [(code, pct) for code, (rank, pct) in sorted(rows.items(), key=lambda kv: kv[1][0])]


def build_stock_future_list(date_str, master, db):
    valid_codes = set(master.keys())
    rows = scan_stock_future_folder(date_str, valid_codes)
    ensure_stock_entries(db, [code for code, _ in rows], master)
    items = []
    for i, (code, pct) in enumerate(rows):
        entry = db["stocks"].get(code, {})
        items.append({
            "rank": i + 1,
            "code": code,
            "name": entry.get("name", "—"),
            "market": entry.get("market", "TW"),
            "pct_change": pct,
        })
    return items


# ---------------------------------------------------------------------------
# OCR：族群清單截圖（group/<日期>/）－ 擷取族群 / 個股名稱與日漲跌幅(%)
#
# App 這兩個畫面（市場總覽→熱力圖→清單模式；點進單一族群後的成分股→清單模式）都是
# 排版一致的清單，而非熱力圖色塊，逐列位置可直接用固定間距推算，比色塊拼接的
# treemap 排版簡單、可靠得多。
# ---------------------------------------------------------------------------
_GROUP_NOISE_RE = re.compile(r"[﹣﹍‥。﹒｜|:：'’,，)）(（\[\]{}『』﹚﹛ˍ︰…=~`^\s]+")
_GROUP_PCT_VALUE_RE = re.compile(r"^([+-])?(\d+)\.(\d{2,})")
GROUP_TOP_N = 10  # 族群分頁只顯示漲幅前 N 名
GROUP_DETAIL_TOP_N = 10  # 每個族群展開後只顯示成分股前 N 名
GROUP_DETAIL_NAME_CUTOFF = 0.6

# 依實測截圖校準：市場總覽（overall.jpg）清單第一列資料距圖片頂端、族群明細清單
# 第一列資料距圖片頂端的相對位置不同（總覽多一段產業彙總列，明細少一段），因此
# 分開校準；每列高度與漲跌幅副行相對列頂端的垂直位移則兩種畫面相同。
GROUP_OVERALL_ROW0_FRAC = 505 / 1884
GROUP_DETAIL_ROW0_FRAC = 416 / 1884
GROUP_ROW_HEIGHT_FRAC = 137.7 / 1884
GROUP_PCT_Y_OFFSET = 28
GROUP_PCT_BAND_HEIGHT = 35
GROUP_LIST_MAX_ROWS = 12  # 抓多一點再各自篩選/排序取前 N，容錯漏抓或誤判的列

# 依實測截圖校準的已知族群名稱表：清單文字偶爾因字體、截圖壓縮而 OCR 失準，因此對
# 辨識結果做「像 STRENGTH_LABELS 一樣的模糊比對校正」，snap 到最接近的已知名稱；
# 若比對信心不足則保留原始 OCR 文字，讓使用者自行核對。
GROUP_SECTOR_WHITELIST = [
    "IC-代工", "IC-製造", "被動元件", "IC-封測", "PCB-製造", "PCB-材料設備", "記憶體製造", "ABF",
    "光學鏡片", "IC-設計", "晶圓材料", "EMS", "LCD-TF...", "IC-半導體", "連接元件", "照明",
    "金控", "儀器設備...", "塑膠", "電機", "電源供應器", "IP/ASIC", "航運", "通訊設備", "散熱零組件",
    "半導體元件", "高爾夫球", "主機板", "遊戲", "記憶體 IC 設計", "網通",
    "工業電腦", "LED照明及光電",
]


def _normalize_group_pct(raw):
    """OCR 常把 +/- 與小數點辨識成全形變體（﹢﹣﹒），偶爾還會夾帶雜訊數字，
    依「漲跌幅固定顯示兩位小數」的版面特性做正規化；超出合理範圍（±15%）甚多者
    視為 OCR 雜訊，回傳 None。"""
    s = raw.strip().replace("﹢", "+").replace("﹣", "-").replace("．", ".").replace("﹒", ".").replace("％", "%")
    if "%" not in s:
        return None
    m = _GROUP_PCT_VALUE_RE.match(s)
    if not m:
        return None
    sign, intpart, frac = m.groups()
    frac = frac[:2]
    val = float(f"{intpart}.{frac}")
    if val > 15 and len(intpart) > 1:
        # OCR 偶爾會在整數部分多讀出一個雜訊數字（例如 +4.31% 誤讀成 44.31%），
        # 去掉最前面那一位再試一次，仍在合理範圍內才採用。
        retry = float(f"{intpart[1:]}.{frac}")
        if retry <= 15:
            val = retry
    if sign == "-":
        val = -val
    return val if abs(val) <= 15 else None


def _snap_to_sector_name(name):
    if not name:
        return None, 0.0
    match = difflib.get_close_matches(name, GROUP_SECTOR_WHITELIST, n=1, cutoff=0)
    if not match:
        return None, 0.0
    return match[0], difflib.SequenceMatcher(None, name, match[0]).ratio()


def _ocr_sector_detail_title(img):
    """族群明細截圖最上方置中的白色族群名稱標題，字體大、位置固定，比清單內文字更好辨識。"""
    w, h = img.size
    crop = img.crop((int(w * 0.10), int(h * 0.055), int(w * 0.90), int(h * 0.115)))
    g = crop.convert("L")
    big = g.resize((g.width * 3, g.height * 3), Image.LANCZOS)
    txt = pytesseract.image_to_string(big, lang="chi_tra+eng", config="--psm 7").strip()
    return _GROUP_NOISE_RE.sub("", txt.replace("\n", ""))


def _ocr_group_row_name(img, box):
    l, t, r, b = box
    crop = img.crop((int(l), int(t), int(r), int(b)))
    g = crop.convert("L")
    big = g.resize((g.width * 3, g.height * 3), Image.LANCZOS)
    txt = pytesseract.image_to_string(big, lang="chi_tra+eng", config="--psm 7").strip()
    return _GROUP_NOISE_RE.sub("", txt.replace("\n", ""))


def _ocr_group_row_pct(img, box):
    """漲跌幅副行為紅字（漲）或綠字（跌），灰階常因對比不足漏辨識，改用色版二值化：
    先試紅色版，抓不到再試綠色版並判定為負值（比 OCR 認出的 +/- 小三角圖示更可靠）。"""
    l, t, r, b = box
    crop = img.crop((int(l), int(t), int(r), int(b)))
    for channel_idx in (0, 1):
        ch = crop.split()[channel_idx]
        th = ch.point(lambda p: 255 if p > 150 else 0)
        big = th.resize((th.width * 4, th.height * 4), Image.LANCZOS)
        txt = _ocr_single_line(big, "0123456789.%")
        if not txt:
            continue
        val = _normalize_group_pct(txt if "%" in txt else txt + "%")
        if val is not None:
            return -abs(val) if channel_idx == 1 else abs(val)
    return None


def _scan_group_list_rows(img, row0_frac, name_x_frac, max_rows=GROUP_LIST_MAX_ROWS):
    """依固定列高逐列擷取清單畫面（族群總覽或族群明細皆適用），回傳
    [{"name": 原始 OCR 名稱, "pct_change": 漲跌幅}, ...]，抓不到漲跌幅的列直接略過
    （名稱可能因被 UI 浮動元件遮擋等因素辨識失敗，仍保留該列、名稱為空字串）。"""
    w, h = img.size
    row0_top = h * row0_frac
    row_h = h * GROUP_ROW_HEIGHT_FRAC
    rows = []
    for i in range(max_rows):
        top = row0_top + i * row_h
        if top + row_h > h * 0.97:
            break
        name_box = (name_x_frac[0] * w, top - row_h * 0.08, name_x_frac[1] * w, top + row_h * 0.30)
        pct_box = (w * 0.76, top + GROUP_PCT_Y_OFFSET - 6, w * 0.97, top + GROUP_PCT_Y_OFFSET + GROUP_PCT_BAND_HEIGHT)
        pct = _ocr_group_row_pct(img, pct_box)
        if pct is None:
            continue
        name = _ocr_group_row_name(img, name_box)
        rows.append({"name": name, "pct_change": pct})
    return rows


def scan_group_overall(date_str):
    """解析 group/<日期>/overall.jpg（App 市場總覽→熱力圖→清單模式截圖），擷取每個
    產業／族群列的名稱與日漲跌幅(%)，僅保留漲幅 > 0% 的族群，依漲幅由高到低排序，
    取前 GROUP_TOP_N 名並附上名次。名稱與 GROUP_SECTOR_WHITELIST 模糊比對校正，
    比對信心不足則保留原始 OCR 文字，讓使用者自行核對。"""
    path = SCREENSHOTS_DIR / "group" / date_str / "overall.jpg"
    if not path.exists():
        return []
    img = Image.open(path)
    rows = _scan_group_list_rows(img, GROUP_OVERALL_ROW0_FRAC, (0.0, 0.35))

    results = []
    for r in rows:
        match, score = _snap_to_sector_name(r["name"])
        name = match if (match and score >= 0.6) else r["name"]
        if not name:
            print(f"[WARN] 族群清單有一列（漲跌幅 {r['pct_change']:+.2f}%）名稱無法辨識，已略過",
                  file=sys.stderr)
            continue
        if not (match and score >= 0.6):
            print(f"[WARN] 族群清單有一列（漲跌幅 {r['pct_change']:+.2f}%）名稱與已知族群表比對信心不足，"
                  f"保留原始辨識結果 {name!r}，建議人工核對", file=sys.stderr)
        results.append({"sector": name, "pct_change": r["pct_change"]})

    results = [r for r in results if r["pct_change"] > 0]
    results.sort(key=lambda r: -r["pct_change"])
    results = results[:GROUP_TOP_N]
    for i, r in enumerate(results):
        r["rank"] = i + 1
    return results


def scan_group_sector_details(date_str, master):
    """掃描 group/<日期>/ 底下除 overall.jpg 外的個別族群明細截圖（點進某一族群後看到
    的成分股清單），依標題辨識所屬族群，擷取該族群內個股名稱與日漲跌幅(%)、與三大
    法人主檔模糊比對校正取得代號，取前 GROUP_DETAIL_TOP_N 名，回傳
    {族群名稱: [個股排行, ...]}，供前端點擊某個族群時展開其成分股排行。
    若某個族群沒有對應的明細截圖，該族群不會出現在回傳結果中——前端遇到查無資料的
    族群時會顯示「No more Information, please update」。"""
    folder = SCREENSHOTS_DIR / "group" / date_str
    detail = {}
    if not folder.exists():
        return detail

    name_to_code = {}
    for code, info in (master or {}).items():
        name_to_code.setdefault(info["name"], (code, info["market"]))
    master_names = list(name_to_code.keys())

    for img_path in sorted(folder.iterdir()):
        if img_path.suffix.lower() not in IMAGE_EXTS or img_path.name.lower() == "overall.jpg":
            continue
        img = Image.open(img_path)
        title = _ocr_sector_detail_title(img)
        sector, score = _snap_to_sector_name(title)
        if not sector or score < 0.5:
            print(f"[WARN] 族群明細截圖 {img_path.name} 無法辨識所屬族群（標題辨識為 {title!r}），已略過",
                  file=sys.stderr)
            continue

        rows = _scan_group_list_rows(img, GROUP_DETAIL_ROW0_FRAC, (0.0, 0.30))
        stocks = []
        for r in rows:
            raw_name = r["name"]
            match = None
            if len(raw_name) >= 2 and master_names:
                close = difflib.get_close_matches(raw_name, master_names, n=1, cutoff=GROUP_DETAIL_NAME_CUTOFF)
                if close and difflib.SequenceMatcher(None, raw_name, close[0]).ratio() >= GROUP_DETAIL_NAME_CUTOFF:
                    match = close[0]
            code, market = name_to_code.get(match, (None, None))
            stocks.append({"name": match or raw_name, "code": code, "market": market,
                            "pct_change": r["pct_change"]})
        stocks.sort(key=lambda s: -s["pct_change"])
        stocks = stocks[:GROUP_DETAIL_TOP_N]
        for i, s in enumerate(stocks):
            s["rank"] = i + 1

        if not stocks:
            print(f"[WARN] 族群明細截圖 {img_path.name}（{sector}）辨識不出任何個股資料", file=sys.stderr)
            continue
        detail[sector] = stocks
    return detail


# ---------------------------------------------------------------------------
# tracker_db.json 持久化狀態
# ---------------------------------------------------------------------------
def load_tracker_db():
    if TRACKER_DB_PATH.exists():
        with open(TRACKER_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_updated": None, "stocks": {}}


def save_tracker_db(db):
    with open(TRACKER_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def ensure_stock_entries(db, codes, master):
    for code in codes:
        entry = db["stocks"].setdefault(code, {"name": "—", "market": "TW", "history": []})
        if code in master:
            entry["name"] = master[code]["name"]
            entry["market"] = master[code]["market"]


def apply_detail_updates(db, detail_updates):
    """將截圖 OCR 出的『相對強度』表，逐日 upsert 進各股歷史（可一次回補多天）。"""
    for code, day_labels in detail_updates.items():
        entry = db["stocks"].setdefault(code, {"name": "—", "market": "TW", "history": []})
        hist = entry["history"]
        by_date = {h["date"]: h for h in hist}
        for d, label in day_labels.items():
            if d in by_date:
                by_date[d]["strength"] = label
                by_date[d]["source"] = "super"
            else:
                hist.append({"date": d, "strength": label, "source": "super"})
        hist.sort(key=lambda h: h["date"])


def activate_pool_codes(db, codes, date_str):
    """當日出現在 super 資料夾的股票，自動納入監控股池。"""
    for code in codes:
        pool = db["stocks"][code].setdefault("pool", {"active": False, "warned": False, "added_date": None})
        if not pool["active"]:
            pool["active"] = True
            pool["warned"] = False
            if pool.get("added_date") is None:
                pool["added_date"] = date_str


def recompute_pool_state(db, date_str, update_paths):
    """監控股池的❓補記，以及『連續5日無偏強/極強』剔除規則。由監控股池技能負責維護。"""
    pool_active_codes = {
        code for code, info in db["stocks"].items() if info.get("pool", {}).get("active")
    }

    # 監控池中的股票，若當日既無 super 也無 update 截圖可確認強度，標記為未更新（❓）
    for code in pool_active_codes:
        hist = db["stocks"][code]["history"]
        if not (hist and hist[-1]["date"] == date_str):
            source = "update" if code in update_paths else "missing"
            hist.append({"date": date_str, "strength": UNKNOWN_LEVEL, "source": source})

    # 剔除規則：連續5日無偏強/極強 -> 當日標記警示保留，隔天更新時才正式剔除
    # 觀察中（pinned）股票不套用這條規則，永遠不會被自動剔除，需靠 unpin 手動解除。
    for code in pool_active_codes:
        entry = db["stocks"][code]
        hist = entry["history"]
        pool = entry["pool"]
        if pool.get("pinned"):
            pool["warned"] = False
            continue
        today_strength = hist[-1]["strength"] if hist and hist[-1]["date"] == date_str else UNKNOWN_LEVEL

        if pool["warned"]:
            if today_strength in STRONG_LEVELS:
                pool["warned"] = False
            else:
                pool["active"] = False
                pool["warned"] = False

        if pool["active"]:
            streak = 0
            for h in reversed(hist):
                if h["strength"] in STRONG_LEVELS:
                    break
                streak += 1
            if streak >= 5:
                pool["warned"] = True


# ---------------------------------------------------------------------------
# 輸出 docs/today_summary.json ＋ docs/history/{date}.json
# ---------------------------------------------------------------------------
def star_info(strength):
    if strength in ("極強", "偏強"):
        return {"level": strength, "symbol": "★", "color": "gold"}
    if strength == "中立":
        return {"level": strength, "symbol": "☆", "color": "neutral"}
    if strength in ("弱", "偏弱"):
        return {"level": strength, "symbol": "★", "color": "dark"}
    return {"level": UNKNOWN_LEVEL, "symbol": "❓", "color": "unknown"}


def last5_stars(history):
    """近 5 日星星，New -> Old 排列（最左為當日 T0）。"""
    last5 = list(reversed(history[-5:]))
    stars = [star_info(h["strength"]) for h in last5]
    while len(stars) < 5:
        stars.append(star_info(UNKNOWN_LEVEL))
    return stars


_STRENGTH_RANK = {"極強": 0, "偏強": 1, "中立": 2, "偏弱": 3, "弱": 4, UNKNOWN_LEVEL: 5}


def build_tab_list(codes, db):
    items = []
    for code in sorted(codes):
        entry = db["stocks"].get(code)
        if not entry:
            continue
        history = entry.get("history", [])
        items.append({
            "code": code,
            "name": entry.get("name", "—"),
            "market": entry.get("market", "TW"),
            "today_strength": history[-1]["strength"] if history else UNKNOWN_LEVEL,
            "stars": last5_stars(history),
        })
    items.sort(key=lambda x: (_STRENGTH_RANK.get(x["today_strength"], 5), x["code"]))
    return items


def build_pool_list(db):
    items = []
    for code, entry in db["stocks"].items():
        pool = entry.get("pool")
        if not pool or not pool.get("active"):
            continue
        items.append({
            "code": code,
            "name": entry.get("name", "—"),
            "market": entry.get("market", "TW"),
            "today_strength": entry["history"][-1]["strength"] if entry["history"] else UNKNOWN_LEVEL,
            "stars": last5_stars(entry["history"]),
            "warned": pool.get("warned", False),
            "pinned": pool.get("pinned", False),
            "added_date": pool.get("added_date"),
        })
    items.sort(key=lambda x: (_STRENGTH_RANK.get(x["today_strength"], 5), x["code"]))
    return items


def load_date_tabs(date_str):
    """讀取（或初始化）某日期在 docs/history/ 的分頁快照，讓各分類技能可各自獨立更新。"""
    path = HISTORY_DIR / f"{date_str}.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)["tabs"]
    return {cat: [] for cat in CATEGORIES}


def refresh_tab_strengths(db, tabs):
    """強度資料（super／監控股池補漏）更新後，重算既有分頁內每檔股票的當日強度與五日星星，
    避免焦點監控／α動能／回檔型／當日Super 分頁殘留過期的強度快照。"""
    for cat in CATEGORIES:
        items = tabs.get(cat, [])
        for item in items:
            history = db["stocks"].get(item["code"], {}).get("history", [])
            item["today_strength"] = history[-1]["strength"] if history else UNKNOWN_LEVEL
            item["stars"] = last5_stars(history)
        items.sort(key=lambda x: (_STRENGTH_RANK.get(x["today_strength"], 5), x["code"]))
    return tabs


def save_date_tabs(date_str, tabs, db):
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date": date_str,
        "tabs": tabs,
    }
    with open(HISTORY_DIR / f"{date_str}.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    finalize_summary(db)


def finalize_summary(db):
    """依 docs/history/ 內既有日期快照，重新輸出 docs/today_summary.json：
    tabs.focus/alpha/pullback/super 取「最新日期」快照；tabs.pool 為累加型，
    不論由哪個分類技能觸發，一律取當下最新的監控股池狀態。"""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    dates = sorted((p.stem for p in HISTORY_DIR.glob("*.json")), reverse=True)
    if not dates:
        return
    latest = dates[0]
    with open(HISTORY_DIR / f"{latest}.json", "r", encoding="utf-8") as f:
        snapshot = json.load(f)

    refresh_tab_strengths(db, snapshot["tabs"])
    snapshot["tabs"]["pool"] = build_pool_list(db)
    snapshot["generated_at"] = datetime.now().isoformat(timespec="seconds")

    with open(HISTORY_DIR / f"{latest}.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    summary = dict(snapshot, dates=dates)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 五個可獨立執行的更新技能：焦點監控／α動能／回檔型／當日Super／監控股池
# ---------------------------------------------------------------------------
def update_list_category(date_str, category):
    """焦點監控／α動能／回檔型 共用：僅掃描清單型截圖辨識當日名單，強度沿用既有歷史資料。"""
    assert category in LIST_CATEGORIES
    print(f"=== [{category}] 處理日期: {date_str} ===")
    master = fetch_institutional_master(date_str)
    valid_codes = set(master.keys())

    codes = scan_category_folder(category, date_str, valid_codes)
    print(f"  辨識出 {len(codes)} 檔: {sorted(codes)}")

    db = load_tracker_db()
    ensure_stock_entries(db, codes, master)

    tabs = load_date_tabs(date_str)
    tabs[category] = build_tab_list(codes, db)
    save_date_tabs(date_str, tabs, db)

    db["last_updated"] = date_str
    save_tracker_db(db)
    print(f"  已更新 {category} 分頁（{len(codes)} 檔），並重新輸出 {SUMMARY_PATH}")
    return codes


def update_super(date_str):
    """當日Super：掃描個股詳細頁，強度完全以此為準，並自動將當日出現的股票納入監控股池。"""
    print(f"=== [super] 處理日期: {date_str} ===")
    master = fetch_institutional_master(date_str)
    valid_codes = set(master.keys())

    super_codes, super_detail = scan_super_folder(date_str, valid_codes)
    print(f"  辨識出 {len(super_codes)} 檔: {sorted(super_codes)}")

    db = load_tracker_db()
    ensure_stock_entries(db, super_codes, master)
    apply_detail_updates(db, super_detail)
    activate_pool_codes(db, super_codes, date_str)

    tabs = load_date_tabs(date_str)
    tabs["super"] = build_tab_list(super_codes, db)
    save_date_tabs(date_str, tabs, db)

    db["last_updated"] = date_str
    save_tracker_db(db)
    print(f"  已更新 super 分頁（{len(super_codes)} 檔），並重新輸出 {SUMMARY_PATH}")
    return super_codes


def update_stock_future(date_str):
    """股期：掃描 stock_future_top/<日期>/ 的量大股期排行榜截圖，依代號去重後的
    出現順序排名，並記錄期漲幅(%)。此分頁依日期切換（寫入 docs/history/<日期>.json），
    不涉及強度歷史，不影響其他分頁。"""
    print(f"=== [stock_future] 處理日期: {date_str} ===")
    master = fetch_institutional_master(date_str)

    db = load_tracker_db()
    items = build_stock_future_list(date_str, master, db)
    save_tracker_db(db)

    tabs = load_date_tabs(date_str)
    tabs["stock_future"] = items
    save_date_tabs(date_str, tabs, db)

    print(f"  股期排行榜共 {len(items)} 檔，已重新輸出 {SUMMARY_PATH}")
    return items


def update_group(date_str):
    """族群：解析 group/<日期>/overall.jpg 熱力圖，僅保留漲幅 > 0% 的族群並依漲幅排名；
    再掃描同資料夾內其他族群明細截圖（點進單一族群後看到的成分股熱力圖），依標題比對
    出所屬族群，附上該族群前 6 大個股排行（供前端點擊該族群列時展開）。找不到對應明細
    截圖的族群，stocks 為空陣列，前端會顯示「No more Information, please update」。
    此分頁依日期切換（寫入 docs/history/<日期>.json），不涉及強度歷史，不影響其他分頁。"""
    print(f"=== [group] 處理日期: {date_str} ===")
    items = scan_group_overall(date_str)

    master = fetch_institutional_master(date_str)
    detail_map = scan_group_sector_details(date_str, master)
    for item in items:
        stocks = detail_map.get(item["sector"])
        if stocks is None and detail_map:
            # overall.jpg 該列族群名稱比對信心不足時會保留原始 OCR 文字（可能與明細截圖
            # 標題辨識出的正確名稱不同字），改用寬鬆模糊比對去對 detail_map 的既有（已較高
            # 信心比對過）族群名稱，避免因兩處 OCR 結果字面不同而漏接已存在的成分股資料。
            close = difflib.get_close_matches(item["sector"], detail_map.keys(), n=1, cutoff=0.4)
            if close:
                stocks = detail_map[close[0]]
        item["stocks"] = stocks or []

    db = load_tracker_db()
    tabs = load_date_tabs(date_str)
    tabs["group"] = items
    save_date_tabs(date_str, tabs, db)

    with_detail = sum(1 for it in items if it["stocks"])
    print(f"  漲幅 > 0% 的族群共 {len(items)} 個（{with_detail} 個有成分股明細），已重新輸出 {SUMMARY_PATH}")
    return items


def update_pool(date_str):
    """監控股池：讀取 update/ 補漏截圖、更新相對強度歷史，並執行❓補記與5日剔除規則。
    此分頁為累加型、不依日期切換，因此不寫入 docs/history/，只重新輸出 docs/today_summary.json。"""
    print(f"=== [pool] 處理日期: {date_str} ===")
    master = fetch_institutional_master(date_str)
    valid_codes = set(master.keys())
    update_paths, update_detail = scan_update_folder(valid_codes)
    if update_paths:
        print(f"  [update 補漏] {len(update_paths)} 檔: {sorted(update_paths.keys())}")

    db = load_tracker_db()
    ensure_stock_entries(db, update_paths.keys(), master)  # 代號可能是新從截圖內容辨識出來的，補上名稱/市場
    apply_detail_updates(db, update_detail)
    recompute_pool_state(db, date_str, update_paths)

    db["last_updated"] = date_str
    save_tracker_db(db)
    finalize_summary(db)
    print(f"  監控股池目前共 {len(build_pool_list(db))} 檔，已重新輸出 {SUMMARY_PATH}")
    return update_paths


def pin_stock(code, date_str):
    """手動將股票加入監控股池並標記為觀察中（pinned）：不受『連續5日無偏強/極強』
    剔除規則影響，永遠不會被自動剔除。若該股票尚未在池中，會直接建立池成員紀錄
    （不需要先出現在 super 截圖中）；已在池中的股票只是補上觀察中標記。
    強度歷史仍需靠平常的 super/update 截圖持續更新，pin 本身不提供每日資料。"""
    master = fetch_institutional_master(date_str)
    db = load_tracker_db()
    ensure_stock_entries(db, [code], master)

    entry = db["stocks"].setdefault(code, {"name": "—", "market": "TW", "history": []})
    pool = entry.setdefault("pool", {"active": False, "warned": False, "added_date": None})
    was_active = pool["active"]
    pool["active"] = True
    pool["warned"] = False
    pool["pinned"] = True
    if pool.get("added_date") is None:
        pool["added_date"] = date_str

    db["last_updated"] = date_str
    save_tracker_db(db)
    finalize_summary(db)

    action = "已標記為觀察中" if was_active else "已加入監控股池並標記為觀察中"
    print(f"{code}（{entry.get('name', '—')}）{action}，不受5日剔除規則影響。")


def unpin_stock(code):
    """取消某股票的觀察中（pinned）標記，恢復套用一般的『連續5日無偏強/極強』剔除規則。
    不會把它從池中移除——若它目前的強度已經連續多日不強，下次執行 update-pool 時
    就會依一般規則被標記警示、隔天再未轉強才正式剔除。"""
    db = load_tracker_db()
    entry = db["stocks"].get(code)
    if not entry or not entry.get("pool", {}).get("active"):
        print(f"[WARN] {code} 目前不在監控股池中，無需取消觀察標記", file=sys.stderr)
        return
    entry["pool"]["pinned"] = False
    save_tracker_db(db)
    finalize_summary(db)
    print(f"{code}（{entry.get('name', '—')}）已取消觀察中標記，恢復套用一般剔除規則。")


UPDATE_FUNCS = {
    "focus": lambda d: update_list_category(d, "focus"),
    "alpha": lambda d: update_list_category(d, "alpha"),
    "pullback": lambda d: update_list_category(d, "pullback"),
    "super": update_super,
    "stock_future": update_stock_future,
    "group": update_group,
    "pool": update_pool,
}


# ---------------------------------------------------------------------------
# 主流程：一次更新全部七個分頁
# ---------------------------------------------------------------------------
def run_pipeline(date_str=None):
    """依序更新：焦點監控 -> α動能 -> 回檔型 -> 當日Super -> 股期 -> 族群 -> 監控股池。
    Super 必須先於監控股池執行，才能讓當日 super 掃到的股票即時納入監控池；
    監控股池最後執行，才能套用當日最終、完整的強度資料做5日剔除判斷。
    股期／族群不涉及強度歷史，順序上不影響其他分頁，排在 super 之後、pool 之前即可。"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    for category in ("focus", "alpha", "pullback", "super", "stock_future", "group", "pool"):
        UPDATE_FUNCS[category](date_str)

    with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
        summary = json.load(f)
    print(f"=== 全部分頁更新完成（{date_str}） ===")
    print(f"  焦點監控: {len(summary['tabs']['focus'])} 檔 / "
          f"α動能: {len(summary['tabs']['alpha'])} 檔 / "
          f"回檔型: {len(summary['tabs']['pullback'])} 檔 / "
          f"當日Super: {len(summary['tabs']['super'])} 檔 / "
          f"股期: {len(summary['tabs'].get('stock_future', []))} 檔 / "
          f"族群: {len(summary['tabs'].get('group', []))} 個 / "
          f"監控股池: {len(summary['tabs']['pool'])} 檔")

    return SUMMARY_PATH, date_str


def main():
    parser = argparse.ArgumentParser(description="台股強勢股分析資料處理")
    parser.add_argument("--date", default=None, help="指定處理日期 YYYY-MM-DD，預設為今天")
    parser.add_argument(
        "--category",
        choices=["focus", "alpha", "pullback", "super", "stock_future", "group", "pool", "all"],
        default="all",
        help="只更新單一分頁（focus/alpha/pullback/super/stock_future/group/pool），"
             "預設 all 依序更新全部七個分頁",
    )
    parser.add_argument("--pin", metavar="CODE", default=None,
                         help="將股票代號加入監控股池並標記為觀察中，不受5日剔除規則影響")
    parser.add_argument("--unpin", metavar="CODE", default=None,
                         help="取消某股票代號的觀察中標記，恢復套用一般5日剔除規則")
    args = parser.parse_args()
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    if args.pin:
        pin_stock(args.pin, date_str)
    elif args.unpin:
        unpin_stock(args.unpin)
    elif args.category == "all":
        run_pipeline(date_str)
    else:
        UPDATE_FUNCS[args.category](date_str)


if __name__ == "__main__":
    main()
