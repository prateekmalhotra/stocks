"""Task Queue Manager for Async Thesis Ingestion & Monitoring."""

import re
from datetime import datetime
from typing import Optional, List, Any
from stocks.models import WatchlistStock, ThesisVersion, AlertItem, TaskItem
from stocks.data_store import (
    get_stock,
    save_stock,
    load_thesis_history,
    save_thesis_version,
    add_alert
)
from stocks.tracker import fetch_live_stock_info
from stocks.gemini_agent import generate_genesis_thesis, review_stock_thesis, sanitize_labels, normalize_catalyst_date, normalize_action_signal
from stocks.dashboard import render_all


def safe_float(val: Any, default: float) -> float:
    """Safely extracts float from float, int, or string like '$42.50'."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(val).replace(",", ""))
    if match:
        return float(match.group(0))
    return default


def enqueue_task(task: TaskItem):
    """Enqueues a task for execution."""
    _execute_task(task)


def enqueue_genesis(ticker: str, notes: str = ""):
    """Enqueues an initial Living Thesis generation task for a new stock."""
    task = TaskItem(
        id=f"genesis-{ticker.upper()}-{int(datetime.now().timestamp())}",
        task_type="GENESIS",
        ticker=ticker.upper(),
        payload={"notes": notes},
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    enqueue_task(task)


def enqueue_review(ticker: str, trigger_reason: str):
    """Enqueues a thesis review task triggered by a price or catalyst threshold."""
    task = TaskItem(
        id=f"review-{ticker.upper()}-{int(datetime.now().timestamp())}",
        task_type="REVIEW",
        ticker=ticker.upper(),
        payload={"trigger_reason": trigger_reason},
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    enqueue_task(task)


def _handle_genesis_task(ticker: str, notes: str):
    """Executes the Genesis Living Thesis generation for a new stock."""
    company_name, current_price = fetch_live_stock_info(ticker)
    print(f"🔍 Researching {ticker} ({company_name}) at real market price ${current_price:.2f} with Gemini 3.6 Flash + Search...")

    meta, html_content = generate_genesis_thesis(ticker, company_name, current_price, notes)
    labels = sanitize_labels(meta.get("labels") or meta.get("status_label"))
    action_signal = normalize_action_signal(meta.get("action_signal", "BUY"))

    # 1. Create Initial Thesis Version
    today_str = datetime.now().strftime("%Y-%m-%d")
    version_1 = ThesisVersion(
        version=1,
        date=today_str,
        price_at_version=current_price,
        status_label=labels[0] if labels else "Active",
        labels=labels,
        action_signal=action_signal,
        summary_of_change=meta.get("executive_summary", "Initial institutional thesis established."),
        what_was_before="Initial Genesis baseline.",
        what_changes_now=meta.get("executive_summary", "Initial coverage initiated."),
        fair_value_estimate=meta.get("fair_value_estimate", f"${current_price:.2f}"),
        bear_target=meta.get("bear_target", ""),
        base_target=meta.get("base_target", ""),
        bull_target=meta.get("bull_target", ""),
        upper_alert_threshold=safe_float(meta.get("upper_alert_threshold"), current_price * 1.15),
        lower_alert_threshold=safe_float(meta.get("lower_alert_threshold"), current_price * 0.88),
        next_catalyst_date=normalize_catalyst_date(meta.get("next_catalyst_date", "")),
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
        action_signal=action_signal,
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
    action_signal = normalize_action_signal(meta.get("action_signal", "BUY"))
    new_version_num = len(history) + 1
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 1. Create New Thesis Version
    new_version = ThesisVersion(
        version=new_version_num,
        date=today_str,
        price_at_version=current_price,
        status_label=labels[0] if labels else prev_status,
        labels=labels,
        action_signal=action_signal,
        summary_of_change=meta.get("what_changes_now", "Living thesis updated with recent market developments."),
        what_was_before=meta.get("what_was_before", prev_summary),
        what_changes_now=meta.get("what_changes_now", ""),
        fair_value_estimate=meta.get("new_fair_value", stock.fair_value_estimate),
        bear_target=meta.get("new_bear_target", stock.bear_target),
        base_target=meta.get("new_base_target", stock.base_target),
        bull_target=meta.get("new_bull_target", stock.bull_target),
        upper_alert_threshold=safe_float(meta.get("new_upper_alert_threshold"), current_price * 1.15),
        lower_alert_threshold=safe_float(meta.get("new_lower_alert_threshold"), current_price * 0.88),
        next_catalyst_date=normalize_catalyst_date(meta.get("next_catalyst_date", stock.next_catalyst_date)),
        next_catalyst_event=meta.get("next_catalyst_event", stock.next_catalyst_event),
        full_html_content=html_content
    )
    save_thesis_version(ticker, new_version)

    # 2. Update Watchlist Stock
    stock.current_price = current_price
    stock.return_pct = round(((current_price - stock.baseline_price) / stock.baseline_price) * 100, 2)
    stock.status_label = new_version.status_label
    stock.labels = labels
    stock.action_signal = action_signal
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

    # 3. Create Alert Item
    price_change_pct = round(((current_price - stock.baseline_price) / stock.baseline_price) * 100, 2)
    alert_obj = AlertItem(
        id=f"alert-{ticker.lower()}-{int(datetime.now().timestamp())}",
        ticker=ticker,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=meta.get("alert_title", f"{ticker} Alert: Price Threshold Breached"),
        severity=labels[0] if labels else "Review",
        labels=labels,
        action_signal=action_signal,
        trigger_reason=trigger_reason,
        what_was_before=meta.get("what_was_before", prev_summary),
        what_changes_now=meta.get("what_changes_now", "Living thesis updated with recent market developments."),
        price_at_alert=current_price,
        price_change_pct=price_change_pct,
        report_url=f"reports/{ticker}.html"
    )
    add_alert(alert_obj)

    # 4. Re-render HTML Dashboard
    render_all()


def process_task(task: TaskItem):
    """Processes a single task item."""
    _execute_task(task)


def process_all_pending_tasks() -> int:
    """Processes all pending tasks from the data_store queue."""
    from stocks.data_store import load_queue, save_queue
    queue = load_queue()
    if not queue:
        return 0

    processed_count = 0
    remaining_queue = []
    
    for task in queue:
        if task.status in ("PENDING", "IN_PROGRESS"):
            try:
                print(f"🚀 Processing task: {task.task_type} for {task.ticker}...")
                _execute_task(task)
                task.status = "COMPLETED"
                processed_count += 1
            except Exception as e:
                print(f"❌ Failed task {task.id}: {e}")
                task.status = "FAILED"
                remaining_queue.append(task)
        else:
            remaining_queue.append(task)
            
    save_queue(remaining_queue)
    return processed_count


def _execute_task(task: TaskItem):
    """Internal task dispatcher."""
    try:
        if task.task_type in ("GENESIS", "ANALYZE_NEW"):
            notes = task.payload.get("notes", "") if getattr(task, "payload", None) else getattr(task, "notes", "") or ""
            _handle_genesis_task(task.ticker, notes)
        elif task.task_type in ("REVIEW", "PRICE_TRIGGER", "CATALYST_TRIGGER", "SURVEILLANCE_REVIEW"):
            trigger_reason = task.payload.get("trigger_reason", "") if getattr(task, "payload", None) else getattr(task, "notes", "") or "Market Trigger"
            _handle_review_task(task.ticker, trigger_reason)
        else:
            print(f"⚠️ Unknown task type: {task.task_type}")
    except Exception as e:
        print(f"❌ Error executing task {task.id}: {e}")
        raise e
