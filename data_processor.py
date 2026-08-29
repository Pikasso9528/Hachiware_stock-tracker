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
TRACKER_DB_PATH = ROOT / "tracker_db.json"
SUMMARY_PATH = DOCS_DIR / "today_summary.json"

CATEGORIES = ["focus", "alpha", "pullback", "super"]
LIST_CATEGORIES = ["focus", "alpha", "pullback"]  # 清單型截圖（多檔股票／頁），僅用於辨識當日名單
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


def scan_category_folder(date_dir, category, valid_codes):
    folder = date_dir / category
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


def scan_super_folder(date_dir, valid_codes):
    """回傳 (codes, detail)：codes 為當日 super 資料夾辨識出的股票代號集合，
    detail 為 {code: {date: 強度標籤}} 的相對強度歷史表彙整結果。"""
    folder = date_dir / "super"
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


def process_day(db, date_str, master, category_codes, detail_updates, update_paths):
    """
    category_codes: {focus, alpha, pullback, super} -> 當日辨識出的股票代號集合（僅供分頁清單顯示）
    detail_updates: {code: {date: 強度標籤}}，來自 super/update 截圖 OCR 出的『相對強度』表，為強度的唯一真實來源
    update_paths:   {code: Path}，當日 update/ 資料夾內的補漏截圖
    """
    all_codes_today = set()
    for codes in category_codes.values():
        all_codes_today |= codes
    all_codes_today |= set(detail_updates.keys())
    all_codes_today |= set(update_paths.keys())

    for code in all_codes_today:
        entry = db["stocks"].setdefault(code, {"name": "—", "market": "TW", "history": []})
        if code in master:
            entry["name"] = master[code]["name"]
            entry["market"] = master[code]["market"]

    # 將截圖 OCR 出的『相對強度』表，逐日 upsert 進各股歷史（可一次回補多天）
    for code, day_labels in detail_updates.items():
        hist = db["stocks"][code]["history"]
        by_date = {h["date"]: h for h in hist}
        for d, label in day_labels.items():
            if d in by_date:
                by_date[d]["strength"] = label
                by_date[d]["source"] = "super"
            else:
                hist.append({"date": d, "strength": label, "source": "super"})
        hist.sort(key=lambda h: h["date"])

    # 當日出現在 super 資料夾的股票，自動納入累加型監控池
    for code in category_codes.get("super", set()):
        pool = db["stocks"][code].setdefault("pool", {"active": False, "warned": False, "added_date": None})
        if not pool["active"]:
            pool["active"] = True
            pool["warned"] = False
            if pool.get("added_date") is None:
                pool["added_date"] = date_str

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

    db["last_updated"] = date_str
    return db


# ---------------------------------------------------------------------------
# 輸出 docs/today_summary.json
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


def build_summary(date_str, db, category_codes):
    tabs = {cat: build_tab_list(category_codes.get(cat, set()), db) for cat in CATEGORIES}
    tabs["pool"] = build_pool_list(db)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date": date_str,
        "tabs": tabs,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run_pipeline(date_str=None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"=== 處理日期: {date_str} ===")
    date_dir = SCREENSHOTS_DIR / date_str

    print("抓取三大法人買賣超資料（外資 / 主力，僅作為代號有效性校驗與名稱對照）...")
    master = fetch_institutional_master(date_str)
    print(f"  取得 {len(master)} 檔股票的籌碼資料。")
    valid_codes = set(master.keys())

    category_codes = {}
    for cat in LIST_CATEGORIES:
        codes = scan_category_folder(date_dir, cat, valid_codes)
        category_codes[cat] = codes
        print(f"  [{cat}] 辨識出 {len(codes)} 檔: {sorted(codes)}")

    print("解析 super 個股詳細頁（強度完全以此為準）...")
    super_codes, super_detail = scan_super_folder(date_dir, valid_codes)
    category_codes["super"] = super_codes
    print(f"  [super] 辨識出 {len(super_codes)} 檔: {sorted(super_codes)}")

    update_paths, update_detail = scan_update_folder()
    if update_paths:
        print(f"  [update 補漏] {len(update_paths)} 檔: {sorted(update_paths.keys())}")

    detail_updates = {}
    for code, labels in super_detail.items():
        detail_updates.setdefault(code, {}).update(labels)
    for code, labels in update_detail.items():
        detail_updates.setdefault(code, {}).update(labels)

    db = load_tracker_db()
    db = process_day(db, date_str, master, category_codes, detail_updates, update_paths)
    save_tracker_db(db)
    print(f"tracker_db.json 已更新，共追蹤 {len(db['stocks'])} 檔股票。")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    summary = build_summary(date_str, db, category_codes)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"已輸出 {SUMMARY_PATH}")
    print(f"  焦點監控: {len(summary['tabs']['focus'])} 檔 / "
          f"α動能: {len(summary['tabs']['alpha'])} 檔 / "
          f"回檔型: {len(summary['tabs']['pullback'])} 檔 / "
          f"當日Super: {len(summary['tabs']['super'])} 檔 / "
          f"累加型監控池: {len(summary['tabs']['pool'])} 檔")

    return SUMMARY_PATH, date_str


def main():
    parser = argparse.ArgumentParser(description="台股強勢股分析資料處理")
    parser.add_argument("--date", default=None, help="指定處理日期 YYYY-MM-DD，預設為今天")
    args = parser.parse_args()
    run_pipeline(args.date)


if __name__ == "__main__":
    main()
