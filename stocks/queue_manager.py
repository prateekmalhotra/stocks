"""Task Queue Manager for Async Thesis Ingestion & Monitoring."""

import re
import time
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
from stocks.gemini_agent import (
    generate_genesis_thesis,
    review_stock_thesis,
    sanitize_labels,
    normalize_catalyst_date,
    normalize_action_signal,
    CANONICAL_MOAT_LABELS,
    CANONICAL_CONVICTION_TIERS
)
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
    from stocks.ownership_intelligence import fetch_and_cache_complete_ownership, parse_trade_value
    
    company_name, current_price = fetch_live_stock_info(ticker)
    print(f"🔍 Fetching live OpenInsider Form 4s and Dataroma superinvestors for {ticker} ({company_name})...")
    ownership_data = fetch_and_cache_complete_ownership(ticker, company_name)
    
    max_genesis_attempts = 3
    meta, html_content = {}, ""
    for attempt in range(1, max_genesis_attempts + 1):
        print(f"\n🚀 [GENESIS EXECUTION] Generating complete institutional dossier for {ticker} ({company_name}) at ${current_price:.2f} (Attempt {attempt}/{max_genesis_attempts})...", flush=True)
        meta, html_content = generate_genesis_thesis(ticker, company_name, current_price, notes)
        from stocks.gemini_agent import verify_and_repair_html_structure
        html_content = verify_and_repair_html_structure(html_content)
        
        from stocks.quality_gatekeeper import validate_dossier_quality
        is_valid, quality_issues = validate_dossier_quality(ticker, html_content, metadata=meta)
        if is_valid:
            print(f"✅ [QUALITY GATE PASSED] {ticker} passed 100% of institutional quality pillars on attempt {attempt}!", flush=True)
            break
        else:
            print(f"⚠️ [QUALITY GATE WARNING] {ticker} quality audit flagged issues on attempt {attempt}:", flush=True)
            for issue in quality_issues:
                print(f"   └─ {issue}", flush=True)
            if attempt < max_genesis_attempts:
                print(f"🔄 [AUTO-RETRY] Automatically re-running genesis pipeline for {ticker} (waiting 20s for API cool-down)...", flush=True)
                time.sleep(20)

    labels = sanitize_labels(meta.get("labels") or meta.get("status_label"), action_signal=meta.get("action_signal"))
    action_signal = normalize_action_signal(meta.get("action_signal", "BUY"))

    # 1. Create Initial Thesis Version
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Format top funds from real Dataroma scrape if available
    dr_holders = ownership_data.get("dataroma_holders", [])
    if dr_holders:
        top_funds = [f"{h.get('manager')} ({h.get('pct_of_portfolio', '')})" for h in dr_holders[:10]]
    else:
        raw_funds = meta.get("top_funds") or []
        top_funds = [f if isinstance(f, str) else str(f) for f in raw_funds]
        
    raw_inst = meta.get("institutional_ownership_pct")
    if raw_inst and str(raw_inst).strip() not in ("N/A", "None", "", "TBD") and "%" in str(raw_inst):
        inst_pct = str(raw_inst).strip()
    elif dr_holders:
        inst_pct = f"{len(dr_holders)} Whales" if len(dr_holders) > 1 else f"{len(dr_holders)} Whale"
    else:
        inst_pct = "0 Tracked"
    
    # Derive insider signal from Form 4 trades
    oi_trades = ownership_data.get("openinsider_trades", [])
    insider_signal = meta.get("insider_signal") or "Neutral (10b5-1)"
    insider_summary = meta.get("insider_summary") or ""
    if oi_trades:
        buy_val = sum([parse_trade_value(t.get("value", "")) for t in oi_trades if "Buy" in t.get("trade_type", "") or "P - Purchase" in t.get("trade_type", "")])
        sell_val = sum([parse_trade_value(t.get("value", "")) for t in oi_trades if "Sale" in t.get("trade_type", "") or "S - Sale" in t.get("trade_type", "")])
        sentiment = ownership_data.get("sentiment", {})
        insider_signal = sentiment.get("signal", "Neutral (10b5-1)")
        insider_summary = sentiment.get("summary", "Audited SEC Form 3 / 20-F / Form 4 filings.")

    version_1 = ThesisVersion(
        version=1,
        date=today_str,
        price_at_version=current_price,
        status_label=labels[0] if labels else "Narrow Moat",
        labels=labels,
        action_signal=action_signal,
        summary_of_change=meta.get("executive_summary", "Initial institutional thesis established."),
        what_was_before="Initial Genesis baseline.",
        what_changes_now=meta.get("executive_summary", "Initial coverage initiated."),
        fair_value_estimate=meta.get("fair_value_estimate", f"${current_price:.2f}"),
        story1_target=meta.get("story1_target", ""),
        story2_target=meta.get("story2_target", ""),
        story3_target=meta.get("story3_target", ""),
        story1_title=meta.get("story1_title", ""),
        story2_title=meta.get("story2_title", ""),
        story3_title=meta.get("story3_title", ""),
        bear_target=meta.get("bear_target", ""),
        base_target=meta.get("base_target", ""),
        bull_target=meta.get("bull_target", ""),
        upper_alert_threshold=safe_float(meta.get("upper_alert_threshold"), None),
        lower_alert_threshold=safe_float(meta.get("lower_alert_threshold"), None),
        next_catalyst_date=normalize_catalyst_date(meta.get("next_catalyst_date", "")),
        next_catalyst_event=meta.get("next_catalyst_event", ""),
        trigger_reason="Genesis Initial Underwriting",
        what_is_priced_in=meta.get("what_is_priced_in", ""),
        top_funds=top_funds,
        institutional_ownership_pct=inst_pct,
        insider_signal=insider_signal,
        insider_summary=insider_summary,
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
        story1_target=version_1.story1_target,
        story2_target=version_1.story2_target,
        story3_target=version_1.story3_target,
        story1_title=version_1.story1_title,
        story2_title=version_1.story2_title,
        story3_title=version_1.story3_title,
        bear_target=version_1.bear_target,
        base_target=version_1.base_target,
        bull_target=version_1.bull_target,
        what_is_priced_in=version_1.what_is_priced_in,
        upper_alert_threshold=version_1.upper_alert_threshold,
        lower_alert_threshold=version_1.lower_alert_threshold,
        next_catalyst_date=version_1.next_catalyst_date,
        next_catalyst_event=version_1.next_catalyst_event,
        top_funds=top_funds,
        institutional_ownership_pct=inst_pct,
        insider_signal=insider_signal,
        insider_summary=insider_summary,
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
        previous_version_num=len(history),
        previous_fair_value=stock.fair_value_estimate,
        previous_bear_target=stock.bear_target,
        previous_base_target=stock.base_target,
        previous_bull_target=stock.bull_target
    )

    labels = sanitize_labels(meta.get("labels") or meta.get("new_status_label") or prev_status, action_signal=meta.get("action_signal"))
    action_signal = normalize_action_signal(meta.get("action_signal", "BUY"))
    new_version_num = len(history) + 1
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 1. Create New Thesis Version
    from stocks.ownership_intelligence import fetch_and_cache_complete_ownership
    ownership_data = fetch_and_cache_complete_ownership(ticker, company_name)
    dr_holders = ownership_data.get("dataroma_holders", [])
    if dr_holders:
        top_funds = [f"{h.get('manager')} ({h.get('pct_of_portfolio', '')})" for h in dr_holders[:10]]
    else:
        raw_funds = meta.get("top_funds") or stock.top_funds or []
        top_funds = [f if isinstance(f, str) else str(f) for f in raw_funds]

    raw_inst = meta.get("institutional_ownership_pct") or stock.institutional_ownership_pct or ""
    if raw_inst and str(raw_inst).strip() not in ("N/A", "None", "", "TBD") and "%" in str(raw_inst):
        inst_pct = str(raw_inst).strip()
    elif top_funds:
        inst_pct = f"{len(top_funds)} Whales" if len(top_funds) > 1 else f"{len(top_funds)} Whale"
    else:
        inst_pct = "0 Tracked"
    insider_signal = meta.get("insider_signal") or stock.insider_signal or "Neutral (10b5-1)"
    insider_summary = meta.get("insider_summary") or stock.insider_summary or ""

    new_version = ThesisVersion(
        version=new_version_num,
        date=today_str,
        price_at_version=current_price,
        status_label=labels[0] if labels else (prev_status if prev_status in CANONICAL_MOAT_LABELS else "Narrow Moat"),
        labels=labels,
        action_signal=action_signal,
        summary_of_change=meta.get("what_changes_now", "Living thesis updated with recent market developments."),
        what_was_before=meta.get("what_was_before", prev_summary),
        fair_value_estimate=meta.get("fair_value_estimate") or meta.get("new_fair_value") or stock.fair_value_estimate,
        story1_target=meta.get("story1_target", stock.story1_target or ""),
        story2_target=meta.get("story2_target", stock.story2_target or ""),
        story3_target=meta.get("story3_target", stock.story3_target or ""),
        story1_title=meta.get("story1_title", stock.story1_title or "Storyline 1"),
        story2_title=meta.get("story2_title", stock.story2_title or "Storyline 2"),
        story3_title=meta.get("story3_title", stock.story3_title or "Storyline 3"),
        bear_target=meta.get("bear_target") or meta.get("new_bear_target") or stock.bear_target,
        base_target=meta.get("base_target") or meta.get("new_base_target") or stock.base_target,
        bull_target=meta.get("bull_target") or meta.get("new_bull_target") or stock.bull_target,
        upper_alert_threshold=safe_float(meta.get("upper_alert_threshold") or meta.get("new_upper_alert_threshold"), None),
        lower_alert_threshold=safe_float(meta.get("lower_alert_threshold") or meta.get("new_lower_alert_threshold"), None),
        next_catalyst_date=normalize_catalyst_date(meta.get("next_catalyst_date") or stock.next_catalyst_date),
        next_catalyst_event=meta.get("next_catalyst_event") or stock.next_catalyst_event,
        trigger_reason=trigger_reason,
        what_is_priced_in=meta.get("what_is_priced_in") or stock.what_is_priced_in or "",
        top_funds=top_funds,
        institutional_ownership_pct=inst_pct,
        insider_signal=insider_signal,
        insider_summary=insider_summary,
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
    stock.story1_target = new_version.story1_target
    stock.story2_target = new_version.story2_target
    stock.story3_target = new_version.story3_target
    stock.story1_title = new_version.story1_title
    stock.story2_title = new_version.story2_title
    stock.story3_title = new_version.story3_title
    stock.bear_target = new_version.bear_target
    stock.base_target = new_version.base_target
    stock.bull_target = new_version.bull_target
    stock.what_is_priced_in = new_version.what_is_priced_in
    stock.upper_alert_threshold = new_version.upper_alert_threshold
    stock.lower_alert_threshold = new_version.lower_alert_threshold
    stock.next_catalyst_date = new_version.next_catalyst_date
    stock.next_catalyst_event = new_version.next_catalyst_event
    stock.top_funds = top_funds
    stock.institutional_ownership_pct = inst_pct
    stock.insider_signal = insider_signal
    stock.insider_summary = insider_summary
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

    # 4. If this review was an Earnings Catalyst, reset prior cycle and register new Beat & Retrace Pop Watcher
    if "earnings" in trigger_reason.lower() or "catalyst" in trigger_reason.lower():
        try:
            from stocks.earnings_retrace import reset_earnings_cycle, register_earnings_pop
            reset_earnings_cycle(ticker)
            register_earnings_pop(
                ticker=ticker,
                earnings_date=today_str,
                pre_earnings_price=stock.baseline_price,
                peak_price=current_price,
                notes=f"Quarterly Earnings Review ({trigger_reason})"
            )
        except Exception as e:
            print(f"⚠️ Beat & Retrace registration warning: {e}")

    # 5. Re-render HTML Dashboard
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
        elif task.task_type in ("REVIEW", "PRICE_TRIGGER", "CATALYST_TRIGGER", "SURVEILLANCE_REVIEW", "SEC_8K_TRIGGER", "SEC_FILING_TRIGGER"):
            trigger_reason = task.payload.get("trigger_reason", "") if getattr(task, "payload", None) else getattr(task, "notes", "") or "Market Trigger"
            _handle_review_task(task.ticker, trigger_reason)
        else:
            print(f"⚠️ Unknown task type: {task.task_type}")
    except Exception as e:
        print(f"❌ Error executing task {task.id}: {e}")
        raise e
