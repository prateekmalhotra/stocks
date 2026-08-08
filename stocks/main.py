"""CLI Entry point for Equity Living Thesis & 24/7 Surveillance Engine."""

import sys
import re
import argparse
from datetime import datetime
from typing import List
from stocks.models import TaskItem
from stocks.data_store import enqueue_task, load_watchlist, load_queue, load_alerts, get_stock
from stocks.tracker import check_watchlist_triggers
from stocks.queue_manager import process_all_pending_tasks, process_task
from stocks.dashboard import render_all


def cmd_add(tickers: List[str], notes: str = "", force: bool = False):
    """Enqueues and processes one or more new stock analyses (supports comma, semicolon, or space-separated lists)."""
    watchlist = load_watchlist()
    enqueued = []

    # Flatten and parse comma, semicolon, and space separated tickers
    parsed_tickers = []
    for raw_arg in tickers:
        for item in re.split(r"[,;\s]+", raw_arg):
            clean = item.upper().strip()
            if clean and clean not in parsed_tickers:
                parsed_tickers.append(clean)

    for ticker in parsed_tickers:
        if ticker in watchlist and not force:
            print(f"⏭️ [SKIPPED] {ticker} already has an active thesis in watchlist. Use --force to re-analyze.")
            continue

        task = TaskItem(
            id=f"genesis_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            task_type="ANALYZE_NEW",
            ticker=ticker,
            notes=notes,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        enqueue_task(task)
        enqueued.append(ticker)
        print(f"📥 [ENQUEUED] Genesis Research task for {ticker}.")

    if enqueued:
        print(f"\n⚡ Processing {len(enqueued)} enqueued stock(s): {', '.join(enqueued)}...")
        process_all_pending_tasks()
        render_all()


def cmd_check():
    """Runs surveillance trigger checks on all watchlist stocks."""
    print("🔍 Running surveillance trigger check across watchlist...")
    triggers = check_watchlist_triggers()
    print(f"Done. Triggered {triggers} review tasks.")


def cmd_process():
    """Processes all pending tasks in the queue."""
    print("⚡ Processing all pending queue tasks...")
    count = process_all_pending_tasks()
    print(f"Done. Processed {count} tasks.")


def cmd_run():
    """Full end-to-end pass for 24/7 cron (Check triggers + Process queue + Render HTML)."""
    print(f"🚀 [SURVEILLANCE CYCLE START] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    check_watchlist_triggers()
    process_all_pending_tasks()
    render_all()
    print(f"🏁 [SURVEILLANCE CYCLE COMPLETE] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def cmd_list():
    """Prints active watchlist and triggers in terminal."""
    watchlist = load_watchlist()
    if not watchlist:
        print("Watchlist is currently empty.")
        return

    print("\n" + "=" * 90)
    print(f"{'TICKER':<8} {'PRICE':<10} {'RETURN':<10} {'FAIR VAL':<12} {'TRIGGERS (L - U)':<22} {'STATUS'}")
    print("=" * 90)
    for ticker, s in sorted(watchlist.items()):
        ret_str = f"{s.return_pct:+.1f}%"
        bounds_str = f"${s.lower_alert_threshold:.1f} - ${s.upper_alert_threshold:.1f}" if s.lower_alert_threshold and s.upper_alert_threshold else "N/A"
        print(f"{s.ticker:<8} ${s.current_price:<9.2f} {ret_str:<10} {s.fair_value_estimate:<12} {bounds_str:<22} {s.status_label}")
    print("=" * 90 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Equity Living Thesis & Surveillance Engine")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # add (supports multiple tickers: python -m stocks.main add NVDA AAPL TSLA ...)
    p_add = subparsers.add_parser("add", help="Add and analyze one or more stocks")
    p_add.add_argument("tickers", nargs="+", help="One or more stock tickers (e.g. NVDA AAPL TSLA)")
    p_add.add_argument("--notes", default="", help="Optional context or user notes for the LLM")
    p_add.add_argument("--force", action="store_true", help="Force re-analysis even if thesis exists")

    # check
    subparsers.add_parser("check", help="Check watchlist against alert triggers")

    # process
    subparsers.add_parser("process", help="Process pending queue tasks")

    # run (check + process + render)
    subparsers.add_parser("run", help="Execute complete surveillance cycle (for cron / GitHub Actions)")

    # list
    subparsers.add_parser("list", help="List tracked stocks and trigger boundaries")

    # render
    subparsers.add_parser("render", help="Recompile all HTML reports and dashboard")

    args = parser.parse_args()

    if args.command == "add":
        cmd_add(args.tickers, args.notes, force=args.force)
    elif args.command == "check":
        cmd_check()
    elif args.command == "process":
        cmd_process()
    elif args.command == "run":
        cmd_run()
    elif args.command == "list":
        cmd_list()
    elif args.command == "render":
        render_all()
        print("✅ Recompiled public/index.html and all company reports.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
