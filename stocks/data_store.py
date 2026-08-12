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
            return {k: WatchlistStock(**v) for k, v in data.items()}
    except Exception:
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
            task.error_message = error
            break
    save_queue(queue)
