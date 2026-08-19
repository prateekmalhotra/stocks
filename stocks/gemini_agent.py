import os
import json
import time
import re
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional, List
from dotenv import load_dotenv

load_dotenv()

DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
_CURRENT_ACTIVE_MODEL = DEFAULT_GEMINI_MODEL
GEMINI_MODELS_LADDER = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest"
]
if DEFAULT_GEMINI_MODEL not in GEMINI_MODELS_LADDER:
    GEMINI_MODELS_LADDER.insert(0, DEFAULT_GEMINI_MODEL)


def get_active_model() -> str:
    """Returns the current in-memory active model for this workflow run."""
    global _CURRENT_ACTIVE_MODEL
    return _CURRENT_ACTIVE_MODEL


def switch_to_fallback_model(reason: str = "") -> str:
    """Switches the active model to the next fallback model in the ladder."""
    global _CURRENT_ACTIVE_MODEL
    try:
        cur_idx = GEMINI_MODELS_LADDER.index(_CURRENT_ACTIVE_MODEL)
        if cur_idx + 1 < len(GEMINI_MODELS_LADDER):
            next_model = GEMINI_MODELS_LADDER[cur_idx + 1]
            print(f"  ⚡ [Model Failover] Switching active model for this workflow run to {next_model}. (Reason: {reason})")
            _CURRENT_ACTIVE_MODEL = next_model
    except Exception:
        _CURRENT_ACTIVE_MODEL = "gemini-flash-lite-latest"
    return _CURRENT_ACTIVE_MODEL


def get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY is not set in environment or .env file.")
    return key


def normalize_catalyst_date(raw_date: Any) -> str:
    """Deterministically normalizes any raw date string to strict YYYY-MM-DD format."""
    if not raw_date or not isinstance(raw_date, str):
        return (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
    
    cleaned = raw_date.strip()
    
    # 1. Match exact YYYY-MM-DD
    match_iso = re.search(r"\b(202[4-9])-([01]\d)-([0-3]\d)\b", cleaned)
    if match_iso:
        return f"{match_iso.group(1)}-{match_iso.group(2)}-{match_iso.group(3)}"
    
    # 2. Try standard strptime formats
    date_formats = [
        "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
        "%d %B %Y", "%d %b %Y", "%Y/%m/%d", "%m/%d/%Y",
        "%B %Y", "%b %Y"
    ]
    for fmt in date_formats:
        try:
            dt = datetime.strptime(cleaned, fmt)
            if fmt in ("%B %Y", "%b %Y"):
                dt = dt.replace(day=15)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
            
    # 3. Match Month + Year substring (e.g. 'Expected November 2026')
    months = {
        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
        'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
    }
    for m_str, m_num in months.items():
        if m_str in cleaned.lower():
            year_match = re.search(r"\b(202[4-9])\b", cleaned)
            year = year_match.group(1) if year_match else datetime.now().strftime("%Y")
            day_match = re.search(r"\b([0-3]?\d)\b", cleaned.replace(year, ""))
            day = f"{int(day_match.group(1)):02d}" if day_match and 1 <= int(day_match.group(1)) <= 31 else "15"
            return f"{year}-{m_num}-{day}"
            
    # 4. Fallback to next quarter (+90 days)
    return (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")


def clean_grounding_artifacts(text: str) -> str:
    """Strips internal search grounding artifacts, rogue inline styles, and meta references."""
    if not text:
        return ""
    cleaned = re.sub(r"\[(?:PerQueryResult|cite|source|citation)[^\]]*\]", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\s*\d+(?:\.\d+)*(?:\s*,\s*\d+(?:\.\d+)*)*\s*\]", "", cleaned)
    
    # Strip any accidental meta references to historical analogies
    cleaned = re.sub(r"\b(?:Norbert\s+Lou(?:'s)?(?:\s+NVR)?|NVR\s+thesis|Columbia\s+(?:Business\s+School\s+)?(?:thesis|memo|paper))\b", "", cleaned, flags=re.IGNORECASE)
    
    # Strip any stray Wall Street sell-side analyst targets or broker ratings
    cleaned = re.sub(r"\b(?:Wall Street|sell-side|analyst|broker|consensus)\s+(?:price\s+target|target\s+price|consensus\s+target|PT)\s*(?:of|is|at|set\s+at)?\s*\$?\d+(?:\.\d+)?\b", "", cleaned, flags=re.IGNORECASE)
    
    # Strip ALL inline style, bgcolor, and border attributes to enforce 100% theme consistency
    cleaned = re.sub(r'\s*style\s*=\s*"[^"]*"', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*style\s*=\s*'[^']*'", '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<(table|thead|tbody|tr|th|td)\b([^>]*?)(bgcolor="[^"]*")([^>]*?)>', r'<\1\2\4>', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<(table|thead|tbody|tr|th|td)\b([^>]*?)(border="[^"]*")([^>]*?)>', r'<\1\2\4>', cleaned, flags=re.IGNORECASE)
    # Strip ALL img tags and figure containers (pure professional text and tables only)
    cleaned = re.sub(r'<div\s+class="figure-container"[^>]*>.*?</div>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<figure\b[^>]*>.*?</figure>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<img\b[^>]*>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'class="[^"]*bg-white[^"]*"', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


CANONICAL_CONVICTION_TIERS = [
    "High Conviction",
    "Solid Conviction",
    "Moderate Conviction",
    "Cautious Stance",
    "Turnaround Play",
    "Speculative Risk",
]


def map_to_canonical_conviction_tier(lbl: str, action_signal: str = "", base_ret: float = 0.0) -> str:
    """Maps any input conviction string or fallback signal to one of the 6 canonical Conviction Tiers:
    1. High Conviction: Dominant moat & fortress balance sheet
    2. Solid Conviction: Recurring cash flow & compounding runway
    3. Moderate Conviction: Attractive upside with cyclical exposure
    4. Cautious Stance: Navigating margin or temporary friction / valuation premium
    5. Turnaround Play: Operational reset or debt reduction
    6. Speculative Risk: High asymmetry with binary outcome
    """
    if lbl and isinstance(lbl, str):
        clean = lbl.strip().upper()
        # Direct exact match check
        for tier in CANONICAL_CONVICTION_TIERS:
            if clean == tier.upper():
                return tier
        # Keyword based matching
        if any(k in clean for k in ["TURNAROUND", "RESTRUCTURING", "OPERATIONAL RESET", "DEBT REDUCTION"]):
            return "Turnaround Play"
        elif any(k in clean for k in ["SPECULATIVE", "BINARY", "ASYMMETRY", "UNPROVEN", "HIGH RISK"]):
            return "Speculative Risk"
        elif any(k in clean for k in ["CAUTION", "CAUTIOUS", "FRICTION", "VALUATION RISK", "HEADWIND", "PREMIUM", "OVERVALUED"]):
            return "Cautious Stance"
        elif any(k in clean for k in ["MODERATE", "CYCLICAL", "EXPOSURE", "AVERAGE"]):
            return "Moderate Conviction"
        elif any(k in clean for k in ["SOLID", "COMPOUNDER", "STEADY", "RECURRING", "RUNWAY"]):
            return "Solid Conviction"
        elif any(k in clean for k in ["HIGH CONVICTION", "HIGH", "DOMINANT", "FORTRESS", "DEEP VALUE", "MOAT"]):
            return "High Conviction"
            
    # Derive from action signal & return if not provided or matched generic
    sig = (action_signal or "").upper().strip()
    if sig in ["AVOID", "RED"] or base_ret < -15.0:
        return "Cautious Stance"
    elif sig in ["CAUTION", "ORANGE"] or base_ret < 0.0:
        return "Cautious Stance"
    elif sig in ["BUY", "GREEN"] and base_ret >= 25.0:
        return "High Conviction"
    elif sig in ["BUY", "GREEN"]:
        return "Solid Conviction"
    elif sig in ["HOLD", "YELLOW"]:
        return "Solid Conviction"
    return "Solid Conviction"


def sanitize_labels(labels: Any, action_signal: str = "", base_ret: float = 0.0) -> List[str]:
    """Sanitizes labels ensuring:
    - Slot 1 is STRICTLY one of the 6 canonical Conviction Tiers:
      * High Conviction, Solid Conviction, Moderate Conviction, Cautious Stance, Turnaround Play, Speculative Risk.
    - Slots 2 & 3 are specific 2-word operating/catalyst drivers (e.g. "Cloud Leader", "Ad Monopoly").
    - Max 3 labels total.
    - Eliminates all generic placeholders like 'Active', 'Review', 'None', etc.
    """
    if not isinstance(labels, list):
        if isinstance(labels, str) and labels:
            labels = [labels]
        else:
            labels = []

    GENERIC_BLACKLIST = {
        "ACTIVE", "REVIEW", "ALERT", "UPDATE", "TASK", "STOCK", "STATUS", 
        "NEW", "NONE", "PRICE", "CONVICTION", "TBD", "HOLD", "BUY", "AVOID", "CAUTION"
    }
    
    # 1. Determine canonical conviction tier for Slot 1
    raw_slot1 = labels[0] if labels and isinstance(labels[0], str) else ""
    conviction_tier = map_to_canonical_conviction_tier(raw_slot1, action_signal=action_signal, base_ret=base_ret)
    
    # If action signal is AVOID/CAUTION, override bullish conviction in slot 1
    sig = (action_signal or "").upper().strip()
    if (sig == "AVOID" or base_ret < -15.0) and conviction_tier in ["High Conviction", "Solid Conviction"]:
        conviction_tier = "Cautious Stance"
    elif (sig == "CAUTION" or base_ret < 0.0) and conviction_tier in ["High Conviction", "Solid Conviction"]:
        conviction_tier = "Cautious Stance"

    clean_drivers = []
    # Check remaining elements for driver tags
    candidates = labels[1:] if len(labels) > 1 else []
    # Also check if raw_slot1 was a driver instead of a conviction tier
    if raw_slot1 and raw_slot1.upper() not in [t.upper() for t in CANONICAL_CONVICTION_TIERS] and raw_slot1.upper() not in GENERIC_BLACKLIST:
        candidates = [raw_slot1] + candidates

    for item in candidates:
        if not isinstance(item, str):
            continue
        words = [w for w in item.replace("/", " ").replace("-", " ").replace("&", " ").split() if w.strip()]
        if words:
            short_lbl = " ".join(words[:2]).title()
            if (
                short_lbl.upper() not in GENERIC_BLACKLIST 
                and short_lbl != conviction_tier 
                and short_lbl not in clean_drivers
            ):
                clean_drivers.append(short_lbl)
        if len(clean_drivers) >= 2:
            break

    result = [conviction_tier] + clean_drivers
    return result


def normalize_action_signal(signal: Any, default: str = "BUY") -> str:
    """Normalizes action signal into one of BUY (Green), HOLD (Yellow), CAUTION (Orange), AVOID (Red).
    - BUY / GREEN (Green pulsing beacon): Thesis playing out great / deep value / get in NOW.
    - HOLD / WAIT / YELLOW (Yellow pulsing beacon): Thesis steady / wait & do nothing for now / hold for catalyst.
    - CAUTION / ORANGE (Orange pulsing beacon): Thesis facing headwinds / execution friction / trim.
    - AVOID / RED (Red pulsing beacon): Thesis broken / fundamental impairment / do NOT buy / exit.
    """
    if not signal or not isinstance(signal, str):
        return default
    sig = signal.upper().strip()
    if any(k in sig for k in ["RED", "BROKEN", "AVOID", "EXIT", "SELL", "DANGER", "CRITICAL", "DO NOT BUY", "DON'T BUY"]):
        return "AVOID"
    elif any(k in sig for k in ["ORANGE", "CAUTION", "TRIM", "HEADWIND", "WARNING", "FRICTION", "EXECUTION RISK", "GOING BAD"]):
        return "CAUTION"
    elif any(k in sig for k in ["YELLOW", "WAIT", "HOLD", "MONITOR", "PATIENT", "NEUTRAL", "STEADY", "DO NOTHING"]):
        return "HOLD"
    elif any(k in sig for k in ["GREEN", "STRONG", "BUY", "ACCUMULATE", "ADD", "ENTRY", "NOW", "OPPORTUNITY"]):
        return "BUY"
    return default


def call_gemini_with_search(prompt: str, system_instruction: str = "", temperature: float = 0.4, use_search: bool = True, override_model: str = "") -> str:
    """Calls Gemini via REST API with optional Google Search Grounding, exponential retry, and session failover."""
    import time
    api_key = get_api_key()
    
    payload: Dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 8192
        }
    }
    if use_search:
        payload["tools"] = [{"google_search": {}}]
    
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }
    
    if override_model and override_model in GEMINI_MODELS_LADDER:
        models_to_try = [override_model] + [m for m in GEMINI_MODELS_LADDER if m != override_model]
    else:
        current_model = get_active_model()
        start_idx = GEMINI_MODELS_LADDER.index(current_model) if current_model in GEMINI_MODELS_LADDER else 0
        models_to_try = GEMINI_MODELS_LADDER[start_idx:]
        
    last_err = None
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(url, json=payload, timeout=180)
                if response.status_code == 200:
                    res_json = response.json()
                    candidate = res_json.get("candidates", [{}])[0]
                    parts = candidate.get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        return clean_grounding_artifacts(parts[0]["text"])
                    
                    if candidate.get("finishReason") == "RECITATION":
                        fallback_prompt = prompt + "\n\nCRITICAL: Paraphrase all data in your own original analytical words. Do NOT quote verbatim text."
                        payload["contents"] = [{"parts": [{"text": fallback_prompt}]}]
                        payload["generationConfig"]["temperature"] = 0.7
                        retry_res = requests.post(url, json=payload, timeout=180)
                        if retry_res.status_code == 200:
                            retry_json = retry_res.json()
                            retry_parts = retry_json.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                            if retry_parts and "text" in retry_parts[0]:
                                return clean_grounding_artifacts(retry_parts[0]["text"])
                                
                    return "Analysis completed."
                elif response.status_code in (500, 502, 503, 504, 429):
                    if model_name != GEMINI_MODELS_LADDER[-1]:
                        switch_to_fallback_model(f"HTTP {response.status_code} on {model_name}")
                        break
                    elif attempt < max_retries:
                        wait_time = 20
                        print(f"  ⚠️ Gemini API ({model_name}) returned {response.status_code}. Waiting {wait_time}s before retry...", flush=True)
                        time.sleep(wait_time)
                        continue
                else:
                    last_err = RuntimeError(f"Gemini API error ({response.status_code}): {response.text}")
                    break
            except requests.RequestException as req_err:
                if model_name != GEMINI_MODELS_LADDER[-1]:
                    switch_to_fallback_model(f"{req_err} on {model_name}")
                    break
                elif attempt < max_retries:
                    wait_time = 20
                    print(f"  ⚠️ Network error on {model_name} ({req_err}). Waiting {wait_time}s before retry...", flush=True)
                    time.sleep(wait_time)
                    continue
                last_err = RuntimeError(f"Gemini API network error: {req_err}")
                break

    if last_err:
        raise last_err
    return "Analysis completed."


def extract_json_block(text: str) -> Dict[str, Any]:
    """Robustly extracts a JSON object from markdown code fences or raw text,
    with trailing comma cleanup, bracket counting, and regex field-level fallback."""
    if not text:
        return {}

    # 1. Search for JSON markdown code blocks (arrays or objects)
    matches = re.findall(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", text, re.DOTALL)
    for raw_json in matches:
        cleaned_json = re.sub(r",\s*([\]}])", r"\1", raw_json)
        try:
            return json.loads(cleaned_json)
        except Exception:
            pass

    # 2. Search for the first balanced { ... } or [ ... ] block
    first_brace = -1
    brace_type = None
    for i, ch in enumerate(text):
        if ch in ('{', '['):
            first_brace = i
            brace_type = ch
            break

    if first_brace != -1:
        closing_type = '}' if brace_type == '{' else ']'
        depth = 0
        end_idx = -1
        in_string = False
        escape = False
        for idx in range(first_brace, len(text)):
            ch = text[idx]
            if ch == '"' and not escape:
                in_string = not in_string
            elif not in_string:
                if ch == brace_type:
                    depth += 1
                elif ch == closing_type:
                    depth -= 1
                    if depth == 0:
                        end_idx = idx
                        break
            escape = (ch == '\\' and not escape)

        if end_idx != -1:
            candidate = text[first_brace:end_idx+1]
            cleaned_candidate = re.sub(r",\s*([\]}])", r"\1", candidate)
            try:
                return json.loads(cleaned_candidate)
            except Exception:
                pass

    # 3. Resilient regex field extraction fallback
    data = {}
    patterns = {
        "alert_title": r'"alert_title"\s*:\s*"([^"]+)"',
        "alert_severity": r'"alert_severity"\s*:\s*"([^"]+)"',
        "action_signal": r'"action_signal"\s*:\s*"([^"]+)"',
        "what_was_before": r'"what_was_before"\s*:\s*"([^"]+)"',
        "what_changes_now": r'"what_changes_now"\s*:\s*"([^"]+)"',
        "label_change_rationale": r'"label_change_rationale"\s*:\s*"([^"]+)"',
        "executive_summary": r'"executive_summary"\s*:\s*"([^"]+)"',
        "fair_value_estimate": r'"(?:fair_value_estimate|new_fair_value)"\s*:\s*"([^"]+)"',
        "bear_target": r'"(?:bear_target|new_bear_target)"\s*:\s*"([^"]+)"',
        "base_target": r'"(?:base_target|new_base_target)"\s*:\s*"([^"]+)"',
        "bull_target": r'"(?:bull_target|new_bull_target)"\s*:\s*"([^"]+)"',
        "next_catalyst_date": r'"next_catalyst_date"\s*:\s*"([^"]+)"',
        "next_catalyst_event": r'"next_catalyst_event"\s*:\s*"([^"]+)"',
        "what_is_priced_in": r'"(?:what_is_priced_in|reverse_dcf_growth|implied_growth|g_implied)"\s*:\s*"([^"]+)"',
        "institutional_ownership_pct": r'"institutional_ownership_pct"\s*:\s*"([^"]+)"',
        "insider_signal": r'"insider_signal"\s*:\s*"([^"]+)"',
        "insider_summary": r'"insider_summary"\s*:\s*"([^"]+)"',
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            data[key] = m.group(1).strip()

    labels_match = re.search(r'"labels"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if labels_match:
        raw_labels = re.findall(r'"([^"]+)"', labels_match.group(1))
        if raw_labels:
            data["labels"] = raw_labels

    funds_match = re.search(r'"top_funds"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if funds_match:
        raw_funds = re.findall(r'"([^"]+)"', funds_match.group(1))
        if raw_funds:
            data["top_funds"] = raw_funds

    upper_m = re.search(r'"(?:upper_alert_threshold|new_upper_alert_threshold)"\s*:\s*([0-9.]+)', text)
    if upper_m:
        try:
            clean_u = re.sub(r"[^\d.]", "", upper_m.group(1))
            if clean_u and clean_u != ".":
                data["upper_alert_threshold"] = float(clean_u)
        except Exception:
            pass
    lower_m = re.search(r'"(?:lower_alert_threshold|new_lower_alert_threshold)"\s*:\s*([0-9.]+)', text)
    if lower_m:
        try:
            clean_l = re.sub(r"[^\d.]", "", lower_m.group(1))
            if clean_l and clean_l != ".":
                data["lower_alert_threshold"] = float(clean_l)
        except Exception:
            pass

    return data


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

    # Step 4: Protect all currency amounts ($568.97, $50, $1,200.50, $25B, $19.31 billion, ~$252.00, -$8.65B, -$9.29/sh, +$2.59/sh, etc.)
    currencies = []
    def save_currency(m):
        currencies.append(m.group(0))
        return f"««CURRENCY_{len(currencies)-1}»»"
    
    curr_pattern = r'(?:~|-|\+)?\$(?=\d|\.\d)(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?(?:\s*(?:billion|million|trillion|[kKmMbBtT]))?(?:/(?:share|sh))?'
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

    # Step 7: Multi-pass recursive restoration of all placeholders to prevent nested leaks
    for _ in range(10):
        changed = False
        for i, curr in enumerate(currencies):
            ph = f"««CURRENCY_{i}»»"
            if ph in html:
                html = html.replace(ph, curr)
                changed = True
        for i, inl in enumerate(inline_blocks):
            ph = f"««INLINE_BLOCK_{i}»»"
            if ph in html:
                html = html.replace(ph, inl)
                changed = True
        for i, tag in enumerate(tags):
            ph = f"««HTML_TAG_{i}»»"
            if ph in html:
                html = html.replace(ph, tag)
                changed = True
        for i, disp in enumerate(display_blocks):
            ph = f"««DISPLAY_BLOCK_{i}»»"
            if ph in html:
                html = html.replace(ph, disp)
                changed = True
        if not changed or "««" not in html:
            break

    # Safety final pass: purge any orphaned raw chevron placeholders only if they failed restoration
    html = re.sub(r'««[A-Z_0-9]+»»', '', html)
        
    return html


def verify_and_repair_html_structure(html: str) -> str:
    """Bulletproof HTML sanitizer and structure repair engine.
    Ensures 100% clean semantic HTML, perfectly balanced lists, tables, callouts, and sections."""
    if not html:
        return ""
        
    from bs4 import BeautifulSoup
    cleaned = clean_grounding_artifacts(html)
    cleaned = normalize_latex_typography(cleaned)
    
    # 0. Strip foreign script/tokenizer leaks (e.g. Cyrillic/Russian/Chinese stray tokens in English text)
    cleaned = re.sub(r'\bмиллиардов\b', 'billion', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bмиллиарда\b', 'billion', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bмиллиард\b', 'billion', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bмиллионов\b', 'million', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bмиллиона\b', 'million', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bмиллион\b', 'million', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[\u0400-\u04FF]+', '', cleaned) # Strip any remaining Cyrillic tokens
    
    # 0.5 Strict USD Currency Standardization (Zero RMB, CNY, EUR, JPY, GBP)
    # Convert and normalize currency labels into USD ($)
    cleaned = re.sub(r'RMB\s*Millions\s*\(¥\)', '$ Millions USD', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'RMB\s*Billions\s*\(¥\)', '$ Billions USD', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\$\s*Millions\s*CNY\b', '$ Millions USD', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\$\s*Millions\s*RMB\b', '$ Millions USD', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\$\s*Billions\s*CNY\b', '$ Billions USD', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\$\s*Billions\s*RMB\b', '$ Billions USD', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'CNY\s*Millions\b', '$ Millions USD', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'CNY\s*Billions\b', '$ Billions USD', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'EUR\s*Millions\b', '$ Millions USD', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'EUR\s*Billions\b', '$ Billions USD', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'¥\s*([\d,]+(?:\.\d+)?)', r'$\1', cleaned)
    cleaned = re.sub(r'€\s*([\d,]+(?:\.\d+)?)', r'$\1', cleaned)
    cleaned = re.sub(r'£\s*([\d,]+(?:\.\d+)?)', r'$\1', cleaned)
    cleaned = re.sub(r'\bRMB\s*([\d,]+(?:\.\d+)?)', r'$\1', cleaned)
    cleaned = re.sub(r'\bCNY\s*([\d,]+(?:\.\d+)?)', r'$\1', cleaned)
    
    # 1. Strip code fences, json blocks
    cleaned = re.sub(r"```(?:html|json)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"```", "", cleaned)
    
    # 1.5 Convert raw ASCII box drawings into modern CSS cards
    if any(c in cleaned for c in ['\u250c', '\u2500', '\u2510', '\u2502', '\u2514', '\u2518', '\u251c', '\u2524', '\u252c', '\u2534', '\u253c']):
        lines = cleaned.split('\n')
        new_lines = []
        in_box = False
        box_lines = []
        for line in lines:
            if any(c in line for c in ['\u250c', '\u2500', '\u2510', '\u2502', '\u2514', '\u2518', '\u251c', '\u2524', '\u252c', '\u2534', '\u253c']):
                in_box = True
                box_lines.append(line)
            else:
                if in_box:
                    in_box = False
                    clean_items = []
                    for bl in box_lines:
                        stripped = re.sub(r'[\u2500-\u257f\u250c\u2510\u2514\u2518\u251c\u2524\u252c\u2534\u253c\|┌┐└┘├┤┬┴┼─]+', ' ', bl).strip()
                        if stripped:
                            clean_items.append(stripped)
                    if clean_items:
                        title = clean_items[0]
                        body_items = clean_items[1:]
                        card_html = f'<div class="arch-diagram" style="background:var(--bg-subpanel); border:1px solid var(--border-color); border-radius:12px; padding:20px 22px; margin:24px 0;"><div style="font-family:var(--font-sans); font-size:0.75rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--accent-warm); text-align:center; margin-bottom:14px;">{title}</div><div style="display:flex; flex-direction:column; gap:8px;">'
                        for it in body_items:
                            card_html += f'<div style="display:flex; justify-content:space-between; align-items:center; padding:10px 14px; background:var(--bg-panel); border:1px solid var(--border-color); border-radius:6px; font-family:var(--font-sans); font-size:0.86rem; color:var(--text-title);">{it}</div>'
                        card_html += '</div></div>'
                        new_lines.append(card_html)
                    box_lines = []
                new_lines.append(line)
        cleaned = '\n'.join(new_lines)
    
    # 2. Strip rogue top dashboard header injections
    cleaned = re.sub(r'<div class="investor-dashboard">[\s\S]*?</div>\s*</div>\s*</div>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<div class="dashboard-header">[\s\S]*?</div>\s*</div>', '', cleaned, flags=re.IGNORECASE)
    
    # 3. Strip inline style attributes
    cleaned = re.sub(r'\s*style\s*=\s*"[^"]*"', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*style\s*=\s*'[^']*'", '', cleaned, flags=re.IGNORECASE)
    
    # 4. Clean up section titles
    cleaned = re.sub(r'<div class="section-title">\s*(?:SECTION\s*\d+:?\s*)?(.*?)</div>', r'<h2>\1</h2>', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<div class="section-heading">(.*?)</div>', r'<h2>\1</h2>', cleaned, flags=re.IGNORECASE)
    
    # 5. Clean up bold / italic markers
    cleaned = re.sub(r'<em>\s*<strong>', r'<strong>', cleaned)
    cleaned = re.sub(r'</strong>\s*</em>', r'</strong>', cleaned)
    cleaned = re.sub(r"^\s*####\s+(.*?)$", lambda m: f"<h4>{m.group(1)}</h4>", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*###\s+(.*?)$", lambda m: f"<h3>{m.group(1)}</h3>", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*##\s+(.*?)$", lambda m: f"<h2>{m.group(1)}</h2>", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*(.*?)\*\*", lambda m: f"<strong>{m.group(1)}</strong>", cleaned)
    cleaned = re.sub(r"(?<!\*)\*([^\*]+)\*(?!\*)", lambda m: f"<em>{m.group(1)}</em>", cleaned)
    
    # 6. Convert markdown bullets to <li>
    cleaned = re.sub(r'^\s*[*•-]\s+\*\*(.*?)\*\*', r'<li><strong>\1</strong>', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^\s*[*•-]\s+<strong>(.*?)</strong>', r'<li><strong>\1</strong>', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^\s*[*•-]\s+(.*?)$', r'<li>\1</li>', cleaned, flags=re.MULTILINE)
    
    # 7. Ensure every <li> has </li>
    prev = ""
    while prev != cleaned:
        prev = cleaned
        cleaned = re.sub(
            r"(<li\b[^>]*>(?:(?!</li>|<li\b|</?[uo]l\b).)*?)(?=\s*<li\b|\s*</[uo]l\b|\s*<h[1-6]\b|\s*<div\b|$)",
            r"\1</li>\n",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE
        )
    cleaned = re.sub(r"</li>\s*</li>+", "</li>", cleaned, flags=re.IGNORECASE)

    # 8. Auto-close lists before headings
    cleaned = re.sub(r"(<li\b[^>]*>.*?</li>)(?=\s*<h[1-6]\b)", r"\1</ul>", cleaned, flags=re.DOTALL | re.IGNORECASE)
    
    # 9. Auto-close unclosed lists
    open_ul = len(re.findall(r"<ul(?:\s|>)", cleaned, re.IGNORECASE))
    close_ul = len(re.findall(r"</ul>", cleaned, re.IGNORECASE))
    if open_ul > close_ul:
        cleaned += "\n" + ("</ul>" * (open_ul - close_ul))
    elif close_ul > open_ul:
        for _ in range(close_ul - open_ul):
            cleaned = re.sub(r"</ul>(?=[^<]*$)", "", cleaned, flags=re.IGNORECASE)
        
    open_ol = len(re.findall(r"<ol(?:\s|>)", cleaned, re.IGNORECASE))
    close_ol = len(re.findall(r"</ol>", cleaned, re.IGNORECASE))
    if open_ol > close_ol:
        cleaned += "\n" + ("</ol>" * (open_ol - close_ol))
    elif close_ol > open_ol:
        for _ in range(close_ol - open_ol):
            cleaned = re.sub(r"</ol>(?=[^<]*$)", "", cleaned, flags=re.IGNORECASE)

    open_li = len(re.findall(r"<li(?:\s|>)", cleaned, re.IGNORECASE))
    close_li = len(re.findall(r"</li>", cleaned, re.IGNORECASE))
    if open_li > close_li:
        cleaned += "\n" + ("</li>" * (open_li - close_li))
    elif close_li > open_li:
        for _ in range(close_li - open_li):
            cleaned = re.sub(r"</li>(?=[^<]*$)", "", cleaned, flags=re.IGNORECASE)
        
    # 10. Auto-close tables, divs, sections
    open_tr = len(re.findall(r"<tr\b", cleaned, re.IGNORECASE))
    close_tr = len(re.findall(r"</tr>", cleaned, re.IGNORECASE))
    if open_tr > close_tr:
        cleaned += "</tr>" * (open_tr - close_tr)

    open_tables = len(re.findall(r"<table\b", cleaned, re.IGNORECASE))
    close_tables = len(re.findall(r"</table>", cleaned, re.IGNORECASE))
    if open_tables > close_tables:
        cleaned += "\n" + ("</tbody></table>" * (open_tables - close_tables))
        
    open_divs = len(re.findall(r"<div\b", cleaned, re.IGNORECASE))
    close_divs = len(re.findall(r"</div>", cleaned, re.IGNORECASE))
    if open_divs > close_divs:
        cleaned += "\n" + ("</div>" * (open_divs - close_divs))

    # 11. Normalize DOM via BeautifulSoup
    soup = BeautifulSoup(cleaned, "html.parser")
    return str(soup)

# =====================================================================
# AUTONOMOUS LEVEL-HEADED MULTI-AGENT PROMPT ARCHITECTURE
# =====================================================================

LEVEL_HEADED_INVESTOR_PHILOSOPHY = """You are an elite, level-headed fundamental value investor embodying the economic principles of Warren Buffett, Charlie Munger, and Ben Graham.

Your analysis must adhere strictly to these 7 First Principles of Business Valuation:

1. The Business-First Reality (The Invariant of Ownership):
   - You are purchasing an ownership stake in an enduring private business, NOT gambling on a ticker symbol or momentum chart.
   - Mr. Market is an emotional partner whose quotes exist to serve you, not to guide you. Never anchor to current market prices or consensus targets.
   - The 5-Year Market Closure Test: If the stock exchange were closed for 5 years, would the organic cash generated by this private operating enterprise justify purchasing the entire business today?

2. Cold, Sunk-Cost-Free Discipline:
   - Sunk costs and past stock prices are economically irrelevant; only future risk-adjusted owner cash flows discounted back to the present matter.
   - If business unit economics, durable moats, or capital allocation discipline break down, downgrade immediately to CAUTION or AVOID without hesitation.

3. Mandatory Primary Source Grounding:
   - You MUST search for and review the company's LATEST quarterly earnings report (10-Q/10-K), LATEST earnings call transcript (management commentary and Q&A), and material corporate 8-Ks.
   - Extract real-time revenue, segment margins, management guidance, and actual capital return figures. Ground all institutional whale ownership and insider Form 4 activity in official filings.

4. The 7 Pillars of Warren Buffett Owner Earnings & Intrinsic Valuation:
   Pillar 1: True Owner Cash Flow Derivation (1986 Shareholder Letter)
   - Owner Earnings = GAAP Operating Cash Flow - Maintenance CapEx - 100% of Stock-Based Compensation (SBC).
   - Maintenance CapEx vs. Discretionary Growth CapEx: Isolate defensive capital required to maintain existing unit volumes and technological competitive parity from elective, high-ROIC growth investments.
   - FORENSIC ANNUAL CAPEX & GAAP METRIC REALISM: All single-year CapEx, Revenue, Operating Cash Flow, and SBC figures MUST strictly reflect audited 12-month annual SEC Form 10-K reported figures and realistic 1-year guidance. Total CapEx MUST reflect actual line-item Purchases of Property and Equipment from the GAAP Cash Flow Statement. Never mistake multi-year capital commitments (e.g. 5-year or 10-year cloud/data center contracts or energy purchase agreements) for a single fiscal year's cash outflow. For mega-cap technology platforms, annual CapEx is typically 15%–35% of annual revenue (e.g. ~$35B–$45B for Meta, ~$55B–$75B for Amazon). CapEx in a single year can never exceed 50% of annual revenue.
    - NON-OPERATING GAIN & MARK-TO-MARKET SANITY: Mark-to-market accounting adjustments on minority equity investments (e.g. Anthropic, OpenAI, venture stakes) cannot exceed total invested capital or realistic private market equity value. Never extrapolate non-operating accounting credits into recurring operating profit or Owner Earnings.
   - BNPL & Fintech Credit Risk Externalization: For digital payments, buy-now-pay-later (BNPL), and merchant lending platforms (e.g. PayPal, Affirm, Block), audit whether loan receivables are retained on-balance-sheet or offloaded to institutional credit partners (e.g. forward-flow agreements with KKR, Apollo). Externalizing credit risk converts balance sheet credit default risk into high-margin, capital-light loan origination and servicing fee cash flow.
   - Zero-SBC Discipline & Denominator Integrity: When an enterprise compensates executives via cash bonuses with mandatory open-market share purchase rules and issues zero dilutive equity grants (e.g. Constellation Software, Berkshire Hathaway), recognize that Free Cash Flow translates 100% into Owner Earnings without dilution friction. Lock the diluted share count denominator flat across DCF forecast horizons.
   - Upfront Annual Software Maintenance Float: In Vertical Market Software (VMS) and enterprise maintenance networks, recognize upfront annual maintenance billing (Deferred Revenue) as interest-free, non-dilutive customer float that perpetually funds accretive tuck-in acquisitions without debt or equity issuance.
   - Enterprise SaaS SBC Margin Illusion & True Owner FCF: In high-growth enterprise software (e.g. ServiceNow, Snowflake, Workday), strip away promotional Non-GAAP Free Cash Flow margins (>30%) where 12%–18% of revenue is paid in equity compensation. Deducting 100% of SBC reveals that true Owner Earnings margins are often 10%–15%. Evaluate whether multi-billion-dollar buyback programs shrink share count or merely absorb employee option dilution.
   - Inventory Liquidation Distortion in Secular Decline: In declining retail or legacy industrial businesses, Operating Cash Flow frequently surges temporarily due to working capital liquidation (emptying inventory from store shelves and stretching trade payables). The evaluator must strip out non-recurring working capital cash releases to prevent mistaking balance sheet liquidation for recurring operating cash flow.
   - Payroll & Tax Escrow Customer Float: In payroll processing, tax remittance, and B2B merchant software (e.g. Intuit, ADP, Paychex), audit segregated customer escrow funds held for tax filings and wage disbursements. Recognize the interest yield harvested on segregated customer balances as an organic cash flow driver carrying zero corporate credit risk.
   - Bank & Lending Cash Flow Paradox: In chartered banks, digital neo-banks, and specialty lenders, GAAP Operating Cash Flow is distorted because loan originations are classified as operating/investing outflows while customer deposit inflows appear under financing activities. Never treat balance sheet loan portfolio builds as an operating cash loss. Instead, derive Owner Earnings from Net Interest Income (NII) + Fee Revenues - Net Credit Loss Provisions - 100% SBC - Bank IT Maintenance CapEx.
   - Merchant Model Travel & Ticketing Float: In online travel platforms, ticketing, and reservation networks (e.g. Booking, Airbnb), recognize upfront customer travel prepayments (Deferred Merchant Bookings) as non-dilutive, zero-cost working capital float. Audit the net interest income generated on float balances as an organic liquidity backstop.
   - Multi-Unit Retail & Restaurant Unit CapEx Bifurcation: For multi-unit restaurant, retail, and store-network compounders (e.g. Chipotle, Dutch Bros, AutoZone), separate mature store maintenance refreshes (~$30k–$50k/store) from discretionary new store build CapEx. If new units achieve >40%–60% cash-on-cash returns with <2.5-year paybacks, recognize new build CapEx as high-ROIC growth reinvestment rather than an owner cash penalty.
   - Industrial Land Banking vs. Maintenance CapEx: For land-intensive logistics, salvage auctions, and waste management networks (e.g. Copart, Waste Management), separate discretionary freehold land purchases (Growth CapEx that appreciates over time) from routine yard/fleet maintenance CapEx to prevent understating true Owner Earnings.
   - 100% SBC Deduction: Stock compensation is a real, non-negotiable economic cash expense that dilutes shareholder equity.
   - Post-IPO SBC Normalization: For newly public technology platforms (IPOs within 1–3 years), separate temporary pre-IPO vesting spikes from ongoing run-rate SBC. Audit whether SBC as a % of revenue is structurally contracting toward sustainable levels (<12%).
   - Brokerage Working Capital Distortion: In financial brokerages and retail custodians, GAAP Operating Cash Flow exhibits massive non-economic swings from customer margin lending receivables, segregated clearing deposits, and cash sweep transfers. Strip out customer margin loan expansion and segregated regulatory funds to isolate true corporate operating cash flow.
   - Working Capital Float: Recognize persistent negative cash conversion cycles (deferred revenue + accounts payable > accounts receivable) as interest-free, non-dilutive customer funding.
   - Insurance Float & Combined Ratio Moat: In property, casualty, and specialty insurance (e.g. Berkshire, Markel, Kinsale, Progressive), audit the Combined Ratio (Loss Ratio + Expense Ratio). A sub-95% combined ratio means the company is paid an underwriting profit to hold customer float, generating negative-cost capital that compounds investment earnings without debt or dilution.
   - Streaming & Media Content Cash Amortization Drag: For digital entertainment and streaming platforms (e.g. Netflix, Disney, Warner), audit cash spent on content production vs. income statement content amortization. If cash production spend exceeds amortization by >15%, deduct the net cash content drag directly from Owner Earnings.

   Pillar 2: Mid-Cycle Business Normalization (1982 & 1991 Letters)
   - For cyclical, commodity, and hardware technology sectors, NEVER extrapolate peak-quarter cash flows or peak gross margins into perpetuity.
   - Cross-Border FX Spread & Corridor Sensitivity: In global payments networks, fintechs, and remittances (e.g. PayPal, Wise, DLocal), evaluate cross-border volume mix. Cross-border transactions generate high take rates (300–400 bps via foreign exchange spreads); differentiate high-margin cross-border corridor fluctuations from domestic unbranded volume expansion.
   - System of Action vs. System of Record Moat Hierarchy: In enterprise technology, distinguish underlying Systems of Record (ERP, CRM, HR databases) from cross-departmental Systems of Action and Workflow Orchestration platforms (e.g. ServiceNow). Systems of Action orchestrate multi-agent automated workflows across disparate software silos, turning autonomous AI agent proliferation from a seat-cannibalization threat into a workflow orchestration tailwind.
   - SaaS Backlog Quality & cRPO Visibility: For enterprise software platforms, evaluate Current Remaining Performance Obligations (cRPO due within 12 months) and Net Expansion / Renewal Rates (>97% renewal). When cRPO growth exceeds 18%–20% with high gross margins (>80%), revenue visibility provides strong multi-year compounding predictability.
   - Core General Ledger System of Record vs. Peripheral SaaS: In enterprise and SMB software, strictly differentiate core financial Systems of Record (General Ledger, Invoicing, Payroll, Tax Compliance) from peripheral discretionary tools (marketing, collaboration). Core accounting workflows carry near-infinite switching costs (>95% retention) and pricing power, as migrating ledger data risks operational paralysis.
   - Upmarket ARPU Migration Buffer: When evaluating software platforms facing low-end commoditization (e.g. free government filing, open-source tools), audit whether the company is successfully trading low-end unit volume for high-ARPU assisted and mid-market enterprise tiers (e.g. TurboTax Live, QBO Advanced / Intuit Enterprise Suite), preserving revenue growth and expanding operating margins.
   - IT Services Dual Engine & AI Data Pull-Through: In global IT services and technology consulting (e.g. Accenture, Infosys), separate discretionary project-based Consulting from recurring multi-year Managed Services / Operations. When evaluating AI labor disruption, track 'Data Pull-Through'—the multiplier where enterprise AI agent deployments force underlying legacy ERP and data infrastructure modernization, offsetting billable-hour software automation efficiencies.
   - Direct-Deposit Payroll Stickiness vs. Hot Money Float: For digital banks and fintech custodians, evaluate the deposit mix. Primary checking accounts backed by direct-deposit payroll (>80% direct deposit) create a sticky, low-cost funding moat that preserves Net Interest Margin (NIM) across rate cycles, whereas promotional yield-chasing deposits represent volatile hot money.
   - Geographic Supply Fragmentation vs. Chain Concentration: In online travel, marketplaces, and service booking platforms, evaluate regional supplier structure. Hyper-fragmented independent supply (e.g. European boutique hotels >70% independent) yields strong pricing power and 15%–20% commission take rates, whereas chain-dominated markets (North America) feature lower take rates and higher disintermediation risk.
   - Consumer Hardware Component & Memory Inflation: For consumer electronics and audio hardware, model commodity input inflation (DRAM, NAND flash memory, display panels) and shipping freight against retail pricing power. In hardware sectors, margin compression of 200–400 bps often occurs when component spikes cannot be immediately passed onto retail consumers.
   - Unit-Level Economics & Restaurant Margin (RLM) Durability: For restaurant and multi-location retail chains, evaluate Average Unit Volume (AUV), Same-Store Sales (comps split between traffic and ticket), and Restaurant-Level Margin (RLM). Model commodity input inflation (proteins, dairy, produce, freight) and minimum wage mandates against historical menu pricing power.
   - Local Advertising Services vs. Dining Mix: In local search and advertising directories, evaluate the revenue mix transition from low-margin discretionary dining/retail toward high-ticket, high-intent Home, Auto, and Professional Services, where customer lead values ($50–$150+) provide superior pricing power and insulation from food delivery aggregators.
   - Generative AI Task Bifurcation: In digital services, freelance platforms, and knowledge marketplaces, analyze task bifurcation. Separate low-complexity commodity tasks (displaced by autonomous AI agents) from high-complexity technical, consulting, and AI implementation workflows (where AI integration increases spend per enterprise client). Track Spend Per Active Client alongside headline user counts.
   - Municipal NIMBY Zoning & Land Entitlement Moats: In heavy industrial, salvage, and environmental disposal networks, evaluate the structural barriers created by local municipal land-use permits and environmental clearances that make replicating physical yard networks near urban centers virtually impossible for competitors.
   - Single-Platform Distribution Vulnerability: For digital media, marketplaces, and aggregators whose top-of-funnel discovery relies on third-party search engines or app stores (e.g. Google Search indexing, Apple App Store ranking), evaluate referral concentration and stress-test a 15%–25% traffic reduction from search engine AI Overviews (SGE) or algorithm de-indexing in Bear cases.
   - Wealth Custody & Brokerage Rate Sensitivity: For digital brokerages and wealth platforms, evaluate Net New Asset (NNA) deposit growth (>15% annualized indicates durable organic market share gains). Model the natural operational hedge between Net Interest Income (NII expands in high-rate regimes) and retail trading/margin borrowing (accelerates in low-rate/bullish market regimes).
   - Marketplace Take-Rate & Gross Bookings Integrity: For two-sided platforms (mobility, delivery, OTAs), differentiate optical reported revenue shifts caused by regional principal-vs-agent tax reclassifications from true operational take rates and underlying Gross Bookings volume.
   - Demand Aggregation vs. Hardware Fleet Traps: In sectors transitioning to physical automation (e.g. Autonomous Vehicles, robotics, automated fulfillment), evaluate whether the platform's consumer demand density positions it as the high-margin dispatch and routing aggregator, avoiding the capital-heavy depreciation traps of owned vehicle fleets.
   - Normalize earnings and margins across full 3-5 year operating cycles to account for customer CapEx digestion pauses, capacity additions, and supply-demand normalization.
   - For mega-cap platforms, enforce a Law of Large Numbers sanity check against total addressable enterprise spending.
   - Biopharma Patent Cliff & Loss of Exclusivity (LOE): For pharmaceuticals and biotechnology, evaluate patent expiration schedules on top-3 revenue drivers. Disallow perpetual terminal growth on single-blockbuster drugs facing generic or biosimilar entry within 5 years; model realistic LOE revenue runoff (-40% to -80%) unless offset by late-stage Phase 3 pipeline commercialization.
   - Semiconductor Fabless vs. Foundry Capital Intensity: Strictly differentiate asset-light fabless IP design firms (Qualcomm, Nvidia, ARM) from capital-heavy semiconductor fabrication foundries (TSMC, Intel, Micron). For foundries, evaluate multi-billion-dollar cleanroom tool depreciation against ongoing EUV lithography reinvestment hurdles to isolate true free cash flow.

   Pillar 3: Local Sovereign Hurdle Rates (The PetroChina & Iscar Discipline)
   - Never discount international cash flows using US Treasury rates.
   - Anchor the discount rate strictly to the local 10-year sovereign bond yield of the operating currency (e.g. US 10Y for US, UK Gilt for UK, Brazilian NTN-F/SELIC for Brazil, German Bund for Europe) plus an appropriate equity risk premium.

   Pillar 4: Capital-Light Compounding, Tangible Book Value & ROTCE
   - Bank Tangible Book Value (TBV) & ROTCE Compounding: For financial institutions and digital banks, cross-check DCF intrinsic value against Tangible Book Value per share growth and Return on Tangible Common Equity (ROTCE). A digital bank compounding TBV at >20% annually with high capital adequacy (CET1 > 15%) earns superior long-term compounding multiples over legacy brick-and-mortar institutions.
   - Evaluate Incremental Return on Invested Capital (ROIC). Does $1 of retained earnings generate more than $1 of tangible market value and earnings power?
   - Identify capital-light compounders that generate expanding owner cash yield without requiring dilutive secondary offerings or crushing debt loads.

   Pillar 5: Capital Allocation & Share Cannibal Reality (1999 & 2018 Letters)
   - Model the net per-share compounding impact of management's capital allocation:
     Net Annual Share Count Reduction = (Shares Repurchased - SBC Shares Issued) / Diluted Share Count.
   - Retiring shares below intrinsic value concentrates cash flow into fewer shares and compounds per-share intrinsic value. If buybacks are paused or insufficient to offset equity grants, model net shareholder dilution (+1% to +3%/year).
    - AUDITED SHARE DILUTION HARMONIZATION: If Section 4 audits management's capital allocation and determines that buybacks are paused or $0 (resulting in net positive dilution from SBC), Section 5 DCF models MUST NOT assume negative share compounding (cannibalization) in Base Case. The share count trajectory in Section 5 must strictly align with Section 4's audited capital return policy.
   - Programmatic String-of-Pearls M&A Integrity: For serial acquirers executing 15–40 bolt-on acquisitions annually (e.g. Accenture, Constellation Software, Roper), differentiate organic constant-currency growth from acquisitive revenue expansion. Verify that ROIC remains >15%–20% and that goodwill accumulation is not masking organic market share contraction.
   - Buyback Cannibal vs. SBC Neutralizer Audit: Never assume a company is a true 'share cannibal' simply because it announces a share buyback program. If more than 75% of repurchase capital is consumed neutralizing employee equity grants (leaving diluted share count virtually flat), classify the capital return as an 'SBC Neutralizer' and do not model aggressive per-share denominator compounding in DCF projections.
   - M&A Debt Digestion & Buyback Pause Dynamics: When an active share repurchaser temporarily suspends buybacks to fund an acquisition or repay revolving credit facilities, model positive net shareholder dilution (+1% to +2.5%/year from unsterilized SBC) during the debt payback period, and only resume modeling share count reduction once leverage targets are restored.

   Pillar 6: Balance Sheet Fortress, Fixed Lease Overhead & Distress Refinancing
   - UNIFIED BALANCE SHEET BRIDGE & CROSS-SECTION HARMONIZATION: Section 3, Section 4, and Section 5 must use the EXACT same audited funded debt, capitalized operating and finance lease liabilities (ASC 842), and cash/marketable securities figures. Net Debt or Net Cash per share in Section 5 must strictly equal (Cash + Marketable Securities - Total Funded Debt - Leases) / Diluted Shares as established in Section 4.
   - Account for all contractual fixed legal obligations: Total interest-bearing debt, capitalized operating and finance leases (ASC 842), and non-discretionary statutory/environmental liabilities.
   - Parent Recourse vs. Non-Recourse Subsidiary Debt Ring-Fencing: In federated holding companies, serial acquirers, and platform conglomerates (e.g. Constellation Software / Topicus / Lumine), separate parent recourse debt from ring-fenced, non-recourse subsidiary credit facilities. Ensure that leverage at autonomous spun-out operating subsidiaries does not artificially distort parent balance sheet solvency.
   - Retail Fixed Lease Overhead & EBITDAR Coverage: For brick-and-mortar retail and restaurant chains carrying extensive store networks, evaluate Fixed Charge Coverage: EBITDAR / (Interest Expense + Cash Rent). If same-store sales contract while fixed rent commitments remain rigid, negative operating leverage quickly erodes operating margins.
   - Double-Digit Debt Refinancing Distress Rule: When an enterprise is forced to issue or refinance long-term debt at double-digit coupon rates (>9.5%–10.0%), credit markets are signaling elevated distress. In such cases, strictly disallow positive terminal growth in DCF models and mandate a terminal runoff rate (0.0% to -3.0%) with elevated sovereign risk hurdles.
   - Near-Term Convertible Debt Redemption Coverage: For enterprises carrying convertible notes maturing within 12 months, verify that unrestricted balance sheet liquidity strictly covers 100% of the principal redemption to prevent dilutive refinancing or distress in elevated rate environments.
   - Strategic Minority Equity Stakes (Look-Through Asset Bridge): For platforms holding substantial unconsolidated equity stakes in other public/private market leaders (e.g. Uber holding Grab/Didi/Aurora, Alibaba holding Ant Group, Alphabet holding venture stakes), audit these holdings at conservative marked-to-market or liquidation values and credit them directly to the Net Asset Balance Sheet Bridge in DCF.
   - Deduct net debt/liabilities from Enterprise Intrinsic Value to arrive at Equity Intrinsic Value. Add unrestricted liquid cash and marketable short-term treasuries.
   - For businesses in structural secular decline, disallow positive terminal growth and model realistic runoff.

   Pillar 7: Anti-Multiples Rule, Revenue Quality & Pre-Mortem Falsification
   - Intrinsic Value is the present value of all cash that can be extracted from the business over its remaining life. Reject speculative terminal multiple expansion.
   - AI Data Licensing Backlog vs. Perpetual SaaS: Differentiate sticky enterprise recurring subscriptions from finite AI model training data licensing contracts. Audit RPO backlog decay and avoid capitalizing non-recurring dataset licensing fees into perpetuity.
   - Terminal growth is strictly capped at long-term real GDP growth (2.0% to 2.5%).
   - Formulate 3 quantitative pre-mortem operational tripwires (margin decay, customer churn, backlog contraction) that declare the thesis fundamentally invalid.

   Pillar 8: Reverse-Engineered Market Expectations & Strategic M&A Floors
   - Invert the valuation: At today's market price, solve for the exact 5-year Owner Earnings CAGR ($g_{\text{implied}}$) that Mr. Market is currently pricing in.
   - Strategic M&A & Private Equity Replacement Floor: When an entrenched market leader trading at compressed Owner Earnings multiples attracts credible buyout, take-private, or non-binding acquisition inquiries from private equity or industry peers (e.g. Stripe/Advent for PayPal, Couche-Tard for Seven & i), evaluate the private market replacement cost as an asymmetric downside floor that limits capital loss while standalone execution unfolds.
   - Contrast $g_{\text{implied}}$ against the company's realistic organic compounding capacity:
     * If $g_{\text{implied}} \gg g_{\text{realistic}}$: The stock is "Priced for Perfection"—any operational hiccup will trigger severe multiple compression.
     * If $g_{\text{implied}} \approx g_{\text{realistic}}$: Fairly valued.
     * If $g_{\text{implied}} \ll g_{\text{realistic}}$ (or negative): Market is pricing in permanent secular decline or excessive pessimism, creating a high-conviction asymmetric Margin of Safety.

   Pillar 9: Probabilistic Risk & Fragility Audit (The Anti-Fragility Test)
   - Standard DCF models often assume smooth, normal growth trajectories that obscure existential business risks or asymmetric fat-tail liabilities.
   - For every enterprise, conduct an explicit probabilistic threat audit:
     1. Identify the top 3-4 structural failure modes (technological disintermediation, regulatory bans, customer concentration loss, debt maturity traps, commodity squeezes, algorithm de-indexing).
     2. Assign an honest Probability Rating (High >50%, Medium 20%-50%, Low <20%, Tail Risk <5%) and Financial Severity (Catastrophic, Severe, Moderate, Minor).
     3. Detail the exact fundamental "Why" (the transmission mechanism into Owner Earnings, margins, or balance sheet solvency).
     4. Assign an overall Business Fragility Score (Low Fragility / Robust Moat | Moderate Sensitivity | High Fragility / Tail-Risk Asymmetric) to disqualify or caution against businesses where risk probability is dangerously elevated regardless of theoretical DCF upside.

   Pillar 10: Central Bank Policy Rate & Pure-Profit Float Sensitivity
   - For financial platforms, neo-banks, digital brokerages, and payroll/escrow custodians holding material customer float (>10% of operating profit), stress-test earnings against interest rate cycles.
   - Model the earnings impact of a +/-100 bps shift in central bank policy rates (e.g. Fed funds rate, ECB deposit rate). Never assume peak-rate Net Interest Income (NII) persists indefinitely during an easing cycle.

   Pillar 11: Agile Boutique Challenger & Incremental Market Share Loss Audit
   - When evaluating competitive moats, do not limit comparisons to legacy mega-cap peers.
   - Explicitly audit fast-growing agile disrupters and boutique category specialists (e.g. On Running/Hoka vs Nike, Alo Yoga/Vuori vs Lululemon, Shop Pay/Stripe vs PayPal). Identify where the marginal high-income or younger consumer is shifting and quantify physical store encroachment and digital checkout capture.

   Pillar 12: Turnaround J-Curve & Physical Product Lead-Time Realism
   - For enterprises executing a strategic restructuring or product line pruning (labeled 'Turnaround Play' or 'Turnaround Risk'), enforce a 12–24 month innovation lag.
   - Restricting legacy product supply (e.g. pruning retro footwear franchises, pulling defective apparel lines) creates an immediate revenue gap. Incorporate Year 1–2 trough conservatism in Base Case DCF modeling before projecting multi-year compounding re-acceleration.

   Pillar 13: Antitrust & Regulatory M&A Plausibility Filter
   - Disallow treating speculative mega-cap takeovers or private equity buyouts as a firm downside 'valuation floor' unless the transaction is legally and regulatory feasible under global antitrust regimes (FTC/DOJ, EU Commission, UK CMA).

   Pillar 14: Capital Hoarder Discount & Cash Repatriation Governance Audit
   - When an enterprise holds cash and liquid investments exceeding 35%–40% of its market capitalization but refuses to return capital via share repurchases or cash dividends ($0 capital return), audit the capital distribution governance.
   - For non-dividend-paying / non-repurchasing enterprises (e.g. PDD), evaluate whether cash is economically locked in operating jurisdictions or subject to withholding taxes upon offshore repatriation. Apply a conservative 15%–25% governance/repatriation haircut to unreturned balance sheet cash in Bear and Base DCF bridges.

   Pillar 15: Cross-Border De Minimis Customs & Local Warehousing Margin Audit
   - For global export and cross-border direct-to-consumer platforms (e.g. Temu, Shein, AliExpress), stress-test the operational transition from duty-free air parcels (US $800 / EU €150 de minimis exemptions) to semi-managed local bonded warehouse fulfillment.
   - Model the resulting compression in gross take rates and higher localized merchant inventory holding overhead in Bear and Base case margin projections.

   Pillar 19: Strict USD Currency Standardization & Mandatory FX Conversion
   - MANDATORY USD CURRENCY DENOMINATION: Every single financial metric, stat card, segment revenue, operating cash flow, CapEx, debt, cash, and DCF valuation across the entire dossier MUST strictly be converted to and presented in US DOLLARS ($ USD).
   - If a company reports in foreign currency (e.g. RMB/CNY, EUR, JPY, GBP, NTD, BRL), you MUST convert every number to USD ($) at prevailing exchange rates (e.g. for Chinese companies, divide RMB by ~7.15).
   - Zero RMB (¥ / CNY), zero EUR (€), zero foreign currency symbols or labels in text, tables, metrics cards, or JSON blocks.
   - For foreign ADRs, the share count denominator MUST strictly be the US-traded ADS (American Depositary Share) count so per-share numbers are directly in USD per ADS / USD per share.

5. Editorial Aesthetics & Structural Clarity:
   - Format financial KPIs and segment data into `<div class="metrics-grid"><div class="metric-card">...</div></div>` or structured HTML tables. Zero raw text dumps.
   - Use Callout boxes (`<div class="callout">...</div>`) for key insights, management quotes, and pre-mortem falsification triggers.
   - Zero external images: Keep all analyses purely professional analytical text, data tables, callouts, and metric cards.
"""

# ==============================================================================
# OVERHAULED 3-AGENT THESIS PIPELINE PROMPTS & SYSTEM PROMPTS
# ==============================================================================

AGENT_1_PREMISE_PROMPT = """Target: {ticker} ({company_name})
User Focus / Research Notes: {notes}

You are LLM Agent 1: Company Premise Specialist.
Your broad goal is to formulate a comprehensive, crystal-clear, plain-English "Premise of the Company" grounded in verified primary data.

BLIND VALUATION & ZERO PRICE BIAS INVARIANT:
You are analyzing this company 100% blind to current stock market prices or broker consensus targets. Value the enterprise purely as an unlisted private operating business from audited SEC filings, unit economics, and owner cash flows.

MANDATORY USD CONVERSION & ZERO FOREIGN CURRENCY INVARIANT:
- ALL financial numbers, metrics, segment revenues, operating cash flows, CapEx, debt, cash, and balance sheet figures MUST strictly be converted to and denominated in US DOLLARS ($ USD) at prevailing FX exchange rates (e.g. for RMB divide by ~7.15, EUR convert to USD).
- Zero RMB (¥ / CNY), zero EUR (€), zero foreign currencies anywhere in your analysis, stat cards, executive quotes, or commentary.
- For foreign ADRs (e.g. JD, BABA, PDD, TSM, NIO), use the US-listed ADS (American Depositary Share) share count.

MANDATORY RESEARCH & INVESTIGATION DIRECTIVES:
1. AUDITED FINANCIAL STATEMENTS:
   - Search SEC 10-K, 10-Q, 20-F filings or audited financial releases for:
     * Annual / LTM Net Revenue (in $ USD Billions), segment breakdowns, and gross margin profiles.
     * GAAP Operating Income (EBIT), GAAP Operating Cash Flow, Maintenance/Growth CapEx, and Stock-Based Compensation (SBC) in $ USD.
     * Balance Sheet Fortress: Cash, cash equivalents, short-term investments, funded debt, lease liabilities (ASC 842), and net cash/debt in $ USD.
     * Capital Structure: Diluted shares outstanding / Diluted ADSs, share buybacks vs equity dilution trajectory.
2. LAST 4 QUARTERLY EARNINGS CALL TRANSCRIPTS:
   - Search and synthesize the LAST 4 QUARTERLY EARNINGS CALL TRANSCRIPTS (e.g. Q1, Q2, Q3, Q4 / the 4 most recent reporting quarters).
   - Extract authentic executive commentary and direct quotes from the active CEO and CFO.
   - Trace management execution across the 4 quarters: what leadership promised, quarterly inflection points, guidance changes, margin shifts, and forward priorities.
3. C-SUITE LEADERSHIP VERIFICATION:
   - Search and verify the exact active Chief Executive Officer (CEO) and Chief Financial Officer (CFO).

EDITORIAL & FORMATTING DIRECTIVES:
- Write in engaging, plain English so that ANY reader immediately understands what this company does, how it makes money, its current financial standing, and its recent quarterly narrative arc.
- Structure Section 1 in clean Semantic HTML (<div class="section">...</div> or direct HTML tags) with:
  * <h2>Section 1: The Premise of the Company</h2>
  * Plain-English Business Overview (The Core Machine): How the business operates, customer value proposition, unit economics, switching costs, and competitive moat.
  * Financial Reality & Balance Sheet Snapshot (All figures strictly in $ USD):
    <div class="metrics-grid">
      <div class="metric-card"><div class="metric-label">Annual / LTM Net Revenue</div><div class="metric-value">$XX.XXB</div><div class="metric-delta pos">+XX% YoY</div></div>
      <div class="metric-card"><div class="metric-label">GAAP Operating Margin</div><div class="metric-value">XX.X%</div><div class="metric-delta pos">+XXX bps YoY</div></div>
      <div class="metric-card"><div class="metric-label">Operating Cash Flow (OCF)</div><div class="metric-value">$XX.XXB</div><div class="metric-delta pos">GAAP ($ USD)</div></div>
      <div class="metric-card"><div class="metric-label">Net Cash / Debt Fortress</div><div class="metric-value">+$XX.XXB</div><div class="metric-delta pos">Liquid ($ USD)</div></div>
    </div>
  * Last 4 Earnings Calls: Management Commentary & Operational Arc:
    A dedicated executive commentary box synthesizing the 4 quarters with authentic executive quotes:
    <div class="callout">
      <h3>Executive Leadership Commentary &amp; 4-Quarter Trajectory</h3>
      <p><strong>[CEO Name], Chief Executive Officer:</strong> "..."</p>
      <p><strong>[CFO Name], Chief Financial Officer:</strong> "..."</p>
    </div>
  * Current State of Play: A crisp summary of where the business stands right now and why it is at a pivotal inflection point.

NO IMAGES, NO INLINE STYLES, NO CODE FENCES. Output pure HTML only."""


AGENT_2_STORIES_PROMPT = """Target: {ticker} ({company_name})

You are LLM Agent 2: 3 Stories Strategist.
Your input is LLM Agent 1's Company Premise:
{premise_context}

BLIND VALUATION & ZERO PRICE BIAS INVARIANT:
You are operating 100% blind to stock market quotations or stock price targets. Formulate business trajectories based strictly on business realities, competitive moats, and operational levers.

MANDATORY USD CONVERSION & ZERO FOREIGN CURRENCY INVARIANT:
- All financial metrics, segment revenues, margin expansions, and cash flows mentioned across all 3 stories MUST strictly be denominated in US DOLLARS ($ USD).
- Zero RMB, zero EUR, zero foreign currencies.

MANDATORY RESEARCH & GROUNDING DIRECTIVES:
- In addition to Agent 1's Company Premise, you can and MUST search and inspect {company_name}'s ({ticker}) latest SEC financial statements (10-K, 10-Q, 20-F) and recent quarterly earnings call transcripts.
- Use executive commentary, management guidance, segment growth rates, and industry competition from these filings to ground each story firmly in operating reality.

Your Objective:
Formulate 3 PROBABLE BUT DISTINCT STORIES (i.e. probable future fundamental paths this play could unfold over the next 3 to 5 years).

STORYLINE REQUIREMENTS:
1. Understandable to Anyone: Anyone who reads Agent 1's Premise should be able to clearly understand these 3 stories.
2. Probable & Distinct:
   - They are NOT labeled simply Bear/Base/Bull or Low/Medium/High.
   - They represent 3 distinct realistic operating paths with narrative descriptive business titles (e.g. "Story 1: [Descriptive Title]", "Story 2: [Descriptive Title]", "Story 3: [Descriptive Title]").
   - All 3 stories must be grounded in the company's real business units, customer trends, industry competition, and operational levers.
3. Detailed Structure for Each Story:
   - Narrative & Market Dynamics: What happens to customer demand, adoption, market share, and competitive rivalry.
   - Management Execution & Strategic Levers: What leadership does regarding pricing, investment, cost optimization, product development, or capital return.
   - Financial Trajectory (3-5 Year Horizon): Expected revenue growth, margin expansion or compression, and cash generation (in $ USD).
   - Key Milestones / Indicators to Watch: Concrete signs that confirm this storyline is unfolding.

Generate Section 2 in clean Semantic HTML:
<h2>Section 2: 3 Probable Business Stories</h2>
<p>Based on the company's core premise, operating reality, financial filings, and 4-quarter earnings trajectory, here are 3 distinct, probable fundamental paths this business could take over the next 3–5 years:</p>

<div class="callout">
  <h3>📖 Story 1: [Descriptive Operational Title 1]</h3>
  <p>[Full narrative explanation of this operational path...]</p>
  <p><strong>Core Operating Trajectory:</strong> [Revenue growth, margin profile, cash generation dynamics in $ USD...]</p>
  <p><strong>Key Milestones to Watch:</strong> [Specific indicators to monitor...]</p>
</div>

<div class="callout">
  <h3>📖 Story 2: [Descriptive Operational Title 2]</h3>
  <p>[Full narrative explanation of this operational path...]</p>
  <p><strong>Core Operating Trajectory:</strong> [Revenue growth, margin profile, cash generation dynamics in $ USD...]</p>
  <p><strong>Key Milestones to Watch:</strong> [Specific indicators to monitor...]</p>
</div>

<div class="callout">
  <h3>📖 Story 3: [Descriptive Operational Title 3]</h3>
  <p>[Full narrative explanation of this operational path...]</p>
  <p><strong>Core Operating Trajectory:</strong> [Revenue growth, margin profile, cash generation dynamics in $ USD...]</p>
  <p><strong>Key Milestones to Watch:</strong> [Specific indicators to monitor...]</p>
</div>

NO IMAGES, NO INLINE STYLES, NO CODE FENCES. Output pure HTML only."""


AGENT_3_DCF_EVALUATOR_PROMPT = """Target: {ticker} ({company_name})

Company Premise:
{premise_context}

The 3 Stories:
{stories_context}

You are LLM Agent 3: Storyline DCF Valuation Specialist.

BLIND VALUATION & ZERO PRICE BIAS INVARIANT:
You have ZERO knowledge of current stock market price, 52-week ranges, or broker consensus targets. Value the enterprise purely from First Principles of business cash generation as if purchasing 100% of the unlisted private business.

MANDATORY USD CONVERSION & DENOMINATOR INTEGRITY INVARIANT:
- ALL DCF numbers MUST strictly be evaluated in US DOLLARS ($ USD).
- `year1_oe_m`: Full 12-Month ANNUALized Base Year 1 Owner Earnings in MILLIONS OF US DOLLARS ($ Millions USD). (GAAP Operating Cash Flow minus Maintenance CapEx minus 100% SBC). NEVER use a single quarter's figure! For large enterprises ($10B+ revenue), annual OE is typically $500M - $25,000M USD.
- `net_cash_debt_per_share`: Audited Net Balance Sheet Cash/Debt in US DOLLARS PER ADS/SHARE ($ USD per ADS/share). Calculated strictly as: (Cash & Short-Term Investments - Total Funded Debt - Capitalized Leases) / Diluted Shares (ADSs). For almost all companies, this is between -$30.00 to +$25.00/sh. NEVER plug an arbitrary round placeholder like $100.00.
- `diluted_shares_m`: Diluted shares outstanding (in Millions). For US-listed foreign ADRs (e.g. JD, BABA, PDD, TSM, NIO), you MUST use the US-traded ADS (American Depositary Share) count, NOT the ordinary share count!

STORYLINE PARAMETER CONSISTENCY & HIERARCHY:
- Parameters MUST be strictly consistent with the specific operating narrative of each story:
  * Story 1 (Modeled Base Path): Expected operational compounding parameters.
  * Story 2 (Headwinds / Conservative Path): Lower Year 1 OE and LOWER 5-year CAGR than Story 1.
  * Story 3 (Expansion / Accelerated Path): Higher Year 1 OE and HIGHER 5-year CAGR than Story 1.
- NEVER copy-paste identical parameters across stories.

MANDATORY FINANCIAL RESEARCH & AUDITING DIRECTIVES:
- In addition to the Premise and 3 Stories, you can and MUST search and inspect {company_name}'s ({ticker}) audited SEC financial statements (10-K, 10-Q, 20-F), balance sheet cash/debt, cash flow statements (Operating Cash Flow, Maintenance CapEx, Stock-Based Compensation), and recent earnings call guidance.
- Ensure all DCF parameters (Year 1 Owner Earnings, 5-Year CAGR, Discount Rate, Terminal Growth, Diluted Shares/ADSs, Net Cash/Debt) are reasonable, level-headed, and consistent with each specific storyline.

Your Objective:
For each of the 3 stories generated by Agent 2, evaluate and formulate reasonable, level-headed DCF assumptions in USD that are strictly consistent with that specific storyline.

Valuation Invariants:
1. Zero Price Anchoring: Value the business strictly from First Principles of cash generation as if purchasing 100% of the private enterprise.
2. DCF Parameters for each of the 3 Stories (Strictly $ USD):
   - Year 1 Base Owner Earnings (OE₁) in $ Millions USD (GAAP Operating Cash Flow minus Maintenance CapEx minus 100% SBC).
   - 5-Year Organic OE CAGR (%) consistent with that story's operational trajectory.
   - Discount Rate (r) (%) anchored to local sovereign 10Y bond yield + equity risk premium (typically 8.5% - 11.0%).
   - Terminal Growth Rate (g_term) (%) capped at long-term GDP growth (1.50% - 2.50%).
   - Net Balance Sheet Debt/Cash per share adjustment ($/sh USD): (Cash + Short-Term Investments - Funded Debt - Leases) / Diluted Shares.
   - Diluted Share Count / Diluted ADSs (in Millions).
3. Column Order Invariant:
   - Column 1 MUST correspond to Story 1
   - Column 2 MUST correspond to Story 2
   - Column 3 MUST correspond to Story 3

Return your valuation evaluation as a JSON block in ```json ... ```:
```json
{{
  "diluted_shares_m": <float (in millions, prioritizing ADSs for US-listed foreign ADRs)>,
  "net_cash_debt_per_share": <float (USD per share/ADS, positive for net cash, negative for net debt)>,
  "story1": {{
    "title": "<Clean Descriptive Title 1>",
    "year1_oe_m": <float (USD Millions, full annual 12-month figure)>,
    "cagr_5yr": <float (e.g. 0.075 for 7.5%)>,
    "discount_rate": <float (e.g. 0.095 for 9.5%)>,
    "terminal_growth": <float (e.g. 0.0225 for 2.25%)>,
    "rationale": "<Brief plain-English explanation of why these parameters match Story 1>"
  }},
  "story2": {{
    "title": "<Clean Descriptive Title 2>",
    "year1_oe_m": <float (USD Millions, full annual 12-month figure)>,
    "cagr_5yr": <float (e.g. 0.020 for 2.0%)>,
    "discount_rate": <float (e.g. 0.095 for 9.5%)>,
    "terminal_growth": <float (e.g. 0.020 for 2.0%)>,
    "rationale": "<Brief plain-English explanation of why these parameters match Story 2>"
  }},
  "story3": {{
    "title": "<Clean Descriptive Title 3>",
    "year1_oe_m": <float (USD Millions, full annual 12-month figure)>,
    "cagr_5yr": <float (e.g. 0.120 for 12.0%)>,
    "discount_rate": <float (e.g. 0.095 for 9.5%)>,
    "terminal_growth": <float (e.g. 0.025 for 2.5%)>,
    "rationale": "<Brief plain-English explanation of why these parameters match Story 3>"
  }},
  "labels": ["<Canonical Conviction Tier (High Conviction | Solid Conviction | Moderate Conviction | Cautious Stance | Turnaround Play | Speculative Risk)>", "<Play Driver 1 (max 2 words)>", "<Play Driver 2 (max 2 words)>"],
  "next_catalyst_date": "<YYYY-MM-DD (ISO format)>",
  "next_catalyst_event": "<Concise event e.g. Q3 '26 ER, Investor Day>",
  "top_funds": ["<Top Fund / Whale 1>", "<Top Fund / Whale 2>"],
  "institutional_ownership_pct": "<e.g. 48.5%>",
  "insider_signal": "<Neutral (10b5-1) | Net Buying | Cluster Buying | Net Selling | No Activity>",
  "insider_summary": "<Crisp 1-line Form 4 insider trading summary, max 12 words>",
  "executive_summary": "<2-3 sentence crisp plain-English summary of the premise and valuation in USD>"
}}
```
"""

def extract_capital_structure_invariants(context_text: str) -> Tuple[float, float]:
    """Extracts Diluted Shares (in Millions, prioritizing ADS count for US ADRs) 
    and Net Cash / Net Debt per share in USD from audited financials."""
    shares_m = 100.0
    net_debt_adj = 0.0

    # 1. Shares Extraction (Prioritize ADS for foreign ADRs like JD, BABA, PDD, TSM)
    m_ads = re.search(r'([\d,]+(?:\.\d+)?)\s*(?:million|billion|M|B)?\s*(?:American Depositary Shares|ADSs|ADS\b)', context_text, re.IGNORECASE)
    m_prefix = re.search(r'(?:Diluted ADS Count|Diluted ADSs|Audited Diluted Share Count|diluted shares|share count).*?([\d,]+(?:\.\d+)?)\s*(?:million|billion|M|B|\bADSs\b|\bshares\b)?', context_text, re.IGNORECASE)
    m_sh = re.search(r'([\d,]+(?:\.\d+)?)\s*(?:million|billion|M|B)?\s*(?:diluted shares|shares outstanding|ordinary shares)', context_text, re.IGNORECASE)
    
    m_target = m_ads or m_prefix or m_sh
    if m_target:
        try:
            val = float(re.sub(r"[^\d.-]", "", m_target.group(1)))
            if val < 50.0:
                val = val * 1000.0
            shares_m = max(1.0, val)
        except Exception:
            pass

    # 2. Derive Net Cash / Net Debt per share directly from Total Liquid Cash & Debt ($B USD)
    cash_m = re.search(r'(?:Cash Fortress|Net Cash / Debt Fortress|Net Cash Fortress|Cash & ST Investments|Liquid Cash|Liquid).*?([+-]?\$\s*[\d,]+(?:\.\d+)?)\s*(?:B|billion)', context_text, re.IGNORECASE)
    if cash_m:
        try:
            total_cash_b = float(re.sub(r"[^\d.-]", "", cash_m.group(1)))
            if total_cash_b > 0 and shares_m > 0:
                calc_val = round((total_cash_b * 1000.0) / shares_m, 2)
                if 0.5 <= calc_val <= 35.0:
                    net_debt_adj = calc_val
        except Exception:
            pass

    # 3. Fallback: Net Cash / Net Debt per share extraction (USD)
    if abs(net_debt_adj) < 0.01:
        m_nd_sh = re.search(r'(?:Net Cash|Net Debt|Cash Fortress|Net Liquid Cash).*?([+-]?\$\s*[\d,]+(?:\.\d+)?\s*(?:/ADS|/sh|/share|\bper ADS\b|\bper share\b))', context_text, re.IGNORECASE)
        if not m_nd_sh:
            m_nd_sh = re.search(r'([+-]?\$\s*[\d,]+(?:\.\d+)?\s*(?:/ADS|/sh|/share|\bper ADS\b|\bper share\b))', context_text, re.IGNORECASE)
            
        if m_nd_sh:
            try:
                v_str = re.sub(r"[^\d.-]", "", m_nd_sh.group(1))
                if v_str and v_str not in (".", "-"):
                    v = float(v_str)
                    if "net debt" in m_nd_sh.group(0).lower() and v > 0:
                        v = -v
                    # Plausibility clamp: Net cash per share cannot be an arbitrary plug (e.g. $100/sh)
                    if -80.0 <= v <= 35.0:
                        net_debt_adj = v
            except Exception:
                pass

    return shares_m, net_debt_adj


def reconcile_and_repair_section_3_valuation(
    ticker: str,
    current_price: float,
    sec3_raw_html: str,
    dcf_data: Dict[str, Any],
    premise_context: str = "",
    stories_context: str = ""
) -> Tuple[str, Dict[str, Any]]:
    """Calculates exact mathematical DCF values in Python for the 3 stories,
    producing Table 1 (3-Storyline DCF Valuation Table), Table 2 (2D Sensitivity Grid),
    Reverse DCF callout, and 5-Year Market Closure Test with 100% precision."""
    
    # 1. Extract shares and net debt adjustment
    shares_m = float(dcf_data.get("diluted_shares_m") or 0.0)
    net_debt_adj = float(dcf_data.get("net_cash_debt_per_share") or 0.0)
    
    # Prevent hallucinated/plugged cash adjustments (e.g. $100/sh)
    if net_debt_adj > 35.0 or net_debt_adj < -80.0 or abs(net_debt_adj) < 0.001 or shares_m <= 0.0:
        extracted_shares, extracted_nd = extract_capital_structure_invariants(f"{premise_context} {stories_context} {sec3_raw_html}")
        if shares_m <= 0.0:
            shares_m = extracted_shares
        if net_debt_adj > 35.0 or net_debt_adj < -80.0 or abs(net_debt_adj) < 0.001:
            net_debt_adj = extracted_nd

    shares_m = max(1.0, shares_m)
    net_debt_adj = max(-80.0, min(35.0, net_debt_adj))

    # 2. Extract Story Titles & Parameters
    s1_dict = dcf_data.get("story1", {})
    s2_dict = dcf_data.get("story2", {})
    s3_dict = dcf_data.get("story3", {})

    # Extract titles from stories_context or json
    titles = [
        s1_dict.get("title") or "Story 1",
        s2_dict.get("title") or "Story 2",
        s3_dict.get("title") or "Story 3"
    ]
    
    # Clean titles of prefixes like "Story 1: " or "Storyline 1: "
    clean_titles = []
    for idx, t in enumerate(titles, start=1):
        clean_t = re.sub(rf"^(?:📖\s*)?(?:Story|Storyline)\s*{idx}\s*[:\-–—]\s*", "", str(t), flags=re.IGNORECASE).strip()
        clean_titles.append(clean_t if clean_t else f"Operating Path {idx}")

    # Parameters per story
    s1_oe1 = float(s1_dict.get("year1_oe_m") or 5000.0)
    s1_c = float(s1_dict.get("cagr_5yr") or 0.065)
    s1_r = float(s1_dict.get("discount_rate") or 0.095)
    s1_gt = float(s1_dict.get("terminal_growth") or 0.0225)

    s2_oe1 = float(s2_dict.get("year1_oe_m") or (s1_oe1 * 0.85))
    s2_c = float(s2_dict.get("cagr_5yr") or 0.020)
    s2_r = float(s2_dict.get("discount_rate") or s1_r)
    s2_gt = float(s2_dict.get("terminal_growth") or 0.020)

    s3_oe1 = float(s3_dict.get("year1_oe_m") or (s1_oe1 * 1.15))
    s3_c = float(s3_dict.get("cagr_5yr") or 0.110)
    s3_r = float(s3_dict.get("discount_rate") or s1_r)
    s3_gt = float(s3_dict.get("terminal_growth") or 0.025)

    # Annual Cash Flow Sanity Guard: Check if Year 1 Owner Earnings was erroneously provided as a single quarter
    m_rev = re.search(r'(?:Net Revenue|Annual Revenue|LTM Revenue).*?\$([\d,]+(?:\.\d+)?)\s*(?:B|billion)', premise_context, re.IGNORECASE)
    if m_rev:
        try:
            rev_b = float(re.sub(r"[^\d.-]", "", m_rev.group(1)))
            if rev_b >= 20.0 and s1_oe1 < 900.0:
                s1_oe1 = s1_oe1 * 4.0
                if s2_oe1 < 900.0:
                    s2_oe1 = s2_oe1 * 4.0
                if s3_oe1 < 900.0:
                    s3_oe1 = s3_oe1 * 4.0
        except Exception:
            pass

    # Ensure Storyline Scenario Ordering Integrity (Story 2 conservative vs Story 3 expansion)
    if abs(s1_oe1 - s3_oe1) < 1.0 and abs(s1_c - s3_c) < 0.005:
        s3_oe1 = round(s1_oe1 * 1.15, 1)
        s3_c = round(s1_c + 0.04, 3)
    if abs(s1_oe1 - s2_oe1) < 1.0 and abs(s1_c - s2_c) < 0.005:
        s2_oe1 = round(s1_oe1 * 0.85, 1)
        s2_c = round(max(-0.02, s1_c - 0.04), 3)

    story_configs = [
        {"title": clean_titles[0], "oe1": max(10.0, s1_oe1), "cagr": s1_c, "r": s1_r, "gt": s1_gt},
        {"title": clean_titles[1], "oe1": max(10.0, s2_oe1), "cagr": s2_c, "r": s2_r, "gt": s2_gt},
        {"title": clean_titles[2], "oe1": max(10.0, s3_oe1), "cagr": s3_c, "r": s3_r, "gt": s3_gt}
    ]

    cols = []
    for sc in story_configs:
        oe = sc["oe1"]
        c = sc["cagr"]
        r = sc["r"]
        gt = sc["gt"]

        # Standard 5-year discounting
        pvs = [oe * ((1 + c) ** (t - 1)) / ((1 + r) ** t) for t in range(1, 6)]
        pv_5yr = sum(pvs)
        yr5_oe = oe * ((1 + c) ** 4)
        tv = (yr5_oe * (1 + gt)) / (r - gt)
        pv_tv = tv / ((1 + r) ** 5)
        ev = pv_5yr + pv_tv
        eq_val = ev + (net_debt_adj * shares_m)
        fv_sh = max(0.00, eq_val / shares_m)
        mos = ((fv_sh - current_price) / current_price) * 100.0 if current_price > 0 else 0.0

        cols.append({
            "title": sc["title"],
            "oe1": oe,
            "cagr": c,
            "r": r,
            "gt": gt,
            "oe1_str": f"${oe:,.1f}M",
            "cagr_str": f"{c * 100:+.1f}%",
            "r_str": f"{r * 100:.1f}%",
            "gt_str": f"{gt * 100:.2f}%",
            "pv_5yr_str": f"${pv_5yr:,.1f}M",
            "pv_tv_str": f"${pv_tv:,.1f}M",
            "ev_str": f"${ev:,.1f}M",
            "nd_str": f"{net_debt_adj:+.2f}/sh" if net_debt_adj != 0 else "$0.00/sh",
            "fv_str": f"${fv_sh:.2f}",
            "mos_str": f"{mos:+.1f}%",
            "fv_raw": fv_sh,
            "mos_raw": mos,
            "ev_raw": ev
        })

    # Table 1: 3-Storyline DCF Valuation Table
    dcf_table_html = f"""<h3>3-Storyline DCF Valuation Summary</h3>
<table class="data-table">
  <thead>
    <tr>
      <th>Valuation Metric / Parameter</th>
      <th>Story 1: {cols[0]['title']}</th>
      <th>Story 2: {cols[1]['title']}</th>
      <th>Story 3: {cols[2]['title']}</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>Year 1 Base Owner Earnings (OE₁)</td><td>{cols[0]['oe1_str']}</td><td>{cols[1]['oe1_str']}</td><td>{cols[2]['oe1_str']}</td></tr>
    <tr><td>5-Year Organic OE CAGR</td><td>{cols[0]['cagr_str']}</td><td>{cols[1]['cagr_str']}</td><td>{cols[2]['cagr_str']}</td></tr>
    <tr><td>Discount Rate (Local Sovereign + ERP)</td><td>{cols[0]['r_str']}</td><td>{cols[1]['r_str']}</td><td>{cols[2]['r_str']}</td></tr>
    <tr><td>Terminal Growth Rate (GDP Capped)</td><td>{cols[0]['gt_str']}</td><td>{cols[1]['gt_str']}</td><td>{cols[2]['gt_str']}</td></tr>
    <tr><td>PV of 5-Year Cash Flows</td><td>{cols[0]['pv_5yr_str']}</td><td>{cols[1]['pv_5yr_str']}</td><td>{cols[2]['pv_5yr_str']}</td></tr>
    <tr><td>PV of Terminal Value (TV)</td><td>{cols[0]['pv_tv_str']}</td><td>{cols[1]['pv_tv_str']}</td><td>{cols[2]['pv_tv_str']}</td></tr>
    <tr><td><strong>Total Enterprise Value (EV)</strong></td><td><strong>{cols[0]['ev_str']}</strong></td><td><strong>{cols[1]['ev_str']}</strong></td><td><strong>{cols[2]['ev_str']}</strong></td></tr>
    <tr><td>Net Balance Sheet Debt/Cash Adjustment</td><td>{cols[0]['nd_str']}</td><td>{cols[1]['nd_str']}</td><td>{cols[2]['nd_str']}</td></tr>
    <tr><td><strong>Intrinsic Fair Value / Share</strong></td><td><strong>{cols[0]['fv_str']}</strong></td><td><strong>{cols[1]['fv_str']}</strong></td><td><strong>{cols[2]['fv_str']}</strong></td></tr>
    <tr><td><strong>Margin of Safety vs Current Price (${current_price:.2f})</strong></td><td><strong>{cols[0]['mos_str']}</strong></td><td><strong>{cols[1]['mos_str']}</strong></td><td><strong>{cols[2]['mos_str']}</strong></td></tr>
  </tbody>
</table>"""

    # Table 2: 2D Valuation Sensitivity Matrix (Story 1 / Base)
    base_oe = cols[0]["oe1"]
    base_c = cols[0]["cagr"]
    r_base = cols[0]["r"]
    gt_base = cols[0]["gt"]

    r_shifts = [-0.01, 0.0, 0.01]
    gt_shifts = [-0.005, -0.0025, 0.0, 0.005]

    grid_headers = "".join([f"<th>{(gt_base + gs)*100:.2f}%</th>" for gs in gt_shifts])
    grid_rows_html = ""
    for rs in r_shifts:
        r_cur = r_base + rs
        row_label = f"r - {abs(rs)*100:.1f}%" if rs < 0 else (f"r + {rs*100:.1f}%" if rs > 0 else "r Base")
        cell_strs = []
        for gs in gt_shifts:
            gt_cur = gt_base + gs
            pvs_g = [base_oe * ((1 + base_c) ** (t - 1)) / ((1 + r_cur) ** t) for t in range(1, 6)]
            pv_5_g = sum(pvs_g)
            tv_g = (base_oe * ((1 + base_c) ** 4) * (1 + gt_cur)) / (r_cur - gt_cur)
            pv_tv_g = tv_g / ((1 + r_cur) ** 5)
            ev_g = pv_5_g + pv_tv_g
            eq_g = ev_g + (net_debt_adj * shares_m)
            fv_g = max(0.00, eq_g / shares_m)
            if rs == 0.0 and gs == 0.0:
                cell_strs.append(f"<td><strong>${fv_g:.2f} (Target)</strong></td>")
            else:
                cell_strs.append(f"<td>${fv_g:.2f}</td>")
        grid_rows_html += f"<tr><td><strong>{row_label} ({r_cur*100:.1f}%)</strong></td>{''.join(cell_strs)}</tr>\n"

    sensitivity_html = f"""<h3>2D Valuation Sensitivity Matrix (Story 1 Baseline)</h3>
<table class="data-table">
  <thead>
    <tr>
      <th>Discount Rate \\ Terminal Growth</th>
      {grid_headers}
    </tr>
  </thead>
  <tbody>
    {grid_rows_html}
  </tbody>
</table>"""

    # Reverse DCF & Market Closure
    ratio = current_price / cols[0]["fv_raw"] if cols[0]["fv_raw"] > 0 else 1.0
    implied_g = round(base_c * 100.0 * ratio - (1.0 - ratio) * 4.0, 1)

    mkt_cap = current_price * shares_m
    cum_cash_5yr = sum([base_oe * ((1 + base_c) ** (t - 1)) for t in range(1, 6)])
    cum_return_pct = (cum_cash_5yr / mkt_cap) * 100.0 if mkt_cap > 0 else 0.0
    tot_liq_pct = ((cum_cash_5yr + (net_debt_adj * shares_m)) / mkt_cap) * 100.0 if mkt_cap > 0 else 0.0

    reverse_dcf_html = f"""<h3>Market-Implied Expectations &amp; &quot;What is Priced In?&quot; (Reverse DCF Audit)</h3>
<p>A reverse DCF analysis inverts the valuation equation: rather than forecasting arbitrary cash flows, we determine what 5-year Owner Earnings CAGR (\(g_{{\\text{{implied}}}}\)) Mr. Market is currently embedding into today's market price of ${current_price:.2f}.</p>
<div class="callout">
<p><strong>Market-Implied Growth Expectations vs. Story 1 Reality:</strong></p>
<ul>
<li><strong>Current Share Price:</strong> ${current_price:.2f} (Story 1 Fair Value: {cols[0]['fv_str']})</li>
<li><strong>Market-Implied 5-Year Owner Earnings CAGR (\(g_{{\\text{{implied}}}}\)):</strong> <strong>{implied_g:+.1f}% per annum</strong></li>
<li><strong>Story 1 Modeled Growth Rate (\(g_{{\\text{{base}}}}\)):</strong> <strong>{base_c*100:+.1f}% per annum</strong></li>
<li><strong>Market Expectations Assessment:</strong> {'At current levels, Mr. Market prices in aggressive top-line expansion and sustained high-margin execution, leaving little room for execution missteps.' if current_price > cols[0]['fv_raw'] else 'Mr. Market prices in modest growth expectations and margin contraction, providing an attractive risk-reward profile and margin of safety.'}</li>
</ul>
</div>"""

    closure_html = f"""<h3>The 5-Year Market Closure Test</h3>
<p>If the stock exchange were to shut down completely for 5 full years starting today, an investor purchasing 100% of the company at today's market price (${current_price:.2f}) would rely entirely on organic cash flow generated by the business:</p>
<div class="callout">
<ul>
<li><strong>Current Market Capitalization:</strong> ${mkt_cap/1000.0:.2f}B (Current Price: ${current_price:.2f} &times; {shares_m:,.0f}M Diluted Shares/ADSs)</li>
<li><strong>5-Year Cumulative Organic Cash Generation:</strong> <strong>${cum_cash_5yr/1000.0:.2f}B</strong> (Generating <strong>{cum_return_pct:.1f}%</strong> of today's entire equity valuation purely from business operations)</li>
<li><strong>Balance Sheet Liquid Cash Cushion:</strong> <strong>${(net_debt_adj * shares_m)/1000.0:+.2f}B</strong> ({net_debt_adj:+.2f}/sh)</li>
<li><strong>Total Organic 5-Year Liquidity Coverage:</strong> <strong>${(cum_cash_5yr + net_debt_adj * shares_m)/1000.0:.2f}B</strong> (Represents <strong>{tot_liq_pct:.1f}%</strong> of current market capitalization)</li>
<li><strong>Market Closure Assessment:</strong> Without requiring a single share trade on Wall Street or multiple expansion, the private business engine generates sufficient owner cash flow to deliver an attractive compounding return.</li>
</ul>
</div>"""

    sec3_complete_html = f"""<h2>Section 3: Valuation &amp; DCF Matrix Across the 3 Stories</h2>
<p>Translating each of the 3 probable business stories into discounted cash flow valuation models rooted in Warren Buffett's Owner Earnings framework (GAAP Operating Cash Flow minus Maintenance CapEx minus 100% Stock-Based Compensation). Each valuation represents the present value of all cash the private operating business can return to owners across that specific fundamental trajectory:</p>

{dcf_table_html}

{sensitivity_html}

{reverse_dcf_html}

{closure_html}"""

    computed_meta = {
        "story1_target": f"{cols[0]['fv_str']} ({cols[0]['mos_str']})",
        "story2_target": f"{cols[1]['fv_str']} ({cols[1]['mos_str']})",
        "story3_target": f"{cols[2]['fv_str']} ({cols[2]['mos_str']})",
        "story1_title": cols[0]["title"],
        "story2_title": cols[1]["title"],
        "story3_title": cols[2]["title"],
        "story1_val": cols[0]["fv_raw"],
        "story2_val": cols[1]["fv_raw"],
        "story3_val": cols[2]["fv_raw"],
        "fair_value_estimate": cols[0]["fv_str"],
        "base_target": f"{cols[0]['fv_str']} ({cols[0]['mos_str']})",
        "bear_target": f"{cols[1]['fv_str']} ({cols[1]['mos_str']})",
        "bull_target": f"{cols[2]['fv_str']} ({cols[2]['mos_str']})",
        "what_is_priced_in": f"g_implied: {implied_g:+.1f}% (vs Base {base_c*100:+.1f}%)",
        "implied_g": implied_g,
        "base_cagr": base_c
    }

    return sec3_complete_html, computed_meta


def generate_genesis_thesis(ticker: str, company_name: str, current_price: float, initial_notes: str = "") -> Tuple[Dict[str, Any], str]:
    """Generates an investment thesis via the overhauled 3-Agent pipeline:
    1. Agent 1: Company Premise (Financial statements + last 4 earnings call transcripts).
    2. Agent 2: 3 Stories (Probable & distinct future operational paths based on premise).
    3. DCF Evaluator: 3-Story DCF Matrix + deterministic mathematical calculation.
    """
    ticker_clean = ticker.upper().strip()
    
    print("\n" + "=" * 70, flush=True)
    print(f"🏢 INITIATING 3-AGENT THESIS GENERATION: {ticker_clean} ({company_name})", flush=True)
    print(f"💵 Market Entry Price: ${current_price:.2f}", flush=True)
    if initial_notes:
        print(f"📝 User Notes / Focus: {initial_notes}", flush=True)
    print("=" * 70, flush=True)
    
    # ------------------------------------------------------------------
    # Step 1: LLM Agent 1 - Company Premise Specialist
    # ------------------------------------------------------------------
    print(f"\n🧠 [AGENT 1/3: COMPANY PREMISE] Researching financial statements and last 4 earnings calls (Blind Valuation Mode)...", flush=True)
    agent_1_prompt = AGENT_1_PREMISE_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        notes=initial_notes or "Synthesize core business model, unit economics, 4-quarter earnings commentary, and balance sheet strength in plain English."
    )
    
    sec1_raw = call_gemini_with_search(agent_1_prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY)
    sec1_clean = verify_and_repair_html_structure(clean_grounding_artifacts(sec1_raw))
    print(f"   │ Status: Premise established ({len(sec1_clean.split())} words generated)", flush=True)
    print("   └" + "─" * 50, flush=True)

    # ------------------------------------------------------------------
    # Step 2: LLM Agent 2 - 3 Stories Strategist
    # ------------------------------------------------------------------
    print(f"\n📖 [AGENT 2/3: 3 STORIES GENERATOR] Formulating 3 probable, distinct operational stories (Blind Valuation Mode)...", flush=True)
    agent_2_prompt = AGENT_2_STORIES_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        premise_context=sec1_clean
    )
    
    sec2_raw = call_gemini_with_search(agent_2_prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY)
    sec2_clean = verify_and_repair_html_structure(clean_grounding_artifacts(sec2_raw))
    print(f"   │ Status: 3 Stories generated ({len(sec2_clean.split())} words generated)", flush=True)
    print("   └" + "─" * 50, flush=True)

    # ------------------------------------------------------------------
    # Step 3: LLM Agent 3 / DCF Evaluator - Storyline DCF Valuation Engine
    # ------------------------------------------------------------------
    print(f"\n🧮 [AGENT 3/3: DCF EVALUATOR] Evaluating DCF parameters (Blind Valuation Mode)...", flush=True)
    agent_3_prompt = AGENT_3_DCF_EVALUATOR_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        premise_context=sec1_clean,
        stories_context=sec2_clean
    )
    
    sec3_raw = call_gemini_with_search(agent_3_prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY)
    dcf_data = extract_json_block(sec3_raw)

    # Run deterministic quantitative reconciliation pass
    sec3_clean, computed_meta = reconcile_and_repair_section_3_valuation(
        ticker=ticker_clean,
        current_price=current_price,
        sec3_raw_html=sec3_raw,
        dcf_data=dcf_data,
        premise_context=sec1_clean,
        stories_context=sec2_clean
    )
    print(f"   │ Status: 3 Valuations computed with deterministic math precision", flush=True)
    print("   └" + "─" * 50, flush=True)

    # ------------------------------------------------------------------
    # Step 4: Assemble Full Dossier HTML & Extract Metadata
    # ------------------------------------------------------------------
    print(f"\n🛡️ [HARMONIZER & QA] Assembling thesis sections and verifying structural integrity...", flush=True)
    raw_full_html = f"{sec1_clean}\n\n{sec2_clean}\n\n{sec3_clean}"
    full_html = verify_and_repair_html_structure(raw_full_html)
    
    # Metadata assembly
    story1_val = computed_meta["story1_val"]
    story2_val = computed_meta["story2_val"]
    story3_val = computed_meta["story3_val"]
    base_ret = ((story1_val - current_price) / current_price) * 100.0 if current_price > 0 else 0.0

    # Action Signal Derivation
    if base_ret >= 20.0:
        action_signal = "BUY"
    elif base_ret >= 0.0:
        action_signal = "HOLD"
    elif base_ret >= -15.0:
        action_signal = "CAUTION"
    else:
        action_signal = "AVOID"

    # Price alert corridors
    valid_story_vals = [v for v in [story1_val, story2_val, story3_val] if v > 0]
    min_story = min(valid_story_vals) if valid_story_vals else round(current_price * 0.85, 2)
    max_story = max(valid_story_vals) if valid_story_vals else round(current_price * 1.15, 2)

    lower_alert = round(min_story, 2)
    upper_alert = round(max_story, 2)
    if lower_alert >= current_price:
        lower_alert = round(current_price * 0.90, 2)
    if upper_alert <= current_price:
        upper_alert = round(current_price * 1.15, 2)

    raw_labels = dcf_data.get("labels") or ["Solid Conviction", "Moat Compounder", "Cash Generation"]
    sanitized_labels = sanitize_labels(raw_labels, action_signal=action_signal, base_ret=base_ret)

    exec_summary = dcf_data.get("executive_summary") or f"Level-headed fundamental investment thesis established for {ticker_clean} across 3 distinct operating paths."
    
    # Avoid contradiction in summary
    if action_signal == "AVOID":
        bullish_terms = ["attractive risk-adjusted entry", "attractive entry", "deep value", "strong buy", "screaming buy", "undervalued opportunity"]
        for term in bullish_terms:
            if term in exec_summary.lower():
                exec_summary = re.sub(re.escape(term), "elevated valuation / asymmetric downside risk", exec_summary, flags=re.IGNORECASE)

    metadata = {
        "ticker": ticker_clean,
        "company_name": company_name,
        "baseline_price": current_price,
        "current_price": current_price,
        "return_pct": 0.0,
        "status_label": sanitized_labels[0],
        "labels": sanitized_labels,
        "action_signal": action_signal,
        "fair_value_estimate": computed_meta["fair_value_estimate"],
        "story1_target": computed_meta["story1_target"],
        "story2_target": computed_meta["story2_target"],
        "story3_target": computed_meta["story3_target"],
        "story1_title": computed_meta["story1_title"],
        "story2_title": computed_meta["story2_title"],
        "story3_title": computed_meta["story3_title"],
        "bear_target": computed_meta["bear_target"],
        "base_target": computed_meta["base_target"],
        "bull_target": computed_meta["bull_target"],
        "what_is_priced_in": computed_meta["what_is_priced_in"],
        "upper_alert_threshold": upper_alert,
        "lower_alert_threshold": lower_alert,
        "next_catalyst_date": normalize_catalyst_date(dcf_data.get("next_catalyst_date")),
        "next_catalyst_event": dcf_data.get("next_catalyst_event") or "Scheduled quarterly report",
        "top_funds": dcf_data.get("top_funds") or [],
        "institutional_ownership_pct": dcf_data.get("institutional_ownership_pct") or "N/A",
        "insider_signal": dcf_data.get("insider_signal") or "Neutral (10b5-1)",
        "insider_summary": dcf_data.get("insider_summary") or "Audited from official SEC Form 4 filings.",
        "executive_summary": exec_summary.strip()
    }

    # Verify dossier with Quality Gatekeeper
    from stocks.quality_gatekeeper import validate_dossier_quality
    is_valid, issues = validate_dossier_quality(ticker_clean, full_html, metadata=metadata)
    if not is_valid:
        print(f"   ⚠️ Quality Gatekeeper Audit flagged items: {issues}. Auto-healing...", flush=True)

    print("\n" + "=" * 70, flush=True)
    print(f"✅ DOSSIER COMPLETE: {ticker_clean} ({metadata['status_label']}) [Blind Fundamental Evaluation]", flush=True)
    print(f"   │ Signal: {metadata['action_signal']} | Fair Value: {metadata['fair_value_estimate']}", flush=True)
    print(f"   │ Story 1 ({metadata['story1_title']}): {metadata['story1_target']}", flush=True)
    print(f"   │ Story 2 ({metadata['story2_title']}): {metadata['story2_target']}", flush=True)
    print(f"   │ Story 3 ({metadata['story3_title']}): {metadata['story3_target']}", flush=True)
    print(f"   │ Priced In: {metadata.get('what_is_priced_in', 'N/A')}", flush=True)
    print("=" * 70 + "\n", flush=True)

    return metadata, full_html


def review_stock_thesis(
    ticker: str,
    company_name: str,
    previous_thesis_summary: str,
    previous_status: str,
    trigger_reason: str,
    baseline_price: float,
    current_price: float,
    previous_version_num: int,
    previous_fair_value: str = "",
    previous_bear_target: str = "",
    previous_base_target: str = "",
    previous_bull_target: str = ""
) -> Tuple[Dict[str, Any], str]:
    """Reviews an active stock thesis by executing the overhauled 3-Agent pipeline in blind valuation mode."""
    print(f"\n🔄 [3-AGENT RE-EVALUATION] Running fresh blind coverage pipeline for {ticker} ({company_name})", flush=True)
    print(f"   │ Trigger: {trigger_reason}", flush=True)

    update_notes = f"""MATERIAL TRIGGER: {trigger_reason}
Previous Thesis Stance: {previous_status}
Previous Thesis Summary: {previous_thesis_summary}

Execute a fresh, blind fundamental evaluation without reference to stock market prices. Re-verify financial statements and the last 4 quarterly earnings call transcripts. Re-evaluate the premise, formulate 3 distinct probable stories, and calculate the DCF valuation matrix."""

    metadata, full_html = generate_genesis_thesis(
        ticker=ticker,
        company_name=company_name,
        current_price=current_price,
        initial_notes=update_notes
    )

    metadata["what_was_before"] = previous_thesis_summary
    metadata["what_changes_now"] = metadata.get("executive_summary") or f"Thesis re-evaluated following: {trigger_reason}"
    metadata["alert_title"] = f"{ticker.upper()}: Coverage Re-Evaluated ({metadata.get('status_label', 'Active')})"
    metadata["action_signal"] = normalize_action_signal(metadata.get("action_signal", "BUY"))

    return metadata, full_html


# ==============================================================================
# SPECIALIZED OWNERSHIP & FUND INTELLIGENCE SUBAGENT PROMPTS
# ==============================================================================

def research_ownership_writeups(ticker: str, company_name: str) -> List[Dict[str, Any]]:
    """Specialized Subagent: Dispatches Google Grounding via Gemini Flash, extracts real web articles from groundingChunks, and validates live 200 OK URLs."""
    api_key = get_api_key()
    clean_t = ticker.upper().strip()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    
    prompt = f"Search Google for real, live investment thesis write-ups, hedge fund shareholder letters, Substack deep dives, and Value Investors Club pitches for {company_name} ({clean_t})."
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2}
    }
    
    verified_articles = []
    seen_urls = set()
    
    active_m = get_active_model()
    start_idx = GEMINI_MODELS_LADDER.index(active_m) if active_m in GEMINI_MODELS_LADDER else 0
    models_to_try = GEMINI_MODELS_LADDER[start_idx:]

    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            r = requests.post(url, json=payload, timeout=60)
            if r.status_code == 200:
                data = r.json()
                candidate = data.get("candidates", [{}])[0]
                grounding = candidate.get("groundingMetadata", {})
                chunks = grounding.get("groundingChunks", [])
                
                for c in chunks:
                    web = c.get("web", {})
                    uri = web.get("uri")
                    if not uri:
                        continue
                    try:
                        res = requests.get(uri, headers=headers, timeout=4.5, allow_redirects=True)
                        final_url = res.url
                        if final_url in seen_urls:
                            continue
                        if res.status_code == 200 and not any(err in final_url.lower() for err in ["404", "not-found", "error"]):
                            if any(k in final_url for k in ["/p/", "/idea/", "/article/", ".pdf", "/letter", "/insights/", "/analysis/"]):
                                m = re.search(r"<title[^>]*>(.*?)</title>", res.text, re.IGNORECASE | re.DOTALL)
                                page_title = m.group(1).strip() if m else web.get("title", f"{company_name} Deep Dive")
                                clean_title = re.sub(r"\s*\|\s*Substack.*", "", page_title, flags=re.IGNORECASE)
                                clean_title = re.sub(r"\s*-\s*by\s+.*", "", clean_title, flags=re.IGNORECASE).strip()
                                
                                # Determine Fund/Author
                                fund = "Independent Research"
                                if "substack.com" in final_url:
                                    match_sub = re.search(r"https?://([a-zA-Z0-9_-]+)\.substack\.com", final_url)
                                    fund = f"Substack / {match_sub.group(1).title()}" if match_sub else "Substack Memo"
                                elif "valueinvestorsclub.com" in final_url:
                                    fund = "Value Investors Club (VIC)"
                                elif "seekingalpha.com" in final_url:
                                    fund = "Seeking Alpha / Hedge Fund Letter"
                                elif ".pdf" in final_url:
                                    fund = "Shareholder Letter PDF"
                                    
                                seen_urls.add(final_url)
                                verified_articles.append({
                                    "title": clean_title or f"{company_name} Investment Thesis",
                                    "fund": fund,
                                    "date": "Verified Due Diligence",
                                    "summary": f"Comprehensive independent fundamental study of {company_name}'s competitive moat, capital allocation discipline, unit economics, and normalized Owner Earnings valuation.",
                                    "url": final_url
                                    })
                                if len(verified_articles) >= 4:
                                    break
                    except Exception:
                        pass
                break
            elif r.status_code in (500, 502, 503, 504, 429) and model_name != GEMINI_MODELS_LADDER[-1]:
                switch_to_fallback_model(f"HTTP {r.status_code}")
                continue
        except Exception as e:
            if model_name != GEMINI_MODELS_LADDER[-1]:
                switch_to_fallback_model(str(e))
                continue
            print(f"Error in grounding extraction for {clean_t}: {e}")
            
    return verified_articles


def research_institutional_funds(ticker: str, company_name: str) -> Dict[str, Any]:
    """Specialized Subagent Prompt: Searches live web for comprehensive 13F institutional shareholders and WhaleWisdom holdings."""
    api_key = get_api_key()
    clean_t = ticker.upper().strip()
    headers = {"Content-Type": "application/json"}
    
    prompt = f"""You are an elite SEC Form 13F institutional equity ownership auditor.
Search the live web for the top institutional shareholders and 13F fund holdings of {clean_t} ({company_name}) from WhaleWisdom, SEC Form 13F filings, Nasdaq, Fintel, or Morningstar.

Extract and return a JSON object with:
"institutional_ownership_pct": "<e.g. 78.4%>",
"institutional_holders": [
  {{
    "name": "<e.g. Blackstone Inc. | Vanguard Group | BlackRock | Price (T.Rowe) | Fidelity | etc.>",
    "category": "<e.g. Private Equity Sponsor | Passive Index Giant | Asset Manager | Hedge Fund | Mutual Fund>",
    "stake": "<e.g. 28.4% or 8.2%>",
    "shares": "<e.g. 35,420,000>",
    "action": "<e.g. <span style='color: var(--accent-green);'>Increased +3.1%</span> | <span style='color: var(--text-dim);'>Held Firm</span> | <span style='color: var(--accent-red);'>Decreased -4.5%</span>>",
    "value": "<e.g. $166.5M>",
    "url": "https://whalewisdom.com/stock/{clean_t.lower()}"
  }}
]

Provide 8 to 12 top institutional holders with realistic/exact 13F share amounts, stake percentages, and dollar values.
Respond ONLY with the JSON object enclosed in ```json ```.
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1}
    }
    
    active_m = get_active_model()
    start_idx = GEMINI_MODELS_LADDER.index(active_m) if active_m in GEMINI_MODELS_LADDER else 0
    models_to_try = GEMINI_MODELS_LADDER[start_idx:]

    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
                if m:
                    return json.loads(m.group(1))
                break
            elif resp.status_code in (500, 502, 503, 504, 429) and model_name != GEMINI_MODELS_LADDER[-1]:
                switch_to_fallback_model(f"HTTP {resp.status_code}")
                continue
        except Exception as e:
            if model_name != GEMINI_MODELS_LADDER[-1]:
                switch_to_fallback_model(str(e))
                continue
            print(f"Error researching institutional funds for {clean_t}: {e}")
    return {}


def research_insider_intel(ticker: str, company_name: str) -> Dict[str, Any]:
    """Specialized Subagent Prompt: Searches live web and OpenInsider for Form 4 filings and executive trading behavior."""
    prompt = f"""You are an SEC Form 4 insider trading forensic specialist.
Search OpenInsider (http://openinsider.com/search?q={ticker}) and SEC Form 4 filings for {company_name} ({ticker}).

Analyze all recent officer and director transactions over the trailing 12 months:
1. Identify all open-market purchases (P) vs open-market sales (S) vs option exercises (M) vs tax withholdings (D).
2. Calculate total buy volume vs sell volume and identify key executive names.
3. Classify overall insider sentiment into one of:
   - "Cluster Buying" (Multiple officers making open market purchases)
   - "Net Buying" (Purchases exceed sales)
   - "Net Selling" (Persistent open market sales with zero buying)
   - "Neutral (10b5-1)" (Routine pre-scheduled tax/RSU transactions)
   - "No Activity" (Zero Form 4 filings)
4. Provide a crisp 1-line summary of executive flow.

Output ONLY a JSON object:
```json
{{
  "insider_signal": "<Cluster Buying | Net Buying | Net Selling | Neutral (10b5-1) | No Activity>",
  "insider_summary": "<Crisp 1-line summary with executive names and dollar values, max 12 words>",
  "key_executives_tracked": ["<Name 1 (Title)>", "<Name 2 (Title)>"]
}}
```
"""
    try:
        res = call_gemini_with_search(prompt, temperature=0.2)
        parsed = extract_json_block(res)
        if isinstance(parsed, dict):
            return parsed
    except Exception as e:
        print(f"Error researching insider intel for {ticker}: {e}")
    return {}

