"""
stocks.weekly_surveillance
~~~~~~~~~~~~~~~~~~~~~~~~~~
Institutional Weekly Autonomous Surveillance & Macro Cash Audit Engine.

Audits portfolio health, enforces Shiller CAPE macro cash targets,
monitors company MoS expansions/compressions, and scans for dislocation swaps.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any

from stocks.portfolio_engine import (
    calculate_shiller_macro_cash,
    SHILLER_CAPE,
    CAPE_HISTORICAL_MEDIAN,
    BUFFETT_INDICATOR,
    TREASURY_BILL_YIELD,
    TAXONOMY_MAP,
    EXCLUDED_TICKERS
)

DATA_DIR = Path("/Users/pmlhtra/Documents/software/stocks/data")
WATCHLIST_FILE = DATA_DIR / "watchlist.json"

def get_portfolio_filepath(portfolio_type: str) -> Path:
    if portfolio_type == "aggressive":
        return DATA_DIR / "portfolio_aggressive.json"
    return DATA_DIR / "portfolio_defensive.json"

def get_surveillance_filepath(portfolio_type: str) -> Path:
    if portfolio_type == "aggressive":
        return DATA_DIR / "surveillance_aggressive.json"
    return DATA_DIR / "surveillance_defensive.json"

def calculate_kelly_edge(ticker: str, current_price: float, fair_value: float) -> Dict[str, float]:
    """Calculates Expected 5-Year IRR and Quality-Adjusted Kelly Edge."""
    meta = TAXONOMY_MAP.get(ticker, {
        "moat_base": 8.5, "bs_base": 8.5, "growth_base": 10.0, "cannibal_base": 1.5, "oe_yield": 4.5, "p_success": 0.85
    })
    
    mos_pct = max(0.0, ((fair_value - current_price) / current_price) * 100.0) if current_price > 0 else 0.0
    oe_y = meta.get("oe_yield", 4.5)
    cannibal = meta.get("cannibal_base", 1.5)
    growth = meta.get("growth_base", 10.0)
    
    irr_5y = oe_y + cannibal + growth + (mos_pct / 5.0)
    
    payoff_b = (mos_pct / 500.0) + (oe_y / 100.0) + (cannibal / 100.0) + (growth / 100.0)
    p = meta.get("p_success", 0.85)
    q = 1.0 - p
    raw_kelly = (p * payoff_b - q) / payoff_b if payoff_b > 0 else 0.0
    quality_mult = ((meta["moat_base"] * 0.70 + meta["bs_base"] * 0.30) / 10.0) ** 2
    kelly_score = max(0.001, raw_kelly * quality_mult)
    
    return {
        "expected_irr": round(irr_5y, 1),
        "kelly_edge": round(kelly_score * 100.0, 2),
        "moat": meta["moat_base"],
        "bs": meta["bs_base"]
    }

def run_portfolio_surveillance(portfolio_type: str = "defensive") -> Dict[str, Any]:
    """Runs complete weekly audit including Shiller CAPE macro cash gauge."""
    p_file = get_portfolio_filepath(portfolio_type)
    if not p_file.exists():
        p_file = DATA_DIR / "portfolio.json"

    with open(p_file, "r") as f:
        portfolio_state = json.load(f)

    with open(WATCHLIST_FILE, "r") as f:
        watchlist = json.load(f)

    is_defensive = (portfolio_type == "defensive")
    port_label = "Fidelity (Defensive Fortress)" if is_defensive else "Wealthsimple (Aggressive Alpha)"
    
    holdings = portfolio_state.get("holdings", [])
    total_active_holdings = len([h for h in holdings if h.get("ticker") != "USD_CASH"])
    
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    next_run_str = (today + timedelta(days=7)).strftime("%Y-%m-%d")

    holding_audits = []
    rebalance_triggers = []
    active_edge_scores = []
    actual_cash_pct = 0.0
    
    weighted_mos_numerator = 0.0
    equity_weight_sum = 0.0

    for h in holdings:
        ticker = h.get("ticker")
        if ticker == "USD_CASH":
            actual_cash_pct = float(h.get("target_weight", 0.15)) * 100.0
            continue

        w_item = watchlist.get(ticker, {})
        cur_p = float(w_item.get("current_price", h.get("current_price", 100.0)))
        raw_fv = str(w_item.get("fair_value_estimate", h.get("fair_value", cur_p)))
        try:
            fv = float(re.sub(r"[^\d.]", "", raw_fv))
        except Exception:
            fv = cur_p * 1.2
            
        mos = round(((fv - cur_p) / cur_p) * 100.0, 2) if cur_p > 0 else 0.0
        signal = w_item.get("action_signal", "BUY")
        w_tgt = float(h.get("target_weight", 0.10))
        
        weighted_mos_numerator += (mos * w_tgt)
        equity_weight_sum += w_tgt

        calc = calculate_kelly_edge(ticker, cur_p, fv)
        active_edge_scores.append(calc["kelly_edge"])

        # Health checks
        if signal in ["AVOID", "CAUTION"] and mos < -15.0:
            rebalance_triggers.append({
                "action": "SELL",
                "ticker": ticker,
                "reason": f"Thesis impairment / severe negative MoS ({mos:.1f}%)."
            })
            health = "IMPAIRED"
        elif cur_p > 1.35 * fv:
            rebalance_triggers.append({
                "action": "TRIM",
                "ticker": ticker,
                "reason": f"Valuation overextension (${cur_p:.2f} vs FV ${fv:.2f}, MoS: {mos:.1f}%)."
            })
            health = "FROTHY"
        else:
            health = "PRISTINE"

        holding_audits.append({
            "ticker": ticker,
            "company_name": h.get("company_name", ticker),
            "price": cur_p,
            "fair_value": fv,
            "mos_pct": mos,
            "signal": signal,
            "moat_score": calc["moat"],
            "expected_irr": calc["expected_irr"],
            "kelly_edge": calc["kelly_edge"],
            "health_status": health,
            "thesis_core": h.get("thesis_core", "")
        })

    portfolio_weighted_mos = (weighted_mos_numerator / equity_weight_sum) if equity_weight_sum > 0 else 20.0
    
    # Run exact Shiller Macro Cash Engine
    calc_cash_pct_float, eq_budget_float, cash_rationale = calculate_shiller_macro_cash(
        is_defensive=is_defensive,
        weighted_mos=portfolio_weighted_mos
    )
    target_cash_pct = round(calc_cash_pct_float * 100.0, 2)
    
    # Assess Cash Health & Status
    cash_diff = abs(actual_cash_pct - target_cash_pct)
    if cash_diff <= 1.0:
        cash_status = "OPTIMAL_DRY_POWDER_MAINTAINED"
        cash_directive = f"Maintain 3M US Treasury float yielding {TREASURY_BILL_YIELD*100:.2f}% risk-free. Stand ready for fat pitch market dislocations."
    elif actual_cash_pct < target_cash_pct:
        cash_status = "ACCUMULATE_DRY_POWDER"
        cash_directive = f"Market froth (Shiller CAPE {SHILLER_CAPE}x) warrants expanding cash reserves toward {target_cash_pct:.2f}%."
    else:
        cash_status = "SURPLUS_STRIKE_READY"
        cash_directive = f"Cash reserves ({actual_cash_pct:.2f}%) exceed target ({target_cash_pct:.2f}%). Ready for opportunistic deployment."

    # Scan Watchlist for Dislocation Opportunities
    watchlist_candidates = []
    active_tickers = {h.get("ticker") for h in holdings}
    active_tickers.update(EXCLUDED_TICKERS.keys())
    
    # Exclude sibling holdings
    sibling_type = "aggressive" if is_defensive else "defensive"
    sibling_file = get_portfolio_filepath(sibling_type)
    if sibling_file.exists():
        try:
            with open(sibling_file, "r") as sf:
                sib_state = json.load(sf)
                for sh in sib_state.get("holdings", []):
                    active_tickers.add(sh.get("ticker"))
        except Exception:
            pass
            
    min_active_edge = min(active_edge_scores) if active_edge_scores else 15.0

    for ticker, s in watchlist.items():
        if ticker in active_tickers or ticker in EXCLUDED_TICKERS:
            continue

        cur_p = float(s.get("current_price", 0.0))
        raw_fv = str(s.get("fair_value_estimate", cur_p))
        try:
            fv = float(re.sub(r"[^\d.]", "", raw_fv))
        except Exception:
            fv = cur_p * 1.2
            
        mos = round(((fv - cur_p) / cur_p) * 100.0, 2) if cur_p > 0 else 0.0
        signal = s.get("action_signal", "HOLD")
        calc = calculate_kelly_edge(ticker, cur_p, fv)

        if signal == "BUY" and calc["kelly_edge"] >= (min_active_edge + 8.0):
            rebalance_triggers.append({
                "action": "SWAP_PROPOSAL",
                "ticker": ticker,
                "reason": f"Dislocation arbitrage: {ticker} offers Edge {calc['kelly_edge']} vs {min_active_edge} min active."
            })

        if signal == "BUY" and mos >= 20.0:
            watchlist_candidates.append({
                "ticker": ticker,
                "company_name": s.get("company_name", ticker),
                "price": cur_p,
                "fair_value": fv,
                "mos_pct": mos,
                "expected_irr": calc["expected_irr"],
                "kelly_edge": calc["kelly_edge"],
                "moat_score": calc["moat"]
            })

    watchlist_candidates.sort(key=lambda x: x["kelly_edge"], reverse=True)

    if not rebalance_triggers:
        status = "OPTIMAL"
        status_display = "COUNCIL AUDIT ACTIVE • ALL HOLDINGS INTACT"
        verdict = (
            f"Audited {port_label} across Buffett-Munger Kelly filters. "
            f"All {total_active_holdings} core holdings maintain pristine moats and healthy cash compounding. "
            f"Zero thesis impairments detected. Shiller CAPE macro cash gauge verified at {target_cash_pct:.2f}%."
        )
        action_required = False
    else:
        status = "ACTION_REQUIRED"
        status_display = f"REBALANCE PROPOSAL PENDING ({len(rebalance_triggers)} ACTIONS)"
        verdict = f"Council flagged {len(rebalance_triggers)} position(s) exceeding materiality rebalance hurdles."
        action_required = True

    macro_cash_audit = {
        "shiller_cape": SHILLER_CAPE,
        "historical_cape_median": CAPE_HISTORICAL_MEDIAN,
        "buffett_indicator_pct": BUFFETT_INDICATOR,
        "treasury_3m_yield_pct": TREASURY_BILL_YIELD * 100.0,
        "portfolio_weighted_mos_pct": round(portfolio_weighted_mos, 2),
        "mandate_structural_floor_pct": 5.0 if is_defensive else 3.0,
        "calculated_target_cash_pct": target_cash_pct,
        "current_actual_cash_pct": actual_cash_pct,
        "cash_status": cash_status,
        "strike_trigger_threshold": "MoS > 45.0% on Tier-1 Compounder or Flash Crash Dislocation",
        "cash_directive": cash_directive,
        "formula_description": cash_rationale
    }

    surveillance_report = {
        "portfolio_type": portfolio_type,
        "portfolio_label": port_label,
        "last_run_date": today_str,
        "last_run_timestamp": datetime.now().isoformat(),
        "status": status,
        "status_display": status_display,
        "action_required": action_required,
        "verdict_summary": verdict,
        "total_universe_scanned": len(watchlist),
        "active_holdings_verified": total_active_holdings,
        "shiller_cape": SHILLER_CAPE,
        "buffett_indicator_pct": BUFFETT_INDICATOR,
        "treasury_3m_yield_pct": TREASURY_BILL_YIELD * 100.0,
        "portfolio_average_mos_pct": round(portfolio_weighted_mos, 2),
        "cash_cushion_pct": target_cash_pct,
        "macro_cash_audit": macro_cash_audit,
        "next_scheduled_run": next_run_str,
        "holdings_health": holding_audits,
        "top_watchlist_on_radar": watchlist_candidates[:3],
        "rebalance_proposals": rebalance_triggers
    }

    s_file = get_surveillance_filepath(portfolio_type)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(s_file, "w") as f:
        json.dump(surveillance_report, f, indent=2)

    if portfolio_type == "defensive":
        with open(DATA_DIR / "surveillance.json", "w") as f:
            json.dump(surveillance_report, f, indent=2)

    print(f"✅ Surveillance audit completed for {port_label} (Target Cash: {target_cash_pct:.2f}% | Actual: {actual_cash_pct:.2f}% | Status: {cash_status})")
    return surveillance_report

def run_dual_surveillance():
    print("=== RUNNING WEEKLY AUTONOMOUS DUAL SURVEILLANCE ===")
    run_portfolio_surveillance("defensive")
    run_portfolio_surveillance("aggressive")

if __name__ == "__main__":
    run_dual_surveillance()
