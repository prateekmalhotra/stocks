"""Minimalist, Soothing Financial Research Dashboard & Due Diligence Dossier."""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from stocks.models import WatchlistStock, AlertItem, ThesisVersion
from stocks.data_store import load_watchlist, load_alerts, load_thesis_history
from stocks.tracker import fetch_all_chart_ranges
from stocks.ownership_intelligence import build_ownership_tab_html, calculate_insider_sentiment_and_flow, load_cached_ownership
from bs4 import BeautifulSoup, NavigableString, Tag

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


def format_usd_target(val: Any) -> str:
    """Guarantees any price or target string is formatted strictly in clean USD ($X,XXX.XX),
    stripping foreign currency prefixes like C$, CAD, HK$, EUR, etc."""
    if val is None or val == "":
        return "$0.00"
    if isinstance(val, (int, float)):
        return f"${val:,.2f}"
    
    val_str = str(val).strip()
    m = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", val_str)
    if m:
        try:
            num = float(m.group(0).replace(",", ""))
            return f"${num:,.2f}"
        except Exception:
            pass
    return val_str.replace("C$", "$").replace("CAD", "").replace("USD", "").strip()


def extract_pct_delta(base_target: str, current_price: float, fair_value_str: str) -> str:
    """Extracts clean percentage difference without repeating the dollar value."""
    match = re.search(r"\(([-+]?\d+(?:\.\d+)?%)\)", base_target)
    if match:
        return match.group(1)
    
    fv_match = re.search(r"[-+]?\d+(?:\.\d+)?", fair_value_str.replace(",", ""))
    if fv_match and current_price > 0:
        fv = float(fv_match.group(0))
        diff_pct = ((fv - current_price) / current_price) * 100
        return f"{diff_pct:+.1f}%"
        
    return ""


def sanitize_catalyst_desc(desc: str) -> str:
    """Formats catalyst description to max 4 words without ellipses or clutter."""
    if not desc:
        return ""
    cleaned = re.sub(r"\.{2,}", "", desc).strip()
    words = [w for w in cleaned.split() if w.strip()]
    if len(words) > 4:
        return " ".join(words[:4])
    return " ".join(words)


def format_action_beacon(signal: Optional[str] = None) -> str:
    """Renders the subtle pulsing status beacon chosen autonomously by the LLM on update."""
    if not signal:
        return ""
    sig = signal.upper().strip()
    if any(k in sig for k in ["RED", "AVOID", "BROKEN", "EXIT", "SELL", "DANGER", "CRITICAL", "DON'T BUY", "DO NOT BUY"]):
        css = "beacon-avoid"
        tooltip = "Action Signal: Avoid / Do Not Buy (Thesis Broken)"
    elif any(k in sig for k in ["ORANGE", "CAUTION", "TRIM", "HEADWIND", "WARNING", "FRICTION", "GOING BAD"]):
        css = "beacon-caution"
        tooltip = "Action Signal: Caution (Facing Headwinds / Trim Zone)"
    elif any(k in sig for k in ["YELLOW", "WAIT", "HOLD", "MONITOR", "PATIENT", "NEUTRAL", "STEADY", "DO NOTHING"]):
        css = "beacon-hold"
        tooltip = "Action Signal: Wait / Hold (Wait & Do Nothing for Now)"
    elif any(k in sig for k in ["GREEN", "BUY", "ACCUMULATE", "STRONG", "NOW"]):
        css = "beacon-buy"
        tooltip = "Action Signal: Strong Buy (Get in NOW / Thesis Accelerating)"
    else:
        css = "beacon-buy"
        tooltip = "Action Signal: Strong Buy"
    
    return f'<span class="status-beacon {css}" title="{tooltip}"><span class="beacon-ping"></span><span class="beacon-dot"></span></span>'


def clean_fund_name(name: str) -> str:
    """Strips parentheticals and extra annotations for ultra-clean subtext display."""
    if not name:
        return ""
    c = re.sub(r"\(.*?\)", "", name).strip()
    c = re.sub(r"\s*/.*", "", c).strip()
    c = c.replace("Management", "").replace("Capital", "").replace("Hathaway", "").strip()
    return c


def format_top_funds_card_html(stock: WatchlistStock) -> str:
    """Renders a clean, high-density institutional float card."""
    funds = getattr(stock, "top_funds", None) or []
    inst_pct = getattr(stock, "institutional_ownership_pct", None) or "70%+"
    
    clean_names = [clean_fund_name(f) for f in funds if clean_fund_name(f)]
    subtext = " · ".join(clean_names[:3]) if clean_names else "13F Institutional Float"
    
    full_tooltip = ", ".join(funds) if funds else "Institutional Ownership"
    if inst_pct and inst_pct not in full_tooltip:
        full_tooltip += f" ({inst_pct} of float)"
    
    return f"""
    <div class="metric-cell">
        <div class="metric-label">Institutional Float</div>
        <div class="metric-value" style="font-family: var(--font-mono); color: var(--text-title); font-size: 1.15rem; font-weight: 500;">{inst_pct}</div>
        <div class="metric-subtext" style="color: var(--text-dim);" title="{full_tooltip}">{subtext}</div>
    </div>
    """


def format_insider_activity_card_html(stock: WatchlistStock) -> str:
    """Renders a clean, high-density insider sentiment card computed deterministically from Form 4 ledger."""
    cached = load_cached_ownership(stock.ticker)
    oi_trades = cached.get("openinsider_trades", [])
    raw_signal = getattr(stock, "insider_signal", None) or ""
    intel = calculate_insider_sentiment_and_flow(oi_trades, raw_signal)
    
    summary = intel["summary"]
    subtext = summary if len(summary) <= 34 else "Executive alignment"

    return f"""
    <div class="metric-cell">
        <div class="metric-label">Insider Sentiment</div>
        <div class="metric-value" style="font-family: var(--font-sans); color: {intel['color']}; font-size: 1.05rem; font-weight: 600;">{intel['badge_html']}</div>
        <div class="metric-subtext" style="color: var(--text-dim);" title="{summary}">{subtext}</div>
    </div>
    """


def build_labels_legend_modal_html() -> str:
    """Builds the clean, interactive modal explaining investment taxonomy, conviction tiers, beacons, and play drivers."""
    return """
    <!-- Labels & Taxonomy Legend Modal -->
    <div id="labels-legend-modal" class="modal-shade" onclick="closeLegendModalOutside(event)">
        <div class="modal-body-card" style="max-width: 780px;">
            <button class="modal-x" onclick="closeLabelsLegendModal()">✕</button>
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 6px;">
                <span style="font-size: 1.3rem;">🏷️</span>
                <h2 style="font-family: var(--font-serif); font-size: 1.55rem; color: var(--text-title); margin: 0; letter-spacing: -0.02em;">Investment Taxonomy & Labels Legend</h2>
            </div>
            <p style="color: var(--text-dim); font-size: 0.88rem; margin: 0 0 24px; line-height: 1.4;">
                Autonomous multi-tier categorization system evaluating long-term conviction, live surveillance action signals, and strategic play drivers.
            </p>

            <div style="display: flex; flex-direction: column; gap: 20px;">
                <!-- Section 1: Conviction Tiers -->
                <div style="background: var(--bg-subpanel); border: 1px solid var(--border-color); border-radius: 12px; padding: 20px;">
                    <div style="font-family: var(--font-sans); font-size: 0.76rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent-warm); margin-bottom: 12px;">
                        Tier 1: Forward Conviction & Risk Stance (Slot 1 Primary Pill)
                    </div>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px;">
                        <div style="display: flex; flex-direction: column; gap: 3px;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span class="pill pill-active" style="font-size: 0.75rem;">High Conviction</span>
                            </div>
                            <span style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">Exceptional asymmetric risk/reward, dominant economic moat, fortress balance sheet, and deep margin of safety.</span>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 3px;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span class="pill pill-active" style="font-size: 0.75rem;">Solid Conviction</span>
                            </div>
                            <span style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">Proven recurring cash generation, structural advantages, and clear compounding runway with standard execution risk.</span>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 3px;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span class="pill pill-active" style="font-size: 0.75rem;">Moderate Conviction</span>
                            </div>
                            <span style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">Attractive upside balanced by cyclical exposure, customer concentration, or competitive transition.</span>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 3px;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span class="pill pill-active" style="font-size: 0.75rem;">Cautious Stance</span>
                            </div>
                            <span style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">Thesis structurally intact but facing temporary execution headwinds, margin compression, or macro friction.</span>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 3px;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span class="pill pill-active" style="font-size: 0.75rem;">Turnaround Play</span>
                            </div>
                            <span style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">High upside anchored in management operational reset, debt paydown, cost cuts, or real estate asset backing.</span>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 3px;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span class="pill pill-active" style="font-size: 0.75rem;">Speculative Risk</span>
                            </div>
                            <span style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">High asymmetry paired with balance sheet leverage, regulatory hurdles, or binary product adoption.</span>
                        </div>
                    </div>
                </div>

                <!-- Section 2: Action Signals -->
                <div style="background: var(--bg-subpanel); border: 1px solid var(--border-color); border-radius: 12px; padding: 20px;">
                    <div style="font-family: var(--font-sans); font-size: 0.76rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent-warm); margin-bottom: 12px;">
                        Live Surveillance Action Signals (Pulsing Beacons)
                    </div>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px;">
                        <div style="display: flex; gap: 10px; align-items: flex-start;">
                            <span class="status-beacon beacon-buy" style="margin-top: 5px;"><span class="beacon-dot"></span><span class="beacon-ping"></span></span>
                            <div>
                                <strong style="color: #10b981; font-size: 0.85rem;">BUY (Green Pulse):</strong>
                                <div style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">Thesis accelerating, fundamentals compounding, deep value buy zone -> High priority entry.</div>
                            </div>
                        </div>
                        <div style="display: flex; gap: 10px; align-items: flex-start;">
                            <span class="status-beacon beacon-hold" style="margin-top: 5px;"><span class="beacon-dot"></span><span class="beacon-ping"></span></span>
                            <div>
                                <strong style="color: #f59e0b; font-size: 0.85rem;">HOLD (Yellow Pulse):</strong>
                                <div style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">Thesis steady, fairly valued -> Wait and do nothing for now while awaiting next catalyst.</div>
                            </div>
                        </div>
                        <div style="display: flex; gap: 10px; align-items: flex-start;">
                            <span class="status-beacon beacon-caution" style="margin-top: 5px;"><span class="beacon-dot"></span><span class="beacon-ping"></span></span>
                            <div>
                                <strong style="color: #f97316; font-size: 0.85rem;">CAUTION (Orange Pulse):</strong>
                                <div style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">Thesis encountering execution friction, margin pressure, or guidance cuts -> Caution / trim zone.</div>
                            </div>
                        </div>
                        <div style="display: flex; gap: 10px; align-items: flex-start;">
                            <span class="status-beacon beacon-avoid" style="margin-top: 5px;"><span class="beacon-dot"></span><span class="beacon-ping"></span></span>
                            <div>
                                <strong style="color: #ef4444; font-size: 0.85rem;">AVOID (Red Pulse):</strong>
                                <div style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">Thesis broken, structural moat decay, or fatal hurdle breakdown -> Do NOT buy / exit.</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Section 3: Play Drivers -->
                <div style="background: var(--bg-subpanel); border: 1px solid var(--border-color); border-radius: 12px; padding: 20px;">
                    <div style="font-family: var(--font-sans); font-size: 0.76rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent-warm); margin-bottom: 12px;">
                        Tier 2: Key Play Drivers & Strategic Catalysts (Slots 2 & 3 Secondary Pills)
                    </div>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px;">
                        <div style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">
                            <strong style="color: var(--text-title);">💰 Buyback Cannibal:</strong> Aggressive share retirement concentrating per-share cash flow.
                        </div>
                        <div style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">
                            <strong style="color: var(--text-title);">🏰 Cash Fortress:</strong> Massive net cash balance (>15-20% market cap) eliminating solvency risk.
                        </div>
                        <div style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">
                            <strong style="color: var(--text-title);">📈 Margin Expansion:</strong> Operating leverage and fixed cost efficiency expanding margins.
                        </div>
                        <div style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">
                            <strong style="color: var(--text-title);">🏷️ Deep Value:</strong> High normalized Owner Earnings yield at extreme market discount.
                        </div>
                        <div style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">
                            <strong style="color: var(--text-title);">🔁 Quality Compounder:</strong> High ROIC with durable, high-velocity cash reinvestment.
                        </div>
                        <div style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.35;">
                            <strong style="color: var(--text-title);">🤝 M&A Engine:</strong> Disciplined serial acquirer compounding free cash flow.
                        </div>
                    </div>
                </div>
            </div>

            <div style="display: flex; justify-content: flex-end; margin-top: 24px;">
                <button class="btn-primary" onclick="closeLabelsLegendModal()">Got it</button>
            </div>
        </div>
    </div>
    """


def build_native_svg_chart(ticker: str, current_price: float) -> str:
    """Builds a lightweight, native interactive SVG area chart with 1Y, 5Y, 10Y, MAX ranges."""
    all_ranges_data = fetch_all_chart_ranges(ticker, current_price)
    ranges_json = json.dumps(all_ranges_data)

    initial_pts = all_ranges_data.get("1Y", [])
    prices = [p["price"] for p in initial_pts]
    min_p = min(prices) if prices else current_price * 0.9
    max_p = max(prices) if prices else current_price * 1.1

    first_date = initial_pts[0]["date"] if initial_pts else ""
    last_date = initial_pts[-1]["date"] if initial_pts else ""
    last_price = initial_pts[-1]["price"] if initial_pts else current_price

    width = 900
    height = 260
    padding_x = 20
    padding_y = 25

    return f"""
    <div class="native-chart-wrap" id="chart-container">
        <div class="chart-top-bar">
            <div id="chart-live-val" class="chart-live-val">
                <span id="tooltip-date">{last_date}</span> • <strong id="tooltip-price" style="color: var(--accent-warm);">${last_price:.2f}</strong>
            </div>
            <div class="chart-range-pills">
                <button class="range-pill active" onclick="switchChartRange('1Y')">1Y</button>
                <button class="range-pill" onclick="switchChartRange('5Y')">5Y</button>
                <button class="range-pill" onclick="switchChartRange('10Y')">10Y</button>
                <button class="range-pill" onclick="switchChartRange('MAX')">MAX</button>
            </div>
        </div>

        <svg id="interactive-svg" viewBox="0 0 {width} {height}" preserveAspectRatio="none" class="chart-svg">
            <defs>
                <linearGradient id="area-grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color="#CC785C" stop-opacity="0.20" />
                    <stop offset="100%" stop-color="#CC785C" stop-opacity="0.0" />
                </linearGradient>
            </defs>
            
            <line x1="{padding_x}" y1="{padding_y}" x2="{width - padding_x}" y2="{padding_y}" stroke="rgba(235,225,210,0.04)" stroke-width="1" />
            <line x1="{padding_x}" y1="{height/2}" x2="{width - padding_x}" y2="{height/2}" stroke="rgba(235,225,210,0.04)" stroke-width="1" />
            <line x1="{padding_x}" y1="{height - padding_y}" x2="{width - padding_x}" y2="{height - padding_y}" stroke="rgba(235,225,210,0.04)" stroke-width="1" />

            <path id="chart-area-path" d="" fill="url(#area-grad)" />
            <path id="chart-line-path" d="" fill="none" stroke="#CC785C" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />

            <line id="crosshair-line" x1="0" y1="{padding_y}" x2="0" y2="{height - padding_y}" stroke="rgba(204,120,92,0.4)" stroke-width="1" stroke-dasharray="3 3" style="display: none;" />
            <circle id="hover-dot" r="4.5" fill="#CC785C" stroke="#1E1C19" stroke-width="2" style="display: none;" />
        </svg>
        <div class="chart-labels">
            <span id="chart-start-lbl">{first_date} (${min_p:.2f})</span>
            <span id="chart-range-title">1-Year Historical Range</span>
            <span id="chart-end-lbl">{last_date} (${last_price:.2f})</span>
        </div>
    </div>

    <script>
    (function() {{
        const allDatasets = {ranges_json};
        let currentRangeKey = '1Y';
        let currentPoints = allDatasets[currentRangeKey] || [];
        let currentSvgCoords = [];

        const width = {width};
        const height = {height};
        const padX = {padding_x};
        const padY = {padding_y};

        const container = document.getElementById('chart-container');
        const svg = document.getElementById('interactive-svg');
        const linePath = document.getElementById('chart-line-path');
        const areaPath = document.getElementById('chart-area-path');
        const tooltipDate = document.getElementById('tooltip-date');
        const tooltipPrice = document.getElementById('tooltip-price');
        const crosshair = document.getElementById('crosshair-line');
        const dot = document.getElementById('hover-dot');
        const startLbl = document.getElementById('chart-start-lbl');
        const endLbl = document.getElementById('chart-end-lbl');
        const rangeTitle = document.getElementById('chart-range-title');

        function recalculatePaths(points) {{
            if (!points || points.length < 2) return;
            const prices = points.map(p => p.price);
            const minP = Math.min(...prices);
            const maxP = Math.max(...prices);
            const pRange = Math.max(maxP - minP, 0.01);
            const n = points.length;

            currentSvgCoords = [];
            for (let i = 0; i < n; i++) {{
                const x = padX + (i / (n - 1)) * (width - 2 * padX);
                const y = height - padY - ((points[i].price - minP) / pRange) * (height - 2 * padY);
                currentSvgCoords.push([Math.round(x * 10) / 10, Math.round(y * 10) / 10]);
            }}

            const lineD = 'M ' + currentSvgCoords.map(c => c[0] + ',' + c[1]).join(' L ');
            const firstC = currentSvgCoords[0];
            const lastC = currentSvgCoords[currentSvgCoords.length - 1];
            const areaD = lineD + ' L ' + lastC[0] + ',' + height + ' L ' + firstC[0] + ',' + height + ' Z';

            linePath.setAttribute('d', lineD);
            areaPath.setAttribute('d', areaD);

            startLbl.innerText = points[0].date + ' ($' + minP.toFixed(2) + ')';
            endLbl.innerText = points[n - 1].date + ' ($' + points[n - 1].price.toFixed(2) + ')';
            
            tooltipDate.innerText = points[n - 1].date;
            tooltipPrice.innerText = '$' + points[n - 1].price.toFixed(2);

            const titles = {{ '1Y': '1-Year Range', '5Y': '5-Year Range', '10Y': '10-Year Range', 'MAX': 'All-Time Historical Range' }};
            rangeTitle.innerText = titles[currentRangeKey] || currentRangeKey + ' Range';
        }}

        window.switchChartRange = function(rangeKey) {{
            if (!allDatasets[rangeKey]) return;
            currentRangeKey = rangeKey;
            currentPoints = allDatasets[rangeKey];
            
            document.querySelectorAll('.range-pill').forEach(btn => {{
                if (btn.innerText.trim() === rangeKey) {{
                    btn.classList.add('active');
                }} else {{
                    btn.classList.remove('active');
                }}
            }});

            recalculatePaths(currentPoints);
            hideHover();
        }};

        function updateHover(e) {{
            if (!currentPoints.length || !currentSvgCoords.length) return;
            const rect = svg.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const pct = Math.max(0, Math.min(1, mouseX / rect.width));
            const idx = Math.round(pct * (currentPoints.length - 1));
            
            const pt = currentPoints[idx];
            const coord = currentSvgCoords[idx];
            if (!pt || !coord) return;

            crosshair.setAttribute('x1', coord[0]);
            crosshair.setAttribute('x2', coord[0]);
            crosshair.style.display = 'block';

            dot.setAttribute('cx', coord[0]);
            dot.setAttribute('cy', coord[1]);
            dot.style.display = 'block';

            tooltipDate.innerText = pt.date;
            tooltipPrice.innerText = '$' + pt.price.toFixed(2);
        }}

        function hideHover() {{
            crosshair.style.display = 'none';
            dot.style.display = 'none';
            if (currentPoints.length) {{
                tooltipDate.innerText = currentPoints[currentPoints.length - 1].date;
                tooltipPrice.innerText = '$' + currentPoints[currentPoints.length - 1].price.toFixed(2);
            }}
        }}

        container.addEventListener('mousemove', updateHover);
        container.addEventListener('mouseleave', hideHover);
        container.addEventListener('touchstart', (e) => {{ if (e.touches.length) updateHover(e.touches[0]); }}, {{passive: true}});
        container.addEventListener('touchmove', (e) => {{ if (e.touches.length) updateHover(e.touches[0]); }}, {{passive: true}});
        container.addEventListener('touchend', hideHover);

        recalculatePaths(currentPoints);
    }})();
    </script>
    """


def generate_company_dossier_html(ticker: str, stock: WatchlistStock, history: List[ThesisVersion]) -> str:
    """Generates a clean, soothing, book-like investment due diligence dossier."""
    current_version = history[-1] if history else None
    labels_html = format_labels_pills(stock.labels or [stock.status_label])

    def clean_and_sanitize_html(content: str) -> str:
        if not content:
            return ""
        # 1. Strip code fences, markdown blocks, and leaked json metadata blocks
        cleaned = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", content, flags=re.DOTALL)
        cleaned = re.sub(r"(?:\n|^)\s*json\s*\{.*?\}\s*(?=\n|<div|$)", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"^```(?:html)?\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()
        cleaned = re.sub(r'\s*style\s*=\s*"[^"]*"', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*style\s*=\s*'[^']*'", '', cleaned, flags=re.IGNORECASE)
        
        # 1b. Strip all img tags, figure containers, and broken image embeds
        cleaned = re.sub(r'<div\s+class="figure-container"[^>]*>.*?</div>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r'<figure\b[^>]*>.*?</figure>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r'<img\b[^>]*>', '', cleaned, flags=re.IGNORECASE)
        
        # 1c. Fix unclosed <li> followed by another <li> before BeautifulSoup parses
        prev_pass = ""
        while prev_pass != cleaned:
            prev_pass = cleaned
            cleaned = re.sub(
                r"(<li>(?:(?!</li>|<ul>|<ol>).)*?)(?=\s*<li>)",
                r"\1</li>\n",
                cleaned,
                flags=re.DOTALL | re.IGNORECASE
            )
            
        cleaned = re.sub(r"</li>\s*</li>\s*(</(?:ul|ol)>)", r"</li>\n\1", cleaned, flags=re.IGNORECASE)
        
        # 1d. Convert markdown headings
        cleaned = re.sub(r"^\s*####\s+(.*?)$", lambda m: f"<h4>{m.group(1)}</h4>", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*###\s+(.*?)$", lambda m: f"<h3>{m.group(1)}</h3>", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*##\s+(.*?)$", lambda m: f"<h2>{m.group(1)}</h2>", cleaned, flags=re.MULTILINE)
        
        # 1e. Convert bold and italics
        cleaned = re.sub(r"\*\*(.*?)\*\*", lambda m: f"<strong>{m.group(1)}</strong>", cleaned)
        cleaned = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", lambda m: f"<em>{m.group(1)}</em>", cleaned)
        
        # 1f. Math syntax normalizer (ensure LaTeX formulas render properly)
        def fix_single_dollar_math(match):
            inner = match.group(1)
            if any(cmd in inner for cmd in [r"\text", r"\mathbf", r"\math", r"\frac", r"\times", r"\ge", r"\le", r"\quad", r"\%", r"\cdot", r"\approx", r"\pm"]):
                return f"\\({inner}\\)"
            return match.group(0)

        cleaned = re.sub(r"(?<![\$\\])\$(?!\$)([^\$\n]+?)(?<![\$\\])\$(?!\$)", fix_single_dollar_math, cleaned)
        
        # 1g. Use BeautifulSoup for perfect DOM normalization
        soup = BeautifulSoup(cleaned, "html.parser")
        
        # Flatten improperly nested <li> tags
        for outer_li in soup.find_all("li"):
            nested_lis = outer_li.find_all("li")
            for inner_li in nested_lis:
                parent_list = outer_li.parent
                if parent_list and parent_list.name in ["ul", "ol"]:
                    outer_li.insert_after(inner_li.extract())
                    
        # Remove empty list items
        for li in soup.find_all("li"):
            text = li.get_text(strip=True)
            if not text or text in ["-", "•", "。", "◦", "○"]:
                li.decompose()
                
        # Remove empty lists
        for lst in soup.find_all(["ul", "ol"]):
            if not lst.find_all("li") and not lst.get_text(strip=True):
                lst.decompose()
                
        # Remove empty paragraphs
        for p in soup.find_all("p"):
            if not p.get_text(strip=True) and not p.find_all(["table", "svg", "button"]):
                p.decompose()
                
        # Wrap tables in table-scroll-wrap
        for tbl in soup.find_all("table"):
            if not (tbl.parent and "table-scroll-wrap" in tbl.parent.get("class", [])):
                wrapper = soup.new_tag("div", attrs={"class": "table-scroll-wrap"})
                tbl.wrap(wrapper)

        # 1h. Transform executive quotes and callout commentary into elegant executive cards
        for callout in soup.find_all("div", class_="callout"):
            text = callout.get_text()
            has_quote = bool(callout.find("em") or re.search(r'["“][^"”]{20,}["”]', text))
            has_attribution = bool(re.search(r'[—–-]\s*.*?(?:CEO|CFO|President|COO|CTO|Director|Founder|Chair|Executive)', text, re.IGNORECASE))
            is_commentary_header = bool(re.search(r'(?:Executive Commentary|Earnings Call|CEO on|CFO on|Management on|Strategic Takeaway|Strategic Insights)', text, re.IGNORECASE))
            
            if (has_quote and has_attribution) or is_commentary_header:
                callout["class"] = ["executive-callout"]
                
                # Find and clean up headers
                first_p = callout.find("p")
                if first_p and first_p.find("strong") and not first_p.find("em"):
                    header_text = first_p.get_text().strip()
                    if any(k in header_text.lower() for k in ["executive commentary", "earnings call", "ceo on", "cfo on", "management", "strategic", "leadership"]):
                        header_div = soup.new_tag("div", attrs={"class": "exec-header"})
                        header_icon = soup.new_tag("span", attrs={"class": "exec-badge"})
                        
                        if "earnings call" in header_text.lower() or "commentary" in header_text.lower():
                            header_icon.string = "Executive Commentary"
                        elif "strategic" in header_text.lower():
                            header_icon.string = "Strategic Insights"
                        else:
                            header_icon.string = "Leadership Perspective"
                        
                        sub_match = re.search(r'[—–-]\s*(.*)$', header_text)
                        if sub_match:
                            header_sub = soup.new_tag("span", attrs={"class": "exec-sub"})
                            header_sub.string = sub_match.group(1).strip()
                            header_div.append(header_icon)
                            header_div.append(header_sub)
                        else:
                            header_div.append(header_icon)
                        first_p.replace_with(header_div)

                # Replace raw <hr/> with subtle clean divider
                for hr in callout.find_all("hr"):
                    hr_div = soup.new_tag("div", attrs={"class": "exec-divider"})
                    hr.replace_with(hr_div)
                    
                # Clean and style attribution paragraphs
                for p in callout.find_all("p"):
                    p_text = p.get_text().strip()
                    if p_text.startswith("—") or p_text.startswith("–") or p_text.startswith("- "):
                        p["class"] = ["exec-attribution"]
                        for s in list(p.strings):
                            if s.strip().startswith("—") or s.strip().startswith("–") or s.strip().startswith("-"):
                                new_s = re.sub(r'^[—–-]\s*', '', s.strip())
                                s.replace_with(new_s)
                                break
                
        return str(soup)

    evolution_count = max(0, len(history) - 1)
    ownership_tab_html = build_ownership_tab_html(ticker, stock, current_version)
    history_cards_html = ""
    
    if evolution_count == 0:
        history_cards_html = """
        <div class="empty-state-box" style="background: var(--bg-panel); border: 1px dashed var(--border-color); border-radius: 14px; padding: 75px 24px;">
            <div class="empty-state-title">Initial Baseline Active</div>
            <div class="empty-state-sub">Version 1 represents the initial underwriting thesis. Future revisions, price trigger reviews, and catalyst audits will be logged here</div>
        </div>
        """
    else:
        # Show actual evolution revisions (v2, v3, ...)
        for v in reversed(history):
            if v.version == 1:
                continue
            is_current = (v.version == len(history))
            v_labels_html = format_labels_pills(v.labels or [v.status_label])

            # Check if labels evolved in this version
            v_idx = history.index(v)
            v_prev = history[v_idx - 1] if v_idx > 0 else None
            v_label_diff = ""
            if v_prev:
                p_lbls = v_prev.labels or [v_prev.status_label]
                c_lbls = v.labels or [v.status_label]
                if p_lbls != c_lbls:
                    p_pills = " ".join([f'<span class="pill pill-neutral" style="font-size:0.75rem;">{l}</span>' for l in p_lbls])
                    c_pills = " ".join([f'<span class="pill pill-active" style="font-size:0.75rem;">{l}</span>' for l in c_lbls])
                    v_label_diff = f"""
                    <div style="margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--border-color); font-size: 0.84rem;">
                        <div style="font-weight: 500; color: var(--text-title); margin-bottom: 6px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                            <span style="color: var(--accent-warm);">🏷️ Label & Conviction Evolution:</span>
                            <div style="display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                                {p_pills}
                                <span style="color: var(--text-dim);">→</span>
                                {c_pills}
                            </div>
                        </div>
                    </div>
                    """

            diff_box = ""
            if v.what_was_before or v.what_changes_now:
                diff_box = f"""
                <div class="diff-grid">
                    <div class="diff-box diff-prev">
                        <div class="diff-label">PREVIOUS THESIS</div>
                        <div class="diff-text">{v.what_was_before or 'Previous stance'}</div>
                    </div>
                    <div class="diff-box diff-now">
                        <div class="diff-label">THESIS EVOLUTION</div>
                        <div class="diff-text">
                            {v.what_changes_now or v.summary_of_change}
                            {v_label_diff}
                        </div>
                    </div>
                </div>
                """
                
            v_beacon_html = format_action_beacon(getattr(v, "action_signal", None)) if v.version > 1 else ""
            sanitized_snapshot = clean_and_sanitize_html(v.full_html_content)
            history_cards_html += f"""
            <div class="history-entry {'history-entry-active' if is_current else ''}">
                <div class="history-top">
                    <div class="history-tags">
                        <span class="history-time">{v.date}</span>
                        <span class="history-price">${v.price_at_version:.2f}</span>
                        {v_beacon_html}
                        {v_labels_html}
                    </div>
                    <button class="btn btn-subtle" onclick="toggleSnapshot({v.version})">Read Snapshot ▾</button>
                </div>
                <div class="history-content">
                    <p class="history-shift-desc">{v.summary_of_change}</p>
                    {diff_box}
                    <div id="snapshot-{v.version}" class="snapshot-drawer" style="display: none;">
                        <div class="snapshot-body">
                            {sanitized_snapshot}
                        </div>
                    </div>
                </div>
            </div>
            """

    raw_active_content = clean_and_sanitize_html(current_version.full_html_content if current_version else "<p>No active thesis found.</p>")
    
    # Prepend highlighted evolution notes if this is an updated version (v2, v3, etc.)
    evolution_banner_html = ""
    if current_version and current_version.version > 1:
        v_diff = current_version.what_changes_now or current_version.summary_of_change
        v_trigger = getattr(current_version, "trigger_reason", "") or "Surveillance Review"
        
        # Check if labels changed from previous version
        label_change_html = ""
        prev_version = history[-2] if len(history) >= 2 else None
        if prev_version:
            prev_labels = prev_version.labels or [prev_version.status_label]
            curr_labels = current_version.labels or [current_version.status_label]
            if prev_labels != curr_labels:
                prev_pills = " ".join([f'<span class="pill pill-neutral" style="font-size:0.75rem;">{l}</span>' for l in prev_labels])
                curr_pills = " ".join([f'<span class="pill pill-active" style="font-size:0.75rem;">{l}</span>' for l in curr_labels])
                label_change_html = f"""
                <div class="label-evolution-divider" style="margin-top: 18px; padding-top: 14px; border-top: 1px dashed var(--border-color); font-size: 0.88rem;">
                    <div style="font-weight: 500; color: var(--text-title); margin-bottom: 6px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <span style="color: var(--accent-warm);">🏷️ Label & Conviction Evolution:</span>
                        <div style="display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                            {prev_pills}
                            <span style="color: var(--text-dim);">→</span>
                            {curr_pills}
                        </div>
                    </div>
                </div>
                """

        evolution_banner_html = f"""
        <div class="update-banner-box">
            <div class="update-banner-header">
                <span class="update-banner-badge">⚡ Version {current_version.version} Thesis Evolution • {current_version.date}</span>
                <span class="update-trigger-pill">Trigger: {v_trigger}</span>
            </div>
            <div class="update-banner-body">
                <div class="update-banner-title">What Changed & Forward Thesis Impact</div>
                <div class="update-banner-desc">
                    {v_diff}
                    {label_change_html}
                </div>
            </div>
        </div>
        """

    active_content = evolution_banner_html + raw_active_content
    chart_html = build_native_svg_chart(ticker, stock.current_price)
    dossier_beacon = format_action_beacon(getattr(stock, "action_signal", None)) if stock.total_versions > 1 else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{ticker} — Investment Memo</title>
    <link rel="icon" type="image/svg+xml" href="../favicon.svg">
    <link rel="apple-touch-icon" href="../favicon.svg">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;1,6..72,400&family=Plus+Jakarta+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <!-- KaTeX Math Engine for Typography-Grade LaTeX Equations -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css" crossorigin="anonymous">
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js" crossorigin="anonymous"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js" crossorigin="anonymous"></script>
    <style>
        :root {{
            --bg-canvas: #161513;
            --bg-panel: #1E1C19;
            --bg-subpanel: #252320;
            --bg-hover: #2D2A25;
            --text-title: #F5EFEB;
            --text-body: #D4CDC3;
            --text-secondary: #9E9689;
            --text-dim: #736C61;
            --accent-warm: #CC785C;
            --accent-warm-hover: #E08A6E;
            --accent-warm-subtle: rgba(204, 120, 92, 0.14);
            --accent-green: #6FA882;
            --accent-red: #D46E65;
            --border-color: rgba(235, 225, 210, 0.08);
            --border-focus: rgba(204, 120, 92, 0.38);
            --font-serif: 'Newsreader', Garamond, Georgia, serif;
            --font-sans: 'Plus Jakarta Sans', -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}

        /* KaTeX Math Styling & Dark Theme Alignment */
        .katex-display {{
            margin: 20px 0 !important;
            overflow-x: auto !important;
            overflow-y: hidden !important;
            padding: 12px 16px !important;
            background: rgba(0, 0, 0, 0.18) !important;
            border-radius: 8px !important;
            border: 1px solid var(--border-color) !important;
        }}
        .katex {{
            font-size: 1.08em !important;
            color: var(--text-title) !important;
        }}
        .katex .mord.text {{
            color: var(--text-body) !important;
            font-family: var(--font-serif) !important;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: 
                radial-gradient(ellipse 70% 40% at 50% -10%, rgba(204, 120, 92, 0.08), transparent 60%),
                var(--bg-canvas);
            color: var(--text-body);
            font-family: var(--font-serif);
            line-height: 1.85;
            -webkit-font-smoothing: antialiased;
            padding-bottom: 120px;
        }}

        .container {{ max-width: 960px; margin: 0 auto; padding: 0 24px; }}

        /* Top Nav */
        nav.nav-bar {{
            background: rgba(22, 21, 19, 0.88);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
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
            transition: all 0.15s;
        }}
        .nav-back:hover {{ color: var(--accent-warm-hover); transform: translateX(-2px); }}

        /* Hero Deck */
        .hero-deck {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 36px 40px;
            margin: 32px 0 28px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.02);
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
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 16px 20px 12px;
            position: relative;
            user-select: none;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
        }}
        .chart-top-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            padding-bottom: 6px;
            min-height: 28px;
        }}
        .chart-live-val {{
            font-size: 0.88rem;
            font-family: var(--font-mono);
            color: var(--text-secondary);
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .chart-range-pills {{
            display: flex;
            gap: 4px;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 2px;
        }}
        .range-pill {{
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 0.72rem;
            font-family: var(--font-sans);
            font-weight: 500;
            padding: 4px 10px;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .range-pill:hover {{ color: var(--text-title); }}
        .range-pill.active {{
            background: var(--accent-warm);
            color: #161513;
            font-weight: 600;
            box-shadow: 0 1px 4px rgba(204, 120, 92, 0.3);
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
            z-index: 10;
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
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin-top: 24px;
        }}
        @media (max-width: 960px) {{
            .metrics-grid {{ grid-template-columns: repeat(2, 1fr); }}
        }}
        @media (max-width: 520px) {{
            .metrics-grid {{ grid-template-columns: 1fr; }}
        }}
        .metric-cell {{
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 14px 16px;
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
            min-height: 80px;
            box-sizing: border-box;
        }}
        .metric-label {{ font-size: 0.68rem; text-transform: uppercase; color: var(--text-dim); font-family: var(--font-sans); letter-spacing: 0.05em; margin-bottom: 3px; }}
        .metric-value {{ font-size: 1.15rem; font-weight: 500; color: var(--text-title); font-family: var(--font-mono); }}
        .metric-subtext {{ font-size: 0.72rem; color: var(--text-muted); font-family: var(--font-sans); margin-top: 4px; line-height: 1.25; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

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

        /* Ownership, Insiders & Fund Intelligence Tab */
        .ownership-container {{
            display: flex;
            flex-direction: column;
            gap: 28px;
        }}
        .ownership-header-card {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 24px 28px;
        }}
        .ownership-stat-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
        }}
        @media (max-width: 768px) {{
            .ownership-stat-grid {{ grid-template-columns: 1fr; }}
        }}
        .stat-box {{
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .stat-label {{
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-dim);
            font-family: var(--font-sans);
        }}
        .stat-num {{
            font-size: 1.45rem;
            font-weight: 500;
            font-family: var(--font-mono);
            color: var(--text-title);
        }}
        .stat-note {{
            font-size: 0.76rem;
            color: var(--text-muted);
            font-family: var(--font-sans);
        }}
        .ownership-section {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 28px 32px;
        }}
        .section-title-row {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 6px;
        }}
        .section-icon {{ font-size: 1.35rem; }}
        .section-heading {{
            font-family: var(--font-serif);
            font-size: 1.35rem;
            color: var(--text-title);
            margin: 0;
            letter-spacing: -0.01em;
        }}
        .section-desc {{
            color: var(--text-dim);
            font-size: 0.86rem;
            margin: 0 0 20px;
            line-height: 1.4;
        }}
        .table-responsive {{
            width: 100%;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            border-radius: 12px;
            border: 1px solid var(--border-color);
            background: var(--bg-subpanel);
            margin-top: 14px;
        }}
        .ownership-table {{
            width: 100%;
            min-width: 980px;
            border-collapse: collapse;
            font-size: 0.86rem;
        }}
        .ownership-table th {{
            text-align: left;
            padding: 13px 16px;
            font-size: 0.70rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-dim);
            border-bottom: 1px solid var(--border-color);
            background: #1E1D1A;
            font-family: var(--font-sans);
            white-space: nowrap;
        }}
        .ownership-table td {{
            padding: 12px 16px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.035);
            vertical-align: middle;
            white-space: nowrap;
        }}
        .ownership-table tr:last-child td {{
            border-bottom: none;
        }}
        .ownership-table tr:hover td {{
            background: rgba(255, 255, 255, 0.02);
        }}
        .link-out {{
            color: var(--accent-warm);
            text-decoration: none;
            font-size: 0.82rem;
            font-weight: 500;
            transition: color 0.15s ease;
        }}
        .link-out:hover {{
            color: #fcd34d;
            text-decoration: underline;
        }}
        .writeups-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
        }}
        .writeup-card {{
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 22px 24px;
            display: flex;
            flex-direction: column;
            transition: border-color 0.15s ease;
        }}
        .writeup-card:hover {{
            border-color: rgba(217, 119, 6, 0.4);
        }}
        .btn-read-letter {{
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: rgba(217, 119, 6, 0.12);
            color: var(--accent-warm);
            border: 1px solid rgba(217, 119, 6, 0.25);
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 0.76rem;
            font-weight: 500;
            text-decoration: none;
            white-space: nowrap;
            transition: all 0.15s ease;
        }}
        .btn-read-letter:hover {{
            background: rgba(217, 119, 6, 0.25);
            color: #fcd34d;
        }}

        /* Quick Portals Bar */
        .quick-portals-bar {{
            display: flex;
            align-items: center;
            gap: 14px;
            margin-top: 20px;
            padding-top: 16px;
            border-top: 1px solid var(--border-color);
            flex-wrap: wrap;
        }}
        .portal-links-group {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .portal-link {{
            background: var(--bg-subpanel);
            color: var(--text-secondary);
            border: 1px solid var(--border-color);
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 0.78rem;
            font-family: var(--font-sans);
            font-weight: 500;
            text-decoration: none;
            transition: all 0.15s ease;
            display: inline-flex;
            align-items: center;
        }}
        .portal-link:hover {{
            background: rgba(201, 154, 117, 0.14);
            border-color: var(--accent-warm);
            color: var(--accent-warm);
            transform: translateY(-1px);
        }}

        /* Memo Content & Premium Editorial Typography */
        .memo-container {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 48px 52px;
        }}
        .memo-container * {{
            box-sizing: border-box;
        }}
        .memo-container a {{
            color: var(--accent-warm) !important;
            text-decoration: none !important;
            transition: color 0.15s ease !important;
            border-bottom: 1px dotted rgba(201, 154, 117, 0.4) !important;
        }}
        .memo-container a:hover {{
            color: #E2DDD5 !important;
            border-bottom-color: var(--accent-warm) !important;
        }}
        .memo-container h1, .memo-container h2 {{
            font-family: var(--font-serif) !important;
            font-size: 1.55rem !important;
            font-weight: 500 !important;
            color: var(--text-title) !important;
            margin: 44px 0 18px !important;
            padding-bottom: 10px !important;
            border-bottom: 1px solid var(--border-color) !important;
            letter-spacing: -0.02em !important;
            line-height: 1.35 !important;
        }}
        .memo-container h1:first-child, .memo-container h2:first-of-type {{ margin-top: 0 !important; }}
        .memo-container h3 {{
            font-family: var(--font-serif) !important;
            font-size: 1.28rem !important;
            font-weight: 500 !important;
            color: var(--accent-warm) !important;
            margin: 32px 0 14px !important;
            line-height: 1.4 !important;
        }}
        .memo-container h4, .memo-container h5, .memo-container h6 {{
            font-family: var(--font-serif) !important;
            font-size: 1.12rem !important;
            font-weight: 600 !important;
            color: var(--text-title) !important;
            margin: 24px 0 10px !important;
        }}
        .memo-container p {{
            font-family: var(--font-serif) !important;
            font-size: 1.15rem !important;
            line-height: 1.9 !important;
            color: var(--text-body) !important;
            margin-bottom: 22px !important;
        }}
        .memo-container ul, .memo-container ol {{
            font-family: var(--font-serif) !important;
            font-size: 1.12rem !important;
            line-height: 1.85 !important;
            color: var(--text-body) !important;
            margin: 16px 0 24px 24px !important;
            padding-left: 12px !important;
        }}
        .memo-container ul {{ list-style-type: disc !important; }}
        .memo-container ol {{ list-style-type: decimal !important; }}
        .memo-container li {{
            margin-bottom: 12px !important;
            color: var(--text-body) !important;
            line-height: 1.85 !important;
        }}
        .memo-container li::marker {{
            color: var(--accent-warm) !important;
        }}
        .memo-container strong, .memo-container b {{
            color: var(--text-title) !important;
            font-weight: 600 !important;
        }}

        /* STUNNING CONSISTENT TABLES - SOOTHING WARM TONES & ZERO OVERFLOW */
        .table-scroll-wrap {{
            width: 100% !important;
            overflow-x: auto !important;
            -webkit-overflow-scrolling: touch !important;
            margin: 32px 0 !important;
            background: #171614 !important;
            background-color: #171614 !important;
            border-radius: 12px !important;
            border: 1px solid rgba(215, 205, 190, 0.08) !important;
            box-sizing: border-box !important;
        }}
        .memo-container table {{
            width: 100% !important;
            min-width: 600px !important;
            border-collapse: separate !important;
            border-spacing: 0 !important;
            margin: 0 !important;
            background: transparent !important;
            background-color: transparent !important;
            border: none !important;
        }}
        .memo-container tr, .memo-container td, .memo-container th {{
            background: transparent !important;
            background-color: transparent !important;
        }}
        .memo-container th {{
            background: #1E1D1A !important;
            background-color: #1E1D1A !important;
            color: #C99A75 !important;
            font-family: var(--font-sans) !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.06em !important;
            padding: 14px 18px !important;
            border-bottom: 1px solid rgba(215, 205, 190, 0.08) !important;
            text-align: left !important;
        }}
        .memo-container td {{
            padding: 14px 18px !important;
            border-bottom: 1px solid rgba(215, 205, 190, 0.05) !important;
            font-size: 0.92rem !important;
            color: #BDB7AA !important;
            font-family: var(--font-mono) !important;
            text-align: left !important;
        }}
        .memo-container tr:last-child td {{
            border-bottom: none !important;
        }}
        .memo-container tr:nth-child(even) td {{
            background: rgba(255, 255, 255, 0.012) !important;
            background-color: rgba(255, 255, 255, 0.012) !important;
        }}
        .memo-container tr:hover td {{
            background: rgba(201, 154, 117, 0.04) !important;
            background-color: rgba(201, 154, 117, 0.04) !important;
        }}
        .memo-container td strong, .memo-container td b {{
            color: #D8D2C6 !important;
            font-weight: 500 !important;
        }}

        /* UNIVERSAL CALLOUT & BOX STYLING - NEVER WHITE OR PINK, STRICT DARK OBSIDIAN */
        .memo-container blockquote,
        .memo-container .callout,
        .memo-container .falsification-box,
        .memo-container .institutional-box,
        .memo-container div[class*="box"],
        .memo-container div[class*="card"],
        .memo-container div[class*="alert"],
        .memo-container div[class*="warning"],
        .memo-container div[class*="highlight-box"] {{
            background: var(--bg-subpanel) !important;
            background-color: var(--bg-subpanel) !important;
            border: 1px solid rgba(215, 205, 190, 0.08) !important;
            border-left: 3px solid var(--accent-warm) !important;
            padding: 22px 26px !important;
            border-radius: 8px !important;
            margin: 28px 0 !important;
            color: var(--text-body) !important;
            line-height: 1.8 !important;
        }}
        .memo-container blockquote *,
        .memo-container .callout *,
        .memo-container .falsification-box *,
        .memo-container .institutional-box *,
        .memo-container div[class*="box"] *,
        .memo-container div[class*="card"] *,
        .memo-container div[class*="alert"] * {{
            background: transparent !important;
            background-color: transparent !important;
            color: var(--text-body) !important;
        }}
        .memo-container blockquote h3,
        .memo-container blockquote h4,
        .memo-container .callout h3,
        .memo-container .callout h4,
        .memo-container .falsification-box h4,
        .memo-container .falsification-box strong,
        .memo-container .institutional-box h4,
        .memo-container .institutional-box strong,
        .memo-container div[class*="box"] h4,
        .memo-container div[class*="box"] strong,
        .memo-container div[class*="card"] strong {{
            color: var(--text-title) !important;
        }}

        /* EXECUTIVE COMMENTARY & TRANSCRIPT QUOTE CARDS */
        .memo-container .executive-callout {{
            background: radial-gradient(ellipse 80% 50% at 50% 0%, rgba(204, 120, 92, 0.05), transparent 70%), var(--bg-subpanel) !important;
            border: 1px solid rgba(204, 120, 92, 0.22) !important;
            border-left: 4px solid var(--accent-warm) !important;
            border-radius: 10px !important;
            padding: 24px 28px !important;
            margin: 32px 0 !important;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25) !important;
        }}
        .memo-container .exec-header {{
            display: flex !important;
            align-items: center !important;
            flex-wrap: wrap !important;
            gap: 10px !important;
            margin-bottom: 18px !important;
            padding-bottom: 12px !important;
            border-bottom: 1px solid rgba(235, 225, 210, 0.07) !important;
        }}
        .memo-container .exec-badge {{
            font-family: var(--font-sans) !important;
            font-size: 0.72rem !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.08em !important;
            color: var(--accent-warm) !important;
            background: rgba(204, 120, 92, 0.12) !important;
            padding: 4px 10px !important;
            border-radius: 4px !important;
            border: 1px solid rgba(204, 120, 92, 0.24) !important;
        }}
        .memo-container .exec-sub {{
            font-family: var(--font-sans) !important;
            font-size: 0.82rem !important;
            font-weight: 500 !important;
            color: var(--text-secondary) !important;
        }}
        .memo-container .executive-callout p em,
        .memo-container .executive-callout blockquote {{
            font-family: var(--font-serif) !important;
            font-style: italic !important;
            font-size: 1.05rem !important;
            line-height: 1.8 !important;
            color: var(--text-title) !important;
            display: block !important;
            margin: 8px 0 !important;
        }}
        .memo-container .exec-attribution {{
            font-family: var(--font-sans) !important;
            font-size: 0.84rem !important;
            color: var(--text-secondary) !important;
            margin-top: 6px !important;
            margin-bottom: 16px !important;
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
        }}
        .memo-container .exec-attribution::before {{
            content: "—";
            color: var(--accent-warm) !important;
            font-weight: 600 !important;
            margin-right: 2px !important;
        }}
        .memo-container .exec-attribution strong {{
            color: var(--text-title) !important;
            font-weight: 600 !important;
        }}
        .memo-container .exec-divider {{
            height: 1px !important;
            background: linear-gradient(90deg, transparent, rgba(235, 225, 210, 0.10), transparent) !important;
            margin: 20px 0 !important;
        }}
        .memo-container hr {{
            border: none !important;
            height: 1px !important;
            background: linear-gradient(90deg, transparent, rgba(235, 225, 210, 0.10), transparent) !important;
            margin: 24px 0 !important;
        }}
        .highlight, mark {{
            background: rgba(201, 154, 117, 0.16) !important;
            color: #E2DDD5 !important;
            padding: 2px 6px;
            border-radius: 4px;
        }}

        /* FINANCIAL METRIC CARDS & STAT GRIDS */
        .metrics-grid, .stats-grid, .grid-3, .grid-4, .grid-2, .metric-grid {{
            display: grid !important;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)) !important;
            gap: 16px !important;
            margin: 28px 0 !important;
        }}
        .metric-card, .stat-card, div[class*="metric-box"], div[class*="stat-box"], div[class*="kpi-card"] {{
            background: var(--bg-subpanel) !important;
            background-color: var(--bg-subpanel) !important;
            border: 1px solid rgba(215, 205, 190, 0.08) !important;
            border-radius: 10px !important;
            padding: 18px 20px !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
            box-sizing: border-box !important;
        }}
        .metric-label, .stat-label, .kpi-label {{
            font-family: var(--font-sans) !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.06em !important;
            color: var(--text-secondary) !important;
            margin-bottom: 6px !important;
        }}
        .metric-value, .stat-value, .kpi-value {{
            font-family: var(--font-mono) !important;
            font-size: 1.4rem !important;
            font-weight: 600 !important;
            color: var(--text-title) !important;
            letter-spacing: -0.02em !important;
            line-height: 1.2 !important;
            margin-bottom: 4px !important;
        }}
        .metric-delta, .metric-sub, .stat-sub, .kpi-sub {{
            font-family: var(--font-mono) !important;
            font-size: 0.82rem !important;
            color: var(--accent-warm) !important;
        }}

        /* EMBEDDED IMAGES, CHARTS & VISUAL INFOGRAPHICS */
        .figure-container, figure {{
            margin: 32px 0 !important;
            text-align: center !important;
            background: var(--bg-subpanel) !important;
            border: 1px solid rgba(215, 205, 190, 0.08) !important;
            border-radius: 12px !important;
            padding: 16px !important;
            overflow: hidden !important;
        }}
        .memo-container img {{
            max-width: 100% !important;
            height: auto !important;
            border-radius: 8px !important;
            display: block !important;
            margin: 0 auto !important;
            border: 1px solid rgba(215, 205, 190, 0.08) !important;
        }}
        .figure-caption, figcaption {{
            font-family: var(--font-sans) !important;
            font-size: 0.8rem !important;
            color: var(--text-secondary) !important;
            margin-top: 10px !important;
            text-align: center !important;
        }}

        /* Evolution Update Highlight Banner at top of Memo */
        .update-banner-box {{
            background: #1C1B18 !important;
            border: 1px solid rgba(201, 154, 117, 0.3) !important;
            border-left: 4px solid var(--accent-warm) !important;
            border-radius: 12px !important;
            padding: 24px 28px !important;
            margin-bottom: 36px !important;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25) !important;
        }}
        .update-banner-header {{
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
            flex-wrap: wrap !important;
            gap: 10px !important;
            margin-bottom: 14px !important;
            padding-bottom: 10px !important;
            border-bottom: 1px solid rgba(215, 205, 190, 0.08) !important;
        }}
        .update-banner-badge {{
            font-family: var(--font-sans) !important;
            font-size: 0.76rem !important;
            font-weight: 600 !important;
            color: var(--accent-warm) !important;
            letter-spacing: 0.04em !important;
            text-transform: uppercase !important;
        }}
        .update-trigger-pill {{
            font-family: var(--font-mono) !important;
            font-size: 0.74rem !important;
            color: var(--text-secondary) !important;
            background: var(--bg-subpanel) !important;
            padding: 3px 10px !important;
            border-radius: 4px !important;
            border: 1px solid var(--border-color) !important;
        }}
        .update-banner-title {{
            font-family: var(--font-serif) !important;
            font-size: 1.22rem !important;
            font-weight: 600 !important;
            color: var(--text-title) !important;
            margin-bottom: 8px !important;
        }}
        .update-banner-desc {{
            font-family: var(--font-serif) !important;
            font-size: 1.08rem !important;
            line-height: 1.8 !important;
            color: var(--text-body) !important;
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
        .diff-text {{ font-size: 1.02rem; color: var(--text-body); line-height: 1.65; }}

        /* Pills */
        .pill {{
            display: inline-flex;
            align-items: center;
            padding: 3px 11px;
            border-radius: 9999px;
            font-size: 0.72rem;
            font-family: var(--font-sans);
            letter-spacing: 0.03em;
            white-space: nowrap;
        }}
        .pill-active {{ background: rgba(201, 154, 117, 0.12); color: var(--accent-warm); border: 1px solid rgba(201, 154, 117, 0.45); font-weight: 600; box-shadow: 0 0 10px rgba(201, 154, 117, 0.06); }}
        .pill-neutral {{ background: var(--bg-subpanel); color: var(--text-secondary); border: 1px solid var(--border-color); font-weight: 500; }}
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

        /* Subtle Hinge-style Status Pulse Beacon */
        .status-beacon {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            position: relative;
            width: 9px;
            height: 9px;
            margin-left: 7px;
            vertical-align: middle;
            cursor: help;
        }}
        .beacon-dot {{
            width: 6px;
            height: 6px;
            border-radius: 50%;
            position: relative;
            z-index: 2;
        }}
        .beacon-ping {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            animation: beacon-ripple 2.2s cubic-bezier(0, 0, 0.2, 1) infinite;
            z-index: 1;
        }}
        .beacon-buy .beacon-dot {{ background-color: #10b981; box-shadow: 0 0 6px rgba(16, 185, 129, 0.7); }}
        .beacon-buy .beacon-ping {{ background-color: rgba(16, 185, 129, 0.45); }}
        .beacon-hold .beacon-dot {{ background-color: #f59e0b; box-shadow: 0 0 6px rgba(245, 158, 11, 0.7); }}
        .beacon-hold .beacon-ping {{ background-color: rgba(245, 158, 11, 0.45); }}
        .beacon-caution .beacon-dot {{ background-color: #f97316; box-shadow: 0 0 6px rgba(249, 115, 22, 0.7); }}
        .beacon-caution .beacon-ping {{ background-color: rgba(249, 115, 22, 0.45); }}
        .beacon-avoid .beacon-dot {{ background-color: #ef4444; box-shadow: 0 0 6px rgba(239, 68, 68, 0.7); }}
        .beacon-avoid .beacon-ping {{ background-color: rgba(239, 68, 68, 0.45); }}
        @keyframes beacon-ripple {{
            0% {{ transform: scale(0.9); opacity: 0.85; }}
            70% {{ transform: scale(2.5); opacity: 0; }}
            100% {{ transform: scale(2.5); opacity: 0; }}
        }}

        .pos {{ color: var(--accent-green); }}
        .neg {{ color: var(--accent-red); }}

        /* Info Circle Button */
        .btn-info-circle {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            color: var(--text-dim);
            font-size: 0.72rem;
            font-family: var(--font-mono);
            cursor: pointer;
            margin-left: 6px;
            vertical-align: middle;
            transition: all 0.15s ease;
            padding: 0;
            line-height: 1;
        }}
        .btn-info-circle:hover {{
            background: var(--bg-hover);
            border-color: var(--accent-warm);
            color: var(--accent-warm);
            transform: scale(1.1);
        }}

        /* Modal */
        .modal-shade {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(10, 10, 9, 0.85);
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
        .btn-primary {{
            background: var(--accent-warm); color: #141312; font-family: var(--font-sans); font-weight: 500;
            padding: 10px 20px; border-radius: 6px; text-decoration: none; display: inline-flex; align-items: center; border: none; cursor: pointer;
            transition: all 0.15s;
        }}
        .btn-primary:hover {{ background: #DDB495; }}
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
                        <span class="ticker-symbol">{stock.ticker}{dossier_beacon}</span>
                        {labels_html}
                        <button type="button" class="btn-info-circle" onclick="openLabelsLegendModal(event)" title="View Investment Taxonomy & Labels Legend">ⓘ</button>
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

            <!-- Native Multi-Range Interactive Area Chart -->
            {chart_html}

            <!-- Key Metrics Grid -->
            <div class="metrics-grid">
                <div class="metric-cell">
                    <div class="metric-label">Fair Value</div>
                    <div class="metric-value" style="color: var(--accent-warm);">{format_usd_target(stock.fair_value_estimate)}</div>
                    <div class="metric-subtext" style="color: var(--text-dim);">Intrinsic baseline</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Bear Target</div>
                    <div class="metric-value" style="color: var(--accent-red);">{stock.bear_target}</div>
                    <div class="metric-subtext" style="color: var(--text-dim);">Downside floor</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Base Target</div>
                    <div class="metric-value">{stock.base_target}</div>
                    <div class="metric-subtext" style="color: var(--text-dim);">Mid-cycle value</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Bull Target</div>
                    <div class="metric-value" style="color: var(--accent-green);">{stock.bull_target}</div>
                    <div class="metric-subtext" style="color: var(--text-dim);">Asymmetric upside</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Alert Corridor</div>
                    <div class="metric-value" style="font-size: 1.05rem; font-family: var(--font-mono); color: var(--text-title);">${stock.lower_alert_threshold:.2f} ⇄ ${stock.upper_alert_threshold:.2f}</div>
                    <div class="metric-subtext" style="color: var(--text-dim);">Surveillance triggers</div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Next Catalyst</div>
                    <div class="metric-value" style="font-size: 0.88rem; font-family: var(--font-sans);">{stock.next_catalyst_date or 'TBD'}</div>
                    <div class="metric-subtext" style="color: var(--text-dim);">{stock.next_catalyst_event or 'Calendar review'}</div>
                </div>
                {format_top_funds_card_html(stock)}
                {format_insider_activity_card_html(stock)}
            </div>
        </section>

        <!-- Navigation Tabs -->
        <div class="tabs-header">
            <button id="btn-tab-memo" class="tab-btn active" onclick="showTab('memo')">Investment Thesis</button>
            <button id="btn-tab-history" class="tab-btn" onclick="showTab('history')">Evolution ({evolution_count})</button>
            <button id="btn-tab-ownership" class="tab-btn" onclick="showTab('ownership')">Ownership & Fund Intel</button>
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

        <!-- Ownership & Fund Intel Content -->
        <div id="tab-ownership" class="tab-content">
            {ownership_tab_html}
        </div>
    </main>

    {build_labels_legend_modal_html()}

    <script>
        function showTab(id) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            const btn = document.getElementById('btn-tab-' + id);
            const content = document.getElementById('tab-' + id);
            if (btn && content) {{
                btn.classList.add('active');
                content.classList.add('active');
                setTimeout(renderLatexEquations, 20);
            }}
        }}

        function toggleSnapshot(ver) {{
            const el = document.getElementById('snapshot-' + ver);
            el.style.display = (el.style.display === 'none' ? 'block' : 'none');
            if (el.style.display === 'block') {{
                setTimeout(renderLatexEquations, 20);
            }}
        }}

        function openLabelsLegendModal(event) {{
            if (event) {{
                event.stopPropagation();
                event.preventDefault();
            }}
            const modal = document.getElementById('labels-legend-modal');
            if (modal) modal.style.display = 'flex';
        }}

        function closeLabelsLegendModal() {{
            const modal = document.getElementById('labels-legend-modal');
            if (modal) modal.style.display = 'none';
        }}

        function closeLegendModalOutside(event) {{
            if (event.target.id === 'labels-legend-modal') {{
                closeLabelsLegendModal();
            }}
        }}

        function renderLatexEquations() {{
            if (typeof renderMathInElement === 'function') {{
                renderMathInElement(document.body, {{
                    delimiters: [
                        {{left: '$$', right: '$$', display: true}},
                        {{left: '\\\\[', right: '\\\\]', display: true}},
                        {{left: '\\\\(', right: '\\\\)', display: false}}
                    ],
                    ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'],
                    throwOnError: false
                }});
            }}
        }}

        document.addEventListener("DOMContentLoaded", renderLatexEquations);
        window.addEventListener("load", renderLatexEquations);
        window.addEventListener("keydown", (e) => {{
            if (e.key === "Escape") {{
                closeEvolutionModal();
                closeLabelsLegendModal();
            }}
        }});
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
            <td colspan="5" style="border-bottom: none !important; padding: 0 !important;">
                <div class="empty-state-box">
                    <div class="empty-state-title">No Stocks Tracked</div>
                    <div class="empty-state-sub">Ready for coverage</div>
                </div>
            </td>
        </tr>
        """
        grid_cards_html = """
        <div style="grid-column: 1 / -1; background: var(--bg-panel); border: 1px dashed var(--border-color); border-radius: 14px;">
            <div class="empty-state-box">
                <div class="empty-state-title">No Stocks Tracked</div>
                <div class="empty-state-sub">Ready for coverage</div>
            </div>
        </div>
        """

    for ticker, stock in sorted(watchlist.items(), key=lambda x: x[0]):
        ret_class = "pos" if stock.return_pct >= 0 else "neg"
        labels_html = format_labels_pills(stock.labels or [stock.status_label])
        stock_beacon = format_action_beacon(getattr(stock, "action_signal", None)) if stock.total_versions > 1 else ""
        
        # Clean company name (preserve full name like JD.com, Inc. without cutting ticker prefix)
        clean_company = (stock.company_name or stock.ticker).strip().rstrip(".")

        # Clean percentage delta for fair value
        pct_delta_str = extract_pct_delta(stock.base_target, stock.current_price, stock.fair_value_estimate)

        # Clean catalyst description (max 4 words, no ellipses, wraps cleanly)
        safe_baseline = stock.baseline_price if stock.baseline_price > 0 else stock.current_price
        clean_catalyst_desc = sanitize_catalyst_desc(stock.next_catalyst_event).rstrip(".")

        table_rows_html += f"""
        <tr class="table-row" data-ticker="{stock.ticker}" data-baseline="{safe_baseline}" onclick="location.href='reports/{stock.ticker}.html'">
            <td>
                <div class="tbl-ticker-cell">
                    <span class="tbl-symbol">{stock.ticker}{stock_beacon}</span>
                    <span class="tbl-company-hover">{clean_company}</span>
                </div>
            </td>
            <td>
                <div class="tbl-price-cell">
                    <span class="tbl-price tbl-price-{stock.ticker}">${stock.current_price:.2f}</span>
                    <span class="tbl-return tbl-ret-{stock.ticker} {ret_class}">{stock.return_pct:+.2f}%</span>
                </div>
            </td>
            <td>
                <div class="tbl-labels-cell">
                    {labels_html}
                </div>
            </td>
            <td>
                <div class="tbl-val-cell">
                    <span class="tbl-fv" style="color: var(--accent-warm);">{format_usd_target(stock.fair_value_estimate)}</span>
                    {f'<span class="tbl-base">{pct_delta_str}</span>' if pct_delta_str else ''}
                </div>
            </td>
            <td>
                <div class="tbl-catalyst-cell">
                    <span class="tbl-cat-date">{stock.next_catalyst_date or 'TBD'}</span>
                    {f'<span class="tbl-cat-desc">{clean_catalyst_desc}</span>' if clean_catalyst_desc else ''}
                    {f'<span class="tbl-corridor" style="font-size: 0.74rem; color: var(--text-dim); font-family: var(--font-mono); display: block; margin-top: 4px;">Alerts: ${stock.lower_alert_threshold:.2f} ⇄ ${stock.upper_alert_threshold:.2f}</span>' if (stock.lower_alert_threshold and stock.upper_alert_threshold) else ''}
                </div>
            </td>
        </tr>
        """

        grid_cards_html += f"""
        <div class="grid-card" data-ticker="{stock.ticker}" data-baseline="{safe_baseline}" onclick="location.href='reports/{stock.ticker}.html'">
            <div class="grid-card-top">
                <span class="grid-symbol">{stock.ticker}{stock_beacon}</span>
                <div class="grid-price grid-price-{stock.ticker}">${stock.current_price:.2f}</div>
            </div>
            <div class="grid-labels-row" style="margin: 6px 0 14px;">
                {labels_html}
            </div>
            <div class="grid-company">{clean_company}</div>
            
            <div class="grid-metrics-box">
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Return</span>
                    <span class="grid-stat-val grid-ret-{stock.ticker} {ret_class}">{stock.return_pct:+.2f}%</span>
                </div>
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Fair Value</span>
                    <span class="grid-stat-val" style="color: var(--accent-warm);">{format_usd_target(stock.fair_value_estimate)}</span>
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
    for a in alerts:
        ret_class = "pos" if a.price_change_pct >= 0 else "neg"
        labels_html = format_labels_pills(a.labels or [a.severity])
        alert_beacon = format_action_beacon(getattr(a, "action_signal", None))
        alert_id = f"{a.ticker}_{a.timestamp.replace(' ', '_').replace(':', '')}"
        safe_payload = json.dumps({
            "id": alert_id,
            "ticker": a.ticker,
            "title": a.title.rstrip("."),
            "timestamp": a.timestamp,
            "severity": a.severity,
            "price": a.price_at_alert,
            "change": a.price_change_pct,
            "trigger_reason": a.trigger_reason.rstrip("."),
            "what_was_before": a.what_was_before.rstrip("."),
            "what_changes_now": a.what_changes_now.rstrip("."),
            "report_url": a.report_url
        }).replace("'", "&#39;").replace('"', "&quot;")

        clean_blurb = a.what_changes_now[:220].rstrip(".")

        alerts_feed_html += f"""
        <div class="alert-item" data-alert-id="{alert_id}" onclick='openAlertModal({safe_payload})'>
            <div class="alert-left">
                <div class="alert-badges">
                    <strong class="alert-ticker">{a.ticker}{alert_beacon}</strong>
                    {labels_html}
                    <span class="alert-time">{a.timestamp}</span>
                </div>
                <div class="alert-title">{a.title.rstrip(".")}</div>
                <div class="alert-blurb">{clean_blurb}</div>
            </div>
            <div class="alert-right" style="display:flex; align-items:center; gap:16px;">
                <div style="text-align:right;">
                    <div class="alert-price-val">${a.price_at_alert:.2f}</div>
                    <div class="alert-price-pct {ret_class}">{a.price_change_pct:+.2f}%</div>
                </div>
                <button class="alert-dismiss-btn" title="Dismiss this alert" onclick="event.stopPropagation(); dismissAlert('{alert_id}')">✕</button>
            </div>
        </div>
        """

    empty_alerts_html = """
    <div id="empty-alerts-box" class="empty-alerts" style="{display_style}">
        <div class="empty-title">No Active Alerts</div>
        <div class="empty-sub">All positions within normal corridors</div>
    </div>
    """
    disp_style = "display: flex;" if not alerts else "display: none;"
    alerts_feed_html = alerts_feed_html + empty_alerts_html.format(display_style=disp_style)

    from stocks.portfolio import build_portfolio_tab_html, get_enriched_portfolio
    portfolio_defensive_html = build_portfolio_tab_html("defensive", 200000.0)
    portfolio_aggressive_html = build_portfolio_tab_html("aggressive", 200000.0)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>AlphaThesis</title>
    <link rel="icon" type="image/svg+xml" href="favicon.svg">
    <link rel="apple-touch-icon" href="favicon.svg">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;1,6..72,400&family=Plus+Jakarta+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <!-- KaTeX Math Engine for Typography-Grade LaTeX Equations -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css" crossorigin="anonymous">
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js" crossorigin="anonymous"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js" crossorigin="anonymous"></script>
    <style>
        :root {{
            --bg-canvas: #161513;
            --bg-panel: #1E1C19;
            --bg-subpanel: #252320;
            --bg-hover: #2D2A25;
            --text-title: #F5EFEB;
            --text-body: #D4CDC3;
            --text-secondary: #9E9689;
            --text-dim: #736C61;
            --accent-warm: #CC785C;
            --accent-warm-hover: #E08A6E;
            --accent-warm-subtle: rgba(204, 120, 92, 0.14);
            --accent-green: #6FA882;
            --accent-red: #D46E65;
            --border-color: rgba(235, 225, 210, 0.08);
            --border-focus: rgba(204, 120, 92, 0.38);
            --font-serif: 'Newsreader', Garamond, Georgia, serif;
            --font-sans: 'Plus Jakarta Sans', -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}

        /* KaTeX Math Styling & Dark Theme Alignment */
        .katex-display {{
            margin: 20px 0 !important;
            overflow-x: auto !important;
            overflow-y: hidden !important;
            padding: 12px 16px !important;
            background: rgba(0, 0, 0, 0.18) !important;
            border-radius: 8px !important;
            border: 1px solid var(--border-color) !important;
        }}
        .katex {{
            font-size: 1.08em !important;
            color: var(--text-title) !important;
        }}
        .katex .mord.text {{
            color: var(--text-body) !important;
            font-family: var(--font-serif) !important;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: 
                radial-gradient(ellipse 70% 40% at 50% -10%, rgba(204, 120, 92, 0.08), transparent 60%),
                var(--bg-canvas);
            color: var(--text-body);
            font-family: var(--font-serif);
            min-height: 100vh;
            -webkit-font-smoothing: antialiased;
            padding-bottom: 120px;
        }}

        .container {{ max-width: 1000px; margin: 0 auto; padding: 0 24px; }}

        /* Header */
        header.nav-header {{
            background: rgba(22, 21, 19, 0.88);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 100;
            padding: 18px 0;
        }}
        .header-content {{ display: flex; justify-content: space-between; align-items: center; }}
        .brand-logo {{
            font-family: var(--font-serif);
            font-size: 1.45rem;
            font-weight: 500;
            letter-spacing: -0.01em;
            color: var(--text-title);
            text-decoration: none;
            transition: color 0.15s;
        }}
        .brand-logo:hover {{ color: var(--accent-warm-hover); }}

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
        .hub-tab-btn.active {{ color: var(--accent-warm); font-weight: 500; }}
        .hub-tab-btn.active::after {{
            content: '';
            position: absolute;
            bottom: -15px;
            left: 0; right: 0;
            height: 2px;
            background: var(--accent-warm);
            box-shadow: 0 0 8px rgba(204, 120, 92, 0.4);
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

        .search-input-wrap {{
            display: flex;
            align-items: center;
            gap: 8px;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 5px 12px;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
        }}
        .search-input-wrap:focus-within {{
            border-color: var(--accent-warm);
            box-shadow: 0 0 0 3px rgba(204, 120, 92, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.02);
        }}
        .search-input {{
            background: transparent !important;
            background-color: transparent !important;
            border: none !important;
            color: var(--text-title) !important;
            font-family: var(--font-sans);
            font-size: 0.82rem;
            outline: none !important;
            width: 200px;
            box-shadow: none !important;
        }}
        .search-input:focus,
        .search-input:active {{
            background: transparent !important;
            background-color: transparent !important;
            color: var(--text-title) !important;
            outline: none !important;
            box-shadow: none !important;
        }}
        .search-input:-webkit-autofill,
        .search-input:-webkit-autofill:hover,
        .search-input:-webkit-autofill:focus,
        .search-input:-webkit-autofill:active {{
            -webkit-box-shadow: 0 0 0 30px #181614 inset !important;
            -webkit-text-fill-color: #E8E4DF !important;
            caret-color: #E8E4DF !important;
            transition: background-color 5000s ease-in-out 0s;
        }}
        .search-input::placeholder {{
            color: var(--text-dim);
        }}

        .tab-panel {{ display: none; }}
        .tab-panel.active {{ display: block; }}

        /* Table View */
        .table-wrap {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.02);
        }}
        table.fin-table {{
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            text-align: left;
        }}
        table.fin-table th {{
            background: var(--bg-subpanel);
            color: var(--text-dim);
            font-family: var(--font-sans);
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-color);
        }}
        table.fin-table td {{
            padding: 18px 20px;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.96rem;
            color: var(--text-body);
            vertical-align: middle;
        }}
        table.fin-table th:first-child, table.fin-table td:first-child {{
            padding-left: 28px;
        }}
        table.fin-table th:last-child, table.fin-table td:last-child {{
            padding-right: 28px;
        }}
        .table-row {{ cursor: pointer; transition: background 0.15s cubic-bezier(0.16, 1, 0.3, 1); position: relative; }}
        .table-row:hover {{ background: rgba(204, 120, 92, 0.035); }}
        .table-row:last-child td {{ border-bottom: none; }}

        /* Spacious Ticker Column with No Overlap */
        .tbl-ticker-cell {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            line-height: 1.3;
        }}
        .tbl-symbol {{
            font-family: var(--font-serif);
            font-size: 1.35rem;
            font-weight: 500;
            color: var(--text-title);
            line-height: 1.2;
        }}
        .tbl-company-hover {{
            font-size: 0.82rem;
            color: var(--text-secondary);
            font-style: italic;
            line-height: 1.2;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 200px;
        }}

        .tbl-price-cell {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            line-height: 1.3;
        }}
        .tbl-price {{
            font-size: 1.2rem;
            font-weight: 500;
            font-family: var(--font-mono);
            color: var(--text-title);
            line-height: 1.2;
        }}
        .tbl-return {{ font-size: 0.8rem; font-family: var(--font-mono); }}

        .tbl-labels-cell {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}

        .tbl-val-cell {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            line-height: 1.3;
        }}
        .tbl-fv {{
            font-size: 1.15rem;
            font-weight: 500;
            font-family: var(--font-mono);
            line-height: 1.2;
        }}
        .tbl-base {{
            font-size: 0.82rem;
            color: var(--text-secondary);
            font-family: var(--font-mono);
            line-height: 1.2;
        }}

        /* Strict Stacked 2-Line Table Cells */
        .tbl-cell-stacked {{
            display: flex !important;
            flex-direction: column !important;
            gap: 3px !important;
            align-items: flex-start !important;
            justify-content: center !important;
            line-height: 1.25 !important;
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
            font-weight: 400 !important;
        }}

        /* Catalyst Column: Max 4 Words, Clean Line Wrap, No Truncation */
        .tbl-catalyst-cell {{
            display: flex;
            flex-direction: column;
            gap: 6px;
            max-width: 220px;
            line-height: 1.4;
        }}
        .tbl-cat-date {{
            font-family: var(--font-sans);
            font-size: 0.88rem;
            font-weight: 500;
            color: var(--text-title);
            line-height: 1.2;
        }}
        .tbl-cat-desc {{
            font-size: 0.8rem;
            color: var(--text-dim);
            line-height: 1.35;
            white-space: normal;
            word-break: break-word;
        }}

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
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.02);
        }}
        .grid-card:hover {{
            background: var(--bg-hover);
            border-color: rgba(204, 120, 92, 0.3);
            transform: translateY(-2px);
            box-shadow: 0 8px 24px -4px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.03);
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
        .alert-blurb {{ font-size: 1.02rem; color: var(--text-secondary); line-height: 1.55; }}

        .alert-right {{ text-align: right; }}
        .alert-price-val {{ font-size: 1.45rem; font-weight: 500; font-family: var(--font-mono); color: var(--text-title); }}
        .alert-price-pct {{ font-size: 0.9rem; font-family: var(--font-mono); }}
        .alert-dismiss-btn {{
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-color);
            color: var(--text-dim);
            border-radius: 8px;
            width: 32px;
            height: 32px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 0.85rem;
            transition: all 0.15s ease;
            flex-shrink: 0;
        }}
        .alert-dismiss-btn:hover {{
            background: rgba(204, 120, 92, 0.16) !important;
            color: var(--accent-warm) !important;
            border-color: var(--accent-warm) !important;
            transform: scale(1.08);
        }}

        /* Pills */
        .pill {{
            display: inline-flex;
            align-items: center;
            padding: 3px 11px;
            border-radius: 9999px;
            font-size: 0.72rem;
            font-family: var(--font-sans);
            letter-spacing: 0.03em;
            white-space: nowrap;
        }}
        .pill-active {{ background: rgba(201, 154, 117, 0.12); color: var(--accent-warm); border: 1px solid rgba(201, 154, 117, 0.45); font-weight: 600; box-shadow: 0 0 10px rgba(201, 154, 117, 0.06); }}
        .pill-neutral {{ background: var(--bg-subpanel); color: var(--text-secondary); border: 1px solid var(--border-color); font-weight: 500; }}
        .pill-alert {{ background: rgba(191, 160, 117, 0.14); color: var(--accent-warm); border: 1px solid rgba(191, 160, 117, 0.28); }}

        .pos {{ color: var(--accent-green); }}
        .neg {{ color: var(--accent-red); }}

        .empty-state-box, .empty-alerts {{
            background: var(--bg-panel);
            border: 1px dashed var(--border-color);
            border-radius: 14px;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            text-align: center !important;
            padding: 80px 24px !important;
            gap: 12px !important;
            width: 100% !important;
            box-sizing: border-box !important;
        }}
        .empty-state-title, .empty-title {{
            font-family: var(--font-serif) !important;
            font-size: 1.45rem !important;
            font-weight: 400 !important;
            color: var(--text-title) !important;
            letter-spacing: -0.01em !important;
            text-align: center !important;
            width: 100% !important;
            margin: 0 auto !important;
            line-height: 1.25 !important;
        }}
        .empty-state-sub, .empty-sub {{
            font-family: var(--font-sans) !important;
            font-size: 0.88rem !important;
            color: var(--text-dim) !important;
            font-weight: 400 !important;
            letter-spacing: 0.02em !important;
            text-align: center !important;
            width: 100% !important;
            margin: 0 auto !important;
            line-height: 1.35 !important;
        }}

        /* Subtle Hinge-style Status Pulse Beacon */
        .status-beacon {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            position: relative;
            width: 9px;
            height: 9px;
            margin-left: 7px;
            vertical-align: middle;
            cursor: help;
        }}
        .beacon-dot {{
            width: 6px;
            height: 6px;
            border-radius: 50%;
            position: relative;
            z-index: 2;
        }}
        .beacon-ping {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            animation: beacon-ripple 2.2s cubic-bezier(0, 0, 0.2, 1) infinite;
            z-index: 1;
        }}
        .beacon-buy .beacon-dot {{ background-color: #10b981; box-shadow: 0 0 6px rgba(16, 185, 129, 0.7); }}
        .beacon-buy .beacon-ping {{ background-color: rgba(16, 185, 129, 0.45); }}
        .beacon-hold .beacon-dot {{ background-color: #f59e0b; box-shadow: 0 0 6px rgba(245, 158, 11, 0.7); }}
        .beacon-hold .beacon-ping {{ background-color: rgba(245, 158, 11, 0.45); }}
        .beacon-caution .beacon-dot {{ background-color: #f97316; box-shadow: 0 0 6px rgba(249, 115, 22, 0.7); }}
        .beacon-caution .beacon-ping {{ background-color: rgba(249, 115, 22, 0.45); }}
        .beacon-avoid .beacon-dot {{ background-color: #ef4444; box-shadow: 0 0 6px rgba(239, 68, 68, 0.7); }}
        .beacon-avoid .beacon-ping {{ background-color: rgba(239, 68, 68, 0.45); }}
        @keyframes beacon-ripple {{
            0% {{ transform: scale(0.9); opacity: 0.85; }}
            70% {{ transform: scale(2.5); opacity: 0; }}
            100% {{ transform: scale(2.5); opacity: 0; }}
        }}

        /* Modal */
        .modal-shade {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(10, 10, 9, 0.85);
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
        .side-text {{ font-size: 1.02rem; color: var(--text-body); line-height: 1.65; }}

        .btn-primary {{
            background: var(--accent-warm); color: #141312; font-family: var(--font-sans); font-weight: 500;
            padding: 10px 20px; border-radius: 6px; text-decoration: none; display: inline-flex; align-items: center; border: none; cursor: pointer;
            transition: all 0.15s;
        }}
        .btn-primary:hover {{ background: #DDB495; }}
        .btn-outline {{
            background: var(--bg-subpanel); color: var(--text-title); border: 1px solid var(--border-color);
            font-family: var(--font-sans); font-weight: 500; padding: 10px 18px; border-radius: 6px; cursor: pointer;
        }}
        .btn-outline:hover {{ background: var(--bg-hover); }}

        /* Info Circle Button */
        .btn-info-circle {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            color: var(--text-dim);
            font-size: 0.72rem;
            font-family: var(--font-mono);
            cursor: pointer;
            margin-left: 6px;
            vertical-align: middle;
            transition: all 0.15s ease;
            padding: 0;
            line-height: 1;
        }}
        .btn-info-circle:hover {{
            background: var(--bg-hover);
            border-color: var(--accent-warm);
            color: var(--accent-warm);
            transform: scale(1.1);
        }}
    </style>
</head>
<body>
    <header class="nav-header">
        <div class="container header-content">
            <a href="#" class="brand-logo" style="display: inline-flex; align-items: center; gap: 10px;">
                <svg width="22" height="22" viewBox="0 0 32 32" style="display: block;">
                    <rect width="32" height="32" rx="8" fill="#1E1C19" stroke="#CC785C" stroke-opacity="0.35" stroke-width="1.2" />
                    <path d="M 9 22 C 7.5 19 7 16 9 13.5 C 11 11 14.5 11 17 13 C 19.5 15 20.5 18 20 21 C 19.5 22.5 17.8 23 16 22.5 C 13.5 21.8 11.5 19 12 16 C 12.5 13 15 10 18.5 9 C 21.5 8.2 24 10 24.5 13 C 25 16 23.5 19.5 23 22" fill="none" stroke="#CC785C" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
                <span>AlphaThesis</span>
            </a>
        </div>
    </header>

    <main class="container">
        <!-- Navigation Controls -->
        <div class="hub-controls">
            <div class="hub-tabs">
                <button class="hub-tab-btn active" onclick="switchTab('stocks')">Coverage ({len(watchlist)})</button>
                <button class="hub-tab-btn" onclick="switchTab('alerts')"><span id="alerts-tab-count">Alerts ({len(alerts)})</span></button>
                <button class="hub-tab-btn" onclick="switchTab('portfolio-defensive')">Fidelity</button>
                <button class="hub-tab-btn" onclick="switchTab('portfolio-aggressive')">Wealthsimple</button>
            </div>
            <div style="display: flex; align-items: center; gap: 10px;" id="stocks-view-controls">
                <div class="search-input-wrap" id="hub-search-wrap">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--text-dim)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="11" cy="11" r="8"></circle>
                        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                    </svg>
                    <input type="text" id="stock-search-input" class="search-input" placeholder="Search {len(watchlist)} stocks..." oninput="filterStocks(this.value)" spellcheck="false" autocomplete="off" autocapitalize="off">
                </div>
                <div class="view-toggle" id="view-toggle-bar">
                    <button class="view-btn active" onclick="setView('table')">Table</button>
                    <button class="view-btn" onclick="setView('grid')">Cards</button>
                </div>
            </div>
        </div>

        <!-- STOCKS SECTION -->
        <section id="pane-stocks" class="tab-panel active">
            <!-- Table View -->
            <div id="stocks-table-view" class="table-wrap">
                <table class="fin-table">
                    <colgroup>
                        <col style="width: 22%;">
                        <col style="width: 17%;">
                        <col style="width: 25%;">
                        <col style="width: 18%;">
                        <col style="width: 18%;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Market Price</th>
                            <th>Labels <button type="button" class="btn-info-circle" onclick="openLabelsLegendModal(event)" title="View Investment Taxonomy & Labels Legend">ⓘ</button></th>
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

        <!-- DEFENSIVE PORTFOLIO SECTION -->
        <section id="pane-portfolio-defensive" class="tab-panel">
            {portfolio_defensive_html}
        </section>

        <!-- AGGRESSIVE PORTFOLIO SECTION -->
        <section id="pane-portfolio-aggressive" class="tab-panel">
            {portfolio_aggressive_html}
        </section>
    </main>

    <!-- Alert Delta Modal -->
    <div id="alert-modal" class="modal-shade" onclick="closeModalOutside(event)">
        <div class="modal-body-card" id="modal-card">
            <button class="modal-x" onclick="closeAlertModal()">✕</button>
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                <strong id="modal-ticker" style="font-family: var(--font-serif); font-size: 1.35rem; color: var(--text-title);">TICKER</strong>
                <span id="modal-badge" class="pill pill-alert">ALERT</span>
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
                <button class="btn-outline" onclick="dismissCurrentAlert()">Dismiss</button>
                <a id="modal-report-link" href="#" class="btn-primary" onclick="dismissCurrentAlert()">Open Research Memo →</a>
            </div>
        </div>
    </div>

    <script>
        let currentAlertId = null;

        function getDismissedAlertIds() {{
            try {{
                return JSON.parse(localStorage.getItem('alphathesis_dismissed_alerts') || '[]');
            }} catch(e) {{
                return [];
            }}
        }}

        function dismissAlert(alertId) {{
            if (!alertId) return;
            const item = document.querySelector(`.alert-item[data-alert-id="${{alertId}}"]`);
            if (item) {{
                item.style.transition = 'opacity 0.22s ease, transform 0.22s ease';
                item.style.opacity = '0';
                item.style.transform = 'scale(0.96)';
            }}
            setTimeout(() => {{
                const dismissed = getDismissedAlertIds();
                if (!dismissed.includes(alertId)) {{
                    dismissed.push(alertId);
                    localStorage.setItem('alphathesis_dismissed_alerts', JSON.stringify(dismissed));
                }}
                refreshAlertsUI();
            }}, 200);
        }}

        function refreshAlertsUI() {{
            const dismissed = getDismissedAlertIds();
            const items = document.querySelectorAll('.alert-item');
            let visibleCount = 0;

            items.forEach(el => {{
                const id = el.getAttribute('data-alert-id');
                if (dismissed.includes(id)) {{
                    el.style.display = 'none';
                }} else {{
                    el.style.display = 'flex';
                    visibleCount++;
                }}
            }});

            const countLabel = document.getElementById('alerts-tab-count');
            if (countLabel) countLabel.innerText = 'Alerts (' + visibleCount + ')';

            const emptyBox = document.getElementById('empty-alerts-box');
            if (emptyBox) {{
                emptyBox.style.display = (visibleCount === 0 ? 'flex' : 'none');
            }}
        }}

        function filterStocks(query) {{
            const q = (query || '').toLowerCase().trim();
            const rows = document.querySelectorAll('#stocks-table-view tbody tr.table-row');
            const cards = document.querySelectorAll('#stocks-grid-view .grid-card');
            
            rows.forEach(r => {{
                const text = r.innerText.toLowerCase();
                r.style.display = (!q || text.includes(q)) ? '' : 'none';
            }});
            
            cards.forEach(c => {{
                const text = c.innerText.toLowerCase();
                c.style.display = (!q || text.includes(q)) ? '' : 'none';
            }});
        }}

        function switchTab(tab) {{
            document.querySelectorAll('.hub-tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(sec => sec.classList.remove('active'));
            const viewCtrl = document.getElementById('stocks-view-controls');
            
            const btnIdxMap = {{
                'stocks': 0,
                'alerts': 1,
                'portfolio-defensive': 2,
                'portfolio-aggressive': 3
            }};
            const idx = btnIdxMap[tab] !== undefined ? btnIdxMap[tab] : 0;
            const btns = document.querySelectorAll('.hub-tab-btn');
            if (btns[idx]) btns[idx].classList.add('active');

            const targetPane = document.getElementById('pane-' + tab);
            if (targetPane) targetPane.classList.add('active');

            if (viewCtrl) {{
                viewCtrl.style.display = (tab === 'stocks') ? 'flex' : 'none';
            }}

            if (tab === 'portfolio-defensive' && typeof initPortfolioChart_defensive === 'function') {{
                setTimeout(initPortfolioChart_defensive, 50);
            }} else if (tab === 'portfolio-aggressive' && typeof initPortfolioChart_aggressive === 'function') {{
                setTimeout(initPortfolioChart_aggressive, 50);
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
            currentAlertId = payload.id || (payload.ticker + '_' + payload.timestamp);
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

        function dismissCurrentAlert() {{
            if (currentAlertId) {{
                dismissAlert(currentAlertId);
            }}
            closeAlertModal();
        }}

        function closeAlertModal() {{
            document.getElementById('alert-modal').style.display = 'none';
        }}

        function closeModalOutside(event) {{
            if (event.target.id === 'alert-modal') {{
                closeAlertModal();
            }}
        }}

        function openLabelsLegendModal(event) {{
            if (event) {{
                event.stopPropagation();
                event.preventDefault();
            }}
            const modal = document.getElementById('labels-legend-modal');
            if (modal) modal.style.display = 'flex';
        }}

        function closeLabelsLegendModal() {{
            const modal = document.getElementById('labels-legend-modal');
            if (modal) modal.style.display = 'none';
        }}

        function closeLegendModalOutside(event) {{
            if (event.target.id === 'labels-legend-modal') {{
                closeLabelsLegendModal();
            }}
        }}

        function renderLatexEquations() {{
            if (typeof renderMathInElement === 'function') {{
                renderMathInElement(document.body, {{
                    delimiters: [
                        {{left: '$$', right: '$$', display: true}},
                        {{left: '\\\\[', right: '\\\\]', display: true}},
                        {{left: '\\\\(', right: '\\\\)', display: false}}
                    ],
                    ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'],
                    throwOnError: false
                }});
            }}
        }}

        async function syncWatchlistQuotes() {{
            try {{
                const res = await fetch('data/live_quotes.json?_t=' + Date.now());
                if (!res.ok) return;
                const quotes = await res.json();
                
                for (const [ticker, q] of Object.entries(quotes)) {{
                    if (!q || q.price === undefined) continue;
                    const price = parseFloat(q.price);
                    
                    // Update table
                    const priceSpan = document.querySelector(`.tbl-price-${{ticker}}`);
                    const retSpan = document.querySelector(`.tbl-ret-${{ticker}}`);
                    if (priceSpan) priceSpan.textContent = '$' + price.toFixed(2);
                    
                    const row = document.querySelector(`tr.table-row[data-ticker="${{ticker}}"]`);
                    if (row && retSpan) {{
                        const baseline = parseFloat(row.getAttribute('data-baseline')) || price;
                        if (baseline > 0) {{
                            const ret = ((price - baseline) / baseline) * 100.0;
                            const sign = ret >= 0 ? '+' : '';
                            retSpan.textContent = `${{sign}}${{ret.toFixed(2)}}%`;
                            retSpan.className = `tbl-return ${{ret >= 0 ? 'ret-pos' : 'ret-neg'}}`;
                        }}
                    }}
                    
                    // Update grid cards
                    const gPrice = document.querySelector(`.grid-price-${{ticker}}`);
                    const gRet = document.querySelector(`.grid-ret-${{ticker}}`);
                    if (gPrice) gPrice.textContent = '$' + price.toFixed(2);
                    if (gRet && row) {{
                        const baseline = parseFloat(row.getAttribute('data-baseline')) || price;
                        if (baseline > 0) {{
                            const ret = ((price - baseline) / baseline) * 100.0;
                            const sign = ret >= 0 ? '+' : '';
                            gRet.textContent = `${{sign}}${{ret.toFixed(2)}}%`;
                            gRet.className = `grid-stat-val ${{ret >= 0 ? 'ret-pos' : 'ret-neg'}}`;
                        }}
                    }}
                }}
            }} catch(e) {{}}
        }}

        document.addEventListener('DOMContentLoaded', () => {{
            refreshAlertsUI();
            renderLatexEquations();
            syncWatchlistQuotes();
        }});
        window.addEventListener('load', renderLatexEquations);
        window.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') {{
                closeAlertModal();
                closeLabelsLegendModal();
            }}
        }});
        refreshAlertsUI();
        setInterval(syncWatchlistQuotes, 20000);
    </script>
    {build_labels_legend_modal_html()}
</body>
</html>
"""


def render_all():
    """Compiles all company dossiers and the master index dashboard."""
    from stocks.portfolio import sync_live_market_data
    try:
        sync_live_market_data()
    except Exception as e:
        print(f"⚠️ Live market data sync warning: {e}")
        
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

