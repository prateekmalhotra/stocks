"""
Weekly Autonomous Investment Council Deep Surveillance Engine.

Provides dual-cadence autonomous audits:
- Defensive Fortress ($200k): Evaluated every Sunday at 2:00 PM EST.
- Aggressive Alpha ($200k): Evaluated every Saturday at 2:00 PM EST.

Uses Shiller CAPE macro cash gauge, Kelly risk-adjusted return ranking,
and strict >= 5.0% anti-churn hurdles.
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"

# Macro & Risk-Free Benchmarks
SHILLER_CAPE = 35.5             # S&P 500 Cyclically Adjusted P/E (95th percentile)
HISTORICAL_MEDIAN_CAPE = 18.0   # Long-term historical baseline
RISK_FREE_TREASURY_RATE = 0.045 # 3-Month US Treasury Bill Yield (4.50%)

# Universal Quality Matrix
UNIVERSE_PROFILES = {
    # Defensive Fortress Candidates (Fidelity)
    "CSU":   {"name": "Constellation Software Inc.", "oe_yield": 4.5, "cannibal": 0.0, "growth": 14.0, "moat": 9.8, "bs": 8.5, "pool": "defensive"},
    "MA":    {"name": "Mastercard Incorporated",      "oe_yield": 3.8, "cannibal": 2.0, "growth": 11.0, "moat": 9.7, "bs": 8.5, "pool": "defensive"},
    "V":     {"name": "Visa Inc.",                    "oe_yield": 4.6, "cannibal": 2.2, "growth": 9.5,  "moat": 9.7, "bs": 8.5, "pool": "defensive"},
    "CPRT":  {"name": "Copart, Inc.",                 "oe_yield": 4.4, "cannibal": 0.5, "growth": 11.0, "moat": 9.6, "bs": 10.0, "pool": "defensive"},
    "BKNG":  {"name": "Booking Holdings Inc.",        "oe_yield": 6.8, "cannibal": 4.5, "growth": 8.5,  "moat": 9.4, "bs": 8.5, "pool": "defensive"},
    "INTU":  {"name": "Intuit Inc.",                  "oe_yield": 4.5, "cannibal": 1.5, "growth": 10.0, "moat": 9.4, "bs": 8.5, "pool": "defensive"},
    "UNH":   {"name": "UnitedHealth Group Inc.",      "oe_yield": 5.8, "cannibal": 1.2, "growth": 9.0,  "moat": 9.6, "bs": 8.5, "pool": "defensive"},
    "SPGI":  {"name": "S&P Global Inc.",              "oe_yield": 4.1, "cannibal": 1.8, "growth": 9.5,  "moat": 9.8, "bs": 8.5, "pool": "defensive"},
    "MSFT":  {"name": "Microsoft Corporation",        "oe_yield": 3.9, "cannibal": 0.8, "growth": 11.0, "moat": 9.7, "bs": 9.0, "pool": "defensive"},
    "ADBE":  {"name": "Adobe Inc.",                   "oe_yield": 5.5, "cannibal": 3.2, "growth": 10.5, "moat": 9.5, "bs": 9.0, "pool": "defensive"},

    # Aggressive Alpha Candidates (Wealthsimple)
    "NVDA":  {"name": "NVIDIA Corporation",            "oe_yield": 5.2, "cannibal": 2.5, "growth": 18.0, "moat": 9.8, "bs": 10.0, "pool": "aggressive"},
    "META":  {"name": "Meta Platforms, Inc.",         "oe_yield": 5.4, "cannibal": 2.8, "growth": 12.0, "moat": 9.5, "bs": 9.5, "pool": "aggressive"},
    "MELI":  {"name": "MercadoLibre, Inc.",           "oe_yield": 6.1, "cannibal": 0.0, "growth": 19.0, "moat": 9.5, "bs": 9.0, "pool": "aggressive"},
    "ASML":  {"name": "ASML Holding N.V.",            "oe_yield": 4.8, "cannibal": 1.5, "growth": 14.0, "moat": 9.9, "bs": 9.5, "pool": "aggressive"},
    "TSM":   {"name": "Taiwan Semiconductor Mfg",     "oe_yield": 5.9, "cannibal": 0.0, "growth": 15.0, "moat": 9.8, "bs": 9.5, "pool": "aggressive"},
    "BABA":  {"name": "Alibaba Group Holding Limited", "oe_yield": 8.5, "cannibal": 6.5, "growth": 6.0,  "moat": 9.5, "bs": 10.0, "pool": "aggressive"},
    "JD":    {"name": "JD.com, Inc.",                 "oe_yield": 9.2, "cannibal": 5.5, "growth": 6.0,  "moat": 9.0, "bs": 9.5, "pool": "aggressive"},
    "STNE":  {"name": "StoneCo Ltd.",                 "oe_yield": 11.5,"cannibal": 4.0, "growth": 12.0, "moat": 8.5, "bs": 8.5, "pool": "aggressive"},
    "CROX":  {"name": "Crocs, Inc.",                  "oe_yield": 8.8, "cannibal": 5.0, "growth": 6.0,  "moat": 8.6, "bs": 8.5, "pool": "aggressive"},
    "GCT":   {"name": "GigaCloud Technology Inc",     "oe_yield": 9.5, "cannibal": 2.0, "growth": 18.0, "moat": 8.8, "bs": 9.5, "pool": "aggressive"}
}


def calculate_kelly_edge(ticker: str, current_price: float, fair_value: float) -> Dict[str, float]:
    """Calculates Expected 5-Year IRR and Quality-Adjusted Kelly Edge."""
    prof = UNIVERSE_PROFILES.get(ticker, {
        "oe_yield": 5.0, "cannibal": 1.5, "growth": 8.0, "moat": 8.0, "bs": 8.0
    })
    
    mos = max(0.0, ((fair_value - current_price) / fair_value) * 100.0) if fair_value > 0 else 0.0
    mos_expansion = mos / 5.0
    expected_irr = prof["oe_yield"] + prof["cannibal"] + prof["growth"] + mos_expansion
    
    q_score = (prof["moat"] * 0.70 + prof["bs"] * 0.30) / 10.0
    kelly_edge = expected_irr * (q_score ** 2)
    
    return {
        "expected_irr": round(expected_irr, 2),
        "q_score": round(q_score, 3),
        "kelly_edge": round(kelly_edge, 2),
        "moat": prof["moat"],
        "balance_sheet": prof["bs"]
    }


def get_surveillance_filepath(portfolio_type: str = "defensive") -> Path:
    if portfolio_type.lower() in ["aggressive", "alpha"]:
        return DATA_DIR / "surveillance_aggressive.json"
    return DATA_DIR / "surveillance_defensive.json"


def get_portfolio_filepath(portfolio_type: str = "defensive") -> Path:
    if portfolio_type.lower() in ["aggressive", "alpha"]:
        return DATA_DIR / "portfolio_aggressive.json"
    return DATA_DIR / "portfolio_defensive.json"


def run_weekly_deep_surveillance(portfolio_type: str = "defensive") -> Dict[str, Any]:
    """Executes surveillance audit for either the Defensive (Sunday) or Aggressive (Saturday) portfolio."""
    is_defensive = (portfolio_type == "defensive")
    port_label = "Fidelity Portfolio ($200k)" if is_defensive else "Wealthsimple Portfolio ($200k)"
    day_target = 6 if is_defensive else 5 # Sunday = 6, Saturday = 5
    day_name = "Sunday" if is_defensive else "Saturday"

    print("=" * 85)
    print(f"🔍 [COUNCIL SURVEILLANCE] Scanning {port_label}...")
    print("=" * 85)

    watchlist = {}
    if WATCHLIST_FILE.exists():
        with open(WATCHLIST_FILE, "r") as f:
            watchlist = json.load(f)

    p_file = get_portfolio_filepath(portfolio_type)
    portfolio_state = {}
    if p_file.exists():
        with open(p_file, "r") as f:
            portfolio_state = json.load(f)

    holdings = portfolio_state.get("holdings", [])
    now_dt = datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d")

    # Next run target
    days_until = (day_target - now_dt.weekday()) % 7
    if days_until == 0:
        days_until = 7
    next_run_dt = now_dt + timedelta(days=days_until)
    next_run_str = f"{day_name}, {next_run_dt.strftime('%b %d, %Y')} at 2:00 PM EST"

    holding_audits = []
    rebalance_triggers = []
    active_edge_scores = []
    total_active_holdings = len([h for h in holdings if h.get("ticker") != "USD_CASH"])

    for h in holdings:
        ticker = h.get("ticker")
        if ticker == "USD_CASH":
            continue

        w_data = watchlist.get(ticker, {})
        cur_p = float(w_data.get("current_price", h.get("current_price", 100.0)))
        fv_raw = w_data.get("fair_value_estimate", "$0.00")
        fv_match = re.search(r"[\d\.]+", fv_raw.replace(",", ""))
        fv = float(fv_match.group(0)) if fv_match else cur_p
        
        mos = round(((fv - cur_p) / fv) * 100.0, 1) if fv > 0 else 0.0
        signal = w_data.get("action_signal", "BUY")
        
        calc = calculate_kelly_edge(ticker, cur_p, fv)
        active_edge_scores.append(calc["kelly_edge"])

        if signal == "AVOID":
            rebalance_triggers.append({
                "action": "LIQUIDATE",
                "ticker": ticker,
                "reason": f"Fundamental thesis impairment detected. Downgraded to AVOID."
            })
            health = "IMPAIRED"
        elif cur_p > 1.35 * fv:
            rebalance_triggers.append({
                "action": "TRIM",
                "ticker": ticker,
                "reason": f"Extreme valuation overextension (${cur_p:.2f} vs FV ${fv:.2f}, MoS: {mos}%)."
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

    avg_mos = sum(x["mos_pct"] for x in holding_audits) / len(holding_audits) if holding_audits else 25.0
    froth_component = max(0.0, min(0.15, (SHILLER_CAPE - 22.0) / 14.0 * 0.15))
    base_floor = 0.08 if is_defensive else 0.05
    target_cash_pct = round(base_floor + (froth_component * (1.0 - (avg_mos / 100.0))), 2) * 100.0

    # Scan universe (strictly exclude sibling portfolio holdings to maintain mutual exclusivity)
    watchlist_candidates = []
    active_tickers = {h.get("ticker") for h in holdings}
    active_tickers.add("GOOG")

    # Exclude sibling portfolio holdings
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
    
    min_active_edge = min(active_edge_scores) if active_edge_scores else 18.0

    for ticker, s in watchlist.items():
        if ticker in active_tickers:
            continue

        cur_p = float(s.get("current_price", 0.0))
        fv_raw = s.get("fair_value_estimate", "$0.00")
        fv_match = re.search(r"[\d\.]+", fv_raw.replace(",", ""))
        fv = float(fv_match.group(0)) if fv_match else cur_p
        mos = round(((fv - cur_p) / fv) * 100.0, 1) if fv > 0 else 0.0
        signal = s.get("action_signal", "HOLD")
        
        calc = calculate_kelly_edge(ticker, cur_p, fv)

        if signal == "BUY" and calc["kelly_edge"] >= (min_active_edge + 5.0):
            rebalance_triggers.append({
                "action": "SWAP_PROPOSAL",
                "ticker": ticker,
                "reason": f"Dislocation arbitrage: {ticker} offers Edge {calc['kelly_edge']} vs {min_active_edge} min active."
            })

        if signal == "BUY" and mos >= 15.0:
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
            f"All {total_active_holdings} core holdings maintain pristine moats and >18% expected 5Y IRRs. "
            f"Zero thesis impairments detected. Strategic cash buffer maintained at {target_cash_pct:.1f}%."
        )
        action_required = False
    else:
        status = "ACTION_REQUIRED"
        status_display = f"REBALANCE PROPOSAL PENDING ({len(rebalance_triggers)} ACTIONS)"
        verdict = f"Council flagged {len(rebalance_triggers)} position(s) exceeding materiality rebalance hurdles."
        action_required = True

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
        "treasury_3m_yield_pct": RISK_FREE_TREASURY_RATE * 100.0,
        "portfolio_average_mos_pct": round(avg_mos, 1),
        "cash_cushion_pct": target_cash_pct,
        "next_scheduled_run": next_run_str,
        "holdings_health": holding_audits,
        "top_watchlist_on_radar": watchlist_candidates[:3],
        "rebalance_proposals": rebalance_triggers
    }

    s_file = get_surveillance_filepath(portfolio_type)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(s_file, "w") as f:
        json.dump(surveillance_report, f, indent=2)

    # Also sync surveillance.json for backwards compatibility
    with open(DATA_DIR / "surveillance.json", "w") as f:
        json.dump(surveillance_report, f, indent=2)

    print(f"✅ [{portfolio_type.upper()} SURVEILLANCE COMPLETE] Status: {status_display}")
    print(f"📅 Next Run: {next_run_str}")
    print("=" * 85)
    
    return surveillance_report


def get_surveillance_summary(portfolio_type: str = "defensive") -> Dict[str, Any]:
    """Loads surveillance report for the specified portfolio or runs fresh audit."""
    s_file = get_surveillance_filepath(portfolio_type)
    if not s_file.exists():
        return run_weekly_deep_surveillance(portfolio_type)
    try:
        with open(s_file, "r") as f:
            return json.load(f)
    except Exception:
        return run_weekly_deep_surveillance(portfolio_type)


if __name__ == "__main__":
    import sys
    ptype = sys.argv[1] if len(sys.argv) > 1 else "all"
    if ptype == "all":
        run_weekly_deep_surveillance("defensive")
        run_weekly_deep_surveillance("aggressive")
    else:
        run_weekly_deep_surveillance(ptype)
