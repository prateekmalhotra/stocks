"""Data models for Stock Analysis & Living Thesis System."""

from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class ThesisVersion(BaseModel):
    """Represents a historical or current version of an investment thesis."""
    version: int
    date: str
    price_at_version: float
    status_label: str = "Active"
    labels: List[str] = Field(default_factory=list)  # Max 3 labels, max 2 words each
    action_signal: str = "BUY"  # BUY, HOLD, CAUTION, AVOID
    summary_of_change: str  # How the company/thesis changed in this version
    what_was_before: Optional[str] = ""
    what_changes_now: Optional[str] = ""
    fair_value_estimate: Optional[str] = ""
    bear_target: Optional[str] = ""
    base_target: Optional[str] = ""
    bull_target: Optional[str] = ""
    upper_alert_threshold: Optional[float] = None
    lower_alert_threshold: Optional[float] = None
    next_catalyst_date: Optional[str] = ""
    next_catalyst_event: Optional[str] = ""
    trigger_reason: Optional[str] = ""
    top_funds: List[str] = Field(default_factory=list)  # Top institutional holders / 13F whales
    institutional_ownership_pct: Optional[str] = ""  # e.g. "78.4%"
    insider_signal: Optional[str] = "Neutral (10b5-1)"  # Net Buying, Cluster Buying, Neutral (10b5-1), Net Selling, No Activity
    insider_summary: Optional[str] = ""  # 1-line summary of recent Form 4 insider transactions
    full_html_content: str = ""


class AlertItem(BaseModel):
    """Represents an alert triggered by price breach or thesis evolution."""
    id: str
    ticker: str
    timestamp: str
    title: str
    severity: str = "Review"
    labels: List[str] = Field(default_factory=list)
    action_signal: str = "BUY"  # BUY, HOLD, CAUTION, AVOID
    trigger_reason: str
    what_was_before: str
    what_changes_now: str
    price_at_alert: float
    price_change_pct: float
    report_url: str


class WatchlistStock(BaseModel):
    """Summary record for a tracked stock in the master registry."""
    ticker: str
    company_name: str
    baseline_price: float
    current_price: float
    return_pct: float
    status_label: str = "Active"
    labels: List[str] = Field(default_factory=list)  # Max 3 labels, max 2 words each
    action_signal: str = "BUY"  # BUY, HOLD, CAUTION, AVOID
    fair_value_estimate: str
    bear_target: str
    base_target: str
    bull_target: str
    upper_alert_threshold: Optional[float] = None
    lower_alert_threshold: Optional[float] = None
    next_catalyst_date: Optional[str] = ""
    next_catalyst_event: Optional[str] = ""
    top_funds: List[str] = Field(default_factory=list)
    institutional_ownership_pct: Optional[str] = ""
    insider_signal: Optional[str] = "Neutral (10b5-1)"
    insider_summary: Optional[str] = ""
    last_updated: str
    total_versions: int = 1
    report_path: str


class TaskItem(BaseModel):
    """Represents a work item in the queue."""
    id: str
    task_type: str
    ticker: str
    notes: Optional[str] = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    status: str = "PENDING"
    error: Optional[str] = None
