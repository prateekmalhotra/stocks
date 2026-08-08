"""Minimalist, Soothing Financial Research Dashboard & Due Diligence Dossier."""

import json
import re
from pathlib import Path
from typing import List, Dict, Any
from stocks.models import WatchlistStock, AlertItem, ThesisVersion
from stocks.data_store import load_watchlist, load_alerts, load_thesis_history
from stocks.tracker import fetch_historical_chart_data

PUBLIC_DIR = Path("public")
REPORTS_DIR = PUBLIC_DIR / "reports"


def _ensure_dirs():
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def format_labels_pills(labels: List[str]) -> str:
    """Formats up to 3 labels (max 2 words each) into clean, elegant pills."""
    if not labels:
        return '<span class="pill pill-neutral">Active</span>'
    
    html = ""
    for i, lbl in enumerate(labels[:3]):
        words = [w for w in lbl.replace("/", " ").replace("-", " ").replace("&", " ").split() if w.strip()]
        if not words:
            continue
        short_lbl = " ".join(words[:2]).title()
        pill_cls = "pill-active" if i == 0 else "pill-neutral"
        html += f'<span class="pill {pill_cls}">{short_lbl}</span> '
    return html.strip() or '<span class="pill pill-neutral">Active</span>'


def build_native_svg_chart(ticker: str, current_price: float) -> str:
    """Builds a lightweight, native interactive SVG area chart with mouse hover tracking."""
    points = fetch_historical_chart_data(ticker, "1y")
    if not points or len(points) < 2:
        points = [
            {"date": "Start", "price": round(current_price * 0.92, 2)},
            {"date": "Mid", "price": round(current_price * 0.97, 2)},
            {"date": "Today", "price": round(current_price, 2)}
        ]

    prices = [p["price"] for p in points]
    min_p = min(prices)
    max_p = max(prices)
    price_range = max(max_p - min_p, 0.01)

    width = 900
    height = 260
    padding_x = 20
    padding_y = 25

    svg_pts = []
    n = len(points)
    for i, p in enumerate(points):
        x = padding_x + (i / (n - 1)) * (width - 2 * padding_x)
        y = height - padding_y - ((p["price"] - min_p) / price_range) * (height - 2 * padding_y)
        svg_pts.append((round(x, 1), round(y, 1)))

    line_path_d = "M " + " L ".join(f"{x},{y}" for x, y in svg_pts)
    first_x, first_y = svg_pts[0]
    last_x, last_y = svg_pts[-1]
    area_path_d = f"{line_path_d} L {last_x},{height} L {first_x},{height} Z"

    pts_json = json.dumps(points)
    svg_pts_json = json.dumps(svg_pts)

    return f"""
    <div class="native-chart-wrap" id="chart-container">
        <div id="chart-tooltip" class="chart-tooltip">
            <span id="tooltip-date">---</span> • <strong id="tooltip-price">$0.00</strong>
        </div>
        <svg id="interactive-svg" viewBox="0 0 {width} {height}" preserveAspectRatio="none" class="chart-svg">
            <defs>
                <linearGradient id="area-grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color="#C99A75" stop-opacity="0.20" />
                    <stop offset="100%" stop-color="#C99A75" stop-opacity="0.0" />
                </linearGradient>
            </defs>
            
            <line x1="{padding_x}" y1="{padding_y}" x2="{width - padding_x}" y2="{padding_y}" stroke="rgba(230,220,205,0.04)" stroke-width="1" />
            <line x1="{padding_x}" y1="{height/2}" x2="{width - padding_x}" y2="{height/2}" stroke="rgba(230,220,205,0.04)" stroke-width="1" />
            <line x1="{padding_x}" y1="{height - padding_y}" x2="{width - padding_x}" y2="{height - padding_y}" stroke="rgba(230,220,205,0.04)" stroke-width="1" />

            <path d="{area_path_d}" fill="url(#area-grad)" />
            <path d="{line_path_d}" fill="none" stroke="#C99A75" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />

            <line id="crosshair-line" x1="0" y1="{padding_y}" x2="0" y2="{height - padding_y}" stroke="rgba(201,154,117,0.35)" stroke-width="1" stroke-dasharray="3 3" style="display: none;" />
            <circle id="hover-dot" r="4" fill="#C99A75" stroke="#1E1D1B" stroke-width="2" style="display: none;" />
        </svg>
        <div class="chart-labels">
            <span>{points[0]['date']} (${min_p:.2f})</span>
            <span>1-Year Range</span>
            <span>{points[-1]['date']} (${points[-1]['price']:.2f})</span>
        </div>
    </div>

    <script>
    (function() {{
        const rawPoints = {pts_json};
        const svgCoords = {svg_pts_json};
        const container = document.getElementById('chart-container');
        const svg = document.getElementById('interactive-svg');
        const tooltip = document.getElementById('chart-tooltip');
        const tooltipDate = document.getElementById('tooltip-date');
        const tooltipPrice = document.getElementById('tooltip-price');
        const crosshair = document.getElementById('crosshair-line');
        const dot = document.getElementById('hover-dot');

        if (!container || !rawPoints.length) return;

        function updateHover(e) {{
            const rect = svg.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const pct = Math.max(0, Math.min(1, mouseX / rect.width));
            const idx = Math.round(pct * (rawPoints.length - 1));
            
            const pt = rawPoints[idx];
            const coord = svgCoords[idx];
            if (!pt || !coord) return;

            crosshair.setAttribute('x1', coord[0]);
            crosshair.setAttribute('x2', coord[0]);
            crosshair.style.display = 'block';

            dot.setAttribute('cx', coord[0]);
            dot.setAttribute('cy', coord[1]);
            dot.style.display = 'block';

            tooltipDate.innerText = pt.date;
            tooltipPrice.innerText = '$' + pt.price.toFixed(2);
            tooltip.style.display = 'block';
            
            const tooltipX = (coord[0] / {width}) * rect.width;
            tooltip.style.left = Math.max(10, Math.min(rect.width - 150, tooltipX - 70)) + 'px';
        }}

        function hideHover() {{
            crosshair.style.display = 'none';
            dot.style.display = 'none';
            tooltip.style.display = 'none';
        }}

        container.addEventListener('mousemove', updateHover);
        container.addEventListener('mouseleave', hideHover);
        container.addEventListener('touchstart', (e) => {{ if (e.touches.length) updateHover(e.touches[0]); }}, {{passive: true}});
        container.addEventListener('touchmove', (e) => {{ if (e.touches.length) updateHover(e.touches[0]); }}, {{passive: true}});
        container.addEventListener('touchend', hideHover);
    }})();
    </script>
    """


def generate_company_dossier_html(ticker: str, stock: WatchlistStock, history: List[ThesisVersion]) -> str:
    """Generates a clean, soothing, book-like investment due diligence dossier."""
    current_version = history[-1] if history else None
    labels_html = format_labels_pills(stock.labels or [stock.status_label])

    # Format history timeline cards
    history_cards_html = ""
    for v in reversed(history):
        is_current = (v.version == len(history))
        v_labels_html = format_labels_pills(v.labels or [v.status_label])

        diff_box = ""
        if v.what_was_before or v.what_changes_now:
            diff_box = f"""
            <div class="diff-grid">
                <div class="diff-box diff-prev">
                    <div class="diff-label">PREVIOUS THESIS</div>
                    <div class="diff-text">{v.what_was_before or 'Genesis baseline initiated.'}</div>
                </div>
                <div class="diff-box diff-now">
                    <div class="diff-label">THESIS EVOLUTION</div>
                    <div class="diff-text">{v.what_changes_now or v.summary_of_change}</div>
                </div>
            </div>
            """
            
        history_cards_html += f"""
        <div class="history-entry {'history-entry-active' if is_current else ''}">
            <div class="history-top">
                <div class="history-tags">
                    <span class="history-time">{v.date}</span>
                    <span class="history-price">${v.price_at_version:.2f}</span>
                    {v_labels_html}
                </div>
                <button class="btn btn-subtle" onclick="toggleSnapshot({v.version})">Read Snapshot ▾</button>
            </div>
            <div class="history-content">
                <p class="history-shift-desc">{v.summary_of_change}</p>
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
    chart_html = build_native_svg_chart(ticker, stock.current_price)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{ticker} — Investment Memo</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com">
    <link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;1,6..72,400&family=Plus+Jakarta+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-canvas: #161514;
            --bg-panel: #1E1D1B;
            --bg-subpanel: #262522;
            --bg-hover: #2C2A26;
            --text-title: #E8E3DA;
            --text-body: #C9C4BA;
            --text-secondary: #948F85;
            --text-dim: #6B665E;
            --accent-warm: #C99A75;
            --accent-green: #7D9D81;
            --accent-red: #C4726C;
            --border-color: rgba(230, 220, 205, 0.07);
            --border-focus: rgba(230, 220, 205, 0.14);
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
            padding-bottom: 120px;
        }}

        .container {{ max-width: 960px; margin: 0 auto; padding: 0 24px; }}

        /* Top Nav */
        nav.nav-bar {{
            background: rgba(22, 21, 20, 0.92);
            backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 100;
            padding: 16px 0;
        }}
        .nav-inner {{ display: flex; justify-content: space-between; align-items: center; }}
        .nav-back {{
            color: var(--accent-warm);
            text-decoration: none;
            font-family: var(--font-sans);
            font-size: 0.88rem;
            font-weight: 500;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: color 0.15s;
        }}
        .nav-back:hover {{ color: #DDB495; }}

        /* Hero Deck */
        .hero-deck {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 36px 40px;
            margin: 32px 0 28px;
        }}

        .hero-top-row {{ display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 20px; }}
        .ticker-symbol {{
            font-family: var(--font-serif);
            font-size: 2.8rem;
            font-weight: 500;
            letter-spacing: -0.02em;
            color: var(--text-title);
        }}
        .company-meta {{ color: var(--text-secondary); font-size: 1.05rem; font-style: italic; margin-top: 2px; }}

        .price-callout {{ text-align: right; }}
        .price-number {{ font-size: 2.6rem; font-weight: 500; font-family: var(--font-mono); color: var(--text-title); }}
        .price-sub {{ font-size: 0.88rem; font-family: var(--font-mono); margin-top: 2px; }}

        /* Native SVG Area Chart */
        .native-chart-wrap {{
            margin-top: 28px;
            background: #191816;
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 16px 20px 12px;
            position: relative;
            user-select: none;
        }}
        .chart-svg {{ width: 100%; height: 220px; display: block; overflow: visible; }}
        .chart-tooltip {{
            position: absolute;
            top: 14px;
            left: 20px;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-focus);
            color: var(--text-title);
            font-family: var(--font-sans);
            font-size: 0.8rem;
            padding: 5px 12px;
            border-radius: 6px;
            pointer-events: none;
            display: none;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }}
        .chart-labels {{
            display: flex;
            justify-content: space-between;
            font-size: 0.72rem;
            color: var(--text-dim);
            font-family: var(--font-sans);
            margin-top: 8px;
            padding-top: 6px;
            border-top: 1px solid var(--border-color);
        }}

        /* Key Metrics Grid */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 10px;
            margin-top: 24px;
        }}
        .metric-cell {{
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 14px 16px;
        }}
        .metric-label {{ font-size: 0.68rem; text-transform: uppercase; color: var(--text-dim); font-family: var(--font-sans); letter-spacing: 0.05em; }}
        .metric-value {{ font-size: 1.15rem; font-weight: 500; color: var(--text-title); font-family: var(--font-mono); margin-top: 3px; }}

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
            font-size: 1.1rem;
            font-family: var(--font-serif);
            padding: 12px 18px;
            cursor: pointer;
            position: relative;
            transition: all 0.15s;
        }}
        .tab-btn:hover {{ color: var(--text-title); }}
        .tab-btn.active {{ color: var(--accent-warm); }}
        .tab-btn.active::after {{
            content: '';
            position: absolute;
            bottom: -1px;
            left: 0; right: 0;
            height: 2px;
            background: var(--accent-warm);
        }}

        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}

        /* Memo Content */
        .memo-container {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 48px 52px;
        }}
        .memo-container h2 {{
            font-family: var(--font-serif);
            font-size: 1.55rem;
            font-weight: 500;
            color: var(--text-title);
            margin: 40px 0 16px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--border-color);
            letter-spacing: -0.02em;
        }}
        .memo-container h2:first-of-type {{ margin-top: 0; }}
        .memo-container h3 {{
            font-family: var(--font-serif);
            font-size: 1.25rem;
            font-weight: 500;
            color: var(--accent-warm);
            margin: 28px 0 12px;
        }}
        .memo-container p {{
            font-size: 1.18rem;
            line-height: 1.9;
            color: var(--text-body);
            margin-bottom: 20px;
        }}
        .memo-container ul, .memo-container ol {{
            font-size: 1.15rem;
            line-height: 1.9;
            color: var(--text-body);
            margin: 0 0 24px 30px;
        }}
        .memo-container li {{ margin-bottom: 8px; }}

        /* STUNNING CONSISTENT TABLES - ZERO WHITE GLARE */
        .memo-container table {{
            width: 100% !important;
            border-collapse: separate !important;
            border-spacing: 0 !important;
            margin: 32px 0 !important;
            background: #1B1A18 !important;
            border-radius: 12px !important;
            overflow: hidden !important;
            border: 1px solid rgba(230, 220, 205, 0.08) !important;
        }}
        .memo-container tr, .memo-container td, .memo-container th {{
            background: transparent !important;
        }}
        .memo-container th {{
            background: #23221E !important;
            color: #C99A75 !important;
            font-family: var(--font-sans) !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.06em !important;
            padding: 14px 18px !important;
            border-bottom: 1px solid rgba(230, 220, 205, 0.08) !important;
            text-align: left !important;
        }}
        .memo-container td {{
            padding: 14px 18px !important;
            border-bottom: 1px solid rgba(230, 220, 205, 0.05) !important;
            font-size: 0.94rem !important;
            color: #C9C4BA !important;
            font-family: var(--font-mono) !important;
            text-align: left !important;
        }}
        .memo-container tr:last-child td {{
            border-bottom: none !important;
        }}
        .memo-container tr:nth-child(even) td {{
            background: rgba(255, 255, 255, 0.015) !important;
        }}
        .memo-container tr:hover td {{
            background: rgba(201, 154, 117, 0.04) !important;
        }}
        .memo-container td strong, .memo-container td b {{
            color: #E8E3DA !important;
            font-weight: 600 !important;
        }}

        .memo-container blockquote {{
            background: var(--bg-subpanel);
            border-left: 3px solid var(--accent-warm);
            padding: 18px 24px;
            border-radius: 0 8px 8px 0;
            margin: 28px 0;
            font-style: italic;
            font-size: 1.15rem;
            color: var(--text-title);
            line-height: 1.8;
        }}
        .memo-container .callout {{
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-left: 3px solid var(--accent-warm);
            border-radius: 8px;
            padding: 18px 22px;
            margin: 24px 0;
        }}

        /* History */
        .history-entry {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 28px 32px;
            margin-bottom: 20px;
        }}
        .history-entry-active {{ border-color: rgba(201, 154, 117, 0.35); }}
        .history-top {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }}
        .history-tags {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
        .history-time {{ color: var(--text-secondary); font-size: 0.88rem; font-family: var(--font-sans); }}
        .history-price {{ font-family: var(--font-mono); font-size: 0.92rem; }}

        .diff-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin: 20px 0;
        }}
        @media (max-width: 768px) {{ .diff-grid {{ grid-template-columns: 1fr; }} }}
        .diff-box {{
            padding: 18px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }}
        .diff-prev {{ background: rgba(196, 114, 108, 0.05); border-color: rgba(196, 114, 108, 0.18); }}
        .diff-now {{ background: rgba(125, 157, 129, 0.05); border-color: rgba(125, 157, 129, 0.18); }}
        .diff-label {{ font-family: var(--font-sans); font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; }}
        .diff-prev .diff-label {{ color: var(--accent-red); }}
        .diff-now .diff-label {{ color: var(--accent-green); }}
        .diff-text {{ font-size: 1.05rem; color: var(--text-body); line-height: 1.65; }}

        /* Pills */
        .pill {{
            display: inline-flex;
            align-items: center;
            padding: 3px 10px;
            border-radius: 9999px;
            font-size: 0.7rem;
            font-family: var(--font-sans);
            font-weight: 500;
            letter-spacing: 0.03em;
            white-space: nowrap;
        }}
        .pill-active {{ background: rgba(201, 154, 117, 0.14); color: var(--accent-warm); border: 1px solid rgba(201, 154, 117, 0.28); }}
        .pill-neutral {{ background: var(--bg-subpanel); color: var(--text-secondary); border: 1px solid var(--border-color); }}
        .pill-alert {{ background: rgba(191, 160, 117, 0.14); color: var(--accent-warm); border: 1px solid rgba(191, 160, 117, 0.28); }}

        .btn-subtle {{
            background: var(--bg-subpanel);
            color: var(--text-title);
            border: 1px solid var(--border-color);
            font-family: var(--font-sans);
            font-size: 0.8rem;
            padding: 7px 14px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .btn-subtle:hover {{ background: var(--bg-hover); }}

        .snapshot-drawer {{ margin-top: 24px; padding-top: 24px; border-top: 1px solid var(--border-color); }}

        .pos {{ color: var(--accent-green); }}
        .neg {{ color: var(--accent-red); }}
    </style>
</head>
<body>
    <nav class="nav-bar">
        <div class="container nav-inner">
            <a href="../index.html" class="nav-back">← AlphaThesis</a>
            <span style="font-size: 0.82rem; color: var(--text-dim); font-family: var(--font-sans);">{ticker} RESEARCH</span>
        </div>
    </nav>

    <main class="container">
        <!-- Hero Deck -->
        <section class="hero-deck">
            <div class="hero-top-row">
                <div>
                    <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                        <span class="ticker-symbol">{stock.ticker}</span>
                        {labels_html}
                    </div>
                    <div class="company-meta">{stock.company_name}</div>
                </div>
                <div class="price-callout">
                    <div class="price-number">${stock.current_price:.2f}</div>
                    <div class="price-sub {'pos' if stock.return_pct >= 0 else 'neg'}">
                        {stock.return_pct:+.2f}% vs Genesis
                    </div>
                </div>
            </div>

            <!-- Native Area Chart -->
            {chart_html}

            <!-- Key Metrics Grid -->
            <div class="metrics-grid">
                <div class="metric-cell">
                    <div class="metric-label">Fair Value</div>
                    <div class="metric-value" style="color: var(--accent-warm);">{stock.fair_value_estimate}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Bear Target</div>
                    <div class="metric-value" style="color: var(--accent-red);">{stock.bear_target}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Base Target</div>
                    <div class="metric-value">{stock.base_target}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Bull Target</div>
                    <div class="metric-value" style="color: var(--accent-green);">{stock.bull_target}</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Next Catalyst</div>
                    <div class="metric-value" style="font-size: 0.88rem; font-family: var(--font-sans);">{stock.next_catalyst_date or 'TBD'}</div>
                </div>
            </div>
        </section>

        <!-- Navigation Tabs -->
        <div class="tabs-header">
            <button class="tab-btn active" onclick="showTab('memo')">Investment Thesis</button>
            <button class="tab-btn" onclick="showTab('history')">Evolution ({len(history)})</button>
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
    """Generates the clean, minimalist, soothing master ledger."""
    _ensure_dirs()
    
    table_rows_html = ""
    grid_cards_html = ""

    if not watchlist:
        table_rows_html = """
        <tr>
            <td colspan="5" style="text-align: center; padding: 70px 24px; color: var(--text-secondary); font-family: var(--font-serif); font-size: 1.15rem;">
                <div style="color: var(--text-title); font-size: 1.25rem; font-weight: 500; margin-bottom: 6px;">Watchlist Empty</div>
                <div style="font-size: 1rem; color: var(--text-secondary);">Add stocks to begin due diligence and tracking.</div>
            </td>
        </tr>
        """
        grid_cards_html = """
        <div style="grid-column: 1 / -1; text-align: center; padding: 70px 24px; background: var(--bg-panel); border: 1px dashed var(--border-color); border-radius: 16px;">
            <div style="color: var(--text-title); font-size: 1.25rem; font-weight: 500; margin-bottom: 6px;">No Active Coverage</div>
            <div style="color: var(--text-secondary); font-size: 1rem;">Ready to process initial due diligence memos.</div>
        </div>
        """

    for ticker, stock in sorted(watchlist.items(), key=lambda x: x[0]):
        ret_class = "pos" if stock.return_pct >= 0 else "neg"
        labels_html = format_labels_pills(stock.labels or [stock.status_label])
        
        # Clean company name for hover
        clean_company = stock.company_name
        if clean_company.upper() == stock.ticker.upper():
            clean_company = stock.ticker
        else:
            clean_company = re.sub(r"\b" + stock.ticker + r"\b", "", clean_company, flags=re.IGNORECASE).strip()
            clean_company = re.sub(r"\s+", " ", clean_company).strip()

        table_rows_html += f"""
        <tr class="table-row" onclick="location.href='reports/{stock.ticker}.html'" title="{clean_company}">
            <td>
                <div class="tbl-ticker-cell">
                    <span class="tbl-symbol">{stock.ticker}</span>
                    <span class="tbl-company-hover">{clean_company}</span>
                </div>
            </td>
            <td>
                <div class="tbl-price-cell">
                    <span class="tbl-price">${stock.current_price:.2f}</span>
                    <span class="tbl-return {ret_class}">{stock.return_pct:+.2f}%</span>
                </div>
            </td>
            <td>
                <div class="tbl-labels-cell">
                    {labels_html}
                </div>
            </td>
            <td>
                <div class="tbl-val-cell">
                    <span class="tbl-fv" style="color: var(--accent-warm);">{stock.fair_value_estimate}</span>
                    <span class="tbl-base">{stock.base_target}</span>
                </div>
            </td>
            <td>
                <div class="tbl-catalyst-cell">
                    <span class="tbl-cat-date">{stock.next_catalyst_date or 'TBD'}</span>
                    <span class="tbl-cat-desc">{stock.next_catalyst_event[:50] if stock.next_catalyst_event else ''}</span>
                </div>
            </td>
        </tr>
        """

        grid_cards_html += f"""
        <div class="grid-card" onclick="location.href='reports/{stock.ticker}.html'">
            <div class="grid-card-top">
                <span class="grid-symbol">{stock.ticker}</span>
                <div class="grid-price">${stock.current_price:.2f}</div>
            </div>
            <div class="grid-labels-row" style="margin: 6px 0 14px;">
                {labels_html}
            </div>
            <div class="grid-company">{clean_company}</div>
            
            <div class="grid-metrics-box">
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Return</span>
                    <span class="grid-stat-val {ret_class}">{stock.return_pct:+.2f}%</span>
                </div>
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Fair Value</span>
                    <span class="grid-stat-val" style="color: var(--accent-warm);">{stock.fair_value_estimate}</span>
                </div>
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Base Target</span>
                    <span class="grid-stat-val">{stock.base_target}</span>
                </div>
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Next Catalyst</span>
                    <span class="grid-stat-val" style="font-family: var(--font-sans);">{stock.next_catalyst_date or 'TBD'}</span>
                </div>
            </div>
            
            <div class="grid-card-foot">
                <span class="grid-updated">Updated {stock.last_updated}</span>
                <span class="grid-open">Open →</span>
            </div>
        </div>
        """

    alerts_feed_html = ""
    if not alerts:
        alerts_feed_html = """
        <div class="empty-alerts">
            <div class="empty-title">All Positions In Normal Corridors</div>
            <div class="empty-sub">No critical threshold breaches or catalyst alerts logged. Surveillance is active.</div>
        </div>
        """
    else:
        for a in alerts:
            ret_class = "pos" if a.price_change_pct >= 0 else "neg"
            labels_html = format_labels_pills(a.labels or [a.severity])
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
                        <strong class="alert-ticker">{a.ticker}</strong>
                        {labels_html}
                        <span class="alert-time">{a.timestamp}</span>
                    </div>
                    <div class="alert-title">{a.title}</div>
                    <div class="alert-blurb">{a.what_changes_now[:220]}...</div>
                </div>
                <div class="alert-right">
                    <div class="alert-price-val">${a.price_at_alert:.2f}</div>
                    <div class="alert-price-pct {ret_class}">{a.price_change_pct:+.2f}%</div>
                </div>
            </div>
            """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AlphaThesis</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com">
    <link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;1,6..72,400&family=Plus+Jakarta+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-canvas: #161514;
            --bg-panel: #1E1D1B;
            --bg-subpanel: #262522;
            --bg-hover: #2C2A26;
            --text-title: #E8E3DA;
            --text-body: #C9C4BA;
            --text-secondary: #948F85;
            --text-dim: #6B665E;
            --accent-warm: #C99A75;
            --accent-green: #7D9D81;
            --accent-red: #C4726C;
            --border-color: rgba(230, 220, 205, 0.07);
            --border-focus: rgba(230, 220, 205, 0.14);
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
            padding-bottom: 120px;
        }}

        .container {{ max-width: 1000px; margin: 0 auto; padding: 0 24px; }}

        /* Header */
        header.nav-header {{
            background: rgba(22, 21, 20, 0.92);
            backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 100;
            padding: 20px 0;
        }}
        .header-content {{ display: flex; justify-content: space-between; align-items: center; }}
        .brand-logo {{
            font-family: var(--font-serif);
            font-size: 1.45rem;
            font-weight: 500;
            letter-spacing: -0.01em;
            color: var(--text-title);
            text-decoration: none;
        }}

        /* Navigation Controls */
        .hub-controls {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            margin: 36px 0 20px;
            padding-bottom: 14px;
            border-bottom: 1px solid var(--border-color);
        }}
        .hub-tabs {{ display: flex; gap: 8px; }}
        .hub-tab-btn {{
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 1.1rem;
            font-family: var(--font-serif);
            font-weight: 400;
            padding: 8px 16px;
            cursor: pointer;
            position: relative;
            transition: color 0.15s;
        }}
        .hub-tab-btn:hover {{ color: var(--text-title); }}
        .hub-tab-btn.active {{ color: var(--accent-warm); }}
        .hub-tab-btn.active::after {{
            content: '';
            position: absolute;
            bottom: -15px;
            left: 0; right: 0;
            height: 2px;
            background: var(--accent-warm);
        }}

        .view-toggle {{
            display: flex;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 2px;
        }}
        .view-btn {{
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 0.78rem;
            font-family: var(--font-sans);
            font-weight: 500;
            padding: 5px 12px;
            border-radius: 4px;
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
            border-radius: 14px;
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
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 14px 22px;
            border-bottom: 1px solid var(--border-color);
        }}
        table.fin-table td {{
            padding: 18px 22px;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.98rem;
            vertical-align: middle;
        }}
        .table-row {{ cursor: pointer; transition: background 0.15s; position: relative; }}
        .table-row:hover {{ background: var(--bg-hover); }}
        .table-row:last-child td {{ border-bottom: none; }}

        /* Clean Ticker with Smooth Hover Company Name */
        .tbl-ticker-cell {{ display: flex; flex-direction: column; position: relative; }}
        .tbl-symbol {{ font-family: var(--font-serif); font-size: 1.4rem; font-weight: 500; color: var(--text-title); line-height: 1; }}
        .tbl-company-hover {{
            font-size: 0.8rem;
            color: var(--accent-warm);
            font-style: italic;
            margin-top: 3px;
            opacity: 0.0;
            max-height: 0;
            overflow: hidden;
            transition: all 0.2s ease-in-out;
        }}
        .table-row:hover .tbl-company-hover {{
            opacity: 0.85;
            max-height: 20px;
        }}

        .tbl-price-cell {{ display: flex; flex-direction: column; gap: 2px; }}
        .tbl-price {{ font-size: 1.18rem; font-weight: 500; font-family: var(--font-mono); color: var(--text-title); line-height: 1.1; }}
        .tbl-return {{ font-size: 0.8rem; font-family: var(--font-mono); }}

        .tbl-labels-cell {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}

        .tbl-val-cell {{ display: flex; flex-direction: column; gap: 2px; }}
        .tbl-fv {{ font-size: 1.1rem; font-weight: 500; font-family: var(--font-mono); line-height: 1.1; }}
        .tbl-base {{ font-size: 0.82rem; color: var(--text-secondary); }}

        .tbl-catalyst-cell {{ display: flex; flex-direction: column; gap: 2px; max-width: 240px; }}
        .tbl-cat-date {{ font-family: var(--font-sans); font-size: 0.85rem; font-weight: 500; color: var(--text-title); }}
        .tbl-cat-desc {{ font-size: 0.78rem; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

        /* Grid View */
        .grid-cards-wrap {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 18px;
        }}
        .grid-card {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 24px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .grid-card:hover {{
            background: var(--bg-hover);
            border-color: var(--border-focus);
        }}
        .grid-card-top {{ display: flex; justify-content: space-between; align-items: center; }}
        .grid-symbol {{ font-family: var(--font-serif); font-size: 1.8rem; font-weight: 500; color: var(--text-title); }}
        .grid-price {{ font-size: 1.6rem; font-weight: 500; font-family: var(--font-mono); color: var(--text-title); }}
        .grid-labels-row {{ display: flex; gap: 6px; flex-wrap: wrap; }}
        .grid-company {{ color: var(--text-secondary); font-size: 0.92rem; font-style: italic; margin: 4px 0 18px; }}

        .grid-metrics-box {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            background: var(--bg-subpanel);
            padding: 14px;
            border-radius: 8px;
            margin-bottom: 18px;
        }}
        .grid-stat {{ display: flex; flex-direction: column; }}
        .grid-stat-lbl {{ font-size: 0.65rem; text-transform: uppercase; color: var(--text-dim); font-family: var(--font-sans); font-weight: 500; }}
        .grid-stat-val {{ font-size: 1rem; font-weight: 500; font-family: var(--font-mono); margin-top: 2px; }}

        .grid-card-foot {{
            display: flex; justify-content: space-between; align-items: center;
            border-top: 1px solid var(--border-color); padding-top: 14px;
        }}
        .grid-updated {{ font-size: 0.75rem; color: var(--text-dim); font-family: var(--font-mono); }}
        .grid-open {{ font-family: var(--font-sans); font-size: 0.82rem; font-weight: 500; color: var(--accent-warm); }}

        /* Alerts */
        .alerts-feed {{ display: flex; flex-direction: column; gap: 14px; }}
        .alert-item {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 22px 26px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 20px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .alert-item:hover {{
            background: var(--bg-hover);
            border-color: rgba(201, 154, 117, 0.35);
        }}
        .alert-left {{ flex: 1; }}
        .alert-badges {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
        .alert-ticker {{ font-family: var(--font-serif); font-size: 1.2rem; font-weight: 500; color: var(--text-title); }}
        .alert-time {{ font-size: 0.78rem; color: var(--text-dim); font-family: var(--font-mono); }}
        .alert-title {{ font-family: var(--font-serif); font-size: 1.2rem; font-weight: 500; color: var(--text-title); margin-bottom: 4px; }}
        .alert-blurb {{ font-size: 1.05rem; color: var(--text-secondary); line-height: 1.55; }}

        .alert-right {{ text-align: right; min-width: 140px; }}
        .alert-price-val {{ font-size: 1.45rem; font-weight: 500; font-family: var(--font-mono); color: var(--text-title); }}
        .alert-price-pct {{ font-size: 0.9rem; font-family: var(--font-mono); }}

        /* Pills */
        .pill {{
            display: inline-flex;
            align-items: center;
            padding: 3px 10px;
            border-radius: 9999px;
            font-size: 0.7rem;
            font-family: var(--font-sans);
            font-weight: 500;
            letter-spacing: 0.03em;
            white-space: nowrap;
        }}
        .pill-active {{ background: rgba(201, 154, 117, 0.14); color: var(--accent-warm); border: 1px solid rgba(201, 154, 117, 0.28); }}
        .pill-neutral {{ background: var(--bg-subpanel); color: var(--text-secondary); border: 1px solid var(--border-color); }}
        .pill-alert {{ background: rgba(191, 160, 117, 0.14); color: var(--accent-warm); border: 1px solid rgba(191, 160, 117, 0.28); }}

        .pos {{ color: var(--accent-green); }}
        .neg {{ color: var(--accent-red); }}

        .empty-alerts {{
            text-align: center;
            background: var(--bg-panel);
            border: 1px dashed var(--border-color);
            border-radius: 14px;
            padding: 60px 24px;
        }}
        .empty-title {{ font-family: var(--font-serif); font-size: 1.25rem; font-weight: 500; color: var(--text-title); margin-bottom: 4px; }}
        .empty-sub {{ font-size: 1rem; color: var(--text-secondary); max-width: 440px; margin: 0 auto; }}

        /* Modal */
        .modal-shade {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(10, 10, 9, 0.82);
            backdrop-filter: blur(12px);
            z-index: 1000;
            display: none;
            justify-content: center;
            align-items: center;
            padding: 24px;
        }}
        .modal-body-card {{
            background: var(--bg-panel);
            border: 1px solid var(--border-focus);
            border-radius: 16px;
            max-width: 720px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            padding: 36px;
            position: relative;
        }}
        .modal-x {{
            position: absolute;
            top: 20px; right: 20px;
            background: none;
            border: none;
            color: var(--text-dim);
            font-size: 1.4rem;
            cursor: pointer;
        }}
        .modal-x:hover {{ color: var(--text-title); }}

        .diff-modal-wrap {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin: 22px 0;
        }}
        @media (max-width: 640px) {{ .diff-modal-wrap {{ grid-template-columns: 1fr; }} }}
        .diff-side {{ padding: 18px; border-radius: 8px; border: 1px solid var(--border-color); }}
        .side-before {{ background: rgba(196, 114, 108, 0.05); border-color: rgba(196, 114, 108, 0.18); }}
        .side-after {{ background: rgba(125, 157, 129, 0.05); border-color: rgba(125, 157, 129, 0.18); }}
        .side-heading {{ font-family: var(--font-sans); font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; }}
        .side-before .side-heading {{ color: var(--accent-red); }}
        .side-after .side-heading {{ color: var(--accent-green); }}
        .side-text {{ font-size: 1.05rem; color: var(--text-body); line-height: 1.65; }}

        .btn-primary {{
            background: var(--accent-warm); color: #161514; font-family: var(--font-sans); font-weight: 500;
            padding: 10px 20px; border-radius: 6px; text-decoration: none; display: inline-flex; align-items: center; border: none; cursor: pointer;
            transition: all 0.15s;
        }}
        .btn-primary:hover {{ background: #DDB495; }}
        .btn-outline {{
            background: var(--bg-subpanel); color: var(--text-title); border: 1px solid var(--border-color);
            font-family: var(--font-sans); font-weight: 500; padding: 10px 18px; border-radius: 6px; cursor: pointer;
        }}
        .btn-outline:hover {{ background: var(--bg-hover); }}
    </style>
</head>
<body>
    <header class="nav-header">
        <div class="container header-content">
            <a href="#" class="brand-logo">AlphaThesis</a>
        </div>
    </header>

    <main class="container">
        <!-- Navigation Controls -->
        <div class="hub-controls">
            <div class="hub-tabs">
                <button class="hub-tab-btn active" onclick="switchTab('stocks')">Coverage ({len(watchlist)})</button>
                <button class="hub-tab-btn" onclick="switchTab('alerts')">Alerts ({len(alerts)})</button>
            </div>
            <div class="view-toggle" id="view-toggle-bar">
                <button class="view-btn active" onclick="setView('table')">Table</button>
                <button class="view-btn" onclick="setView('grid')">Cards</button>
            </div>
        </div>

        <!-- STOCKS SECTION -->
        <section id="pane-stocks" class="tab-panel active">
            <!-- Table View -->
            <div id="stocks-table-view" class="table-wrap">
                <table class="fin-table">
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Market Price</th>
                            <th>Labels</th>
                            <th>Fair Value</th>
                            <th>Catalyst Horizon</th>
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
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                <span id="modal-badge" class="pill pill-alert">ALERT</span>
                <strong id="modal-ticker" style="font-family: var(--font-serif); font-size: 1.35rem; color: var(--text-title);">TICKER</strong>
                <span id="modal-time" style="color: var(--text-dim); font-size: 0.8rem; font-family: var(--font-mono);">Timestamp</span>
            </div>
            <h2 id="modal-title" style="font-family: var(--font-serif); font-size: 1.45rem; color: var(--text-title); margin-bottom: 10px; letter-spacing: -0.02em;">Alert Headline</h2>
            <div style="font-size: 0.9rem; color: var(--text-secondary); margin-bottom: 18px;">
                <strong>Trigger:</strong> <span id="modal-trigger">Reason</span>
            </div>

            <div class="diff-modal-wrap">
                <div class="diff-side side-before">
                    <div class="side-heading">Previous Stance</div>
                    <div id="modal-before" class="side-text">Previous stance...</div>
                </div>
                <div class="diff-side side-after">
                    <div class="side-heading">What Changes Now</div>
                    <div id="modal-after" class="side-text">Updated thesis...</div>
                </div>
            </div>

            <div style="display: flex; justify-content: flex-end; gap: 12px; margin-top: 28px;">
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
