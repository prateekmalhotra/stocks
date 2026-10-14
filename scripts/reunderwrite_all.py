"""Re-underwrite every ticker through the strict QA-gated pipeline.

- Theses that pass QA are appended as a new version (history preserved).
- Theses that fail QA after the full retry budget are NOT saved; the previous version stays live
  and the failure is recorded in data/reunderwrite_progress.json with the exact defects.
- Resumable: tickers already marked "passed" are skipped unless --force.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/reunderwrite_all.py [--tickers AAPL MSFT] [--workers 3] [--force] [--dry-run]
"""

import argparse
import concurrent.futures
import json
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
PROGRESS_FILE = ROOT / "data" / "reunderwrite_progress.json"
_lock = threading.Lock()


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except Exception:
            return {}
    return {}


def record(ticker: str, entry: dict):
    with _lock:
        prog = load_progress()
        prog[ticker] = entry
        tmp = PROGRESS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(prog, indent=2))
        tmp.replace(PROGRESS_FILE)


def run_one(ticker: str, dry_run: bool) -> dict:
    from stocks.thesis_qa import ThesisQAError
    from stocks.data_store import get_stock
    start = time.time()
    try:
        if dry_run:
            from stocks.tracker import fetch_live_stock_info
            from stocks.gemini_agent import generate_genesis_thesis
            name, price = fetch_live_stock_info(ticker)
            meta, _ = generate_genesis_thesis(ticker, name, price)
            result = {"status": "passed", "dry_run": True, "fv": meta.get("fair_value_estimate"),
                      "price": price, "signal": meta.get("action_signal"), "qa": meta.get("qa_attempts")}
        elif get_stock(ticker):
            from stocks.queue_manager import _handle_review_task
            _handle_review_task(ticker, "Full QA re-underwrite", emit_alert=False, render=False)
            result = {"status": "passed"}
        else:
            from stocks.queue_manager import _handle_genesis_task
            _handle_genesis_task(ticker, "")
            result = {"status": "passed"}
    except ThesisQAError as e:
        result = {"status": "failed", "error": str(e).split(" | ")[0], "issues": e.issues}
    except Exception as e:
        result = {"status": "error", "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
    result["seconds"] = round(time.time() - start)
    result["ts"] = datetime.now().isoformat(timespec="seconds")
    return result


def run_one_with_retry(ticker: str, dry_run: bool) -> dict:
    res = run_one(ticker, dry_run)
    for _ in range(2):
        if res["status"] != "error":
            break
        print(f"  ↻ {ticker}: transient error, retrying ({res.get('error', '')[:120]})", flush=True)
        time.sleep(20)
        res = run_one(ticker, dry_run)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="*", default=[])
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from stocks.data_store import load_watchlist
    if args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        theses = [p.stem.upper() for p in (ROOT / "data" / "theses").glob("*.json")]
        tickers = sorted(set(load_watchlist().keys()) | set(theses))

    prog = load_progress()
    if not args.force and not args.dry_run:
        tickers = [t for t in tickers if prog.get(t, {}).get("status") != "passed"]
    print(f"Re-underwriting {len(tickers)} tickers with {args.workers} workers (dry_run={args.dry_run})", flush=True)

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one_with_retry, t, args.dry_run): t for t in tickers}
        for fut in concurrent.futures.as_completed(futs):
            t = futs[fut]
            res = fut.result()
            if not args.dry_run:
                record(t, res)
            done += 1
            print(f"\n===== [{done}/{len(tickers)}] {t}: {res['status'].upper()} ({res['seconds']}s) "
                  f"{res.get('error', '')} {res.get('issues', '')[:3] if res.get('issues') else ''} "
                  f"{('FV ' + str(res.get('fv')) + ' @ ' + str(res.get('price'))) if res.get('fv') else ''}", flush=True)

    if not args.dry_run:
        from stocks.dashboard import render_all
        render_all()
        prog = load_progress()
        summary = {}
        for v in prog.values():
            summary[v["status"]] = summary.get(v["status"], 0) + 1
        print(f"\nDONE. Summary: {summary}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
