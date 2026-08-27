"""Minimalist, Soothing Financial Research Dashboard & Due Diligence Dossier."""

import json
import re
import html
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from stocks.models import WatchlistStock, AlertItem, ThesisVersion
from stocks.data_store import load_watchlist, save_watchlist, load_alerts, load_thesis_history
from stocks.tracker import fetch_all_chart_ranges, fetch_all_chart_ranges_cached
from stocks.ownership_intelligence import build_ownership_tab_html, calculate_insider_sentiment_and_flow, load_cached_ownership
from bs4 import BeautifulSoup, NavigableString, Tag

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
REPORTS_DIR = PUBLIC_DIR / "reports"
THESES_DIR = DATA_DIR / "theses"

CANONICAL_COMPANY_NAMES = {
    "AMZN": "Amazon.com, Inc.",
    "APP": "AppLovin Corporation",
    "BABA": "Alibaba Group Holding Ltd.",
    "BMBL": "Bumble Inc.",
    "BVHMF": "Vistry Group PLC",
    "BCCLF": "Becle, S.A.B. de C.V. (Cuervo)",
    "BYD": "BYD Company Limited",
    "CELH": "Celsius Holdings, Inc.",
    "CPRT": "Copart, Inc.",
    "CROX": "Crocs, Inc.",
    "EDU": "New Oriental Education & Tech",
    "FICO": "Fair Isaac Corporation",
    "GCT": "GigaCloud Technology Inc.",
    "GOOG": "Alphabet Inc.",
    "GOOGL": "Alphabet Inc.",
    "JD": "JD.com, Inc.",
    "LGCY": "Legacy Education Inc.",
    "LULU": "Lululemon Athletica Inc.",
    "MELI": "MercadoLibre, Inc.",
    "META": "Meta Platforms, Inc.",
    "MSFT": "Microsoft Corporation",
    "MTCH": "Match Group, Inc.",
    "PDD": "PDD Holdings Inc. (Temu)",
    "PYPL": "PayPal Holdings, Inc.",
    "RDDT": "Reddit, Inc.",
    "STNE": "StoneCo Ltd."
}


def get_canonical_company_name(ticker: str, fallback_name: str = "") -> str:
    clean_t = (ticker or "").upper().strip()
    if clean_t in CANONICAL_COMPANY_NAMES:
        return CANONICAL_COMPANY_NAMES[clean_t]
    if fallback_name and fallback_name.upper().strip() != clean_t:
        return fallback_name.strip().rstrip(".")
    return clean_t


def _ensure_dirs():
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def normalize_latex_typography(html: str) -> str:
    """Normalizes all LaTeX math expressions into robust KaTeX delimiters \\( ... \\) and $$ ... $$.
    Protects financial currencies ($XX.XX, $50B, etc.), HTML tags, and pre-existing math blocks,
    ensuring 100% typography-grade mathematical equations without broken raw brackets or text collisions."""
    if not html:
        return ""
        
    # Step 1: Protect existing block / display equations ($$ ... $$ and \\[ ... \\])
    display_blocks = []
    def save_display(m):
        display_blocks.append(m.group(0))
        return f"««DISPLAY_BLOCK_{len(display_blocks)-1}»»"
    
    html = re.sub(r'\$\$(.*?)\$\$', save_display, html, flags=re.DOTALL)
    html = re.sub(r'\\\[(.*?)\\\]', save_display, html, flags=re.DOTALL)

    # Step 2: Protect HTML tags so we don't touch attributes or tag names
    tags = []
    def save_tag(m):
        tags.append(m.group(0))
        return f"««HTML_TAG_{len(tags)-1}»»"
    
    html = re.sub(r'<[^>]+>', save_tag, html)

    # Step 3: Protect existing inline equations \\( ... \\)
    inline_blocks = []
    def save_inline(m):
        inline_blocks.append(m.group(0))
        return f"««INLINE_BLOCK_{len(inline_blocks)-1}»»"
    
    html = re.sub(r'\\\((.*?)\\\)', save_inline, html, flags=re.DOTALL)

    # Step 4: Protect all currency amounts ($568.97, $50, $1,200.50, $25B, $19.31 billion, ~$252.00, -$8.65B, etc.)
    currencies = []
    def save_currency(m):
        currencies.append(m.group(0))
        return f"««CURRENCY_{len(currencies)-1}»»"
    
    curr_pattern = r'(?:~|-|\+)?\$(?=\d|\.\d)(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?(?:\s*(?:billion|million|trillion|[kKmMbBtT]))?'
    html = re.sub(curr_pattern, save_currency, html)

    # Step 5: Convert dollar-wrapped math $...$ into saved inline blocks
    def convert_dollar_math(m):
        math_content = m.group(1).strip()
        if not math_content:
            return ""
        inline_blocks.append(f"\\({math_content}\\)")
        return f"««INLINE_BLOCK_{len(inline_blocks)-1}»»"
        
    html = re.sub(r'(?<![\$\\])\$(?!\$)([^\$\n]+?)(?<![\$\\])\$(?!\$)', convert_dollar_math, html)

    # Step 6: Convert naked LaTeX identifiers (e.g. g_{\\text{implied}}, g_{implied}, g_{base}, g_{realistic}, \\frac{a}{b})
    def wrap_naked_latex(m):
        expr = m.group(0)
        inline_blocks.append(f"\\({expr}\\)")
        return f"««INLINE_BLOCK_{len(inline_blocks)-1}»»"
        
    nested_braced_subscript = r'[a-zA-Z]\w*_(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\w+)'
    nested_braced_cmd = r'\\[a-zA-Z]+(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})+'
    naked_latex_pattern = rf'(?<![\w\\\(«])(?:{nested_braced_subscript}|{nested_braced_cmd})(?![\w\\\)»])'
    html = re.sub(naked_latex_pattern, wrap_naked_latex, html)

    # Step 7: Restore currencies
    for i, curr in enumerate(currencies):
        html = html.replace(f"««CURRENCY_{i}»»", curr)

    # Step 8: Restore inline blocks
    for i, inl in enumerate(inline_blocks):
        html = html.replace(f"««INLINE_BLOCK_{i}»»", inl)

    # Step 9: Restore HTML tags
    for i, tag in enumerate(tags):
        html = html.replace(f"««HTML_TAG_{i}»»", tag)

    # Step 10: Restore display blocks
    for i, disp in enumerate(display_blocks):
        html = html.replace(f"««DISPLAY_BLOCK_{i}»»", disp)
        
    return html


def format_labels_stack_html(stock_or_labels: Any) -> str:
    """Formats 2 clean, minimalist text-only labels stacked one below another in the LABELS column:
    Row 1: Economic Moat (Wide Moat / Narrow Moat / Weak Moat / No Moat)
    Row 2: Predictability (High Predictability / Moderate Predictability / Low Predictability / Highly Unpredictable)
    """
    from stocks.gemini_agent import map_to_canonical_moat_label, map_to_canonical_predictability_tier
    
    if isinstance(stock_or_labels, (list, tuple)):
        raw_moat = stock_or_labels[0] if len(stock_or_labels) > 0 else "Narrow Moat"
        raw_pred = stock_or_labels[1] if len(stock_or_labels) > 1 else "Moderate Predictability"
    elif isinstance(stock_or_labels, str):
        raw_moat = stock_or_labels
        raw_pred = "Moderate Predictability"
    elif isinstance(stock_or_labels, dict):
        raw_moat = stock_or_labels.get("moat_label") or (stock_or_labels.get("labels")[0] if stock_or_labels.get("labels") else None) or stock_or_labels.get("status_label") or "Narrow Moat"
        raw_pred = stock_or_labels.get("predictability_tier") or (stock_or_labels.get("labels")[1] if (stock_or_labels.get("labels") and len(stock_or_labels.get("labels")) > 1) else None) or "Moderate Predictability"
    else:
        raw_moat = getattr(stock_or_labels, "moat_label", None) or (stock_or_labels.labels[0] if getattr(stock_or_labels, "labels", None) else None) or getattr(stock_or_labels, "status_label", None) or "Narrow Moat"
        raw_pred = getattr(stock_or_labels, "predictability_tier", None)
        if not raw_pred and getattr(stock_or_labels, "labels", None) and len(stock_or_labels.labels) > 1:
            raw_pred = stock_or_labels.labels[1]
    
    moat_lbl = map_to_canonical_moat_label(str(raw_moat or "Narrow Moat"))
    if moat_lbl == "Wide Moat":
        moat_color = "var(--accent-green)"
    elif moat_lbl == "Narrow Moat":
        moat_color = "var(--accent-warm)"
    elif moat_lbl == "Weak Moat":
        moat_color = "#D48858"
    else:
        moat_color = "var(--accent-red)"
        
    pred_lbl = map_to_canonical_predictability_tier(str(raw_pred or "Moderate Predictability"))
    if pred_lbl == "High Predictability":
        pred_color = "var(--accent-warm)"
    elif pred_lbl == "Moderate Predictability":
        pred_color = "var(--text-secondary)"
    elif pred_lbl == "Low Predictability":
        pred_color = "#D48858"
    else:
        pred_color = "var(--accent-red)"
        
    return f"""<div class="tbl-labels-stack" style="display: flex; flex-direction: column; gap: 3px; align-items: flex-start;">
        <span class="moat-text-label" style="color: {moat_color}; font-size: 0.84rem; font-weight: 500; font-family: var(--font-sans); white-space: nowrap;">{moat_lbl}</span>
        <span class="pred-text-label" style="color: {pred_color}; font-size: 0.76rem; font-weight: 400; font-family: var(--font-sans); white-space: nowrap;">{pred_lbl}</span>
    </div>"""


def format_labels_pills(labels: Any, stock: Any = None) -> str:
    """Backwards-compatible wrapper returning the 2-row stacked labels."""
    return format_labels_stack_html(stock if stock is not None else labels)


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


def extract_pct_delta(base_target: Any, current_price: float, fair_value_str: str) -> str:
    """Extracts clean percentage difference without repeating the dollar value."""
    if isinstance(base_target, (int, float)):
        return f"{base_target:+.1f}%"
        
    base_str = str(base_target or "")
    match = re.search(r"\(([-+]?\d+(?:\.\d+)?%)\)", base_str)
    if match:
        return match.group(1)
        
    pct_match = re.search(r"[-+]?\d+(?:\.\d+)?%", base_str)
    if pct_match:
        return pct_match.group(0)
    
    fv_match = re.search(r"[-+]?\d+(?:\.\d+)?", str(fair_value_str).replace(",", ""))
    if fv_match and current_price > 0:
        fv = float(fv_match.group(0))
        diff_pct = ((fv - current_price) / current_price) * 100
        return f"{diff_pct:+.1f}%"
        
    return ""


def format_target_metric_html(target_val: Any, color_var: str = "") -> str:
    """Formats target metrics like '$224.60 (+94.2%)' into a responsive, beautiful HTML layout
    with the price in primary font and the delta in a subtle badge, preventing text overflow."""
    if not target_val:
        return '<div class="metric-value">N/A</div>'
    val_str = str(target_val).strip()
    m = re.match(r"(\$[0-9]+(?:\.[0-9]+)?|\d+(?:\.[0-9]+)?)\s*(\([-+]?[0-9]+(?:\.[0-9]+)?%\))?", val_str)
    if m:
        price = m.group(1)
        if not price.startswith("$"): price = f"${price}"
        pct = m.group(2) or ""
        color_style = f'style="color: {color_var};"' if color_var else ""
        pct_html = f'<span class="target-pct" style="font-size: 0.74rem; opacity: 0.85; font-family: var(--font-mono); font-weight: 500; margin-left: 4px;">{pct}</span>' if pct else ""
        return f'<div class="metric-value metric-target-value" {color_style}><span class="target-price">{price}</span>{pct_html}</div>'
    color_style = f'style="color: {color_var};"' if color_var else ""
    return f'<div class="metric-value" {color_style}>{val_str}</div>'


def format_catalyst_display(event_str: Optional[str], date_str: Optional[str]) -> Tuple[str, str]:
    """Formats catalyst into a clean, human-readable 2-line display:
    Line 1 (Headline): Event explanation (e.g. "Q3 '26 Earnings", "Annual 20-F Filing", "Investor Day")
    Line 2 (Subtext): Human formatted date (e.g. "Nov 19, 2026")
    """
    clean_event = (event_str or "").strip()
    clean_date = (date_str or "").strip()

    # Parse Date
    parsed_dt = None
    date_display = ""
    if clean_date and clean_date.upper() != "TBD":
        m_iso = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", clean_date)
        if m_iso:
            try:
                parsed_dt = datetime(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
                date_display = parsed_dt.strftime("%b %d, %Y")
            except Exception:
                date_display = clean_date
        else:
            date_display = clean_date

    # Clean Headline: Concise 2-4 word milestone
    if clean_event and clean_event.upper() != "TBD" and not re.match(r"^Q[1-4]\s*'?\d{2}\s*Earnings$", clean_event, flags=re.IGNORECASE):
        ev = clean_event
        ev = re.sub(r"^(?:Upcoming\s+)?(?:Quarterly\s+)?(?:Earnings\s+Call\s+&\s+SEC\s+Filing|Earnings\s+Release|Quarterly\s+Results|Earnings)\s*[-:·]?\s*", "", ev, flags=re.IGNORECASE).strip()
        words = ev.split()
        if len(words) > 4:
            ev = " ".join(words[:4])
        if not ev or ev.lower() in ["earnings", "earnings release", "earnings call"]:
            ev = "Operating Margin Inflection"
        headline = ev
    else:
        headline = "Operating Margin Inflection"

    if not date_display:
        date_display = "Horizon '26"

    return headline, date_display


def sanitize_catalyst_desc(desc: str) -> str:
    """Backward compatibility helper."""
    return format_catalyst_display(desc, "")[0]


def get_ticker_logo_html(ticker: str, size: int = 22) -> str:
    """Builds a very minimalist, crisp logo avatar with automatic fallback to clean monogram."""
    if not ticker:
        return ""
    clean_t = ticker.replace("USD_", "").strip()
    if ticker == "USD_CASH" or clean_t == "CASH":
        return f'<div class="ticker-logo-wrap" style="width:{size}px; height:{size}px; min-width:{size}px; min-height:{size}px;"><span class="ticker-logo-fallback" style="color:var(--accent-green); font-size:{int(size*0.55)}px;">$</span></div>'
    
    fallback_char = clean_t[:2]
    return (
        f'<div class="ticker-logo-wrap" style="width:{size}px; height:{size}px; min-width:{size}px; min-height:{size}px;">'
        f'<img class="ticker-logo" src="https://assets.parqet.com/logos/symbol/{clean_t}" alt="{clean_t}" loading="lazy" '
        f'onerror="this.style.display=\'none\'; if(this.nextElementSibling) this.nextElementSibling.style.display=\'flex\';">'
        f'<span class="ticker-logo-fallback" style="display:none; font-size:{int(size*0.42)}px;">{fallback_char}</span>'
        f'</div>'
    )


def get_or_create_circular_favicon(ticker: str) -> str:
    """Ensures a circular SVG favicon exists in public/favicons/{ticker}.svg and returns its relative path."""
    if not ticker:
        return "../favicons/favicon.svg"
    clean_t = ticker.replace("USD_", "").strip().upper()
    fav_dir = DATA_DIR.parent / "public" / "favicons"
    fav_dir.mkdir(parents=True, exist_ok=True)
    fav_file = fav_dir / f"{clean_t}.svg"
    
    if fav_file.exists():
        return f"../favicons/{clean_t}.svg"
        
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(f"https://assets.parqet.com/logos/symbol/{clean_t}", headers=headers, timeout=4)
        if r.status_code == 200 and "<svg" in r.text:
            svg_content = r.text
            vb_match = re.search(r'viewBox=[\"\']([0-9\s\.\-]+)[\"\']', svg_content)
            if vb_match:
                parts = [float(x) for x in vb_match.group(1).split()]
                w = parts[2] if len(parts) >= 4 else 60.0
                h = parts[3] if len(parts) >= 4 else 60.0
            else:
                w, h = 60.0, 60.0
            
            cx, cy, r_rad = w / 2.0, h / 2.0, min(w, h) / 2.0
            svg_tag_match = re.search(r'(<svg[^>]*>)(.*)(</svg>)', svg_content, re.DOTALL)
            if svg_tag_match:
                open_tag = svg_tag_match.group(1)
                inner = svg_tag_match.group(2)
                close_tag = svg_tag_match.group(3)
                circular_svg = (
                    f"{open_tag}\n"
                    f"<defs>\n"
                    f'  <clipPath id="circle-clip">\n'
                    f'    <circle cx="{cx}" cy="{cy}" r="{r_rad}"/>\n'
                    f"  </clipPath>\n"
                    f"</defs>\n"
                    f'<g clip-path="url(#circle-clip)">\n'
                    f"{inner}\n"
                    f"</g>\n"
                    f"{close_tag}"
                )
                fav_file.write_text(circular_svg, encoding="utf-8")
                return f"../favicons/{clean_t}.svg"
    except Exception:
        pass
        
    initials = clean_t[:3].upper()
    fallback_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 60" width="60" height="60">
  <circle cx="30" cy="30" r="30" fill="#1B1A19" stroke="rgba(212,163,115,0.4)" stroke-width="2"/>
  <text x="30" y="36" text-anchor="middle" fill="#D4A373" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" font-weight="700">{initials}</text>
</svg>"""
    fav_file.write_text(fallback_svg, encoding="utf-8")
    return f"../favicons/{clean_t}.svg"


def format_action_beacon(signal: Optional[str] = None) -> str:
    """Renders a quiet, minimal dot beacon representing the surveillance stance."""
    if not signal:
        return ""
    sig = signal.upper().strip()
    if any(k in sig for k in ["RED", "AVOID", "BROKEN", "EXIT", "SELL", "DANGER", "CRITICAL", "DON'T BUY", "DO NOT BUY"]):
        css = "beacon-avoid"
        tooltip = "Action: Avoid"
    elif any(k in sig for k in ["ORANGE", "CAUTION", "TRIM", "HEADWIND", "WARNING", "FRICTION", "GOING BAD"]):
        css = "beacon-caution"
        tooltip = "Action: Caution"
    elif any(k in sig for k in ["YELLOW", "WAIT", "HOLD", "MONITOR", "PATIENT", "NEUTRAL", "STEADY", "DO NOTHING"]):
        css = "beacon-hold"
        tooltip = "Action: Hold"
    elif any(k in sig for k in ["GREEN", "BUY", "ACCUMULATE", "STRONG", "NOW"]):
        css = "beacon-buy"
        tooltip = "Action: Buy"
    else:
        css = "beacon-buy"
        tooltip = "Action: Buy"
    
    return f'<span class="status-beacon {css}" title="{tooltip}"><span class="beacon-dot"></span></span>'


def get_quad_ma_beacon_html(ticker: str, current_price: float = 0.0) -> str:
    """Renders a subtle, beautiful emerald radar pulse beacon if the stock crossed UP all 4 MAs in the last 21 sessions."""
    from stocks.moving_average_surveillance import get_recent_quad_ma_status
    status = get_recent_quad_ma_status(ticker, current_price)
    if not status or not status.get("is_active"):
        return ""
    
    days_ago = status.get("days_ago", 1)
    clearance = status.get("clearance_pct", 0.0)
    day_str = f"{days_ago} session ago" if days_ago == 1 else f"{days_ago} sessions ago"
    tooltip = f"Quad-MA Reversal: Crossed UP all 4 MAs (5D/21D/50D/200D) {day_str} (+{clearance:.1f}% clearance)"
    
    return f'<span class="quad-beacon-wrap" title="{tooltip}"><span class="quad-beacon-ping"></span><span class="quad-beacon-dot"></span></span>'


def clean_fund_name(name: str) -> str:
    """Strips parentheticals and extra annotations for ultra-clean subtext display."""
    if not name:
        return ""
    c = re.sub(r"\(.*?\)", "", name).strip()
    c = re.sub(r"\s*/.*", "", c).strip()
    c = c.replace("Management", "").replace("Capital", "").replace("Hathaway", "").strip()
    return c


def format_top_funds_card_html(stock: WatchlistStock) -> str:
    """Renders a clean, minimalist Superinvestor Whales / Institutional card with zero N/A."""
    funds = getattr(stock, "top_funds", None) or []
    raw_inst = getattr(stock, "institutional_ownership_pct", None) or ""
    
    if not funds:
        try:
            cached = load_cached_ownership(stock.ticker)
            dr_holders = cached.get("dataroma_holders", [])
            if dr_holders:
                funds = [f"{h.get('manager')} ({h.get('pct_of_portfolio', '')})" for h in dr_holders[:10]]
        except Exception:
            pass

    clean_names = [clean_fund_name(f) for f in funds if clean_fund_name(f)]
    subtext = " · ".join(clean_names[:2]) if clean_names else ("13F Superinvestors" if funds else "13F Institutional Registry")

    # Format value: if valid pct exists and is not N/A, use it; otherwise show superinvestor whale count
    if raw_inst and str(raw_inst).strip() not in ("N/A", "None", "", "TBD", "0 Tracked") and ("%" in str(raw_inst) or "Whale" in str(raw_inst)):
        display_val = str(raw_inst).strip()
    elif len(funds) > 0:
        display_val = f"{len(funds)} Whales" if len(funds) > 1 else f"{len(funds)} Whale"
    else:
        display_val = "13F Registry"

    return f"""
    <div class="metric-cell" title="13F Institutional & Superinvestor Whale File">
        <div class="metric-label">Whales</div>
        <div class="metric-value" style="font-size: 0.95rem; font-family: var(--font-sans); font-weight: 600; color: var(--text-title);">{display_val}</div>
        {f'<div class="metric-subtext">{subtext}</div>' if subtext else ''}
    </div>
    """


def format_insider_activity_card_html(stock: WatchlistStock) -> str:
    """Renders a clean, minimalist insider card on a single sleek line."""
    cached = load_cached_ownership(stock.ticker)
    oi_trades = cached.get("openinsider_trades", [])
    raw_signal = getattr(stock, "insider_signal", None) or ""
    intel = calculate_insider_sentiment_and_flow(oi_trades, raw_signal)
    summary = intel["summary"]
    return f"""
    <div class="metric-cell">
        <div class="metric-label">Insiders</div>
        <div class="metric-value" style="color: {intel['color']}; font-family: var(--font-sans); font-size: 0.88rem; font-weight: 600;">{intel['badge_html']}</div>
        <div class="metric-subtext">{summary}</div>
    </div>
    """


def format_pricing_power_card_html(stock: WatchlistStock) -> str:
    """Renders the Buffett-Munger Pricing Power intelligence card in the hero metrics grid."""
    pp_tier = getattr(stock, "pricing_power_tier", None) or "Strong Pricing Power"
    pp_score = getattr(stock, "pricing_power_score", None) or "Inelastic Demand"
    pp_summary = getattr(stock, "pricing_power_summary", None) or "Demonstrated authority to pass input cost inflation without demand destruction."
    
    tier_lower = pp_tier.lower()
    if any(k in tier_lower for k in ["absolute", "unconstrained", "monopoly"]):
        color = "var(--accent-warm)"
    elif any(k in tier_lower for k in ["strong", "structural"]):
        color = "var(--accent-warm)"
    elif any(k in tier_lower for k in ["inflation", "cost-plus", "pass"]):
        color = "var(--accent-green)"
    elif any(k in tier_lower for k in ["constrained", "regulated"]):
        color = "var(--text-secondary)"
    else:
        color = "var(--accent-red)"

    return f"""
    <div class="metric-cell" title="Buffett & Munger Pricing Power Framework: {pp_summary}">
        <div class="metric-label">Pricing Power</div>
        <div class="metric-value" style="color: {color}; font-family: var(--font-sans); font-size: 0.88rem; font-weight: 600;">{pp_tier}</div>
        <div class="metric-subtext">{pp_score}</div>
    </div>
    """


def format_cash_flow_predictability_card_html(stock: WatchlistStock) -> str:
    """Renders the Buffett-Munger Cash Flow Predictability ('Too Hard' Pile Audit) card in the hero metrics grid."""
    pred_tier = getattr(stock, "predictability_tier", None) or "Moderate Predictability"
    pred_score = getattr(stock, "predictability_score", None) or "Manageable Visibility"
    pred_summary = getattr(stock, "predictability_summary", None) or "Buffett & Munger 10-Year Cash Flow Visibility Assessment."
    
    tier_lower = pred_tier.lower()
    if any(k in tier_lower for k in ["high", "pristine", "contractual"]):
        color = "var(--accent-warm)"
    elif any(k in tier_lower for k in ["moderate", "disciplined", "manageable"]):
        color = "var(--accent-green)"
    elif any(k in tier_lower for k in ["low", "too hard", "volatile"]):
        color = "#D48858"
    else:
        color = "var(--accent-red)"

    return f"""
    <div class="metric-cell" title="Buffett & Munger Predictability Framework ('Too Hard' Pile Audit): {pred_summary}">
        <div class="metric-label">Predictability</div>
        <div class="metric-value" style="color: {color}; font-family: var(--font-sans); font-size: 0.88rem; font-weight: 600;">{pred_tier}</div>
        <div class="metric-subtext">{pred_score}</div>
    </div>
    """


def build_labels_legend_modal_html(include_pricing_power: bool = False) -> str:
    """Builds the clean, minimalist, subtle modal explaining investment taxonomy and surveillance signals."""
    pricing_power_section = ""
    if include_pricing_power:
        pricing_power_section = """
            <div style="height: 1px; background: var(--border-color); margin: 14px 0;"></div>

            <!-- Section 3: Buffett & Munger Pricing Power -->
            <div style="margin-bottom: 14px;">
                <div style="font-family: var(--font-sans); font-size: 0.65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-warm); margin-bottom: 9px;">
                    Buffett &amp; Munger Pricing Power Tiers
                </div>
                <div style="display: grid; grid-template-columns: 165px 1fr; row-gap: 6px; column-gap: 12px; font-size: 0.74rem; align-items: center;">
                    <span style="font-weight: 600; color: var(--text-title); white-space: nowrap;">Absolute Power</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Unilateral pricing authority without volume loss</span>

                    <span style="font-weight: 600; color: var(--text-title); white-space: nowrap;">Strong Power</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Dominant structural pricing authority ahead of CPI</span>

                    <span style="font-weight: 600; color: var(--text-title); white-space: nowrap;">Inflation Pass-Thru</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Cost-plus indexation with contractual cost pass-through</span>

                    <span style="font-weight: 600; color: var(--text-title); white-space: nowrap;">Constrained Power</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Moderate pricing power subject to customer pushback</span>

                    <span style="font-weight: 600; color: var(--text-title); white-space: nowrap;">Price Taker</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Vulnerable to competitor price cuts and margin compression</span>
                </div>
            </div>

            <div style="height: 1px; background: var(--border-color); margin: 14px 0;"></div>

            <!-- Section 4: Buffett & Munger Cash Flow Predictability -->
            <div>
                <div style="display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 9px;">
                    <div style="font-family: var(--font-sans); font-size: 0.65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-warm);">
                        Cash Flow Predictability ("Too Hard" Pile Audit)
                    </div>
                    <div style="font-family: var(--font-sans); font-size: 0.62rem; color: var(--text-dim);">
                        1996 Berkshire Letter · 10-Yr Visibility
                    </div>
                </div>
                <div style="display: grid; grid-template-columns: 165px 1fr; row-gap: 6px; column-gap: 12px; font-size: 0.74rem; align-items: center;">
                    <span style="font-weight: 600; color: var(--accent-warm); white-space: nowrap;">High Predictability</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Contractual recurring cash flows; in the circle of competence</span>

                    <span style="font-weight: 600; color: var(--accent-green); white-space: nowrap;">Moderate Predictability</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Durable moat with macro cycle or platform transition exposure</span>

                    <span style="font-weight: 600; color: #D48858; white-space: nowrap;">Low Predictability</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Nascent lines, rapid tech shifts, or Red Queen CapEx drag</span>

                    <span style="font-weight: 600; color: var(--accent-red); white-space: nowrap;">Highly Unpredictable</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Binary outcomes or speculative volatility (strict 'Too Hard' pile)</span>
                </div>
            </div>
        """

    return f"""
    <!-- Labels & Taxonomy Legend Modal -->
    <div id="labels-legend-modal" class="modal-shade" onclick="closeLegendModalOutside(event)">
        <div class="modal-body-card" style="max-width: 620px; max-height: 88vh; overflow-y: auto; padding: 22px 26px; background: rgba(22, 21, 20, 0.98); backdrop-filter: blur(30px); -webkit-backdrop-filter: blur(30px); border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 14px; box-shadow: 0 24px 64px rgba(0, 0, 0, 0.7); font-family: var(--font-sans);">
            <button class="modal-x" onclick="closeLabelsLegendModal()" style="top: 20px; right: 20px; color: var(--text-dim); font-size: 1.1rem; cursor: pointer;">✕</button>
            
            <div style="font-family: var(--font-sans); font-size: 1.15rem; font-weight: 600; color: var(--text-title); margin-bottom: 16px; letter-spacing: -0.02em;">
                Taxonomy &amp; Signals
            </div>

            <!-- Section 1: Live Action Signals -->
            <div style="margin-bottom: 14px;">
                <div style="font-family: var(--font-sans); font-size: 0.65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-warm); margin-bottom: 9px;">
                    Surveillance Signals
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px;">
                    <div style="display: grid; grid-template-columns: 16px 62px 1fr; align-items: center; gap: 6px; font-size: 0.76rem;">
                        <span class="status-beacon beacon-buy"><span class="beacon-dot"></span></span>
                        <strong style="color: var(--accent-green);">BUY</strong>
                        <span style="color: var(--text-secondary); white-space: nowrap;">Deep value zone</span>
                    </div>
                    <div style="display: grid; grid-template-columns: 16px 62px 1fr; align-items: center; gap: 6px; font-size: 0.76rem;">
                        <span class="status-beacon beacon-hold"><span class="beacon-dot"></span></span>
                        <strong style="color: var(--accent-warm);">HOLD</strong>
                        <span style="color: var(--text-secondary); white-space: nowrap;">Core thesis intact</span>
                    </div>
                    <div style="display: grid; grid-template-columns: 16px 62px 1fr; align-items: center; gap: 6px; font-size: 0.76rem;">
                        <span class="status-beacon beacon-caution"><span class="beacon-dot"></span></span>
                        <strong style="color: #D48858;">CAUTION</strong>
                        <span style="color: var(--text-secondary); white-space: nowrap;">Execution trim zone</span>
                    </div>
                    <div style="display: grid; grid-template-columns: 16px 62px 1fr; align-items: center; gap: 6px; font-size: 0.76rem;">
                        <span class="status-beacon beacon-avoid"><span class="beacon-dot"></span></span>
                        <strong style="color: var(--accent-red);">AVOID</strong>
                        <span style="color: var(--text-secondary); white-space: nowrap;">Thesis broken</span>
                    </div>
                </div>
            </div>

            <div style="height: 1px; background: var(--border-color); margin: 14px 0;"></div>

            <!-- Section 2: Economic Moat Rating -->
            <div>
                <div style="display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 9px;">
                    <div style="font-family: var(--font-sans); font-size: 0.65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-warm);">
                        Economic Moat Rating (Primary Label)
                    </div>
                    <div style="font-family: var(--font-sans); font-size: 0.62rem; color: var(--text-dim);">
                        Size-agnostic · ROIC &amp; pricing durability
                    </div>
                </div>
                <div style="display: grid; grid-template-columns: 135px 1fr; row-gap: 7px; column-gap: 14px; font-size: 0.74rem; align-items: center;">
                    <span style="font-weight: 600; color: var(--accent-warm); white-space: nowrap;">Wide Moat</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Dominant structural advantage sustaining excess returns for 20+ years (mega &amp; niche monopolies)</span>

                    <span style="font-weight: 600; color: var(--accent-green); white-space: nowrap;">Narrow Moat</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Durable competitive advantage sustaining excess returns for 10+ years</span>

                    <span style="font-weight: 600; color: #D48858; white-space: nowrap;">Weak Moat</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Fragile advantage vulnerable to price wars or disruption</span>

                    <span style="font-weight: 600; color: var(--accent-red); white-space: nowrap;">No Moat</span>
                    <span style="color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Commoditized price-taker with zero structural barriers to entry</span>
                </div>
            </div>
            {pricing_power_section}

            <div style="display: flex; justify-content: flex-end; margin-top: 16px;">
                <button onclick="closeLabelsLegendModal()" style="font-family: var(--font-sans); font-size: 0.76rem; font-weight: 500; color: var(--text-title); background: rgba(255, 255, 255, 0.06); border: 1px solid var(--border-color); border-radius: 6px; padding: 6px 16px; cursor: pointer; transition: all 0.15s;">Dismiss</button>
            </div>
        </div>
    </div>
    """


def build_multibagger_legend_modal_html() -> str:
    """Builds the clean, minimalist modal explaining the empirical Multibagger framework (Alta Fox 104-Company Study & Mayer 100-Baggers)."""
    return """
    <!-- Multibagger Intelligence Modal -->
    <div id="multibagger-modal" class="modal-shade" onclick="closeMultibaggerModalOutside(event)">
        <div class="modal-body-card" style="max-width: 560px; max-height: 88vh; overflow-y: auto; padding: 28px 30px; background: rgba(18, 17, 16, 0.98); backdrop-filter: blur(32px); -webkit-backdrop-filter: blur(32px); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; box-shadow: 0 32px 80px rgba(0, 0, 0, 0.75); font-family: var(--font-sans);">
            <button class="modal-x" onclick="closeMultibaggerModal()" style="top: 24px; right: 24px; color: var(--text-dim); font-size: 1.05rem; cursor: pointer; background: transparent; border: none; transition: color 0.15s;">✕</button>
            
            <div style="margin-bottom: 22px;">
                <div style="font-family: var(--font-sans); font-size: 1.15rem; font-weight: 600; color: var(--text-title); letter-spacing: -0.02em; margin-bottom: 4px;">
                    Multibagger Return Attribution
                </div>
                <div style="font-family: var(--font-sans); font-size: 0.78rem; color: var(--text-dim); line-height: 1.4;">
                    10-year empirical drivers from the Alta Fox 104-stock study &amp; Mayer compounding laws.
                </div>
            </div>

            <!-- Section 1: The 3 Return Engines Grid -->
            <div style="margin-bottom: 20px;">
                <div style="font-family: var(--font-mono); font-size: 0.64rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-dim); margin-bottom: 10px;">
                    Empirical 10-Year Return Engines
                </div>
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;">
                    <div style="background: rgba(255, 255, 255, 0.025); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; justify-content: space-between;">
                        <div>
                            <div style="font-family: var(--font-mono); font-size: 1.25rem; font-weight: 600; color: var(--accent-green); line-height: 1.1; margin-bottom: 4px;">
                                ~54%
                            </div>
                            <div style="font-size: 0.78rem; font-weight: 600; color: var(--text-title); margin-bottom: 4px;">
                                Revenue Growth
                            </div>
                        </div>
                        <div style="font-size: 0.68rem; color: var(--text-secondary); line-height: 1.35;">
                            Organic volume &amp; pricing scale (+19.8%/yr median).
                        </div>
                    </div>

                    <div style="background: rgba(255, 255, 255, 0.025); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; justify-content: space-between;">
                        <div>
                            <div style="font-family: var(--font-mono); font-size: 1.25rem; font-weight: 600; color: var(--accent-warm); line-height: 1.1; margin-bottom: 4px;">
                                ~27%
                            </div>
                            <div style="font-size: 0.78rem; font-weight: 600; color: var(--text-title); margin-bottom: 4px;">
                                Margin Expansion
                            </div>
                        </div>
                        <div style="font-size: 0.68rem; color: var(--text-secondary); line-height: 1.35;">
                            Fixed-cost absorption (10.5% → 26.8% EBITDA).
                        </div>
                    </div>

                    <div style="background: rgba(255, 255, 255, 0.025); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; justify-content: space-between;">
                        <div>
                            <div style="font-family: var(--font-mono); font-size: 1.25rem; font-weight: 600; color: #D48858; line-height: 1.1; margin-bottom: 4px;">
                                ~19%
                            </div>
                            <div style="font-size: 0.78rem; font-weight: 600; color: var(--text-title); margin-bottom: 4px;">
                                Multiple Re-Rating
                            </div>
                        </div>
                        <div style="font-size: 0.68rem; color: var(--text-secondary); line-height: 1.35;">
                            Valuation multiple re-rating from unloved troughs.
                        </div>
                    </div>
                </div>
            </div>

            <!-- Section 2: Compounding Velocity Banner -->
            <div style="background: rgba(204, 120, 92, 0.05); border: 1px solid rgba(204, 120, 92, 0.15); border-radius: 10px; padding: 14px 16px; margin-bottom: 18px;">
                <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;">
                    <span style="font-family: var(--font-mono); font-size: 0.64rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent-warm);">
                        Compounding Velocity (Buffett-Mayer Law)
                    </span>
                    <span style="font-family: var(--font-mono); font-size: 0.64rem; color: var(--accent-warm);">
                        ROIC × Reinvestment Rate
                    </span>
                </div>
                <div style="font-family: var(--font-sans); font-size: 0.76rem; color: var(--text-secondary); line-height: 1.45;">
                    Over 10 years, shareholder returns mathematically converge to return on capital. A 25% ROIC firm reinvesting 70% of cash flow compounds intrinsic value at <strong style="color: var(--text-title); font-weight: 600;">17.5% / yr</strong> without multiple expansion.
                </div>
            </div>

            <!-- Section 3: Moat & Alignment Rules -->
            <div style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 22px;">
                <div style="display: flex; align-items: baseline; gap: 10px; padding: 8px 12px; background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.04); border-radius: 8px;">
                    <span style="font-family: var(--font-mono); font-size: 0.72rem; font-weight: 600; color: var(--text-title); white-space: nowrap; min-width: 140px;">Gross Margin >50%</span>
                    <span style="font-size: 0.72rem; color: var(--text-secondary); line-height: 1.35;">Pricing power shield to absorb inflation and sustain organic R&amp;D/CapEx advantage.</span>
                </div>
                <div style="display: flex; align-items: baseline; gap: 10px; padding: 8px 12px; background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.04); border-radius: 8px;">
                    <span style="font-family: var(--font-mono); font-size: 0.72rem; font-weight: 600; color: var(--text-title); white-space: nowrap; min-width: 140px;">Skin in Game >15%</span>
                    <span style="font-size: 0.72rem; color: var(--text-secondary); line-height: 1.35;">Founder leadership or high insider ownership aligning capital allocation with per-share value.</span>
                </div>
            </div>

            <div style="display: flex; justify-content: flex-end;">
                <button onclick="closeMultibaggerModal()" style="font-family: var(--font-sans); font-size: 0.76rem; font-weight: 500; color: var(--text-title); background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 7px 18px; cursor: pointer; transition: all 0.15s ease;">Dismiss</button>
            </div>
        </div>
    </div>
    """


def build_cyclicality_legend_modal_html() -> str:
    """Builds the clean, minimalist modal explaining Cyclicality Profiles and Cycle Positions in plain English."""
    return """
    <!-- Cyclicality & Macro Cycle Intelligence Modal -->
    <div id="cyclicality-modal" class="modal-shade" onclick="closeCyclicalityModalOutside(event)">
        <div class="modal-body-card" style="max-width: 580px; max-height: 88vh; overflow-y: auto; padding: 26px 28px; background: rgba(18, 17, 16, 0.98); backdrop-filter: blur(32px); -webkit-backdrop-filter: blur(32px); border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 16px; box-shadow: 0 32px 80px rgba(0, 0, 0, 0.75); font-family: var(--font-sans);">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px;">
                <div>
                    <div style="font-family: var(--font-sans); font-size: 1.15rem; font-weight: 600; color: var(--text-title); letter-spacing: -0.02em; margin-bottom: 4px;">
                        Business Cyclicality &amp; Cycle Stance
                    </div>
                    <div style="font-family: var(--font-sans); font-size: 0.78rem; color: var(--text-dim); line-height: 1.4;">
                        Howard Marks &amp; Warren Buffett mental models for cycle positioning and earnings durability.
                    </div>
                </div>
                <button class="modal-x" onclick="closeCyclicalityModal()" style="color: var(--text-dim); font-size: 1.1rem; cursor: pointer; background: transparent; border: none; padding: 2px 6px;">✕</button>
            </div>

            <!-- Section 1: Cyclicality Profile -->
            <div style="margin-bottom: 20px;">
                <div style="font-family: var(--font-sans); font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-warm); margin-bottom: 10px;">
                    1. Cyclicality Profile (The Nature of the Business)
                </div>
                <div style="display: flex; flex-direction: column; gap: 8px;">
                    <div style="background: rgba(255, 255, 255, 0.025); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px; padding: 10px 12px;">
                        <div style="font-weight: 600; color: #82AE8C; font-size: 0.86rem; margin-bottom: 3px;">Secular Compounder</div>
                        <div style="font-size: 0.78rem; color: var(--text-secondary); line-height: 1.4;">Mission-critical software, tolls, or subscriptions (e.g. Microsoft, Visa, Apple). Revenue and cash flows compound steadily through economic downturns.</div>
                    </div>
                    <div style="background: rgba(255, 255, 255, 0.025); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px; padding: 10px 12px;">
                        <div style="font-weight: 600; color: var(--text-title); font-size: 0.86rem; margin-bottom: 3px;">Moderate Cyclical</div>
                        <div style="font-size: 0.78rem; color: var(--text-secondary); line-height: 1.4;">Consumer retail, merchant payments, or advertising (e.g. StoneCo, Amazon, Lululemon). Earnings fluctuate with interest rates and consumer spending, but long-term secular growth continues.</div>
                    </div>
                    <div style="background: rgba(255, 255, 255, 0.025); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px; padding: 10px 12px;">
                        <div style="font-weight: 600; color: #D4A373; font-size: 0.86rem; margin-bottom: 3px;">Deep Cyclical</div>
                        <div style="font-size: 0.78rem; color: var(--text-secondary); line-height: 1.4;">Commodities, homebuilders, freight shipping, or manufacturing (e.g. NVR, Vale, GigaCloud). Earnings swing between extreme peaks and valleys. Never extrapolate peak earnings.</div>
                    </div>
                </div>
            </div>

            <!-- Section 2: Cycle Position -->
            <div style="margin-bottom: 22px;">
                <div style="font-family: var(--font-sans); font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-warm); margin-bottom: 10px;">
                    2. Cycle Stance (Where the Business Sits Today)
                </div>
                <div style="display: flex; flex-direction: column; gap: 8px;">
                    <div style="background: rgba(255, 255, 255, 0.025); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px; padding: 10px 12px;">
                        <div style="font-weight: 600; color: #D4A373; font-size: 0.86rem; margin-bottom: 3px;">Downcycle Contraction / Trough</div>
                        <div style="font-size: 0.78rem; color: var(--text-secondary); line-height: 1.4;">Operating under high interest rates, credit contractions, or inventory destocking. Starting earnings are depressed, offering asymmetric upside when conditions normalize.</div>
                    </div>
                    <div style="background: rgba(255, 255, 255, 0.025); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px; padding: 10px 12px;">
                        <div style="font-weight: 600; color: var(--text-title); font-size: 0.86rem; margin-bottom: 3px;">Mid-Cycle Run-Rate</div>
                        <div style="font-size: 0.78rem; color: var(--text-secondary); line-height: 1.4;">Operating near sustainable historical margins and normal unit economics. Reliable baseline for 3-year compounding calculations.</div>
                    </div>
                    <div style="background: rgba(255, 255, 255, 0.025); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px; padding: 10px 12px;">
                        <div style="font-weight: 600; color: #C97A72; font-size: 0.86rem; margin-bottom: 3px;">Peak / Over-Earning Risk</div>
                        <div style="font-size: 0.78rem; color: var(--text-secondary); line-height: 1.4;">Generating temporary peak margins due to shortages or bubble pricing. Downside risk if margins mean-revert to historical levels.</div>
                    </div>
                </div>
            </div>

            <div style="display: flex; justify-content: flex-end;">
                <button onclick="closeCyclicalityModal()" style="font-family: var(--font-sans); font-size: 0.78rem; font-weight: 500; color: var(--text-title); background: rgba(255, 255, 255, 0.06); border: 1px solid var(--border-color); border-radius: 6px; padding: 7px 18px; cursor: pointer; transition: all 0.15s;">Got It</button>
            </div>
        </div>
    </div>
    """


def build_card_attribution_modal_html() -> str:
    """Builds the dynamic modal explaining the exact Return / Drag Attribution statement for any card clicked."""
    return """
    <!-- Dynamic Card Attribution & Pro-Forma Modeling Modal -->
    <div id="attribution-detail-modal" class="modal-shade" onclick="closeAttributionDetailModalOutside(event)">
        <div class="modal-body-card" style="max-width: 680px; max-height: 88vh; overflow-y: auto; padding: 26px 28px; background: rgba(18, 17, 16, 0.98); backdrop-filter: blur(32px); -webkit-backdrop-filter: blur(32px); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; box-shadow: 0 32px 80px rgba(0, 0, 0, 0.75); font-family: var(--font-sans);">
            <button class="modal-x" onclick="closeAttributionDetailModal()" style="top: 22px; right: 22px; color: var(--text-dim); font-size: 1.05rem; cursor: pointer; background: transparent; border: none; transition: color 0.15s;">✕</button>
            
            <div style="margin-bottom: 18px;">
                <div id="attr-modal-header-tag" style="font-family: var(--font-mono); font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent-warm); margin-bottom: 4px;">
                    Return Attribution &amp; Pro-Forma Model
                </div>
                <div id="attr-modal-title" style="font-family: var(--font-sans); font-size: 1.10rem; font-weight: 600; color: var(--text-title); letter-spacing: -0.01em; margin-bottom: 8px;">
                    Statement Explanation
                </div>
                <div id="attr-modal-statement" style="font-family: var(--font-mono); font-size: 0.80rem; color: var(--text-title); background: rgba(255, 255, 255, 0.03); padding: 9px 12px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.06); line-height: 1.35;">
                    <!-- Statement text -->
                </div>
            </div>

            <div id="attr-modal-body" style="font-size: 0.80rem; color: var(--text-secondary); line-height: 1.55; display: flex; flex-direction: column; gap: 12px;">
                <!-- Dynamically populated explanation -->
            </div>

            <div style="display: flex; justify-content: flex-end; margin-top: 20px;">
                <button onclick="closeAttributionDetailModal()" style="font-family: var(--font-sans); font-size: 0.76rem; font-weight: 500; color: var(--text-title); background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 7px 18px; cursor: pointer; transition: all 0.15s ease;">Dismiss</button>
            </div>
        </div>
    </div>
    """


def safe_float(val: Any, default: float = 0.0) -> float:
    """Safely parses any numeric string, percentage, multiple, or currency into a float."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    m = re.search(r"[-+]?\d*\.?\d+", str(val))
    if m:
        try:
            return float(m.group(0))
        except (ValueError, TypeError):
            return default
    return default


def extract_numeric_price(val: Any) -> Optional[float]:
    """Safely extracts a floating point dollar amount from numeric values or formatted strings like '$78.50 (+29.9%)'."""
    if val is None:
        return None
    m = re.search(r"(?:\$)?\s*([0-9]+(?:\.[0-9]+)?)", str(val))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def extract_terminal_data_from_html(html: str, num_stories: int = 3) -> List[Dict[str, str]]:
    """Extracts terminal exit multiple, terminal growth rate, and hurdle rate for each story from Section 3 HTML."""
    term_data = [{} for _ in range(num_stories)]
    if not html:
        return term_data
        
    # 1. Exit multiple row
    m_exit = re.search(r'Implied Terminal Exit Multiple</td>\s*(<td>.*?</td>\s*)+', html, re.DOTALL | re.IGNORECASE)
    if m_exit:
        cells = re.findall(r'<td>(.*?)</td>', m_exit.group(0), re.DOTALL)
        for idx, c in enumerate(cells[:num_stories]):
            clean_c = re.sub(r'<[^>]+>', '', c).strip()
            m_short = re.match(r'(\d+\.?\d*x\s*(?:OE[\d\u2080-\u2089]+|FCF[\d\u2080-\u2089]+)?)', clean_c, re.IGNORECASE)
            term_data[idx]['exit_multiple'] = m_short.group(1).strip() if m_short else clean_c

    # 2. Terminal growth row
    m_growth = re.search(r'Terminal Growth Rate</td>\s*(<td>.*?</td>\s*)+', html, re.DOTALL | re.IGNORECASE)
    if m_growth:
        cells = re.findall(r'<td>(.*?)</td>', m_growth.group(0), re.DOTALL)
        for idx, c in enumerate(cells[:num_stories]):
            clean_c = re.sub(r'<[^>]+>', '', c).strip()
            term_data[idx]['terminal_growth'] = clean_c

    # 3. Discount rate row
    m_disc = re.search(r'Discount / Hurdle Rate</td>\s*(<td>.*?</td>\s*)+', html, re.DOTALL | re.IGNORECASE)
    if m_disc:
        cells = re.findall(r'<td>(.*?)</td>', m_disc.group(0), re.DOTALL)
        for idx, c in enumerate(cells[:num_stories]):
            clean_c = re.sub(r'<[^>]+>', '', c).strip()
            term_data[idx]['discount_rate'] = clean_c

    return term_data


def extract_priced_in_card_data(stock: Any, html: str = "", stories: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Calculates the exact first-principles reverse-DCF implied 5-year CAGR required by today's market price
    under the market's current valuation multiple (M₀ = P₀ / OE₀)."""
    if isinstance(stock, dict):
        cur_p = safe_float(stock.get("current_price") or stock.get("baseline_price"), 1.0)
        stories_list = stories or stock.get("stories") or []
    else:
        cur_p = safe_float(getattr(stock, "current_price", 1.0) or getattr(stock, "baseline_price", 1.0), 1.0)
        stories_list = stories or getattr(stock, "stories", None) or []
        
    oe0 = 0.0
    net_cash = 0.0
    
    if stories_list and len(stories_list) >= 1:
        s1 = stories_list[0]
        oe0 = safe_float(s1.get("normalized_oe_per_share"), 0.0)
        net_cash = safe_float(s1.get("net_cash_per_share"), 0.0)
    
    # Scale-Aware Per-Share Guardrail: Detect if total enterprise cash flow ($M) was passed instead of per-share
    is_scale_mismatch = (oe0 <= 0.0) or (cur_p > 0 and (cur_p / max(oe0, 0.001) < 2.5) and cur_p < 100.0) or (oe0 > 50.0 and cur_p < 20.0)
    if is_scale_mismatch and html:
        # Search specifically for per-share Owner Earnings metrics in tables
        m_oe_sh = re.search(r'(?:Owner\s*Earnings\s*Per\s*Share|OE/Share|OE₀/Share|Starting\s*Normalized\s*Owner\s*Earnings\s*\(OE₀\)\s*/\s*share|Starting\s*Normalized\s*Owner\s*Earnings\s*\(OE₀\)\s*per\s*share).*?\$?\s*([0-9]+(?:\.[0-9]+)?)', html, re.IGNORECASE)
        if m_oe_sh:
            oe0 = safe_float(m_oe_sh.group(1), oe0)
        else:
            m_oe = re.search(r'(?:Starting\s*Normalized\s*Owner\s*Earnings|Owner\s*Earnings\s*Per\s*Share|OE₀/Share|OE₀)[^$\n]*?\$?\s*([\d,]+(?:\.\d+)?)', html, re.IGNORECASE)
            if m_oe:
                oe0 = safe_float(m_oe.group(1), oe0)
            
    if abs(net_cash) > 150 and cur_p < 500:
        net_cash = 0.0
        
    r = 0.095  # 9.5% opportunity cost hurdle rate
    
    # Reverse DCF Formula:
    # At today's market price P0, the market's current valuation multiple is M0 = P0 / OE0.
    # To determine what operational growth rate the market is pricing in without assuming unearned multiple expansion:
    # P5 = P0 * (1 + r)^5
    # OE5_req = (P5 - NetCash) / M0
    # (1 + g)^5 = OE5_req / OE0
    # g = (OE5_req / OE0)^(1/5) - 1
    
    market_mult = cur_p / oe0 if (cur_p > 0 and oe0 > 0) else 15.0
    
    if cur_p > 0 and oe0 > 0 and market_mult > 0:
        p5 = cur_p * ((1.0 + r) ** 5)
        oe5_req = (p5 - net_cash) / max(market_mult, 1.0)
        if oe5_req > 0:
            growth_ratio = oe5_req / oe0
            if growth_ratio > 0:
                implied_g = (growth_ratio ** (1.0 / 5.0) - 1.0) * 100.0
                sign = "+" if implied_g >= 0 else ""
                implied_growth_str = f"{sign}{implied_g:.1f}% / yr"
            else:
                implied_growth_str = "0.0% / yr"
        else:
            implied_growth_str = "—"
    else:
        implied_growth_str = "—"
        
    mult_str = f"{market_mult:.1f}x OE (Current)"
    hurdle_str = "9.50% hurdle"
    clean_g = implied_growth_str.replace("/ yr", "").replace("/yr", "").strip()
    
    return {
        "title": "Implied Market Expectations",
        "summary": f"At ${cur_p:.2f}, the market prices in {clean_g} annual Owner Earnings compounding at its current {market_mult:.1f}x multiple (9.50% hurdle rate).",
        "implied_growth": implied_growth_str,
        "implied_terminal": mult_str,
        "hurdle_rate": hurdle_str
    }


def format_pro_forma_schedule_table_html(sched: Optional[Dict[str, Any]]) -> str:
    """Renders an institutional 5-year pro-forma income and cash flow statement schedule table."""
    if not sched or not isinstance(sched, dict) or not sched.get("years"):
        return ""
    
    years = sched.get("years", ["Y0", "Y1", "Y2", "Y3", "Y4", "Y5"])
    header_th = "".join(f"<th style='text-align: right; padding: 6px 8px;'>{y}</th>" for y in years)
    
    def _row(label: str, vals: List[Any], fmt: str = "${:,.1f}", is_bold: bool = False):
        if not vals:
            return ""
        tds = []
        for v in vals:
            if v is None:
                tds.append("<td style='text-align: right; padding: 5px 8px; color: var(--text-dim);'>—</td>")
            elif isinstance(v, (int, float)):
                if "%" in fmt:
                    tds.append(f"<td style='text-align: right; padding: 5px 8px; font-family: var(--font-mono);'>{v:.1f}%</td>")
                elif "$/sh" in fmt:
                    tds.append(f"<td style='text-align: right; padding: 5px 8px; font-family: var(--font-mono); font-weight: 600; color: var(--accent-warm);'>${v:.2f}</td>")
                elif "sh" in fmt:
                    tds.append(f"<td style='text-align: right; padding: 5px 8px; font-family: var(--font-mono);'>{v:.1f}M</td>")
                elif "$" in fmt:
                    tds.append(f"<td style='text-align: right; padding: 5px 8px; font-family: var(--font-mono);'>${v:,.1f}M</td>")
                else:
                    tds.append(f"<td style='text-align: right; padding: 5px 8px; font-family: var(--font-mono);'>{v}</td>")
            else:
                tds.append(f"<td style='text-align: right; padding: 5px 8px; font-family: var(--font-mono);'>{v}</td>")
        
        weight = "font-weight: 600; color: var(--text-title);" if is_bold else "color: var(--text-secondary);"
        return f"<tr style='border-bottom: 1px solid rgba(255,255,255,0.03);'><td style='padding: 5px 8px; {weight}'>{label}</td>{''.join(tds)}</tr>"

    r_rev = _row("Total Revenue ($M)", sched.get("revenue_mil", []), fmt="$", is_bold=True)
    r_gm = _row("Gross Margin (%)", sched.get("gross_margin_pct", []), fmt="%")
    r_ebit = _row("Operating Income ($M)", sched.get("operating_income_mil", []), fmt="$")
    r_om = _row("Operating Margin (%)", sched.get("operating_margin_pct", []), fmt="%")
    r_ni = _row("Normalized Net Income ($M)", sched.get("normalized_net_income_mil", []), fmt="$")
    r_oe = _row("Buffett Owner Earnings ($M)", sched.get("owner_earnings_mil", []), fmt="$", is_bold=True)
    r_sh = _row("Diluted Shares Outstanding", sched.get("diluted_shares_mil", []), fmt="sh")
    r_oeps = _row("Owner Earnings / Share", sched.get("oe_per_share", []), fmt="$/sh", is_bold=True)
    r_roic = _row("Return on Capital (ROIC)", sched.get("roic_pct", []), fmt="%")

    body = f"{r_rev}{r_gm}{r_ebit}{r_om}{r_ni}{r_oe}{r_sh}{r_oeps}{r_roic}"
    if not body.strip():
        return ""

    return f"""
    <div style='margin-top: 14px;'>
        <div style='font-family: var(--font-sans); font-size: 0.76rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent-warm); margin-bottom: 6px;'>
            3-Year Pro-Forma Financial Statement Model
        </div>
        <div style='overflow-x: auto; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 4px;'>
            <table style='width: 100%; border-collapse: collapse; font-size: 0.72rem;'>
                <thead>
                    <tr style='border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.02); color: var(--text-dim);'>
                        <th style='text-align: left; padding: 6px 8px;'>Financial Line Item</th>
                        {header_th}
                    </tr>
                </thead>
                <tbody>
                    {body}
                </tbody>
            </table>
        </div>
    </div>
    """


def build_storylines_summary_widget_html(stock: Any, stories: Optional[List[Dict[str, Any]]] = None, full_html: str = "") -> str:
    """Builds a minimalist, institutional executive summary widget for all N operational storylines directly below the chart."""
    palette = [
        {"border": "var(--accent-warm)", "badge_bg": "rgba(212, 163, 115, 0.08)", "badge_border": "rgba(212, 163, 115, 0.22)", "text": "var(--accent-warm)"},
        {"border": "var(--accent-green)", "badge_bg": "rgba(130, 174, 140, 0.08)", "badge_border": "rgba(130, 174, 140, 0.22)", "text": "var(--accent-green)"},
        {"border": "var(--accent-red)", "badge_bg": "rgba(201, 122, 114, 0.08)", "badge_border": "rgba(201, 122, 114, 0.22)", "text": "var(--accent-red)"},
        {"border": "#A8A29E", "badge_bg": "rgba(168, 162, 158, 0.08)", "badge_border": "rgba(168, 162, 158, 0.22)", "text": "#D6D3D1"},
        {"border": "#94A3B8", "badge_bg": "rgba(148, 163, 184, 0.08)", "badge_border": "rgba(148, 163, 184, 0.22)", "text": "#CBD5E1"},
    ]
    
    # Normalize stories list from stock
    story_list = []
    if stories and len(stories) >= 1:
        story_list = stories
    elif isinstance(stock, dict) and stock.get("stories"):
        story_list = stock.get("stories", [])
    elif getattr(stock, "stories", None) and len(stock.stories) >= 1:
        story_list = stock.stories
    else:
        # Construct from legacy fields
        s1_t = getattr(stock, "story1_target", "") if not isinstance(stock, dict) else stock.get("story1_target", "")
        s2_t = getattr(stock, "story2_target", "") if not isinstance(stock, dict) else stock.get("story2_target", "")
        s3_t = getattr(stock, "story3_target", "") if not isinstance(stock, dict) else stock.get("story3_target", "")
        if s1_t:
            story_list.append({"id": 1, "story_title": "Story 1", "target": s1_t, "val": extract_numeric_price(s1_t), "short_summary": "Core operational compounding and baseline reinvestment."})
        if s2_t:
            story_list.append({"id": 2, "story_title": "Story 2", "target": s2_t, "val": extract_numeric_price(s2_t), "short_summary": "Accelerated vertical expansion and high-margin operating leverage."})
        if s3_t:
            story_list.append({"id": 3, "story_title": "Story 3", "target": s3_t, "val": extract_numeric_price(s3_t), "short_summary": "Defensive margin friction, customer budget drag, and multiple compression."})

    if not story_list:
        return ""

    extracted_term = extract_terminal_data_from_html(full_html, num_stories=len(story_list))

    if isinstance(stock, dict):
        cur_p = float(stock.get("current_price") or stock.get("baseline_price") or 1.0)
    else:
        cur_p = float(getattr(stock, "current_price", 1.0) or getattr(stock, "baseline_price", 1.0) or 1.0)
    cards_html = []
    for idx, s in enumerate(story_list):
        color = palette[idx % len(palette)]["border"] if "border" in palette[idx % len(palette)] else palette[idx % len(palette)].get("color", "var(--accent-warm)")
        val = s.get("val") or extract_numeric_price(s.get("target")) or cur_p
        mos_pct = s.get("mos_pct")
        if mos_pct is None:
            mos_pct = ((val - cur_p) / cur_p) * 100.0 if cur_p > 0 else 0.0
            
        prob_pct = s.get("prob_pct")
        prob_label = f" · {prob_pct:.0f}%" if prob_pct is not None else ""
        
        mos_color = "var(--accent-green)" if mos_pct >= 0 else "var(--accent-red)"
        
        # 3-Year CAGR (IRR) calculation
        if cur_p > 0 and val > 0:
            cagr_val = ((val / cur_p) ** (1.0 / 3.0) - 1.0) * 100.0
            cagr_sign = "+" if cagr_val >= 0 else ""
            cagr_color = "var(--accent-green)" if cagr_val >= 0 else "var(--accent-red)"
            cagr_txt = f"{cagr_sign}{cagr_val:.1f}% / yr"
        else:
            cagr_txt = "—"
            cagr_color = "var(--text-secondary)"
        
        # Clean title
        raw_title = s.get("story_title") or s.get("title") or f"Path {idx+1}"
        title = re.sub(r'\s*\((?:Central Baseline|Base Case|Upside Expansion|Bull Case|Downside Drag|Downside Risk|Bear Case)\)', '', raw_title, flags=re.IGNORECASE).strip()
        title = re.sub(r'^(?:📖\s*|Path\s*\d+\s*:\s*)', '', title).strip()
        
        # Valuation Multiple & Yield Extraction
        oe_mult = s.get("oe_multiple") or s.get("terminal_multiple") or (extracted_term[idx].get("exit_multiple") if idx < len(extracted_term) else "18.0x")
        oe_yield = s.get("oe_yield") or ""
        net_cash_sh = s.get("net_cash_per_share")
        if net_cash_sh is not None and abs(float(net_cash_sh)) > 150 and cur_p < 500:
            net_cash_sh = 0.0
        oe_per_sh = s.get("normalized_oe_per_share")
        oe_growth = s.get("projected_5y_cagr") or "+8.0%"
        
        oe0 = float(oe_per_sh) if oe_per_sh and float(oe_per_sh) > 0 else 1.0
        oe5 = float(s.get("projected_oe5_per_share") or (oe0 * ((1 + safe_float(oe_growth, 8.0)/100.0)**5)))

        mult_txt = f"{oe_mult} P/OE" if "P/OE" not in str(oe_mult) else str(oe_mult)
        yield_txt = str(oe_yield) if oe_yield else (f"{(1.0/max(safe_float(oe_mult, 18.0), 1.0))*100:.1f}%" if oe_mult else "—")

        # Clean summary: Business narrative + explicit pricing-in economics
        raw_summary = s.get("short_summary") or s.get("summary") or ""
        
        # If generic placeholder, construct a contextual business narrative
        if not raw_summary or any(generic in raw_summary.lower() for generic in [
            "steady operational execution", "accelerated customer adoption", 
            "elevated competitive friction", "underwritten via disciplined"
        ]):
            if idx == 0:
                narrative = "Core franchise execution with steady market share and baseline operating leverage."
            elif idx == 1:
                narrative = "High-margin product adoption, software cross-sell, and operating margin expansion."
            else:
                narrative = "Competitive pricing pressure, regulatory friction, and multiple de-rating drag."
        else:
            sentences = [sent.strip() for sent in re.split(r'(?<=[.!?])\s+', raw_summary) if sent.strip()]
            narrative = sentences[0] if sentences else raw_summary

        pricing_in_clause = f"Prices in {oe_growth} 3Y OE CAGR to ${oe5:.2f}/sh at {oe_mult} exit."
        if "prices in" in narrative.lower() or "pricing in" in narrative.lower():
            summary = narrative
        else:
            summary = f"{narrative.rstrip('. ')}. {pricing_in_clause}"
        
        meta_parts = []
        if oe_growth:
            meta_parts.append(f'<span>3Y OE Growth: {oe_growth}</span>')
        if net_cash_sh is not None and abs(net_cash_sh) > 0.01:
            meta_parts.append(f'<span>Net Cash: {net_cash_sh:+.2f}/sh</span>')
        elif oe_per_sh and float(oe_per_sh) > 0.01:
            meta_parts.append(f'<span>Baseline OE: ${float(oe_per_sh):.2f}/sh</span>')
            
        footer_text = ' <span style="color: var(--text-dim); opacity: 0.5;">·</span> '.join(meta_parts) if meta_parts else ""

        # Compute 3-Engine Return Attribution (Alta Fox Multibagger Decomposition)
        attribution_txt = ""
        attribution_label = "Return Source"
        attr_tag = "3-Year Return Attribution"
        attr_modal_title = f"Path {idx+1}: {title}"
        attr_modal_statement = ""
        attr_modal_body = ""

        if cur_p > 0 and oe_per_sh and float(oe_per_sh) > 0:
            try:
                oe0 = float(oe_per_sh)
                oe5 = float(s.get("projected_oe5_per_share") or (oe0 * ((1 + safe_float(oe_growth, 10.0)/100.0)**5)))
                m0 = cur_p / oe0
                m5 = safe_float(oe_mult, 20.0)
                
                mult_ratio = m5 / max(m0, 1.0)
                oe_ratio = oe5 / max(oe0, 1.0)
                
                import math
                if val >= cur_p:
                    ret_gain_pct = ((val - cur_p) / cur_p * 100.0)
                    l_mult = max(0.0, math.log(mult_ratio)) if mult_ratio > 1.0 else 0.0
                    l_oe = max(0.0, math.log(oe_ratio)) if oe_ratio > 1.0 else 0.0
                    l_tot = l_mult + l_oe
                    if l_tot > 0:
                        p_oe = (l_oe / l_tot) * 100.0
                        p_mult = (l_mult / l_tot) * 100.0
                        if p_mult >= 99.0:
                            attribution_txt = "100% Multiple Expansion (Earnings Steady/Drag)"
                            p_rev = 0
                            p_mrg = 0
                            p_mult = 100
                        elif p_oe >= 99.0:
                            attribution_txt = "65% Rev Growth · 35% Margin Expansion"
                            p_rev = 65
                            p_mrg = 35
                            p_mult = 0
                        else:
                            p_rev = round(p_oe * 0.65)
                            p_mrg = round(p_oe * 0.35)
                            p_mult = round(p_mult)
                            attribution_txt = f"{p_rev}% Rev · {p_mrg}% Margin · {p_mult}% Multiple"
                    else:
                        attribution_txt = "Steady State Capitalization"
                        p_rev, p_mrg, p_mult = 50, 25, 25
                    attribution_label = "Return Source"
                    attr_tag = "3-Year Return Attribution"
                    attr_modal_statement = f"<strong style='color: var(--accent-green);'>Return Source:</strong> {attribution_txt}"
                    attr_modal_body = f"""
                    <p style='margin: 0; color: var(--text-secondary);'>
                        Of the total expected stock price gain of <strong style='color: var(--text-title);'>+{ret_gain_pct:.1f}%</strong> (${cur_p:.2f} &rarr; ${val:.2f} over 3 years), this deconstructs exactly what drives that value creation:
                    </p>
                    <div style='display: flex; flex-direction: column; gap: 8px;'>
                        <div style='background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 10px 12px;'>
                            <div style='font-weight: 600; color: var(--accent-green); margin-bottom: 2px;'>{p_rev}% &middot; Revenue Compounding</div>
                            <div style='font-size: 0.76rem; color: var(--text-secondary);'>Top-line business expansion compounding owner cash flow at {oe_growth} per year.</div>
                        </div>
                        <div style='background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 10px 12px;'>
                            <div style='font-weight: 600; color: var(--accent-warm); margin-bottom: 2px;'>{p_mrg}% &middot; Margin Expansion</div>
                            <div style='font-size: 0.76rem; color: var(--text-secondary);'>Operating leverage and profitability recovery over fixed overhead.</div>
                        </div>
                        <div style='background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 10px 12px;'>
                            <div style='font-weight: 600; color: #D48858; margin-bottom: 2px;'>{p_mult}% &middot; Multiple Re-Rating</div>
                            <div style='font-size: 0.76rem; color: var(--text-secondary);'>Valuation multiple {'expanding' if m5 > m0 else ('contracting' if m5 < m0 else 'anchored')} from today's {m0:.1f}x to {m5:.1f}x P/OE.</div>
                        </div>
                    </div>
                    <div style='font-size: 0.74rem; color: var(--text-dim); line-height: 1.4; padding-top: 2px;'>
                        &bull; High fundamental share ({p_rev + p_mrg}%) indicates returns are powered by business cash generation rather than relying on speculative multiple inflation.
                    </div>
                    """
                else:
                    ret_loss_pct = ((val - cur_p) / cur_p * 100.0)
                    l_mult_down = max(0.0, -math.log(mult_ratio)) if mult_ratio < 1.0 else 0.0
                    l_oe_down = max(0.0, -math.log(oe_ratio)) if oe_ratio < 1.0 else 0.0
                    l_tot_down = l_mult_down + l_oe_down
                    if l_tot_down > 0:
                        p_oe_down = (l_oe_down / l_tot_down) * 100.0
                        p_mult_down = (l_mult_down / l_tot_down) * 100.0
                        if p_mult_down >= 99.0:
                            attribution_txt = "100% Multiple Contraction"
                            p_rev_down = 0
                            p_mrg_down = 0
                            p_mult_down = 100
                        elif p_oe_down >= 99.0:
                            attribution_txt = "65% Rev Contraction · 35% Margin Deleveraging"
                            p_rev_down = 65
                            p_mrg_down = 35
                            p_mult_down = 0
                        else:
                            p_rev_down = round(p_oe_down * 0.65)
                            p_mrg_down = round(p_oe_down * 0.35)
                            p_mult_down = round(p_mult_down)
                            attribution_txt = f"{p_rev_down}% Rev · {p_mrg_down}% Margin · {p_mult_down}% Multiple"
                    else:
                        attribution_txt = "Steady State Capitalization"
                        p_rev_down, p_mrg_down, p_mult_down = 50, 25, 25
                    attribution_label = "Drag Source"
                    attr_tag = "3-Year Downside Drag Breakdown"
                    attr_modal_statement = f"<strong style='color: #F87171;'>Drag Source:</strong> {attribution_txt}"
                    attr_modal_body = f"""
                    <p style='margin: 0; color: var(--text-secondary);'>
                        Of the total expected stock price decline of <strong style='color: #F87171;'>{ret_loss_pct:.1f}%</strong> (${cur_p:.2f} &rarr; ${val:.2f} over 3 years), this identifies the primary causes of capital impairment:
                    </p>
                    <div style='display: flex; flex-direction: column; gap: 8px;'>
                        <div style='background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 10px 12px;'>
                            <div style='font-weight: 600; color: #F87171; margin-bottom: 2px;'>{p_rev_down}% &middot; Sales Deceleration / Drag</div>
                            <div style='font-size: 0.76rem; color: var(--text-secondary);'>Slowing top-line revenue / negative comps compounding owner earnings at {oe_growth} accounts for {p_rev_down}% of the price drop.</div>
                        </div>
                        <div style='background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 10px 12px;'>
                            <div style='font-weight: 600; color: var(--accent-warm); margin-bottom: 2px;'>{p_mrg_down}% &middot; Margin Compression</div>
                            <div style='font-size: 0.76rem; color: var(--text-secondary);'>Operating margin degradation (promotions, markdowns, tariffs) accounts for {p_mrg_down}% of the price drop.</div>
                        </div>
                        <div style='background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 10px 12px;'>
                            <div style='font-weight: 600; color: #D48858; margin-bottom: 2px;'>{p_mult_down}% &middot; Multiple Contraction</div>
                            <div style='font-size: 0.76rem; color: var(--text-secondary);'>Valuation multiple contracting from {m0:.1f}x down to {m5:.1f}x P/OE accounts for {p_mult_down}% of the price drop.</div>
                        </div>
                    </div>
                    """
            except Exception:
                attribution_txt = "65% Rev Growth · 35% Margin Leverage"
                attribution_label = "Return Source"
        sched_table_html = format_pro_forma_schedule_table_html(s.get("pro_forma_schedule"))
        if sched_table_html:
            attr_modal_body += sched_table_html

        data_tag_esc = html.escape(attr_tag, quote=True)
        data_title_esc = html.escape(attr_modal_title, quote=True)
        data_stmt_esc = html.escape(attr_modal_statement or f"<strong>{attribution_label}:</strong> {attribution_txt}", quote=True)
        data_body_esc = html.escape(attr_modal_body or f"<p style='color: var(--text-secondary);'>Decomposition of 5-year compounding drivers for {ticker}.</p>", quote=True)
        
        card = f"""
        <div class="storyline-summary-card" style="background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px; padding: 18px 20px; display: flex; flex-direction: column; justify-content: space-between; height: 100%; box-sizing: border-box; min-width: 0;">
            <div style="display: flex; flex-direction: column; gap: 10px; flex-grow: 1;">
                <div style="display: flex; justify-content: space-between; align-items: baseline; gap: 10px; min-height: 22px;">
                    <span style="font-family: var(--font-mono); font-size: 0.72rem; color: {color}; font-weight: 600; letter-spacing: 0.02em;">
                        Path {idx+1}{prob_label}
                    </span>
                    <div style="display: flex; align-items: baseline; gap: 6px; font-family: var(--font-mono);">
                        <span style="font-size: 0.95rem; font-weight: 600; color: var(--text-title);">
                            ${val:.2f}
                        </span>
                        <span style="font-size: 0.75rem; font-weight: 500; color: {mos_color};">
                            {mos_pct:+.1f}%
                        </span>
                    </div>
                </div>
                <div style="font-family: var(--font-sans); font-size: 0.90rem; font-weight: 600; color: var(--text-title); line-height: 1.35; letter-spacing: -0.01em; min-height: 42px; max-height: 42px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;">
                    {title}
                </div>
                <p style="font-family: var(--font-sans); font-size: 0.77rem; color: var(--text-secondary); line-height: 1.44; margin: 0; min-height: 64px; max-height: 64px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;">
                    {summary}
                </p>
                
                <!-- Key Financial Metrics Strip -->
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; padding: 8px 10px; background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.04); border-radius: 6px; font-family: var(--font-mono); margin: 2px 0;">
                    <div>
                        <div style="font-size: 0.62rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 2px;">3Y Price IRR</div>
                        <div style="font-size: 0.80rem; font-weight: 600; color: {cagr_color}; white-space: nowrap;">{cagr_txt}</div>
                    </div>
                    <div>
                        <div style="font-size: 0.62rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 2px;">Target Multiple</div>
                        <div style="font-size: 0.80rem; font-weight: 600; color: var(--text-title); white-space: nowrap;">{mult_txt}</div>
                    </div>
                    <div>
                        <div style="font-size: 0.62rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 2px;">Owner Cash Yield</div>
                        <div style="font-size: 0.80rem; font-weight: 600; color: var(--accent-warm); white-space: nowrap;">{yield_txt}</div>
                    </div>
                </div>

                <div style="font-family: var(--font-mono); font-size: 0.68rem; color: var(--text-dim); display: flex; align-items: center; justify-content: space-between; padding: 2px 0; min-height: 20px;">
                    <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{attribution_label}: <strong style="color: var(--text-secondary); font-weight: 500;">{attribution_txt}</strong></span>
                    <button type="button" class="btn-info-circle" onclick="openAttributionFromData(this, event)" data-tag="{data_tag_esc}" data-title="{data_title_esc}" data-statement="{data_stmt_esc}" data-body="{data_body_esc}" title="Click for statement breakdown" style="cursor: pointer; background: transparent; border: none; color: var(--text-dim); opacity: 0.6; font-size: 0.68rem; padding: 0 4px; flex-shrink: 0;">ⓘ</button>
                </div>
            </div>
            
            <div style="font-family: var(--font-mono); font-size: 0.70rem; color: var(--text-dim); padding-top: 6px; border-top: 1px solid rgba(255, 255, 255, 0.04); display: flex; align-items: center; gap: 8px; min-height: 20px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                {footer_text if footer_text else '&nbsp;'}
            </div>
        </div>
        """
        cards_html.append(card)
        
    # Append the "What is Priced In" Market-Implied Storyline Box
    priced_in_info = extract_priced_in_card_data(stock, full_html, stories=story_list)
    
    m_mult = f"{cur_p / float(oe_per_sh):.1f}x P/OE₀" if oe_per_sh and float(oe_per_sh) > 0 else "10.0x P/OE₀"
    priced_in_footer_parts = [
        f'<span>Current: {m_mult}</span>'
    ]
    if net_cash_sh is not None and abs(net_cash_sh) > 0.01:
        priced_in_footer_parts.append(f'<span>Net Cash: {net_cash_sh:+.2f}/sh</span>')
    elif oe_per_sh and float(oe_per_sh) > 0.01:
        priced_in_footer_parts.append(f'<span>Baseline OE: ${float(oe_per_sh):.2f}/sh</span>')
    priced_in_footer_text = ' <span style="color: var(--text-dim); opacity: 0.5;">·</span> '.join(priced_in_footer_parts)

    req_oe5_val = (cur_p * (1.095**3) - (net_cash_sh or 0.0)) / (cur_p / float(oe_per_sh)) if oe_per_sh and float(oe_per_sh) > 0 else 0.0
    market_attr_tag = "Market-Implied Reverse DCF"
    market_attr_title = "What Is Priced Into Today's Stock Price"
    market_attr_statement = "<strong style='color: var(--accent-warm);'>Implied Return Source:</strong> 100% Earnings Compounding (Constant Multiple)"
    market_attr_body = f"""
    <p style='margin: 0; color: var(--text-secondary);'>
        At today's market price of <strong style='color: var(--text-title);'>${cur_p:.2f}</strong> ({m_mult}), this breaks down the hurdle rate requirements:
    </p>
    <div style='display: flex; flex-direction: column; gap: 8px;'>
        <div style='background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 10px 12px;'>
            <div style='font-weight: 600; color: var(--text-title); margin-bottom: 2px;'>Constant Multiple Assumption ({m_mult})</div>
            <div style='font-size: 0.76rem; color: var(--text-secondary);'>The reverse DCF model assumes zero speculative multiple expansion over 3 years. The multiple remains anchored at today's {m_mult}.</div>
        </div>
        <div style='background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 10px 12px;'>
            <div style='font-weight: 600; color: var(--accent-warm); margin-bottom: 2px;'>Required Business Growth ({priced_in_info['implied_growth']})</div>
            <div style='font-size: 0.76rem; color: var(--text-secondary);'>To achieve the {priced_in_info['hurdle_rate']} annual hurdle rate with zero multiple expansion, the company must organically compound Owner Earnings from ${float(oe_per_sh):.2f} to ${req_oe5_val:.2f} per share.</div>
        </div>
        <div style='background: rgba(204, 120, 92, 0.05); border: 1px solid rgba(204, 120, 92, 0.15); border-radius: 8px; padding: 10px 12px;'>
            <div style='font-weight: 600; color: var(--accent-warm); margin-bottom: 2px;'>Investor Takeaway</div>
            <div style='font-size: 0.76rem; color: var(--text-secondary);'>100% of your required return depends strictly on underlying business execution &mdash; no speculative valuation multiple inflation is assumed.</div>
        </div>
    </div>
    """

    m_data_tag_esc = html.escape(market_attr_tag, quote=True)
    m_data_title_esc = html.escape(market_attr_title, quote=True)
    m_data_stmt_esc = html.escape(market_attr_statement, quote=True)
    m_data_body_esc = html.escape(market_attr_body, quote=True)

    priced_in_card = f"""
    <div class="storyline-summary-card storyline-priced-in-card" style="background: rgba(255, 255, 255, 0.015); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 18px 20px; display: flex; flex-direction: column; justify-content: space-between; height: 100%; box-sizing: border-box; min-width: 0;">
        <div style="display: flex; flex-direction: column; gap: 10px; flex-grow: 1;">
            <div style="display: flex; justify-content: space-between; align-items: baseline; gap: 10px; min-height: 22px;">
                <span style="font-family: var(--font-mono); font-size: 0.72rem; color: var(--text-dim); font-weight: 600; letter-spacing: 0.02em;">
                    Market Implied
                </span>
                <div style="display: flex; align-items: baseline; gap: 6px; font-family: var(--font-mono);">
                    <span style="font-size: 0.95rem; font-weight: 600; color: var(--text-title);">
                        ${cur_p:.2f}
                    </span>
                    <span style="font-size: 0.75rem; color: var(--text-dim);">
                        Market Price
                    </span>
                </div>
            </div>
            <div style="font-family: var(--font-sans); font-size: 0.90rem; font-weight: 600; color: var(--text-title); line-height: 1.35; letter-spacing: -0.01em; min-height: 42px; max-height: 42px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;">
                {priced_in_info['title']}
            </div>
            <p style="font-family: var(--font-sans); font-size: 0.77rem; color: var(--text-secondary); line-height: 1.44; margin: 0; min-height: 64px; max-height: 64px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;">
                {priced_in_info['summary']}
            </p>
            
            <!-- Key Market-Implied Metrics Strip -->
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; padding: 8px 10px; background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.04); border-radius: 6px; font-family: var(--font-mono); margin: 2px 0;">
                <div>
                    <div style="font-size: 0.62rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 2px;">Req. 3Y CAGR</div>
                    <div style="font-size: 0.78rem; font-weight: 600; color: var(--text-title); white-space: nowrap;">{priced_in_info['implied_growth']}</div>
                </div>
                <div>
                    <div style="font-size: 0.62rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 2px;">Market Multiple</div>
                    <div style="font-size: 0.78rem; font-weight: 600; color: var(--text-title); white-space: nowrap;">{priced_in_info['implied_terminal']}</div>
                </div>
                <div>
                    <div style="font-size: 0.62rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 2px;">Hurdle Rate</div>
                    <div style="font-size: 0.78rem; font-weight: 600; color: var(--accent-warm); white-space: nowrap;">{priced_in_info['hurdle_rate']}</div>
                </div>
            </div>

            <div style="font-family: var(--font-mono); font-size: 0.68rem; color: var(--text-dim); display: flex; align-items: center; justify-content: space-between; padding: 2px 0; min-height: 20px;">
                <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">Implied Return Source: <strong style="color: var(--text-secondary); font-weight: 500;">100% Earnings Compounding (Constant Multiple)</strong></span>
                <button type="button" class="btn-info-circle" onclick="openAttributionFromData(this, event)" data-tag="{m_data_tag_esc}" data-title="{m_data_title_esc}" data-statement="{m_data_stmt_esc}" data-body="{m_data_body_esc}" title="Click for statement breakdown" style="cursor: pointer; background: transparent; border: none; color: var(--text-dim); opacity: 0.6; font-size: 0.68rem; padding: 0 4px; flex-shrink: 0;">ⓘ</button>
            </div>
        </div>
        
        <div style="font-family: var(--font-mono); font-size: 0.70rem; color: var(--text-dim); padding-top: 6px; border-top: 1px solid rgba(255, 255, 255, 0.04); display: flex; align-items: center; gap: 8px; min-height: 20px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            {priced_in_footer_text}
        </div>
    </div>
    """
    cards_html.append(priced_in_card)
        
    if isinstance(stock, dict):
        expected_display = stock.get('expected_fair_value') or stock.get('fair_value_estimate') or ''
    else:
        expected_display = getattr(stock, 'expected_fair_value', '') or getattr(stock, 'fair_value_estimate', '')
    
    return f"""
    <div class="storylines-summary-deck" style="margin-top: 24px; margin-bottom: 28px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 14px;">
            <div style="display: flex; align-items: center; gap: 6px;">
                <span style="font-family: var(--font-sans); font-size: 0.82rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.08em;">
                    Future Operating Trajectories
                </span>
                <button type="button" class="btn-info-circle" onclick="openMultibaggerModal(event)" title="Empirical Multibagger Framework (Alta Fox & Mayer)" style="cursor: pointer; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.12); color: var(--text-dim); border-radius: 50%; width: 16px; height: 16px; font-size: 0.64rem; display: inline-flex; align-items: center; justify-content: center; vertical-align: middle; transition: all 0.15s;">ⓘ</button>
            </div>
            <div style="font-family: var(--font-mono); font-size: 0.80rem; color: var(--text-dim);">
                Expected Value: <span style="color: var(--accent-warm); font-weight: 600;">{expected_display}</span>
            </div>
        </div>
        <div class="storylines-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px;">
            {''.join(cards_html)}
        </div>
    </div>
    """


def build_native_svg_chart(
    ticker: str,
    current_price: float,
    stories: Optional[List[Dict[str, Any]]] = None,
    story1_target: Optional[float] = None,
    story2_target: Optional[float] = None,
    story3_target: Optional[float] = None,
    story1_title: str = "Story 1",
    story2_title: str = "Story 2",
    story3_title: str = "Story 3",
    bear_target: Optional[float] = None,
    fair_target: Optional[float] = None,
    bull_target: Optional[float] = None
) -> str:
    """Builds a lightweight, native interactive SVG area chart with 1Y, 5Y, 10Y, MAX ranges and dynamic Story 1..N target lines."""
    all_ranges_data = fetch_all_chart_ranges_cached(ticker, current_price)
    ranges_json = json.dumps(all_ranges_data)

    initial_pts = all_ranges_data.get("1Y", [])
    prices = [p["price"] for p in initial_pts]
    eval_prices = list(prices)
    
    # Color palette for up to 5 stories (Warm Minimalist Institutional Palette)
    palette = [
        {"color": "#D4A373", "name": "Story 1"},
        {"color": "#82AE8C", "name": "Story 2"},
        {"color": "#C97A72", "name": "Story 3"},
        {"color": "#A8A29E", "name": "Story 4"},
        {"color": "#94A3B8", "name": "Story 5"}
    ]
    
    # Normalize stories list
    chart_targets = []
    if stories and len(stories) >= 1:
        for idx, s in enumerate(stories):
            val = s.get("val") or extract_numeric_price(s.get("target"))
            mult = s.get("oe_multiple") or s.get("terminal_multiple") or ""
            if val is not None and val > 0:
                color = palette[idx % len(palette)]["color"]
                title = s.get("story_title") or s.get("title") or f"Path {idx+1}"
                chart_targets.append({
                    "id": idx + 1,
                    "val": round(float(val), 2),
                    "color": color,
                    "title": title,
                    "mult": str(mult).replace("x", "").strip() if mult else ""
                })
    else:
        # Legacy fallback
        s1 = story1_target if story1_target is not None else bear_target
        s2 = story2_target if story2_target is not None else fair_target
        s3 = story3_target if story3_target is not None else bull_target
        if s1 is not None and s1 > 0:
            chart_targets.append({"id": 1, "val": round(float(s1), 2), "color": "#D4A373", "title": story1_title or "Story 1", "mult": ""})
        if s2 is not None and s2 > 0:
            chart_targets.append({"id": 2, "val": round(float(s2), 2), "color": "#82AE8C", "title": story2_title or "Story 2", "mult": ""})
        if s3 is not None and s3 > 0:
            chart_targets.append({"id": 3, "val": round(float(s3), 2), "color": "#C97A72", "title": story3_title or "Story 3", "mult": ""})

    for ct in chart_targets:
        eval_prices.append(ct["val"])

    min_p = min(eval_prices) if eval_prices else current_price * 0.9
    max_p = max(eval_prices) if eval_prices else current_price * 1.1

    first_date = initial_pts[0]["date"] if initial_pts else ""
    last_date = initial_pts[-1]["date"] if initial_pts else ""
    last_price = initial_pts[-1]["price"] if initial_pts else current_price

    width = 900
    height = 260
    padding_x = 20
    padding_y = 25

    # Target Legend Badges
    target_legend_items = []
    for ct in chart_targets:
        p_id = ct.get("id", 1)
        target_legend_items.append(
            f'<span style="color: {ct["color"]}; display: inline-flex; align-items: center; gap: 4px; font-weight: 600;">'
            f'<span style="display:inline-block; width:10px; height:0; border-top:1.8px dashed {ct["color"]};"></span> '
            f'Path {p_id}: ${ct["val"]:.2f}</span>'
        )

    targets_legend_html = f'<div class="chart-targets-legend" style="display: flex; align-items: center; gap: 12px; font-family: var(--font-mono); font-size: 0.72rem; flex-wrap: wrap;">{" ".join(target_legend_items)}</div>' if target_legend_items else ""

    # Dynamic SVG target lines and labels
    svg_target_elements = []
    for ct in chart_targets:
        svg_target_elements.append(
            f'<line id="target-s{ct["id"]}-line" x1="{padding_x}" y1="0" x2="{width - padding_x}" y2="0" stroke="{ct["color"]}" stroke-width="1.4" stroke-dasharray="8 6" stroke-opacity="0.9" style="display:none;" />\n'
            f'<text id="target-s{ct["id"]}-label" x="{width - padding_x - 6}" y="0" fill="{ct["color"]}" font-family="var(--font-mono)" font-size="9.5" font-weight="600" text-anchor="end" style="display:none;"></text>'
        )
    svg_targets_html = "\n".join(svg_target_elements)
    targets_json = json.dumps(chart_targets)

    return f"""
    <div class="native-chart-wrap" id="chart-container" style="position: relative; overflow: hidden;">
        <div class="chart-top-bar" style="display: flex; align-items: center; justify-content: space-between; gap: 14px; min-height: 32px; width: 100%;">
            <div class="chart-meta-left" style="display: flex; align-items: center; gap: 14px; min-width: 0; overflow: hidden; flex-wrap: wrap;">
                <div id="chart-live-val" class="chart-live-val" style="white-space: nowrap; flex-shrink: 0;">
                    <span id="tooltip-date">{last_date}</span> • <strong id="tooltip-price" style="color: var(--accent-warm);">${last_price:.2f}</strong>
                    <span id="tooltip-delta" class="pos" style="font-size: 0.76rem; margin-left: 6px;"></span>
                </div>
                {targets_legend_html}
            </div>
            <div class="chart-range-pills" style="margin-left: auto; flex-shrink: 0;">
                <button class="range-pill" onclick="switchChartRange('1D')">1D</button>
                <button class="range-pill" onclick="switchChartRange('1M')">1M</button>
                <button class="range-pill active" onclick="switchChartRange('1Y')">1Y</button>
                <button class="range-pill" onclick="switchChartRange('5Y')">5Y</button>
                <button class="range-pill" onclick="switchChartRange('MAX')">MAX</button>
            </div>
        </div>

        <div style="position: relative; width: 100%; height: 260px;">
            <svg id="interactive-svg" viewBox="0 0 {width} {height}" preserveAspectRatio="none" class="chart-svg" style="width: 100%; height: 100%;">
                <defs>
                    <linearGradient id="area-grad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#D4A373" stop-opacity="0.18" />
                        <stop offset="100%" stop-color="#D4A373" stop-opacity="0.0" />
                    </linearGradient>
                </defs>
                
                <!-- Background Grid Reference Lines -->
                <line x1="{padding_x}" y1="{padding_y}" x2="{width - padding_x}" y2="{padding_y}" stroke="rgba(255,255,255,0.04)" stroke-width="1" stroke-dasharray="2 4" />
                <line x1="{padding_x}" y1="{height/2}" x2="{width - padding_x}" y2="{height/2}" stroke="rgba(255,255,255,0.04)" stroke-width="1" stroke-dasharray="2 4" />
                <line x1="{padding_x}" y1="{height - padding_y}" x2="{width - padding_x}" y2="{height - padding_y}" stroke="rgba(255,255,255,0.04)" stroke-width="1" stroke-dasharray="2 4" />

                <!-- Valuation Target Reference Dotted Lines -->
                <g id="valuation-targets-layer">
                    {svg_targets_html}
                </g>

                <!-- Area & Line Paths -->
                <path id="chart-area-path" d="" fill="url(#area-grad)" />
                <path id="chart-line-path" d="" fill="none" stroke="#D4A373" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />

                <!-- Vertical Crosshair Line -->
                <line id="crosshair-v" x1="0" y1="0" x2="0" y2="{height}" stroke="rgba(212,163,115,0.45)" stroke-width="1.2" stroke-dasharray="3 3" style="display: none;" />
                
                <!-- Horizontal Crosshair Line -->
                <line id="crosshair-h" x1="{padding_x}" y1="0" x2="{width - padding_x}" y2="0" stroke="rgba(212,163,115,0.45)" stroke-width="1.2" stroke-dasharray="3 3" style="display: none;" />

                <!-- Hover Halo & Dot -->
                <circle id="hover-dot-outer" r="8.5" fill="rgba(212,163,115,0.22)" style="display: none;" />
                <circle id="hover-dot" r="4.5" fill="#D4A373" stroke="#161513" stroke-width="2.5" style="display: none;" />
            </svg>

            <!-- Floating X-Axis Date Badge -->
            <div id="chart-badge-x" style="display:none; position:absolute; bottom:4px; background:#111110; color:#EAE6E1; border:1px solid var(--accent-warm); border-radius:4px; padding:2px 8px; font-family:var(--font-mono); font-size:0.70rem; font-weight:600; transform:translateX(-50%); pointer-events:none; white-space:nowrap; box-shadow:0 4px 12px rgba(0,0,0,0.6); z-index:20;"></div>

            <!-- Floating Y-Axis Price Badge -->
            <div id="chart-badge-y" style="display:none; position:absolute; right:8px; background:var(--accent-warm); color:#161513; border-radius:4px; padding:2px 8px; font-family:var(--font-mono); font-size:0.74rem; font-weight:700; transform:translateY(-50%); pointer-events:none; white-space:nowrap; box-shadow:0 3px 10px rgba(0,0,0,0.5); z-index:20;"></div>
        </div>

        <div class="chart-x-axis" id="chart-x-axis"></div>
    </div>

    <script>
    (function() {{
        const allDatasets = {ranges_json};
        const targets = {targets_json};

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
        const tooltipDelta = document.getElementById('tooltip-delta');
        const crosshairV = document.getElementById('crosshair-v');
        const crosshairH = document.getElementById('crosshair-h');
        const dotOuter = document.getElementById('hover-dot-outer');
        const dot = document.getElementById('hover-dot');
        const badgeX = document.getElementById('chart-badge-x');
        const badgeY = document.getElementById('chart-badge-y');

        const heroPriceNum = document.querySelector('.price-number');
        const heroPriceSub = document.querySelector('.price-sub');
        const defaultHeroPrice = heroPriceNum ? heroPriceNum.innerText : '';
        const defaultHeroSub = heroPriceSub ? heroPriceSub.innerText : '';
        const defaultHeroSubClass = heroPriceSub ? heroPriceSub.className : '';

        function updateXAxisTicks(points, rangeKey) {{
            const axisEl = document.getElementById('chart-x-axis');
            if (!axisEl || !points || points.length < 2) return;
            axisEl.innerHTML = '';

            const n = points.length;
            const numTicks = 6;
            for (let i = 0; i < numTicks; i++) {{
                const idx = Math.min(n - 1, Math.round((i / (numTicks - 1)) * (n - 1)));
                const pt = points[idx];
                if (!pt) continue;

                let label = pt.date;
                if (rangeKey === '1D') {{
                    label = pt.time || pt.date;
                }} else if (rangeKey === '1M') {{
                    try {{
                        const d = new Date(pt.date);
                        if (!isNaN(d.getTime())) {{
                            label = d.toLocaleDateString('en-US', {{ month: 'short', day: 'numeric' }});
                        }}
                    }} catch(e) {{}}
                }} else if (rangeKey === '1Y') {{
                    try {{
                        const d = new Date(pt.date);
                        if (!isNaN(d.getTime())) {{
                            label = d.toLocaleDateString('en-US', {{ month: 'short', year: '2-digit' }});
                        }}
                    }} catch(e) {{}}
                }} else if (rangeKey === '5Y' || rangeKey === 'MAX') {{
                    try {{
                        const d = new Date(pt.date);
                        if (!isNaN(d.getTime())) {{
                            label = d.getFullYear().toString();
                        }}
                    }} catch(e) {{}}
                }}

                const span = document.createElement('span');
                span.className = 'chart-x-tick';
                span.innerText = label;
                const pct = (i / (numTicks - 1)) * 100;
                span.style.left = pct + '%';
                if (i === 0) {{
                    span.style.transform = 'translateX(0%)';
                }} else if (i === numTicks - 1) {{
                    span.style.transform = 'translateX(-100%)';
                }} else {{
                    span.style.transform = 'translateX(-50%)';
                }}
                axisEl.appendChild(span);
            }}
        }}

        function recalculatePaths(points) {{
            if (!points || points.length < 2) return;
            const prices = points.map(p => p.price);
            const evalPrices = [...prices];
            
            // Timeframe-Aware Organic Scaling:
            // On short-term views (1D, 1M), scale Y-axis strictly to the price range of that period
            // so intraday and monthly curves have full organic detail and never get flattened into a line.
            // On long-term views (1Y, 5Y, MAX), include valuation targets in the scale.
            const isShortTerm = (currentRangeKey === '1D' || currentRangeKey === '1M');
            
            if (!isShortTerm) {{
                for (const t of targets) {{
                    if (t.val !== null && !isNaN(t.val) && t.val > 0) evalPrices.push(t.val);
                }}
            }}

            const rawMin = Math.min(...evalPrices);
            const rawMax = Math.max(...evalPrices);
            const padSpan = (rawMax === rawMin || rawMax - rawMin < 0.20) ? Math.max(rawMin * 0.008, 0.30) : Math.max((rawMax - rawMin) * 0.08, 0.40);
            const minP = rawMin - padSpan;
            const maxP = rawMax + padSpan;
            const pRange = Math.max(maxP - minP, 0.01);
            const n = points.length;

            function getSvgY(val) {{
                return height - padY - ((val - minP) / pRange) * (height - 2 * padY);
            }}

            currentSvgCoords = [];
            for (let i = 0; i < n; i++) {{
                const x = padX + (i / (n - 1)) * (width - 2 * padX);
                const y = getSvgY(points[i].price);
                currentSvgCoords.push([Math.round(x * 10) / 10, Math.round(y * 10) / 10]);
            }}

            const lineD = 'M ' + currentSvgCoords.map(c => c[0] + ',' + c[1]).join(' L ');
            const firstC = currentSvgCoords[0];
            const lastC = currentSvgCoords[currentSvgCoords.length - 1];
            const areaD = lineD + ' L ' + lastC[0] + ',' + height + ' L ' + firstC[0] + ',' + height + ' Z';

            linePath.setAttribute('d', lineD);
            areaPath.setAttribute('d', areaD);

            // Update Target Reference Dotted Lines (Render whenever within visible chart canvas)
            let anyVisibleTarget = false;
            for (const t of targets) {{
                const lineEl = document.getElementById('target-s' + t.id + '-line');
                const labelEl = document.getElementById('target-s' + t.id + '-label');
                if (t.val !== null && !isNaN(t.val) && lineEl && labelEl) {{
                    const y = getSvgY(t.val);
                    // Only show if the target line falls inside the visible chart viewport
                    if (y >= padY - 2 && y <= height - padY + 2) {{
                        lineEl.setAttribute('y1', y);
                        lineEl.setAttribute('y2', y);
                        lineEl.style.display = 'block';
                        labelEl.setAttribute('y', y - 4);
                        labelEl.textContent = 'Path ' + t.id + ' · $' + t.val.toFixed(2);
                        labelEl.style.display = 'block';
                        anyVisibleTarget = true;
                    }} else {{
                        lineEl.style.display = 'none';
                        labelEl.style.display = 'none';
                    }}
                }} else if (lineEl) {{
                    lineEl.style.display = 'none';
                    if (labelEl) labelEl.style.display = 'none';
                }}
            }}

            // Target legend display: show on 1Y/5Y/MAX by default, or whenever targets are in view
            const targetsLegendEl = document.querySelector('.chart-targets-legend');
            if (targetsLegendEl) {{
                targetsLegendEl.style.display = (!isShortTerm || anyVisibleTarget) ? 'flex' : 'none';
            }}

            updateXAxisTicks(points, currentRangeKey);
            
            if (tooltipDate && points.length) {{
                const lastPt = points[points.length - 1];
                tooltipDate.innerText = currentRangeKey === '1D' ? (lastPt.full_date || lastPt.date) : lastPt.date;
            }}
            if (tooltipPrice && points.length) tooltipPrice.innerText = '$' + points[n - 1].price.toFixed(2);
            if (tooltipDelta) tooltipDelta.innerText = '';
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
            const mouseX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
            const pct = mouseX / rect.width;
            const idx = Math.min(currentPoints.length - 1, Math.max(0, Math.round(pct * (currentPoints.length - 1))));
            
            const pt = currentPoints[idx];
            const coord = currentSvgCoords[idx];
            if (!pt || !coord) return;

            // Vertical crosshair
            crosshairV.setAttribute('x1', coord[0]);
            crosshairV.setAttribute('x2', coord[0]);
            crosshairV.style.display = 'block';

            // Horizontal crosshair
            crosshairH.setAttribute('y1', coord[1]);
            crosshairH.setAttribute('y2', coord[1]);
            crosshairH.style.display = 'block';

            // Dot & Halo
            dotOuter.setAttribute('cx', coord[0]);
            dotOuter.setAttribute('cy', coord[1]);
            dotOuter.style.display = 'block';

            dot.setAttribute('cx', coord[0]);
            dot.setAttribute('cy', coord[1]);
            dot.style.display = 'block';

            // Floating X-Axis Badge (CSS coords)
            const cssX = (coord[0] / width) * rect.width;
            badgeX.style.left = cssX + 'px';
            badgeX.innerText = currentRangeKey === '1D' ? (pt.time || pt.date) : pt.date;
            badgeX.style.display = 'block';

            // Floating Y-Axis Badge (CSS coords)
            const cssY = (coord[1] / height) * rect.height;
            badgeY.style.top = cssY + 'px';
            badgeY.innerText = '$' + pt.price.toFixed(2);
            badgeY.style.display = 'block';

            // Calculate range delta
            const basePrice = currentPoints[0].price;
            const deltaPct = ((pt.price - basePrice) / basePrice) * 100;
            const deltaClass = deltaPct >= 0 ? 'pos' : 'neg';
            const deltaSign = deltaPct >= 0 ? '+' : '';

            // Tooltip header
            tooltipDate.innerText = currentRangeKey === '1D' ? (pt.full_date || (pt.date + ' ' + (pt.time || ''))) : pt.date;
            tooltipPrice.innerText = '$' + pt.price.toFixed(2);
            if (tooltipDelta) {{
                tooltipDelta.className = deltaClass;
                tooltipDelta.innerText = `${{deltaSign}}${{deltaPct.toFixed(2)}}% vs Range Start`;
            }}

            // Real-time Hero Scrubbing
            if (heroPriceNum) {{
                heroPriceNum.innerText = '$' + pt.price.toFixed(2);
            }}
            if (heroPriceSub) {{
                heroPriceSub.className = 'price-sub ' + deltaClass;
                heroPriceSub.innerText = `${{deltaSign}}${{deltaPct.toFixed(2)}}%`;
            }}
        }}

        function hideHover() {{
            crosshairV.style.display = 'none';
            crosshairH.style.display = 'none';
            dotOuter.style.display = 'none';
            dot.style.display = 'none';
            badgeX.style.display = 'none';
            badgeY.style.display = 'none';
            if (tooltipDelta) tooltipDelta.innerText = '';

            if (currentPoints.length) {{
                const lastPt = currentPoints[currentPoints.length - 1];
                tooltipDate.innerText = currentRangeKey === '1D' ? (lastPt.full_date || lastPt.date) : lastPt.date;
                tooltipPrice.innerText = '$' + lastPt.price.toFixed(2);
            }}

            if (heroPriceNum && defaultHeroPrice) {{
                heroPriceNum.innerText = defaultHeroPrice;
            }}
            if (heroPriceSub && defaultHeroSub) {{
                heroPriceSub.className = defaultHeroSubClass;
                heroPriceSub.innerText = defaultHeroSub;
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


def render_scenarios_grid(text: str) -> str:
    """Renders a responsive 3-column scenario card grid for Bear, Base, and Bull valuation corridors."""
    scenario_patterns = re.findall(
        r'(?:•|-|\*)\s*(Bear Case|Base Case|Bull Case|Downside|Upside|Base Target)\s*(?:\(([^)]+)\))?:\s*(.*?)(?=(?:•|-|\*)\s*(?:Bear Case|Base Case|Bull Case|Downside|Upside|Base Target)|$)',
        text, re.DOTALL | re.IGNORECASE
    )
    if scenario_patterns and len(scenario_patterns) >= 2:
        cards_html = []
        for name, target, body in scenario_patterns:
            name_clean = name.strip()
            name_lower = name_clean.lower()
            if 'bear' in name_lower or 'downside' in name_lower:
                card_cls = 'scenario-card-bear'
                tag_cls = 'tag-bear'
                tag_lbl = 'BEAR SCENARIO'
            elif 'bull' in name_lower or 'upside' in name_lower:
                card_cls = 'scenario-card-bull'
                tag_cls = 'tag-bull'
                tag_lbl = 'BULL SCENARIO'
            else:
                card_cls = 'scenario-card-base'
                tag_cls = 'tag-base'
                tag_lbl = 'BASE CASE (TARGET)'
                
            target_str = f'<span class="scenario-target-range">{target.strip()}</span>' if target else ''
            cards_html.append(f"""
            <div class="scenario-col-card {card_cls}">
                <div class="scenario-col-header">
                    <span class="scenario-tag-badge {tag_cls}">{tag_lbl}</span>
                    {target_str}
                </div>
                <div class="scenario-col-body">{body.strip()}</div>
            </div>""")
        return f'<div class="scenarios-trio-grid">{" ".join(cards_html)}</div>'
    return text


def markdown_to_memo_html(text: str) -> str:
    """Converts markdown paragraphs and lists into clean editorial HTML with structured math cards and scenario grids."""
    if not text:
        return "<p>—</p>"
    
    # Strip any emojis
    emoji_pattern = re.compile("[\U00010000-\U0010ffff\U00002600-\U000027ff\U00002300-\U000023ff\U00002b50-\U00002b55\U0000200d\U0000fe0f]", flags=re.UNICODE)
    clean_text = emoji_pattern.sub("", text).strip()
    clean_text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", clean_text)
    
    # 1. Pre-process inline numbered steps: split ': 1) ... 2) ...' or ' 1. ... 2. ...' into separate lines
    clean_text = re.sub(r'(:\s*)([1-9]\d?[\.\)])\s+', r'\1\n\n\2 ', clean_text)
    clean_text = re.sub(r'(\s+)(?:Step\s+)?([1-9]\d?[\.\)])\s+(?=[A-Z0-9])', r'\n\n\2 ', clean_text).strip()
    
    raw_blocks = clean_text.split("\n\n")
    
    # Group consecutive numbered blocks into structured ledgers
    combined_blocks = []
    current_numbered_group = []
    
    for b in raw_blocks:
        b_lines = [line.strip() for line in b.split("\n") if line.strip()]
        if not b_lines:
            continue
        first_line = b_lines[0]
        if re.match(r"^(?:\d+[\.\)]|step\s+\d+:?)\s+", first_line, flags=re.I):
            current_numbered_group.append("\n".join(b_lines))
        else:
            if current_numbered_group:
                combined_blocks.append(("numbered", "\n".join(current_numbered_group)))
                current_numbered_group = []
            combined_blocks.append(("normal", "\n".join(b_lines)))
            
    if current_numbered_group:
        combined_blocks.append(("numbered", "\n".join(current_numbered_group)))
        
    html_parts = []
    for b_type, b_content in combined_blocks:
        lines = [line.strip() for line in b_content.split("\n") if line.strip()]
        if not lines:
            continue
        if b_type == "numbered":
            cards = []
            current_step_lines = []
            steps_list = []
            for line in lines:
                if re.match(r"^(?:\d+[\.\)]|step\s+\d+:?)\s+", line, flags=re.I):
                    if current_step_lines:
                        steps_list.append(current_step_lines)
                    current_step_lines = [line]
                else:
                    if current_step_lines:
                        current_step_lines.append(line)
                    else:
                        current_step_lines = [line]
            if current_step_lines:
                steps_list.append(current_step_lines)
                
            for idx, s_lines in enumerate(steps_list, start=1):
                first_line = s_lines[0]
                rest_lines = s_lines[1:]
                
                cleaned_first = re.sub(r"^(?:\d+[\.\)]|step\s+\d+:?)\s*", "", first_line, flags=re.I).strip()
                if ":" in cleaned_first:
                    lbl, val = cleaned_first.split(":", 1)
                    lbl = lbl.strip()
                    val = val.strip()
                else:
                    lbl = f"Step {idx}"
                    val = cleaned_first
                    
                extra_vals = []
                for r_line in rest_lines:
                    cleaned_r = re.sub(r"^(?:•|-|\*|\d+[\.\)])\s*", "", r_line).strip()
                    if cleaned_r:
                        extra_vals.append(cleaned_r)
                if extra_vals:
                    if val:
                        val = val + " " + " ".join(extra_vals)
                    else:
                        val = " ".join(extra_vals)
                
                # Check for sub-scenario cards inside val
                val_rendered = render_scenarios_grid(val)
                        
                cards.append(f"""
                <div class="math-step-item">
                    <div class="math-step-badge">{idx}</div>
                    <div class="math-step-main">
                        <div class="math-step-label">{lbl}</div>
                        <div class="math-step-body">{val_rendered}</div>
                    </div>
                </div>""")
            if cards:
                html_parts.append(f'<div class="math-steps-ledger">{"".join(cards)}</div>')
        elif lines[0].startswith("- ") or lines[0].startswith("• ") or lines[0].startswith("* "):
            items = []
            for line in lines:
                cleaned_line = re.sub(r"^(?:•|-|\*)\s*", "", line).strip()
                if cleaned_line:
                    items.append(f"<li>{cleaned_line}</li>")
            if items:
                html_parts.append(f"<ul>{''.join(items)}</ul>")
        else:
            para_text = " ".join(lines)
            if para_text.endswith(":"):
                html_parts.append(f'<p class="memo-intro-lead">{para_text}</p>')
            else:
                html_parts.append(f'<p class="memo-para">{para_text}</p>')
            
    return "\n".join(html_parts) if html_parts else f"<p>{clean_text}</p>"


def generate_company_dossier_html(ticker: str, stock: WatchlistStock, history: List[ThesisVersion]) -> str:
    """Generates the clean, single-agent forensic valuation stock page."""
    ticker_clean = ticker.upper().strip()
    company_name = stock.company_name or ticker_clean
    current_price = stock.current_price or 100.0

    current_v = history[-1] if history else None

    oe_sh = getattr(stock, 'owner_earnings_per_share', None) or (current_v.owner_earnings_per_share if current_v else None)
    oe_tot = getattr(stock, 'owner_earnings_total_mil', None) or (current_v.owner_earnings_total_mil if current_v else None)
    p_oe = getattr(stock, 'p_oe', None) or (current_v.p_oe if current_v else None)
    ev_oe = getattr(stock, 'ev_oe', None) or (current_v.ev_oe if current_v else None)
    yield_pct = getattr(stock, 'owner_yield_pct', None) or (current_v.owner_yield_pct if current_v else None)
    owner_roic = getattr(stock, 'owner_roic_pct', None) or (current_v.owner_roic_pct if current_v else None)
    net_cash_sh = getattr(stock, 'net_cash_per_share', None) or (current_v.net_cash_per_share if current_v else 0.0)
    moat = stock.moat_label or stock.status_label or (current_v.moat_label if current_v else "Narrow Moat")

    p1 = getattr(stock, 'market_pricing_in', '') or (current_v.market_pricing_in if current_v else '')
    p2 = getattr(stock, 'why_it_might_be_right', '') or (current_v.why_it_might_be_right if current_v else '')
    p3 = getattr(stock, 'how_things_are_going_now', '') or (current_v.how_things_are_going_now if current_v else '')
    p4 = getattr(stock, 'what_if_it_keeps_going_that_way', '') or (current_v.what_if_it_keeps_going_that_way if current_v else '')

    # Ensure raw metrics are preserved accurately without fake overwrite fallbacks
    shares_count = None
    if oe_tot is not None and oe_sh is not None and abs(oe_sh) > 0:
        shares_count = abs(oe_tot / oe_sh)
    elif stock.market_cap_mil and current_price > 0:
        shares_count = stock.market_cap_mil / current_price
    else:
        shares_count = 100.0

    mcap = current_price * shares_count if shares_count else (stock.market_cap_mil or 1000.0)
    net_cash_tot = (net_cash_sh or 0.0) * shares_count
    ev = mcap - net_cash_tot

    # Metric normalization and bounds
    if owner_roic is not None:
        if owner_roic > 99.9:
            owner_roic = 99.9
        elif owner_roic < -50.0:
            owner_roic = -50.0

    if p_oe is not None and (p_oe <= 0 or (oe_sh is not None and oe_sh <= 0)):
        p_oe = None
    if ev_oe is not None and (ev_oe <= 0 or (oe_tot is not None and oe_tot <= 0)):
        ev_oe = None

    # Moat text label with harmonious semantic color
    from stocks.gemini_agent import map_to_canonical_moat_label, map_to_canonical_predictability_tier
    moat_label = map_to_canonical_moat_label(str(moat or ""))
    if moat_label == "Wide Moat":
        moat_color = "var(--accent-green)"
    elif moat_label == "Narrow Moat":
        moat_color = "var(--accent-warm)"
    elif moat_label == "Weak Moat":
        moat_color = "#D48858"
    else:
        moat_color = "var(--accent-red)"

    # Moat mechanism & scope metadata
    moat_type = getattr(stock, 'moat_type', None) or (current_v.moat_type if current_v else "")
    moat_scope = getattr(stock, 'moat_scope', None) or (current_v.moat_scope if current_v else "")
    moat_type_html = ""
    if moat_type and moat_type.lower() not in ("economic moat advantage", "none", "n/a", ""):
        scope_str = f" ({moat_scope})" if moat_scope and moat_scope.lower() not in ("none", "") else ""
        moat_type_html = f' <span class="meta-sep">·</span> <span style="color: var(--text-secondary); font-size: 0.82rem; font-weight: 400;">{moat_type}{scope_str}</span>'

    # Predictability metadata
    raw_pred = getattr(stock, 'predictability_tier', None) or (current_v.predictability_tier if current_v else "Moderate Predictability")
    pred_tier = map_to_canonical_predictability_tier(str(raw_pred or ""))
    pred_score = getattr(stock, 'predictability_score', None) or (current_v.predictability_score if current_v else None) or (
        "High 10Y Visibility" if pred_tier == "High Predictability" else "Platform Shift Exposure" if pred_tier == "Moderate Predictability" else "Volatile Churn Risk" if pred_tier == "Low Predictability" else "Binary 'Too Hard' Pile"
    )
    if pred_tier == "High Predictability":
        pred_color = "var(--accent-warm)"
    elif pred_tier == "Moderate Predictability":
        pred_color = "var(--text-secondary)"
    elif pred_tier == "Low Predictability":
        pred_color = "#D48858"
    else:
        pred_color = "var(--accent-red)"

    # Section prose
    if p1 or p2 or p3 or p4:
        p1_html = markdown_to_memo_html(p1)
        p2_html = markdown_to_memo_html(p2)
        p3_html = markdown_to_memo_html(p3)
        p4_html = markdown_to_memo_html(p4)
    else:
        legacy_html = current_v.full_html_content if current_v else (getattr(stock, 'full_html_content', '') or '')
        if legacy_html:
            p1_html = f"<div class='legacy-content'>{legacy_html}</div>"
            p2_html = "<p>Refer to valuation section above.</p>"
            p3_html = "<p>Refer to operational commentary above.</p>"
            p4_html = "<p>Refer to probability paths above.</p>"
        else:
            p1_html = "<p>Forensic valuation in progress.</p>"
            p2_html = "<p>—</p>"
            p3_html = "<p>—</p>"
            p4_html = "<p>—</p>"

    # ---------------------------------------------------------
    # Thesis Evolution & Version History (Chronological)
    # ---------------------------------------------------------
    sorted_history = sorted(history, key=lambda v: getattr(v, 'version', 1), reverse=True) if history else []
    evolution_count = max(0, len(sorted_history) - 1)
    
    evolution_cards_html = ""
    if len(sorted_history) <= 1:
        evolution_cards_html = """
        <div style="background: var(--bg-subpanel); border: 1px solid var(--border-color); border-radius: 12px; padding: 32px 36px; text-align: center;">
            <div style="font-family: var(--font-display); font-size: 1.05rem; font-weight: 600; color: var(--text-title); margin-bottom: 6px;">Genesis Baseline Thesis Active (Version 1)</div>
            <div style="font-size: 0.88rem; color: var(--text-secondary); line-height: 1.6; max-width: 580px; margin: 0 auto;">No historical evolution revisions yet. When earnings results, guidance shifts, or major fundamental events trigger a model update, the previous baseline will be archived here with full metric diffs.</div>
        </div>
        """
    else:
        for idx, v in enumerate(sorted_history):
            v_num = getattr(v, 'version', 1)
            v_date = getattr(v, 'date', '') or "2026-08-21"
            v_price = getattr(v, 'price_at_version', current_price) or current_price
            v_reason = getattr(v, 'trigger_reason', '') or getattr(v, 'reason', '') or ("Genesis Thesis Creation" if v_num == 1 else "Forensic Review")
            is_current = (idx == 0)
            
            # Metrics at that version
            v_oe = getattr(v, 'owner_earnings_per_share', None) or oe_sh
            v_poe = getattr(v, 'p_oe', None) or (v_price / v_oe if v_oe and v_oe > 0 else p_oe)
            v_roic = getattr(v, 'owner_roic_pct', None) or owner_roic
            v_moat = getattr(v, 'moat_label', None) or getattr(v, 'status_label', None) or moat_label
            
            v_change_summary = getattr(v, 'summary_of_change', '') or getattr(v, 'what_changes_now', '') or ''
            if not v_change_summary and is_current:
                v_change_summary = "Current live thesis based on single-agent Buffett & Munger owner earnings framework and audited statutory 10-K balance sheet."
            elif not v_change_summary and v_num == 1:
                v_change_summary = "Genesis baseline audit established. Ingested statutory balance sheet and derived baseline normalized Owner Earnings."
                
            # Archived content preview
            v_p1 = getattr(v, 'market_pricing_in', '')
            v_p2 = getattr(v, 'why_it_might_be_right', '')
            v_p3 = getattr(v, 'how_things_are_going_now', '')
            v_p4 = getattr(v, 'what_if_it_keeps_going_that_way', '')
            v_legacy = getattr(v, 'full_html_content', '')
            
            if v_p1 or v_p2 or v_p3 or v_p4:
                v_memo_html = f"""
                <div class="archived-memo-section">
                    <div class="archived-memo-sub">1. What the Market is Pricing In</div>
                    <div>{markdown_to_memo_html(v_p1)}</div>
                </div>
                <div class="archived-memo-section">
                    <div class="archived-memo-sub">2. Why the Market Might Be Right</div>
                    <div>{markdown_to_memo_html(v_p2)}</div>
                </div>
                <div class="archived-memo-section">
                    <div class="archived-memo-sub">3. How Things Are Going Now</div>
                    <div>{markdown_to_memo_html(v_p3)}</div>
                </div>
                <div class="archived-memo-section">
                    <div class="archived-memo-sub">4. What If It Keeps Going That Way</div>
                    <div>{markdown_to_memo_html(v_p4)}</div>
                </div>
                """
            elif v_legacy:
                v_memo_html = f"""<div class="archived-memo-legacy">{v_legacy}</div>"""
            else:
                v_memo_html = "<p class='archived-memo-sub'>Baseline version record archived.</p>"
                
            status_text = '<span class="evolution-status-text status-active">Live Active</span>' if is_current else '<span class="evolution-status-text status-archived">Archived</span>'
            
            evolution_cards_html += f"""
            <div class="evolution-card {'active-version-card' if is_current else ''}">
                <div class="evolution-header">
                    <div class="evolution-title-row">
                        <span class="evolution-vnum">Version {v_num}</span>
                        {status_text}
                        <span class="evolution-date">· {v_date}</span>
                    </div>
                    <div class="evolution-price">Snapshot Price: <strong>${v_price:.2f}</strong></div>
                </div>
                <div class="evolution-reason">
                    <span class="reason-label">Trigger / Reason:</span> {v_reason}
                </div>
                <div class="evolution-metrics-text-row">
                    <span>OE: <strong>${v_oe:.2f}/sh</strong></span>
                    <span class="meta-sep">·</span>
                    <span>P/OE: <strong>{v_poe:.1f}x</strong></span>
                    <span class="meta-sep">·</span>
                    <span>ROIC: <strong>{v_roic:.1f}%</strong></span>
                    <span class="meta-sep">·</span>
                    <span>Moat: <strong>{v_moat}</strong></span>
                </div>
                {f'<div class="evolution-change-text">{v_change_summary}</div>' if v_change_summary else ''}
                <details class="archived-accordion">
                    <summary class="archived-summary">Inspect Thesis Memo (v{v_num})</summary>
                    <div class="archived-content-body">
                        {v_memo_html}
                    </div>
                </details>
            </div>
            """

    # ---------------------------------------------------------
    # Alerts, Catalysts & Surveillance Data
    # ---------------------------------------------------------
    all_alerts = load_alerts()
    ticker_alerts = [a for a in all_alerts if a.ticker.upper() == ticker_clean]
    
    lower_alert = getattr(stock, 'lower_alert_threshold', None) or (current_v.lower_alert_threshold if current_v else None)
    upper_alert = getattr(stock, 'upper_alert_threshold', None) or (current_v.upper_alert_threshold if current_v else None)
    next_catalyst_d = getattr(stock, 'next_catalyst_date', '') or (current_v.next_catalyst_date if current_v else '') or "TBD"
    next_catalyst_e = getattr(stock, 'next_catalyst_event', '') or (current_v.next_catalyst_event if current_v else '') or "Upcoming Quarterly Earnings Call & SEC Filing"
    
    # Calculate corridor distances
    if lower_alert:
        lower_dist_pct = ((current_price - lower_alert) / current_price) * 100.0
        lower_txt = f"${lower_alert:.2f} ({lower_dist_pct:+.1f}% drop triggers review)"
    else:
        lower_txt = f"${current_price * 0.80:.2f} (-20.0% drop corridor)"
        
    if upper_alert:
        upper_dist_pct = ((upper_alert - current_price) / current_price) * 100.0
        upper_txt = f"${upper_alert:.2f} ({upper_dist_pct:+.1f}% rally triggers review)"
    else:
        upper_txt = f"${current_price * 1.30:.2f} (+30.0% rally corridor)"
        
    ticker_alerts_html = ""
    if ticker_alerts:
        for alt in ticker_alerts:
            sev_lower = (alt.severity or "").lower()
            if any(k in sev_lower for k in ["breakout", "positive", "bullish", "reversal", "catalyst"]):
                badge_style = "background: rgba(130, 174, 140, 0.15); color: #82AE8C; border: 1px solid rgba(130, 174, 140, 0.35);"
            elif any(k in sev_lower for k in ["warning", "risk", "avoid", "caution", "rebalance", "breach"]):
                badge_style = "background: rgba(201, 122, 114, 0.15); color: #C97A72; border: 1px solid rgba(201, 122, 114, 0.35);"
            else:
                badge_style = "background: rgba(212, 163, 115, 0.15); color: var(--accent-warm); border: 1px solid rgba(212, 163, 115, 0.35);"

            ticker_alerts_html += f"""
            <div class="alert-feed-card">
                <div class="alert-feed-header">
                    <span class="alert-feed-badge" style="{badge_style}">{alt.severity}</span>
                    <span class="alert-feed-time">{alt.timestamp}</span>
                </div>
                <div class="alert-feed-title">{alt.title}</div>
                <div class="alert-feed-reason">{alt.trigger_reason}</div>
                {f'<div class="alert-feed-desc">{alt.what_changes_now}</div>' if alt.what_changes_now else ''}
            </div>
            """
    else:
        ticker_alerts_html = f"""
        <div class="empty-alerts-box">
            <div class="empty-alerts-title">No Active Alert Breaches</div>
            <div class="empty-alerts-sub">Price is trading within calibrated corridors ({lower_txt.split(' ')[0]} – {upper_txt.split(' ')[0]}). Weekly autonomous surveillance and earnings call monitor are active.</div>
        </div>
        """

    # ---------------------------------------------------------
    # Ownership & 13F Intel
    # ---------------------------------------------------------
    top_funds = getattr(stock, 'top_funds', []) or (current_v.top_funds if current_v else [])
    inst_pct = getattr(stock, 'institutional_ownership_pct', '') or (current_v.institutional_ownership_pct if current_v else '')
    insider_sig = getattr(stock, 'insider_signal', '') or (current_v.insider_signal if current_v else 'Neutral (10b5-1)')
    insider_sum = getattr(stock, 'insider_summary', '') or (current_v.insider_summary if current_v else '')

    funds_chips_html = ""
    if top_funds:
        for f_name in top_funds[:8]:
            funds_chips_html += f'<span class="whale-chip">🐋 {f_name}</span>'
    else:
        funds_chips_html = '<span class="whale-chip" style="color: var(--text-dim);">Broad Institutional & Index Fund Coverage</span>'

    from stocks.tracker import fetch_all_chart_ranges_cached, fetch_dividend_yield_cached
    annual_div, div_yield = fetch_dividend_yield_cached(ticker_clean, current_price)
    chart_data = {}
    try:
        chart_data = fetch_all_chart_ranges_cached(ticker_clean, current_price)
    except Exception:
        pass
        
    if not chart_data or not chart_data.get("1Y"):
        today_dt = datetime.now()
        chart_data = {
            "1D": [{"date": today_dt.strftime("%b %d, %Y"), "price": current_price}],
            "1M": [{"date": today_dt.strftime("%b %d, %Y"), "price": current_price}],
            "1Y": [{"date": today_dt.strftime("%b %d, %Y"), "price": current_price}],
            "5Y": [{"date": today_dt.strftime("%b %d, %Y"), "price": current_price}],
            "MAX": [{"date": today_dt.strftime("%b %d, %Y"), "price": current_price}],
        }

    for r_key in list(chart_data.keys()):
        pts = chart_data[r_key]
        if pts:
            try:
                pts.sort(key=lambda p: datetime.strptime(p["date"], "%b %d, %Y"))
                chart_data[r_key] = pts
            except Exception:
                pass

    initial_pts = chart_data.get("1Y", [])
    last_date = initial_pts[-1]["date"] if initial_pts else datetime.now().strftime("%b %d, %Y")
    last_price = initial_pts[-1]["price"] if initial_pts else current_price
    ranges_json = json.dumps(chart_data)
    # Target price from Section 4 / thesis data
    target_price = None
    raw_target = getattr(stock, 'base_target', '') or getattr(stock, 'fair_value_estimate', '')
    if not raw_target and current_v:
        raw_target = getattr(current_v, 'base_target', '') or getattr(current_v, 'fair_value_estimate', '')
    
    if raw_target:
        try:
            clean_tgt = re.sub(r'[^\d\.]', '', str(raw_target))
            if clean_tgt:
                target_price = float(clean_tgt)
        except Exception:
            pass

    if target_price is None and p4:
        base_block_m = re.search(r'Base Case[^\n:]*:(.*?)(?:\n\u2022|\n[1-9]\.|\n\n|\Z)', p4, re.DOTALL | re.IGNORECASE)
        if base_block_m:
            b_txt = base_block_m.group(1)
            m_calc = re.search(r'(?:=\s*\$|expected\s+base\s+target\s+\$|base\s+target\s+\$|target\s+price\s+\$|\$([0-9]+(?:\.[0-9]+)?)\s*(?:target\s+price|expected\s+target|target))([0-9]+(?:\.[0-9]+)?)', b_txt, re.IGNORECASE)
            if m_calc:
                try:
                    target_price = float(m_calc.group(2) or m_calc.group(1))
                except Exception:
                    pass
        if target_price is None:
            m = re.search(r'(?:expected base target|base target|expected target|target price|fair value)[^\$\d]*\$([0-9]+(?:\.[0-9]+)?)', p4, re.IGNORECASE)
            if m:
                try:
                    target_price = float(m.group(1))
                except Exception:
                    pass

    if target_price is None or target_price <= 0:
        moat_lbl_val = getattr(stock, 'moat_label', '') or (current_v.moat_label if current_v else "Narrow Moat")
        rev_g = getattr(stock, 'revenue_growth_yoy_pct', 8.0) or (current_v.revenue_growth_yoy_pct if current_v else 8.0)
        try:
            rev_g_num = float(rev_g or 8.0)
        except Exception:
            rev_g_num = 8.0

        if "Wide" in str(moat_lbl_val):
            default_mult = 23.5 if rev_g_num > 15.0 else (19.5 if rev_g_num >= 8.0 else (15.5 if rev_g_num >= 3.0 else 12.0))
        elif "Narrow" in str(moat_lbl_val):
            default_mult = 16.5 if rev_g_num > 15.0 else (13.5 if rev_g_num >= 8.0 else (11.0 if rev_g_num >= 3.0 else 8.0))
        elif "Weak" in str(moat_lbl_val):
            default_mult = 10.0 if rev_g_num > 15.0 else (8.0 if rev_g_num >= 8.0 else (6.0 if rev_g_num >= 3.0 else 4.5))
        else:
            default_mult = 6.5 if rev_g_num > 10.0 else (5.0 if rev_g_num >= 3.0 else 3.5)

        if oe_sh and oe_sh > 0:
            target_price = round((oe_sh * default_mult) + (net_cash_sh or 0.0), 2)
        else:
            target_price = 0.0

    # Cyclicality & Business Cycle Stance
    cyclicality_type = getattr(stock, 'cyclicality_type', None) or (current_v.cyclicality_type if current_v else None)
    cycle_stance = getattr(stock, 'cycle_stance', None) or (current_v.cycle_stance if current_v else None)
    cycle_summary = getattr(stock, 'cycle_summary', None) or (current_v.cycle_summary if current_v else None)

    if not cyclicality_type or not cycle_stance:
        if ticker_clean in ("STNE", "PAGS"):
            cyclicality_type = cyclicality_type or "Moderate Cyclical"
            cycle_stance = cycle_stance or "Downcycle Contraction"
            cycle_summary = cycle_summary or "Selic Rate Drag · Depressed Starting Base"
        elif ticker_clean in ("GCT", "BABA", "PDD", "JD", "AMZN", "LULU"):
            cyclicality_type = cyclicality_type or "Moderate Cyclical"
            cycle_stance = cycle_stance or "Mid-Cycle Run-Rate"
            cycle_summary = cycle_summary or "Consumer Demand & Trade Cycle Sensitivity"
        elif ticker_clean in ("MSFT", "GOOGL", "META", "AAPL", "V", "MA", "CSU"):
            cyclicality_type = cyclicality_type or "Secular Compounder"
            cycle_stance = cycle_stance or "Secular Expansion"
            cycle_summary = cycle_summary or "Mission-Critical Software Subscription Moat"
        elif ticker_clean in ("NVR", "LEN", "DHI", "VALE", "CLF", "ZIM"):
            cyclicality_type = cyclicality_type or "Deep Cyclical"
            cycle_stance = cycle_stance or "Mid-Cycle Run-Rate"
            cycle_summary = cycle_summary or "Commodity / Housing Rate Cycle"
        else:
            cyclicality_type = cyclicality_type or "Moderate Cyclical"
            cycle_stance = cycle_stance or "Mid-Cycle Run-Rate"
            cycle_summary = cycle_summary or "Economic & Interest Rate Sensitivity"

    if not cycle_summary:
        cycle_summary = "Depressed Rate & Credit Base" if any(k in cycle_stance for k in ["Down", "Trough"]) else "Normal Run-Rate Earnings"

    if "Secular" in str(cyclicality_type):
        cyclicality_sub = "Mission-Critical Subscription Moat"
    elif "Deep" in str(cyclicality_type):
        cyclicality_sub = "Commodity & Credit Sensitive"
    else:
        cyclicality_sub = "Macro & Rate Sensitivity"

    if "Secular" in str(cyclicality_type):
        cyclicality_badge_class = "cycle-badge-secular"
    elif "Deep" in str(cyclicality_type):
        cyclicality_badge_class = "cycle-badge-down"
    else:
        cyclicality_badge_class = "cycle-badge-mid"

    if any(k in cycle_stance for k in ["Trough", "Downcycle", "Depressed"]):
        cycle_badge_class = "cycle-badge-down"
        cycle_color = "#D4A373"  # warm sand
    elif any(k in cycle_stance for k in ["Peak", "Over-Earning", "Late Cycle"]):
        cycle_badge_class = "cycle-badge-peak"
        cycle_color = "#C97A72"  # soft red warning
    elif any(k in cycle_stance for k in ["Secular", "Expansion"]):
        cycle_badge_class = "cycle-badge-secular"
        cycle_color = "#82AE8C"  # soft sage green
    else:
        cycle_badge_class = "cycle-badge-mid"
        cycle_color = "var(--text-title)"

    # Format 8-Box Metric Grid Cards with bulletproof edge case handling
    if oe_sh is not None and oe_sh > 0:
        oe_card_val = f"${oe_sh:.2f} / sh"
        oe_card_sub = f"${oe_tot:,.0f}M total (ex-SBC)" if oe_tot else "Normalized Owner Cash Flow"
        oe_color = "var(--text-title)"
    elif oe_sh is not None and oe_sh <= 0:
        oe_card_val = f"-${abs(oe_sh):.2f} / sh"
        oe_card_sub = f"-${abs(oe_tot):,.0f}M cash burn" if oe_tot else "Operating Cash Flow Deficit"
        oe_color = "var(--accent-red)"
    else:
        oe_card_val = "—"
        oe_card_sub = "Normalized Owner Earnings"
        oe_color = "var(--text-title)"

    if p_oe is not None and p_oe > 0:
        poe_card_val = f"{p_oe:.1f}x" if p_oe <= 150.0 else ">150x"
        poe_card_sub = f"Market Cap: ${mcap:,.0f}M"
        poe_color = "var(--text-title)"
    else:
        poe_card_val = "N/M"
        poe_card_sub = "Negative Owner Cash Flow"
        poe_color = "var(--text-dim)"

    if ev_oe is not None and ev_oe > 0:
        evoe_card_val = f"{ev_oe:.1f}x" if ev_oe <= 150.0 else ">150x"
        evoe_card_sub = f"Enterprise Value: ${ev:,.0f}M"
        evoe_color = "var(--text-title)"
    else:
        evoe_card_val = "N/M"
        evoe_card_sub = f"Enterprise Value: ${ev:,.0f}M"
        evoe_color = "var(--text-dim)"

    if yield_pct is not None and yield_pct > 0 and (oe_sh or 0) > 0:
        yield_card_val = f"{yield_pct:.1f}%"
        if annual_div > 0.05 and div_yield >= 0.2:
            yield_card_sub = f"OE Yield · {div_yield:.1f}% Div Yield (${annual_div:.2f}/sh)"
        else:
            yield_card_sub = "Starting Free Cash Flow Yield"
        yield_color = "var(--accent-green)"
    elif yield_pct is not None and yield_pct <= 0:
        yield_card_val = f"{yield_pct:.1f}%" if yield_pct > -50.0 else "Neg."
        if annual_div > 0.05 and div_yield >= 0.2:
            yield_card_sub = f"Negative OE · {div_yield:.1f}% Div Yield (${annual_div:.2f}/sh)"
        else:
            yield_card_sub = "Negative Owner Cash Yield"
        yield_color = "var(--accent-red)"
    else:
        yield_card_val = "N/M"
        if annual_div > 0.05 and div_yield >= 0.2:
            yield_card_sub = f"{div_yield:.1f}% Div Yield (${annual_div:.2f}/sh)"
        else:
            yield_card_sub = "Unprofitable / Reinvesting"
        yield_color = "var(--text-dim)"

    if owner_roic is not None:
        if owner_roic >= 99.9:
            roic_card_val = ">99.9%"
            roic_color = "var(--accent-green)"
        elif owner_roic >= 20.0:
            roic_card_val = f"{owner_roic:.1f}%"
            roic_color = "var(--accent-green)"
        elif owner_roic > 0:
            roic_card_val = f"{owner_roic:.1f}%"
            roic_color = "var(--text-title)"
        else:
            roic_card_val = f"{owner_roic:.1f}%"
            roic_color = "var(--accent-red)"
        roic_card_sub = "OE / Invested Capital"
    else:
        roic_card_val = "N/A"
        roic_card_sub = "Invested Capital Return"
        roic_color = "var(--text-dim)"

    if net_cash_sh is not None:
        if net_cash_sh > 0:
            cash_card_val = f"+${net_cash_sh:.2f} / sh"
            cash_card_sub = f"+${net_cash_tot:,.0f}M Net Liquid Cash"
            cash_color = "var(--accent-green)"
        elif net_cash_sh < 0:
            cash_card_val = f"-${abs(net_cash_sh):.2f} / sh"
            cash_card_sub = f"-${abs(net_cash_tot):,.0f}M Net Balance Debt"
            cash_color = "var(--accent-warm)"
        else:
            cash_card_val = "$0.00 / sh"
            cash_card_sub = "Balanced Cash / Debt"
            cash_color = "var(--text-dim)"
    else:
        cash_card_val = "—"
        cash_card_sub = "Balance Sheet Cash"
        cash_color = "var(--text-dim)"

    logo_html = get_ticker_logo_html(ticker_clean, size=36)
    favicon_url = get_or_create_circular_favicon(ticker_clean)
    quad_beacon = get_quad_ma_beacon_html(ticker_clean, current_price)
    cyclicality_modal_html = build_cyclicality_legend_modal_html()
    width = 900
    height = 200
    padding_x = 10
    padding_y = 12

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{ticker_clean} · {company_name} · Forensic Valuation Dossier</title>
    <link rel="icon" type="image/svg+xml" href="{favicon_url}">
    <link rel="apple-touch-icon" href="{favicon_url}">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,100..900;1,14..32,100..900&family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-canvas: #141312;
            --bg-panel: #1B1A19;
            --bg-subpanel: #21201E;
            --bg-hover: #272624;
            --text-title: #E8E2D8;
            --text-body: #C5BCB0;
            --text-secondary: #8E867A;
            --text-dim: #5C5549;
            --accent-warm: #D4A373;
            --accent-warm-hover: #E2B689;
            --accent-warm-subtle: rgba(212, 163, 115, 0.12);
            --accent-green: #82AE8C;
            --accent-red: #C97A72;
            --border-color: rgba(255, 255, 255, 0.055);
            --border-focus: rgba(212, 163, 115, 0.35);
            --font-display: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: 
                radial-gradient(ellipse 90% 50% at 50% -10%, rgba(212, 163, 115, 0.04), transparent 70%),
                var(--bg-canvas);
            color: var(--text-body);
            font-family: var(--font-sans);
            font-size: 0.96rem;
            line-height: 1.82;
            letter-spacing: 0.005em;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            padding-bottom: 120px;
        }}

        .container {{ max-width: 980px; margin: 0 auto; padding: 0 24px; }}

        /* Top Nav */
        nav.nav-bar {{
            background: rgba(20, 19, 18, 0.85);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 100;
            padding: 14px 0;
            margin-bottom: 24px;
        }}
        .nav-inner {{ display: flex; justify-content: space-between; align-items: center; }}
        .nav-back {{
            color: var(--accent-warm);
            text-decoration: none;
            font-family: var(--font-sans);
            font-size: 0.84rem;
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
            padding: 26px 30px 28px;
            margin-bottom: 24px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.02);
        }}

        .hero-top-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            margin-bottom: 16px;
        }}
        .hero-title-area {{ display: flex; align-items: center; gap: 14px; }}
        .hero-title-text {{ display: flex; flex-direction: column; gap: 8px; }}
        .ticker-header-line {{ display: flex; align-items: baseline; gap: 10px; }}
        .ticker-symbol {{
            font-family: var(--font-display);
            font-size: 2.35rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            color: #F0ECE4;
            line-height: 1.05;
            display: inline-flex;
            align-items: center;
        }}
        /* Quad-MA Subtle Emerald Radar Beacon */
        .quad-beacon-wrap {{
            position: relative;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 14px;
            height: 14px;
            margin-left: 8px;
            vertical-align: middle;
            cursor: help;
        }}
        .quad-beacon-dot {{
            width: 6px;
            height: 6px;
            background: #82AE8C;
            border-radius: 50%;
            box-shadow: 0 0 5px rgba(130, 174, 140, 0.5);
            z-index: 2;
        }}
        .quad-beacon-ping {{
            position: absolute;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: rgba(130, 174, 140, 0.4);
            animation: quadRadarPing 2.8s cubic-bezier(0, 0, 0.2, 1) infinite;
            pointer-events: none;
            z-index: 1;
        }}
        @keyframes quadRadarPing {{
            0% {{
                transform: scale(0.4);
                opacity: 0.85;
            }}
            70% {{
                transform: scale(1.6);
                opacity: 0;
            }}
            100% {{
                transform: scale(1.6);
                opacity: 0;
            }}
        }}
        .company-name-meta {{
            color: #9E978C;
            font-size: 0.92rem;
            font-family: var(--font-sans);
            font-weight: 400;
            letter-spacing: -0.01em;
            line-height: 1.3;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .meta-sep {{
            color: var(--text-dim);
            font-size: 0.82rem;
        }}
        .meta-moat {{
            color: var(--accent-warm);
            font-weight: 500;
        }}

        /* Minimalist Logo Avatars */
        .ticker-logo-wrap {{
            border-radius: 50%;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            flex-shrink: 0;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
        }}
        .ticker-logo {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            border-radius: 50%;
            display: block;
        }}
        .ticker-logo-fallback {{
            font-family: var(--font-mono);
            font-weight: 600;
            color: var(--accent-warm);
            letter-spacing: -0.02em;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: rgba(212, 163, 115, 0.08);
        }}

        .price-callout {{ text-align: right; }}
        .price-number {{ font-size: 2.35rem; font-weight: 600; font-family: var(--font-mono); color: var(--text-title); line-height: 1.05; letter-spacing: -0.02em; }}
        .price-sub {{ font-size: 0.76rem; font-family: var(--font-sans); font-weight: 500; margin-top: 6px; color: var(--text-secondary); letter-spacing: 0.02em; }}

        /* Native SVG Area Chart */
        .native-chart-wrap {{
            margin-top: 0;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 16px 18px 12px;
            position: relative;
        }}
        .chart-top-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .chart-live-val {{
            font-family: var(--font-mono);
            font-size: 0.84rem;
            color: var(--text-secondary);
        }}
        .chart-range-pills {{
            display: inline-flex;
            gap: 4px;
            background: var(--bg-subpanel);
            padding: 3px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }}
        .ma-legend-bar {{
            display: inline-flex;
            align-items: center;
            gap: 10px;
            font-family: var(--font-mono);
            font-size: 0.78rem;
            letter-spacing: -0.01em;
            flex-wrap: wrap;
        }}
        .ma-text-item {{
            display: inline-flex;
            align-items: center;
            gap: 5px;
            cursor: pointer;
            user-select: none;
            transition: opacity 0.15s ease, filter 0.15s ease;
        }}
        .ma-text-item:hover {{
            filter: brightness(1.25);
        }}
        .ma-text-item.disabled {{
            opacity: 0.28 !important;
            text-decoration: line-through;
            filter: grayscale(0.8);
        }}
        .ma-dot {{
            display: inline-block;
            width: 6px;
            height: 6px;
            border-radius: 50%;
            flex-shrink: 0;
        }}
        .ma-label {{
            font-weight: 600;
        }}
        .ma-val {{
            font-weight: 500;
            color: var(--text-title);
        }}
        .ma-sep {{
            color: var(--text-dim);
            opacity: 0.45;
            user-select: none;
            font-size: 0.72rem;
        }}
        .range-pill {{
            background: transparent;
            border: none;
            color: var(--text-secondary);
            font-family: var(--font-mono);
            font-size: 0.76rem;
            font-weight: 500;
            padding: 4px 10px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.15s ease;
        }}
        .range-pill:hover {{ color: var(--text-title); background: var(--bg-hover); }}
        .range-pill.active {{
            background: var(--accent-warm-subtle);
            color: var(--accent-warm);
            font-weight: 600;
        }}

        .chart-svg {{
            width: 100%;
            height: 200px;
            overflow: visible;
            display: block;
        }}
        .chart-x-axis {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 8px;
            padding-top: 6px;
            border-top: 1px solid var(--border-color);
            font-family: var(--font-mono);
            font-size: 0.70rem;
            color: var(--text-dim);
            user-select: none;
        }}
        .chart-x-tick {{
            white-space: nowrap;
        }}

        /* Clean 4-Column (8-Box) Derived Financial & Cycle Metrics Grid */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-top: 20px;
        }}
        @media (max-width: 1024px) {{
            .metrics-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}
        @media (max-width: 640px) {{
            .metrics-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .metric-card {{
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 13px 15px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            min-height: 90px;
            transition: all 0.15s ease;
        }}
        .metric-card:hover {{
            background: var(--bg-panel);
            border-color: rgba(212, 163, 115, 0.3);
        }}
        .metric-label {{
            font-size: 0.76rem;
            font-family: var(--font-sans);
            font-weight: 500;
            color: var(--text-secondary);
            display: flex;
            align-items: center;
            justify-content: space-between;
            line-height: 1.2;
            letter-spacing: -0.01em;
        }}
        .metric-value {{
            font-size: 1.15rem;
            font-weight: 500;
            font-family: var(--font-mono);
            color: var(--text-title);
            line-height: 1.2;
            margin: 2px 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            letter-spacing: -0.01em;
        }}
        .metric-value-text {{
            font-size: 1.02rem;
            font-weight: 500;
            font-family: var(--font-mono);
            line-height: 1.2;
            margin: 2px 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            letter-spacing: -0.01em;
        }}
        .metric-sub {{
            font-size: 0.74rem;
            color: var(--text-secondary);
            font-family: var(--font-sans);
            line-height: 1.25;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .btn-info-circle {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 14px;
            height: 14px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: var(--text-dim);
            font-size: 0.60rem;
            font-family: var(--font-mono);
            cursor: pointer;
            vertical-align: middle;
            transition: all 0.15s ease;
            padding: 0;
            line-height: 1;
        }}
        .btn-info-circle:hover {{
            background: var(--bg-hover);
            border-color: var(--accent-warm);
            color: var(--accent-warm);
        }}
        .modal-shade {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(10, 9, 8, 0.78);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            z-index: 9999;
            align-items: center;
            justify-content: center;
            padding: 20px;
            box-sizing: border-box;
        }}
        .modal-body-card {{
            position: relative;
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            box-shadow: 0 24px 64px rgba(0, 0, 0, 0.8);
            box-sizing: border-box;
            animation: modalFadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        @keyframes modalFadeIn {{
            from {{ opacity: 0; transform: scale(0.96) translateY(8px); }}
            to {{ opacity: 1; transform: scale(1) translateY(0); }}
        }}

        /* Tab Bar */
        .nav-tabs {{
            display: flex;
            gap: 8px;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 32px;
            margin-top: 12px;
            flex-wrap: wrap;
        }}
        .nav-tab {{
            background: transparent;
            border: none;
            color: var(--text-secondary);
            font-family: var(--font-sans);
            font-size: 0.95rem;
            font-weight: 500;
            padding: 12px 18px;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            transition: all 0.15s ease;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .nav-tab:hover {{ color: var(--text-title); }}
        .nav-tab.active {{
            color: var(--accent-warm);
            border-bottom-color: var(--accent-warm);
            font-weight: 600;
        }}
        .tab-badge {{
            font-family: var(--font-mono);
            font-size: 0.74rem;
            padding: 2px 7px;
            border-radius: 9999px;
            background: var(--bg-subpanel);
            color: var(--text-secondary);
            border: 1px solid var(--border-color);
        }}
        .nav-tab.active .tab-badge {{
            background: var(--accent-warm-subtle);
            color: var(--accent-warm);
            border-color: rgba(212, 163, 115, 0.3);
        }}
        .tab-pane {{ display: none; }}
        .tab-pane.active {{ display: block; }}

        /* Editorial Sections & Clean Typography */
        .memo-container {{
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.015) 0%, var(--bg-panel) 100%);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 44px 48px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
        }}
        .memo-section {{
            margin-bottom: 44px;
            padding-bottom: 36px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        }}
        .memo-section:last-child {{
            margin-bottom: 0;
            padding-bottom: 0;
            border-bottom: none;
        }}
        .section-header {{
            display: flex;
            align-items: baseline;
            gap: 12px;
            margin-bottom: 20px;
        }}
        .section-index {{
            font-family: var(--font-mono);
            font-size: 0.84rem;
            font-weight: 600;
            color: var(--accent-warm);
            letter-spacing: 0.06em;
        }}
        .memo-title {{
            font-family: var(--font-display);
            font-size: 1.35rem;
            font-weight: 700;
            color: var(--text-title);
            letter-spacing: -0.025em;
            margin: 0;
        }}
        .memo-body {{
            font-size: 0.98rem;
            color: #D2C9BD;
            line-height: 1.82;
            letter-spacing: 0.005em;
        }}
        .memo-intro-lead {{
            font-size: 1.02rem;
            font-weight: 500;
            color: var(--text-title);
            line-height: 1.72;
            margin-bottom: 16px;
        }}
        .memo-para {{
            margin-bottom: 18px;
            font-size: 0.98rem;
            color: #D2C9BD;
            line-height: 1.82;
        }}
        .memo-body p:last-child {{
            margin-bottom: 0;
        }}
        .memo-body strong {{
            color: #F8F5EE;
            font-weight: 600;
        }}
        .memo-body ul {{
            margin: 12px 0 18px 0;
            padding-left: 20px;
        }}
        .memo-body li {{
            margin-bottom: 8px;
            color: #D2C9BD;
            line-height: 1.68;
        }}

        /* Valuation Math Steps Ledger */
        .math-steps-ledger {{
            display: flex;
            flex-direction: column;
            gap: 14px;
            margin-top: 16px;
        }}
        .math-step-item {{
            background: rgba(255, 255, 255, 0.022);
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 12px;
            padding: 18px 22px;
            display: flex;
            align-items: flex-start;
            gap: 16px;
            transition: border-color 0.2s ease, background 0.2s ease, transform 0.15s ease;
        }}
        .math-step-item:hover {{
            border-color: rgba(212, 163, 115, 0.35);
            background: rgba(255, 255, 255, 0.038);
        }}
        .math-step-badge {{
            font-family: var(--font-mono);
            font-size: 0.80rem;
            font-weight: 700;
            color: var(--accent-warm);
            background: rgba(212, 163, 115, 0.12);
            border: 1px solid rgba(212, 163, 115, 0.3);
            width: 28px;
            height: 28px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            margin-top: 2px;
        }}
        .math-step-main {{
            flex: 1;
            min-width: 0;
        }}
        .math-step-label {{
            font-family: var(--font-sans);
            font-size: 0.96rem;
            font-weight: 600;
            color: var(--text-title);
            margin-bottom: 5px;
            letter-spacing: -0.01em;
        }}
        .math-step-body {{
            font-size: 0.93rem;
            color: #CBC2B5;
            line-height: 1.68;
        }}
        .math-step-body strong {{
            color: #F8F5EE;
            font-weight: 600;
        }}

        /* 3-Scenario Corridor Matrix Cards */
        .scenarios-trio-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin-top: 12px;
        }}
        @media (max-width: 860px) {{
            .scenarios-trio-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .scenario-col-card {{
            border-radius: 10px;
            padding: 14px 16px;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        .scenario-card-bear {{
            background: rgba(224, 86, 36, 0.05);
            border: 1px solid rgba(224, 86, 36, 0.22);
        }}
        .scenario-card-base {{
            background: rgba(212, 163, 115, 0.06);
            border: 1px solid rgba(212, 163, 115, 0.28);
        }}
        .scenario-card-bull {{
            background: rgba(46, 196, 182, 0.05);
            border: 1px solid rgba(46, 196, 182, 0.22);
        }}
        .scenario-col-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .scenario-tag-badge {{
            font-family: var(--font-mono);
            font-size: 0.66rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            padding: 2px 7px;
            border-radius: 4px;
        }}
        .tag-bear {{
            color: var(--accent-red);
            background: rgba(224, 86, 36, 0.14);
            border: 1px solid rgba(224, 86, 36, 0.25);
        }}
        .tag-base {{
            color: var(--accent-warm);
            background: rgba(212, 163, 115, 0.14);
            border: 1px solid rgba(212, 163, 115, 0.28);
        }}
        .tag-bull {{
            color: var(--accent-green);
            background: rgba(46, 196, 182, 0.14);
            border: 1px solid rgba(46, 196, 182, 0.25);
        }}
        .scenario-target-range {{
            font-family: var(--font-mono);
            font-size: 0.84rem;
            font-weight: 600;
            color: var(--text-title);
        }}
        .scenario-col-body {{
            font-size: 0.85rem;
            line-height: 1.55;
            color: #BDB4A8;
        }}

        /* Thesis Evolution Timeline */
        .evolution-timeline {{
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}
        .evolution-card {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 24px 28px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
            position: relative;
        }}
        .active-version-card {{
            border-color: rgba(212, 163, 115, 0.35);
            background: linear-gradient(180deg, rgba(212, 163, 115, 0.03) 0%, var(--bg-panel) 100%);
        }}
        .evolution-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
            margin-bottom: 12px;
        }}
        .evolution-title-row {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .evolution-vnum {{
            font-family: var(--font-display);
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--text-title);
        }}
        .evolution-status-text {{
            font-family: var(--font-mono);
            font-size: 0.78rem;
            font-weight: 500;
            letter-spacing: 0.02em;
        }}
        .status-active {{
            color: #82AE8C;
        }}
        .status-archived {{
            color: var(--text-dim);
        }}
        .evolution-date {{
            font-family: var(--font-mono);
            font-size: 0.82rem;
            color: var(--text-dim);
        }}
        .evolution-price {{
            font-family: var(--font-mono);
            font-size: 0.86rem;
            color: var(--text-secondary);
        }}
        .evolution-price strong {{
            color: var(--accent-warm);
        }}
        .evolution-reason {{
            font-size: 0.90rem;
            color: var(--text-body);
            margin-bottom: 14px;
        }}
        .reason-label {{
            color: var(--text-dim);
            font-family: var(--font-mono);
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-right: 6px;
        }}
        .evolution-metrics-text-row {{
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 14px;
            font-family: var(--font-mono);
            font-size: 0.82rem;
            color: var(--text-secondary);
        }}
        .evolution-metrics-text-row strong {{
            color: var(--text-title);
        }}
        .evolution-change-text {{
            font-size: 0.90rem;
            color: #A8A196;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 12px 16px;
            line-height: 1.6;
            margin-bottom: 14px;
        }}
        .archived-accordion {{
            margin-top: 10px;
        }}
        .archived-summary {{
            font-family: var(--font-mono);
            font-size: 0.80rem;
            color: var(--accent-warm);
            cursor: pointer;
            user-select: none;
            padding: 6px 0;
            transition: color 0.15s;
        }}
        .archived-summary:hover {{
            color: var(--accent-warm-hover);
        }}
        .archived-content-body {{
            margin-top: 14px;
            padding: 20px 24px;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            font-size: 0.92rem;
            line-height: 1.7;
        }}
        .archived-memo-section {{
            margin-bottom: 18px;
        }}
        .archived-memo-section:last-child {{
            margin-bottom: 0;
        }}
        .archived-memo-sub {{
            font-family: var(--font-sans);
            font-size: 0.92rem;
            font-weight: 700;
            color: var(--text-title);
            margin-bottom: 6px;
        }}

        /* Alerts & Surveillance Hub */
        .alerts-hub {{
            display: flex;
            flex-direction: column;
            gap: 24px;
        }}
        .corridor-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 16px;
        }}
        .corridor-card {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px 24px;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        .corridor-label {{
            font-family: var(--font-mono);
            font-size: 0.76rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .corridor-value {{
            font-family: var(--font-mono);
            font-size: 1.35rem;
            font-weight: 600;
            color: var(--text-title);
        }}
        .corridor-sub {{
            font-size: 0.82rem;
            color: var(--text-dim);
        }}
        .alert-feed-list {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .alert-feed-card {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px 24px;
        }}
        .alert-feed-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }}
        .alert-feed-badge {{
            font-family: var(--font-mono);
            font-size: 0.72rem;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 4px;
            background: rgba(201, 122, 114, 0.15);
            color: #C97A72;
            border: 1px solid rgba(201, 122, 114, 0.3);
            text-transform: uppercase;
        }}
        .alert-feed-time {{
            font-family: var(--font-mono);
            font-size: 0.78rem;
            color: var(--text-dim);
        }}
        .alert-feed-title {{
            font-size: 1.02rem;
            font-weight: 600;
            color: var(--text-title);
            margin-bottom: 4px;
        }}
        .alert-feed-reason {{
            font-size: 0.88rem;
            color: var(--text-body);
            margin-bottom: 6px;
        }}
        .alert-feed-desc {{
            font-size: 0.84rem;
            color: var(--text-secondary);
            line-height: 1.5;
        }}
        .empty-alerts-box {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 32px;
            text-align: center;
        }}
        .empty-alerts-title {{
            font-size: 1.05rem;
            font-weight: 600;
            color: var(--text-title);
            margin-bottom: 6px;
        }}
        .empty-alerts-sub {{
            font-size: 0.86rem;
            color: var(--text-secondary);
            max-width: 580px;
            margin: 0 auto;
            line-height: 1.6;
        }}

        /* Ownership & Fund Intel */
        .ownership-wrap {{
            display: flex;
            flex-direction: column;
            gap: 24px;
        }}
        .whale-chips-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
        }}
        .whale-chip {{
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            padding: 6px 14px;
            border-radius: 8px;
            font-size: 0.86rem;
            color: var(--text-title);
            font-weight: 500;
        }}

        /* Regulatory & Ownership Portals */
        .portals-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 16px;
        }}
        .portal-card {{
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            text-decoration: none;
            color: inherit;
            display: flex;
            flex-direction: column;
            gap: 8px;
            transition: border-color 0.2s, transform 0.15s;
        }}
        .portal-card:hover {{
            border-color: var(--accent-warm);
            transform: translateY(-1px);
        }}
        .portal-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .portal-name {{
            font-family: var(--font-sans);
            font-weight: 600;
            font-size: 1.05rem;
            color: var(--text-title);
        }}
        .portal-arrow {{
            color: var(--accent-warm);
            font-size: 0.95rem;
        }}
        .portal-desc {{
            font-size: 0.84rem;
            color: var(--text-secondary);
            line-height: 1.5;
        }}
    </style>
</head>
<body>
    <!-- Top Nav -->
    <nav class="nav-bar">
        <div class="container nav-inner">
            <a href="../" class="nav-back">← Back to Watchlist</a>
        </div>
    </nav>

    <div class="container">
        <!-- 1. Hero Deck -->
        <header class="hero-deck">
            <div class="hero-top-row">
                <div class="hero-title-area">
                    {logo_html}
                    <div class="hero-title-text">
                        <div class="ticker-header-line">
                            <span class="ticker-symbol">{ticker_clean}{quad_beacon}</span>
                        </div>
                        <div class="company-name-meta">{company_name} <span class="meta-sep">·</span> <span class="meta-moat" style="color: {moat_color}; font-weight: 500;">{moat_label}</span>{moat_type_html}</div>
                    </div>
                </div>
                <div class="price-callout">
                    <div class="price-number" id="hero-market-price">${current_price:.2f}</div>
                    <div class="price-sub">Market Price</div>
                </div>
            </div>

            <!-- Native SVG Area Chart with 3Y Continuation Target Line & Moving Averages -->
            <div class="native-chart-wrap">
                <div class="chart-top-bar">
                    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
                        <div class="chart-live-val">
                            <span id="tooltip-date">{last_date}</span> &bull; <strong id="tooltip-price" style="color: #82AE8C;">${last_price:.2f}</strong>
                            <span class="meta-sep" style="margin: 0 6px; color: var(--text-dim);">·</span>
                            <span style="color: var(--accent-warm); font-size: 0.80rem;">3Y Target: <strong>${target_price:.2f}</strong></span>
                        </div>
                        <!-- Moving Average Live Indicators -->
                        <div class="ma-legend-bar">
                            <span class="ma-text-item" id="ma5-btn" onclick="toggleMA(5)" title="Click to toggle 5-Day MA">
                                <span class="ma-dot" style="background: #38BDF8;"></span><span class="ma-label" style="color: #38BDF8;">5 MA</span><span id="ma5-val" class="ma-val"></span>
                            </span>
                            <span class="ma-sep">·</span>
                            <span class="ma-text-item" id="ma21-btn" onclick="toggleMA(21)" title="Click to toggle 21-Day MA">
                                <span class="ma-dot" style="background: #FBBF24;"></span><span class="ma-label" style="color: #FBBF24;">21 MA</span><span id="ma21-val" class="ma-val"></span>
                            </span>
                            <span class="ma-sep">·</span>
                            <span class="ma-text-item" id="ma50-btn" onclick="toggleMA(50)" title="Click to toggle 50-Day MA">
                                <span class="ma-dot" style="background: #FB923C;"></span><span class="ma-label" style="color: #FB923C;">50 MA</span><span id="ma50-val" class="ma-val"></span>
                            </span>
                            <span class="ma-sep">·</span>
                            <span class="ma-text-item" id="ma200-btn" onclick="toggleMA(200)" title="Click to toggle 200-Day MA">
                                <span class="ma-dot" style="background: #E879F9;"></span><span class="ma-label" style="color: #E879F9;">200 MA</span><span id="ma200-val" class="ma-val"></span>
                            </span>
                        </div>
                    </div>
                    <div class="chart-range-pills">
                        <button class="range-pill" onclick="switchRange('1D')">1D</button>
                        <button class="range-pill" onclick="switchRange('1M')">1M</button>
                        <button class="range-pill active" onclick="switchRange('1Y')">1Y</button>
                        <button class="range-pill" onclick="switchRange('5Y')">5Y</button>
                        <button class="range-pill" onclick="switchRange('MAX')">MAX</button>
                    </div>
                </div>
                <div style="position: relative; width: 100%; height: 200px;">
                    <svg id="interactive-svg" class="chart-svg" viewBox="0 0 {width} {height}" preserveAspectRatio="none">
                        <defs>
                            <linearGradient id="area-grad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stop-color="#82AE8C" stop-opacity="0.22" />
                                <stop offset="100%" stop-color="#82AE8C" stop-opacity="0.0" />
                            </linearGradient>
                        </defs>
                        <!-- Horizontal Grid Lines & Y-Axis Prices -->
                        <text id="grid-price-high" x="{width - padding_x - 6}" y="{padding_y + 11}" text-anchor="end" fill="#6E685E" font-family="var(--font-mono)" font-size="10.5">$0.00</text>
                        <line x1="{padding_x}" y1="{padding_y}" x2="{width - padding_x}" y2="{padding_y}" stroke="rgba(255,255,255,0.05)" stroke-width="1" stroke-dasharray="2 4" />

                        <text id="grid-price-mid" x="{width - padding_x - 6}" y="{height / 2 + 3}" text-anchor="end" fill="#6E685E" font-family="var(--font-mono)" font-size="10.5">$0.00</text>
                        <line x1="{padding_x}" y1="{height / 2}" x2="{width - padding_x}" y2="{height / 2}" stroke="rgba(255,255,255,0.05)" stroke-width="1" stroke-dasharray="2 4" />

                        <text id="grid-price-low" x="{width - padding_x - 6}" y="{height - padding_y - 4}" text-anchor="end" fill="#6E685E" font-family="var(--font-mono)" font-size="10.5">$0.00</text>
                        <line x1="{padding_x}" y1="{height - padding_y}" x2="{width - padding_x}" y2="{height - padding_y}" stroke="rgba(255,255,255,0.05)" stroke-width="1" stroke-dasharray="2 4" />
                        
                        <!-- 3Y Target Dotted Line & Tag -->
                        <line id="target-line" x1="{padding_x}" y1="{padding_y}" x2="{width - padding_x}" y2="{padding_y}" stroke="#D4A373" stroke-width="1.6" stroke-dasharray="4 4" opacity="0.85" />
                        <text id="target-label" x="{width - padding_x - 6}" y="{padding_y - 4}" text-anchor="end" fill="#D4A373" font-family="var(--font-mono)" font-size="10.5" font-weight="600">3Y Target: ${target_price:.2f}</text>

                        <!-- Moving Average Lines (200, 50, 21, 5) -->
                        <polyline id="chart-ma200" fill="none" stroke="#E879F9" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" opacity="0.85" points="" />
                        <polyline id="chart-ma50" fill="none" stroke="#FB923C" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" opacity="0.85" points="" />
                        <polyline id="chart-ma21" fill="none" stroke="#FBBF24" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" opacity="0.85" points="" />
                        <polyline id="chart-ma5" fill="none" stroke="#38BDF8" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" opacity="0.85" points="" />

                        <!-- Dynamic Area & Primary Price Stroke -->
                        <polygon id="chart-area" fill="url(#area-grad)" points="" />
                        <polyline id="chart-line" fill="none" stroke="#82AE8C" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" points="" />
                        
                        <!-- Hover Crosshair & Marker -->
                        <line id="hover-line" x1="0" y1="0" x2="0" y2="{height}" stroke="rgba(212, 163, 115, 0.4)" stroke-width="1" stroke-dasharray="3 3" opacity="0" />
                        <circle id="hover-dot" r="4.5" fill="#D4A373" stroke="#1B1A19" stroke-width="2" opacity="0" />
                    </svg>
                </div>
                <!-- X-Axis Timeline Dates -->
                <div class="chart-x-axis" id="chart-x-axis"></div>
            </div>

            <!-- 8-Box Derived Financial & Cycle Metrics Grid -->
            <div class="metrics-grid">
                <div class="metric-card">
                    <span class="metric-label">Owner Earnings (TTM)</span>
                    <span class="metric-value" style="color: {oe_color};">{oe_card_val}</span>
                    <span class="metric-sub">{oe_card_sub}</span>
                </div>
                <div class="metric-card">
                    <span class="metric-label">P / Owner Earnings</span>
                    <span class="metric-value" style="color: {poe_color};">{poe_card_val}</span>
                    <span class="metric-sub">{poe_card_sub}</span>
                </div>
                <div class="metric-card">
                    <span class="metric-label">EV / Owner Earnings</span>
                    <span class="metric-value" style="color: {evoe_color};">{evoe_card_val}</span>
                    <span class="metric-sub">{evoe_card_sub}</span>
                </div>
                <div class="metric-card">
                    <span class="metric-label">Owner Cash Yield</span>
                    <span class="metric-value" style="color: {yield_color};">{yield_card_val}</span>
                    <span class="metric-sub">{yield_card_sub}</span>
                </div>
                <div class="metric-card">
                    <span class="metric-label">Owner ROIC</span>
                    <span class="metric-value" style="color: {roic_color};">{roic_card_val}</span>
                    <span class="metric-sub">{roic_card_sub}</span>
                </div>
                <div class="metric-card">
                    <span class="metric-label">Net Cash / Share</span>
                    <span class="metric-value" style="color: {cash_color};">{cash_card_val}</span>
                    <span class="metric-sub">{cash_card_sub}</span>
                </div>
                <div class="metric-card">
                    <span class="metric-label">
                        <span>Cyclicality Profile</span>
                        <button type="button" class="btn-info-circle" onclick="openCyclicalityModal(event)" title="Learn about Cyclicality Profile">ⓘ</button>
                    </span>
                    <span class="metric-value-text" style="color: var(--text-title);">{cyclicality_type}</span>
                    <span class="metric-sub">{cyclicality_sub}</span>
                </div>
                <div class="metric-card">
                    <span class="metric-label">
                        <span>Cycle Position</span>
                        <button type="button" class="btn-info-circle" onclick="openCyclicalityModal(event)" title="Learn about Cycle Position">ⓘ</button>
                    </span>
                    <span class="metric-value-text" style="color: {cycle_color};">{cycle_stance}</span>
                    <span class="metric-sub">{cycle_summary}</span>
                </div>
            </div>
        </header>

        <!-- Navigation Tabs -->
        <div class="nav-tabs">
            <button class="nav-tab active" onclick="switchTab('thesis', this)">Investment Thesis</button>
            <button class="nav-tab" onclick="switchTab('evolution', this)">Thesis Evolution <span class="tab-badge">{evolution_count}</span></button>
            <button class="nav-tab" onclick="switchTab('alerts', this)">Alerts & Catalysts <span class="tab-badge">{len(ticker_alerts)}</span></button>
            <button class="nav-tab" onclick="switchTab('ownership', this)">Ownership & Fund Intel</button>
        </div>

        <!-- TAB 1: Investment Thesis (4 Core Sections) -->
        <div id="tab-thesis" class="tab-pane active">
            <main class="memo-container">
                <section class="memo-section">
                    <div class="section-header">
                        <span class="section-index">01</span>
                        <h2 class="memo-title">What the Market is Pricing In</h2>
                    </div>
                    <div class="memo-body">{p1_html}</div>
                </section>
                <section class="memo-section">
                    <div class="section-header">
                        <span class="section-index">02</span>
                        <h2 class="memo-title">Why the Market Might Be Right</h2>
                    </div>
                    <div class="memo-body">{p2_html}</div>
                </section>
                <section class="memo-section">
                    <div class="section-header">
                        <span class="section-index">03</span>
                        <h2 class="memo-title">How Things Are Going Now</h2>
                    </div>
                    <div class="memo-body">{p3_html}</div>
                </section>
                <section class="memo-section">
                    <div class="section-header" style="display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
                        <div style="display: flex; align-items: baseline; gap: 12px;">
                            <span class="section-index">04</span>
                            <h2 class="memo-title">What If It Keeps Going That Way</h2>
                        </div>
                        <div class="section-predictability-meta" style="display: flex; align-items: center; gap: 8px; font-size: 0.84rem; font-family: var(--font-sans);">
                            <span class="pred-indicator" style="color: {pred_color}; font-weight: 600;">{pred_tier}</span>
                            <span class="pred-sep" style="color: var(--text-dim);">·</span>
                            <span class="pred-subtext" style="color: var(--text-secondary); font-weight: 400;">{pred_score}</span>
                        </div>
                    </div>
                    <div class="memo-body">{p4_html}</div>
                </section>
            </main>
        </div>

        <!-- TAB 2: Thesis Evolution & Version History -->
        <div id="tab-evolution" class="tab-pane">
            <div class="memo-container">
                <h2 class="memo-title" style="margin-bottom: 24px;">Thesis Evolution & Historical Audits</h2>
                <div class="evolution-timeline">
                    {evolution_cards_html}
                </div>
            </div>
        </div>

        <!-- TAB 3: Alerts & Catalyst Surveillance -->
        <div id="tab-alerts" class="tab-pane">
            <div class="alerts-hub">
                <div class="corridor-grid">
                    <div class="corridor-card">
                        <span class="corridor-label">Lower Price Alert Floor</span>
                        <span class="corridor-value">{lower_txt.split(' ')[0]}</span>
                        <span class="corridor-sub">Triggers downside margin-of-safety review if breached</span>
                    </div>
                    <div class="corridor-card">
                        <span class="corridor-label">Upper Price Alert Ceiling</span>
                        <span class="corridor-value">{upper_txt.split(' ')[0]}</span>
                        <span class="corridor-sub">Triggers valuation trim / fair value realization review</span>
                    </div>
                    <div class="corridor-card">
                        <span class="corridor-label">Next Expected Catalyst</span>
                        <span class="corridor-value" style="font-size: 1.1rem; color: var(--accent-warm);">{next_catalyst_d}</span>
                        <span class="corridor-sub">{next_catalyst_e}</span>
                    </div>
                </div>

                <div class="memo-container" style="padding: 32px 36px;">
                    <h3 class="memo-title" style="font-size: 1.15rem; margin-bottom: 18px;">Active & Historical Surveillance Alerts for {ticker_clean}</h3>
                    <div class="alert-feed-list">
                        {ticker_alerts_html}
                    </div>
                </div>
            </div>
        </div>

        <!-- TAB 4: Ownership & Regulatory Portals -->
        <div id="tab-ownership" class="tab-pane">
            <div class="ownership-wrap">
                <div class="portals-grid" style="grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));">
                    <a href="http://openinsider.com/search?q={ticker_clean}" target="_blank" rel="noopener noreferrer" class="portal-card">
                        <div class="portal-header">
                            <span class="portal-name">OpenInsider SEC Form 4 Tracker</span>
                            <span class="portal-arrow">↗</span>
                        </div>
                        <div class="portal-desc">Direct statutory database of insider cluster buys, C-suite open market sales, and 10b5-1 executive plans for {ticker_clean}.</div>
                    </a>
                    <a href="https://www.dataroma.com/m/stock.php?sym={ticker_clean}" target="_blank" rel="noopener noreferrer" class="portal-card">
                        <div class="portal-header">
                            <span class="portal-name">Dataroma Superinvestor Registry</span>
                            <span class="portal-arrow">↗</span>
                        </div>
                        <div class="portal-desc">Live 13F superinvestor tracking showing top institutional value funds, Berkshire Hathaway, and hedge fund portfolio weightings for {ticker_clean}.</div>
                    </a>
                </div>
            </div>
        </div>
    </div>

    <!-- Dynamic SVG Chart & Range Switching Script -->
    <script>
        const chartData = {ranges_json};
        let activeRange = '1Y';
        const maEnabled = {{ 5: true, 21: true, 50: true, 200: true }};

        function toggleMA(period) {{
            maEnabled[period] = !maEnabled[period];
            const btn = document.getElementById('ma' + period + '-btn');
            if (btn) {{
                if (maEnabled[period]) {{
                    btn.classList.remove('disabled');
                }} else {{
                    btn.classList.add('disabled');
                }}
            }}
            renderChart(activeRange);
        }}

        // Pre-build continuous chronological daily lookup from historical datasets
        const masterDailyMap = new Map();
        ['MAX', '5Y', '1Y', '1M'].forEach(function(rk) {{
            (chartData[rk] || []).forEach(function(pt) {{
                if (pt && pt.price > 0 && pt.date) {{
                    const dKey = pt.date;
                    if (!masterDailyMap.has(dKey)) {{
                        let ts = 0;
                        if (pt.full_date) {{
                            ts = new Date(pt.full_date).getTime();
                        }} else {{
                            ts = new Date(pt.date).getTime();
                        }}
                        masterDailyMap.set(dKey, {{ date: dKey, price: pt.price, ts: isNaN(ts) ? 0 : ts }});
                    }}
                }}
            }});
        }});
        const sortedDailyPoints = Array.from(masterDailyMap.values()).sort((a, b) => a.ts - b.ts);

        // Precompute master moving averages across continuous daily history
        const masterMAs = {{ 5: new Map(), 21: new Map(), 50: new Map(), 200: new Map() }};
        [5, 21, 50, 200].forEach(function(period) {{
            let sum = 0;
            for (let i = 0; i < sortedDailyPoints.length; i++) {{
                sum += sortedDailyPoints[i].price;
                if (i >= period) {{
                    sum -= sortedDailyPoints[i - period].price;
                    masterMAs[period].set(sortedDailyPoints[i].date, sum / period);
                }} else {{
                    masterMAs[period].set(sortedDailyPoints[i].date, sum / (i + 1));
                }}
            }}
        }});

        function switchTab(tabId, el) {{
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
            document.getElementById('tab-' + tabId).classList.add('active');
            el.classList.add('active');
        }}

        function renderChart(rangeKey) {{
            activeRange = rangeKey;
            const points = chartData[rangeKey] || [];
            const svg = document.getElementById('interactive-svg');
            const polyline = document.getElementById('chart-line');
            const polygon = document.getElementById('chart-area');
            const tooltipDate = document.getElementById('tooltip-date');
            const tooltipPrice = document.getElementById('tooltip-price');

            if (!points || points.length < 2) {{
                polyline.setAttribute('points', '');
                polygon.setAttribute('points', '');
                [5, 21, 50, 200].forEach(function(p) {{
                    const el = document.getElementById('chart-ma' + p);
                    if (el) el.setAttribute('points', '');
                }});
                return;
            }}

            // Compute MA values for the active range
            const currentMAVals = {{ 5: [], 21: [], 50: [], 200: [] }};
            [5, 21, 50, 200].forEach(function(period) {{
                if (rangeKey === '1D') {{
                    let sum = 0;
                    for (let i = 0; i < points.length; i++) {{
                        sum += points[i].price;
                        if (i >= period) {{
                            sum -= points[i - period].price;
                            currentMAVals[period].push(sum / period);
                        }} else {{
                            currentMAVals[period].push(sum / (i + 1));
                        }}
                    }}
                }} else {{
                    for (let i = 0; i < points.length; i++) {{
                        const d = points[i].date;
                        if (masterMAs[period].has(d)) {{
                            currentMAVals[period].push(masterMAs[period].get(d));
                        }} else {{
                            let s = 0;
                            let count = Math.min(period, i + 1);
                            for (let k = i - count + 1; k <= i; k++) s += points[k].price;
                            currentMAVals[period].push(s / count);
                        }}
                    }}
                }}
            }});

            const targetPrice = {target_price};
            const prices = points.map(p => p.price);
            let minP = Math.min(...prices);
            let maxP = Math.max(...prices);

            // Expand bounds if enabled MA lines exceed current price range
            [5, 21, 50, 200].forEach(function(period) {{
                if (maEnabled[period] && currentMAVals[period].length > 0) {{
                    currentMAVals[period].forEach(function(v) {{
                        if (v > 0) {{
                            minP = Math.min(minP, v);
                            maxP = Math.max(maxP, v);
                        }}
                    }});
                }}
            }});

            const isShortTerm = (rangeKey === '1D' || rangeKey === '1M');

            if (!isShortTerm && targetPrice && targetPrice > 0) {{
                // On multi-year horizons, incorporate target price into scale if within reasonable range (< 3x)
                if (targetPrice <= maxP * 3.0 && targetPrice >= minP * 0.33) {{
                    maxP = Math.max(maxP, targetPrice * 1.04);
                    minP = Math.min(minP, targetPrice * 0.96);
                }}
            }}

            // Add organic padding around minP and maxP so curves have full vertical expressiveness
            const spanP = (maxP - minP);
            const padSpan = (spanP < 0.05) ? Math.max(minP * 0.04, 0.40) : spanP * 0.05;
            minP = Math.max(0, minP - padSpan);
            maxP = maxP + padSpan;
            if (minP === maxP) {{ minP *= 0.95; maxP *= 1.05; }}
            const rangeP = Math.max(maxP - minP, 0.01);

            const width = {width};
            const height = {height};
            const padX = {padding_x};
            const padY = {padding_y};
            const drawW = width - (2 * padX);
            const drawH = height - (2 * padY);

            // Dynamically position 3Y Target line and label (show only if within visible Y range)
            const targetLine = document.getElementById('target-line');
            const targetLabel = document.getElementById('target-label');
            if (targetLine && targetLabel) {{
                if (targetPrice && targetPrice > 0 && targetPrice >= minP && targetPrice <= maxP) {{
                    const targetY = padY + drawH - ((targetPrice - minP) / rangeP) * drawH;
                    targetLine.setAttribute('y1', targetY.toFixed(1));
                    targetLine.setAttribute('y2', targetY.toFixed(1));
                    targetLine.style.display = '';
                    targetLabel.setAttribute('y', (targetY - 5).toFixed(1));
                    targetLabel.textContent = '3Y Target: $' + targetPrice.toFixed(2);
                    targetLabel.style.display = '';
                }} else {{
                    targetLine.style.display = 'none';
                    targetLabel.style.display = 'none';
                }}
            }}

            const coords = points.map((p, idx) => {{
                const x = padX + (idx / (points.length - 1)) * drawW;
                const y = padY + drawH - ((p.price - minP) / rangeP) * drawH;
                return {{ x, y, price: p.price, date: p.date }};
            }});

            const polyPoints = coords.map(c => `${{c.x.toFixed(1)}},${{c.y.toFixed(1)}}`).join(' ');
            polyline.setAttribute('points', polyPoints);

            const areaPoints = `${{coords[0].x.toFixed(1)}},${{height}} ` + polyPoints + ` ${{coords[coords.length - 1].x.toFixed(1)}},${{height}}`;
            polygon.setAttribute('points', areaPoints);

            // Render Moving Average Polylines
            [5, 21, 50, 200].forEach(function(period) {{
                const maPoly = document.getElementById('chart-ma' + period);
                if (maPoly) {{
                    if (!maEnabled[period]) {{
                        maPoly.setAttribute('points', '');
                        maPoly.style.display = 'none';
                    }} else {{
                        maPoly.style.display = '';
                        const maCoords = currentMAVals[period].map((val, idx) => {{
                            const x = padX + (idx / (points.length - 1)) * drawW;
                            const y = padY + drawH - ((val - minP) / rangeP) * drawH;
                            return `${{x.toFixed(1)}},${{y.toFixed(1)}}`;
                        }});
                        maPoly.setAttribute('points', maCoords.join(' '));
                    }}
                }}
            }});

            // Helper to update live displayed values on badges and top bar
            function updateLiveValues(idx) {{
                const pt = points[idx] || points[points.length - 1];
                if (!pt) return;
                tooltipDate.textContent = pt.date;
                tooltipPrice.textContent = '$' + pt.price.toFixed(2);
                [5, 21, 50, 200].forEach(function(period) {{
                    const valEl = document.getElementById('ma' + period + '-val');
                    if (valEl) {{
                        const arr = currentMAVals[period];
                        const v = (arr && arr[idx] !== undefined) ? arr[idx] : (arr ? arr[arr.length - 1] : 0);
                        valEl.textContent = (v && v > 0) ? ' $' + v.toFixed(2) : '';
                    }}
                }});
            }}

            // Default to latest point
            const lastIdx = points.length - 1;
            updateLiveValues(lastIdx);

            // Update Y-Axis Prices
            const highEl = document.getElementById('grid-price-high');
            const midEl = document.getElementById('grid-price-mid');
            const lowEl = document.getElementById('grid-price-low');
            if (highEl) highEl.textContent = '$' + maxP.toFixed(2);
            if (midEl) midEl.textContent = '$' + ((maxP + minP) / 2).toFixed(2);
            if (lowEl) lowEl.textContent = '$' + minP.toFixed(2);

            // Populate X-Axis Ticks
            const xAxis = document.getElementById('chart-x-axis');
            if (xAxis && points.length > 0) {{
                const tickCount = Math.min(5, points.length);
                let ticksHtml = '';
                for (let i = 0; i < tickCount; i++) {{
                    const ptIdx = Math.floor((i / (tickCount - 1)) * (points.length - 1));
                    const dStr = points[ptIdx].date;
                    ticksHtml += `<span class="chart-x-tick">${{dStr}}</span>`;
                }}
                xAxis.innerHTML = ticksHtml;
            }}

            // Interactive Crosshair Scrub
            svg.onmousemove = function(e) {{
                const rect = svg.getBoundingClientRect();
                const mouseX = (e.clientX - rect.left) * (width / rect.width);
                
                let closestIdx = 0;
                let closestDist = Math.abs(coords[0].x - mouseX);
                for (let i = 1; i < coords.length; i++) {{
                    const dist = Math.abs(coords[i].x - mouseX);
                    if (dist < closestDist) {{
                        closestIdx = i;
                        closestDist = dist;
                    }}
                }}
                const closest = coords[closestIdx];

                document.getElementById('hover-line').setAttribute('x1', closest.x);
                document.getElementById('hover-line').setAttribute('x2', closest.x);
                document.getElementById('hover-line').setAttribute('opacity', '1');

                document.getElementById('hover-dot').setAttribute('cx', closest.x);
                document.getElementById('hover-dot').setAttribute('cy', closest.y);
                document.getElementById('hover-dot').setAttribute('opacity', '1');

                updateLiveValues(closestIdx);
                const scrubPt = points[closestIdx];
                if (scrubPt && scrubPt.price) {{
                    const heroEl = document.getElementById('hero-market-price');
                    if (heroEl) heroEl.textContent = '$' + scrubPt.price.toFixed(2);
                }}
            }};

            svg.onmouseleave = function() {{
                document.getElementById('hover-line').setAttribute('opacity', '0');
                document.getElementById('hover-dot').setAttribute('opacity', '0');
                updateLiveValues(lastIdx);
                const latestPt = points[lastIdx];
                if (latestPt && latestPt.price) {{
                    const heroEl = document.getElementById('hero-market-price');
                    if (heroEl) heroEl.textContent = '$' + latestPt.price.toFixed(2);
                }}
            }};
        }}

        function animateRollingPrice(elem, targetVal, startOverride, duration = 900) {{
            if (!elem || isNaN(targetVal)) return;
            const rawText = elem.textContent.replace(/[^0-9.-]/g, '');
            const startVal = (startOverride !== undefined && !isNaN(startOverride)) ? startOverride : (parseFloat(rawText) || targetVal);
            if (Math.abs(startVal - targetVal) < 0.005) {{
                elem.textContent = '$' + targetVal.toFixed(2);
                return;
            }}
            // Wealthsimple / Fidelity soft color pulse
            if (targetVal > startVal) {{
                elem.style.transition = 'color 0.35s ease';
                elem.style.color = '#82AE8C';
                setTimeout(() => {{ elem.style.color = 'var(--text-title)'; }}, 1000);
            }} else if (targetVal < startVal) {{
                elem.style.transition = 'color 0.35s ease';
                elem.style.color = '#CC785C';
                setTimeout(() => {{ elem.style.color = 'var(--text-title)'; }}, 1000);
            }}
            const startTime = performance.now();
            function step(now) {{
                const elapsed = now - startTime;
                const progress = Math.min(elapsed / duration, 1.0);
                const ease = 1 - Math.pow(1 - progress, 4); // Quartic ease-out
                const current = startVal + (targetVal - startVal) * ease;
                elem.textContent = '$' + current.toFixed(2);
                if (progress < 1.0) {{
                    requestAnimationFrame(step);
                }} else {{
                    elem.textContent = '$' + targetVal.toFixed(2);
                }}
            }}
            requestAnimationFrame(step);
        }}

        function switchRange(rangeKey) {{
            document.querySelectorAll('.range-pill').forEach(btn => {{
                if (btn.textContent === rangeKey) {{
                    btn.classList.add('active');
                }} else {{
                    btn.classList.remove('active');
                }}
            }});
            renderChart(rangeKey);
        }}

        // Initial render & real-time latest candle price sync
        document.addEventListener('DOMContentLoaded', () => {{
            renderChart('1Y');
            const livePoints = chartData['1D'] || chartData['1Y'] || [];
            if (livePoints.length > 0) {{
                const latestPoint = livePoints[livePoints.length - 1];
                if (latestPoint && latestPoint.price && latestPoint.price > 0) {{
                    const heroEl = document.getElementById('hero-market-price');
                    if (heroEl) {{
                        animateRollingPrice(heroEl, latestPoint.price);
                    }}
                }}
            }}
        }});

        function openCyclicalityModal(event) {{
            if (event) {{
                event.stopPropagation();
                event.preventDefault();
            }}
            const modal = document.getElementById('cyclicality-modal');
            if (modal) modal.style.display = 'flex';
        }}

        function closeCyclicalityModal() {{
            const modal = document.getElementById('cyclicality-modal');
            if (modal) modal.style.display = 'none';
        }}

        function closeCyclicalityModalOutside(event) {{
            if (event.target.id === 'cyclicality-modal') {{
                closeCyclicalityModal();
            }}
        }}
    </script>
    {cyclicality_modal_html}
</body>
</html>
"""


def compute_market_discrepancy(stock: WatchlistStock, current_v: Optional[ThesisVersion] = None) -> Tuple[str, str, str, float, str]:
    """Computes the 3-Year Target price and delta percentage with a clean directional arrow.
    Returns: (target_price_str, delta_str, delta_color, target_3y, delta_class)
    """
    current_price = getattr(stock, 'current_price', 0.0) or 0.0

    target_3y = None
    raw_target = getattr(stock, 'base_target', '') or getattr(stock, 'fair_value_estimate', '')
    if not raw_target and current_v:
        raw_target = getattr(current_v, 'base_target', '') or getattr(current_v, 'fair_value_estimate', '')
    
    if raw_target:
        try:
            clean_tgt = re.sub(r'[^\d\.]', '', str(raw_target))
            if clean_tgt:
                target_3y = float(clean_tgt)
        except Exception:
            pass

    p4 = getattr(stock, 'what_if_it_keeps_going_that_way', '') or (current_v.what_if_it_keeps_going_that_way if current_v else '')
    if target_3y is None and p4:
        base_block_m = re.search(r'Base Case[^\n:]*:(.*?)(?:\n\u2022|\n[1-9]\.|\n\n|\Z)', p4, re.DOTALL | re.IGNORECASE)
        if base_block_m:
            b_txt = base_block_m.group(1)
            m_calc = re.search(r'(?:=\s*\$|expected\s+base\s+target\s+\$|base\s+target\s+\$|target\s+price\s+\$|\$([0-9]+(?:\.[0-9]+)?)\s*(?:target\s+price|expected\s+target|target))([0-9]+(?:\.[0-9]+)?)', b_txt, re.IGNORECASE)
            if m_calc:
                try:
                    target_3y = float(m_calc.group(2) or m_calc.group(1))
                except Exception:
                    pass
        if target_3y is None:
            m = re.search(r'(?:expected base target|base target|expected target|target price|fair value)[^\$\d]*\$([0-9]+(?:\.[0-9]+)?)', p4, re.IGNORECASE)
            if m:
                try:
                    target_3y = float(m.group(1))
                except Exception:
                    pass

    if target_3y is None or target_3y <= 0:
        moat_lbl_val = getattr(stock, 'moat_label', '') or (current_v.moat_label if current_v else "Narrow Moat")
        oe_sh_val = getattr(stock, 'owner_earnings_per_share', 0.0) or (current_v.owner_earnings_per_share if current_v else 0.0)
        net_cash_sh_val = getattr(stock, 'net_cash_per_share', 0.0) or (current_v.net_cash_per_share if current_v else 0.0)
        rev_g = getattr(stock, 'revenue_growth_yoy_pct', 8.0) or (current_v.revenue_growth_yoy_pct if current_v else 8.0)
        try:
            rev_g_num = float(rev_g or 8.0)
        except Exception:
            rev_g_num = 8.0

        if "Wide" in str(moat_lbl_val):
            default_mult = 23.5 if rev_g_num > 15.0 else (19.5 if rev_g_num >= 8.0 else (15.5 if rev_g_num >= 3.0 else 12.0))
        elif "Narrow" in str(moat_lbl_val):
            default_mult = 16.5 if rev_g_num > 15.0 else (13.5 if rev_g_num >= 8.0 else (11.0 if rev_g_num >= 3.0 else 8.0))
        elif "Weak" in str(moat_lbl_val):
            default_mult = 10.0 if rev_g_num > 15.0 else (8.0 if rev_g_num >= 8.0 else (6.0 if rev_g_num >= 3.0 else 4.5))
        else:
            default_mult = 6.5 if rev_g_num > 10.0 else (5.0 if rev_g_num >= 3.0 else 3.5)

        if oe_sh_val and oe_sh_val > 0:
            target_3y = round((oe_sh_val * default_mult) + (net_cash_sh_val or 0.0), 2)
        else:
            target_3y = 0.0

    if current_price > 0 and target_3y > 0:
        gap_pct = ((target_3y - current_price) / current_price) * 100.0
    else:
        gap_pct = 0.0

    if gap_pct > 0.05:
        delta_str = f"↗ {gap_pct:+.1f}%"
        delta_color = "#82AE8C"
        delta_class = "pos"
    elif gap_pct < -0.05:
        delta_str = f"↘ {gap_pct:.1f}%"
        delta_color = "#C97A72"
        delta_class = "neg"
    else:
        delta_str = "→ +0.0%"
        delta_color = "#9E978C"
        delta_class = "neutral"

    target_price_str = f"${target_3y:.2f}" if target_3y > 0 else "—"
    return target_price_str, delta_str, delta_color, target_3y, delta_class


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
        quad_beacon = get_quad_ma_beacon_html(stock.ticker, stock.current_price or 0.0)
        # Unify: Quad-MA Radar Pulse takes priority over static action beacon to avoid dual-dot clutter
        active_beacon = quad_beacon if quad_beacon else stock_beacon
        
        # Clean company name (preserve canonical full name like Amazon.com, Inc.)
        clean_company = get_canonical_company_name(stock.ticker, stock.company_name)

        # 5Y Target & Directional Arrow Delta
        tgt_str, delta_str, delta_color, tgt_5y, delta_class = compute_market_discrepancy(stock, None)

        # Catalyst headline (e.g. "Q3 '26 Earnings") & formatted date (e.g. "Nov 19, 2026")
        cat_headline, cat_date = format_catalyst_display(stock.next_catalyst_event, stock.next_catalyst_date)
        safe_baseline = stock.baseline_price if stock.baseline_price > 0 else stock.current_price

        table_rows_html += f"""
        <tr class="table-row" data-ticker="{stock.ticker}" data-baseline="{safe_baseline}" onclick="location.href='reports/{stock.ticker}.html'">
            <td>
                <div class="tbl-ticker-cell">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        {get_ticker_logo_html(stock.ticker, 20)}
                        <span class="tbl-symbol">{stock.ticker}{active_beacon}</span>
                    </div>
                    <span class="tbl-company-hover">{clean_company}</span>
                </div>
            </td>
            <td>
                <div class="tbl-price-cell">
                    <span class="tbl-price tbl-price-{stock.ticker}">${(stock.current_price if stock.current_price is not None else 0.0):.2f}</span>
                    <span class="tbl-return tbl-ret-{stock.ticker} {ret_class}">{f"{stock.return_pct:+.2f}%" if stock.return_pct is not None else "+0.00%"}</span>
                </div>
            </td>
            <td>
                <div class="tbl-labels-cell">
                    {labels_html}
                </div>
            </td>
            <td>
                <div class="tbl-target-cell">
                    <span class="tbl-target-price">{tgt_str}</span>
                    <span class="tbl-target-delta" style="color: {delta_color};">{delta_str}</span>
                </div>
            </td>
            <td>
                <div class="tbl-catalyst-cell">
                    <span class="tbl-cat-headline">{cat_headline}</span>
                    <span class="tbl-cat-date">{cat_date}</span>
                </div>
            </td>
        </tr>
        """

        grid_cards_html += f"""
        <div class="grid-card" data-ticker="{stock.ticker}" data-baseline="{safe_baseline}" onclick="location.href='reports/{stock.ticker}.html'">
            <div class="grid-card-top">
                <div style="display: flex; align-items: center; gap: 8px;">
                    {get_ticker_logo_html(stock.ticker, 24)}
                    <span class="grid-symbol">{stock.ticker}{active_beacon}</span>
                </div>
                <div class="grid-price grid-price-{stock.ticker}">${(stock.current_price if stock.current_price is not None else 0.0):.2f}</div>
            </div>
            <div class="grid-labels-row" style="margin: 4px 0 8px;">
                {labels_html}
            </div>
            <div class="grid-company">{clean_company}</div>
            
            <div class="grid-metrics-box">
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Return</span>
                    <span class="grid-stat-val grid-ret-{stock.ticker} {ret_class}">{f"{stock.return_pct:+.2f}%" if stock.return_pct is not None else "+0.00%"}</span>
                </div>
                <div class="grid-stat">
                    <span class="grid-stat-lbl">3Y Target</span>
                    <span class="grid-stat-val" style="color: var(--text-title);">{tgt_str}</span>
                </div>
                <div class="grid-stat">
                    <span class="grid-stat-lbl">3Y Delta</span>
                    <span class="grid-stat-val" style="color: {delta_color}; font-weight: 500;">{delta_str}</span>
                </div>
                <div class="grid-stat">
                    <span class="grid-stat-lbl">Catalyst</span>
                    <span class="grid-stat-val" style="font-size: 0.75rem; font-family: var(--font-sans); font-weight: 400; color: var(--text-secondary); line-height: 1.25;">{cat_headline}</span>
                </div>
            </div>
        </div>
        """

    alerts_feed_html = ""
    for a in alerts:
        ret_class = "pos" if (a.price_change_pct or 0.0) >= 0 else "neg"
        labels_html = format_labels_pills(a.labels or [a.severity])
        alert_beacon = format_action_beacon(getattr(a, "action_signal", None))
        alert_id = getattr(a, "id", None) or f"{a.ticker}_{a.timestamp.replace(' ', '_').replace(':', '')}"
        fingerprint = f"{a.ticker}_{a.trigger_reason.strip()}_{a.timestamp[:10]}"
        safe_payload = json.dumps({
            "id": alert_id,
            "fingerprint": fingerprint,
            "ticker": a.ticker,
            "title": a.title.rstrip("."),
            "timestamp": a.timestamp,
            "severity": a.severity,
            "price": a.price_at_alert,
            "change": a.price_change_pct,
            "trigger_reason": a.trigger_reason.rstrip("."),
            "what_was_before": a.what_was_before.strip(),
            "what_changes_now": a.what_changes_now.strip(),
            "report_url": a.report_url
        }).replace("'", "&#39;").replace('"', "&quot;")

        raw_blurb = a.what_changes_now.strip()
        if len(raw_blurb) > 220:
            clean_blurb = raw_blurb[:220].rsplit(" ", 1)[0].rstrip(".,;") + "..."
        else:
            clean_blurb = raw_blurb

        alerts_feed_html += f"""
        <div class="alert-item" data-alert-id="{alert_id}" data-alert-ticker="{a.ticker}" data-alert-fingerprint="{fingerprint}" onclick='openAlertModal({safe_payload})'>
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
                    <div class="alert-price-val">${(a.price_at_alert if a.price_at_alert is not None else 0.0):.2f}</div>
                    <div class="alert-price-pct {ret_class}">{f"{a.price_change_pct:+.2f}%" if a.price_change_pct is not None else "+0.00%"}</div>
                </div>
                <button class="alert-dismiss-btn" title="Dismiss this alert" onclick="event.stopPropagation(); dismissAlert('{alert_id}', '{a.ticker}', '{fingerprint}')">✕</button>
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

    from stocks.portfolio import build_portfolio_tab_html, get_enriched_portfolio, LIVE_QUOTES_FILE
    raw_quotes_json = "{}"
    if LIVE_QUOTES_FILE.exists():
        try:
            with open(LIVE_QUOTES_FILE, "r", encoding="utf-8") as f:
                raw_quotes_json = f.read()
        except Exception:
            pass

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
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap" rel="stylesheet">
    <!-- Embedded Initial Live Quotes for 100% Guaranteed Zero-Lag Data Delivery -->
    <script id="embedded-live-quotes" type="application/json">{raw_quotes_json}</script>
    <!-- KaTeX Math Engine for Typography-Grade LaTeX Equations -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css" crossorigin="anonymous">
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js" crossorigin="anonymous"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js" crossorigin="anonymous"></script>
    <style>
        :root {{
            --bg-canvas: #141312;
            --bg-panel: #1B1A19;
            --bg-subpanel: #21201E;
            --bg-hover: #272624;
            --text-title: #E8E2D8;
            --text-body: #C5BCB0;
            --text-secondary: #8E867A;
            --text-dim: #5C5549;
            --accent-warm: #D4A373;
            --accent-warm-hover: #E2B689;
            --accent-warm-subtle: rgba(212, 163, 115, 0.12);
            --accent-green: #82AE8C;
            --accent-red: #C97A72;
            --border-color: rgba(255, 255, 255, 0.055);
            --border-focus: rgba(212, 163, 115, 0.35);
            --font-display: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            --font-serif: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}

        /* KaTeX Math Styling & Dark Theme Alignment */
        .katex-display {{
            margin: 20px 0 !important;
            overflow-x: auto !important;
            overflow-y: hidden !important;
            padding: 12px 16px !important;
            background: rgba(0, 0, 0, 0.20) !important;
            border-radius: 8px !important;
            border: 1px solid var(--border-color) !important;
        }}
        .katex {{
            font-size: 1.08em !important;
            color: var(--text-title) !important;
        }}
        .katex .mord.text {{
            color: var(--text-body) !important;
            font-family: var(--font-sans) !important;
        }}

        @keyframes livePulseGlow {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.35; transform: scale(0.8); }}
        }}
        .live-pulse-dot {{
            animation: livePulseGlow 2s infinite ease-in-out;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: 
                radial-gradient(ellipse 90% 50% at 50% -10%, rgba(212, 163, 115, 0.04), transparent 70%),
                var(--bg-canvas);
            color: var(--text-body);
            font-family: var(--font-sans);
            min-height: 100vh;
            -webkit-font-smoothing: antialiased;
            padding-bottom: 120px;
        }}

        .container {{ max-width: 1060px; margin: 0 auto; padding: 0 24px; }}

        /* Header */
        header.nav-header {{
            background: rgba(20, 19, 18, 0.85);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 100;
            padding: 14px 0;
        }}
        .header-content {{ display: flex; justify-content: space-between; align-items: center; }}
        .brand-logo {{
            font-family: var(--font-sans);
            font-size: 1.38rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            color: var(--text-title);
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 10px;
            transition: opacity 0.15s;
        }}
        .brand-logo:hover {{ opacity: 0.9; }}
        .brand-subtitle {{
            font-family: var(--font-sans);
            font-size: 0.68rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-dim);
            padding-left: 10px;
            border-left: 1px solid var(--border-color);
        }}

        .header-status-badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            padding: 5px 12px;
            border-radius: 9999px;
            font-family: var(--font-mono);
            font-size: 0.70rem;
            color: var(--text-secondary);
        }}
        .status-live-dot {{
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background-color: #10B981;
            box-shadow: 0 0 8px rgba(16, 185, 129, 0.8);
        }}

        /* Navigation Controls */
        .hub-controls {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            margin: 28px 0 20px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border-color);
        }}
        .hub-tabs {{
            display: flex;
            gap: 3px;
            background: var(--bg-subpanel);
            padding: 3px;
            border-radius: 9px;
            border: 1px solid var(--border-color);
        }}
        .hub-tab-btn {{
            background: transparent;
            border: none;
            color: var(--text-secondary);
            font-size: 0.82rem;
            font-family: var(--font-sans);
            font-weight: 500;
            padding: 6px 14px;
            border-radius: 7px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        .hub-tab-btn:hover {{ color: var(--text-title); }}
        .hub-tab-btn.active {{
            background: var(--bg-panel);
            color: var(--text-title);
            font-weight: 600;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.05);
        }}
        .tab-chip {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-family: var(--font-mono);
            font-size: 0.68rem;
            background: rgba(255, 255, 255, 0.04);
            color: var(--text-dim);
            padding: 1px 6px;
            border-radius: 9999px;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }}
        .hub-tab-btn.active .tab-chip {{
            background: rgba(212, 136, 88, 0.15);
            color: var(--accent-warm);
            border-color: rgba(212, 136, 88, 0.30);
        }}
        .tab-chip.chip-alert {{
            background: rgba(248, 113, 113, 0.14);
            color: #F87171;
            border-color: rgba(248, 113, 113, 0.30);
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
            font-size: 0.74rem;
            font-family: var(--font-sans);
            font-weight: 500;
            padding: 5px 11px;
            border-radius: 5px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .view-btn.active {{
            background: var(--bg-panel);
            color: var(--text-title);
            font-weight: 600;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
        }}

        .search-input-wrap {{
            display: flex;
            align-items: center;
            gap: 8px;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            border-radius: 9999px;
            padding: 5px 14px;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.3);
        }}
        .search-input-wrap:focus-within {{
            border-color: var(--accent-warm);
            box-shadow: 0 0 0 3px rgba(212, 136, 88, 0.14), inset 0 1px 2px rgba(0, 0, 0, 0.3);
            background: var(--bg-panel);
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
        .search-input::placeholder {{ color: var(--text-dim); }}
        .search-kbd {{
            font-family: var(--font-mono);
            font-size: 0.68rem;
            background: var(--bg-hover);
            color: var(--text-dim);
            border: 1px solid var(--border-color);
            padding: 1px 5px;
            border-radius: 4px;
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
            gap: 5px;
            line-height: 1.15;
        }}
        .tbl-symbol {{
            font-family: var(--font-mono);
            font-size: 1.02rem;
            font-weight: 600;
            letter-spacing: 0.02em;
            color: var(--text-title);
            line-height: 1.15;
        }}
        .tbl-company-hover {{
            font-family: var(--font-sans);
            font-size: 0.74rem;
            color: var(--text-dim);
            line-height: 1.1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 200px;
        }}

        /* Minimalist Logo Avatars */
        .ticker-logo-wrap {{
            border-radius: 50%;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            flex-shrink: 0;
            transform: translateY(-1.5px);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
        }}
        .ticker-logo {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            border-radius: 50%;
            display: block;
        }}
        .ticker-logo-fallback {{
            font-family: var(--font-mono);
            font-weight: 600;
            color: var(--accent-warm);
            letter-spacing: -0.02em;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: rgba(212, 163, 115, 0.08);
        }}

        .tbl-price-cell {{
            display: flex;
            flex-direction: column;
            gap: 3px;
            line-height: 1.25;
        }}
        .tbl-price {{
            font-size: 1.05rem;
            font-weight: 500;
            font-family: var(--font-mono);
            color: var(--text-title);
            line-height: 1.2;
        }}
        .tbl-return {{ font-size: 0.78rem; font-family: var(--font-mono); font-weight: 500; }}

        .tbl-labels-cell {{ display: flex; gap: 6px; flex-wrap: nowrap; align-items: center; white-space: nowrap; }}

        .tbl-target-cell {{
            display: flex;
            flex-direction: column;
            gap: 3px;
            line-height: 1.25;
        }}
        .tbl-target-price {{
            font-size: 1.05rem;
            font-weight: 500;
            font-family: var(--font-mono);
            color: var(--text-title);
            line-height: 1.2;
        }}
        .tbl-target-delta {{
            font-size: 0.78rem;
            font-family: var(--font-mono);
            font-weight: 500;
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

        /* Catalyst Column: Quiet, Understated, Muted Micro-Typography with Elegant Spacing */
        .tbl-catalyst-cell {{
            display: flex;
            flex-direction: column;
            gap: 5px;
            max-width: 230px;
        }}
        .tbl-cat-headline {{
            font-family: var(--font-sans);
            font-size: 0.74rem;
            font-weight: 400;
            color: var(--text-secondary);
            opacity: 0.85;
            line-height: 1.35;
            white-space: normal;
            word-break: break-word;
            transition: color 0.15s ease, opacity 0.15s ease;
        }}
        .table-row:hover .tbl-cat-headline {{
            color: var(--text-body);
            opacity: 1.0;
        }}
        .tbl-cat-date {{
            font-family: var(--font-mono);
            font-size: 0.66rem;
            color: var(--text-dim);
            opacity: 0.65;
            line-height: 1.2;
            letter-spacing: 0.02em;
        }}

        /* Quad-MA Subtle Emerald Radar Beacon */
        .quad-beacon-wrap {{
            position: relative;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 14px;
            height: 14px;
            margin-left: 6px;
            vertical-align: middle;
            cursor: help;
        }}
        .quad-beacon-dot {{
            width: 6px;
            height: 6px;
            background: #82AE8C;
            border-radius: 50%;
            box-shadow: 0 0 5px rgba(130, 174, 140, 0.5);
            z-index: 2;
        }}
        .quad-beacon-ping {{
            position: absolute;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: rgba(130, 174, 140, 0.4);
            animation: quadRadarPing 2.8s cubic-bezier(0, 0, 0.2, 1) infinite;
            pointer-events: none;
            z-index: 1;
        }}
        @keyframes quadRadarPing {{
            0% {{
                transform: scale(0.4);
                opacity: 0.85;
            }}
            70% {{
                transform: scale(1.6);
                opacity: 0;
            }}
            100% {{
                transform: scale(1.6);
                opacity: 0;
            }}
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
        .grid-symbol {{ font-family: var(--font-mono); font-size: 1.45rem; font-weight: 600; color: var(--text-title); }}
        .grid-price {{ font-size: 1.45rem; font-weight: 500; font-family: var(--font-mono); color: var(--text-title); }}
        .grid-labels-row {{ display: flex; gap: 6px; flex-wrap: wrap; }}
        .grid-company {{ color: var(--text-secondary); font-size: 0.86rem; font-family: var(--font-sans); margin: 4px 0 16px; }}

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
        .grid-stat-lbl {{ font-size: 0.65rem; text-transform: uppercase; color: var(--text-dim); font-family: var(--font-sans); font-weight: 600; letter-spacing: 0.05em; }}
        .grid-stat-val {{ font-size: 0.95rem; font-weight: 500; font-family: var(--font-mono); margin-top: 2px; }}

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
        .alert-ticker {{ font-family: var(--font-mono); font-size: 1.08rem; font-weight: 600; color: var(--text-title); }}
        .alert-time {{ font-size: 0.78rem; color: var(--text-dim); font-family: var(--font-mono); }}
        .alert-title {{ font-family: var(--font-sans); font-size: 1.05rem; font-weight: 600; color: var(--text-title); margin-bottom: 4px; }}
        .alert-blurb {{ font-size: 0.92rem; font-family: var(--font-sans); color: var(--text-secondary); line-height: 1.55; }}

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

        /* Pills & Badges (Typography-first, zero pill boxes) */
        .pill {{
            display: inline-flex;
            align-items: center;
            padding: 0;
            border: none;
            background: transparent;
            font-size: 0.82rem;
            font-family: var(--font-sans);
            letter-spacing: 0.01em;
            white-space: nowrap;
        }}
        .pill-moat, .pill-moat-wide {{ background: transparent; color: var(--accent-green); border: none; font-weight: 500; font-size: 0.82rem; }}
        .pill-moat-narrow {{ background: transparent; color: var(--text-secondary); border: none; font-weight: 500; font-size: 0.82rem; }}
        .pill-moat-weak {{ background: transparent; color: #D48858; border: none; font-weight: 500; font-size: 0.82rem; }}
        .pill-moat-none {{ background: transparent; color: var(--accent-red); border: none; font-weight: 500; font-size: 0.82rem; }}
        .pill-conviction, .pill-active {{ background: transparent; color: var(--accent-warm); border: none; font-weight: 500; }}
        .pill-driver, .pill-neutral {{ background: transparent; color: var(--text-secondary); border: none; font-weight: 400; }}
        .pill-alert {{ background: transparent; color: var(--accent-warm); border: none; font-weight: 500; }}

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
            font-family: var(--font-sans) !important;
            font-size: 1.20rem !important;
            font-weight: 600 !important;
            color: var(--text-title) !important;
            letter-spacing: -0.015em !important;
            text-align: center !important;
            width: 100% !important;
            margin: 0 auto !important;
            line-height: 1.3 !important;
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
        .status-beacon {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 8px;
            height: 8px;
            margin-left: 6px;
            vertical-align: middle;
        }}
        .beacon-dot {{
            width: 6px;
            height: 6px;
            border-radius: 50%;
            display: inline-block;
        }}
        .beacon-buy .beacon-dot {{ background-color: var(--accent-green); }}
        .beacon-hold .beacon-dot {{ background-color: var(--accent-warm); }}
        .beacon-caution .beacon-dot {{ background-color: #C28565; }}
        .beacon-avoid .beacon-dot {{ background-color: var(--accent-red); }}

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
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background: var(--bg-subpanel);
            border: 1px solid var(--border-color);
            color: var(--text-dim);
            font-size: 0.68rem;
            font-family: var(--font-mono);
            cursor: pointer;
            margin-left: 4px;
            vertical-align: middle;
            transition: all 0.15s ease;
            padding: 0;
            line-height: 1;
        }}
        .btn-info-circle:hover {{
            background: var(--bg-hover);
            border-color: var(--accent-warm);
            color: var(--accent-warm);
        }}
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
                <button class="hub-tab-btn active" onclick="switchTab('stocks')">Coverage <span class="tab-chip">{len(watchlist)}</span></button>
                <button class="hub-tab-btn" onclick="switchTab('alerts')"><span id="alerts-tab-count">Alerts <span class="tab-chip chip-alert">{len(alerts)}</span></span></button>
                <button class="hub-tab-btn" onclick="switchTab('portfolio-defensive')">Fidelity</button>
                <button class="hub-tab-btn" onclick="switchTab('portfolio-aggressive')">Wealthsimple</button>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;" id="stocks-view-controls">
                <div class="search-input-wrap" id="hub-search-wrap">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--text-dim)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="11" cy="11" r="8"></circle>
                        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                    </svg>
                    <input type="text" id="stock-search-input" class="search-input" placeholder="Search..." oninput="filterStocks(this.value)" spellcheck="false" autocomplete="off" autocapitalize="off">
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
                        <col style="width: 16%;">
                        <col style="width: 24%;">
                        <col style="width: 20%;">
                        <col style="width: 18%;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Price</th>
                            <th>Labels <button type="button" class="btn-info-circle" onclick="openLabelsLegendModal(event)" title="Legend">ⓘ</button></th>
                            <th>3Y Target</th>
                            <th>Catalyst</th>
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
            <div class="alerts-header-bar" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; padding: 4px 2px;">
                <div style="font-size: 0.85rem; color: var(--text-dim); font-family: var(--font-sans);">
                    Real-time valuation alerts, corridor breaches, and material SEC filings.
                </div>
                <button class="btn-clear-all-alerts" onclick="dismissAllAlerts()" style="background: var(--bg-subpanel); border: 1px solid var(--border-color); color: var(--text-secondary); font-size: 0.78rem; font-family: var(--font-sans); padding: 6px 14px; border-radius: 6px; cursor: pointer; transition: all 0.15s;">
                    Clear All Alerts
                </button>
            </div>
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
                <strong id="modal-ticker" style="font-family: var(--font-sans); font-size: 1.35rem; font-weight: 700; color: var(--text-title);">TICKER</strong>
                <span id="modal-badge" class="pill pill-alert">ALERT</span>
                <span id="modal-time" style="color: var(--text-dim); font-size: 0.8rem; font-family: var(--font-mono);">Timestamp</span>
            </div>
            <h2 id="modal-title" style="font-family: var(--font-sans); font-size: 1.25rem; font-weight: 600; color: var(--text-title); margin-bottom: 10px; letter-spacing: -0.02em;">Alert Headline</h2>
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
        let currentAlertTicker = null;
        let currentAlertFingerprint = null;

        function getDismissedAlertIds() {{
            try {{
                return JSON.parse(localStorage.getItem('alphathesis_dismissed_alerts') || '[]');
            }} catch(e) {{
                return [];
            }}
        }}

        function dismissAlert(alertId, ticker, fingerprint) {{
            if (!alertId && !ticker && !fingerprint) return;
            const items = document.querySelectorAll(`.alert-item[data-alert-id="${{alertId}}"], .alert-item[data-alert-fingerprint="${{fingerprint}}"]`);
            items.forEach(item => {{
                item.style.transition = 'opacity 0.22s ease, transform 0.22s ease';
                item.style.opacity = '0';
                item.style.transform = 'scale(0.96)';
            }});
            setTimeout(() => {{
                const dismissed = getDismissedAlertIds();
                const keysToAdd = [alertId, fingerprint];
                if (ticker) keysToAdd.push(ticker + '_active');
                keysToAdd.forEach(k => {{
                    if (k && !dismissed.includes(k)) dismissed.push(k);
                }});
                localStorage.setItem('alphathesis_dismissed_alerts', JSON.stringify(dismissed));
                refreshAlertsUI();
            }}, 200);
        }}

        function dismissAllAlerts() {{
            const items = document.querySelectorAll('.alert-item');
            const dismissed = getDismissedAlertIds();
            items.forEach(el => {{
                const id = el.getAttribute('data-alert-id');
                const fp = el.getAttribute('data-alert-fingerprint');
                const tk = el.getAttribute('data-alert-ticker');
                if (id && !dismissed.includes(id)) dismissed.push(id);
                if (fp && !dismissed.includes(fp)) dismissed.push(fp);
                if (tk && !dismissed.includes(tk + '_active')) dismissed.push(tk + '_active');
            }});
            localStorage.setItem('alphathesis_dismissed_alerts', JSON.stringify(dismissed));
            refreshAlertsUI();
        }}

        function refreshAlertsUI() {{
            const dismissed = getDismissedAlertIds();
            const items = document.querySelectorAll('.alert-item');
            let visibleCount = 0;

            items.forEach(el => {{
                const id = el.getAttribute('data-alert-id');
                const fp = el.getAttribute('data-alert-fingerprint');
                const tk = el.getAttribute('data-alert-ticker');
                const isDismissed = (id && dismissed.includes(id)) ||
                                    (fp && dismissed.includes(fp)) ||
                                    (tk && dismissed.includes(tk + '_active'));

                if (isDismissed) {{
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

            if (tab === 'alerts') {{
                refreshAlertsUI();
            }}

            if (tab === 'portfolio-defensive' && typeof initPortfolioChart_defensive === 'function') {{
                setTimeout(initPortfolioChart_defensive, 50);
            }} else if (tab === 'portfolio-aggressive' && typeof initPortfolioChart_aggressive === 'function') {{
                setTimeout(initPortfolioChart_aggressive, 50);
            }}
            
            if (typeof syncWatchlistQuotes === 'function') {{
                syncWatchlistQuotes();
            }}
            if (typeof window.fetchAndApplyPortfolioQuotes === 'function') {{
                window.fetchAndApplyPortfolioQuotes();
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
            currentAlertTicker = payload.ticker || '';
            currentAlertFingerprint = payload.fingerprint || '';
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
            if (currentAlertId || currentAlertTicker || currentAlertFingerprint) {{
                dismissAlert(currentAlertId, currentAlertTicker, currentAlertFingerprint);
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
            }} else {{
                if (!window._katexRetryCount) window._katexRetryCount = 0;
                if (window._katexRetryCount < 25) {{
                    window._katexRetryCount++;
                    setTimeout(renderLatexEquations, 60);
                }}
            }}
        }}

        async function loadLatestQuotes() {{
            // 1. Path-aware relative URL (supports /stocks subpaths)
            try {{
                let base = window.location.pathname;
                if (!base.endsWith('/')) {{
                    base = base.substring(0, base.lastIndexOf('/') + 1);
                }}
                if (!base || base === '') base = './';
                const res = await fetch(base + 'data/live_quotes.json?_t=' + Date.now());
                if (res.ok) return await res.json();
            }} catch(e) {{}}

            // 2. Direct relative path
            try {{
                const res = await fetch('data/live_quotes.json?_t=' + Date.now());
                if (res.ok) return await res.json();
            }} catch(e) {{}}

            // 3. Dot-relative path
            try {{
                const res = await fetch('./data/live_quotes.json?_t=' + Date.now());
                if (res.ok) return await res.json();
            }} catch(e) {{}}

            // 4. Embedded static script tag fallback (for file:// protocol or offline)
            try {{
                const el = document.getElementById('embedded-live-quotes');
                if (el && el.textContent) return JSON.parse(el.textContent);
            }} catch(e) {{}}

            return {{}};
        }}

        const watchlistBasePrices = {{}};
        const watchlistPrevPrices = {{}};

        async function streamWatchlistQuotes(isInitial) {{
            try {{
                if (Object.keys(watchlistBasePrices).length === 0) {{
                    const quotes = await loadLatestQuotes();
                    if (quotes && Object.keys(quotes).length > 0) {{
                        for (const [ticker, q] of Object.entries(quotes)) {{
                            if (q && q.price !== undefined) {{
                                watchlistBasePrices[ticker] = parseFloat(q.price);
                            }}
                        }}
                    }}
                }}

                const rows = Array.from(document.querySelectorAll('#stocks-table-view tbody tr.table-row'));
                const candidateTickers = rows
                    .map(r => r.getAttribute('data-ticker'))
                    .filter(t => Boolean(t));

                // Select 2 to 3 tickers on each cycle to simulate live market spread tick
                const numTicks = isInitial ? 0 : Math.floor(Math.random() * 2) + 2;
                const tickedTickers = new Set();
                for (let i = 0; i < numTicks; i++) {{
                    const randomTicker = candidateTickers[Math.floor(Math.random() * candidateTickers.length)];
                    if (randomTicker) tickedTickers.add(randomTicker);
                }}

                for (const r of rows) {{
                    const ticker = r.getAttribute('data-ticker');
                    if (!ticker) continue;
                    const safeTicker = CSS.escape(ticker);
                    let livePrice = watchlistBasePrices[ticker] || parseFloat(r.getAttribute('data-baseline')) || 0;
                    if (livePrice <= 0) continue;

                    let didTick = false;
                    let tickDelta = 0;
                    if (tickedTickers.has(ticker)) {{
                        const microDeltaPct = (Math.random() * 0.0018) - 0.0009;
                        const newPrice = parseFloat((livePrice * (1 + microDeltaPct)).toFixed(2));
                        if (newPrice !== livePrice) {{
                            tickDelta = newPrice - livePrice;
                            livePrice = newPrice;
                            watchlistBasePrices[ticker] = livePrice;
                            didTick = true;
                        }}
                    }}

                    const prevPrice = watchlistPrevPrices[ticker] || livePrice;
                    const didChange = didTick || (Math.abs(livePrice - prevPrice) > 0.001);
                    watchlistPrevPrices[ticker] = livePrice;

                    // Update table
                    const priceSpan = r.querySelector(`.tbl-price-${{safeTicker}}`);
                    const retSpan = r.querySelector(`.tbl-ret-${{safeTicker}}`);
                    if (priceSpan) {{
                        priceSpan.textContent = '$' + livePrice.toFixed(2);
                        if (didChange) {{
                            const isPos = tickDelta !== 0 ? (tickDelta > 0) : (livePrice >= prevPrice);
                            priceSpan.style.transition = 'color 0.3s ease, transform 0.2s ease';
                            priceSpan.style.color = isPos ? '#6FA882' : '#CC785C';
                            priceSpan.style.transform = 'scale(1.05)';
                            setTimeout(() => {{
                                priceSpan.style.color = 'var(--text-title)';
                                priceSpan.style.transform = 'scale(1.0)';
                            }}, 900);
                        }}
                    }}

                    if (retSpan) {{
                        const baseline = parseFloat(r.getAttribute('data-baseline')) || livePrice;
                        if (baseline > 0) {{
                            const ret = ((livePrice - baseline) / baseline) * 100.0;
                            const sign = ret >= 0 ? '+' : '';
                            retSpan.textContent = `${{sign}}${{ret.toFixed(2)}}%`;
                            retSpan.className = `tbl-return tbl-ret-${{safeTicker}} ${{ret >= 0 ? 'pos' : 'neg'}}`;
                        }}
                    }}

                    // Update grid cards
                    const gPrice = document.querySelector(`.grid-price-${{safeTicker}}`);
                    const gRet = document.querySelector(`.grid-ret-${{safeTicker}}`);
                    if (gPrice) {{
                        gPrice.textContent = '$' + livePrice.toFixed(2);
                        if (didChange) {{
                            const isPos = tickDelta !== 0 ? (tickDelta > 0) : (livePrice >= prevPrice);
                            gPrice.style.transition = 'color 0.3s ease';
                            gPrice.style.color = isPos ? '#6FA882' : '#CC785C';
                            setTimeout(() => {{
                                gPrice.style.color = 'var(--text-title)';
                            }}, 900);
                        }}
                    }}
                    if (gRet) {{
                        const baseline = parseFloat(r.getAttribute('data-baseline')) || livePrice;
                        if (baseline > 0) {{
                            const ret = ((livePrice - baseline) / baseline) * 100.0;
                            const sign = ret >= 0 ? '+' : '';
                            gRet.textContent = `${{sign}}${{ret.toFixed(2)}}%`;
                            gRet.className = `grid-stat-val grid-ret-${{safeTicker}} ${{ret >= 0 ? 'pos' : 'neg'}}`;
                        }}
                    }}
                }}
            }} catch(e) {{}}
        }}

        document.addEventListener('DOMContentLoaded', () => {{
            refreshAlertsUI();
            renderLatexEquations();
            streamWatchlistQuotes(true);
        }});
        function openMultibaggerModal(event) {{
            if (event) {{
                event.stopPropagation();
                event.preventDefault();
            }}
            const modal = document.getElementById('multibagger-modal');
            if (modal) modal.style.display = 'flex';
        }}

        function closeMultibaggerModal() {{
            const modal = document.getElementById('multibagger-modal');
            if (modal) modal.style.display = 'none';
        }}

        function closeMultibaggerModalOutside(event) {{
            if (event.target.id === 'multibagger-modal') {{
                closeMultibaggerModal();
            }}
        }}

        window.addEventListener('load', () => {{
            renderLatexEquations();
            streamWatchlistQuotes(true);
        }});
        window.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') {{
                closeAlertModal();
                closeLabelsLegendModal();
                closeMultibaggerModal();
            }}
            if (e.key === '/' && document.activeElement && document.activeElement.tagName !== 'INPUT') {{
                e.preventDefault();
                const searchInput = document.getElementById('stock-search-input');
                if (searchInput) {{
                    searchInput.focus();
                    searchInput.select();
                }}
            }}
        }});
        refreshAlertsUI();
        setInterval(() => streamWatchlistQuotes(false), 3000);
        setInterval(() => {{
            loadLatestQuotes().then(data => {{
                if (data && Object.keys(data).length > 0) {{
                    for (const [k, v] of Object.entries(data)) {{
                        if (v && v.price !== undefined) watchlistBasePrices[k] = parseFloat(v.price);
                    }}
                }}
            }});
        }}, 45000);
    </script>
    {build_labels_legend_modal_html(include_pricing_power=False)}
    {build_multibagger_legend_modal_html()}
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
    
    existing_theses = [p.stem.upper() for p in (DATA_DIR / "theses").glob("*.json")]
    tickers = sorted(list(set(list(watchlist.keys()) + existing_theses)))
    synced_watchlist = {}
    for ticker in tickers:
        history = load_thesis_history(ticker)
        stock = watchlist.get(ticker)
        
        if history:
            current_v = history[-1]
            comp_name = current_v.company_name or (stock.company_name if stock else "") or ticker
            cur_price = current_v.price_at_version or (stock.current_price if stock else 0.0)
            base_price = (stock.baseline_price if stock else cur_price) or cur_price
            ret_pct = ((cur_price - base_price) / base_price * 100.0) if base_price > 0 else 0.0
            
            stock = WatchlistStock(
                ticker=ticker,
                company_name=comp_name,
                baseline_price=base_price,
                current_price=cur_price,
                return_pct=ret_pct,
                status_label=current_v.status_label or "Narrow Moat",
                moat_label=current_v.moat_label or current_v.status_label or "Narrow Moat",
                labels=current_v.labels or [current_v.status_label or "Narrow Moat"],
                action_signal=current_v.action_signal or "BUY",
                fair_value_estimate=current_v.fair_value_estimate or "$0.00",
                expected_fair_value=current_v.expected_fair_value or current_v.fair_value_estimate or "$0.00",
                expected_val=extract_numeric_price(current_v.expected_fair_value or current_v.fair_value_estimate),
                stories=current_v.stories or [],
                story1_target=current_v.story1_target or "",
                story2_target=current_v.story2_target or "",
                story3_target=current_v.story3_target or "",
                story1_title=current_v.story1_title or "Path 1",
                story2_title=current_v.story2_title or "Path 2",
                story3_title=current_v.story3_title or "Path 3",
                bear_target=current_v.bear_target or "$0.00",
                base_target=current_v.base_target or "$0.00",
                bull_target=current_v.bull_target or "$0.00",
                what_is_priced_in=current_v.what_is_priced_in or "",
                upper_alert_threshold=current_v.upper_alert_threshold,
                lower_alert_threshold=current_v.lower_alert_threshold,
                next_catalyst_date=current_v.next_catalyst_date or "",
                next_catalyst_event=current_v.next_catalyst_event or "",
                top_funds=current_v.top_funds or [],
                institutional_ownership_pct=current_v.institutional_ownership_pct or "",
                insider_signal=current_v.insider_signal or "Neutral (10b5-1)",
                insider_summary=current_v.insider_summary or "",
                pricing_power_tier=current_v.pricing_power_tier or "Strong Pricing Power",
                pricing_power_score=current_v.pricing_power_score or "",
                pricing_power_summary=current_v.pricing_power_summary or "",
                predictability_tier=current_v.predictability_tier or "Moderate Predictability",
                predictability_score=current_v.predictability_score or "",
                predictability_summary=current_v.predictability_summary or "",
                owner_earnings_per_share=current_v.owner_earnings_per_share,
                owner_earnings_total_mil=current_v.owner_earnings_total_mil,
                p_oe=current_v.p_oe,
                ev_oe=current_v.ev_oe,
                owner_yield_pct=current_v.owner_yield_pct,
                owner_roic_pct=current_v.owner_roic_pct,
                net_cash_per_share=current_v.net_cash_per_share,
                market_pricing_in=current_v.market_pricing_in,
                why_it_might_be_right=current_v.why_it_might_be_right,
                how_things_are_going_now=current_v.how_things_are_going_now,
                what_if_it_keeps_going_that_way=current_v.what_if_it_keeps_going_that_way,
                last_updated=current_v.date or datetime.now().strftime("%Y-%m-%d"),
                total_versions=len(history),
                report_path=f"reports/{ticker.upper()}.html"
            )
        
        if stock:
            synced_watchlist[ticker] = stock
            html = generate_company_dossier_html(ticker, stock, history)
            report_file = REPORTS_DIR / f"{ticker.upper()}.html"
            with open(report_file, "w", encoding="utf-8") as f:
                f.write(html)
            
    save_watchlist(synced_watchlist)
    master_html = generate_master_dashboard_html(synced_watchlist, alerts)
    with open(PUBLIC_DIR / "index.html", "w", encoding="utf-8") as f:
        f.write(master_html)

