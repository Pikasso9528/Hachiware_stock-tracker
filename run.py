# -*- coding: utf-8 -*-
"""
一鍵更新：跑完 OCR / 籌碼爬蟲 / tracker_db.json 更新 / docs/today_summary.json 產出，
接著自動 git add + commit + push，將最新資料推送到 GitHub（供 GitHub Pages 顯示）。
"""
import argparse
import subprocess
import sys
from pathlib import Path

import data_processor

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent


def run_git(args):
    return subprocess.run(
        ["git"] + args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def ensure_git_repo():
    check = run_git(["rev-parse", "--is-inside-work-tree"])
    if check.returncode != 0:
        print("尚未初始化 git repository，執行 git init ...")
        init = run_git(["init"])
        print(init.stdout.strip() or init.stderr.strip())
        return False
    return True


def git_commit_and_push():
    had_repo = ensure_git_repo()

    remote = run_git(["remote", "get-url", "origin"])
    has_remote = remote.returncode == 0

    add = run_git(["add", "docs/today_summary.json"])
    if add.returncode != 0:
        print("[WARN] git add 失敗:", add.stderr.strip())
        return

    commit = run_git(["commit", "-m", f"Update stock data - {data_processor.datetime.now().strftime('%Y-%m-%d %H:%M')}"])
    if commit.returncode != 0:
        msg = (commit.stdout + commit.stderr).strip()
        if "nothing to commit" in msg or "無需要提交" in msg or "尚無" in msg:
            print("目前沒有資料變更，略過提交。")
        else:
            print("[WARN] git commit 失敗:")
            print(msg)
        return
    print(commit.stdout.strip())

    if not has_remote:
        print("\n[提醒] 尚未設定 git remote 'origin'，已略過推送。")
        print("請先在 GitHub 建立一個 repository，然後執行：")
        print(f"  git remote add origin <你的 GitHub repo URL>")
        print(f"  git push -u origin {current_branch()}")
        print("並到 GitHub repo 的 Settings > Pages，將來源設定為 main 分支的 /docs 目錄。")
        return

    push = run_git(["push"])
    if push.returncode != 0:
        # 常見情況：遠端分支尚未有上游追蹤，補做一次帶 -u 的 push
        branch = current_branch()
        push2 = run_git(["push", "-u", "origin", branch])
        if push2.returncode != 0:
            print("[WARN] git push 失敗:")
            print(push2.stderr.strip())
            return
        print(push2.stdout.strip() or push2.stderr.strip())
    else:
        print(push.stdout.strip() or push.stderr.strip())
    print("已推送最新資料到 GitHub。")


def current_branch():
    r = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    return r.stdout.strip() if r.returncode == 0 else "main"


def main():
    parser = argparse.ArgumentParser(description="一鍵更新台股強勢股資料並推送到 GitHub Pages")
    parser.add_argument("--date", default=None, help="指定處理日期 YYYY-MM-DD，預設為今天")
    parser.add_argument("--no-push", action="store_true", help="只更新資料，不執行 git commit/push")
    args = parser.parse_args()

    summary_path, date_str = data_processor.run_pipeline(args.date)

    if args.no_push:
        print("已依 --no-push 略過 git 提交/推送。")
        return

    print("\n=== Git 提交與推送 ===")
    git_commit_and_push()


if __name__ == "__main__":
    sys.exit(main())
