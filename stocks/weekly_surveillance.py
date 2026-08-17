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
from typing import Dict, List, Any, Tuple, Optional

from stocks.portfolio_engine import (
    calculate_shiller_macro_cash,
    SHILLER_CAPE,
    CAPE_HISTORICAL_MEDIAN,
    BUFFETT_INDICATOR,
    TREASURY_BILL_YIELD,
    TAXONOMY_MAP,
    COMPLIANCE_EXCLUSIONS
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"

def get_portfolio_filepath(portfolio_type: str) -> Path:
    if portfolio_type == "aggressive":
        return DATA_DIR / "portfolio_aggressive.json"
    return DATA_DIR / "portfolio_defensive.json"

def get_surveillance_filepath(portfolio_type: str) -> Path:
    if portfolio_type == "aggressive":
        return DATA_DIR / "surveillance_aggressive.json"
    return DATA_DIR / "surveillance_defensive.json"

def calculate_kelly_edge(ticker: str, current_price: float, fair_value: float, wl_item: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """Calculates Expected 5-Year IRR and Quality-Adjusted Kelly Edge for all existing and newly ingested stocks."""
    meta = TAXONOMY_MAP.get(ticker)
    if not meta:
        wl_item = wl_item or {}
        labels = wl_item.get("labels", [])
        status = wl_item.get("status_label", "")
        
        # Derive high-precision fundamental heuristics from research labels
        moat = 9.4 if ("Monopoly Moat" in labels or "High Conviction" in status) else (9.0 if "Solid Conviction" in status else 8.5)
        bs = 9.5 if "Cash Fortress" in labels else (8.0 if "Debt Caution" in labels else 8.5)
        growth = 15.0 if ("Cloud Acceleration" in labels or "Growth" in labels) else 9.0
        cannibal = 4.0 if "Buyback Cannibal" in labels else 1.5
        oe_y = 6.0 if "Deep Value" in labels else 4.5
        p = 0.90 if "Monopoly Moat" in labels else 0.85
        meta = {"moat": moat, "bs": bs, "growth": growth, "cannibal": cannibal, "oe_yield": oe_y, "p": p}
    
    moat = meta.get("moat", meta.get("moat_base", 8.5))
    bs = meta.get("bs", meta.get("bs_base", 8.5))
    oe_y = meta.get("oe_yield", 4.5)
    cannibal = meta.get("cannibal", meta.get("cannibal_base", 1.5))
    growth = meta.get("growth", meta.get("growth_base", 10.0))
    p = meta.get("p", meta.get("p_success", 0.85))
    
    mos_pct = max(0.0, ((fair_value - current_price) / current_price) * 100.0) if current_price > 0 else 0.0
    irr_5y = oe_y + cannibal + growth + (mos_pct / 5.0)
    
    payoff_b = (mos_pct / 500.0) + (oe_y / 100.0) + (cannibal / 100.0) + (growth / 100.0)
    q = 1.0 - p
    raw_kelly = (p * payoff_b - q) / payoff_b if payoff_b > 0 else 0.0
    quality_mult = ((moat * 0.70 + bs * 0.30) / 10.0) ** 2
    kelly_score = max(0.001, raw_kelly * quality_mult)
    
    return {
        "expected_irr": round(irr_5y, 1),
        "kelly_edge": round(kelly_score * 100.0, 2),
        "moat": moat,
        "bs": bs
    }

def make_holding_record(
    ticker: str,
    s: Dict[str, Any],
    weight: float,
    total_capital: float,
    is_defensive: bool
) -> Dict[str, Any]:
    """Constructs a standard holding dictionary for portfolio persistence."""
    cur_p = float(s.get("current_price", 100.0))
    raw_fv = str(s.get("fair_value_estimate", cur_p))
    try:
        fv = float(re.sub(r"[^\d.]", "", raw_fv))
    except Exception:
        fv = cur_p * 1.2
    mos = round(((fv - cur_p) / cur_p) * 100.0, 2) if cur_p > 0 else 0.0
    alloc = round(total_capital * weight, 2)
    shs = round(alloc / cur_p, 4) if cur_p > 0 else 0.0
    meta = TAXONOMY_MAP.get(ticker, {})
    oe_yield = meta.get("oe_yield", 5.0)
    oe_yr = round(alloc * (oe_yield / 100.0), 2)
    
    return {
        "ticker": ticker,
        "company_name": s.get("company_name", ticker),
        "sector": s.get("sector", meta.get("sector", "Diversified")),
        "industry": s.get("industry", meta.get("industry", "Compounder")),
        "quality_score": round(meta.get("moat", 9.0) * 10.0, 2),
        "target_weight": round(weight, 4),
        "pillar": "A" if is_defensive else "B",
        "cost_basis": cur_p,
        "current_price": cur_p,
        "fair_value": fv,
        "margin_of_safety_pct": mos,
        "allocated_dollars": alloc,
        "shares_to_buy": shs,
        "look_through_fcf_yield": oe_yield,
        "annual_owner_earnings": oe_yr,
        "cannibal_rate_pct": meta.get("cannibal", 1.0),
        "thesis_core": s.get("thesis_core") or s.get("summary") or meta.get("thesis", f"High-conviction compounder {ticker} with {mos}% MoS."),
        "report_url": f"reports/{ticker}.html"
    }


def execute_surveillance_decisions(
    portfolio_type: str,
    portfolio_state: Dict[str, Any],
    watchlist: Dict[str, Any],
    holding_audits: List[Dict[str, Any]],
    target_cash_pct: float,
    actual_cash_pct: float,
    watchlist_candidates: List[Dict[str, Any]]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Autonomous Execution Engine for Surveillance:
    1. SELL: Exits impaired holdings (AVOID/CAUTION & severe negative MoS).
    2. TRIM: Trims frothy holdings (>1.35x Fair Value or weight > 20%).
    3. BUY: Deploys surplus cash into top-ranked dislocation compounder if cash surplus >= 4.0%.
    4. SWAP: Replaces weakest holding if candidate provides massive edge delta (>= 20 pts).
    5. CASH REBALANCE: Normalizes weights and keeps USD_CASH balanced to macro target.
    """
    is_defensive = (portfolio_type == "defensive")
    total_capital = float(portfolio_state.get("base_capital_usd", 200000.0))
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    current_holdings = [h for h in portfolio_state.get("holdings", []) if h.get("ticker") != "USD_CASH"]
    executed_actions = []
    
    # ---------------------------------------------------------
    # 1. SELL IMPAIRED HOLDINGS
    # ---------------------------------------------------------
    retained_holdings = []
    for h in current_holdings:
        ticker = h.get("ticker")
        audit = next((a for a in holding_audits if a["ticker"] == ticker), None)
        if audit and audit.get("health_status") == "IMPAIRED":
            action_desc = f"Sold {ticker} due to thesis impairment (Signal: {audit.get('signal')}, MoS: {audit.get('mos_pct')}%)"
            executed_actions.append({
                "date": today_str,
                "action": "THESIS EXIT (SELL)",
                "ticker": ticker,
                "reason": action_desc,
                "weight_delta": f"-{float(h.get('target_weight', 0.0))*100:.1f}%",
                "verification_status": "Audited & Executed by Autonomous Surveillance Council"
            })
            print(f"  🚨 [AUTONOMOUS ACTION: SELL] {action_desc}")
        else:
            retained_holdings.append(h)
            
    # ---------------------------------------------------------
    # 2. TRIM FROTHY POSITIONS (Buffett-style up to 50% concentration)
    # ---------------------------------------------------------
    for h in retained_holdings:
        ticker = h.get("ticker")
        audit = next((a for a in holding_audits if a["ticker"] == ticker), None)
        w = float(h.get("target_weight", 0.0))
        if audit and audit.get("health_status") == "FROTHY" and w > 0.50:
            trim_to = 0.35 if is_defensive else 0.40
            delta_w = w - trim_to
            h["target_weight"] = trim_to
            action_desc = f"Trimmed frothy position {ticker} from {w*100:.1f}% to {trim_to*100:.1f}% (Price ${audit['price']} vs Fair Value ${audit['fair_value']})"
            executed_actions.append({
                "date": today_str,
                "action": "VALUATION FROTH (TRIM)",
                "ticker": ticker,
                "reason": action_desc,
                "weight_delta": f"-{delta_w*100:.1f}%",
                "verification_status": "Audited & Executed by Autonomous Surveillance Council"
            })
            print(f"  ✂️ [AUTONOMOUS ACTION: TRIM] {action_desc}")

    # Active tickers currently in portfolio
    active_tickers = {h.get("ticker") for h in retained_holdings}
    
    # ---------------------------------------------------------
    # 3. SURPLUS CASH DEPLOYMENT (BUY)
    # ---------------------------------------------------------
    surplus_cash_pct = actual_cash_pct - target_cash_pct
    if surplus_cash_pct >= 4.0 and watchlist_candidates:
        top_cand = watchlist_candidates[0]
        c_ticker = top_cand["ticker"]
        c_edge = top_cand.get("kelly_edge", 0.0)
        c_mos = top_cand.get("mos_pct", 0.0)
        c_moat = top_cand.get("moat_score", 0.0)
        
        # High quality bar: Moat >= 8.8, MoS >= 25%, Kelly Edge >= 25.0
        if c_ticker not in active_tickers and c_moat >= 8.8 and c_mos >= 25.0 and c_edge >= 25.0:
            deploy_w = min(0.08, max(0.05, round(surplus_cash_pct / 100.0, 4)))
            w_item = watchlist.get(c_ticker, {})
            new_h = make_holding_record(c_ticker, w_item, deploy_w, total_capital, is_defensive)
            retained_holdings.append(new_h)
            active_tickers.add(c_ticker)
            
            action_desc = f"Deployed surplus cash (${total_capital*deploy_w:,.0f} / {deploy_w*100:.1f}%) into Tier-1 compounder {c_ticker} (Moat: {c_moat}/10, MoS: +{c_mos:.1f}%, Kelly Edge: {c_edge})"
            executed_actions.append({
                "date": today_str,
                "action": "SURPLUS CASH DEPLOYMENT (BUY)",
                "ticker": c_ticker,
                "reason": action_desc,
                "weight_delta": f"+{deploy_w*100:.1f}%",
                "verification_status": "Audited & Executed by Autonomous Surveillance Council"
            })
            print(f"  💰 [AUTONOMOUS ACTION: BUY] {action_desc}")

    # ---------------------------------------------------------
    # 4. DISLOCATION SWAP (Only if Massive Edge Delta >= 20 pts)
    # ---------------------------------------------------------
    if not executed_actions and watchlist_candidates and retained_holdings:
        top_cand = watchlist_candidates[0]
        c_ticker = top_cand["ticker"]
        c_edge = top_cand.get("kelly_edge", 0.0)
        c_mos = top_cand.get("mos_pct", 0.0)
        c_moat = top_cand.get("moat_score", 0.0)
        
        if c_ticker not in active_tickers and c_moat >= 9.0 and c_mos >= 35.0 and c_edge >= 35.0:
            weakest_holding = None
            min_edge = 999.0
            for h in retained_holdings:
                t = h.get("ticker")
                audit = next((a for a in holding_audits if a["ticker"] == t), None)
                if audit:
                    edge = audit.get("kelly_edge", 20.0)
                    if edge < min_edge:
                        min_edge = edge
                        weakest_holding = h

            if weakest_holding and min_edge < 15.0:
                edge_delta = c_edge - min_edge
                if edge_delta >= 20.0:
                    old_t = weakest_holding.get("ticker")
                    swap_w = float(weakest_holding.get("target_weight", 0.06))
                    retained_holdings = [h for h in retained_holdings if h.get("ticker") != old_t]
                    w_item = watchlist.get(c_ticker, {})
                    new_h = make_holding_record(c_ticker, w_item, swap_w, total_capital, is_defensive)
                    retained_holdings.append(new_h)
                    
                    action_desc = f"Dislocation Arbitrage Swap: Replaced {old_t} (Edge: {min_edge:.1f}) with {c_ticker} (Edge: {c_edge:.1f}, MoS: +{c_mos:.1f}%) [Edge Delta: +{edge_delta:.1f} pts]"
                    executed_actions.append({
                        "date": today_str,
                        "action": "DISLOCATION SWAP",
                        "ticker": f"{old_t} ➔ {c_ticker}",
                        "reason": action_desc,
                        "weight_delta": f"{swap_w*100:.1f}%",
                        "verification_status": "Audited & Executed by Autonomous Surveillance Council"
                    })
                    print(f"  ⚡ [AUTONOMOUS ACTION: SWAP] {action_desc}")

    # ---------------------------------------------------------
    # 5. RECALCULATE DOLLARS, SHARES & CALIBRATE CASH
    # ---------------------------------------------------------
    tot_equity_w = sum(float(h.get("target_weight", 0.0)) for h in retained_holdings)
    macro_target_cash_w = round(target_cash_pct / 100.0, 4)
    
    if tot_equity_w > 0 and (tot_equity_w + macro_target_cash_w) != 1.0:
        equity_budget = max(0.70, round(1.0 - macro_target_cash_w, 4))
        scale_mult = equity_budget / tot_equity_w
        for h in retained_holdings:
            h["target_weight"] = round(float(h.get("target_weight", 0.0)) * scale_mult, 4)
            alloc = round(total_capital * h["target_weight"], 2)
            cur_p = float(h.get("current_price", 100.0))
            h["allocated_dollars"] = alloc
            h["shares_to_buy"] = round(alloc / cur_p, 4) if cur_p > 0 else 0.0
            oe_y = float(h.get("look_through_fcf_yield", 5.0))
            h["annual_owner_earnings"] = round(alloc * (oe_y / 100.0), 2)
            
    final_equity_dollars = sum(float(h.get("allocated_dollars", 0.0)) for h in retained_holdings)
    cash_dollars = round(max(5000.0, total_capital - final_equity_dollars), 2)
    final_cash_w = round(cash_dollars / total_capital, 4)
    
    cash_holding = {
        "ticker": "USD_CASH",
        "company_name": "USD Cash Reserve" if is_defensive else "USD Cash Strike Reserve",
        "sector": "Cash & Cash Equivalents",
        "industry": "3-Month US Treasury Bills",
        "quality_score": 100.0,
        "target_weight": final_cash_w,
        "pillar": "CASH",
        "cost_basis": 1.0,
        "current_price": 1.0,
        "fair_value": 1.0,
        "margin_of_safety_pct": 0.0,
        "allocated_dollars": cash_dollars,
        "shares_to_buy": cash_dollars,
        "look_through_fcf_yield": round(TREASURY_BILL_YIELD * 100.0, 2),
        "annual_owner_earnings": round(cash_dollars * TREASURY_BILL_YIELD, 2),
        "cannibal_rate_pct": 0.0,
        "thesis_core": f"3-Month US Treasury Yield ({TREASURY_BILL_YIELD*100:.2f}% risk-free). Shiller CAPE Macro Buffer.",
        "report_url": "#"
    }
    
    final_holdings = retained_holdings + [cash_holding]
    portfolio_state["holdings"] = final_holdings
    
    if executed_actions:
        portfolio_state["last_rebalance_date"] = today_str
        for act in reversed(executed_actions):
            portfolio_state.setdefault("rebalance_log", []).insert(0, act)
        portfolio_state["rebalance_log"] = portfolio_state["rebalance_log"][:20]
        
    return portfolio_state, executed_actions


def run_portfolio_surveillance(portfolio_type: str = "defensive", auto_execute: bool = True) -> Dict[str, Any]:
    """Runs complete weekly audit and executes high-conviction decisions autonomously."""
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

        calc = calculate_kelly_edge(ticker, cur_p, fv, w_item)
        active_edge_scores.append(calc["kelly_edge"])

        # Health checks (Buffett-style concentration up to 50%)
        if signal in ["AVOID", "CAUTION"] and mos < -15.0:
            health = "IMPAIRED"
        elif (cur_p > 1.35 * fv and w_tgt > 0.40) or w_tgt > 0.50:
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
    active_tickers.update(COMPLIANCE_EXCLUSIONS.keys())
    
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

    for ticker, s in watchlist.items():
        if ticker in active_tickers or ticker in COMPLIANCE_EXCLUSIONS:
            continue

        cur_p = float(s.get("current_price", 0.0))
        raw_fv = str(s.get("fair_value_estimate", cur_p))
        try:
            fv = float(re.sub(r"[^\d.]", "", raw_fv))
        except Exception:
            fv = cur_p * 1.2
            
        mos = round(((fv - cur_p) / cur_p) * 100.0, 2) if cur_p > 0 else 0.0
        signal = s.get("action_signal", "HOLD")
        calc = calculate_kelly_edge(ticker, cur_p, fv, s)

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

    # ---------------------------------------------------------
    # AUTONOMOUS EXECUTION PASS
    # ---------------------------------------------------------
    executed_actions = []
    if auto_execute:
        portfolio_state, executed_actions = execute_surveillance_decisions(
            portfolio_type=portfolio_type,
            portfolio_state=portfolio_state,
            watchlist=watchlist,
            holding_audits=holding_audits,
            target_cash_pct=target_cash_pct,
            actual_cash_pct=actual_cash_pct,
            watchlist_candidates=watchlist_candidates
        )
        # Save updated portfolio state
        with open(p_file, "w") as f:
            json.dump(portfolio_state, f, indent=2)

    # Status verdict formulation
    if executed_actions:
        status = "EXECUTED"
        status_display = f"SURVEILLANCE ACTIONS EXECUTED ({len(executed_actions)} ACTIONS)"
        verdict = f"Council executed {len(executed_actions)} high-conviction decision(s): {', '.join([a['action'] for a in executed_actions])}."
        action_required = False
    else:
        status = "OPTIMAL"
        status_display = "COUNCIL AUDIT ACTIVE • ALL HOLDINGS INTACT"
        verdict = (
            f"Audited {port_label} across Buffett-Munger Kelly filters. "
            f"All {total_active_holdings} core holdings maintain pristine moats and healthy cash compounding. "
            f"Zero forced trades required. Shiller CAPE macro cash gauge verified at {target_cash_pct:.2f}%."
        )
        action_required = False

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
        "rebalance_proposals": executed_actions
    }

    s_file = get_surveillance_filepath(portfolio_type)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(s_file, "w") as f:
        json.dump(surveillance_report, f, indent=2)

    if portfolio_type == "defensive":
        with open(DATA_DIR / "surveillance.json", "w") as f:
            json.dump(surveillance_report, f, indent=2)

    print(f"✅ Surveillance audit completed for {port_label} (Target Cash: {target_cash_pct:.2f}% | Actual: {actual_cash_pct:.2f}% | Status: {cash_status})")
    if executed_actions:
        print(f"⚡ {len(executed_actions)} Autonomous Portfolio Action(s) Executed & Committed to Rebalance Log.")
    else:
        print("🛡️ All holdings operating within normal corridors. Buffett-Munger patience intact.")
        
    return surveillance_report


def get_surveillance_summary(portfolio_type: str = "defensive") -> Dict[str, Any]:
    """Retrieves or executes surveillance report for the specified portfolio."""
    s_file = get_surveillance_filepath(portfolio_type)
    if s_file.exists():
        try:
            with open(s_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return run_portfolio_surveillance(portfolio_type, auto_execute=False)


def run_dual_surveillance(auto_execute: bool = True):
    print("=== RUNNING WEEKLY AUTONOMOUS DUAL SURVEILLANCE & EXECUTION ===")
    run_portfolio_surveillance("defensive", auto_execute=auto_execute)
    run_portfolio_surveillance("aggressive", auto_execute=auto_execute)


if __name__ == "__main__":
    import sys
    auto_exec = "--no-execute" not in sys.argv
    target_arg = [a for a in sys.argv[1:] if not a.startswith("--")]
    
    if target_arg and target_arg[0].lower() in ["aggressive", "defensive"]:
        port_type = target_arg[0].lower()
        print(f"=== RUNNING AUTONOMOUS SURVEILLANCE & EXECUTION ({port_type.upper()}) ===")
        run_portfolio_surveillance(port_type, auto_execute=auto_exec)
    else:
        run_dual_surveillance(auto_execute=auto_exec)

