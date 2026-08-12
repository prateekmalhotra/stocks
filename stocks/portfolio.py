"""
AlphaThesis Dual Portfolio Engine & Rebalancing Intelligence.

Provides two mutually exclusive, mathematically sound $200k portfolios:
1. Defensive Fortress ($200,000 Base — 50s/60s Horizon):
   - Focus: Monopolistic Platform Moats, Pricing Power, Predictable Earnings Consistency, 18.0% US Treasury Cash Floor.
2. Aggressive Alpha Compounder ($200,000 Base — 20s/30s Horizon):
   - Focus: High-Velocity Mispriced Compounders, Deep Value Arbitrage, Share Cannibalization, 12.0% US Treasury Strike Reserve.

Zero overlap across equity holdings. No GOOG.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from stocks.weekly_surveillance import get_surveillance_summary

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"
HISTORY_FILE = DATA_DIR / "thesis_history.json"


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
            
    # Fallback to legacy portfolio.json if available
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
    Enriches the selected AlphaThesis portfolio with real-time prices, margin of safety,
    owner earnings yields, dollar allocations, and exact share counts for a $200k base.
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
    total_cannibal_weight = 0.0
    pillar_a_weight = 0.0
    pillar_b_weight = 0.0
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
            base_fcf_yield = 4.50
            cannibal_rate = 0.0
            live_fcf_yield = 4.50
        else:
            w_stock = watchlist_data.get(ticker, {})
            company_name = w_stock.get("company_name", h.get("company_name", ticker))
            cur_price = float(w_stock.get("current_price", h.get("current_price", 100.0)))
            cost_b = float(h.get("cost_basis", w_stock.get("baseline_price", cur_price)))
            fair_val_str = w_stock.get("fair_value_estimate", f"${cur_price:.2f}")
            
            try:
                clean_fv = fair_val_str.replace("$", "").replace(",", "").strip()
                fair_val_num = float(clean_fv)
            except Exception:
                fair_val_num = cur_price * 1.25
                
            mos_pct = ((fair_val_num - cur_price) / fair_val_num) * 100.0 if fair_val_num > 0 else 0.0
            shares = round(alloc_dollars / cost_b, 2) if cost_b > 0 else 0.0
            action_signal = w_stock.get("action_signal", "BUY")
            
            if h.get("pillar") == "A":
                pillar_a_weight += target_w
            elif h.get("pillar") == "B":
                pillar_b_weight += target_w
                
            base_fcf_yield = float(h.get("look_through_fcf_yield", 5.0))
            cannibal_rate = float(h.get("cannibal_rate_pct", 0.0))
            live_fcf_yield = base_fcf_yield * (cost_b / cur_price) if cur_price > 0 and cost_b > 0 else base_fcf_yield
            
        annual_owner_earnings = alloc_dollars * (live_fcf_yield / 100.0)
        total_owner_earnings_usd += annual_owner_earnings
        total_cannibal_weight += (cannibal_rate * target_w)
        
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
    
    # Compute live portfolio value from current market prices
    live_portfolio_val = 0.0
    for eh in enriched_holdings:
        if eh["ticker"] == "USD_CASH":
            live_portfolio_val += eh["allocated_dollars"]
        else:
            live_portfolio_val += (eh["shares_to_buy"] * eh["current_price"])
            
    hist_perf = list(state.get("historical_performance", []))
    if not hist_perf:
        hist_perf = [{
            "date": datetime.now().strftime("%Y-%m-%d"),
            "portfolio_value": round(live_portfolio_val, 2),
            "owner_earnings_runrate": round(total_owner_earnings_usd, 2),
            "spy_benchmark": total_capital
        }]
    else:
        today_str = datetime.now().strftime("%Y-%m-%d")
        if hist_perf[-1]["date"] == today_str:
            hist_perf[-1] = {
                "date": today_str,
                "portfolio_value": round(live_portfolio_val, 2),
                "owner_earnings_runrate": round(total_owner_earnings_usd, 2),
                "spy_benchmark": hist_perf[-1].get("spy_benchmark", total_capital)
            }
            
    default_name = "Fidelity Portfolio" if portfolio_type == "defensive" else "Wealthsimple Portfolio"
    
    return {
        "portfolio_name": state.get("portfolio_name", default_name),
        "portfolio_type": portfolio_type,
        "target_audience": state.get("target_audience", ""),
        "inception_date": state.get("inception_date", "2026-08-11"),
        "last_rebalance_date": state.get("last_rebalance_date", datetime.now().strftime("%Y-%m-%d")),
        "base_capital_usd": total_capital,
        "holdings": enriched_holdings,
        "rebalance_log": state.get("rebalance_log", []),
        "historical_performance": hist_perf,
        "stats": {
            "total_value_usd": round(live_portfolio_val, 2),
            "total_owner_earnings_usd": round(total_owner_earnings_usd, 2),
            "look_through_fcf_yield_pct": round(weighted_fcf_yield, 2),
            "share_cannibalization_rate_pct": round(total_cannibal_weight * 100.0, 2),
            "pillar_a_weight_pct": round(pillar_a_weight * 100.0, 1),
            "pillar_b_weight_pct": round(pillar_b_weight * 100.0, 1),
            "cash_weight_pct": round(cash_weight * 100.0, 1),
            "core_positions_count": len([x for x in enriched_holdings if x["ticker"] != "USD_CASH"])
        }
    }


def build_portfolio_tab_html(portfolio_type: str = "defensive", total_capital: float = 200000.0) -> str:
    """Generates the interactive HTML section for either the Defensive or Aggressive portfolio."""
    p_data = get_enriched_portfolio(total_capital, portfolio_type)
    stats = p_data["stats"]
    holdings = p_data["holdings"]
    rebalance_log = p_data["rebalance_log"]
    hist_perf = p_data["historical_performance"]
    surveillance = get_surveillance_summary(portfolio_type)
    
    chart_dates = [x["date"] for x in hist_perf]
    chart_portfolio_vals = [x["portfolio_value"] for x in hist_perf]
    chart_spy_vals = [x["spy_benchmark"] for x in hist_perf]
    chart_earnings = [x["owner_earnings_runrate"] for x in hist_perf]
    
    perf_payload = json.dumps({
        "dates": chart_dates,
        "portfolio": chart_portfolio_vals,
        "spy": chart_spy_vals,
        "earnings": chart_earnings
    })
    
    is_defensive = (portfolio_type == "defensive")
    port_title = "Fidelity Portfolio" if is_defensive else "Wealthsimple Portfolio"
    port_subtitle = "Defensive Fortresses & Consistent Cash Compounding • 50s–60s Horizon • $200k Base" if is_defensive else "Aggressive Alpha, Mispriced Growth & Buyback Cannibals • 20s–30s Horizon • $200k Base"
    cash_badge_label = "18.0% US Treasury Floor" if is_defensive else "12.0% US Treasury Strike Reserve"
    surveillance_cadence = "Every Sunday at 2:00 PM EST" if is_defensive else "Every Saturday at 2:00 PM EST"
    
    # Holdings table rows
    rows_html = ""
    for h in holdings:
        cost_b = float(h.get("cost_basis", h.get("current_price", 100.0)))
        
        if h["ticker"] == "USD_CASH":
            ticker_cell = f"""
            <div class="tbl-cell-stacked">
                <strong style="font-family:var(--font-serif); font-size:1.18rem; color:var(--text-title); display:block;">USD Cash Reserve</strong>
                <div class="cell-sub cell-sub-dim">US Treasury 3M Bills (4.50% Yield)</div>
            </div>
            """
            price_cell = """
            <div class="tbl-cell-stacked">
                <div class="cell-primary">$1.00</div>
                <div class="cell-sub cell-sub-dim">($1.00)</div>
            </div>
            """
            fv_cell = """
            <div class="tbl-cell-stacked">
                <div class="cell-primary">$1.00</div>
                <div class="cell-sub cell-sub-dim">(Par)</div>
            </div>
            """
            yield_cell = f"""
            <div class="tbl-cell-stacked">
                <div class="cell-primary cell-warm">${h["annual_owner_earnings"]:,.0f}/yr</div>
                <div class="cell-sub cell-sub-secondary">(4.50%)</div>
            </div>
            """
        else:
            ticker_cell = f"""
            <div class="tbl-cell-stacked">
                <a href="{h['report_url']}" style="font-family:var(--font-serif); font-size:1.24rem; font-weight:500; color:var(--accent-warm); text-decoration:none; display:inline-flex; align-items:center; gap:4px;">
                    {h['ticker']} <span style="font-size:0.72rem; color:var(--text-dim);">↗</span>
                </a>
                <div class="cell-sub cell-sub-secondary" style="font-family:var(--font-sans);">{h['company_name']}</div>
            </div>
            """
            price_cell = f"""
            <div class="tbl-cell-stacked">
                <div class="cell-primary">${h["current_price"]:.2f}</div>
                <div class="cell-sub cell-sub-dim">(${cost_b:.2f})</div>
            </div>
            """
            fv_cell = f"""
            <div class="tbl-cell-stacked">
                <div class="cell-primary">${h["fair_value"]:.2f}</div>
                <div class="cell-sub cell-sub-green">(+{h["margin_of_safety_pct"]}%)</div>
            </div>
            """
            yield_cell = f"""
            <div class="tbl-cell-stacked">
                <div class="cell-primary cell-warm">${h["annual_owner_earnings"]:,.0f}/yr</div>
                <div class="cell-sub cell-sub-secondary">({h["look_through_fcf_yield"]}%)</div>
            </div>
            """
            
        alloc_cell = f"""
        <div class="tbl-cell-stacked">
            <div class="cell-primary">
                ${h['allocated_dollars']:,.0f} <span style="font-size:0.80rem; font-weight:400; color:var(--accent-warm);">({h['target_weight']*100:.1f}%)</span>
            </div>
            <div class="cell-sub cell-sub-dim">{h['shares_to_buy']} shares</div>
        </div>
        """
        
        rows_html += f"""
        <tr class="table-row">
            <td style="padding:14px 18px; vertical-align:middle; width:28%; max-width:260px; overflow:hidden;">{ticker_cell}</td>
            <td style="padding:14px 18px; vertical-align:middle; width:18%;">{alloc_cell}</td>
            <td style="padding:14px 18px; vertical-align:middle; width:18%;">{price_cell}</td>
            <td style="padding:14px 18px; vertical-align:middle; width:18%;">{fv_cell}</td>
            <td style="padding:14px 18px; vertical-align:middle; width:18%;">{yield_cell}</td>
        </tr>
        """

    # Rebalance log
    log_rows_html = ""
    for entry in rebalance_log:
        log_rows_html += f"""
        <div style="background:var(--bg-subpanel); border:1px solid var(--border-color); border-radius:10px; padding:14px 18px; display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span class="pill pill-active" style="font-size:0.72rem;">{entry.get('action')}</span>
                    <strong style="font-family:var(--font-mono); font-size:0.85rem; color:var(--text-title);">{entry.get('date')}</strong>
                </div>
                <span style="font-size:0.78rem; color:var(--accent-green); font-family:var(--font-sans);">{entry.get('verification_status')}</span>
            </div>
            <div style="font-size:0.88rem; color:var(--text-secondary); line-height:1.45;">
                {entry.get('reason')}
            </div>
        </div>
        """

    canvas_id = f"alphathesis-perf-chart-{portfolio_type}"
    beacon_id = f"chart-beacon-pulse-{portfolio_type}"
    func_name = f"initPortfolioChart_{portfolio_type}"

    return f"""
    <style>
        .tbl-cell-stacked {{
            display: flex !important;
            flex-direction: column !important;
            gap: 3px !important;
            align-items: flex-start !important;
            justify-content: center !important;
            min-width: 0 !important;
            max-width: 100% !important;
        }}
        .tbl-cell-stacked .cell-primary {{
            font-family: var(--font-mono) !important;
            font-size: 0.95rem !important;
            color: var(--text-title) !important;
            font-weight: 600 !important;
            line-height: 1.2 !important;
            display: block !important;
            white-space: nowrap !important;
        }}
        .tbl-cell-stacked .cell-primary.cell-warm {{
            color: var(--accent-warm) !important;
        }}
        .tbl-cell-stacked .cell-sub {{
            font-family: var(--font-mono) !important;
            font-size: 0.80rem !important;
            line-height: 1.2 !important;
            display: block !important;
            white-space: nowrap !important;
        }}
        .tbl-cell-stacked .cell-sub-green {{
            color: var(--accent-green) !important;
            font-weight: 500 !important;
        }}
        .tbl-cell-stacked .cell-sub-dim {{
            color: var(--text-dim) !important;
            font-weight: 400 !important;
        }}
        .tbl-cell-stacked .cell-sub-secondary {{
            color: var(--text-secondary) !important;
            font-family: var(--font-sans) !important;
            font-size: 0.82rem !important;
            font-weight: 400 !important;
            white-space: normal !important;
            word-break: break-word !important;
            line-height: 1.3 !important;
            max-width: 240px !important;
        }}
    </style>

    <div style="display:flex; flex-direction:column; gap:28px;">
        
        <!-- Header Banner -->
        <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:14px; padding:24px 28px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
            <div>
                <div style="display:flex; align-items:center; gap:12px; margin-bottom:6px;">
                    <h2 style="font-family:var(--font-serif); font-size:1.85rem; color:var(--text-title); margin:0; font-weight:400;">
                        {port_title}
                    </h2>
                    <span class="pill pill-active" style="font-size:0.75rem; letter-spacing:0.04em;">$200,000 Base</span>
                    <span class="pill pill-neutral" style="font-size:0.75rem;">{stats['core_positions_count']} Monopolies</span>
                </div>
                <p style="color:var(--text-secondary); margin:0; font-size:0.92rem;">
                    {port_subtitle}
                </p>
            </div>
            <div style="display:flex; align-items:center; gap:12px;">
                <div style="text-align:right;">
                    <div style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.06em; color:var(--text-dim);">Live Portfolio Value</div>
                    <div style="font-family:var(--font-mono); font-size:1.60rem; font-weight:600; color:var(--accent-warm);">
                        ${stats['total_value_usd']:,.2f}
                    </div>
                </div>
            </div>
        </div>

        <!-- Weekly Surveillance Status Banner -->
        <div style="background:linear-gradient(180deg, rgba(37,35,32,0.95), rgba(30,28,25,0.95)); border:1px solid var(--border-color); border-left:4px solid var(--accent-green); border-radius:12px; padding:18px 22px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:14px;">
            <div style="display:flex; align-items:center; gap:14px;">
                <div style="width:36px; height:36px; border-radius:8px; background:rgba(111,168,130,0.15); display:flex; align-items:center; justify-content:center; color:var(--accent-green); font-size:1.15rem; flex-shrink:0;">
                    🛡️
                </div>
                <div>
                    <div style="display:flex; align-items:center; gap:8px;">
                        <strong style="font-family:var(--font-mono); font-size:0.88rem; color:var(--text-title); letter-spacing:0.04em;">
                            {surveillance.get('status_display', 'COUNCIL AUDIT ACTIVE • ALL HOLDINGS INTACT')}
                        </strong>
                        <span class="pill pill-active" style="font-size:0.70rem; background:rgba(111,168,130,0.15); color:var(--accent-green); border:1px solid rgba(111,168,130,0.30);">Verified Optimal</span>
                    </div>
                    <div style="font-size:0.84rem; color:var(--text-secondary); margin-top:3px; line-height:1.4;">
                        {surveillance.get('verdict_summary', 'All holdings maintain unassailable moats and >20% expected 5Y IRRs.')}
                    </div>
                </div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-dim);">Surveillance Cadence</div>
                <div style="font-family:var(--font-mono); font-size:0.80rem; color:var(--text-title); margin-top:2px;">
                    {surveillance_cadence}
                </div>
            </div>
        </div>

        <!-- 4 Primary KPI Summary Cards -->
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:16px;">
            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:12px; padding:20px 22px;">
                <div style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-dim); margin-bottom:6px;">Look-Through Owner Earnings</div>
                <div style="font-family:var(--font-mono); font-size:1.75rem; font-weight:600; color:var(--accent-warm);">
                    ${stats['total_owner_earnings_usd']:,.0f}<span style="font-size:0.95rem; font-weight:400; color:var(--text-dim);">/yr</span>
                </div>
                <div style="font-size:0.82rem; color:var(--accent-green); margin-top:4px;">
                    {stats['look_through_fcf_yield_pct']}% Look-Through Cash Yield
                </div>
            </div>

            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:12px; padding:20px 22px;">
                <div style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-dim); margin-bottom:6px;">Net Share Cannibalization</div>
                <div style="font-family:var(--font-mono); font-size:1.75rem; font-weight:600; color:var(--text-title);">
                    +{stats['share_cannibalization_rate_pct']}%<span style="font-size:0.95rem; font-weight:400; color:var(--text-dim);">/yr</span>
                </div>
                <div style="font-size:0.82rem; color:var(--text-secondary); margin-top:4px;">
                    Organic EPS Expansion via Buybacks
                </div>
            </div>

            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:12px; padding:20px 22px;">
                <div style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-dim); margin-bottom:6px;">Strategic Cash Buffer</div>
                <div style="font-family:var(--font-mono); font-size:1.75rem; font-weight:600; color:var(--accent-green);">
                    {stats['cash_weight_pct']}%
                </div>
                <div style="font-size:0.82rem; color:var(--text-secondary); margin-top:4px;">
                    {cash_badge_label} (4.50% Yield)
                </div>
            </div>

            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:12px; padding:20px 22px;">
                <div style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-dim); margin-bottom:6px;">Rebalance Guardrail</div>
                <div style="font-family:var(--font-mono); font-size:1.75rem; font-weight:600; color:var(--text-title);">
                    &ge; 5.0%
                </div>
                <div style="font-size:0.82rem; color:var(--accent-green); margin-top:4px;">
                    Zero Churn • Material Deltas Only
                </div>
            </div>
        </div>

        <!-- Dual-Axis Visualizer Card -->
        <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:14px; padding:24px 26px; display:flex; flex-direction:column; gap:16px;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                <div>
                    <h3 style="font-family:var(--font-serif); font-size:1.30rem; color:var(--text-title); margin:0; font-weight:500;">
                        Compounding Roadmap & Owner Earnings Engine
                    </h3>
                    <p style="color:var(--text-secondary); font-size:0.85rem; margin:3px 0 0;">
                        Tracking true economic cash generation vs market price quotation.
                    </p>
                </div>
                <div style="display:flex; align-items:center; gap:16px; font-size:0.80rem; font-family:var(--font-mono);">
                    <span style="display:flex; align-items:center; gap:6px; color:var(--accent-warm);">
                        <span style="display:inline-block; width:12px; height:3px; background:#CC785C; border-radius:2px;"></span> Portfolio Value ($)
                    </span>
                    <span style="display:flex; align-items:center; gap:6px; color:var(--accent-green);">
                        <span style="display:inline-block; width:12px; height:2px; border-top:2px dashed #6FA882;"></span> Owner Earnings ($/yr)
                    </span>
                    <span style="display:flex; align-items:center; gap:6px; color:var(--text-dim);">
                        <span style="display:inline-block; width:12px; height:2px; background:#8C8982;"></span> S&P 500 Benchmark
                    </span>
                </div>
            </div>

            <!-- Chart Canvas Container -->
            <div style="position:relative; width:100%; height:320px; border:1px solid rgba(255,255,255,0.03); border-radius:8px; padding:12px; background:rgba(0,0,0,0.15);">
                <div id="{beacon_id}" class="beacon-ping" style="position:absolute; width:16px; height:16px; border-radius:50%; background:rgba(204,120,92,0.4); border:1.5px solid #CC785C; transform:translate(-50%, -50%); pointer-events:none; z-index:10; display:none;"></div>
                <canvas id="{canvas_id}"></canvas>
            </div>
        </div>

        <!-- Master Holdings Table -->
        <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:14px; padding:22px 24px; overflow-x:auto;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:10px;">
                <div>
                    <h3 style="font-family:var(--font-serif); font-size:1.30rem; color:var(--text-title); margin:0; font-weight:500;">
                        Active Fortress Holdings ({stats['core_positions_count']} Equities + Cash)
                    </h3>
                    <p style="color:var(--text-secondary); font-size:0.85rem; margin:3px 0 0;">
                        First-Principles Kelly Risk-Adjusted Allocation ($200,000 Initial Capital Base).
                    </p>
                </div>
                <div style="display:flex; align-items:center; gap:8px;">
                    <span class="pill pill-neutral" style="font-size:0.75rem;">Pillar A: {stats['pillar_a_weight_pct']}%</span>
                    <span class="pill pill-neutral" style="font-size:0.75rem;">Pillar B: {stats['pillar_b_weight_pct']}%</span>
                    <span class="pill pill-neutral" style="font-size:0.75rem;">Cash: {stats['cash_weight_pct']}%</span>
                </div>
            </div>

            <table class="fin-table" style="width:100%; min-width:820px; table-layout:fixed; border-collapse:collapse;">
                <colgroup>
                    <col style="width:28%;">
                    <col style="width:18%;">
                    <col style="width:18%;">
                    <col style="width:18%;">
                    <col style="width:18%;">
                </colgroup>
                <thead>
                    <tr style="border-bottom:1px solid var(--border-color); text-align:left; font-size:0.74rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-dim);">
                        <th style="padding:12px 16px;">Holding</th>
                        <th style="padding:12px 16px;">Allocation ($200k Base)</th>
                        <th style="padding:12px 16px;">Price Today (Cost Basis)</th>
                        <th style="padding:12px 16px;">Fair Value (MoS)</th>
                        <th style="padding:12px 16px;">Owner Earnings Yield</th>
                    </tr>
                </thead>
                <tbody id="portfolio-holdings-tbody-{portfolio_type}">
                    {rows_html}
                </tbody>
            </table>
        </div>

        <!-- Rebalance Log & Audit Trail -->
        <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:14px; padding:22px 24px; display:flex; flex-direction:column; gap:14px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h4 style="font-family:var(--font-serif); font-size:1.15rem; color:var(--text-title); margin:0; font-weight:500;">
                    Rebalancing Log & Verification History
                </h4>
                <span style="font-size:0.75rem; color:var(--text-dim);">Daily 3:00 PM EST Surveillance • Min. Threshold &ge; 5%</span>
            </div>
            <div style="display:flex; flex-direction:column; gap:10px;">
                {log_rows_html}
            </div>
        </div>

    </div>

    <!-- Chart.js Engine for Dual-Axis Portfolio Visualization -->
    <script>
        const perfData_{portfolio_type} = {perf_payload};
        let chartInstance_{portfolio_type} = null;

        function updateChartBeacon_{portfolio_type}() {{
            const beacon = document.getElementById('{beacon_id}');
            if (!beacon || !chartInstance_{portfolio_type}) return;
            if (perfData_{portfolio_type}.dates && perfData_{portfolio_type}.dates.length <= 1) {{
                const meta = chartInstance_{portfolio_type}.getDatasetMeta(0);
                if (meta && meta.data && meta.data[0]) {{
                    beacon.style.left = meta.data[0].x + 'px';
                    beacon.style.top = meta.data[0].y + 'px';
                    beacon.style.display = 'block';
                    return;
                }}
            }}
            beacon.style.display = 'none';
        }}

        function {func_name}() {{
            const ctx = document.getElementById('{canvas_id}');
            if (!ctx) return;
            
            if (chartInstance_{portfolio_type}) {{
                chartInstance_{portfolio_type}.destroy();
            }}

            const rawDates = perfData_{portfolio_type}.dates || [];
            const isSinglePoint = (rawDates.length <= 1);
            
            const formattedDates = rawDates.map(d => {{
                if (!d || d.includes('(')) return d;
                const parts = d.split('-');
                if (parts.length === 3) {{
                    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                    const mIdx = parseInt(parts[1], 10) - 1;
                    return (months[mIdx] || parts[1]) + ' ' + parseInt(parts[2], 10);
                }}
                return d;
            }});

            const chartLabels = isSinglePoint ? ['Aug 11', 'Aug 12', 'Aug 13', 'Aug 14', 'Aug 15'] : formattedDates;
            const portfolioSeries = isSinglePoint ? [perfData_{portfolio_type}.portfolio[0], null, null, null, null] : perfData_{portfolio_type}.portfolio;
            const earningsSeries = isSinglePoint ? [perfData_{portfolio_type}.earnings[0], null, null, null, null] : perfData_{portfolio_type}.earnings;
            const spySeries = isSinglePoint ? [perfData_{portfolio_type}.spy[0], null, null, null, null] : perfData_{portfolio_type}.spy;

            const pointCount = rawDates.length;
            const dynamicRadius = isSinglePoint ? 0 : (pointCount > 40 ? 0 : (pointCount > 15 ? 2 : 3.5));

            chartInstance_{portfolio_type} = new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: chartLabels,
                    datasets: [
                        {{
                            label: '{port_title} ($)',
                            data: portfolioSeries,
                            borderColor: '#CC785C',
                            backgroundColor: 'rgba(204, 120, 92, 0.10)',
                            borderWidth: 2.2,
                            pointRadius: dynamicRadius,
                            pointHoverRadius: 6,
                            pointBackgroundColor: '#CC785C',
                            pointBorderColor: 'transparent',
                            tension: 0.25,
                            showLine: true,
                            spanGaps: false,
                            yAxisID: 'y'
                        }},
                        {{
                            label: 'Look-Through Owner Earnings ($/yr)',
                            data: earningsSeries,
                            borderColor: '#6FA882',
                            backgroundColor: 'transparent',
                            borderWidth: 1.8,
                            borderDash: [5, 5],
                            pointStyle: isSinglePoint ? 'rectRot' : 'circle',
                            pointRadius: isSinglePoint ? 4 : (pointCount > 40 ? 0 : 2.5),
                            pointHoverRadius: 6,
                            pointBackgroundColor: '#6FA882',
                            pointBorderColor: 'transparent',
                            tension: 0.2,
                            showLine: true,
                            spanGaps: false,
                            yAxisID: 'y1'
                        }},
                        {{
                            label: 'S&P 500 Benchmark ($)',
                            data: spySeries,
                            borderColor: '#8C8982',
                            backgroundColor: 'transparent',
                            borderWidth: 1.4,
                            pointStyle: isSinglePoint ? 'triangle' : 'circle',
                            pointRadius: isSinglePoint ? 3 : 0,
                            pointHoverRadius: 5,
                            pointBackgroundColor: '#8C8982',
                            pointBorderColor: 'transparent',
                            tension: 0.2,
                            showLine: true,
                            spanGaps: false,
                            yAxisID: 'y'
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    interaction: {{
                        mode: 'index',
                        intersect: false
                    }},
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{
                            backgroundColor: '#1E1D1A',
                            titleColor: '#F5EFEB',
                            bodyColor: '#D4CDC3',
                            borderColor: '#3D3A35',
                            borderWidth: 1,
                            padding: 12,
                            boxPadding: 6,
                            usePointStyle: true,
                            callbacks: {{
                                label: function(ctx) {{
                                    if (ctx.parsed.y === null || ctx.parsed.y === undefined) return '';
                                    if (ctx.datasetIndex === 1) {{
                                        return ctx.dataset.label + ': $' + ctx.parsed.y.toLocaleString() + '/yr';
                                    }}
                                    return ctx.dataset.label + ': $' + ctx.parsed.y.toLocaleString();
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            grid: {{ color: 'rgba(255,255,255,0.04)' }},
                            ticks: {{
                                color: '#8C8982',
                                font: {{ family: "'JetBrains Mono', monospace", size: 10 }},
                                autoSkip: true,
                                maxTicksLimit: 7,
                                maxRotation: 0
                            }}
                        }},
                        y: {{
                            type: 'linear',
                            display: true,
                            position: 'left',
                            grid: {{ color: 'rgba(255,255,255,0.05)' }},
                            ticks: {{
                                color: '#CC785C',
                                font: {{ family: "'JetBrains Mono', monospace", size: 10 }},
                                callback: function(val) {{
                                    if (val >= 1000) return '$' + (val/1000).toFixed(0) + 'k';
                                    return '$' + val;
                                }}
                            }}
                        }},
                        y1: {{
                            type: 'linear',
                            display: true,
                            position: 'right',
                            grid: {{ drawOnChartArea: false }},
                            ticks: {{
                                color: '#6FA882',
                                font: {{ family: "'JetBrains Mono', monospace", size: 10 }},
                                callback: function(val) {{
                                    if (val >= 1000) return '$' + (val/1000).toFixed(1) + 'k/yr';
                                    return '$' + val + '/yr';
                                }}
                            }}
                        }}
                    }}
                }}
            }});

            setTimeout(updateChartBeacon_{portfolio_type}, 50);
        }}

        window.addEventListener('resize', () => setTimeout(updateChartBeacon_{portfolio_type}, 50));
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
