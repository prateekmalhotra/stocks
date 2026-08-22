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
    company_name: Optional[str] = ""
    status_label: str = "Narrow Moat"
    moat_label: Optional[str] = "Narrow Moat"
    moat_type: Optional[str] = ""  # e.g. "Global 2-Sided Network Effect", "Scale Economies Shared", "Procedural Switching Costs", "Regulatory Tollbooth", "Fickle Consumer / Low Switching Costs"
    moat_scope: Optional[str] = ""  # Global, National, Regional, Local, None
    labels: List[str] = Field(default_factory=list)  # Slot 1: Moat archetype, Slots 2-3: Drivers
    action_signal: str = "BUY"  # BUY, HOLD, CAUTION, AVOID
    summary_of_change: Optional[str] = ""  # How the company/thesis changed in this version
    what_was_before: Optional[str] = ""
    what_changes_now: Optional[str] = ""
    fair_value_estimate: Optional[str] = ""
    expected_fair_value: Optional[str] = ""
    expected_val: Optional[float] = None
    present_fair_value: Optional[float] = None
    stories: List[Dict[str, Any]] = Field(default_factory=list)
    story1_target: Optional[str] = ""
    story2_target: Optional[str] = ""
    story3_target: Optional[str] = ""
    story1_title: Optional[str] = ""
    story2_title: Optional[str] = ""
    story3_title: Optional[str] = ""
    bear_target: Optional[str] = ""
    base_target: Optional[str] = ""
    bull_target: Optional[str] = ""
    upper_alert_threshold: Optional[float] = None
    lower_alert_threshold: Optional[float] = None
    next_catalyst_date: Optional[str] = ""
    next_catalyst_event: Optional[str] = ""
    trigger_reason: Optional[str] = ""
    what_is_priced_in: Optional[str] = ""  # Reverse DCF implied 5-year growth rate
    top_funds: List[str] = Field(default_factory=list)  # Top institutional holders / 13F whales
    institutional_ownership_pct: Optional[str] = ""  # e.g. "78.4%"
    insider_signal: Optional[str] = "Neutral (10b5-1)"  # Net Buying, Cluster Buying, Neutral (10b5-1), Net Selling, No Activity
    insider_summary: Optional[str] = ""  # 1-line summary of recent Form 4 insider transactions
    pricing_power_tier: Optional[str] = "Strong Pricing Power"  # Absolute, Strong, Inflation Pass-Through, Constrained, Price Taker
    pricing_power_score: Optional[str] = "High Inelasticity"  # e.g. "Inelastic Demand · +5% Pricing Power"
    pricing_power_summary: Optional[str] = ""  # 1-sentence synthesis of pricing authority
    predictability_tier: Optional[str] = "Moderate Predictability"  # High, Moderate, Low, Highly Unpredictable
    predictability_score: Optional[str] = "Manageable Visibility · Moat Protected"
    predictability_summary: Optional[str] = ""  # 1-sentence synthesis of 10-year visibility
    cyclicality_type: Optional[str] = "Moderate Cyclical"  # Secular Compounder, Moderate Cyclical, Deep Cyclical
    cycle_stance: Optional[str] = "Mid-Cycle Run-Rate"  # Trough / Max Pessimism, Downcycle Contraction, Mid-Cycle Run-Rate, Peak / Over-Earning Risk
    cycle_summary: Optional[str] = ""  # 1-line synthesis of cycle drivers
    owner_earnings_per_share: Optional[float] = None
    owner_earnings_total_mil: Optional[float] = None
    p_oe: Optional[float] = None
    ev_oe: Optional[float] = None
    owner_yield_pct: Optional[float] = None
    owner_roic_pct: Optional[float] = None
    net_cash_per_share: Optional[float] = None
    market_pricing_in: Optional[str] = ""
    why_it_might_be_right: Optional[str] = ""
    how_things_are_going_now: Optional[str] = ""
    what_if_it_keeps_going_that_way: Optional[str] = ""
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
    status_label: str = "Narrow Moat"
    moat_label: Optional[str] = "Narrow Moat"
    moat_type: Optional[str] = ""  # e.g. "Global 2-Sided Network Effect", "Scale Economies Shared", "Procedural Switching Costs", "Regulatory Tollbooth", "Fickle Consumer / Low Switching Costs"
    moat_scope: Optional[str] = ""  # Global, National, Regional, Local, None
    labels: List[str] = Field(default_factory=list)  # Slot 1: Moat archetype, Slots 2-3: Drivers
    action_signal: str = "BUY"  # BUY, HOLD, CAUTION, AVOID
    fair_value_estimate: str
    expected_fair_value: Optional[str] = ""
    expected_val: Optional[float] = None
    stories: List[Dict[str, Any]] = Field(default_factory=list)
    story1_target: Optional[str] = ""
    story2_target: Optional[str] = ""
    story3_target: Optional[str] = ""
    story1_title: Optional[str] = ""
    story2_title: Optional[str] = ""
    story3_title: Optional[str] = ""
    bear_target: str
    base_target: str
    bull_target: str
    what_is_priced_in: Optional[str] = ""  # Reverse DCF implied 5-year growth rate
    upper_alert_threshold: Optional[float] = None
    lower_alert_threshold: Optional[float] = None
    next_catalyst_date: Optional[str] = ""
    next_catalyst_event: Optional[str] = ""
    top_funds: List[str] = Field(default_factory=list)
    institutional_ownership_pct: Optional[str] = ""
    insider_signal: Optional[str] = "Neutral (10b5-1)"
    insider_summary: Optional[str] = ""
    pricing_power_tier: Optional[str] = "Strong Pricing Power"
    pricing_power_score: Optional[str] = "High Inelasticity"
    pricing_power_summary: Optional[str] = ""
    predictability_tier: Optional[str] = "Moderate Predictability"
    predictability_score: Optional[str] = "Manageable Visibility · Moat Protected"
    predictability_summary: Optional[str] = ""
    cyclicality_type: Optional[str] = "Moderate Cyclical"
    cycle_stance: Optional[str] = "Mid-Cycle Run-Rate"
    cycle_summary: Optional[str] = ""
    owner_earnings_per_share: Optional[float] = None
    owner_earnings_total_mil: Optional[float] = None
    p_oe: Optional[float] = None
    ev_oe: Optional[float] = None
    owner_yield_pct: Optional[float] = None
    owner_roic_pct: Optional[float] = None
    net_cash_per_share: Optional[float] = None
    market_pricing_in: Optional[str] = ""
    why_it_might_be_right: Optional[str] = ""
    how_things_are_going_now: Optional[str] = ""
    what_if_it_keeps_going_that_way: Optional[str] = ""
    last_updated: str
    total_versions: int = 1
    report_path: str


class TaskItem(BaseModel):
    """Represents a work item in the queue."""
    id: str
    task_type: str
    ticker: str
    notes: Optional[str] = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    status: str = "PENDING"
    error: Optional[str] = None
