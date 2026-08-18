"""Persistent JSON data store for watchlists, alerts, thesis history, and task queue."""

import json
import os
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


def save_watchlist(watchlist: Dict[str, WatchlistStock]):
    _ensure_dirs()
    serializable = {k: v.model_dump() for k, v in watchlist.items()}
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2)


def get_stock(ticker: str) -> Optional[WatchlistStock]:
    return load_watchlist().get(ticker.upper())


def save_stock(stock: WatchlistStock):
    wl = load_watchlist()
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
            return [ThesisVersion(**item) for item in data]
    except Exception:
        return []


def save_thesis_history(ticker: str, history: List[ThesisVersion]):
    _ensure_dirs()
    file_path = get_thesis_file(ticker)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump([v.model_dump() for v in history], f, indent=2)


def save_thesis_version(ticker: str, version: ThesisVersion, reset: bool = False):
    _ensure_dirs()
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
