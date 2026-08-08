"""Vercel Master Dashboard and Living Dossier HTML Generator."""

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
    """Generates the living HTML report for a specific company with active thesis and history tab."""
    current_version = history[-1] if history else None
    
    # Format history timeline cards
    history_cards_html = ""
    for v in reversed(history):
        is_current = (v.version == len(history))
        current_badge = '<span class="badge badge-current">Active Version</span>' if is_current else f'<span class="badge badge-history">v{v.version}</span>'
        
        diff_box = ""
        if v.what_was_before or v.what_changes_now:
            diff_box = f"""
            <div class="diff-grid">
                <div class="diff-col diff-before">
                    <div class="diff-header">⏪ What Was Before</div>
                    <div class="diff-body">{v.what_was_before or 'Initial Genesis Thesis baseline.'}</div>
                </div>
                <div class="diff-col diff-after">
                    <div class="diff-header">⚡ What Changed</div>
                    <div class="diff-body">{v.what_changes_now or v.summary_of_change}</div>
                </div>
            </div>
            """
            
        history_cards_html += f"""
        <div class="history-card {'current-version-card' if is_current else ''}">
            <div class="history-header">
                <div class="history-meta">
                    {current_badge}
                    <span class="history-date">📅 {v.date}</span>
                    <span class="history-price">Price: <strong>${v.price_at_version:.2f}</strong></span>
                    <span class="badge badge-status">{v.status_label}</span>
                </div>
                <button class="btn btn-sm btn-outline" onclick="toggleHistoryContent({v.version})">View Snapshot</button>
            </div>
            <div class="history-summary">
                <p><strong>Evolution Summary:</strong> {v.summary_of_change}</p>
            </div>
            {diff_box}
            <div id="history-content-{v.version}" class="history-snapshot-content" style="display: none;">
                <hr class="divider"/>
                <div class="snapshot-inner">
                    {v.full_html_content}
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
    <title>{ticker} — Living Investment Thesis & Research Dossier</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-base: #0a0d14;
            --bg-card: #121824;
            --bg-surface: #182234;
            --bg-accent: #1e2c44;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --text-dim: #64748b;
            --primary: #38bdf8;
            --primary-glow: rgba(56, 189, 248, 0.15);
            --success: #10b981;
            --success-glow: rgba(16, 185, 129, 0.15);
            --warning: #f59e0b;
            --danger: #ef4444;
            --border: #23324a;
            --border-light: #2e4161;
            --font-display: 'Outfit', -apple-system, sans-serif;
            --font-body: 'Newsreader', Georgia, serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg-base);
            color: var(--text-main);
            font-family: var(--font-display);
            line-height: 1.6;
            min-height: 100vh;
            padding-bottom: 80px;
        }}

        .container {{ max-width: 1120px; margin: 0 auto; padding: 0 24px; }}

        /* Top Nav */
        header {{
            background: rgba(18, 24, 36, 0.8);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 100;
            padding: 16px 0;
        }}
        .header-inner {{ display: flex; justify-content: space-between; align-items: center; }}
        .nav-back {{
            color: var(--primary);
            text-decoration: none;
            font-size: 0.95rem;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: transform 0.2s;
        }}
        .nav-back:hover {{ transform: translateX(-3px); }}

        /* Hero Card */
        .hero-card {{
            background: linear-gradient(135deg, #121824 0%, #172338 100%);
            border: 1px solid var(--border-light);
            border-radius: 16px;
            padding: 32px;
            margin: 32px 0 24px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.4);
        }}
        .hero-top {{ display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 16px; }}
        .ticker-group h1 {{ font-size: 2.4rem; font-weight: 800; letter-spacing: -0.5px; }}
        .company-sub {{ color: var(--text-muted); font-size: 1.1rem; }}
        
        .price-group {{ text-align: right; }}
        .price-val {{ font-size: 2.2rem; font-weight: 800; font-family: var(--font-mono); }}
        .price-return {{ font-size: 1rem; font-weight: 600; }}
        .return-pos {{ color: var(--success); }}
        .return-neg {{ color: var(--danger); }}

        .hero-metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 16px;
            margin-top: 24px;
            padding-top: 20px;
            border-top: 1px solid var(--border);
        }}
        .metric-tile {{
            background: var(--bg-surface);
            padding: 12px 16px;
            border-radius: 10px;
            border: 1px solid var(--border);
        }}
        .metric-lbl {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-dim); margin-bottom: 4px; }}
        .metric-val {{ font-size: 1.15rem; font-weight: 700; color: var(--text-main); font-family: var(--font-mono); }}

        /* Badges */
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .badge-status {{ background: var(--primary-glow); color: var(--primary); border: 1px solid var(--primary); }}
        .badge-current {{ background: var(--success-glow); color: var(--success); border: 1px solid var(--success); }}
        .badge-history {{ background: var(--bg-accent); color: var(--text-muted); border: 1px solid var(--border); }}

        /* Tabs */
        .tabs-nav {{
            display: flex;
            gap: 12px;
            border-bottom: 2px solid var(--border);
            margin: 28px 0 24px;
        }}
        .tab-btn {{
            background: none;
            border: none;
            color: var(--text-muted);
            font-size: 1.05rem;
            font-weight: 600;
            padding: 12px 20px;
            cursor: pointer;
            position: relative;
            font-family: var(--font-display);
            transition: color 0.2s;
        }}
        .tab-btn:hover {{ color: var(--text-main); }}
        .tab-btn.active {{ color: var(--primary); }}
        .tab-btn.active::after {{
            content: '';
            position: absolute;
            bottom: -2px;
            left: 0;
            right: 0;
            height: 2px;
            background: var(--primary);
            box-shadow: 0 0 10px var(--primary);
        }}

        .tab-pane {{ display: none; }}
        .tab-pane.active {{ display: block; }}

        /* Report Body Content (Graham & Dodd / Columbia Editorial Style) */
        .thesis-content {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 40px;
            color: #e2e8f0;
        }}
        .thesis-content h2 {{
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--primary);
            margin: 32px 0 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .thesis-content h2:first-of-type {{ margin-top: 0; }}
        .thesis-content h3 {{ font-size: 1.2rem; color: #cbd5e1; margin: 20px 0 10px; }}
        .thesis-content p {{
            font-family: var(--font-body);
            font-size: 1.15rem;
            line-height: 1.8;
            margin-bottom: 18px;
            color: #cbd5e1;
        }}
        .thesis-content ul, .thesis-content ol {{ margin: 0 0 20px 24px; font-family: var(--font-body); font-size: 1.1rem; line-height: 1.8; }}
        .thesis-content li {{ margin-bottom: 8px; }}
        
        .thesis-content table {{
            width: 100%;
            border-collapse: collapse;
            margin: 24px 0;
            background: var(--bg-surface);
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--border);
        }}
        .thesis-content th, .thesis-content td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid var(--border);
            font-size: 0.95rem;
        }}
        .thesis-content th {{ background: var(--bg-accent); color: var(--text-main); font-weight: 600; }}
        .thesis-content blockquote {{
            border-left: 4px solid var(--primary);
            background: var(--bg-surface);
            padding: 16px 20px;
            margin: 20px 0;
            border-radius: 0 8px 8px 0;
            font-style: italic;
        }}

        /* History Cards */
        .history-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            transition: border-color 0.2s;
        }}
        .history-card.current-version-card {{ border-color: var(--success); }}
        .history-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
            margin-bottom: 14px;
        }}
        .history-meta {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
        .history-date {{ color: var(--text-muted); font-size: 0.9rem; }}
        .history-price {{ font-size: 0.95rem; }}

        .diff-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin: 16px 0;
        }}
        @media (max-width: 768px) {{ .diff-grid {{ grid-template-columns: 1fr; }} }}
        .diff-col {{
            padding: 16px;
            border-radius: 8px;
            border: 1px solid var(--border);
        }}
        .diff-before {{ background: rgba(239, 68, 68, 0.05); border-color: rgba(239, 68, 68, 0.2); }}
        .diff-after {{ background: rgba(16, 185, 129, 0.05); border-color: rgba(16, 185, 129, 0.2); }}
        .diff-header {{ font-weight: 700; font-size: 0.85rem; margin-bottom: 8px; text-transform: uppercase; }}
        .diff-before .diff-header {{ color: #f87171; }}
        .diff-after .diff-header {{ color: #34d399; }}
        .diff-body {{ font-size: 0.95rem; color: #cbd5e1; line-height: 1.5; }}

        .btn {{
            background: var(--primary);
            color: #000;
            font-weight: 700;
            padding: 8px 16px;
            border-radius: 6px;
            border: none;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }}
        .btn-outline {{
            background: transparent;
            color: var(--primary);
            border: 1px solid var(--primary);
        }}
        .btn-outline:hover {{ background: var(--primary-glow); }}
        .btn-sm {{ font-size: 0.8rem; padding: 6px 12px; }}

        .divider {{ border: none; border-top: 1px solid var(--border); margin: 20px 0; }}
    </style>
</head>
<body>
    <header>
        <div class="container header-inner">
            <a href="../index.html" class="nav-back">← Back to Master Dashboard</a>
            <span style="color: var(--text-dim); font-size: 0.85rem;">Columbia-Grade Living Thesis Engine</span>
        </div>
    </header>

    <main class="container">
        <!-- Hero Section -->
        <section class="hero-card">
            <div class="hero-top">
                <div class="ticker-group">
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 6px;">
                        <h1>{stock.ticker}</h1>
                        <span class="badge badge-status">{stock.status_label}</span>
                    </div>
                    <div class="company-sub">{stock.company_name} • Last Reviewed: {stock.last_updated}</div>
                </div>
                <div class="price-group">
                    <div class="price-val">${stock.current_price:.2f}</div>
                    <div class="price-return {'return-pos' if stock.return_pct >= 0 else 'return-neg'}">
                        {stock.return_pct:+.2f}% since Thesis Genesis (${stock.baseline_price:.2f})
                    </div>
                </div>
            </div>

            <!-- Hero Metrics Grid -->
            <div class="hero-metrics-grid">
                <div class="metric-tile">
                    <div class="metric-lbl">Fair Value Est.</div>
                    <div class="metric-val" style="color: var(--primary);">{stock.fair_value_estimate}</div>
                </div>
                <div class="metric-tile">
                    <div class="metric-lbl">Bear Case</div>
                    <div class="metric-val" style="color: var(--danger);">{stock.bear_target}</div>
                </div>
                <div class="metric-tile">
                    <div class="metric-lbl">Base Case</div>
                    <div class="metric-val">{stock.base_target}</div>
                </div>
                <div class="metric-tile">
                    <div class="metric-lbl">Bull Case</div>
                    <div class="metric-val" style="color: var(--success);">{stock.bull_target}</div>
                </div>
                <div class="metric-tile">
                    <div class="metric-lbl">Upper Alert Trigger</div>
                    <div class="metric-val">${stock.upper_alert_threshold:.2f}</div>
                </div>
                <div class="metric-tile">
                    <div class="metric-lbl">Lower Alert Trigger</div>
                    <div class="metric-val">${stock.lower_alert_threshold:.2f}</div>
                </div>
                <div class="metric-tile">
                    <div class="metric-lbl">Next Catalyst</div>
                    <div class="metric-val" style="font-size: 0.95rem;">{stock.next_catalyst_date or 'TBD'}</div>
                </div>
            </div>
        </section>

        <!-- Navigation Tabs -->
        <nav class="tabs-nav">
            <button class="tab-btn active" onclick="switchTab('living-thesis')">📖 Active Living Thesis</button>
            <button class="tab-btn" onclick="switchTab('history')">⏳ History & Evolution ({len(history)} Versions)</button>
        </nav>

        <!-- Active Living Thesis Pane -->
        <div id="pane-living-thesis" class="tab-pane active">
            <article class="thesis-content">
                {active_content}
            </article>
        </div>

        <!-- History & Evolution Pane -->
        <div id="pane-history" class="tab-pane">
            <div class="history-feed">
                {history_cards_html}
            </div>
        </div>
    </main>

    <script>
        function switchTab(tabId) {{
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
            
            if (tabId === 'living-thesis') {{
                document.querySelectorAll('.tab-btn')[0].classList.add('active');
                document.getElementById('pane-living-thesis').classList.add('active');
            }} else {{
                document.querySelectorAll('.tab-btn')[1].classList.add('active');
                document.getElementById('pane-history').classList.add('active');
            }}
        }}

        function toggleHistoryContent(versionNum) {{
            const el = document.getElementById('history-content-' + versionNum);
            if (el.style.display === 'none') {{
                el.style.display = 'block';
            }} else {{
                el.style.display = 'none';
            }}
        }}
    </script>
</body>
</html>
"""


def generate_master_dashboard_html(watchlist: Dict[str, WatchlistStock], alerts: List[AlertItem]) -> str:
    """Generates the master public/index.html dashboard for Vercel with Stocks, Alerts, and Delta Modals."""
    _ensure_dirs()
    
    # Render stock cards
    stocks_cards_html = ""
    for ticker, stock in sorted(watchlist.items(), key=lambda x: x[0]):
        ret_class = "return-pos" if stock.return_pct >= 0 else "return-neg"
        stocks_cards_html += f"""
        <div class="stock-card" data-ticker="{ticker}">
            <div class="stock-card-header">
                <div>
                    <span class="stock-ticker">{stock.ticker}</span>
                    <span class="badge badge-status" style="margin-left: 8px;">{stock.status_label}</span>
                </div>
                <div class="stock-price">${stock.current_price:.2f}</div>
            </div>
            <div class="stock-name">{stock.company_name}</div>
            
            <div class="stock-metrics">
                <div class="sm-tile">
                    <span class="sm-lbl">Return</span>
                    <span class="sm-val {ret_class}">{stock.return_pct:+.2f}%</span>
                </div>
                <div class="sm-tile">
                    <span class="sm-lbl">Fair Value</span>
                    <span class="sm-val" style="color: var(--primary);">{stock.fair_value_estimate}</span>
                </div>
                <div class="sm-tile">
                    <span class="sm-lbl">Trigger Bounds</span>
                    <span class="sm-val">${stock.lower_alert_threshold:.0f} — ${stock.upper_alert_threshold:.0f}</span>
                </div>
                <div class="sm-tile">
                    <span class="sm-lbl">Next Catalyst</span>
                    <span class="sm-val">{stock.next_catalyst_date or 'TBD'}</span>
                </div>
            </div>
            
            <div class="stock-card-footer">
                <span style="font-size: 0.8rem; color: var(--text-dim);">Updated: {stock.last_updated}</span>
                <a href="reports/{stock.ticker}.html" class="btn btn-sm btn-primary">Open Dossier →</a>
            </div>
        </div>
        """

    # Render alerts feed
    alerts_feed_html = ""
    if not alerts:
        alerts_feed_html = '<div class="empty-state">No alerts triggered yet. Surveillance engine is active.</div>'
    else:
        for a in alerts:
            ret_class = "return-pos" if a.price_change_pct >= 0 else "return-neg"
            # Prepare JSON for modal payload
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
            <div class="alert-row" onclick='openAlertModal({safe_payload})'>
                <div class="alert-left">
                    <div class="alert-badge-group">
                        <span class="badge badge-alert">{a.severity}</span>
                        <strong class="alert-ticker">{a.ticker}</strong>
                        <span class="alert-time">🕒 {a.timestamp}</span>
                    </div>
                    <div class="alert-title">{a.title}</div>
                    <div class="alert-preview">{a.what_changes_now[:180]}...</div>
                </div>
                <div class="alert-right">
                    <div class="alert-price">${a.price_at_alert:.2f}</div>
                    <div class="alert-pct {ret_class}">{a.price_change_pct:+.2f}%</div>
                    <button class="btn btn-sm btn-outline" style="margin-top: 8px;">Review Delta →</button>
                </div>
            </div>
            """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Institutional Equity Research & Surveillance Hub</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-base: #090c15;
            --bg-card: #111726;
            --bg-surface: #172034;
            --bg-accent: #1e2c47;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --text-dim: #64748b;
            --primary: #38bdf8;
            --primary-glow: rgba(56, 189, 248, 0.15);
            --success: #10b981;
            --success-glow: rgba(16, 185, 129, 0.15);
            --warning: #f59e0b;
            --danger: #ef4444;
            --border: #1e293b;
            --border-light: #28364f;
            --font-display: 'Outfit', sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg-base);
            color: var(--text-main);
            font-family: var(--font-display);
            min-height: 100vh;
            padding-bottom: 80px;
        }}

        .container {{ max-width: 1200px; margin: 0 auto; padding: 0 24px; }}

        /* Top Nav */
        header {{
            background: rgba(17, 23, 38, 0.85);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 100;
            padding: 18px 0;
        }}
        .header-inner {{ display: flex; justify-content: space-between; align-items: center; }}
        .logo {{ display: flex; align-items: center; gap: 10px; font-size: 1.3rem; font-weight: 800; letter-spacing: -0.5px; }}
        .logo-badge {{ background: var(--primary-glow); color: var(--primary); font-size: 0.75rem; padding: 3px 8px; border-radius: 6px; border: 1px solid var(--primary); }}

        /* Main Tabs */
        .main-tabs {{
            display: flex;
            gap: 16px;
            border-bottom: 1px solid var(--border);
            margin: 32px 0 24px;
        }}
        .tab-btn {{
            background: none;
            border: none;
            color: var(--text-muted);
            font-size: 1.15rem;
            font-weight: 700;
            padding: 12px 24px;
            cursor: pointer;
            position: relative;
            font-family: var(--font-display);
            transition: all 0.2s;
        }}
        .tab-btn:hover {{ color: var(--text-main); }}
        .tab-btn.active {{ color: var(--primary); }}
        .tab-btn.active::after {{
            content: '';
            position: absolute;
            bottom: -1px;
            left: 0;
            right: 0;
            height: 3px;
            background: var(--primary);
            border-radius: 3px 3px 0 0;
            box-shadow: 0 0 12px var(--primary);
        }}

        .tab-pane {{ display: none; }}
        .tab-pane.active {{ display: block; }}

        /* Stock Cards Grid */
        .stocks-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
        }}
        .stock-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 24px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: all 0.2s ease;
        }}
        .stock-card:hover {{
            transform: translateY(-3px);
            border-color: var(--border-light);
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
        }}
        .stock-card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
        .stock-ticker {{ font-size: 1.6rem; font-weight: 800; letter-spacing: -0.5px; }}
        .stock-price {{ font-size: 1.5rem; font-weight: 700; font-family: var(--font-mono); }}
        .stock-name {{ color: var(--text-muted); font-size: 0.95rem; margin-bottom: 20px; }}

        .stock-metrics {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            background: var(--bg-surface);
            padding: 14px;
            border-radius: 10px;
            margin-bottom: 20px;
        }}
        .sm-tile {{ display: flex; flex-direction: column; }}
        .sm-lbl {{ font-size: 0.7rem; text-transform: uppercase; color: var(--text-dim); margin-bottom: 2px; }}
        .sm-val {{ font-size: 0.95rem; font-weight: 700; font-family: var(--font-mono); }}

        .stock-card-footer {{ display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--border); padding-top: 16px; }}

        /* Alerts List */
        .alerts-list {{ display: flex; flex-direction: column; gap: 14px; }}
        .alert-row {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 20px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .alert-row:hover {{
            background: var(--bg-surface);
            border-color: var(--primary);
            transform: translateX(4px);
        }}
        .alert-left {{ flex: 1; }}
        .alert-badge-group {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
        .alert-ticker {{ font-size: 1.1rem; font-weight: 800; }}
        .alert-time {{ font-size: 0.8rem; color: var(--text-dim); }}
        .alert-title {{ font-size: 1.1rem; font-weight: 700; color: var(--text-main); margin-bottom: 6px; }}
        .alert-preview {{ font-size: 0.9rem; color: var(--text-muted); line-height: 1.4; }}
        
        .alert-right {{ text-align: right; min-width: 140px; }}
        .alert-price {{ font-size: 1.3rem; font-weight: 700; font-family: var(--font-mono); }}
        .alert-pct {{ font-size: 0.9rem; font-weight: 600; }}

        /* Badges & Buttons */
        .badge {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 16px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
        }}
        .badge-status {{ background: var(--primary-glow); color: var(--primary); border: 1px solid var(--primary); }}
        .badge-alert {{ background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid #f59e0b; }}

        .btn {{
            padding: 8px 16px;
            border-radius: 8px;
            font-weight: 700;
            font-size: 0.85rem;
            cursor: pointer;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            border: none;
            transition: all 0.2s;
        }}
        .btn-primary {{ background: var(--primary); color: #050811; }}
        .btn-primary:hover {{ background: #7dd3fc; }}
        .btn-outline {{ background: transparent; color: var(--primary); border: 1px solid var(--primary); }}
        .btn-outline:hover {{ background: var(--primary-glow); }}
        .btn-sm {{ padding: 6px 12px; font-size: 0.8rem; }}

        .return-pos {{ color: var(--success); }}
        .return-neg {{ color: var(--danger); }}
        .empty-state {{ text-align: center; padding: 60px 20px; color: var(--text-dim); font-size: 1.1rem; }}

        /* Modal / Popup */
        .modal-overlay {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.75);
            backdrop-filter: blur(8px);
            z-index: 1000;
            display: none;
            justify-content: center;
            align-items: center;
            padding: 24px;
        }}
        .modal-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-light);
            border-radius: 16px;
            max-width: 720px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            padding: 32px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.6);
            position: relative;
        }}
        .modal-close {{
            position: absolute;
            top: 20px;
            right: 20px;
            background: none;
            border: none;
            color: var(--text-dim);
            font-size: 1.5rem;
            cursor: pointer;
        }}
        .modal-close:hover {{ color: var(--text-main); }}
        .diff-modal-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin: 20px 0;
        }}
        @media (max-width: 640px) {{ .diff-modal-grid {{ grid-template-columns: 1fr; }} }}
        .diff-box {{ padding: 16px; border-radius: 8px; border: 1px solid var(--border); }}
        .diff-before {{ background: rgba(239, 68, 68, 0.05); border-color: rgba(239, 68, 68, 0.2); }}
        .diff-after {{ background: rgba(16, 185, 129, 0.05); border-color: rgba(16, 185, 129, 0.2); }}
        .diff-title {{ font-size: 0.8rem; font-weight: 700; text-transform: uppercase; margin-bottom: 6px; }}
        .diff-content {{ font-size: 0.95rem; color: #cbd5e1; line-height: 1.5; }}
    </style>
</head>
<body>
    <header>
        <div class="container header-inner">
            <div class="logo">
                <span>📈 Equity Living Thesis Hub</span>
                <span class="logo-badge">Gemini 3.6 Flash Grounded</span>
            </div>
            <div style="font-size: 0.85rem; color: var(--text-dim);">Autonomous 24/7 Surveillance</div>
        </div>
    </header>

    <main class="container">
        <!-- Main Navigation Tabs -->
        <nav class="main-tabs">
            <button class="tab-btn active" onclick="switchMainTab('stocks')">📊 Active Watchlist ({len(watchlist)})</button>
            <button class="tab-btn" onclick="switchMainTab('alerts')">🚨 Alerts & Trigger Feed ({len(alerts)})</button>
        </nav>

        <!-- STOCKS TAB -->
        <section id="pane-stocks" class="tab-pane active">
            <div class="stocks-grid">
                {stocks_cards_html if watchlist else '<div class="empty-state">No stocks added yet. Use CLI to add your first ticker: <code>poetry run python -m stocks.main add NVDA</code></div>'}
            </div>
        </section>

        <!-- ALERTS TAB -->
        <section id="pane-alerts" class="tab-pane">
            <div class="alerts-list">
                {alerts_feed_html}
            </div>
        </section>
    </main>

    <!-- Interactive Alert Modal (What was before vs What changes now) -->
    <div id="alert-modal" class="modal-overlay" onclick="closeModalOnOutsideClick(event)">
        <div class="modal-card" id="modal-card">
            <button class="modal-close" onclick="closeAlertModal()">✕</button>
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
                <span id="modal-badge" class="badge badge-alert">ALERT</span>
                <strong id="modal-ticker" style="font-size: 1.3rem;">TICKER</strong>
                <span id="modal-time" style="color: var(--text-dim); font-size: 0.85rem;">Timestamp</span>
            </div>
            <h2 id="modal-title" style="font-size: 1.4rem; margin-bottom: 16px;">Alert Headline</h2>
            <div style="font-size: 0.95rem; color: var(--text-muted); margin-bottom: 16px;">
                <strong>Trigger Cause:</strong> <span id="modal-trigger">Trigger description</span>
            </div>

            <div class="diff-modal-grid">
                <div class="diff-box diff-before">
                    <div class="diff-title" style="color: #f87171;">⏪ What Was Before</div>
                    <div id="modal-before" class="diff-content">Previous stance...</div>
                </div>
                <div class="diff-box diff-after">
                    <div class="diff-title" style="color: #34d399;">⚡ What Changes Now</div>
                    <div id="modal-after" class="diff-content">Updated thesis stance...</div>
                </div>
            </div>

            <div style="display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px;">
                <button class="btn btn-outline" onclick="closeAlertModal()">Dismiss</button>
                <a id="modal-report-link" href="#" class="btn btn-primary">Open Full Updated Dossier →</a>
            </div>
        </div>
    </div>

    <script>
        function switchMainTab(tab) {{
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
            
            if (tab === 'stocks') {{
                document.querySelectorAll('.tab-btn')[0].classList.add('active');
                document.getElementById('pane-stocks').classList.add('active');
            }} else {{
                document.querySelectorAll('.tab-btn')[1].classList.add('active');
                document.getElementById('pane-alerts').classList.add('active');
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

        function closeModalOnOutsideClick(event) {{
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
