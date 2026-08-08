"""Ultra-Modern Financial Terminal Dashboard & Living Dossier HTML Generator."""

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
    """Generates the living HTML report for a specific company with modern institutional styling."""
    current_version = history[-1] if history else None
    
    # Format history timeline cards
    history_cards_html = ""
    for v in reversed(history):
        is_current = (v.version == len(history))
        current_badge = '<span class="pill pill-success">Active Stance</span>' if is_current else f'<span class="pill pill-neutral">v{v.version}</span>'
        
        diff_box = ""
        if v.what_was_before or v.what_changes_now:
            diff_box = f"""
            <div class="diff-container">
                <div class="diff-card diff-before">
                    <div class="diff-tag">PREVIOUS STANCE</div>
                    <div class="diff-text">{v.what_was_before or 'Initial Genesis baseline.'}</div>
                </div>
                <div class="diff-card diff-after">
                    <div class="diff-tag">WHAT CHANGED</div>
                    <div class="diff-text">{v.what_changes_now or v.summary_of_change}</div>
                </div>
            </div>
            """
            
        history_cards_html += f"""
        <div class="history-item {'history-active' if is_current else ''}">
            <div class="history-item-top">
                <div class="history-meta-left">
                    {current_badge}
                    <span class="history-date">{v.date}</span>
                    <span class="history-price-tag">Price: <strong>${v.price_at_version:.2f}</strong></span>
                    <span class="pill pill-status">{v.status_label}</span>
                </div>
                <button class="btn btn-ghost" onclick="toggleSnapshot({v.version})">Expand Snapshot ▾</button>
            </div>
            <div class="history-body">
                <p><strong>Thesis Shift:</strong> {v.summary_of_change}</p>
                {diff_box}
                <div id="snapshot-{v.version}" class="snapshot-drawer" style="display: none;">
                    <div class="snapshot-content">
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
    <title>{ticker} — Institutional Living Dossier</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&family=Lora:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-page: #08090d;
            --bg-card: #0f121a;
            --bg-card-hover: #141924;
            --bg-elevated: #181f2e;
            --bg-accent: #1e283d;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --primary: #38bdf8;
            --primary-rgb: 56, 189, 248;
            --success: #10b981;
            --success-rgb: 16, 185, 129;
            --danger: #f43f5e;
            --warning: #fbbf24;
            --border: #1e2638;
            --border-highlight: #2a364f;
            --font-sans: 'Plus Jakarta Sans', -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
            --font-serif: 'Lora', Georgia, serif;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg-page);
            color: var(--text-primary);
            font-family: var(--font-sans);
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
            padding-bottom: 100px;
        }}

        .container {{ max-width: 1100px; margin: 0 auto; padding: 0 24px; }}

        /* Top Nav */
        nav.top-nav {{
            background: rgba(8, 9, 13, 0.85);
            backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 50;
            padding: 14px 0;
        }}
        .nav-content {{ display: flex; justify-content: space-between; align-items: center; }}
        .back-link {{
            color: var(--primary);
            text-decoration: none;
            font-size: 0.9rem;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: transform 0.15s;
        }}
        .back-link:hover {{ transform: translateX(-3px); }}

        /* Hero Header */
        .hero {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 36px;
            margin: 32px 0 28px;
            box-shadow: 0 12px 36px rgba(0,0,0,0.4);
        }}
        .hero-header {{ display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 20px; }}
        .hero-left h1 {{ font-size: 2.5rem; font-weight: 800; letter-spacing: -0.03em; }}
        .hero-company {{ color: var(--text-secondary); font-size: 1.1rem; margin-top: 4px; }}

        .hero-price-block {{ text-align: right; }}
        .hero-price {{ font-size: 2.6rem; font-weight: 800; font-family: var(--font-mono); letter-spacing: -0.02em; }}
        .hero-return {{ font-size: 0.95rem; font-weight: 600; font-family: var(--font-mono); margin-top: 2px; }}

        .pills-group {{ display: flex; align-items: center; gap: 8px; margin-top: 12px; flex-wrap: wrap; }}
        .pill {{
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            display: inline-flex;
            align-items: center;
        }}
        .pill-status {{ background: rgba(var(--primary-rgb), 0.12); color: var(--primary); border: 1px solid rgba(var(--primary-rgb), 0.3); }}
        .pill-success {{ background: rgba(var(--success-rgb), 0.12); color: var(--success); border: 1px solid rgba(var(--success-rgb), 0.3); }}
        .pill-neutral {{ background: var(--bg-elevated); color: var(--text-muted); border: 1px solid var(--border); }}

        /* Valuation & Metric Ribbon */
        .metric-ribbon {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 12px;
            margin-top: 28px;
            padding-top: 24px;
            border-top: 1px solid var(--border);
        }}
        .metric-box {{
            background: var(--bg-elevated);
            padding: 14px 16px;
            border-radius: 12px;
            border: 1px solid var(--border);
        }}
        .metric-box-label {{ font-size: 0.7rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; letter-spacing: 0.04em; }}
        .metric-box-val {{ font-size: 1.15rem; font-weight: 700; color: var(--text-primary); font-family: var(--font-mono); margin-top: 4px; }}

        /* Tabs */
        .tab-bar {{
            display: flex;
            gap: 8px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 28px;
        }}
        .tab-button {{
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 1rem;
            font-weight: 600;
            padding: 12px 20px;
            cursor: pointer;
            position: relative;
            font-family: var(--font-sans);
            transition: color 0.15s;
        }}
        .tab-button:hover {{ color: var(--text-primary); }}
        .tab-button.tab-active {{ color: var(--primary); }}
        .tab-button.tab-active::after {{
            content: '';
            position: absolute;
            bottom: -1px;
            left: 0; right: 0;
            height: 2px;
            background: var(--primary);
            box-shadow: 0 0 12px var(--primary);
        }}

        .tab-panel {{ display: none; }}
        .tab-panel.panel-active {{ display: block; }}

        /* Editorial Living Thesis Container */
        .thesis-container {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 44px;
        }}
        .thesis-container h2 {{
            font-size: 1.4rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            color: var(--primary);
            margin: 36px 0 16px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .thesis-container h2:first-of-type {{ margin-top: 0; }}
        .thesis-container h3 {{ font-size: 1.15rem; font-weight: 700; color: #e2e8f0; margin: 24px 0 12px; }}
        .thesis-container p {{
            font-family: var(--font-serif);
            font-size: 1.12rem;
            line-height: 1.85;
            color: #cbd5e1;
            margin-bottom: 20px;
        }}
        .thesis-container ul, .thesis-container ol {{
            font-family: var(--font-serif);
            font-size: 1.08rem;
            line-height: 1.85;
            color: #cbd5e1;
            margin: 0 0 22px 24px;
        }}
        .thesis-container li {{ margin-bottom: 8px; }}

        .thesis-container table {{
            width: 100%;
            border-collapse: collapse;
            margin: 28px 0;
            background: var(--bg-elevated);
            border-radius: 10px;
            overflow: hidden;
            border: 1px solid var(--border);
        }}
        .thesis-container th, .thesis-container td {{
            padding: 12px 18px;
            text-align: left;
            border-bottom: 1px solid var(--border);
            font-size: 0.92rem;
        }}
        .thesis-container th {{ background: var(--bg-accent); color: var(--text-primary); font-weight: 700; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; }}
        .thesis-container blockquote {{
            background: var(--bg-elevated);
            border-left: 3px solid var(--primary);
            padding: 18px 24px;
            border-radius: 0 12px 12px 0;
            margin: 24px 0;
            font-family: var(--font-serif);
            font-style: italic;
            color: #e2e8f0;
        }}

        /* History Tab */
        .history-item {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 28px;
            margin-bottom: 20px;
            transition: border-color 0.2s;
        }}
        .history-active {{ border-color: rgba(var(--success-rgb), 0.5); }}
        .history-item-top {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }}
        .history-meta-left {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
        .history-date {{ color: var(--text-secondary); font-size: 0.9rem; }}
        .history-price-tag {{ font-family: var(--font-mono); font-size: 0.95rem; }}

        .diff-container {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin: 20px 0;
        }}
        @media (max-width: 768px) {{ .diff-container {{ grid-template-columns: 1fr; }} }}
        .diff-card {{
            padding: 18px;
            border-radius: 12px;
            border: 1px solid var(--border);
        }}
        .diff-before {{ background: rgba(244, 63, 94, 0.04); border-color: rgba(244, 63, 94, 0.2); }}
        .diff-after {{ background: rgba(var(--success-rgb), 0.04); border-color: rgba(var(--success-rgb), 0.2); }}
        .diff-tag {{ font-size: 0.7rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }}
        .diff-before .diff-tag {{ color: #fb7185; }}
        .diff-after .diff-tag {{ color: #34d399; }}
        .diff-text {{ font-size: 0.95rem; color: #cbd5e1; line-height: 1.55; }}

        .btn {{
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s;
            border: none;
        }}
        .btn-ghost {{ background: var(--bg-elevated); color: var(--text-primary); border: 1px solid var(--border); }}
        .btn-ghost:hover {{ background: var(--bg-accent); border-color: var(--border-highlight); }}

        .snapshot-drawer {{ margin-top: 20px; padding-top: 20px; border-top: 1px solid var(--border); }}

        .pos {{ color: var(--success); }}
        .neg {{ color: var(--danger); }}
    </style>
</head>
<body>
    <nav class="top-nav">
        <div class="container nav-content">
            <a href="../index.html" class="back-link">← Master Terminal</a>
            <span style="font-size: 0.8rem; color: var(--text-muted); font-family: var(--font-mono);">RESEARCH DOSSIER // {ticker}</span>
        </div>
    </nav>

    <main class="container">
        <!-- Hero Card -->
        <section class="hero">
            <div class="hero-header">
                <div class="hero-left">
                    <div style="display: flex; align-items: center; gap: 14px;">
                        <h1>{stock.ticker}</h1>
                        <span class="pill pill-status">{stock.status_label}</span>
                    </div>
                    <div class="hero-company">{stock.company_name} • Updated {stock.last_updated}</div>
                </div>
                <div class="hero-price-block">
                    <div class="hero-price">${stock.current_price:.2f}</div>
                    <div class="hero-return {'pos' if stock.return_pct >= 0 else 'neg'}">
                        {stock.return_pct:+.2f}% vs Genesis (${stock.baseline_price:.2f})
                    </div>
                </div>
            </div>

            <!-- Metric Ribbon -->
            <div class="metric-ribbon">
                <div class="metric-box">
                    <div class="metric-box-label">Fair Value Est.</div>
                    <div class="metric-box-val" style="color: var(--primary);">{stock.fair_value_estimate}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-box-label">Bear Target</div>
                    <div class="metric-box-val" style="color: var(--danger);">{stock.bear_target}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-box-label">Base Target</div>
                    <div class="metric-box-val">{stock.base_target}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-box-label">Bull Target</div>
                    <div class="metric-box-val" style="color: var(--success);">{stock.bull_target}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-box-label">Upper Alert Trigger</div>
                    <div class="metric-box-val">${stock.upper_alert_threshold:.2f}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-box-label">Lower Alert Trigger</div>
                    <div class="metric-box-val">${stock.lower_alert_threshold:.2f}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-box-label">Catalyst Timeline</div>
                    <div class="metric-box-val" style="font-size: 0.9rem;">{stock.next_catalyst_date or 'TBD'}</div>
                </div>
            </div>
        </section>

        <!-- Navigation Tabs -->
        <div class="tab-bar">
            <button class="tab-button tab-active" onclick="switchView('thesis')">📖 Active Living Thesis</button>
            <button class="tab-button" onclick="switchView('history')">⏳ Changelog & Evolution ({len(history)})</button>
        </div>

        <!-- Active Living Thesis Pane -->
        <div id="panel-thesis" class="tab-panel panel-active">
            <article class="thesis-container">
                {active_content}
            </article>
        </div>

        <!-- History & Evolution Pane -->
        <div id="panel-history" class="tab-panel">
            {history_cards_html}
        </div>
    </main>

    <script>
        function switchView(tabName) {{
            document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('tab-active'));
            document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.remove('panel-active'));
            
            if (tabName === 'thesis') {{
                document.querySelectorAll('.tab-button')[0].classList.add('tab-active');
                document.getElementById('panel-thesis').classList.add('panel-active');
            }} else {{
                document.querySelectorAll('.tab-button')[1].classList.add('tab-active');
                document.getElementById('panel-history').classList.add('panel-active');
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
    """Generates the master public/index.html terminal dashboard for Vercel."""
    _ensure_dirs()
    
    # Render stock cards
    stocks_cards_html = ""
    for ticker, stock in sorted(watchlist.items(), key=lambda x: x[0]):
        ret_class = "pos" if stock.return_pct >= 0 else "neg"
        stocks_cards_html += f"""
        <div class="stock-item" onclick="location.href='reports/{stock.ticker}.html'">
            <div class="stock-item-head">
                <div>
                    <span class="stock-symbol">{stock.ticker}</span>
                    <span class="pill pill-status" style="margin-left: 8px;">{stock.status_label}</span>
                </div>
                <div class="stock-price-val">${stock.current_price:.2f}</div>
            </div>
            <div class="stock-full-name">{stock.company_name}</div>
            
            <div class="stock-stat-grid">
                <div class="stat-cell">
                    <span class="stat-label">Return</span>
                    <span class="stat-value {ret_class}">{stock.return_pct:+.2f}%</span>
                </div>
                <div class="stat-cell">
                    <span class="stat-label">Fair Value</span>
                    <span class="stat-value" style="color: var(--primary);">{stock.fair_value_estimate}</span>
                </div>
                <div class="stat-cell">
                    <span class="stat-label">Trigger Bounds</span>
                    <span class="stat-value">${stock.lower_alert_threshold:.0f} — ${stock.upper_alert_threshold:.0f}</span>
                </div>
                <div class="stat-cell">
                    <span class="stat-label">Next Catalyst</span>
                    <span class="stat-value">{stock.next_catalyst_date or 'TBD'}</span>
                </div>
            </div>
            
            <div class="stock-card-foot">
                <span class="stock-updated-tag">Updated {stock.last_updated}</span>
                <span class="open-link">Read Dossier →</span>
            </div>
        </div>
        """

    # Render alerts feed
    alerts_feed_html = ""
    if not alerts:
        alerts_feed_html = """
        <div class="empty-feed">
            <div style="font-size: 2rem; margin-bottom: 8px;">🛡️</div>
            <div style="font-weight: 700; font-size: 1.1rem; color: var(--text-primary);">All Positions Stable</div>
            <div style="color: var(--text-muted); font-size: 0.9rem; margin-top: 4px;">No critical threshold breaches or catalyst alerts triggered. Surveillance engine is active.</div>
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
            <div class="alert-card" onclick='openAlertModal({safe_payload})'>
                <div class="alert-card-left">
                    <div class="alert-tags">
                        <span class="pill pill-alert">{a.severity}</span>
                        <strong class="alert-ticker-name">{a.ticker}</strong>
                        <span class="alert-timestamp">{a.timestamp}</span>
                    </div>
                    <h3 class="alert-headline">{a.title}</h3>
                    <p class="alert-blurb">{a.what_changes_now[:200]}...</p>
                </div>
                <div class="alert-card-right">
                    <div class="alert-price-tag">${a.price_at_alert:.2f}</div>
                    <div class="alert-change-pct {ret_class}">{a.price_change_pct:+.2f}%</div>
                    <span class="alert-inspect-btn">Inspect Delta →</span>
                </div>
            </div>
            """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Institutional Equity Research Hub</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-page: #08090d;
            --bg-card: #0f121a;
            --bg-card-hover: #141a26;
            --bg-elevated: #171f2e;
            --bg-accent: #1e293d;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --primary: #38bdf8;
            --primary-rgb: 56, 189, 248;
            --success: #10b981;
            --danger: #f43f5e;
            --warning: #fbbf24;
            --border: #1e2638;
            --border-highlight: #2a364f;
            --font-sans: 'Plus Jakarta Sans', -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg-page);
            color: var(--text-primary);
            font-family: var(--font-sans);
            min-height: 100vh;
            -webkit-font-smoothing: antialiased;
            padding-bottom: 100px;
        }}

        .container {{ max-width: 1180px; margin: 0 auto; padding: 0 24px; }}

        /* Top Header */
        header.terminal-nav {{
            background: rgba(8, 9, 13, 0.85);
            backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 50;
            padding: 16px 0;
        }}
        .header-wrap {{ display: flex; justify-content: space-between; align-items: center; }}
        .brand {{ display: flex; align-items: center; gap: 10px; font-size: 1.25rem; font-weight: 800; letter-spacing: -0.02em; }}
        .brand-badge {{
            background: rgba(var(--primary-rgb), 0.12);
            color: var(--primary);
            font-size: 0.72rem;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 6px;
            border: 1px solid rgba(var(--primary-rgb), 0.3);
            text-transform: uppercase;
        }}
        .status-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--success); box-shadow: 0 0 8px var(--success); margin-right: 6px; }}

        /* Navigation Tabs */
        .main-nav-tabs {{
            display: flex;
            gap: 8px;
            border-bottom: 1px solid var(--border);
            margin: 36px 0 28px;
        }}
        .nav-tab-btn {{
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 1.05rem;
            font-weight: 700;
            padding: 12px 24px;
            cursor: pointer;
            position: relative;
            font-family: var(--font-sans);
            transition: all 0.15s;
        }}
        .nav-tab-btn:hover {{ color: var(--text-primary); }}
        .nav-tab-btn.active {{ color: var(--primary); }}
        .nav-tab-btn.active::after {{
            content: '';
            position: absolute;
            bottom: -1px;
            left: 0; right: 0;
            height: 2px;
            background: var(--primary);
            box-shadow: 0 0 12px var(--primary);
        }}

        .tab-section {{ display: none; }}
        .tab-section.active {{ display: block; }}

        /* Stock Cards Grid */
        .stock-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
        }}
        .stock-item {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 24px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        .stock-item:hover {{
            background: var(--bg-card-hover);
            border-color: var(--border-highlight);
            transform: translateY(-3px);
            box-shadow: 0 12px 30px rgba(0,0,0,0.4);
        }}
        .stock-item-head {{ display: flex; justify-content: space-between; align-items: center; }}
        .stock-symbol {{ font-size: 1.6rem; font-weight: 800; letter-spacing: -0.02em; }}
        .stock-price-val {{ font-size: 1.5rem; font-weight: 700; font-family: var(--font-mono); }}
        .stock-full-name {{ color: var(--text-secondary); font-size: 0.9rem; margin: 4px 0 20px; }}

        .stock-stat-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            background: var(--bg-elevated);
            padding: 14px;
            border-radius: 12px;
            margin-bottom: 20px;
        }}
        .stat-cell {{ display: flex; flex-direction: column; }}
        .stat-label {{ font-size: 0.68rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; }}
        .stat-value {{ font-size: 0.95rem; font-weight: 700; font-family: var(--font-mono); margin-top: 2px; }}

        .stock-card-foot {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-top: 1px solid var(--border);
            padding-top: 16px;
        }}
        .stock-updated-tag {{ font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono); }}
        .open-link {{ font-size: 0.85rem; font-weight: 700; color: var(--primary); }}

        /* Alerts Feed */
        .alerts-feed {{ display: flex; flex-direction: column; gap: 14px; }}
        .alert-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 22px 26px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 24px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .alert-card:hover {{
            background: var(--bg-card-hover);
            border-color: var(--primary);
            transform: translateX(4px);
        }}
        .alert-card-left {{ flex: 1; }}
        .alert-tags {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
        .alert-ticker-name {{ font-size: 1.1rem; font-weight: 800; }}
        .alert-timestamp {{ font-size: 0.8rem; color: var(--text-muted); font-family: var(--font-mono); }}
        .alert-headline {{ font-size: 1.1rem; font-weight: 700; color: var(--text-primary); margin-bottom: 6px; }}
        .alert-blurb {{ font-size: 0.9rem; color: var(--text-secondary); line-height: 1.45; }}

        .alert-card-right {{ text-align: right; min-width: 140px; }}
        .alert-price-tag {{ font-size: 1.4rem; font-weight: 700; font-family: var(--font-mono); }}
        .alert-change-pct {{ font-size: 0.9rem; font-weight: 600; font-family: var(--font-mono); }}
        .alert-inspect-btn {{ font-size: 0.8rem; font-weight: 700; color: var(--primary); display: inline-block; margin-top: 6px; }}

        /* Badges & Pills */
        .pill {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 9999px;
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .pill-status {{ background: rgba(var(--primary-rgb), 0.12); color: var(--primary); border: 1px solid rgba(var(--primary-rgb), 0.3); }}
        .pill-alert {{ background: rgba(251, 191, 36, 0.12); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.3); }}

        .pos {{ color: var(--success); }}
        .neg {{ color: var(--danger); }}
        .empty-feed {{
            text-align: center;
            background: var(--bg-card);
            border: 1px dashed var(--border);
            border-radius: 16px;
            padding: 60px 24px;
            margin: 20px 0;
        }}

        /* Modal Overlay */
        .modal-shade {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.8);
            backdrop-filter: blur(12px);
            z-index: 1000;
            display: none;
            justify-content: center;
            align-items: center;
            padding: 24px;
        }}
        .modal-body-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-highlight);
            border-radius: 20px;
            max-width: 760px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            padding: 36px;
            box-shadow: 0 24px 60px rgba(0,0,0,0.7);
            position: relative;
        }}
        .modal-x {{
            position: absolute;
            top: 24px; right: 24px;
            background: none;
            border: none;
            color: var(--text-muted);
            font-size: 1.4rem;
            cursor: pointer;
        }}
        .modal-x:hover {{ color: var(--text-primary); }}

        .diff-modal-wrap {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin: 24px 0;
        }}
        @media (max-width: 640px) {{ .diff-modal-wrap {{ grid-template-columns: 1fr; }} }}
        .diff-side {{ padding: 18px; border-radius: 12px; border: 1px solid var(--border); }}
        .side-before {{ background: rgba(244, 63, 94, 0.04); border-color: rgba(244, 63, 94, 0.2); }}
        .side-after {{ background: rgba(var(--success-rgb), 0.04); border-color: rgba(var(--success-rgb), 0.2); }}
        .side-heading {{ font-size: 0.72rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }}
        .side-before .side-heading {{ color: #fb7185; }}
        .side-after .side-heading {{ color: #34d399; }}
        .side-text {{ font-size: 0.95rem; color: #cbd5e1; line-height: 1.55; }}

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
        .btn-primary {{ background: var(--primary); color: #08090d; }}
        .btn-primary:hover {{ background: #7dd3fc; }}
        .btn-outline {{ background: var(--bg-elevated); color: var(--text-primary); border: 1px solid var(--border); }}
        .btn-outline:hover {{ background: var(--bg-accent); }}
    </style>
</head>
<body>
    <header class="terminal-nav">
        <div class="container header-wrap">
            <div class="brand">
                <span class="status-dot"></span>
                <span>Institutional Equity Surveillance Hub</span>
                <span class="brand-badge">Gemini 3.6 Flash</span>
            </div>
            <div style="font-size: 0.8rem; color: var(--text-muted); font-family: var(--font-mono);">24/7 ACTIVE SURVEILLANCE</div>
        </div>
    </header>

    <main class="container">
        <!-- Navigation Tabs -->
        <div class="main-nav-tabs">
            <button class="nav-tab-btn active" onclick="switchMainTab('stocks')">📊 Active Portfolio & Watchlist ({len(watchlist)})</button>
            <button class="nav-tab-btn" onclick="switchMainTab('alerts')">🚨 Critical Alerts ({len(alerts)})</button>
        </div>

        <!-- STOCKS TAB -->
        <section id="section-stocks" class="tab-section active">
            <div class="stock-grid">
                {stocks_cards_html if watchlist else '<div class="empty-feed">No stocks tracked yet. Add your first ticker: <code>poetry run python -m stocks.main add NVDA</code></div>'}
            </div>
        </section>

        <!-- ALERTS TAB -->
        <section id="section-alerts" class="tab-section">
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
                <strong id="modal-ticker" style="font-size: 1.3rem;">TICKER</strong>
                <span id="modal-time" style="color: var(--text-muted); font-size: 0.85rem; font-family: var(--font-mono);">Timestamp</span>
            </div>
            <h2 id="modal-title" style="font-size: 1.4rem; margin-bottom: 12px; letter-spacing: -0.02em;">Alert Headline</h2>
            <div style="font-size: 0.92rem; color: var(--text-secondary); margin-bottom: 20px;">
                <strong>Trigger Cause:</strong> <span id="modal-trigger">Reason</span>
            </div>

            <div class="diff-modal-wrap">
                <div class="diff-side side-before">
                    <div class="side-heading">⏪ What Was Before</div>
                    <div id="modal-before" class="side-text">Previous stance...</div>
                </div>
                <div class="diff-side side-after">
                    <div class="side-heading">⚡ What Changes Now</div>
                    <div id="modal-after" class="side-text">Updated thesis...</div>
                </div>
            </div>

            <div style="display: flex; justify-content: flex-end; gap: 12px; margin-top: 28px;">
                <button class="btn btn-outline" onclick="closeAlertModal()">Dismiss</button>
                <a id="modal-report-link" href="#" class="btn btn-primary">Open Full Updated Dossier →</a>
            </div>
        </div>
    </div>

    <script>
        function switchMainTab(tab) {{
            document.querySelectorAll('.nav-tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-section').forEach(sec => sec.classList.remove('active'));
            
            if (tab === 'stocks') {{
                document.querySelectorAll('.nav-tab-btn')[0].classList.add('active');
                document.getElementById('section-stocks').classList.add('active');
            }} else {{
                document.querySelectorAll('.nav-tab-btn')[1].classList.add('active');
                document.getElementById('section-alerts').classList.add('active');
            }}
        }}

        function openAlertModal(payload) {{
            document.getElementById('modal-ticker').innerText = payload.ticker;
            document.getElementById('modal-title').innerText = payload.title;
            document.getElementById('modal-time').innerText = payload.timestamp;
            document.getElementById('modal-badge').innerText = payload.severity;
            document.getElementById('modal-trigger').innerText = payload.trigger_reason;
            document.getElementById('modal-before').innerText = payload.what_was_before || 'Initial Genesis baseline';
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
