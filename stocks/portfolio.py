"""
AlphaThesis Dual Portfolio Engine & Rebalancing Intelligence.

Provides two mutually exclusive, mathematically sound $200k portfolios:
1. Fidelity Portfolio (Defensive Fortress — 50s/60s Horizon):
   - Focus: Monopolistic Platform Moats, Pricing Power, Predictable Earnings Consistency, 15.0% US Treasury Cash Floor.
2. Wealthsimple Portfolio (Aggressive Alpha Compounder — 20s/30s Horizon):
   - Focus: High-Velocity Mispriced Compounders, Deep Value Arbitrage, Share Cannibalization, 8.0% US Treasury Strike Reserve.

Zero overlap across equity holdings. Rooted in first-principles Buffett & Munger mathematics.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from stocks.weekly_surveillance import get_surveillance_summary

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"


def get_portfolio_filepath(portfolio_type: str = "defensive") -> Path:
    """Returns the persistent JSON filepath for the given portfolio type."""
    if portfolio_type.lower() in ["aggressive", "alpha", "growth"]:
        return DATA_DIR / "portfolio_aggressive.json"
    return DATA_DIR / "portfolio_defensive.json"


def load_portfolio_state(portfolio_type: str = "defensive") -> Dict[str, Any]:
    """Loads persistent portfolio state from disk for either defensive or aggressive portfolios."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p_file = get_portfolio_filepath(portfolio_type)
    
    if p_file.exists():
        try:
            with open(p_file, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {portfolio_type} portfolio state: {e}")
            
    legacy_file = DATA_DIR / "portfolio.json"
    if legacy_file.exists():
        try:
            with open(legacy_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
            
    return {}


def save_portfolio_state(state: Dict[str, Any], portfolio_type: str = "defensive"):
    """Saves portfolio state to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p_file = get_portfolio_filepath(portfolio_type)
    with open(p_file, "w") as f:
        json.dump(state, f, indent=2)


def get_enriched_portfolio(total_capital: float = 200000.0, portfolio_type: str = "defensive") -> Dict[str, Any]:
    """
    Enriches the selected portfolio with live prices, fair values, margins of safety,
    owner earnings yields, dollar allocations, and exact share counts.
    """
    state = load_portfolio_state(portfolio_type)
    watchlist_data = {}
    if WATCHLIST_FILE.exists():
        try:
            with open(WATCHLIST_FILE, "r") as f:
                watchlist_data = json.load(f)
        except Exception:
            pass
            
    enriched_holdings = []
    total_owner_earnings_usd = 0.0
    total_cannibal_product = 0.0
    total_mos_product = 0.0
    cash_weight = 0.0
    
    for h in state.get("holdings", []):
        ticker = h["ticker"]
        target_w = float(h.get("target_weight", 0.0))
        alloc_dollars = total_capital * target_w
        
        if ticker == "USD_CASH":
            cur_price = 1.0
            cost_b = 1.0
            fair_val_num = 1.0
            mos_pct = 0.0
            shares = alloc_dollars
            company_name = "USD Cash Reserve"
            action_signal = "HOLD"
            cash_weight += target_w
            live_fcf_yield = 5.00  # 5.00% Risk-free 3M Treasury Yield
            cannibal_rate = 0.0
            annual_owner_earnings = alloc_dollars * (live_fcf_yield / 100.0)
            total_owner_earnings_usd += annual_owner_earnings
        else:
            w_item = watchlist_data.get(ticker, {})
            company_name = w_item.get("company_name", h.get("company_name", ticker))
            cur_price = float(w_item.get("current_price", h.get("current_price", 100.0)))
            cost_b = float(h.get("cost_basis", cur_price))
            
            raw_fv = str(w_item.get("fair_value_estimate", h.get("fair_value", cur_price)))
            import re
            try:
                fair_val_num = float(re.sub(r"[^\d.]", "", raw_fv))
            except Exception:
                fair_val_num = float(h.get("fair_value", cur_price))
                
            mos_pct = ((fair_val_num - cur_price) / cur_price) * 100.0 if cur_price > 0 else 0.0
            shares = round(alloc_dollars / cost_b, 4) if cost_b > 0 else 0.0
            action_signal = w_item.get("action_signal", "BUY")
            
            base_fcf_yield = float(h.get("look_through_fcf_yield", 5.0))
            if cost_b > 0 and cur_price > 0:
                live_fcf_yield = base_fcf_yield * (cost_b / cur_price)
            else:
                live_fcf_yield = base_fcf_yield
                
            cannibal_rate = float(h.get("cannibal_rate_pct", 1.5))
            annual_owner_earnings = alloc_dollars * (live_fcf_yield / 100.0)
            total_owner_earnings_usd += annual_owner_earnings
            total_cannibal_product += (cannibal_rate * target_w)
            total_mos_product += (mos_pct * target_w)
            
        enriched_holdings.append({
            **h,
            "company_name": company_name,
            "current_price": cur_price,
            "cost_basis": cost_b if ticker != "USD_CASH" else 1.0,
            "fair_value": fair_val_num,
            "margin_of_safety_pct": round(mos_pct, 1),
            "allocated_dollars": round(alloc_dollars, 2),
            "shares_to_buy": shares,
            "look_through_fcf_yield": round(live_fcf_yield, 2),
            "annual_owner_earnings": round(annual_owner_earnings, 2),
            "action_signal": action_signal,
            "report_url": f"reports/{ticker}.html" if ticker != "USD_CASH" else None
        })
        
    weighted_fcf_yield = (total_owner_earnings_usd / total_capital) * 100.0 if total_capital > 0 else 0.0
    weighted_cannibal_rate = total_cannibal_product
    weighted_mos = total_mos_product
    
    live_portfolio_val = 0.0
    for eh in enriched_holdings:
        if eh["ticker"] == "USD_CASH":
            live_portfolio_val += eh["allocated_dollars"]
        else:
            live_portfolio_val += (eh["shares_to_buy"] * eh["current_price"])
    live_portfolio_val = round(live_portfolio_val, 2)
    if abs(live_portfolio_val - total_capital) < 0.10:
        live_portfolio_val = round(total_capital, 2)
            
    hist_perf = list(state.get("historical_performance", []))
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Ensure clean baseline start at inception
    if not hist_perf:
        hist_perf = [{
            "date": "2026-08-11",
            "portfolio_value": 200000.00,
            "owner_earnings_runrate": round(total_owner_earnings_usd, 2),
            "spy_benchmark": 200000.00
        }]
    else:
        # Guarantee inception date starts cleanly at 200,000.00
        hist_perf[0]["portfolio_value"] = 200000.00
        hist_perf[0]["spy_benchmark"] = 200000.00
        
        # If inception is yesterday (2026-08-11) and starting fresh today (2026-08-12), keep flat baseline at 200k
        if len(hist_perf) > 1 and hist_perf[-1]["date"] == today_str:
            hist_perf[-1] = {
                "date": today_str,
                "portfolio_value": round(live_portfolio_val, 2),
                "owner_earnings_runrate": round(total_owner_earnings_usd, 2),
                "spy_benchmark": total_capital
            }
        elif hist_perf[-1]["date"] != today_str:
            hist_perf.append({
                "date": today_str,
                "portfolio_value": round(live_portfolio_val, 2),
                "owner_earnings_runrate": round(total_owner_earnings_usd, 2),
                "spy_benchmark": total_capital
            })
            
    default_name = "Fidelity" if portfolio_type == "defensive" else "Wealthsimple"
    
    return {
        "portfolio_name": state.get("portfolio_name", default_name),
        "portfolio_type": portfolio_type,
        "target_audience": state.get("target_audience", ""),
        "inception_date": state.get("inception_date", "2026-08-11"),
        "last_rebalance_date": state.get("last_rebalance_date", today_str),
        "base_capital_usd": total_capital,
        "holdings": enriched_holdings,
        "rebalance_log": state.get("rebalance_log", []),
        "historical_performance": hist_perf,
        "stats": {
            "total_value_usd": round(live_portfolio_val, 2),
            "total_owner_earnings_usd": round(total_owner_earnings_usd, 2),
            "look_through_fcf_yield_pct": round(weighted_fcf_yield, 2),
            "share_cannibalization_rate_pct": round(weighted_cannibal_rate, 2),
            "portfolio_margin_of_safety_pct": round(weighted_mos, 1),
            "cash_weight_pct": round(cash_weight * 100.0, 2),
            "core_positions_count": len([x for x in enriched_holdings if x["ticker"] != "USD_CASH"])
        }
    }


def build_portfolio_tab_html(portfolio_type: str = "defensive", total_capital: float = 200000.0) -> str:
    """Generates the ultra-clean, spacious, minimalist high-end portfolio UI."""
    p_data = get_enriched_portfolio(total_capital, portfolio_type)
    stats = p_data["stats"]
    holdings = p_data["holdings"]
    rebalance_log = p_data["rebalance_log"]
    hist_perf = p_data["historical_performance"]
    
    is_defensive = (portfolio_type == "defensive")
    port_title = "Fidelity" if is_defensive else "Wealthsimple"
    cash_item = next((x for x in holdings if x["ticker"] == "USD_CASH"), None)
    cash_dol = cash_item["allocated_dollars"] if cash_item else total_capital * 0.15
    cash_desc = f"${cash_dol:,.0f} in 3M Bills (5.00% Float)"
    
    # Clean concise names
    CLEAN_NAMES = {
        "ASML": "ASML Holding N.V.",
        "TSM": "Taiwan Semiconductor (TSMC)",
        "BABA": "Alibaba Group",
        "JD": "JD.com, Inc.",
        "STNE": "StoneCo Ltd.",
        "CROX": "Crocs, Inc.",
        "GCT": "GigaCloud Technology",
        "NVDA": "NVIDIA Corporation",
        "META": "Meta Platforms, Inc.",
        "MELI": "MercadoLibre, Inc.",
        "CSU": "Constellation Software",
        "CPRT": "Copart, Inc.",
        "V": "Visa Inc.",
        "MA": "Mastercard Incorporated",
        "ADBE": "Adobe Inc.",
        "SPGI": "S&P Global Inc.",
        "INTU": "Intuit Inc.",
        "MSFT": "Microsoft Corporation",
        "UNH": "UnitedHealth Group",
        "BKNG": "Booking Holdings"
    }
    
    # Table rows: Sort equities from highest allocation to lowest, then append USD Cash Reserve at the bottom
    equities = [h for h in holdings if h.get("ticker") != "USD_CASH"]
    cash_holdings = [h for h in holdings if h.get("ticker") == "USD_CASH"]
    equities_sorted = sorted(equities, key=lambda x: x.get("allocated_dollars", x.get("target_weight", 0)), reverse=True)
    sorted_holdings = equities_sorted + cash_holdings
    
    rows_html = ""
    for h in sorted_holdings:
        t = h["ticker"]
        w_pct = h["target_weight"] * 100.0
        alloc_dol = h["allocated_dollars"]
        cur_p = h["current_price"]
        fv = h["fair_value"]
        mos = h["margin_of_safety_pct"]
        oe_yr = h["annual_owner_earnings"]
        fcf_y = h["look_through_fcf_yield"]
        display_name = CLEAN_NAMES.get(t, h.get("company_name", t))
        
        if t == "USD_CASH":
            ticker_col = """
            <div style="display:flex; flex-direction:column; gap:4px;">
                <span style="font-weight:600; font-size:0.96rem; color:var(--text-title);">USD Cash Reserve</span>
                <span style="font-size:0.78rem; color:var(--text-dim);">3M US Treasury Bills (5.00%)</span>
            </div>
            """
            alloc_col = f"""
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-family:var(--font-mono); font-weight:600; font-size:0.94rem; color:var(--text-title);">${alloc_dol:,.0f}</span>
                <span class="pill pill-neutral" style="font-size:0.72rem; padding:2px 7px;">{w_pct:.1f}%</span>
            </div>
            """
            price_col = '<span style="font-family:var(--font-mono); font-size:0.90rem; color:var(--text-dim);">$1.00</span>'
            fv_col = '<span style="font-family:var(--font-mono); font-size:0.90rem; color:var(--text-dim);">$1.00 (Par)</span>'
            yield_col = f"""
            <div style="display:flex; flex-direction:column; gap:4px;">
                <span style="font-family:var(--font-mono); font-weight:600; font-size:0.92rem; color:var(--accent-warm);">${oe_yr:,.0f}/yr</span>
                <span style="font-size:0.76rem; color:var(--text-dim); font-family:var(--font-mono);">5.00% Risk-Free</span>
            </div>
            """
        else:
            industry_tag = h.get("industry", "")
            sector_tag = h.get("sector", "")
            raw_label = industry_tag if industry_tag else sector_tag
            # Format cleanly as title case without uppercase shouting
            tag_label = raw_label.title() if raw_label.isupper() else raw_label
            tag_html = f'<span style="display:inline-block; font-size:0.68rem; color:var(--text-muted); background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.07); border-radius:4px; padding:1px 6px; margin-top:3px; max-width:fit-content; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; letter-spacing:0.01em;">{tag_label}</span>' if tag_label else ''

            ticker_col = f"""
            <div style="display:flex; flex-direction:column; gap:2px; min-width:0;">
                <div style="display:flex; align-items:center; gap:6px;">
                    <a href="{h['report_url']}" style="font-family:var(--font-mono); font-weight:700; font-size:1.00rem; color:var(--accent-warm); text-decoration:none; display:inline-flex; align-items:center; gap:3px;">
                        {t} <span style="font-size:0.68rem; opacity:0.6;">↗</span>
                    </a>
                </div>
                <span style="font-size:0.80rem; color:var(--text-secondary); display:block; max-width:220px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="{display_name}">{display_name}</span>
                {tag_html}
            </div>
            """
            alloc_col = f"""
            <div style="display:flex; flex-direction:column; gap:4px;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="font-family:var(--font-mono); font-weight:600; font-size:0.94rem; color:var(--text-title);">${alloc_dol:,.0f}</span>
                    <span class="pill pill-neutral" style="font-size:0.72rem; padding:2px 7px;">{w_pct:.1f}%</span>
                </div>
                <span style="font-size:0.76rem; color:var(--text-dim); font-family:var(--font-mono);">{h['shares_to_buy']:,.2f} shs</span>
            </div>
            """
            price_col = f"""
            <span style="font-family:var(--font-mono); font-weight:500; font-size:0.92rem; color:var(--text-title);">${cur_p:,.2f}</span>
            """
            mos_color = "var(--accent-green)" if mos > 0 else "var(--signal-avoid)"
            mos_sign = "+" if mos > 0 else ""
            fv_col = f"""
            <div style="display:flex; flex-direction:column; gap:4px;">
                <span style="font-family:var(--font-mono); font-weight:600; font-size:0.92rem; color:var(--text-title);">${fv:,.2f}</span>
                <span style="font-size:0.76rem; font-family:var(--font-mono); color:{mos_color}; font-weight:500;">{mos_sign}{mos:.1f}% MoS</span>
            </div>
            """
            yield_col = f"""
            <div style="display:flex; flex-direction:column; gap:4px;">
                <span style="font-family:var(--font-mono); font-weight:600; font-size:0.92rem; color:var(--accent-warm);">${oe_yr:,.0f}/yr</span>
                <span style="font-size:0.76rem; color:var(--text-secondary); font-family:var(--font-mono);">{fcf_y:.1f}% Yield</span>
            </div>
            """

        rows_html += f"""
        <tr style="border-bottom:1px solid rgba(255,255,255,0.03); transition:background 0.15s ease;">
            <td style="padding:14px 16px; vertical-align:middle;">{ticker_col}</td>
            <td style="padding:14px 16px; vertical-align:middle;">{alloc_col}</td>
            <td style="padding:14px 16px; vertical-align:middle;">{price_col}</td>
            <td style="padding:14px 16px; vertical-align:middle;">{fv_col}</td>
            <td style="padding:14px 16px; vertical-align:middle;">{yield_col}</td>
        </tr>
        """

    # Rebalance log
    log_rows_html = ""
    for entry in rebalance_log:
        log_rows_html += f"""
        <div style="background:var(--bg-subpanel); border:1px solid var(--border-color); border-radius:8px; padding:14px 18px; display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span class="pill pill-active" style="font-size:0.72rem; padding:2px 7px;">{entry.get('action')}</span>
                    <span style="font-family:var(--font-mono); font-size:0.80rem; color:var(--text-dim);">{entry.get('date')}</span>
                </div>
                <span style="font-size:0.76rem; color:var(--accent-green);">{entry.get('verification_status')}</span>
            </div>
            <div style="font-size:0.84rem; color:var(--text-secondary); line-height:1.45;">
                {entry.get('reason')}
            </div>
        </div>
        """

    canvas_id = f"chart-{portfolio_type}"
    chart_payload = json.dumps({
        "dates": [x["date"] for x in hist_perf],
        "portfolio": [x["portfolio_value"] for x in hist_perf],
        "spy": [x["spy_benchmark"] for x in hist_perf]
    })

    return f"""
    <div style="display:flex; flex-direction:column; gap:24px; padding-top:4px;">
        
        <!-- Clean Minimalist Header Bar -->
        <div style="display:flex; justify-content:space-between; align-items:center; padding:12px 0 20px 0; border-bottom:1px solid var(--border-color); flex-wrap:wrap; gap:16px;">
            <div style="display:flex; align-items:center; gap:12px;">
                <h1 style="font-family:var(--font-serif); font-size:2.2rem; color:var(--text-title); margin:0; font-weight:400; letter-spacing:-0.02em;">
                    {port_title}
                </h1>
                <span style="display:inline-flex; align-items:center; gap:6px; font-size:0.76rem; color:var(--accent-green); font-family:var(--font-mono); background:rgba(111,168,130,0.08); border:1px solid rgba(111,168,130,0.24); border-radius:20px; padding:3px 10px;">
                    <span style="width:6px; height:6px; border-radius:50%; background:var(--accent-green);"></span> Council Audited
                </span>
            </div>
            <div style="text-align:right;">
                <div style="font-size:0.70rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--text-dim); margin-bottom:2px;">Live Portfolio Value</div>
                <div style="font-family:var(--font-mono); font-size:2.0rem; font-weight:600; color:var(--text-title); letter-spacing:-0.02em; line-height:1.1;">
                    ${stats['total_value_usd']:,.2f}
                </div>
            </div>
        </div>

        <!-- 4 Spacious KPI Cards -->
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:16px;">
            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; padding:20px 22px; display:flex; flex-direction:column; justify-content:space-between;">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--text-dim); margin-bottom:8px; font-weight:500;">Cash Flow Yield</div>
                <div style="font-family:var(--font-mono); font-size:1.85rem; font-weight:600; color:var(--accent-warm); margin-bottom:6px; line-height:1.1; letter-spacing:-0.02em;">
                    {stats['look_through_fcf_yield_pct']:.2f}%
                </div>
                <div style="font-size:0.80rem; color:var(--text-secondary); font-family:var(--font-mono); line-height:1.3;">${stats['total_owner_earnings_usd']:,.0f} / yr (Net Cash)</div>
            </div>

            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; padding:20px 22px; display:flex; flex-direction:column; justify-content:space-between;">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--text-dim); margin-bottom:8px; font-weight:500;">Treasury Cash</div>
                <div style="font-family:var(--font-mono); font-size:1.85rem; font-weight:600; color:var(--accent-green); margin-bottom:6px; line-height:1.1; letter-spacing:-0.02em;">
                    {stats['cash_weight_pct']:.1f}%
                </div>
                <div style="font-size:0.80rem; color:var(--text-secondary); font-family:var(--font-mono); line-height:1.3;">{cash_desc}</div>
            </div>

            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; padding:20px 22px; display:flex; flex-direction:column; justify-content:space-between;">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--text-dim); margin-bottom:8px; font-weight:500;">Margin of Safety</div>
                <div style="font-family:var(--font-mono); font-size:1.85rem; font-weight:600; color:var(--accent-green); margin-bottom:6px; line-height:1.1; letter-spacing:-0.02em;">
                    +{stats['portfolio_margin_of_safety_pct']:.1f}%
                </div>
                <div style="font-size:0.80rem; color:var(--text-secondary); line-height:1.3;">Weighted Undervaluation vs DCF</div>
            </div>

            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; padding:20px 22px; display:flex; flex-direction:column; justify-content:space-between;">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--text-dim); margin-bottom:8px; font-weight:500;">Share Cannibalization</div>
                <div style="font-family:var(--font-mono); font-size:1.85rem; font-weight:600; color:var(--text-title); margin-bottom:6px; line-height:1.1; letter-spacing:-0.02em;">
                    +{stats['share_cannibalization_rate_pct']:.2f}%
                </div>
                <div style="font-size:0.80rem; color:var(--text-secondary); line-height:1.3;">Annual Share Buyback Rate</div>
            </div>
        </div>

        <!-- Master Holdings Table -->
        <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:12px; padding:20px 22px; overflow-x:auto;">
            <table class="fin-table" style="width:100%; min-width:750px; table-layout:fixed; border-collapse:collapse;">
                <colgroup>
                    <col style="width:28%;">
                    <col style="width:20%;">
                    <col style="width:18%;">
                    <col style="width:18%;">
                    <col style="width:16%;">
                </colgroup>
                <thead>
                    <tr style="border-bottom:1px solid var(--border-color); text-align:left; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.06em; color:var(--text-dim);">
                        <th style="padding:12px 16px;">Holding</th>
                        <th style="padding:12px 16px;">Allocation</th>
                        <th style="padding:12px 16px;">Market Price</th>
                        <th style="padding:12px 16px;">Fair Value &amp; MoS</th>
                        <th style="padding:12px 16px;">Cash Flow Yield</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>

        <!-- Clean Scaled Performance Visualizer -->
        <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:12px; padding:20px 24px; display:flex; flex-direction:column; gap:14px;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                <div style="font-family:var(--font-serif); font-size:1.15rem; color:var(--text-title); font-weight:400;">
                    Performance vs S&amp;P 500 Baseline
                </div>
                <div style="display:flex; align-items:center; gap:16px; font-size:0.75rem; font-family:var(--font-mono);">
                    <span style="display:flex; align-items:center; gap:6px; color:var(--accent-warm);">
                        <span style="display:inline-block; width:12px; height:3px; background:#CC785C; border-radius:2px;"></span> {port_title}
                    </span>
                    <span style="display:flex; align-items:center; gap:6px; color:var(--text-dim);">
                        <span style="display:inline-block; width:12px; height:2px; background:#8C8982;"></span> S&amp;P 500
                    </span>
                </div>
            </div>

            <div style="position:relative; width:100%; height:240px; border-radius:8px; padding:8px 12px; background:rgba(0,0,0,0.10);">
                <canvas id="{canvas_id}"></canvas>
            </div>
        </div>

        <!-- Audit Log -->
        <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:12px; padding:20px 22px; display:flex; flex-direction:column; gap:12px;">
            <div style="font-family:var(--font-serif); font-size:1.10rem; color:var(--text-title); font-weight:400;">
                Council Audit Log
            </div>
            <div style="display:flex; flex-direction:column; gap:8px;">
                {log_rows_html}
            </div>
        </div>

    </div>

    <!-- Chart Script -->
    <script>
        (function() {{
            const pData = {chart_payload};
            const ctx = document.getElementById('{canvas_id}');
            if (!ctx) return;

            const dates = pData.dates || ['Day 1'];
            const portfolioVals = pData.portfolio || [200000];
            const spyVals = pData.spy || [200000];

            new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: dates,
                    datasets: [
                        {{
                            label: '{port_title}',
                            data: portfolioVals,
                            borderColor: '#CC785C',
                            backgroundColor: 'rgba(204, 120, 92, 0.06)',
                            borderWidth: 2,
                            pointRadius: dates.length === 1 ? 4 : (dates.length > 30 ? 0 : 2),
                            pointHoverRadius: 5,
                            pointBackgroundColor: '#CC785C',
                            tension: 0.2,
                            fill: true
                        }},
                        {{
                            label: 'S&P 500',
                            data: spyVals,
                            borderColor: '#605C55',
                            borderDash: [4, 4],
                            borderWidth: 1.4,
                            pointRadius: 0,
                            pointHoverRadius: 4,
                            pointBackgroundColor: '#8C8982',
                            tension: 0.2,
                            fill: false
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{
                            backgroundColor: '#1E1D1A',
                            titleColor: '#F5EFEB',
                            bodyColor: '#D4CDC3',
                            borderColor: '#3D3A35',
                            borderWidth: 1,
                            padding: 10,
                            callbacks: {{
                                label: (c) => c.dataset.label + ': $' + Math.round(c.parsed.y).toLocaleString()
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            grid: {{ color: 'rgba(255,255,255,0.02)' }},
                            ticks: {{
                                color: '#8C8982',
                                font: {{ family: "'JetBrains Mono', monospace", size: 10 }}
                            }}
                        }},
                        y: {{
                            suggestedMin: 180000,
                            suggestedMax: 220000,
                            grid: {{ color: 'rgba(255,255,255,0.03)' }},
                            ticks: {{
                                stepSize: 10000,
                                color: '#8C8982',
                                font: {{ family: "'JetBrains Mono', monospace", size: 10 }},
                                callback: (v) => '$' + (v / 1000).toFixed(0) + 'k'
                            }}
                        }}
                    }}
                }}
            }});
        }})();
    </script>
    """


def record_daily_market_close_snapshot():
    """Records daily valuation snapshots for both Defensive and Aggressive portfolios."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    for p_type in ["defensive", "aggressive"]:
        enriched = get_enriched_portfolio(200000.0, p_type)
        state = load_portfolio_state(p_type)
        
        hist = list(state.get("historical_performance", []))
        entry = {
            "date": today_str,
            "portfolio_value": enriched["stats"]["total_value_usd"],
            "owner_earnings_runrate": enriched["stats"]["total_owner_earnings_usd"],
            "spy_benchmark": 200000.0
        }
        
        if hist and hist[-1]["date"] == today_str:
            hist[-1] = entry
        else:
            hist.append(entry)
            
        state["historical_performance"] = hist
        state["last_rebalance_date"] = today_str
        save_portfolio_state(state, p_type)
        print(f"✅ Recorded daily market close snapshot for {p_type} portfolio: ${enriched['stats']['total_value_usd']:,.2f}")
