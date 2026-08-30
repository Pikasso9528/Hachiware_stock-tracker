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
    from PIL import Image, ImageOps, ImageStat

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
            inv = inv.resize((inv.width * 4, inv.height * 4), Image.LANCZOS)
            txt = pytesseract.image_to_string(
                inv, lang="eng", config="--psm 6 -c tessedit_char_whitelist=0123456789"
            )
            candidates = re.findall(r"\d{4,6}", txt)
            if valid_codes:
                match = next((c for c in candidates if c in valid_codes), None)
            else:
                match = candidates[0] if candidates else None
            if match:
                code = match
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


def scan_update_folder():
    """補漏資料夾：檔名即股票代號（例如 8358.png），內容比照 super 的個股詳細頁格式。
    回傳 (paths, detail)：paths 為 {code: Path}，detail 為 {code: {date: 強度標籤}}。"""
    paths = {}
    detail = {}
    if not UPDATE_DIR.exists():
        return paths, detail
    for img_path in sorted(UPDATE_DIR.iterdir()):
        if img_path.suffix.lower() not in IMAGE_EXTS:
            continue
        m = re.match(r"(\d{4,6})", img_path.stem)
        if not m:
            continue
        code = m.group(1)
        paths[code] = img_path
        _, labels = ocr_super_detail(img_path)  # 代號採信檔名，這裡僅取相對強度表
        if labels:
            detail[code] = labels
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
    """在單一列的 y 範圍內，分別裁切「代號」與「期漲幅(%)」兩個欄位辨識。"""
    y0, y1 = int(center - row_h * 0.42), int(center + row_h * 0.42)
    code_crop = img.crop((int(w * 0.20), int(center - 5), int(w * 0.34), y1))
    pct_crop = img.crop((int(w * 0.60), y0, int(w * 0.84), y1))

    code = _ocr_single_line(_threshold_channel(code_crop), "0123456789")

    pct_txt = _ocr_single_line(_threshold_channel(pct_crop, channel=0), "0123456789.")  # 紅字：上漲
    sign = 1
    if not pct_txt:
        pct_txt = _ocr_single_line(_threshold_channel(pct_crop, channel=1), "0123456789.")  # 綠字：下跌
        sign = -1

    pct = sign * float(pct_txt) if re.fullmatch(r"\d{1,3}\.\d{1,2}", pct_txt) else None
    code = code if re.fullmatch(r"\d{4,6}", code) else None
    return code, pct


def scan_stock_future_folder(date_str, valid_codes):
    """掃描 stock_future_top/<日期>/ 內的「量大股期」排行榜截圖（可能為捲動後的多張截圖）。
    依截圖檔名排序（即拍攝／捲動先後順序）逐張辨識每一列的股票代號與期漲幅(%)，
    以代號去重（保留第一次出現的位置）串接成完整排行，回傳 [(code, pct_change), ...]。"""
    folder = SCREENSHOTS_DIR / "stock_future_top" / date_str
    ordered = []
    seen = set()
    if not folder.exists():
        return ordered
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
        for c in centers:
            code, pct = _future_row_fields(img, w, c, row_h)
            if not code or pct is None:
                print(f"[WARN] 股期排行截圖 {img_path.name} 有一列無法辨識代號或期漲幅，已略過",
                      file=sys.stderr)
                continue
            if valid_codes and code not in valid_codes:
                continue
            if code in seen:
                continue
            seen.add(code)
            ordered.append((code, pct))
    return ordered


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
# OCR：族群熱力圖截圖（group/overall.jpg）－ 擷取族群名稱與漲跌幅(%)
# ---------------------------------------------------------------------------
_GROUP_NOISE_RE = re.compile(r"[﹣﹍‥。﹒｜|:：'’,，)）(（\[\]{}『』﹚﹛ˍ︰…=~`^\s]+")
_GROUP_PCT_VALUE_RE = re.compile(r"^([+-])?(\d+)\.(\d{2,})")
_GROUP_NAME_XTOL = 140  # 名稱列文字與漲跌幅的 x 座標容許誤差（依實測截圖校準）
GROUP_TOP_N = 6  # 族群分頁只顯示漲幅前 N 名

# 依實測截圖校準的已知族群名稱表：熱力圖色塊的中文名稱常因字體小、色塊擁擠而 OCR
# 失準，因此對辨識結果做「像 STRENGTH_LABELS 一樣的模糊比對校正」，snap 到最接近的
# 已知名稱；若比對信心不足則保留原始 OCR 文字，讓使用者自行核對。
GROUP_SECTOR_WHITELIST = [
    "IC-代工", "被動元件", "IC-封測", "PCB-製造", "PCB-材料設備", "記憶體製造", "ABF",
    "光學鏡片", "IC-設計", "晶圓材料", "EMS", "LCD-TF...", "IC-半導體", "連接元件",
    "金控", "儀器設備...", "塑膠", "電機", "電源供應器", "IP/ASIC", "航運", "通訊設備",
]


def _normalize_group_pct(raw):
    """OCR 常把 +/- 與小數點辨識成全形變體（﹢﹣﹒），偶爾還會夾帶雜訊數字，
    依「族群漲跌幅固定顯示兩位小數」的版面特性做正規化；超出熱力圖色階上限
    （圖例僅到 ±5%）甚多者視為 OCR 雜訊，回傳 None。"""
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


def _isolated_sector_ocr(img, box, y_offset):
    """對單一色塊的名稱區域重新獨立裁切放大辨識，比整張熱力圖一次 OCR 更準，
    但只在整張圖辨識結果對不上已知族群名稱表時才使用（單獨裁切對大色塊反而
    常常變差，依實測截圖校準）。"""
    l, t, r, b = box
    pad = 8
    w, h = img.size
    crop = img.crop((max(0, l - pad), max(0, t + y_offset - pad),
                      min(w, r + pad), min(h, b + y_offset + pad)))
    big = crop.convert("L")
    big = big.resize((big.width * 3, big.height * 3), Image.LANCZOS)
    txt = pytesseract.image_to_string(big, lang="chi_tra+eng", config="--psm 13").strip()
    return _GROUP_NOISE_RE.sub("", txt.replace("\n", ""))


def scan_group_overall(date_str):
    """解析 group/<日期>/overall.jpg（熱力圖截圖），擷取每個族群色塊的名稱與漲跌幅(%)，
    僅保留漲幅 > 0% 的族群，依漲幅由高到低排序，取前 GROUP_TOP_N 名並附上名次。

    熱力圖為不規則大小色塊拼接而成的 treemap，無法單純依固定座標切欄取值，因此採
    「文字列聚類＋依水平座標就近配對」策略：先把 OCR 文字依 y 座標分行，對每一行
    「漲跌幅(%)」文字，往上（限制搜尋範圍內）找最近一行「x 座標與該漲跌幅相近」的
    文字當作名稱列，再依各漲跌幅的 x 座標把名稱列的文字分配給最近的漲跌幅。名稱最終
    會與 GROUP_SECTOR_WHITELIST 模糊比對校正；比對信心不足時，改用單獨裁切放大重新
    辨識該色塊再比對一次，兩次都對不上已知名稱才保留原始 OCR 文字。"""
    path = SCREENSHOTS_DIR / "group" / date_str / "overall.jpg"
    if not path.exists():
        return []
    img = Image.open(path)
    w, h = img.size
    y_offset = int(h * 0.20)
    crop = img.crop((0, y_offset, w, int(h * 0.865)))
    g = crop.convert("L")
    data = pytesseract.image_to_data(
        g, lang="chi_tra+eng", config="--psm 6", output_type=pytesseract.Output.DICT
    )

    words = []
    for i, raw in enumerate(data["text"]):
        t = raw.strip()
        if not t:
            continue
        words.append({"text": t, "left": data["left"][i], "top": data["top"][i],
                       "width": data["width"][i], "height": data["height"][i],
                       "pct": _normalize_group_pct(raw)})
    words.sort(key=lambda x: x["top"])

    lines = []
    for wd in words:
        placed = False
        for ln in lines:
            if abs(ln["top"] - wd["top"]) < 15:
                ln["words"].append(wd)
                ln["top"] = sum(x["top"] for x in ln["words"]) / len(ln["words"])
                placed = True
                break
        if not placed:
            lines.append({"top": wd["top"], "words": [wd]})
    lines.sort(key=lambda l: l["top"])
    for ln in lines:
        ln["words"].sort(key=lambda x: x["left"])

    results = []
    for idx, ln in enumerate(lines):
        pct_words = [wd for wd in ln["words"] if wd["pct"] is not None]
        if not pct_words:
            continue
        pct_centers = [p["left"] + p["width"] / 2 for p in pct_words]

        name_line = None
        relevant = None
        for j in range(idx - 1, max(-1, idx - 8), -1):
            cand = [wd for wd in lines[j]["words"] if wd["pct"] is None]
            rel = [c for c in cand if any(abs((c["left"] + c["width"] / 2) - pc) < _GROUP_NAME_XTOL
                                           for pc in pct_centers)]
            text = _GROUP_NOISE_RE.sub("", "".join(c["text"] for c in rel))
            if len(text) >= 2:
                name_line, relevant = lines[j], rel
                break
        if not name_line:
            continue

        buckets = {i: [] for i in range(len(pct_words))}
        for nwd in relevant:
            ncx = nwd["left"] + nwd["width"] / 2
            k = min(range(len(pct_centers)), key=lambda k2: abs(pct_centers[k2] - ncx))
            buckets[k].append(nwd)

        for i, p in enumerate(pct_words):
            group = buckets[i]
            if not group:
                continue
            raw_name = _GROUP_NOISE_RE.sub(
                "", "".join(x["text"] for x in sorted(group, key=lambda x: x["left"]))
            )
            match, score = _snap_to_sector_name(raw_name)
            if not match or score < 0.6:
                box = (min(x["left"] for x in group), min(x["top"] for x in group),
                       max(x["left"] + x["width"] for x in group), max(x["top"] + x["height"] for x in group))
                iso_name = _isolated_sector_ocr(img, box, y_offset)
                match2, score2 = _snap_to_sector_name(iso_name)
                if match2 and score2 >= 0.6:
                    match, score = match2, score2
            name = match if (match and score >= 0.6) else raw_name
            if not name:
                print(f"[WARN] 族群熱力圖有一色塊只辨識出漲跌幅 {p['pct']:+.2f}%，"
                      f"名稱無法辨識，已略過", file=sys.stderr)
                continue
            if not (match and score >= 0.6):
                print(f"[WARN] 族群熱力圖有一色塊（漲跌幅 {p['pct']:+.2f}%）名稱與已知族群表比對信心不足，"
                      f"保留原始辨識結果 {name!r}，建議人工核對", file=sys.stderr)
            results.append({"sector": name, "pct_change": p["pct"]})

    results = [r for r in results if r["pct_change"] > 0]
    results.sort(key=lambda r: -r["pct_change"])
    results = results[:GROUP_TOP_N]
    for i, r in enumerate(results):
        r["rank"] = i + 1
    return results


# ---------------------------------------------------------------------------
# OCR：族群明細截圖（group/<日期>/ 底下除 overall.jpg 外的其他截圖）
# 每張對應點進某一個族群後看到的成分股熱力圖，用來讓前端點擊族群列時展開排行
# ---------------------------------------------------------------------------
GROUP_DETAIL_XTOL = 160  # 個股明細色塊較大，名稱列與漲跌幅的 x 座標容許誤差也放寬
GROUP_DETAIL_NAME_CUTOFF = 0.6


def _tile_gain_sign(color_crop, box, margin=8):
    """依色塊背景的紅／綠分量比較判斷漲跌方向（紅漲、綠跌），比 OCR 認出的正負號
    小圖示更可靠——實測小數點附近的 +/- 常被完全漏辨識。"""
    l, t, r, b = box
    l, t = max(0, int(l)), max(0, int(t))
    r, b = min(color_crop.width, int(r)), min(color_crop.height, int(b))
    if r <= l or b <= t:
        return None
    stat = ImageStat.Stat(color_crop.crop((l, t, r, b)))
    avg_r, avg_g = stat.mean[0], stat.mean[1]
    if avg_r - avg_g > margin:
        return "+"
    if avg_g - avg_r > margin:
        return "-"
    return None


def _ocr_sector_detail_title(img):
    """族群明細截圖最上方置中的白色族群名稱標題，字體大、位置固定，比熱力圖內文字更好辨識。"""
    w, h = img.size
    crop = img.crop((int(w * 0.10), int(h * 0.055), int(w * 0.90), int(h * 0.115)))
    g = crop.convert("L")
    big = g.resize((g.width * 3, g.height * 3), Image.LANCZOS)
    txt = pytesseract.image_to_string(big, lang="chi_tra+eng", config="--psm 7").strip()
    return _GROUP_NOISE_RE.sub("", txt.replace("\n", ""))


def _scan_sector_detail_body(img, name_to_code):
    """掃描單一族群明細截圖的色塊本體，擷取該族群內個股名稱與漲跌幅(%)，依漲跌幅
    排序取前 6 名。色塊為白字＋彩色底，改用藍色版（相對灰階更能與紅/綠/灰底拉開對比，
    依實測截圖校準）整張二值化後 OCR，比逐色塊個別裁切更能一次讀到大小混合的字體。
    股票名稱與三大法人主檔（name_to_code）模糊比對校正，比對信心不足或原始文字太短
    （單一字元常是誤配）則保留原始辨識結果、不附代號，前端不會顯示個股連結。"""
    w, h = img.size
    y_offset = int(h * 0.20)
    crop = img.crop((0, y_offset, w, int(h * 0.94)))
    b_channel = crop.split()[2]
    th = b_channel.point(lambda p: 255 if p > 150 else 0)
    data = pytesseract.image_to_data(
        th, lang="chi_tra+eng", config="--psm 6", output_type=pytesseract.Output.DICT
    )

    words = []
    for i, raw in enumerate(data["text"]):
        t = raw.strip()
        if not t:
            continue
        cy = data["top"][i] + data["height"][i] / 2
        words.append({"text": t, "left": data["left"][i], "top": data["top"][i], "cy": cy,
                       "width": data["width"][i], "height": data["height"][i],
                       "pct": _normalize_group_pct(raw)})
    words.sort(key=lambda x: x["cy"])

    # 依中心 y 座標分行（用中心點而非上緣，避免同一行內不同字元的字高差異把
    # 同一個名稱拆成兩行，實測校準）
    lines = []
    for wd in words:
        placed = False
        for ln in lines:
            if abs(ln["cy"] - wd["cy"]) < 25:
                ln["words"].append(wd)
                ln["cy"] = sum(x["cy"] for x in ln["words"]) / len(ln["words"])
                placed = True
                break
        if not placed:
            lines.append({"cy": wd["cy"], "words": [wd]})
    lines.sort(key=lambda l: l["cy"])
    for ln in lines:
        ln["words"].sort(key=lambda x: x["left"])

    master_names = list(name_to_code.keys())
    results = []
    for idx, ln in enumerate(lines):
        pct_words = [wd for wd in ln["words"] if wd["pct"] is not None]
        if not pct_words:
            continue
        pct_centers = [p["left"] + p["width"] / 2 for p in pct_words]

        name_line, relevant = None, None
        for j in range(idx - 1, max(-1, idx - 6), -1):
            cand = [wd for wd in lines[j]["words"] if wd["pct"] is None]
            rel = [c for c in cand if any(abs((c["left"] + c["width"] / 2) - pc) < GROUP_DETAIL_XTOL
                                           for pc in pct_centers)]
            text = _GROUP_NOISE_RE.sub("", "".join(c["text"] for c in rel))
            if text:
                name_line, relevant = lines[j], rel
                break
        if not name_line:
            continue

        buckets = {i: [] for i in range(len(pct_words))}
        for nwd in relevant:
            ncx = nwd["left"] + nwd["width"] / 2
            k = min(range(len(pct_centers)), key=lambda k2: abs(pct_centers[k2] - ncx))
            buckets[k].append(nwd)

        for i, p in enumerate(pct_words):
            group = buckets[i]
            if not group:
                continue
            raw_name = _GROUP_NOISE_RE.sub(
                "", "".join(x["text"] for x in sorted(group, key=lambda x: x["left"]))
            )
            if not raw_name:
                continue

            match = None
            if len(raw_name) >= 2 and master_names:
                close = difflib.get_close_matches(raw_name, master_names, n=1, cutoff=GROUP_DETAIL_NAME_CUTOFF)
                if close and difflib.SequenceMatcher(None, raw_name, close[0]).ratio() >= GROUP_DETAIL_NAME_CUTOFF:
                    match = close[0]

            pct = p["pct"]
            sign = _tile_gain_sign(crop, (p["left"], p["top"], p["left"] + p["width"], p["top"] + p["height"]))
            if sign == "-" and pct > 0:
                pct = -pct
            elif sign == "+" and pct < 0:
                pct = -pct

            code, market = name_to_code.get(match, (None, None))
            results.append({"name": match or raw_name, "code": code, "market": market, "pct_change": pct})

    results.sort(key=lambda r: -r["pct_change"])
    results = results[:6]
    for i, r in enumerate(results):
        r["rank"] = i + 1
    return results


def scan_group_sector_details(date_str, master):
    """掃描 group/<日期>/ 底下除 overall.jpg 外的個別族群明細截圖，依標題辨識所屬族群，
    回傳 {族群名稱: [該族群前6大個股, ...]}，供前端點擊某個族群時展開其成分股排行。
    若某個族群沒有對應的明細截圖，該族群不會出現在回傳結果中——前端遇到查無資料的
    族群時會顯示「No more Information, please update」。"""
    folder = SCREENSHOTS_DIR / "group" / date_str
    detail = {}
    if not folder.exists():
        return detail

    name_to_code = {}
    for code, info in (master or {}).items():
        name_to_code.setdefault(info["name"], (code, info["market"]))

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
        stocks = _scan_sector_detail_body(img, name_to_code)
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
    for code in pool_active_codes:
        entry = db["stocks"][code]
        hist = entry["history"]
        pool = entry["pool"]
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
            "added_date": pool.get("added_date"),
        })
    items.sort(key=lambda x: (not x["warned"], _STRENGTH_RANK.get(x["today_strength"], 5), x["code"]))
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
        item["stocks"] = detail_map.get(item["sector"], [])

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
    update_paths, update_detail = scan_update_folder()
    if update_paths:
        print(f"  [update 補漏] {len(update_paths)} 檔: {sorted(update_paths.keys())}")

    db = load_tracker_db()
    apply_detail_updates(db, update_detail)
    recompute_pool_state(db, date_str, update_paths)

    db["last_updated"] = date_str
    save_tracker_db(db)
    finalize_summary(db)
    print(f"  監控股池目前共 {len(build_pool_list(db))} 檔，已重新輸出 {SUMMARY_PATH}")
    return update_paths


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
    args = parser.parse_args()
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    if args.category == "all":
        run_pipeline(date_str)
    else:
        UPDATE_FUNCS[args.category](date_str)


if __name__ == "__main__":
    main()
