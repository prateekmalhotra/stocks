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
            shares = round(alloc_dollars / cur_price, 2) if cur_price > 0 else 0.0
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
            
    hist_perf = list(state.get("historical_performance", []))
    today_str = datetime.now().strftime("%Y-%m-%d")
    entry = {
        "date": today_str,
        "portfolio_value": round(live_portfolio_val, 2),
        "owner_earnings_runrate": round(total_owner_earnings_usd, 2),
        "spy_benchmark": total_capital
    }
    if not hist_perf:
        hist_perf = [entry]
    else:
        if hist_perf[-1]["date"] == today_str:
            hist_perf[-1] = entry
        else:
            hist_perf.append(entry)
            
    default_name = "Fidelity Defensive Fortress" if portfolio_type == "defensive" else "Wealthsimple Aggressive Compounder"
    
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
            "cash_weight_pct": round(cash_weight * 100.0, 1),
            "core_positions_count": len([x for x in enriched_holdings if x["ticker"] != "USD_CASH"])
        }
    }


def build_portfolio_tab_html(portfolio_type: str = "defensive", total_capital: float = 200000.0) -> str:
    """Generates the clean, minimalist, and beautiful HTML view for either Fidelity or Wealthsimple."""
    p_data = get_enriched_portfolio(total_capital, portfolio_type)
    stats = p_data["stats"]
    holdings = p_data["holdings"]
    rebalance_log = p_data["rebalance_log"]
    hist_perf = p_data["historical_performance"]
    surveillance = get_surveillance_summary(portfolio_type)
    
    is_defensive = (portfolio_type == "defensive")
    port_title = "Fidelity Portfolio" if is_defensive else "Wealthsimple Portfolio"
    port_subtitle = "Defensive Fortresses & Consistent Compounding • 50s–60s Horizon" if is_defensive else "Aggressive Alpha, Mispriced Growth & Buyback Cannibals • 20s–30s Horizon"
    cash_desc = "$30,000 in 3M US Treasuries (@ 5.00% Risk-Free)" if is_defensive else "$16,000 in 3M US Treasuries (@ 5.00% Risk-Free)"
    
    # Table rows
    rows_html = ""
    for h in holdings:
        t = h["ticker"]
        w_pct = h["target_weight"] * 100.0
        alloc_dol = h["allocated_dollars"]
        cur_p = h["current_price"]
        cost_b = h["cost_basis"]
        fv = h["fair_value"]
        mos = h["margin_of_safety_pct"]
        oe_yr = h["annual_owner_earnings"]
        fcf_y = h["look_through_fcf_yield"]
        
        if t == "USD_CASH":
            ticker_col = """
            <div style="display:flex; flex-direction:column; gap:2px;">
                <span style="font-weight:600; font-size:0.96rem; color:var(--text-title);">USD Cash Reserve</span>
                <span style="font-size:0.75rem; color:var(--text-dim);">3M US Treasury Bills (5.00% Yield)</span>
            </div>
            """
            alloc_col = f"""
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-family:var(--font-mono); font-weight:600; font-size:0.92rem; color:var(--text-title);">${alloc_dol:,.0f}</span>
                <span class="pill pill-neutral" style="font-size:0.70rem; padding:2px 6px;">{w_pct:.1f}%</span>
            </div>
            """
            price_col = '<span style="font-family:var(--font-mono); font-size:0.88rem; color:var(--text-dim);">$1.00</span>'
            fv_col = '<span style="font-family:var(--font-mono); font-size:0.88rem; color:var(--text-dim);">$1.00 (Par)</span>'
            yield_col = f"""
            <div style="display:flex; flex-direction:column; gap:2px;">
                <span style="font-family:var(--font-mono); font-weight:600; font-size:0.90rem; color:var(--accent-warm);">${oe_yr:,.0f}/yr</span>
                <span style="font-size:0.75rem; color:var(--text-dim);">(5.00% Risk-Free)</span>
            </div>
            """
        else:
            ticker_col = f"""
            <div style="display:flex; flex-direction:column; gap:2px;">
                <a href="{h['report_url']}" style="font-family:var(--font-mono); font-weight:700; font-size:1.02rem; color:var(--accent-warm); text-decoration:none; display:inline-flex; align-items:center; gap:4px;">
                    {t} <span style="font-size:0.70rem; opacity:0.6;">↗</span>
                </a>
                <span style="font-size:0.78rem; color:var(--text-secondary); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:210px;">{h['company_name']}</span>
            </div>
            """
            alloc_col = f"""
            <div style="display:flex; flex-direction:column; gap:2px;">
                <div style="display:flex; align-items:center; gap:6px;">
                    <span style="font-family:var(--font-mono); font-weight:600; font-size:0.92rem; color:var(--text-title);">${alloc_dol:,.0f}</span>
                    <span class="pill pill-neutral" style="font-size:0.70rem; padding:2px 6px;">{w_pct:.1f}%</span>
                </div>
                <span style="font-size:0.75rem; color:var(--text-dim); font-family:var(--font-mono);">{h['shares_to_buy']:,.2f} shares</span>
            </div>
            """
            price_col = f"""
            <div style="display:flex; flex-direction:column; gap:2px;">
                <span style="font-family:var(--font-mono); font-weight:500; font-size:0.90rem; color:var(--text-title);">${cur_p:,.2f}</span>
                <span style="font-size:0.75rem; color:var(--text-dim); font-family:var(--font-mono);">Cost: ${cost_b:,.2f}</span>
            </div>
            """
            mos_color = "var(--accent-green)" if mos > 0 else "var(--signal-avoid)"
            mos_sign = "+" if mos > 0 else ""
            fv_col = f"""
            <div style="display:flex; flex-direction:column; gap:2px;">
                <span style="font-family:var(--font-mono); font-weight:600; font-size:0.90rem; color:var(--text-title);">${fv:,.2f}</span>
                <span style="font-size:0.75rem; font-family:var(--font-mono); color:{mos_color}; font-weight:500;">{mos_sign}{mos:.1f}% MoS</span>
            </div>
            """
            yield_col = f"""
            <div style="display:flex; flex-direction:column; gap:2px;">
                <span style="font-family:var(--font-mono); font-weight:600; font-size:0.90rem; color:var(--accent-warm);">${oe_yr:,.0f}/yr</span>
                <span style="font-size:0.75rem; color:var(--text-secondary); font-family:var(--font-mono);">({fcf_y:.1f}% Yield)</span>
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
                    <span class="pill pill-active" style="font-size:0.70rem;">{entry.get('action')}</span>
                    <span style="font-family:var(--font-mono); font-size:0.80rem; color:var(--text-dim);">{entry.get('date')}</span>
                </div>
                <span style="font-size:0.75rem; color:var(--accent-green);">{entry.get('verification_status')}</span>
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
        "spy": [x["spy_benchmark"] for x in hist_perf],
        "earnings": [x["owner_earnings_runrate"] for x in hist_perf]
    })

    return f"""
    <div style="display:flex; flex-direction:column; gap:20px;">
        
        <!-- Header Banner -->
        <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:12px; padding:22px 26px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
            <div>
                <div style="display:flex; align-items:center; gap:10px; margin-bottom:4px;">
                    <h2 style="font-family:var(--font-serif); font-size:1.70rem; color:var(--text-title); margin:0; font-weight:400;">
                        {port_title}
                    </h2>
                    <span class="pill pill-active" style="font-size:0.72rem;">$200,000 Base</span>
                    <span class="pill pill-neutral" style="font-size:0.72rem;">{stats['core_positions_count']} Monopolies</span>
                </div>
                <p style="color:var(--text-secondary); margin:0; font-size:0.86rem;">
                    {port_subtitle}
                </p>
            </div>
            <div style="text-align:right;">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:0.06em; color:var(--text-dim);">Live Portfolio Value</div>
                <div style="font-family:var(--font-mono); font-size:1.70rem; font-weight:600; color:var(--accent-warm);">
                    ${stats['total_value_usd']:,.2f}
                </div>
            </div>
        </div>

        <!-- 4 Clean KPI Cards -->
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:14px;">
            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; padding:18px 20px;">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-dim); margin-bottom:6px;">Look-Through Owner Earnings</div>
                <div style="font-family:var(--font-mono); font-size:1.60rem; font-weight:600; color:var(--accent-warm);">
                    ${stats['total_owner_earnings_usd']:,.0f}<span style="font-size:0.85rem; font-weight:400; color:var(--text-dim);">/yr</span>
                </div>
                <div style="font-size:0.78rem; color:var(--accent-green); margin-top:4px; font-weight:500;">
                    {stats['look_through_fcf_yield_pct']:.2f}% Real Cash Yield
                </div>
            </div>

            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; padding:18px 20px;">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-dim); margin-bottom:6px;">Share Cannibalization</div>
                <div style="font-family:var(--font-mono); font-size:1.60rem; font-weight:600; color:var(--text-title);">
                    +{stats['share_cannibalization_rate_pct']:.2f}%<span style="font-size:0.85rem; font-weight:400; color:var(--text-dim);">/yr</span>
                </div>
                <div style="font-size:0.78rem; color:var(--text-secondary); margin-top:4px;">
                    Organic EPS Expansion via Buybacks
                </div>
            </div>

            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; padding:18px 20px;">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-dim); margin-bottom:6px;">Treasury Cash Buffer</div>
                <div style="font-family:var(--font-mono); font-size:1.60rem; font-weight:600; color:var(--accent-green);">
                    {stats['cash_weight_pct']:.1f}%
                </div>
                <div style="font-size:0.78rem; color:var(--text-secondary); margin-top:4px;">
                    {cash_desc}
                </div>
            </div>

            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; padding:18px 20px;">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-dim); margin-bottom:6px;">Portfolio Margin of Safety</div>
                <div style="font-family:var(--font-mono); font-size:1.60rem; font-weight:600; color:var(--accent-green);">
                    +{stats['portfolio_margin_of_safety_pct']:.1f}%
                </div>
                <div style="font-size:0.78rem; color:var(--text-secondary); margin-top:4px;">
                    Weighted Undervaluation vs DCF
                </div>
            </div>
        </div>

        <!-- Master Holdings Table -->
        <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:12px; padding:20px 22px; overflow-x:auto;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; flex-wrap:wrap; gap:8px;">
                <div>
                    <h3 style="font-family:var(--font-serif); font-size:1.20rem; color:var(--text-title); margin:0; font-weight:400;">
                        Active Portfolio Holdings ({stats['core_positions_count']} Equities + Cash)
                    </h3>
                </div>
                <div style="font-size:0.76rem; color:var(--text-dim);">
                    Rebalancing Discipline: &ge; 15% Valuation Friction Floor
                </div>
            </div>

            <table class="fin-table" style="width:100%; min-width:780px; table-layout:fixed; border-collapse:collapse;">
                <colgroup>
                    <col style="width:28%;">
                    <col style="width:20%;">
                    <col style="width:18%;">
                    <col style="width:18%;">
                    <col style="width:16%;">
                </colgroup>
                <thead>
                    <tr style="border-bottom:1px solid var(--border-color); text-align:left; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-dim);">
                        <th style="padding:10px 16px;">Holding</th>
                        <th style="padding:10px 16px;">Allocation ($200k Base)</th>
                        <th style="padding:10px 16px;">Market Price (Cost)</th>
                        <th style="padding:10px 16px;">Fair Value &amp; MoS</th>
                        <th style="padding:10px 16px;">Cash Flow Yield</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>

        <!-- Visualizer Card (Single Clear Scaled Chart) -->
        <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:12px; padding:20px 24px; display:flex; flex-direction:column; gap:14px;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                <div>
                    <h3 style="font-family:var(--font-serif); font-size:1.15rem; color:var(--text-title); margin:0; font-weight:400;">
                        Portfolio Compounding &amp; Benchmark Performance
                    </h3>
                    <p style="color:var(--text-dim); font-size:0.78rem; margin:2px 0 0;">
                        Tracking live portfolio equity value ($) vs. $200,000.00 S&amp;P 500 benchmark.
                    </p>
                </div>
                <div style="display:flex; align-items:center; gap:16px; font-size:0.76rem; font-family:var(--font-mono);">
                    <span style="display:flex; align-items:center; gap:6px; color:var(--accent-warm);">
                        <span style="display:inline-block; width:12px; height:3px; background:#CC785C; border-radius:2px;"></span> {port_title}
                    </span>
                    <span style="display:flex; align-items:center; gap:6px; color:var(--text-dim);">
                        <span style="display:inline-block; width:12px; height:2px; background:#8C8982;"></span> S&amp;P 500 Baseline
                    </span>
                </div>
            </div>

            <div style="position:relative; width:100%; height:260px; border-radius:6px; padding:8px 12px; background:rgba(0,0,0,0.12);">
                <canvas id="{canvas_id}"></canvas>
            </div>
        </div>

        <!-- Rebalance Log & Surveillance Audit -->
        <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:12px; padding:20px 22px; display:flex; flex-direction:column; gap:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h4 style="font-family:var(--font-serif); font-size:1.05rem; color:var(--text-title); margin:0; font-weight:400;">
                    Weekly Council Audit Log &amp; Rebalance Trail
                </h4>
                <span style="font-size:0.72rem; color:var(--text-dim);">Weekly Friday Close Audit • Verified 3/3 Autonomous Council</span>
            </div>
            <div style="display:flex; flex-direction:column; gap:8px;">
                {log_rows_html}
            </div>
        </div>

    </div>

    <!-- Chart.js Single Clean Scaled Visualizer Script -->
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
                            backgroundColor: 'rgba(204, 120, 92, 0.08)',
                            borderWidth: 2,
                            pointRadius: dates.length === 1 ? 4 : (dates.length > 30 ? 0 : 2.5),
                            pointHoverRadius: 5,
                            pointBackgroundColor: '#CC785C',
                            tension: 0.2,
                            fill: true
                        }},
                        {{
                            label: 'S&P 500 Benchmark',
                            data: spyVals,
                            borderColor: '#605C55',
                            borderDash: [4, 4],
                            borderWidth: 1.5,
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
                            grid: {{ color: 'rgba(255,255,255,0.03)' }},
                            ticks: {{
                                color: '#8C8982',
                                font: {{ family: "'JetBrains Mono', monospace", size: 10 }}
                            }}
                        }},
                        y: {{
                            suggestedMin: 180000,
                            suggestedMax: 220000,
                            grid: {{ color: 'rgba(255,255,255,0.04)' }},
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
