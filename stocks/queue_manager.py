"""Asynchronous Task Queue Manager for Batching & Living Surveillance."""

import traceback
from datetime import datetime
from typing import Optional, List
from stocks.models import TaskItem, WatchlistStock, ThesisVersion, AlertItem
from stocks.data_store import (
    load_queue,
    save_queue,
    pop_next_pending_task,
    update_task_status,
    get_stock,
    save_stock,
    load_thesis_history,
    save_thesis_version,
    add_alert
)
from stocks.tracker import fetch_live_stock_info
from stocks.gemini_agent import generate_genesis_thesis, review_stock_thesis, sanitize_labels
from stocks.dashboard import render_all


def process_next_task() -> Optional[TaskItem]:
    """Pops the next pending task, executes the LLM research pipeline, and updates the store."""
    task = pop_next_pending_task()
    if not task:
        return None

    update_task_status(task.id, status="IN_PROGRESS")
    print(f"\n⚡ [PROCESSING TASK] ID: {task.id} | Type: {task.task_type} | Ticker: {task.ticker}")

    try:
        if task.task_type == "ANALYZE_NEW":
            _handle_genesis_task(task.ticker, task.notes or "")
        elif task.task_type in ("PRICE_TRIGGER", "CATALYST_REVIEW"):
            _handle_review_task(task.ticker, task.notes or "Price threshold breach")
        else:
            raise ValueError(f"Unknown task type: {task.task_type}")

        update_task_status(task.id, status="COMPLETED")
        print(f"✅ [TASK COMPLETED] {task.id} for {task.ticker}\n")
        return task

    except Exception as e:
        print(f"❌ [TASK FAILED] {task.id} for {task.ticker}: {e}")
        traceback.print_exc()
        update_task_status(task.id, status="FAILED", error=str(e))
        raise


def _handle_genesis_task(ticker: str, notes: str):
    """Executes the Genesis Living Thesis generation for a new stock."""
    company_name, current_price = fetch_live_stock_info(ticker)
    print(f"🔍 Researching {ticker} ({company_name}) at real market price ${current_price:.2f} with Gemini 3.6 Flash + Search...")

    meta, html_content = generate_genesis_thesis(ticker, company_name, current_price, notes)
    labels = sanitize_labels(meta.get("labels") or meta.get("status_label"))

    # 1. Create Initial Thesis Version
    today_str = datetime.now().strftime("%Y-%m-%d")
    version_1 = ThesisVersion(
        version=1,
        date=today_str,
        price_at_version=current_price,
        status_label=labels[0] if labels else "Active",
        labels=labels,
        summary_of_change=meta.get("executive_summary", "Initial institutional thesis established."),
        what_was_before="Initial Genesis baseline.",
        what_changes_now=meta.get("executive_summary", "Initial coverage initiated."),
        fair_value_estimate=meta.get("fair_value_estimate", f"${current_price:.2f}"),
        bear_target=meta.get("bear_target", ""),
        base_target=meta.get("base_target", ""),
        bull_target=meta.get("bull_target", ""),
        upper_alert_threshold=float(meta.get("upper_alert_threshold", current_price * 1.15)),
        lower_alert_threshold=float(meta.get("lower_alert_threshold", current_price * 0.88)),
        next_catalyst_date=meta.get("next_catalyst_date", ""),
        next_catalyst_event=meta.get("next_catalyst_event", ""),
        full_html_content=html_content
    )
    save_thesis_version(ticker, version_1)

    # 2. Create Watchlist Stock Record
    stock_record = WatchlistStock(
        ticker=ticker,
        company_name=company_name,
        baseline_price=current_price,
        current_price=current_price,
        return_pct=0.0,
        status_label=version_1.status_label,
        labels=labels,
        fair_value_estimate=version_1.fair_value_estimate,
        bear_target=version_1.bear_target,
        base_target=version_1.base_target,
        bull_target=version_1.bull_target,
        upper_alert_threshold=version_1.upper_alert_threshold,
        lower_alert_threshold=version_1.lower_alert_threshold,
        next_catalyst_date=version_1.next_catalyst_date,
        next_catalyst_event=version_1.next_catalyst_event,
        last_updated=today_str,
        total_versions=1,
        report_path=f"reports/{ticker}.html"
    )
    save_stock(stock_record)
    render_all()


def _handle_review_task(ticker: str, trigger_reason: str):
    """Executes a Living Thesis Review when a price threshold or catalyst is triggered and emits an alert."""
    stock = get_stock(ticker)
    if not stock:
        raise ValueError(f"Cannot review {ticker}: Stock not found in watchlist.")

    company_name, current_price = fetch_live_stock_info(ticker)
    history = load_thesis_history(ticker)
    last_version = history[-1] if history else None
    
    prev_summary = last_version.summary_of_change if last_version else "Previous initial thesis."
    prev_status = stock.status_label

    print(f"⚡ Reviewing {ticker} ({company_name}) at ${current_price:.2f} due to: {trigger_reason}")

    meta, html_content = review_stock_thesis(
        ticker=ticker,
        company_name=company_name,
        previous_thesis_summary=prev_summary,
        previous_status=prev_status,
        trigger_reason=trigger_reason,
        baseline_price=stock.baseline_price,
        current_price=current_price,
        previous_version_num=len(history)
    )

    labels = sanitize_labels(meta.get("labels") or meta.get("new_status_label"))
    new_version_num = len(history) + 1
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 1. Create New Thesis Version
    new_version = ThesisVersion(
        version=new_version_num,
        date=today_str,
        price_at_version=current_price,
        status_label=labels[0] if labels else prev_status,
        labels=labels,
        summary_of_change=meta.get("what_changes_now", "Living thesis updated with recent market developments."),
        what_was_before=meta.get("what_was_before", prev_summary),
        what_changes_now=meta.get("what_changes_now", ""),
        fair_value_estimate=meta.get("new_fair_value", stock.fair_value_estimate),
        bear_target=meta.get("new_bear_target", stock.bear_target),
        base_target=meta.get("new_base_target", stock.base_target),
        bull_target=meta.get("new_bull_target", stock.bull_target),
        upper_alert_threshold=float(meta.get("new_upper_alert_threshold", current_price * 1.15)),
        lower_alert_threshold=float(meta.get("new_lower_alert_threshold", current_price * 0.88)),
        next_catalyst_date=meta.get("next_catalyst_date", stock.next_catalyst_date),
        next_catalyst_event=meta.get("next_catalyst_event", stock.next_catalyst_event),
        full_html_content=html_content
    )
    save_thesis_version(ticker, new_version)

    # 2. Update Watchlist Stock
    stock.current_price = current_price
    stock.return_pct = round(((current_price - stock.baseline_price) / stock.baseline_price) * 100, 2)
    stock.status_label = new_version.status_label
    stock.labels = labels
    stock.fair_value_estimate = new_version.fair_value_estimate
    stock.bear_target = new_version.bear_target
    stock.base_target = new_version.base_target
    stock.bull_target = new_version.bull_target
    stock.upper_alert_threshold = new_version.upper_alert_threshold
    stock.lower_alert_threshold = new_version.lower_alert_threshold
    stock.next_catalyst_date = new_version.next_catalyst_date
    stock.next_catalyst_event = new_version.next_catalyst_event
    stock.last_updated = today_str
    stock.total_versions = new_version_num
    save_stock(stock)

    # 3. Create Alert Record
    price_change_pct = ((current_price - stock.baseline_price) / stock.baseline_price) * 100 if stock.baseline_price else 0.0
    alert_obj = AlertItem(
        id=f"alert_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        ticker=ticker,
        timestamp=datetime.now().strftime("%b %d, %Y • %I:%M %p"),
        title=meta.get("alert_title", f"{ticker} Thesis Review"),
        severity=labels[0] if labels else "Review",
        labels=labels,
        trigger_reason=trigger_reason,
        what_was_before=new_version.what_was_before or "Previous baseline",
        what_changes_now=new_version.what_changes_now or new_version.summary_of_change,
        price_at_alert=current_price,
        price_change_pct=price_change_pct,
        report_url=f"reports/{ticker}.html"
    )
    add_alert(alert_obj)

    # 4. Re-render HTML Dashboard
    render_all()


def process_all_pending_tasks():
    """Processes all enqueued tasks in the queue until empty."""
    queue = load_queue()
    pending = [t for t in queue if t.status == "PENDING"]
    if not pending:
        print("No pending tasks in queue.")
        return

    print(f"⚡ Processing {len(pending)} enqueued stock(s)...")
    while True:
        task = process_next_task()
        if not task:
            break
