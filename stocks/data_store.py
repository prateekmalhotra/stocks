"""Persistent JSON data store for watchlists, alerts, thesis history, and task queue."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from stocks.models import WatchlistStock, AlertItem, ThesisVersion, TaskItem

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
THESES_DIR = DATA_DIR / "theses"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"
ALERTS_FILE = DATA_DIR / "alerts.json"
QUEUE_FILE = DATA_DIR / "queue.json"


def _ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    THESES_DIR.mkdir(parents=True, exist_ok=True)


# ==================== WATCHLIST ====================

def load_watchlist() -> Dict[str, WatchlistStock]:
    _ensure_dirs()
    if not WATCHLIST_FILE.exists():
        return {}
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return {item["ticker"].upper(): WatchlistStock(**item) for item in data if isinstance(item, dict) and "ticker" in item}
            elif isinstance(data, dict):
                return {k.upper(): WatchlistStock(**v) if isinstance(v, dict) else v for k, v in data.items()}
            return {}
    except Exception as e:
        return {}


import threading

_WRITE_LOCK = threading.RLock()


def _atomic_write_json(path: Path, payload: Any):
    """Write JSON via temp file + rename so readers never observe a partially written file."""
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}.{threading.get_ident()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def save_watchlist(watchlist: Dict[str, WatchlistStock]):
    _ensure_dirs()
    serializable = {k: v.model_dump() for k, v in watchlist.items()}
    with _WRITE_LOCK:
        _atomic_write_json(WATCHLIST_FILE, serializable)


def get_stock(ticker: str) -> Optional[WatchlistStock]:
    return load_watchlist().get(ticker.upper())


def save_stock(stock: WatchlistStock):
    with _WRITE_LOCK:
        wl = load_watchlist()
        if not wl and WATCHLIST_FILE.exists() and WATCHLIST_FILE.stat().st_size > 100:
            raise RuntimeError("Refusing to overwrite a non-empty watchlist that failed to load.")
        wl[stock.ticker.upper()] = stock
        save_watchlist(wl)


def delete_stock(ticker: str) -> bool:
    """Completely removes a stock from watchlist, thesis storage, alerts, ownership cache, and reports."""
    _ensure_dirs()
    clean_t = ticker.upper().strip()
    wl = load_watchlist()
    if clean_t in wl:
        del wl[clean_t]
        save_watchlist(wl)
    
    # Remove thesis file
    tf = get_thesis_file(clean_t)
    if tf.exists():
        try:
            tf.unlink()
        except Exception:
            pass
            
    # Remove public report
    report_file = Path(__file__).resolve().parent.parent / "public" / "reports" / f"{clean_t}.html"
    if report_file.exists():
        try:
            report_file.unlink()
        except Exception:
            pass
            
    # Remove ownership cache
    cache_file = DATA_DIR / "ownership_cache" / f"{clean_t}.json"
    if cache_file.exists():
        try:
            cache_file.unlink()
        except Exception:
            pass

    # Remove critique file
    critique_file = DATA_DIR / "critiques" / f"{clean_t}_critique.md"
    if critique_file.exists():
        try:
            critique_file.unlink()
        except Exception:
            pass
            
    return True


# ==================== ALERTS ====================

def load_alerts() -> List[AlertItem]:
    _ensure_dirs()
    if not ALERTS_FILE.exists():
        return []
    try:
        with open(ALERTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [AlertItem(**item) for item in data]
    except Exception:
        return []


def save_alerts(alerts: List[AlertItem]):
    _ensure_dirs()
    with open(ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump([a.model_dump() for a in alerts[:200]], f, indent=2)


def add_alert(alert: AlertItem):
    _ensure_dirs()
    alerts = load_alerts()
    # Deduplicate: remove older alerts for the same ticker if emitted on the same date or identical event
    deduped = [a for a in alerts if not (a.ticker == alert.ticker and (a.timestamp[:10] == alert.timestamp[:10] or a.trigger_reason == alert.trigger_reason))]
    deduped.insert(0, alert)  # Newest first
    save_alerts(deduped)


# ==================== THESIS HISTORY ====================

def get_thesis_file(ticker: str) -> Path:
    _ensure_dirs()
    return THESES_DIR / f"{ticker.upper()}.json"


def load_thesis_history(ticker: str) -> List[ThesisVersion]:
    file_path = get_thesis_file(ticker)
    if not file_path.exists():
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                data = [data]
            results = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                if "metadata" in item and isinstance(item["metadata"], dict):
                    meta = item["metadata"]
                    cur_p = item.get("current_price") or meta.get("price_at_version") or meta.get("baseline_price") or 0.0
                    c_name = str(item.get("company_name") or meta.get("company_name") or "")
                    tv = ThesisVersion(
                        version=int(meta.get("version", 1)),
                        date=str(meta.get("date") or meta.get("last_updated") or datetime.now().strftime("%Y-%m-%d")),
                        price_at_version=float(cur_p),
                        company_name=c_name,
                        status_label=str(meta.get("status_label") or meta.get("moat") or "Narrow Moat"),
                        moat_label=str(meta.get("moat_label") or meta.get("moat") or "Narrow Moat"),
                        labels=list(meta.get("labels") or [meta.get("status_label", "Narrow Moat")]),
                        action_signal=str(meta.get("action_signal", "BUY")),
                        summary_of_change=str(meta.get("summary_of_change", "")),
                        what_was_before=str(meta.get("what_was_before", "")),
                        what_changes_now=str(meta.get("what_changes_now", "")),
                        fair_value_estimate=str(meta.get("fair_value_estimate", "$0.00")),
                        expected_fair_value=str(meta.get("expected_fair_value") or meta.get("fair_value_estimate", "$0.00")),
                        stories=list(meta.get("stories", [])),
                        story1_target=str(meta.get("story1_target", "")),
                        story2_target=str(meta.get("story2_target", "")),
                        story3_target=str(meta.get("story3_target", "")),
                        story1_title=str(meta.get("story1_title", "")),
                        story2_title=str(meta.get("story2_title", "")),
                        story3_title=str(meta.get("story3_title", "")),
                        bear_target=str(meta.get("bear_target", "$0.00")),
                        base_target=str(meta.get("base_target", "$0.00")),
                        bull_target=str(meta.get("bull_target", "$0.00")),
                        upper_alert_threshold=float(meta["upper_alert_threshold"]) if meta.get("upper_alert_threshold") is not None else None,
                        lower_alert_threshold=float(meta["lower_alert_threshold"]) if meta.get("lower_alert_threshold") is not None else None,
                        next_catalyst_date=str(meta.get("next_catalyst_date", "")),
                        next_catalyst_event=str(meta.get("next_catalyst_event", "")),
                        trigger_reason=str(meta.get("trigger_reason", "")),
                        what_is_priced_in=str(meta.get("what_is_priced_in", "")),
                        top_funds=list(meta.get("top_funds", [])),
                        institutional_ownership_pct=str(meta.get("institutional_ownership_pct", "")),
                        insider_signal=str(meta.get("insider_signal", "Neutral (10b5-1)")),
                        insider_summary=str(meta.get("insider_summary", "")),
                        pricing_power_tier=str(meta.get("pricing_power_tier", "Strong Pricing Power")),
                        pricing_power_score=str(meta.get("pricing_power_score", "")),
                        pricing_power_summary=str(meta.get("pricing_power_summary", "")),
                        predictability_tier=str(meta.get("predictability_tier", "Moderate Predictability")),
                        predictability_score=str(meta.get("predictability_score", "")),
                        predictability_summary=str(meta.get("predictability_summary", "")),
                        full_html_content=str(item.get("full_html") or meta.get("full_html_content") or "")
                    )
                    results.append(tv)
                else:
                    results.append(ThesisVersion(**item))
            return results
    except Exception as e:
        print(f"⚠️ Error loading thesis history for {ticker}: {e}")
        return []


def save_thesis_history(ticker: str, history: List[ThesisVersion]):
    _ensure_dirs()
    file_path = get_thesis_file(ticker)
    with _WRITE_LOCK:
        _atomic_write_json(file_path, [v.model_dump() for v in history])


def save_thesis_version(ticker: str, version: ThesisVersion, reset: bool = False):
    _ensure_dirs()
    from stocks.thesis_qa import ThesisQAError, validate_thesis_output, validate_rendered_html, implied_irr_pct, _num
    v_dict = version.model_dump()
    if v_dict.get("qa_passed") is not True:
        raise ThesisQAError(f"{ticker}: Refusing to save thesis version without qa_passed=True", ["qa_passed != True"])
    price = _num(v_dict.get("price_at_version")) or 0.0
    fv = _num(v_dict.get("expected_val")) or _num(v_dict.get("fair_value_estimate"))
    info = {
        "market_pricing_in": v_dict.get("market_pricing_in"),
        "why_it_might_be_right": v_dict.get("why_it_might_be_right"),
        "how_things_are_going_now": v_dict.get("how_things_are_going_now"),
        "what_if_it_keeps_going_that_way": v_dict.get("what_if_it_keeps_going_that_way"),
        "fair_value_target": fv,
        "bear_floor_target": _num(v_dict.get("bear_target")),
        "bull_upside_target": _num(v_dict.get("bull_target")),
        "irr_3y_pct": implied_irr_pct(fv or 0, price) if fv else None,
        "normalized_oe_per_share": v_dict.get("owner_earnings_per_share"),
        "diluted_shares_mil": v_dict.get("diluted_shares_mil"),
        "p_oe": v_dict.get("p_oe"),
        "net_cash_per_share": v_dict.get("net_cash_per_share"),
    }
    qa_issues = validate_thesis_output(info, price) + validate_rendered_html(v_dict.get("full_html_content") or "")
    if qa_issues:
        raise ThesisQAError(f"{ticker}: Refusing to save thesis version failing QA", qa_issues)

    with _WRITE_LOCK:
        if reset or version.version == 1:
            history = [version]
        else:
            history = load_thesis_history(ticker)
            history.append(version)
        save_thesis_history(ticker, history)


# ==================== TASK QUEUE ====================

def load_queue() -> List[TaskItem]:
    _ensure_dirs()
    if not QUEUE_FILE.exists():
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [TaskItem(**item) for item in data]
    except Exception:
        return []


def save_queue(queue: List[TaskItem]):
    _ensure_dirs()
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump([t.model_dump() for t in queue], f, indent=2)


def enqueue_task(task: TaskItem):
    queue = load_queue()
    for existing in queue:
        if existing.status == "PENDING" and existing.ticker == task.ticker and existing.task_type == task.task_type:
            return
    queue.append(task)
    save_queue(queue)


def pop_next_pending_task() -> Optional[TaskItem]:
    queue = load_queue()
    for task in queue:
        if task.status in ("PENDING", "IN_PROGRESS"):
            task.status = "IN_PROGRESS"
            save_queue(queue)
            return task
    return None


def update_task_status(task_id: str, status: str, error: Optional[str] = None):
    queue = load_queue()
    for task in queue:
        if task.id == task_id:
            task.status = status
            task.error = error
            break
    save_queue(queue)
