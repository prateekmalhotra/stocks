"""Claude-Inspired Warm Obsidian & Literary Serif Financial Terminal & Living Dossier."""

import json
from pathlib import Path
from typing import List, Dict
from stocks.models import WatchlistStock, AlertItem, ThesisVersion
from stocks.data_store import load_watchlist, load_alerts, load_thesis_history

PUBLIC_DIR = Path("public")
REPORTS_DIR = PUBLIC_DIR / "reports"


def _ensure_dirs():
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def generate_company_dossier_html(ticker: str, stock: WatchlistStock, history: List[ThesisVersion]) -> str:
    """Generates a Claude-inspired warm obsidian living memo."""
    current_version = history[-1] if history else None
    
    # Corridor percentages
    bear_p = stock.lower_alert_threshold or (stock.current_price * 0.8)
    bull_p = stock.upper_alert_threshold or (stock.current_price * 1.3)
    span = max(bull_p - bear_p, 1.0)
    current_pos_pct = max(0, min(100, ((stock.current_price - bear_p) / span) * 100))

    # Format history timeline cards
    history_cards_html = ""
    for v in reversed(history):
        is_current = (v.version == len(history))
        current_badge = '<span class="pill pill-terracotta">Active Thesis</span>' if is_current else f'<span class="pill pill-muted">v{v.version}</span>'
        
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
                    <span class="history-time">{v.date}</span>
                    <span class="history-price">Price: <strong>${v.price_at_version:.2f}</strong></span>
                    <span class="pill pill-neutral">{v.status_label}</span>
                </div>
                <button class="btn btn-subtle" onclick="toggleSnapshot({v.version})">Read Snapshot ▾</button>
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
    <title>{ticker} — Investment Memo | AlphaThesis</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com">
    <link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,300;1,6..72,400;1,6..72,500&family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <style>
        :root {{
            --bg-canvas: #181816;         /* Claude warm obsidian espresso */
            --bg-panel: #22211D;          /* Warm dark card */
            --bg-subpanel: #2A2924;       /* Subtle inner container */
            --bg-hover: #32302A;
            --text-title: #FAF7F2;        /* Claude warm alabaster */
            --text-body: #DCD6CD;         /* Soothing warm cream text */
            --text-secondary: #A39D93;    /* Muted warm stone */
            --text-dim: #706B62;          /* Subtle label */
            --accent-terracotta: #D97757; /* Claude signature starburst terracotta */
            --accent-terracotta-tint: rgba(217, 119, 87, 0.12);
            --accent-sage: #86A789;       /* Muted warm sage green */
            --accent-rose: #D4736E;       /* Muted warm brick rose */
            --accent-warm: #C4A482;       /* Warm parchment gold */
            --border-color: rgba(240, 235, 225, 0.08);
            --border-focus: rgba(240, 235, 225, 0.16);
            --font-serif: 'Newsreader', Garamond, Georgia, serif;
            --font-sans: 'Plus Jakarta Sans', -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg-canvas);
            color: var(--text-body);
            font-family: var(--font-serif);
            line-height: 1.85;
            -webkit-font-smoothing: antialiased;
            padding-bottom: 140px;
        }}

        .container {{ max-width: 1040px; margin: 0 auto; padding: 0 28px; }}

        /* Top Navigation */
        nav.nav-bar {{
            background: rgba(24, 24, 22, 0.88);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 100;
            padding: 18px 0;
        }}
        .nav-inner {{ display: flex; justify-content: space-between; align-items: center; }}
        .nav-back {{
            color: var(--accent-terracotta);
            text-decoration: none;
            font-family: var(--font-sans);
            font-size: 0.9rem;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.15s;
        }}
        .nav-back:hover {{ transform: translateX(-3px); color: #E89073; }}
        .nav-meta {{ font-size: 0.76rem; color: var(--text-dim); font-family: var(--font-sans); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; }}

        /* Hero Deck */
        .hero-deck {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 44px 48px;
            margin: 40px 0 36px;
            position: relative;
        }}

        .hero-top-row {{ display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 24px; }}
        .ticker-headline {{ display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }}
        .ticker-symbol {{
            font-family: var(--font-serif);
            font-size: 3.2rem;
            font-weight: 500;
            letter-spacing: -0.03em;
            color: var(--text-title);
        }}
        .company-meta {{ color: var(--text-secondary); font-size: 1.15rem; font-style: italic; margin-top: 4px; }}

        .price-callout {{ text-align: right; }}
        .price-number {{ font-size: 3rem; font-weight: 600; font-family: var(--font-mono); color: var(--text-title); letter-spacing: -0.03em; }}
        .price-sub {{ font-size: 0.92rem; font-weight: 500; font-family: var(--font-mono); margin-top: 4px; }}

        /* Embedded Chart Section */
        .chart-section {{
            margin-top: 32px;
            background: #1C1B18;
            border: 1px solid var(--border-color);
            border-radius: 14px;
            overflow: hidden;
            height: 380px;
        }}

        /* Corridor Slider */
        .corridor-container {{
            margin-top: 32px;
            padding-top: 24px;
            border-top: 1px solid var(--border-color);
        }}
        .corridor-header {{
            display: flex;
            justify-content: space-between;
            font-size: 0.78rem;
            color: var(--text-dim);
            text-transform: uppercase;
            font-family: var(--font-sans);
            font-weight: 600;
            letter-spacing: 0.05em;
            margin-bottom: 10px;
        }}
        .corridor-track {{
            height: 6px;
            background: var(--bg-subpanel);
            border-radius: 9999px;
            position: relative;
        }}
        .corridor-fill {{
            height: 100%;
            background: linear-gradient(90deg, #A85854, #C4A482, #789A7A, #D97757);
            border-radius: 9999px;
            opacity: 0.7;
            width: 100%;
        }}
        .corridor-marker {{
            position: absolute;
            top: -6px;
            width: 18px;
            height: 18px;
            background: var(--text-title);
            border: 3px solid var(--accent-terracotta);
            border-radius: 50%;
            transform: translateX(-50%);
            box-shadow: 0 0 10px rgba(217, 119, 87, 0.4);
        }}

        /* Metrics Ribbon */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 12px;
            margin-top: 28px;
        }}
        .metric-cell {{
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 16px 18px;
        }}
        .metric-label {{ font-size: 0.7rem; text-transform: uppercase; color: var(--text-dim); font-family: var(--font-sans); font-weight: 600; letter-spacing: 0.05em; }}
        .metric-value {{ font-size: 1.25rem; font-weight: 600; color: var(--text-title); font-family: var(--font-mono); margin-top: 4px; }}

        /* Tabs Header */
        .tabs-header {{
            display: flex;
            gap: 12px;
            border-bottom: 1px solid var(--border-color);
            margin: 40px 0 32px;
        }}
        .tab-btn {{
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 1.15rem;
            font-family: var(--font-serif);
            padding: 14px 22px;
            cursor: pointer;
            position: relative;
            transition: all 0.15s;
        }}
        .tab-btn:hover {{ color: var(--text-title); }}
        .tab-btn.active {{ color: var(--accent-terracotta); }}
        .tab-btn.active::after {{
            content: '';
            position: absolute;
            bottom: -1px;
            left: 0; right: 0;
            height: 2px;
            background: var(--accent-terracotta);
        }}

        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}

        /* Due Diligence Memo Styling */
        .memo-container {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 56px 64px;
        }}
        .memo-container h2 {{
            font-family: var(--font-serif);
            font-size: 1.65rem;
            font-weight: 500;
            color: var(--text-title);
            margin: 48px 0 20px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            gap: 12px;
            letter-spacing: -0.02em;
        }}
        .memo-container h2:first-of-type {{ margin-top: 0; }}
        .memo-container h3 {{
            font-family: var(--font-serif);
            font-size: 1.35rem;
            font-weight: 500;
            color: var(--accent-warm);
            margin: 32px 0 14px;
        }}
        .memo-container p {{
            font-size: 1.25rem;
            line-height: 1.95;
            color: var(--text-body);
            margin-bottom: 24px;
        }}
        .memo-container ul, .memo-container ol {{
            font-size: 1.2rem;
            line-height: 1.95;
            color: var(--text-body);
            margin: 0 0 28px 36px;
        }}
        .memo-container li {{ margin-bottom: 10px; }}

        .memo-container table {{
            width: 100%;
            border-collapse: collapse;
            margin: 32px 0;
            background: var(--bg-subpanel);
            border-radius: 10px;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }}
        .memo-container th, .memo-container td {{
            padding: 14px 20px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.95rem;
        }}
        .memo-container th {{
            background: rgba(0, 0, 0, 0.2);
            color: var(--text-title);
            font-family: var(--font-sans);
            font-weight: 600;
            font-size: 0.76rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .memo-container blockquote {{
            background: var(--bg-subpanel);
            border-left: 3px solid var(--accent-terracotta);
            padding: 22px 30px;
            border-radius: 0 10px 10px 0;
            margin: 32px 0;
            font-style: italic;
            font-size: 1.22rem;
            color: var(--text-title);
            line-height: 1.85;
        }}
        .memo-container .callout {{
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-left: 3px solid var(--accent-warm);
            border-radius: 10px;
            padding: 22px 26px;
            margin: 28px 0;
        }}

        /* History Entry */
        .history-entry {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 32px 36px;
            margin-bottom: 24px;
        }}
        .history-entry-active {{ border-color: rgba(217, 119, 87, 0.4); }}
        .history-top {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }}
        .history-tags {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
        .history-time {{ color: var(--text-secondary); font-size: 0.92rem; font-family: var(--font-sans); }}
        .history-price {{ font-family: var(--font-mono); font-size: 0.96rem; }}

        .diff-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 18px;
            margin: 24px 0;
        }}
        @media (max-width: 768px) {{ .diff-grid {{ grid-template-columns: 1fr; }} }}
        .diff-box {{
            padding: 22px;
            border-radius: 10px;
            border: 1px solid var(--border-color);
        }}
        .diff-prev {{ background: rgba(212, 115, 110, 0.06); border-color: rgba(212, 115, 110, 0.2); }}
        .diff-now {{ background: rgba(134, 167, 137, 0.06); border-color: rgba(134, 167, 137, 0.2); }}
        .diff-label {{ font-family: var(--font-sans); font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }}
        .diff-prev .diff-label {{ color: var(--accent-rose); }}
        .diff-now .diff-label {{ color: var(--accent-sage); }}
        .diff-text {{ font-size: 1.1rem; color: var(--text-body); line-height: 1.7; }}

        /* Pills & Badges */
        .pill {{
            display: inline-flex;
            align-items: center;
            padding: 4px 14px;
            border-radius: 9999px;
            font-size: 0.74rem;
            font-family: var(--font-sans);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .pill-terracotta {{ background: var(--accent-terracotta-tint); color: var(--accent-terracotta); border: 1px solid rgba(217, 119, 87, 0.3); }}
        .pill-neutral {{ background: var(--bg-subpanel); color: var(--text-secondary); border: 1px solid var(--border-color); }}
        .pill-muted {{ background: var(--bg-subpanel); color: var(--text-dim); }}

        .btn-subtle {{
            background: var(--bg-subpanel);
            color: var(--text-title);
            border: 1px solid var(--border-color);
            font-family: var(--font-sans);
            font-size: 0.82rem;
            font-weight: 600;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .btn-subtle:hover {{ background: var(--bg-hover); }}

        .snapshot-drawer {{ margin-top: 28px; padding-top: 28px; border-top: 1px solid var(--border-color); }}

        .pos {{ color: var(--accent-sage); }}
        .neg {{ color: var(--accent-rose); }}
    </style>
</head>
<body>
    <nav class="nav-bar">
        <div class="container nav-inner">
            <a href="../index.html" class="nav-back">← Master Ledger</a>
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
                        <span class="pill pill-terracotta">{stock.status_label}</span>
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

            <!-- Embedded Live Chart -->
            <div class="chart-section">
                <div id="tradingview_chart_container" style="height: 100%; width: 100%;"></div>
                <script type="text/javascript">
                new TradingView.widget({{
                    "autosize": true,
                    "symbol": "{stock.ticker}",
                    "interval": "D",
                    "timezone": "America/New_York",
                    "theme": "dark",
                    "style": "3",
                    "locale": "en",
                    "toolbar_bg": "#1C1B18",
                    "enable_publishing": false,
                    "hide_top_toolbar": false,
                    "hide_legend": false,
                    "save_image": false,
                    "container_id": "tradingview_chart_container"
                }});
                </script>
            </div>

            <!-- Corridor -->
            <div class="corridor-container">
                <div class="corridor-header">
                    <span>Bear Floor (${bear_p:.2f})</span>
                    <span>Current Market: ${stock.current_price:.2f}</span>
                    <span>Bull Target (${bull_p:.2f})</span>
                </div>
                <div class="corridor-track">
                    <div class="corridor-fill"></div>
                    <div class="corridor-marker" style="left: {current_pos_pct:.1f}%;"></div>
                </div>
            </div>

            <!-- Key Metrics Grid -->
            <div class="metrics-grid">
                <div class="metric-cell">
                    <div class="metric-label">Fair Value Target</div>
                    <div class="metric-value" style="color: var(--accent-terracotta);">{stock.fair_value_estimate}</div>
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
                    <div class="metric-value" style="color: var(--accent-sage);">{stock.bull_target}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Upper Trigger</div>
                    <div class="metric-value">${stock.upper_alert_threshold:.2f}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Lower Trigger</div>
                    <div class="metric-value">${stock.lower_alert_threshold:.2f}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Next Catalyst</div>
                    <div class="metric-value" style="font-size: 0.95rem; font-family: var(--font-sans);">{stock.next_catalyst_date or 'TBD'}</div>
                </div>
            </div>
        </section>

        <!-- Navigation Tabs -->
        <div class="tabs-header">
            <button class="tab-btn active" onclick="showTab('memo')">Active Investment Thesis</button>
            <button class="tab-btn" onclick="showTab('history')">Evolution & Snapshots ({len(history)})</button>
        </div>

        <!-- Memo Content -->
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
    """Generates the Claude-inspired warm obsidian master ledger."""
    _ensure_dirs()
    
    table_rows_html = ""
    grid_cards_html = ""

    if not watchlist:
        table_rows_html = """
        <tr>
            <td colspan="7" style="text-align: center; padding: 70px 24px; color: var(--text-secondary); font-family: var(--font-serif); font-size: 1.15rem;">
                <div style="font-size: 2rem; color: var(--accent-terracotta); margin-bottom: 12px;">✳</div>
                <div style="color: var(--text-title); font-size: 1.3rem; font-weight: 500; margin-bottom: 6px;">Ledger is Currently Empty</div>
                <div style="font-size: 1.05rem;">Add stocks to begin due diligence and 24/7 surveillance tracking.</div>
            </td>
        </tr>
        """
        grid_cards_html = """
        <div style="grid-column: 1 / -1; text-align: center; padding: 70px 24px; background: var(--bg-panel); border: 1px dashed var(--border-color); border-radius: 18px;">
            <div style="font-size: 2rem; color: var(--accent-terracotta); margin-bottom: 12px;">✳</div>
            <div style="color: var(--text-title); font-size: 1.3rem; font-weight: 500; margin-bottom: 6px;">No Active Coverage</div>
            <div style="color: var(--text-secondary); font-size: 1.05rem;">Ready to process initial due diligence memos.</div>
        </div>
        """

    for ticker, stock in sorted(watchlist.items(), key=lambda x: x[0]):
        ret_class = "pos" if stock.return_pct >= 0 else "neg"
        
        bear_p = stock.lower_alert_threshold or (stock.current_price * 0.8)
        bull_p = stock.upper_alert_threshold or (stock.current_price * 1.3)
        span = max(bull_p - bear_p, 1.0)
        pos_pct = max(0, min(100, ((stock.current_price - bear_p) / span) * 100))

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
                <span class="pill pill-terracotta">{stock.status_label}</span>
            </td>
            <td>
                <div class="tbl-val-cell">
                    <span class="tbl-fv" style="color: var(--accent-terracotta);">{stock.fair_value_estimate}</span>
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
                    <span class="tbl-cat-desc">{stock.next_catalyst_event[:45] if stock.next_catalyst_event else ''}</span>
                </div>
            </td>
            <td style="text-align: right; white-space: nowrap;">
                <a href="reports/{stock.ticker}.html" class="btn-action" onclick="event.stopPropagation()">Read Thesis →</a>
            </td>
        </tr>
        """

        grid_cards_html += f"""
        <div class="grid-card" onclick="location.href='reports/{stock.ticker}.html'">
            <div class="grid-card-top">
                <div>
                    <span class="grid-symbol">{stock.ticker}</span>
                    <span class="pill pill-terracotta" style="margin-left: 10px;">{stock.status_label}</span>
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
                    <span class="grid-stat-val" style="color: var(--accent-terracotta);">{stock.fair_value_estimate}</span>
                </div>
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Trigger Bounds</span>
                    <span class="grid-stat-val">${stock.lower_alert_threshold:.0f} — ${stock.upper_alert_threshold:.0f}</span>
                </div>
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Next Catalyst</span>
                    <span class="grid-stat-val" style="font-family: var(--font-sans);">{stock.next_catalyst_date or 'TBD'}</span>
                </div>
            </div>
            
            <div class="grid-card-foot">
                <span class="grid-updated">Evaluated {stock.last_updated}</span>
                <span class="grid-open">Read Thesis →</span>
            </div>
        </div>
        """

    alerts_feed_html = ""
    if not alerts:
        alerts_feed_html = """
        <div class="empty-alerts">
            <div class="empty-star">✳</div>
            <div class="empty-title">All Positions Within Surveillance Corridors</div>
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
                        <span class="alert-time">{a.timestamp}</span>
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
    <title>AlphaThesis — Concentrated Equity Research Hub</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com">
    <link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-canvas: #181816;         /* Claude warm obsidian espresso */
            --bg-panel: #22211D;          /* Warm dark card */
            --bg-subpanel: #2A2924;       /* Subtle inner container */
            --bg-hover: #302E29;
            --text-title: #FAF7F2;        /* Claude warm alabaster */
            --text-body: #DCD6CD;         /* Soothing warm cream */
            --text-secondary: #A39D93;    /* Muted warm stone */
            --text-dim: #706B62;          /* Subtle label */
            --accent-terracotta: #D97757; /* Claude starburst terracotta */
            --accent-terracotta-tint: rgba(217, 119, 87, 0.12);
            --accent-sage: #86A789;       /* Muted warm sage green */
            --accent-rose: #D4736E;       /* Muted warm brick rose */
            --accent-warm: #C4A482;       /* Warm parchment gold */
            --border-color: rgba(240, 235, 225, 0.08);
            --border-focus: rgba(240, 235, 225, 0.16);
            --font-serif: 'Newsreader', Garamond, Georgia, serif;
            --font-sans: 'Plus Jakarta Sans', -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg-canvas);
            color: var(--text-body);
            font-family: var(--font-serif);
            min-height: 100vh;
            -webkit-font-smoothing: antialiased;
            padding-bottom: 140px;
        }}

        .container {{ max-width: 1140px; margin: 0 auto; padding: 0 28px; }}

        /* Header */
        header.nav-header {{
            background: rgba(24, 24, 22, 0.88);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 100;
            padding: 18px 0;
        }}
        .header-content {{ display: flex; justify-content: space-between; align-items: center; }}
        .brand-logo {{ display: flex; align-items: center; gap: 10px; font-family: var(--font-serif); font-size: 1.45rem; font-weight: 500; letter-spacing: -0.02em; color: var(--text-title); }}
        .brand-star {{ color: var(--accent-terracotta); font-size: 1.5rem; line-height: 1; }}
        .engine-pill {{
            background: var(--accent-terracotta-tint);
            color: var(--accent-terracotta);
            font-size: 0.74rem;
            font-family: var(--font-sans);
            font-weight: 600;
            padding: 4px 12px;
            border-radius: 9999px;
            border: 1px solid rgba(217, 119, 87, 0.25);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-left: 8px;
        }}

        /* Macro Stats Ribbon */
        .macro-ribbon {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin: 40px 0 32px;
        }}
        .macro-card {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px 28px;
            display: flex;
            align-items: center;
            gap: 18px;
        }}
        .macro-icon {{ font-size: 1.6rem; color: var(--accent-terracotta); }}
        .macro-data {{ display: flex; flex-direction: column; }}
        .macro-lbl {{ font-size: 0.72rem; text-transform: uppercase; color: var(--text-dim); font-family: var(--font-sans); font-weight: 600; letter-spacing: 0.06em; }}
        .macro-val {{ font-size: 1.55rem; font-weight: 500; color: var(--text-title); font-family: var(--font-serif); margin-top: 2px; }}

        /* Navigation Controls */
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
            font-size: 1.15rem;
            font-family: var(--font-serif);
            font-weight: 400;
            padding: 10px 20px;
            cursor: pointer;
            position: relative;
            transition: all 0.15s;
        }}
        .hub-tab-btn:hover {{ color: var(--text-title); }}
        .hub-tab-btn.active {{ color: var(--accent-terracotta); }}
        .hub-tab-btn.active::after {{
            content: '';
            position: absolute;
            bottom: -17px;
            left: 0; right: 0;
            height: 2px;
            background: var(--accent-terracotta);
        }}

        .view-toggle {{
            display: flex;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 3px;
        }}
        .view-btn {{
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 0.8rem;
            font-family: var(--font-sans);
            font-weight: 600;
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .view-btn.active {{ background: var(--bg-hover); color: var(--text-title); }}

        .tab-panel {{ display: none; }}
        .tab-panel.active {{ display: block; }}

        /* Table View */
        .table-wrap {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 18px;
            overflow: hidden;
        }}
        table.fin-table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        table.fin-table th {{
            background: var(--bg-subpanel);
            color: var(--text-dim);
            font-family: var(--font-sans);
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            padding: 16px 24px;
            border-bottom: 1px solid var(--border-color);
        }}
        table.fin-table td {{
            padding: 20px 24px;
            border-bottom: 1px solid var(--border-color);
            font-size: 1rem;
            vertical-align: middle;
        }}
        .table-row {{ cursor: pointer; transition: background 0.15s; }}
        .table-row:hover {{ background: var(--bg-hover); }}
        .table-row:last-child td {{ border-bottom: none; }}

        .tbl-ticker-cell {{ display: flex; flex-direction: column; }}
        .tbl-symbol {{ font-family: var(--font-serif); font-size: 1.45rem; font-weight: 500; color: var(--text-title); }}
        .tbl-company {{ font-size: 0.9rem; color: var(--text-dim); font-style: italic; }}

        .tbl-price-cell {{ display: flex; flex-direction: column; }}
        .tbl-price {{ font-size: 1.25rem; font-weight: 600; font-family: var(--font-mono); color: var(--text-title); }}
        .tbl-return {{ font-size: 0.82rem; font-weight: 500; font-family: var(--font-mono); }}

        .tbl-val-cell {{ display: flex; flex-direction: column; }}
        .tbl-fv {{ font-size: 1.15rem; font-weight: 600; font-family: var(--font-mono); }}
        .tbl-base {{ font-size: 0.85rem; color: var(--text-secondary); }}

        .tbl-corridor-cell {{ min-width: 160px; }}
        .tbl-corridor-labels {{ display: flex; justify-content: space-between; font-size: 0.7rem; color: var(--text-dim); font-family: var(--font-mono); margin-bottom: 4px; }}
        .mini-corridor-track {{
            height: 6px; background: var(--bg-subpanel); border-radius: 9999px; position: relative;
        }}
        .mini-corridor-fill {{
            height: 100%; width: 100%; border-radius: 9999px;
            background: linear-gradient(90deg, #A85854, #C4A482, #789A7A, #D97757);
            opacity: 0.7;
        }}
        .mini-corridor-dot {{
            position: absolute; top: -3px; width: 12px; height: 12px;
            background: var(--text-title); border: 2px solid var(--accent-terracotta); border-radius: 50%;
            transform: translateX(-50%); box-shadow: 0 0 8px rgba(217, 119, 87, 0.4);
        }}

        .tbl-catalyst-cell {{ display: flex; flex-direction: column; max-width: 200px; }}
        .tbl-cat-date {{ font-family: var(--font-sans); font-size: 0.88rem; font-weight: 600; color: var(--text-title); }}
        .tbl-cat-desc {{ font-size: 0.82rem; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

        .btn-action {{
            background: var(--bg-subpanel);
            color: var(--text-title);
            border: 1px solid var(--border-color);
            font-family: var(--font-sans);
            font-size: 0.82rem;
            font-weight: 600;
            padding: 9px 18px;
            border-radius: 8px;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            transition: all 0.15s;
        }}
        .btn-action:hover {{ background: var(--bg-hover); color: var(--accent-terracotta); border-color: rgba(217, 119, 87, 0.4); }}

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
            padding: 28px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .grid-card:hover {{
            background: var(--bg-hover);
            border-color: var(--border-focus);
            transform: translateY(-2px);
        }}
        .grid-card-top {{ display: flex; justify-content: space-between; align-items: center; }}
        .grid-symbol {{ font-family: var(--font-serif); font-size: 1.9rem; font-weight: 500; color: var(--text-title); }}
        .grid-price {{ font-size: 1.7rem; font-weight: 600; font-family: var(--font-mono); color: var(--text-title); }}
        .grid-company {{ color: var(--text-secondary); font-size: 0.96rem; font-style: italic; margin: 4px 0 22px; }}

        .grid-metrics-box {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            background: var(--bg-subpanel);
            padding: 16px;
            border-radius: 12px;
            margin-bottom: 22px;
        }}
        .grid-stat {{ display: flex; flex-direction: column; }}
        .grid-stat-lbl {{ font-size: 0.68rem; text-transform: uppercase; color: var(--text-dim); font-family: var(--font-sans); font-weight: 600; }}
        .grid-stat-val {{ font-size: 1.05rem; font-weight: 600; font-family: var(--font-mono); margin-top: 2px; }}

        .grid-card-foot {{
            display: flex; justify-content: space-between; align-items: center;
            border-top: 1px solid var(--border-color); padding-top: 16px;
        }}
        .grid-updated {{ font-size: 0.78rem; color: var(--text-dim); font-family: var(--font-mono); }}
        .grid-open {{ font-family: var(--font-sans); font-size: 0.85rem; font-weight: 600; color: var(--accent-terracotta); }}

        /* Alerts List */
        .alerts-feed {{ display: flex; flex-direction: column; gap: 16px; }}
        .alert-item {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 26px 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 24px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .alert-item:hover {{
            background: var(--bg-hover);
            border-color: rgba(217, 119, 87, 0.4);
            transform: translateX(3px);
        }}
        .alert-left {{ flex: 1; }}
        .alert-badges {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }}
        .alert-ticker {{ font-family: var(--font-serif); font-size: 1.25rem; font-weight: 500; color: var(--text-title); }}
        .alert-time {{ font-size: 0.82rem; color: var(--text-dim); font-family: var(--font-mono); }}
        .alert-title {{ font-family: var(--font-serif); font-size: 1.25rem; font-weight: 500; color: var(--text-title); margin-bottom: 6px; }}
        .alert-blurb {{ font-size: 1.1rem; color: var(--text-secondary); line-height: 1.6; }}

        .alert-right {{ text-align: right; min-width: 150px; }}
        .alert-price-val {{ font-size: 1.55rem; font-weight: 600; font-family: var(--font-mono); color: var(--text-title); }}
        .alert-price-pct {{ font-size: 0.95rem; font-weight: 500; font-family: var(--font-mono); }}
        .alert-view-btn {{ font-family: var(--font-sans); font-size: 0.85rem; font-weight: 600; color: var(--accent-terracotta); display: inline-block; margin-top: 8px; }}

        /* Pills */
        .pill {{
            display: inline-flex;
            align-items: center;
            padding: 4px 14px;
            border-radius: 9999px;
            font-size: 0.74rem;
            font-family: var(--font-sans);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .pill-terracotta {{ background: var(--accent-terracotta-tint); color: var(--accent-terracotta); border: 1px solid rgba(217, 119, 87, 0.3); }}
        .pill-alert {{ background: rgba(196, 164, 130, 0.12); color: var(--accent-warm); border: 1px solid rgba(196, 164, 130, 0.3); }}

        .pos {{ color: var(--accent-sage); }}
        .neg {{ color: var(--accent-rose); }}

        .empty-alerts {{
            text-align: center;
            background: var(--bg-panel);
            border: 1px dashed var(--border-color);
            border-radius: 16px;
            padding: 70px 24px;
        }}
        .empty-star {{ font-size: 2.2rem; color: var(--accent-terracotta); margin-bottom: 12px; }}
        .empty-title {{ font-family: var(--font-serif); font-size: 1.35rem; font-weight: 500; color: var(--text-title); margin-bottom: 6px; }}
        .empty-sub {{ font-size: 1.1rem; color: var(--text-secondary); max-width: 480px; margin: 0 auto; }}

        /* Modal */
        .modal-shade {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(12, 12, 11, 0.8);
            backdrop-filter: blur(14px);
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
            padding: 40px;
            position: relative;
        }}
        .modal-x {{
            position: absolute;
            top: 24px; right: 24px;
            background: none;
            border: none;
            color: var(--text-dim);
            font-size: 1.5rem;
            cursor: pointer;
        }}
        .modal-x:hover {{ color: var(--text-title); }}

        .diff-modal-wrap {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 18px;
            margin: 26px 0;
        }}
        @media (max-width: 640px) {{ .diff-modal-wrap {{ grid-template-columns: 1fr; }} }}
        .diff-side {{ padding: 22px; border-radius: 10px; border: 1px solid var(--border-color); }}
        .side-before {{ background: rgba(212, 115, 110, 0.06); border-color: rgba(212, 115, 110, 0.2); }}
        .side-after {{ background: rgba(134, 167, 137, 0.06); border-color: rgba(134, 167, 137, 0.2); }}
        .side-heading {{ font-family: var(--font-sans); font-size: 0.74rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }}
        .side-before .side-heading {{ color: var(--accent-rose); }}
        .side-after .side-heading {{ color: var(--accent-sage); }}
        .side-text {{ font-size: 1.1rem; color: var(--text-body); line-height: 1.7; }}

        .btn-primary {{
            background: var(--accent-terracotta); color: #FAF7F2; font-family: var(--font-sans); font-weight: 600;
            padding: 12px 24px; border-radius: 8px; text-decoration: none; display: inline-flex; align-items: center; border: none; cursor: pointer;
            transition: all 0.15s;
        }}
        .btn-primary:hover {{ background: #E89073; }}
        .btn-outline {{
            background: var(--bg-subpanel); color: var(--text-title); border: 1px solid var(--border-color);
            font-family: var(--font-sans); font-weight: 600; padding: 12px 22px; border-radius: 8px; cursor: pointer;
        }}
        .btn-outline:hover {{ background: var(--bg-hover); }}
    </style>
</head>
<body>
    <header class="nav-header">
        <div class="container header-content">
            <div class="brand-logo">
                <span class="brand-star">✳</span>
                <span>AlphaThesis</span>
                <span class="engine-pill">Gemini 3.6 Flash</span>
            </div>
            <div style="font-size: 0.82rem; color: var(--text-dim); font-family: var(--font-sans); font-weight: 500; text-transform: uppercase; letter-spacing: 0.06em;">
                Surveillance Terminal
            </div>
        </div>
    </header>

    <main class="container">
        <!-- Macro Ribbon -->
        <section class="macro-ribbon">
            <div class="macro-card">
                <div class="macro-icon">✳</div>
                <div class="macro-data">
                    <span class="macro-lbl">Active Watchlist</span>
                    <span class="macro-val">{len(watchlist)} Companies</span>
                </div>
            </div>
            <div class="macro-card">
                <div class="macro-icon">⚡</div>
                <div class="macro-data">
                    <span class="macro-lbl">Surveillance Cadence</span>
                    <span class="macro-val" style="color: var(--accent-sage);">2x Daily Cron</span>
                </div>
            </div>
            <div class="macro-card">
                <div class="macro-icon">🚨</div>
                <div class="macro-data">
                    <span class="macro-lbl">Active Alerts</span>
                    <span class="macro-val" style="color: var(--accent-warm);">{len(alerts)} Triggered</span>
                </div>
            </div>
        </section>

        <!-- Navigation Tabs & View Toggle -->
        <div class="hub-controls">
            <div class="hub-tabs">
                <button class="hub-tab-btn active" onclick="switchTab('stocks')">Active Coverage ({len(watchlist)})</button>
                <button class="hub-tab-btn" onclick="switchTab('alerts')">Critical Alerts ({len(alerts)})</button>
            </div>
            <div class="view-toggle" id="view-toggle-bar">
                <button class="view-btn active" onclick="setView('table')">Table View</button>
                <button class="view-btn" onclick="setView('grid')">Cards View</button>
            </div>
        </div>

        <!-- STOCKS SECTION -->
        <section id="pane-stocks" class="tab-panel active">
            <!-- Table View -->
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
                <strong id="modal-ticker" style="font-family: var(--font-serif); font-size: 1.4rem; color: var(--text-title);">TICKER</strong>
                <span id="modal-time" style="color: var(--text-dim); font-size: 0.85rem; font-family: var(--font-mono);">Timestamp</span>
            </div>
            <h2 id="modal-title" style="font-family: var(--font-serif); font-size: 1.55rem; color: var(--text-title); margin-bottom: 12px; letter-spacing: -0.02em;">Alert Headline</h2>
            <div style="font-size: 0.95rem; color: var(--text-secondary); margin-bottom: 20px;">
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

            <div style="display: flex; justify-content: flex-end; gap: 14px; margin-top: 32px;">
                <button class="btn-outline" onclick="closeAlertModal()">Dismiss</button>
                <a id="modal-report-link" href="#" class="btn-primary">Open Research Memo →</a>
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
    
    for ticker, stock in watchlist.items():
        history = load_thesis_history(ticker)
        html = generate_company_dossier_html(ticker, stock, history)
        report_file = REPORTS_DIR / f"{ticker.upper()}.html"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(html)
            
    master_html = generate_master_dashboard_html(watchlist, alerts)
    with open(PUBLIC_DIR / "index.html", "w", encoding="utf-8") as f:
        f.write(master_html)
