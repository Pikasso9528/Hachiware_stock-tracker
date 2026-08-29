# -*- coding: utf-8 -*-
"""
台股強勢股分析 - 資料處理核心
讀取每日分類截圖 -> OCR 辨識股票代號 -> 爬取三大法人買賣超 -> 更新 tracker_db.json
-> 輸出瘦身後的 docs/today_summary.json 供 GitHub Pages 儀表板使用。
"""
import argparse
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
IMAGE_EXTS = (".png", ".jpg", ".jpeg")

STRONG_THRESHOLD = 1000   # 張，超過視為偏強/偏弱訊號門檻
EXTREME_THRESHOLD = 5000  # 張，超過視為極強/弱訊號門檻

STRONG_LEVELS = {"極強", "偏強"}
WEAK_LEVELS = {"弱", "偏弱"}
UNKNOWN_LEVEL = "未更新"

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


def classify_strength(net_lots):
    if net_lots is None:
        return UNKNOWN_LEVEL
    if net_lots >= EXTREME_THRESHOLD:
        return "極強"
    if net_lots >= STRONG_THRESHOLD:
        return "偏強"
    if net_lots <= -EXTREME_THRESHOLD:
        return "弱"
    if net_lots <= -STRONG_THRESHOLD:
        return "偏弱"
    return "中立"


# ---------------------------------------------------------------------------
# OCR：從截圖左側「股票名稱/代號」欄位擷取股票代號
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


def scan_update_folder():
    """補漏資料夾：檔名即股票代號，例如 8358.png。"""
    codes = {}
    if not UPDATE_DIR.exists():
        return codes
    for img_path in sorted(UPDATE_DIR.iterdir()):
        if img_path.suffix.lower() not in IMAGE_EXTS:
            continue
        m = re.match(r"(\d{4,6})", img_path.stem)
        if m:
            codes[m.group(1)] = img_path
    return codes


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


def process_day(db, date_str, master, category_codes, update_codes):
    today_all_category_codes = set()
    for codes in category_codes.values():
        today_all_category_codes |= codes

    pool_active_codes = {
        code for code, info in db["stocks"].items()
        if info.get("pool", {}).get("active")
    }

    codes_needing_entry = today_all_category_codes | pool_active_codes | set(update_codes.keys())

    for code in codes_needing_entry:
        entry = db["stocks"].setdefault(code, {
            "name": master.get(code, {}).get("name", "—"),
            "market": master.get(code, {}).get("market", "TW"),
            "history": [],
        })
        if code in master:
            entry["name"] = master[code]["name"]
            entry["market"] = master[code]["market"]

        if code in category_codes.get("super", set()):
            source, has_shot = "super", True
        elif code in update_codes:
            source, has_shot = "update", True
        elif code in today_all_category_codes:
            source, has_shot = "category", True
        else:
            source, has_shot = "missing", False

        if has_shot:
            net = None
            if code in master:
                net = master[code]["foreign_lots"] + master[code]["main_lots"]
            strength = classify_strength(net)
        else:
            strength = UNKNOWN_LEVEL

        hist = entry["history"]
        record = {"date": date_str, "strength": strength, "source": source}
        if hist and hist[-1]["date"] == date_str:
            hist[-1] = record
        else:
            hist.append(record)

        pool = entry.setdefault("pool", {"active": False, "warned": False, "added_date": None})
        if code in category_codes.get("super", set()) and not pool["active"]:
            pool["active"] = True
            pool["warned"] = False
            if pool.get("added_date") is None:
                pool["added_date"] = date_str

        if pool["active"]:
            if pool["warned"]:
                if strength in STRONG_LEVELS:
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
        if not entry or not entry["history"]:
            continue
        items.append({
            "code": code,
            "name": entry.get("name", "—"),
            "market": entry.get("market", "TW"),
            "today_strength": entry["history"][-1]["strength"],
            "stars": last5_stars(entry["history"]),
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

    print("抓取三大法人買賣超資料（外資 / 主力）...")
    master = fetch_institutional_master(date_str)
    print(f"  取得 {len(master)} 檔股票的籌碼資料。")
    valid_codes = set(master.keys())

    category_codes = {}
    for cat in CATEGORIES:
        codes = scan_category_folder(date_dir, cat, valid_codes)
        category_codes[cat] = codes
        print(f"  [{cat}] 辨識出 {len(codes)} 檔: {sorted(codes)}")

    update_codes = scan_update_folder()
    if update_codes:
        print(f"  [update 補漏] {len(update_codes)} 檔: {sorted(update_codes.keys())}")

    db = load_tracker_db()
    db = process_day(db, date_str, master, category_codes, update_codes)
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
