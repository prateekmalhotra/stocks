"""AlphaSense-Inspired Institutional Financial Dashboard & Living Dossier HTML Generator."""

import json
from pathlib import Path
from typing import List, Dict
from datetime import datetime
from stocks.models import WatchlistStock, AlertItem, ThesisVersion
from stocks.data_store import load_watchlist, load_alerts, load_thesis_history

PUBLIC_DIR = Path("public")
REPORTS_DIR = PUBLIC_DIR / "reports"


def _ensure_dirs():
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def generate_company_dossier_html(ticker: str, stock: WatchlistStock, history: List[ThesisVersion]) -> str:
    """Generates an AlphaSense-grade institutional equity research living dossier."""
    current_version = history[-1] if history else None
    
    # Calculate corridor percentages for visual range bar
    bear_p = stock.lower_alert_threshold or (stock.current_price * 0.8)
    bull_p = stock.upper_alert_threshold or (stock.current_price * 1.3)
    span = max(bull_p - bear_p, 1.0)
    current_pos_pct = max(0, min(100, ((stock.current_price - bear_p) / span) * 100))

    # Format history timeline cards
    history_cards_html = ""
    for v in reversed(history):
        is_current = (v.version == len(history))
        current_badge = '<span class="pill pill-emerald">Active Version</span>' if is_current else f'<span class="pill pill-neutral">v{v.version}</span>'
        
        diff_box = ""
        if v.what_was_before or v.what_changes_now:
            diff_box = f"""
            <div class="diff-grid">
                <div class="diff-box diff-prev">
                    <div class="diff-label">PREVIOUS THESIS STANCE</div>
                    <div class="diff-text">{v.what_was_before or 'Genesis baseline initiated.'}</div>
                </div>
                <div class="diff-box diff-now">
                    <div class="diff-label">CATALYST & THESIS EVOLUTION</div>
                    <div class="diff-text">{v.what_changes_now or v.summary_of_change}</div>
                </div>
            </div>
            """
            
        history_cards_html += f"""
        <div class="history-entry {'history-entry-active' if is_current else ''}">
            <div class="history-top">
                <div class="history-tags">
                    {current_badge}
                    <span class="history-time">📅 {v.date}</span>
                    <span class="history-price">Price: <strong>${v.price_at_version:.2f}</strong></span>
                    <span class="pill pill-primary">{v.status_label}</span>
                </div>
                <button class="btn btn-outline-sm" onclick="toggleSnapshot({v.version})">View Snapshot ▾</button>
            </div>
            <div class="history-content">
                <p class="history-shift-desc"><strong>Thesis Shift:</strong> {v.summary_of_change}</p>
                {diff_box}
                <div id="snapshot-{v.version}" class="snapshot-drawer" style="display: none;">
                    <div class="snapshot-body">
                        {v.full_html_content}
                    </div>
                </div>
            </div>
        </div>
        """

    active_content = current_version.full_html_content if current_version else "<p>No active thesis found.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{ticker} — Institutional Research Dossier | AlphaThesis</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-canvas: #090b10;
            --bg-panel: #0e131d;
            --bg-subpanel: #141b29;
            --bg-elevated: #1b2438;
            --bg-highlight: #23304a;
            --text-title: #ffffff;
            --text-body: #e2e8f0;
            --text-secondary: #94a3b8;
            --text-dim: #64748b;
            --accent-cyan: #38bdf8;
            --accent-cyan-rgb: 56, 189, 248;
            --accent-emerald: #10b981;
            --accent-emerald-rgb: 16, 185, 129;
            --accent-rose: #f43f5e;
            --accent-amber: #f59e0b;
            --border-color: #1e283d;
            --border-focus: #2e3e5c;
            --font-sans: 'Plus Jakarta Sans', -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
            --font-editorial: 'Newsreader', Georgia, serif;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg-canvas);
            color: var(--text-body);
            font-family: var(--font-sans);
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
            padding-bottom: 120px;
        }}

        .container {{ max-width: 1140px; margin: 0 auto; padding: 0 24px; }}

        /* Top AlphaSense-Style Bar */
        nav.nav-bar {{
            background: rgba(9, 11, 16, 0.85);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 100;
            padding: 14px 0;
        }}
        .nav-inner {{ display: flex; justify-content: space-between; align-items: center; }}
        .nav-back {{
            color: var(--accent-cyan);
            text-decoration: none;
            font-size: 0.88rem;
            font-weight: 700;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: transform 0.15s;
        }}
        .nav-back:hover {{ transform: translateX(-3px); }}
        .nav-meta {{ font-size: 0.75rem; color: var(--text-dim); font-family: var(--font-mono); text-transform: uppercase; letter-spacing: 0.05em; }}

        /* Hero Deck */
        .hero-deck {{
            background: linear-gradient(180deg, #101624 0%, #0c101a 100%);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 36px 40px;
            margin: 32px 0 28px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.5);
            position: relative;
            overflow: hidden;
        }}
        .hero-deck::before {{
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 1px;
            background: linear-gradient(90deg, transparent, rgba(var(--accent-cyan-rgb), 0.5), transparent);
        }}

        .hero-top-row {{ display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 20px; }}
        .ticker-headline {{ display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }}
        .ticker-symbol {{ font-size: 2.8rem; font-weight: 800; letter-spacing: -0.04em; color: #fff; }}
        .company-meta {{ color: var(--text-secondary); font-size: 1.05rem; margin-top: 4px; }}

        .price-callout {{ text-align: right; }}
        .price-number {{ font-size: 2.8rem; font-weight: 800; font-family: var(--font-mono); letter-spacing: -0.03em; color: #fff; }}
        .price-sub {{ font-size: 0.92rem; font-weight: 600; font-family: var(--font-mono); margin-top: 2px; }}

        /* Dynamic Visual Corridor Bar */
        .corridor-container {{
            margin-top: 28px;
            padding-top: 22px;
            border-top: 1px solid var(--border-color);
        }}
        .corridor-header {{ display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--text-dim); text-transform: uppercase; font-weight: 700; letter-spacing: 0.05em; margin-bottom: 8px; }}
        .corridor-track {{
            height: 8px;
            background: var(--bg-elevated);
            border-radius: 9999px;
            position: relative;
            overflow: visible;
        }}
        .corridor-fill {{
            height: 100%;
            background: linear-gradient(90deg, var(--accent-rose), var(--accent-amber), var(--accent-emerald), var(--accent-cyan));
            border-radius: 9999px;
            width: 100%;
            opacity: 0.4;
        }}
        .corridor-marker {{
            position: absolute;
            top: -5px;
            width: 18px;
            height: 18px;
            background: #fff;
            border: 3px solid var(--accent-cyan);
            border-radius: 50%;
            transform: translateX(-50%);
            box-shadow: 0 0 12px var(--accent-cyan);
        }}

        /* Key Metrics Grid */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 12px;
            margin-top: 24px;
        }}
        .metric-cell {{
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 14px 16px;
        }}
        .metric-label {{ font-size: 0.68rem; text-transform: uppercase; color: var(--text-dim); font-weight: 700; letter-spacing: 0.05em; }}
        .metric-value {{ font-size: 1.15rem; font-weight: 700; color: #fff; font-family: var(--font-mono); margin-top: 4px; }}

        /* Tabs */
        .tabs-header {{
            display: flex;
            gap: 12px;
            border-bottom: 1px solid var(--border-color);
            margin: 32px 0 28px;
        }}
        .tab-btn {{
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 1.05rem;
            font-weight: 700;
            padding: 14px 24px;
            cursor: pointer;
            position: relative;
            font-family: var(--font-sans);
            transition: all 0.15s;
        }}
        .tab-btn:hover {{ color: #fff; }}
        .tab-btn.active {{ color: var(--accent-cyan); }}
        .tab-btn.active::after {{
            content: '';
            position: absolute;
            bottom: -1px;
            left: 0; right: 0;
            height: 2px;
            background: var(--accent-cyan);
            box-shadow: 0 0 14px var(--accent-cyan);
        }}

        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}

        /* Living Thesis Editorial Styling */
        .memo-container {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 44px 48px;
            box-shadow: 0 16px 36px rgba(0,0,0,0.3);
        }}
        .memo-container h2 {{
            font-size: 1.45rem;
            font-weight: 800;
            color: var(--accent-cyan);
            margin: 40px 0 16px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            gap: 10px;
            letter-spacing: -0.02em;
        }}
        .memo-container h2:first-of-type {{ margin-top: 0; }}
        .memo-container h3 {{ font-size: 1.2rem; font-weight: 700; color: #f1f5f9; margin: 26px 0 12px; }}
        .memo-container p {{
            font-family: var(--font-editorial);
            font-size: 1.18rem;
            line-height: 1.88;
            color: #cbd5e1;
            margin-bottom: 22px;
        }}
        .memo-container ul, .memo-container ol {{
            font-family: var(--font-editorial);
            font-size: 1.15rem;
            line-height: 1.88;
            color: #cbd5e1;
            margin: 0 0 24px 28px;
        }}
        .memo-container li {{ margin-bottom: 8px; }}

        .memo-container table {{
            width: 100%;
            border-collapse: collapse;
            margin: 28px 0;
            background: var(--bg-subpanel);
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }}
        .memo-container th, .memo-container td {{
            padding: 14px 20px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.92rem;
        }}
        .memo-container th {{ background: var(--bg-elevated); color: #fff; font-weight: 700; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; }}
        .memo-container blockquote {{
            background: var(--bg-subpanel);
            border-left: 3px solid var(--accent-cyan);
            padding: 20px 28px;
            border-radius: 0 12px 12px 0;
            margin: 28px 0;
            font-family: var(--font-editorial);
            font-style: italic;
            color: #f1f5f9;
        }}

        /* History Tab */
        .history-entry {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 28px 32px;
            margin-bottom: 20px;
            transition: all 0.2s;
        }}
        .history-entry-active {{ border-color: rgba(var(--accent-emerald-rgb), 0.4); box-shadow: 0 0 20px rgba(var(--accent-emerald-rgb), 0.08); }}
        .history-top {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }}
        .history-tags {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
        .history-time {{ color: var(--text-secondary); font-size: 0.9rem; }}
        .history-price {{ font-family: var(--font-mono); font-size: 0.95rem; }}

        .diff-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin: 20px 0;
        }}
        @media (max-width: 768px) {{ .diff-grid {{ grid-template-columns: 1fr; }} }}
        .diff-box {{
            padding: 20px;
            border-radius: 12px;
            border: 1px solid var(--border-color);
        }}
        .diff-prev {{ background: rgba(244, 63, 94, 0.03); border-color: rgba(244, 63, 94, 0.2); }}
        .diff-now {{ background: rgba(var(--accent-emerald-rgb), 0.03); border-color: rgba(var(--accent-emerald-rgb), 0.2); }}
        .diff-label {{ font-size: 0.7rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }}
        .diff-prev .diff-label {{ color: #fb7185; }}
        .diff-now .diff-label {{ color: #34d399; }}
        .diff-text {{ font-size: 0.95rem; color: #cbd5e1; line-height: 1.6; }}

        /* Badges & Buttons */
        .pill {{
            display: inline-flex;
            align-items: center;
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .pill-primary {{ background: rgba(var(--accent-cyan-rgb), 0.12); color: var(--accent-cyan); border: 1px solid rgba(var(--accent-cyan-rgb), 0.3); }}
        .pill-emerald {{ background: rgba(var(--accent-emerald-rgb), 0.12); color: var(--accent-emerald); border: 1px solid rgba(var(--accent-emerald-rgb), 0.3); }}
        .pill-neutral {{ background: var(--bg-elevated); color: var(--text-secondary); border: 1px solid var(--border-color); }}

        .btn {{
            padding: 10px 20px;
            border-radius: 10px;
            font-weight: 700;
            font-size: 0.88rem;
            cursor: pointer;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            border: none;
            transition: all 0.15s;
        }}
        .btn-outline-sm {{ background: var(--bg-elevated); color: var(--text-body); border: 1px solid var(--border-color); font-size: 0.8rem; padding: 6px 14px; border-radius: 8px; }}
        .btn-outline-sm:hover {{ background: var(--bg-highlight); }}

        .snapshot-drawer {{ margin-top: 24px; padding-top: 24px; border-top: 1px solid var(--border-color); }}

        .pos {{ color: var(--accent-emerald); }}
        .neg {{ color: var(--accent-rose); }}
    </style>
</head>
<body>
    <nav class="nav-bar">
        <div class="container nav-inner">
            <a href="../index.html" class="nav-back">← Master Surveillance Hub</a>
            <span class="nav-meta">RESEARCH DOSSIER // {ticker}</span>
        </div>
    </nav>

    <main class="container">
        <!-- Hero Deck -->
        <section class="hero-deck">
            <div class="hero-top-row">
                <div>
                    <div class="ticker-headline">
                        <span class="ticker-symbol">{stock.ticker}</span>
                        <span class="pill pill-primary">{stock.status_label}</span>
                    </div>
                    <div class="company-meta">{stock.company_name} • Last Evaluated: {stock.last_updated}</div>
                </div>
                <div class="price-callout">
                    <div class="price-number">${stock.current_price:.2f}</div>
                    <div class="price-sub {'pos' if stock.return_pct >= 0 else 'neg'}">
                        {stock.return_pct:+.2f}% vs Genesis (${stock.baseline_price:.2f})
                    </div>
                </div>
            </div>

            <!-- Visual Range Corridor -->
            <div class="corridor-container">
                <div class="corridor-header">
                    <span>Bear Floor (${bear_p:.2f})</span>
                    <span>Current Price: ${stock.current_price:.2f}</span>
                    <span>Bull Target (${bull_p:.2f})</span>
                </div>
                <div class="corridor-track">
                    <div class="corridor-fill"></div>
                    <div class="corridor-marker" style="left: {current_pos_pct:.1f}%;"></div>
                </div>
            </div>

            <!-- KPI Metric Ribbon -->
            <div class="metrics-grid">
                <div class="metric-cell">
                    <div class="metric-label">Fair Value Target</div>
                    <div class="metric-value" style="color: var(--accent-cyan);">{stock.fair_value_estimate}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Bear Case</div>
                    <div class="metric-value" style="color: var(--accent-rose);">{stock.bear_target}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Base Case</div>
                    <div class="metric-value">{stock.base_target}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Bull Case</div>
                    <div class="metric-value" style="color: var(--accent-emerald);">{stock.bull_target}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Upper Alert Trigger</div>
                    <div class="metric-value">${stock.upper_alert_threshold:.2f}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Lower Alert Trigger</div>
                    <div class="metric-value">${stock.lower_alert_threshold:.2f}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Next Catalyst</div>
                    <div class="metric-value" style="font-size: 0.9rem;">{stock.next_catalyst_date or 'TBD'}</div>
                </div>
            </div>
        </section>

        <!-- Navigation Tabs -->
        <div class="tabs-header">
            <button class="tab-btn active" onclick="showTab('memo')">📖 Active Living Thesis</button>
            <button class="tab-btn" onclick="showTab('history')">⏳ Evolution & Historical Snapshots ({len(history)})</button>
        </div>

        <!-- Living Memo Content -->
        <div id="tab-memo" class="tab-content active">
            <article class="memo-container">
                {active_content}
            </article>
        </div>

        <!-- History Content -->
        <div id="tab-history" class="tab-content">
            {history_cards_html}
        </div>
    </main>

    <script>
        function showTab(id) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            if (id === 'memo') {{
                document.querySelectorAll('.tab-btn')[0].classList.add('active');
                document.getElementById('tab-memo').classList.add('active');
            }} else {{
                document.querySelectorAll('.tab-btn')[1].classList.add('active');
                document.getElementById('tab-history').classList.add('active');
            }}
        }}

        function toggleSnapshot(ver) {{
            const el = document.getElementById('snapshot-' + ver);
            el.style.display = (el.style.display === 'none' ? 'block' : 'none');
        }}
    </script>
</body>
</html>
"""


def generate_master_dashboard_html(watchlist: Dict[str, WatchlistStock], alerts: List[AlertItem]) -> str:
    """Generates the master AlphaSense-grade financial terminal dashboard."""
    _ensure_dirs()
    
    # Table rows
    table_rows_html = ""
    grid_cards_html = ""

    for ticker, stock in sorted(watchlist.items(), key=lambda x: x[0]):
        ret_class = "pos" if stock.return_pct >= 0 else "neg"
        
        # Corridor slider calculation
        bear_p = stock.lower_alert_threshold or (stock.current_price * 0.8)
        bull_p = stock.upper_alert_threshold or (stock.current_price * 1.3)
        span = max(bull_p - bear_p, 1.0)
        pos_pct = max(0, min(100, ((stock.current_price - bear_p) / span) * 100))

        # 1. Table row
        table_rows_html += f"""
        <tr class="table-row" onclick="location.href='reports/{stock.ticker}.html'">
            <td>
                <div class="tbl-ticker-cell">
                    <span class="tbl-symbol">{stock.ticker}</span>
                    <span class="tbl-company">{stock.company_name}</span>
                </div>
            </td>
            <td>
                <div class="tbl-price-cell">
                    <span class="tbl-price">${stock.current_price:.2f}</span>
                    <span class="tbl-return {ret_class}">{stock.return_pct:+.2f}%</span>
                </div>
            </td>
            <td>
                <span class="pill pill-primary">{stock.status_label}</span>
            </td>
            <td>
                <div class="tbl-val-cell">
                    <span class="tbl-fv" style="color: var(--accent-cyan);">{stock.fair_value_estimate}</span>
                    <span class="tbl-base">{stock.base_target}</span>
                </div>
            </td>
            <td>
                <div class="tbl-corridor-cell">
                    <div class="tbl-corridor-labels">
                        <span>${stock.lower_alert_threshold:.0f}</span>
                        <span>${stock.upper_alert_threshold:.0f}</span>
                    </div>
                    <div class="mini-corridor-track">
                        <div class="mini-corridor-fill"></div>
                        <div class="mini-corridor-dot" style="left: {pos_pct:.0f}%;"></div>
                    </div>
                </div>
            </td>
            <td>
                <div class="tbl-catalyst-cell">
                    <span class="tbl-cat-date">{stock.next_catalyst_date or 'TBD'}</span>
                    <span class="tbl-cat-desc">{stock.next_catalyst_event[:40] if stock.next_catalyst_event else ''}</span>
                </div>
            </td>
            <td style="text-align: right;">
                <a href="reports/{stock.ticker}.html" class="btn btn-action" onclick="event.stopPropagation()">Dossier →</a>
            </td>
        </tr>
        """

        # 2. Grid card
        grid_cards_html += f"""
        <div class="grid-card" onclick="location.href='reports/{stock.ticker}.html'">
            <div class="grid-card-top">
                <div>
                    <span class="grid-symbol">{stock.ticker}</span>
                    <span class="pill pill-primary" style="margin-left: 8px;">{stock.status_label}</span>
                </div>
                <div class="grid-price">${stock.current_price:.2f}</div>
            </div>
            <div class="grid-company">{stock.company_name}</div>
            
            <div class="grid-metrics-box">
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Return</span>
                    <span class="grid-stat-val {ret_class}">{stock.return_pct:+.2f}%</span>
                </div>
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Fair Value</span>
                    <span class="grid-stat-val" style="color: var(--accent-cyan);">{stock.fair_value_estimate}</span>
                </div>
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Trigger Bounds</span>
                    <span class="grid-stat-val">${stock.lower_alert_threshold:.0f} — ${stock.upper_alert_threshold:.0f}</span>
                </div>
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Next Catalyst</span>
                    <span class="grid-stat-val">{stock.next_catalyst_date or 'TBD'}</span>
                </div>
            </div>
            
            <div class="grid-card-foot">
                <span class="grid-updated">Updated {stock.last_updated}</span>
                <span class="grid-open">Deep Dive →</span>
            </div>
        </div>
        """

    # Alerts feed
    alerts_feed_html = ""
    if not alerts:
        alerts_feed_html = """
        <div class="empty-alerts">
            <div class="empty-icon">🛡️</div>
            <div class="empty-title">All Tracked Positions Within Safe Bounds</div>
            <div class="empty-sub">No critical threshold breaches or catalyst alerts fired. The 24/7 surveillance engine is monitoring active quotes.</div>
        </div>
        """
    else:
        for a in alerts:
            ret_class = "pos" if a.price_change_pct >= 0 else "neg"
            safe_payload = json.dumps({
                "ticker": a.ticker,
                "title": a.title,
                "timestamp": a.timestamp,
                "severity": a.severity,
                "price": a.price_at_alert,
                "change": a.price_change_pct,
                "trigger_reason": a.trigger_reason,
                "what_was_before": a.what_was_before,
                "what_changes_now": a.what_changes_now,
                "report_url": a.report_url
            }).replace("'", "&#39;").replace('"', "&quot;")

            alerts_feed_html += f"""
            <div class="alert-item" onclick='openAlertModal({safe_payload})'>
                <div class="alert-left">
                    <div class="alert-badges">
                        <span class="pill pill-alert">{a.severity}</span>
                        <strong class="alert-ticker">{a.ticker}</strong>
                        <span class="alert-time">🕒 {a.timestamp}</span>
                    </div>
                    <div class="alert-title">{a.title}</div>
                    <div class="alert-blurb">{a.what_changes_now[:220]}...</div>
                </div>
                <div class="alert-right">
                    <div class="alert-price-val">${a.price_at_alert:.2f}</div>
                    <div class="alert-price-pct {ret_class}">{a.price_change_pct:+.2f}%</div>
                    <span class="alert-view-btn">Inspect Thesis Delta →</span>
                </div>
            </div>
            """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AlphaThesis — Institutional Equity Surveillance Hub</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-canvas: #080a0f;
            --bg-panel: #0d121c;
            --bg-panel-hover: #121824;
            --bg-subpanel: #161e2e;
            --bg-elevated: #1d273b;
            --text-title: #ffffff;
            --text-body: #e2e8f0;
            --text-secondary: #94a3b8;
            --text-dim: #64748b;
            --accent-cyan: #38bdf8;
            --accent-cyan-rgb: 56, 189, 248;
            --accent-emerald: #10b981;
            --accent-emerald-rgb: 16, 185, 129;
            --accent-rose: #f43f5e;
            --accent-amber: #f59e0b;
            --border-color: #1e283d;
            --border-focus: #2c3c5c;
            --font-sans: 'Plus Jakarta Sans', -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg-canvas);
            color: var(--text-body);
            font-family: var(--font-sans);
            min-height: 100vh;
            -webkit-font-smoothing: antialiased;
            padding-bottom: 120px;
        }}

        .container {{ max-width: 1200px; margin: 0 auto; padding: 0 24px; }}

        /* Top Bar */
        header.nav-header {{
            background: rgba(8, 10, 15, 0.88);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 100;
            padding: 16px 0;
        }}
        .header-content {{ display: flex; justify-content: space-between; align-items: center; }}
        .brand-logo {{ display: flex; align-items: center; gap: 12px; font-size: 1.25rem; font-weight: 800; letter-spacing: -0.03em; color: #fff; }}
        .brand-symbol {{ color: var(--accent-cyan); font-size: 1.4rem; }}
        .engine-pill {{
            background: rgba(var(--accent-cyan-rgb), 0.12);
            color: var(--accent-cyan);
            font-size: 0.72rem;
            font-weight: 700;
            padding: 3px 10px;
            border-radius: 9999px;
            border: 1px solid rgba(var(--accent-cyan-rgb), 0.3);
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}

        .pulse-dot {{
            width: 8px; height: 8px; border-radius: 50%; background: var(--accent-emerald);
            box-shadow: 0 0 10px var(--accent-emerald); display: inline-block; margin-right: 6px;
        }}

        /* Macro Summary Stats Ribbon */
        .macro-ribbon {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin: 32px 0 28px;
        }}
        .macro-card {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 20px 24px;
            display: flex;
            align-items: center;
            gap: 18px;
        }}
        .macro-icon {{ font-size: 1.8rem; }}
        .macro-data {{ display: flex; flex-direction: column; }}
        .macro-lbl {{ font-size: 0.72rem; text-transform: uppercase; color: var(--text-dim); font-weight: 700; letter-spacing: 0.05em; }}
        .macro-val {{ font-size: 1.4rem; font-weight: 800; color: #fff; font-family: var(--font-mono); margin-top: 2px; }}

        /* Navigation & View Toggle */
        .hub-controls {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border-color);
        }}
        .hub-tabs {{ display: flex; gap: 8px; }}
        .hub-tab-btn {{
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 1.05rem;
            font-weight: 700;
            padding: 10px 20px;
            cursor: pointer;
            position: relative;
            font-family: var(--font-sans);
            transition: all 0.15s;
        }}
        .hub-tab-btn:hover {{ color: #fff; }}
        .hub-tab-btn.active {{ color: var(--accent-cyan); }}
        .hub-tab-btn.active::after {{
            content: '';
            position: absolute;
            bottom: -17px;
            left: 0; right: 0;
            height: 2px;
            background: var(--accent-cyan);
            box-shadow: 0 0 12px var(--accent-cyan);
        }}

        .view-toggle {{
            display: flex;
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 3px;
        }}
        .view-btn {{
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 0.8rem;
            font-weight: 700;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .view-btn.active {{ background: var(--bg-elevated); color: #fff; }}

        .tab-panel {{ display: none; }}
        .tab-panel.active {{ display: block; }}

        /* Institutional Table View */
        .table-wrap {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 12px 30px rgba(0,0,0,0.3);
        }}
        table.fin-table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        table.fin-table th {{
            background: var(--bg-subpanel);
            color: var(--text-dim);
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 14px 20px;
            border-bottom: 1px solid var(--border-color);
        }}
        table.fin-table td {{
            padding: 18px 20px;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.95rem;
            vertical-align: middle;
        }}
        .table-row {{ cursor: pointer; transition: background 0.15s; }}
        .table-row:hover {{ background: var(--bg-panel-hover); }}
        .table-row:last-child td {{ border-bottom: none; }}

        .tbl-ticker-cell {{ display: flex; flex-direction: column; }}
        .tbl-symbol {{ font-size: 1.25rem; font-weight: 800; color: #fff; letter-spacing: -0.02em; }}
        .tbl-company {{ font-size: 0.82rem; color: var(--text-dim); }}

        .tbl-price-cell {{ display: flex; flex-direction: column; }}
        .tbl-price {{ font-size: 1.15rem; font-weight: 700; font-family: var(--font-mono); color: #fff; }}
        .tbl-return {{ font-size: 0.8rem; font-weight: 600; font-family: var(--font-mono); }}

        .tbl-val-cell {{ display: flex; flex-direction: column; }}
        .tbl-fv {{ font-size: 1.05rem; font-weight: 700; font-family: var(--font-mono); }}
        .tbl-base {{ font-size: 0.8rem; color: var(--text-secondary); }}

        .tbl-corridor-cell {{ min-width: 150px; }}
        .tbl-corridor-labels {{ display: flex; justify-content: space-between; font-size: 0.68rem; color: var(--text-dim); font-family: var(--font-mono); margin-bottom: 4px; }}
        .mini-corridor-track {{
            height: 6px; background: var(--bg-elevated); border-radius: 9999px; position: relative;
        }}
        .mini-corridor-fill {{
            height: 100%; width: 100%; border-radius: 9999px;
            background: linear-gradient(90deg, var(--accent-rose), var(--accent-amber), var(--accent-emerald), var(--accent-cyan));
            opacity: 0.5;
        }}
        .mini-corridor-dot {{
            position: absolute; top: -3px; width: 12px; height: 12px;
            background: #fff; border: 2px solid var(--accent-cyan); border-radius: 50%;
            transform: translateX(-50%); box-shadow: 0 0 8px var(--accent-cyan);
        }}

        .tbl-catalyst-cell {{ display: flex; flex-direction: column; max-width: 180px; }}
        .tbl-cat-date {{ font-size: 0.85rem; font-weight: 600; color: #fff; }}
        .tbl-cat-desc {{ font-size: 0.75rem; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

        .btn-action {{
            background: var(--bg-subpanel);
            color: var(--accent-cyan);
            border: 1px solid var(--border-color);
            font-size: 0.8rem;
            font-weight: 700;
            padding: 8px 16px;
            border-radius: 8px;
            text-decoration: none;
            transition: all 0.15s;
        }}
        .btn-action:hover {{ background: var(--bg-elevated); border-color: var(--accent-cyan); }}

        /* Grid View */
        .grid-cards-wrap {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
            gap: 20px;
        }}
        .grid-card {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 18px;
            padding: 26px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .grid-card:hover {{
            background: var(--bg-panel-hover);
            border-color: var(--border-focus);
            transform: translateY(-3px);
            box-shadow: 0 16px 36px rgba(0,0,0,0.4);
        }}
        .grid-card-top {{ display: flex; justify-content: space-between; align-items: center; }}
        .grid-symbol {{ font-size: 1.7rem; font-weight: 800; color: #fff; letter-spacing: -0.02em; }}
        .grid-price {{ font-size: 1.6rem; font-weight: 700; font-family: var(--font-mono); color: #fff; }}
        .grid-company {{ color: var(--text-secondary); font-size: 0.92rem; margin: 4px 0 20px; }}

        .grid-metrics-box {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            background: var(--bg-subpanel);
            padding: 16px;
            border-radius: 12px;
            margin-bottom: 20px;
        }}
        .grid-stat {{ display: flex; flex-direction: column; }}
        .grid-stat-lbl {{ font-size: 0.68rem; text-transform: uppercase; color: var(--text-dim); font-weight: 700; }}
        .grid-stat-val {{ font-size: 1rem; font-weight: 700; font-family: var(--font-mono); margin-top: 2px; }}

        .grid-card-foot {{
            display: flex; justify-content: space-between; align-items: center;
            border-top: 1px solid var(--border-color); padding-top: 16px;
        }}
        .grid-updated {{ font-size: 0.75rem; color: var(--text-dim); font-family: var(--font-mono); }}
        .grid-open {{ font-size: 0.85rem; font-weight: 700; color: var(--accent-cyan); }}

        /* Alerts List */
        .alerts-feed {{ display: flex; flex-direction: column; gap: 16px; }}
        .alert-item {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px 28px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 24px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .alert-item:hover {{
            background: var(--bg-panel-hover);
            border-color: var(--accent-cyan);
            transform: translateX(4px);
        }}
        .alert-left {{ flex: 1; }}
        .alert-badges {{ display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }}
        .alert-ticker {{ font-size: 1.15rem; font-weight: 800; color: #fff; }}
        .alert-time {{ font-size: 0.8rem; color: var(--text-dim); font-family: var(--font-mono); }}
        .alert-title {{ font-size: 1.15rem; font-weight: 700; color: #fff; margin-bottom: 6px; }}
        .alert-blurb {{ font-size: 0.92rem; color: var(--text-secondary); line-height: 1.5; }}

        .alert-right {{ text-align: right; min-width: 150px; }}
        .alert-price-val {{ font-size: 1.45rem; font-weight: 700; font-family: var(--font-mono); color: #fff; }}
        .alert-price-pct {{ font-size: 0.92rem; font-weight: 600; font-family: var(--font-mono); }}
        .alert-view-btn {{ font-size: 0.82rem; font-weight: 700; color: var(--accent-cyan); display: inline-block; margin-top: 8px; }}

        /* Badges */
        .pill {{
            display: inline-flex;
            align-items: center;
            padding: 3px 10px;
            border-radius: 9999px;
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .pill-primary {{ background: rgba(var(--accent-cyan-rgb), 0.12); color: var(--accent-cyan); border: 1px solid rgba(var(--accent-cyan-rgb), 0.3); }}
        .pill-alert {{ background: rgba(245, 158, 11, 0.12); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }}

        .pos {{ color: var(--accent-emerald); }}
        .neg {{ color: var(--accent-rose); }}

        .empty-alerts {{
            text-align: center;
            background: var(--bg-panel);
            border: 1px dashed var(--border-color);
            border-radius: 18px;
            padding: 70px 24px;
        }}
        .empty-icon {{ font-size: 2.2rem; margin-bottom: 12px; }}
        .empty-title {{ font-size: 1.15rem; font-weight: 700; color: #fff; margin-bottom: 6px; }}
        .empty-sub {{ font-size: 0.92rem; color: var(--text-secondary); max-width: 480px; margin: 0 auto; }}

        /* Modal */
        .modal-shade {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.82);
            backdrop-filter: blur(16px);
            z-index: 1000;
            display: none;
            justify-content: center;
            align-items: center;
            padding: 24px;
        }}
        .modal-body-card {{
            background: var(--bg-panel);
            border: 1px solid var(--border-focus);
            border-radius: 20px;
            max-width: 760px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            padding: 36px;
            box-shadow: 0 24px 60px rgba(0,0,0,0.8);
            position: relative;
        }}
        .modal-x {{
            position: absolute;
            top: 24px; right: 24px;
            background: none;
            border: none;
            color: var(--text-dim);
            font-size: 1.4rem;
            cursor: pointer;
        }}
        .modal-x:hover {{ color: #fff; }}

        .diff-modal-wrap {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin: 24px 0;
        }}
        @media (max-width: 640px) {{ .diff-modal-wrap {{ grid-template-columns: 1fr; }} }}
        .diff-side {{ padding: 20px; border-radius: 12px; border: 1px solid var(--border-color); }}
        .side-before {{ background: rgba(244, 63, 94, 0.03); border-color: rgba(244, 63, 94, 0.2); }}
        .side-after {{ background: rgba(var(--accent-emerald-rgb), 0.03); border-color: rgba(var(--accent-emerald-rgb), 0.2); }}
        .side-heading {{ font-size: 0.72rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }}
        .side-before .side-heading {{ color: #fb7185; }}
        .side-after .side-heading {{ color: #34d399; }}
        .side-text {{ font-size: 0.95rem; color: #cbd5e1; line-height: 1.6; }}

        .btn {{
            padding: 10px 20px;
            border-radius: 10px;
            font-weight: 700;
            font-size: 0.9rem;
            cursor: pointer;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            border: none;
            transition: all 0.15s;
        }}
        .btn-primary {{ background: var(--accent-cyan); color: #090b10; }}
        .btn-primary:hover {{ background: #7dd3fc; }}
        .btn-outline {{ background: var(--bg-elevated); color: #fff; border: 1px solid var(--border-color); }}
        .btn-outline:hover {{ background: var(--bg-subpanel); }}
    </style>
</head>
<body>
    <header class="nav-header">
        <div class="container header-content">
            <div class="brand-logo">
                <span class="brand-symbol">◈</span>
                <span>ALPHATHESIS</span>
                <span class="engine-pill"><span class="pulse-dot"></span>GEMINI 3.6 FLASH</span>
            </div>
            <div style="font-size: 0.8rem; color: var(--text-dim); font-family: var(--font-mono);">
                AUTONOMOUS EQUITY SURVEILLANCE
            </div>
        </div>
    </header>

    <main class="container">
        <!-- Macro Summary Stats Ribbon -->
        <section class="macro-ribbon">
            <div class="macro-card">
                <div class="macro-icon">📊</div>
                <div class="macro-data">
                    <span class="macro-lbl">Active Watchlist</span>
                    <span class="macro-val">{len(watchlist)} Companies</span>
                </div>
            </div>
            <div class="macro-card">
                <div class="macro-icon">⚡</div>
                <div class="macro-data">
                    <span class="macro-lbl">Surveillance Engine</span>
                    <span class="macro-val" style="color: var(--accent-emerald);">2x Daily Cron</span>
                </div>
            </div>
            <div class="macro-card">
                <div class="macro-icon">🚨</div>
                <div class="macro-data">
                    <span class="macro-lbl">Critical Alerts</span>
                    <span class="macro-val" style="color: var(--accent-amber);">{len(alerts)} Active</span>
                </div>
            </div>
        </section>

        <!-- Navigation Tabs & View Toggle -->
        <div class="hub-controls">
            <div class="hub-tabs">
                <button class="hub-tab-btn active" onclick="switchTab('stocks')">📈 Tracked Coverage ({len(watchlist)})</button>
                <button class="hub-tab-btn" onclick="switchTab('alerts')">🚨 Critical Alerts ({len(alerts)})</button>
            </div>
            <div class="view-toggle" id="view-toggle-bar">
                <button class="view-btn active" onclick="setView('table')">Table View</button>
                <button class="view-btn" onclick="setView('grid')">Grid Cards</button>
            </div>
        </div>

        <!-- STOCKS SECTION -->
        <section id="pane-stocks" class="tab-panel active">
            <!-- Table View (Default) -->
            <div id="stocks-table-view" class="table-wrap">
                <table class="fin-table">
                    <thead>
                        <tr>
                            <th>Ticker & Company</th>
                            <th>Current Price</th>
                            <th>Thesis Stance</th>
                            <th>Intrinsic Valuation</th>
                            <th>Surveillance Corridor</th>
                            <th>Catalyst Horizon</th>
                            <th style="text-align: right;">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {table_rows_html}
                    </tbody>
                </table>
            </div>

            <!-- Grid Cards View -->
            <div id="stocks-grid-view" class="grid-cards-wrap" style="display: none;">
                {grid_cards_html}
            </div>
        </section>

        <!-- ALERTS SECTION -->
        <section id="pane-alerts" class="tab-panel">
            <div class="alerts-feed">
                {alerts_feed_html}
            </div>
        </section>
    </main>

    <!-- Alert Delta Modal -->
    <div id="alert-modal" class="modal-shade" onclick="closeModalOutside(event)">
        <div class="modal-body-card" id="modal-card">
            <button class="modal-x" onclick="closeAlertModal()">✕</button>
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
                <span id="modal-badge" class="pill pill-alert">ALERT</span>
                <strong id="modal-ticker" style="font-size: 1.3rem; color: #fff;">TICKER</strong>
                <span id="modal-time" style="color: var(--text-dim); font-size: 0.85rem; font-family: var(--font-mono);">Timestamp</span>
            </div>
            <h2 id="modal-title" style="font-size: 1.4rem; color: #fff; margin-bottom: 12px; letter-spacing: -0.02em;">Alert Headline</h2>
            <div style="font-size: 0.92rem; color: var(--text-secondary); margin-bottom: 20px;">
                <strong>Trigger Event:</strong> <span id="modal-trigger">Reason</span>
            </div>

            <div class="diff-modal-wrap">
                <div class="diff-side side-before">
                    <div class="side-heading">⏪ Previous Thesis Stance</div>
                    <div id="modal-before" class="side-text">Previous stance...</div>
                </div>
                <div class="diff-side side-after">
                    <div class="side-heading">⚡ What Changes Now</div>
                    <div id="modal-after" class="side-text">Updated thesis...</div>
                </div>
            </div>

            <div style="display: flex; justify-content: flex-end; gap: 12px; margin-top: 28px;">
                <button class="btn btn-outline" onclick="closeAlertModal()">Dismiss</button>
                <a id="modal-report-link" href="#" class="btn btn-primary">Open Full Living Dossier →</a>
            </div>
        </div>
    </div>

    <script>
        function switchTab(tab) {{
            document.querySelectorAll('.hub-tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(sec => sec.classList.remove('active'));
            
            if (tab === 'stocks') {{
                document.querySelectorAll('.hub-tab-btn')[0].classList.add('active');
                document.getElementById('pane-stocks').classList.add('active');
                document.getElementById('view-toggle-bar').style.display = 'flex';
            }} else {{
                document.querySelectorAll('.hub-tab-btn')[1].classList.add('active');
                document.getElementById('pane-alerts').classList.add('active');
                document.getElementById('view-toggle-bar').style.display = 'none';
            }}
        }}

        function setView(viewType) {{
            document.querySelectorAll('.view-btn').forEach(btn => btn.classList.remove('active'));
            if (viewType === 'table') {{
                document.querySelectorAll('.view-btn')[0].classList.add('active');
                document.getElementById('stocks-table-view').style.display = 'block';
                document.getElementById('stocks-grid-view').style.display = 'none';
            }} else {{
                document.querySelectorAll('.view-btn')[1].classList.add('active');
                document.getElementById('stocks-table-view').style.display = 'none';
                document.getElementById('stocks-grid-view').style.display = 'grid';
            }}
        }}

        function openAlertModal(payload) {{
            document.getElementById('modal-ticker').innerText = payload.ticker;
            document.getElementById('modal-title').innerText = payload.title;
            document.getElementById('modal-time').innerText = payload.timestamp;
            document.getElementById('modal-badge').innerText = payload.severity;
            document.getElementById('modal-trigger').innerText = payload.trigger_reason;
            document.getElementById('modal-before').innerText = payload.what_was_before || 'Genesis baseline';
            document.getElementById('modal-after').innerText = payload.what_changes_now || 'Thesis updated';
            document.getElementById('modal-report-link').href = payload.report_url;
            
            document.getElementById('alert-modal').style.display = 'flex';
        }}

        function closeAlertModal() {{
            document.getElementById('alert-modal').style.display = 'none';
        }}

        function closeModalOutside(event) {{
            if (event.target.id === 'alert-modal') {{
                closeAlertModal();
            }}
        }}
    </script>
</body>
</html>
"""


def render_all():
    """Compiles all company dossiers and the master index dashboard."""
    _ensure_dirs()
    watchlist = load_watchlist()
    alerts = load_alerts()
    
    # 1. Render each company dossier
    for ticker, stock in watchlist.items():
        history = load_thesis_history(ticker)
        html = generate_company_dossier_html(ticker, stock, history)
        report_file = REPORTS_DIR / f"{ticker.upper()}.html"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(html)
            
    # 2. Render master index dashboard
    master_html = generate_master_dashboard_html(watchlist, alerts)
    with open(PUBLIC_DIR / "index.html", "w", encoding="utf-8") as f:
        f.write(master_html)
