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
    status_label: str
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
    full_html_content: str = ""


class AlertItem(BaseModel):
    """Represents an alert triggered by price breach or thesis evolution."""
    id: str
    ticker: str
    timestamp: str
    title: str
    severity: str = "INFO"  # LLM-assigned: e.g. "HIGH CONVICTION ACCUMULATION", "THESIS DENTED", "BREAKOUT"
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
    status_label: str
    fair_value_estimate: str
    bear_target: str
    base_target: str
    bull_target: str
    upper_alert_threshold: Optional[float] = None
    lower_alert_threshold: Optional[float] = None
    next_catalyst_date: Optional[str] = ""
    next_catalyst_event: Optional[str] = ""
    last_updated: str
    total_versions: int = 1
    report_path: str = ""


class TaskItem(BaseModel):
    """Task in the autonomous processing queue."""
    id: str
    task_type: str  # ANALYZE_NEW, PRICE_TRIGGER, CATALYST_DUE, MANUAL_REVIEW
    ticker: str
    notes: Optional[str] = ""
    created_at: str
    status: str = "PENDING"  # PENDING, IN_PROGRESS, COMPLETED, FAILED
    error_message: Optional[str] = None
