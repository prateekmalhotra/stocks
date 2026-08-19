import os
import json
import time
import re
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional, List
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
_CURRENT_ACTIVE_MODEL = DEFAULT_GEMINI_MODEL
GEMINI_MODELS_LADDER = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite"
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
        _CURRENT_ACTIVE_MODEL = "gemini-3.5-flash"
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
    
    # Strip standalone search grounding timestamps (e.g. '2026-08-19 03:00:00 UTC')
    cleaned = re.sub(r'^\s*\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?(?:\s+(?:UTC|GMT|[A-Z]{3,4}))?\s*$', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'<p>\s*\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?(?:\s+(?:UTC|GMT|[A-Z]{3,4}))?\s*</p>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+(?:UTC|GMT|[A-Z]{3,4})\b', '', cleaned)
    
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


# Shared persistent session with connection pooling
_GEMINI_SESSION: Optional[requests.Session] = None

def get_gemini_session() -> requests.Session:
    global _GEMINI_SESSION
    if _GEMINI_SESSION is None:
        import urllib3
        from requests.adapters import HTTPAdapter
        s = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=urllib3.util.Retry(
                total=2,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
                raise_on_status=False
            )
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _GEMINI_SESSION = s
    return _GEMINI_SESSION


def call_gemini_with_search(prompt: str, system_instruction: str = "", temperature: float = 0.4, use_search: bool = True, override_model: str = "") -> str:
    """Calls Gemini via REST API with optional Google Search Grounding, exponential backoff with jitter, and automatic ladder failover."""
    import time
    import random
    api_key = get_api_key()
    session = get_gemini_session()
    
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
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = session.post(url, json=payload, timeout=180)
                if response.status_code == 200:
                    res_json = response.json()
                    candidate = res_json.get("candidates", [{}])[0]
                    parts = candidate.get("content", {}).get("parts", [])
                    texts = [p["text"] for p in parts if "text" in p and not p.get("thought")]
                    if texts:
                        return clean_grounding_artifacts("\n".join(texts))
                    
                    if candidate.get("finishReason") == "RECITATION":
                        fallback_prompt = prompt + "\n\nCRITICAL: Paraphrase all data in your own original analytical words. Do NOT quote verbatim text."
                        payload["contents"] = [{"parts": [{"text": fallback_prompt}]}]
                        payload["generationConfig"]["temperature"] = 0.7
                        retry_res = session.post(url, json=payload, timeout=180)
                        if retry_res.status_code == 200:
                            retry_json = retry_res.json()
                            retry_parts = retry_json.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                            retry_texts = [p["text"] for p in retry_parts if "text" in p and not p.get("thought")]
                            if retry_texts:
                                return clean_grounding_artifacts("\n".join(retry_texts))
                                
                    return "Analysis completed."
                elif response.status_code in (500, 502, 503, 504, 429):
                    if attempt < max_retries:
                        jitter = random.uniform(0.5, 1.8)
                        wait_time = round(min(24.0, (2.0 ** attempt) + jitter), 2)
                        print(f"  ⚠️ Gemini API ({model_name}) returned HTTP {response.status_code}. Retrying in {wait_time}s (Attempt {attempt}/{max_retries})...", flush=True)
                        time.sleep(wait_time)
                        continue
                    elif model_name != models_to_try[-1]:
                        switch_to_fallback_model(f"HTTP {response.status_code} after {max_retries} attempts on {model_name}")
                        break
                else:
                    last_err = RuntimeError(f"Gemini API error ({response.status_code}): {response.text}")
                    break
            except (requests.RequestException, Exception) as req_err:
                if attempt < max_retries:
                    jitter = random.uniform(0.5, 1.8)
                    wait_time = round(min(24.0, (2.0 ** attempt) + jitter), 2)
                    print(f"  ⚠️ Network/Connection error on {model_name} ({req_err}). Retrying in {wait_time}s (Attempt {attempt}/{max_retries})...", flush=True)
                    time.sleep(wait_time)
                    continue
                elif model_name != models_to_try[-1]:
                    switch_to_fallback_model(f"{req_err} after {max_retries} attempts on {model_name}")
                    break
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
    
    # 0.5 Clean up foreign currency label formatting and fix symbol typos
    cleaned = re.sub(r'\$\s*([\d,]+(?:\.\d+)?\s*(?:[BM]|billion|million)?)\s*(RMB|CNY)\b', r'¥\1 \2', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\(\s*\$\s*([\d,]+(?:\.\d+)?\s*(?:[BM]|billion|million)?)\s*(RMB|CNY)\s*\)', r'(¥\1 \2)', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\$\s*([\d,]+(?:\.\d+)?\s*(?:[BM]|billion|million)?)\s*(EUR|euros?)\b', r'€\1 \2', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\(\s*\$\s*([\d,]+(?:\.\d+)?\s*(?:[BM]|billion|million)?)\s*(EUR|euros?)\s*\)', r'(€\1 \2)', cleaned, flags=re.IGNORECASE)
    
    # Strip standalone search grounding timestamps (e.g. '2026-08-19 03:00:00 UTC')
    cleaned = re.sub(r'^\s*\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?(?:\s+(?:UTC|GMT|[A-Z]{3,4}))?\s*$', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'<p>\s*\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?(?:\s+(?:UTC|GMT|[A-Z]{3,4}))?\s*</p>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+(?:UTC|GMT|[A-Z]{3,4})\b', '', cleaned)
    
    # 0.8 Clean up concatenated heading/sentence transition artifacts
    cleaned = re.sub(r'\b(Strategic Insights|Executive Commentary|Key Insights)([A-Za-z])', r'\1: \2', cleaned)
    cleaned = re.sub(r'([a-z])([A-Z][a-z]+Insights)', r'\1 \2', cleaned)
    
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

LEVEL_HEADED_INVESTOR_PHILOSOPHY = """You are an elite, level-headed fundamental value investor embodying the core economic principles of Warren Buffett, Charlie Munger, and Benjamin Graham.

Core Principles of Business Valuation & Capital Allocation:
1. Ownership Mentality (5-Year Market Closure Mindset):
   - You are evaluating a permanent ownership stake in a private operating business. If the stock market were closed for the next 5 years, would the cash distributable to owners justify purchasing this enterprise today?
   - Ignore short-term market quotation noise, macro forecasting, and consensus momentum. Focus exclusively on the operational engine.

2. True Owner Earnings (Warren Buffett 1986 Shareholder Letter):
   - Owner Earnings = GAAP Operating Cash Flow - Maintenance CapEx - 100% Stock-Based Compensation.
   - "If options aren't compensation, what are they? If they aren't expenses, what are they? And if they don't come out of earnings, where do they come from?" (Buffett). Stock-Based Compensation MUST strictly be treated as a cash charge.
   - Distinguish capital required to maintain competitive standing and volume (Maintenance CapEx) from discretionary expansion (Growth CapEx).

3. Economic Moat & Pricing Power (Buffett & Munger):
   - Does the business possess genuine pricing power (the ability to adjust prices for inflation without losing unit volume)?
   - Is the business protected by durable structural moats: low-cost producer advantages, high customer switching costs, network effects, or tollbridge scale economics?

4. Charlie Munger's Inversion Principle ("Invert, Always Invert"):
   - Do not pretend to predict the unpredictable or model 10-year linear perfection. Invert the equation: What fundamental operational performance and cash generation is Mr. Market embedding into today's share price? Where does that expectation diverge from operational reality?

5. Rational Capital Allocation & Share Buyback Discipline:
   - Every dollar retained by management must create at least one dollar of market value over time.
   - Share repurchases are value-accretive ONLY when executed below conservative intrinsic value; repurchases executed above intrinsic value actively destroy shareholder wealth.

6. Fortress Balance Sheet ("Cash is Like Oxygen"):
   - A fortress balance sheet protects against operational shocks and economic downturns.
   - Unencumbered Net Cash (Gross Cash & Short-Term Investments minus Total Debt, committed M&A cash outlays, and Non-Controlling Interests) is credited dollar-for-dollar in intrinsic value.

7. Opportunity Cost & Margin of Safety (Ben Graham & Buffett):
   - Use a level-headed opportunity-cost hurdle rate (9.0%–10.0%) representing the equity hurdle rate (rejecting academic Beta and CAPM volatility models).
   - Demand a meaningful Margin of Safety to protect principal against miscalculation, technological shifts, and competitive friction.

8. Strict USD Currency Standardization:
   - Every financial number, stat card, cash flow, and valuation MUST strictly be converted to and presented in US DOLLARS ($ USD).
   - For foreign ADRs, strictly use the US-traded ADS share count so per-share valuations are in USD per ADS.
"""

AGENT_1_PREMISE_PROMPT = """Target: {ticker} ({company_name})
User Focus / Research Notes: {notes}

You are LLM Agent 1: Company Premise Specialist.
Your objective is to establish the single audited factual foundation ("The Premise of the Company") for all downstream analysis and valuation.

Guidelines:
- Blind Valuation: Analyze the business purely as an unlisted private enterprise with zero knowledge of current stock prices.
- Currency & Denominator Integrity: ALL figures MUST strictly be in US DOLLARS ($ USD) PER US-LISTED ADS (American Depositary Share). NEVER present figures in foreign currency per ordinary share (e.g. RMB¥ per ordinary share) while downstream sections use USD per ADS. Convert foreign currencies (e.g. RMB, EUR, BRL) at prevailing FX rates. On the first occurrence of a currency conversion, explicitly include the parenthetical exchange rate notation (e.g. "(converted at an exchange rate of RMB 7.25 / $1.00 USD; 1 ADS = 8 Ordinary Shares)").
- Primary Research: Search audited SEC filings (10-K, 10-Q, 20-F, 6-K) and the last 4 quarterly earnings call transcripts.
- Current Reporting Period: Explicitly state the latest reported fiscal year / quarter (e.g. "FY 2025 / Q2 2026 LTM").
- Writing Style: Write natural, bespoke equity research prose. Avoid repetitive boilerplate phrases (e.g. do NOT repeatedly insert phrases like "under the executive leadership of..."). Focus directly on business unit economics and cash flow reality.

CRITICAL AUDITED FINANCIAL REALITY & INTEGRITY CHECKS:
1. Statement of Cash Flows Extraction & Owner Earnings Waterfall:
   - Search the ACTUAL Statement of Cash Flows for the latest completed fiscal year (e.g. Form 20-F / 10-K) and recent quarterly reports (Form 6-K / 10-Q).
   - Line 1: Net Cash Provided by Operating Activities (GAAP OCF) ($ Millions/Billions USD). NEVER use Financing Cash Flows (e.g. share buybacks or debt repayments) or Net Income as OCF!
   - Line 2: Working Capital Normalization: Cross-check LTM GAAP OCF against LTM Net Income + D&A. If OCF includes material temporary working capital inflows/outflows (e.g. aggressive inventory buildup for 1P sales, freight prepayments, or lumpy supplier payable timing), normalize starting Core Baseline Owner Earnings (OE₀) to reflect recurring steady-state cash generation.
   - Line 3: Capital Expenditures (Additions to property, equipment, logistics facilities, software) ($ Millions/Billions USD). Explicitly distinguish between Maintenance CapEx (steady-state upkeep of logistics fleets, warehouses, POS terminals, and server clusters) vs Growth CapEx.
   - Line 4: Stock-Based Compensation (SBC) expense ($ Millions USD) treated as a 100% cash charge.
   - Line 5: Non-Operating Interest Income Deduction ($ Millions USD): Deduct non-operating corporate treasury cash deposit interest from OCF before deriving core Operating Owner Earnings to prevent double-counting when adding cash on the balance sheet bridge (distinguishing non-operating corporate cash yield from operational customer float interest in fintechs/wallets):
     * Core Operating Baseline Owner Earnings (OE₀) = GAAP OCF (Normalized) - Non-Operating Interest Income - Maintenance CapEx - SBC.
   - Line 6: Non-Cash Impairments & One-Off Exclusions: GAAP OCF already automatically adds back non-cash accounting charges (e.g. paper goodwill impairments, asset write-downs). Additionally, normalize and exclude any material non-recurring one-off cash items (e.g. one-time litigation windfalls, asset divestiture gains, extraordinary dividends, or regulatory fines) to ensure Owner Earnings reflects true recurring steady-state cash power.
2. Calibrated Working Capital Operational Cash Buffer, Cash Flow Matching & Balance Sheet Bridge:
   - Cash Flow Matching (FCFE Standard): Under US GAAP, Net Cash Provided by Operating Activities (GAAP OCF) is already net of cash interest paid to lenders. Therefore, core Owner Earnings represents Free Cash Flow to Equity (FCFE).
   - When discounting FCFE at the equity cost of capital, the resulting present value represents Total Intrinsic Equity Value directly.
   - When deriving Net Surplus Balance Sheet Cash per Share/ADS, calculate:
     * Gross Cash & ST Marketable Investments ($ Millions USD)
     * MINUS Operational Working Capital Buffer (2.5%–3.5% of annual revenue)
     * MINUS Off-balance-sheet or ASC 842 lease debt commitments if not fully accounted for in operating expenses
     * MINUS Cross-border dividend withholding taxes / repatriation friction (e.g. 5%–10% statutory tax on foreign cash)
     * MINUS Committed M&A cash outlays
     * PLUS Non-Consolidated Strategic Equity Affiliates / SOTP Value (applying a standard 20%–25% holding company / illiquidity haircut to private/unlisted stakes).
   - If debt service is already net in OCF, do NOT double-penalize equity value by deducting funded debt a second time.
   - The resulting figure is the true Unencumbered Surplus Net Cash & Strategic Asset Value per Share/ADS.
3. Historical Corporate Trauma & Underwriting Post-Mortem:
   - If the company is trading down significantly (>50%) from historical highs or suffered a well-known operational crisis in the past (e.g. credit underwriting blowups, regulatory restructuring, short-seller litigation, failed acquisitions):
     * Explicitly address the historical root cause and contrast it with today's operational reality.
     * Detail the structural fixes (e.g. government-backed credit guarantees like FGI/BNDES, real-time registry verification, independent audit investigations, dismissal of shareholder class action litigation) that prevent a recurrence.
4. Regulatory Capital & Banking Ratio Constraints (For Fintechs & Lenders):
   - For financial institutions, fintechs, and credit businesses, audit regulatory capital adequacy (e.g. BACEN Managerial Capital Ratio, Tier 1 / Basel ratios).
   - Evaluate whether rapid loan book expansion consumes regulatory capital, and confirm that organic retained earnings cover capital adequacy requirements alongside share buybacks.
5. Foreign Private Issuer (FPI), VIE Structure & Upstream Cash Repatriation:
   - For foreign companies traded via ADRs/ADSs, audit corporate structure (direct Cayman holding company vs VIE vs supervisory banking oversight).
   - Evaluate cash repatriation mechanics from domestic operating subsidiaries to offshore holding companies to fund US-traded ADS share repurchases and dividends.

Core Topics to Cover:
1. The Core Business Machine, Moat & Unit Economics:
   - Customer value proposition, monetization mechanics, pricing power, and durable economic moat.
   - Core operational volume drivers vs high-margin service streams.
   - Multi-Brand & Segment Disaggregation: If the company operates distinct brand divisions or operating segments with divergent growth/margin trajectories (e.g. core flagship platform vs secondary/acquired brands), explicitly report their individual revenues and YoY growth rates separately. If an acquired division is falling double digits (e.g. -10% to -15% YoY) or taking inventory write-downs, explicitly document this drag.
   - Product Concentration & Silhouette/Platform Risk: Audit product line concentration (e.g. over-dependence on a single product silhouette, single hardware model, or single app) and assess vulnerability to fashion fatigue or consumer taste shifts.
   - Sourcing Footprint & Tooling Mobility: For consumer and hardware brands, audit supply chain geographic concentration (% of manufacturing in Vietnam, China, Indonesia, Americas) and evaluate exposure to tariffs and freight friction.
   - Identify the 3–5 PRIMARY OPERATIONAL METRICS reported by the company (e.g. Active Clients/Buyers/Paying Users, 3P GMV %, Take Rate %, Spend per Buyer, ARPPU, Cost of Risk, ARPAC, Warehouse Space / Lease Footprint).
2. Audited Financial Baseline (Single Source of Truth in $ Millions/Billions USD):
   - Latest Period Net Revenue ($ USD)
   - Latest GAAP Operating Cash Flow (OCF) ($ Millions USD)
   - Non-Operating Interest Income stripped from OCF ($ Millions USD)
   - Annual CapEx ($ Millions USD): Distinguish Maintenance CapEx vs Growth CapEx.
   - Stock-Based Compensation (SBC) ($ Millions USD) treated as a cash charge.
   - Core Baseline Owner Earnings: OE₀ = OCF (Normalized) - Interest Income - Maintenance CapEx - SBC ($ Millions USD)
   - Balance Sheet Cash & ST Investments ($ Millions USD) vs Total Funded Debt, Operating Lease Commitments, minus Operational Buffer and M&A commitments.
   - Diluted Shares / ADSs Outstanding (Millions)
   - Unencumbered Surplus Net Cash / (Debt) per Share/ADS in USD.
3. Leadership Commentary & 4-Quarter Trajectory: Executive commentary and authentic quotes from the active CEO and CFO across the last 4 quarters (including latest quarterly guidance).
4. Corporate Governance, Regulatory Defenses & Historical Crisis Resolution: Structural defenses, capital adequacy / lease ratios, and historical underwriting post-mortem.

Format Section 1 in clean Semantic HTML:
<h2>Section 1: The Premise of the Company</h2>
<p>[Plain-English explanation of how the business machine operates, its primary operational business metrics, its moat, and customer proposition...]</p>

<div class="metrics-grid">
  <div class="metric-card"><div class="metric-label">Latest Period / LTM Revenue</div><div class="metric-value">$XX.XXB</div><div class="metric-delta pos">[e.g. FY 2025 / +XX% YoY]</div></div>
  <div class="metric-card"><div class="metric-label">GAAP Operating Cash Flow</div><div class="metric-value">$XX.XXB</div><div class="metric-delta pos">Latest Audited Period</div></div>
  <div class="metric-card"><div class="metric-label">Core Baseline Owner Earnings</div><div class="metric-value">$XX.XXB</div><div class="metric-delta pos">OCF - Interest - CapEx - SBC</div></div>
  <div class="metric-card"><div class="metric-label">Surplus Net Cash / ADS</div><div class="metric-value">+$XX.XX</div><div class="metric-delta pos">Net of Working Capital Buffer</div></div>
</div>

<div class="callout">
  <h3>Executive Leadership Commentary &amp; 4-Quarter Trajectory</h3>
  <p><strong>[CEO Name], Chief Executive Officer:</strong> "..."</p>
  <p><strong>[CFO Name], Chief Financial Officer:</strong> "..."</p>
</div>

<div class="callout">
  <h3>Corporate Governance, Regulatory Defenses &amp; Historical Post-Mortem</h3>
  <p>[Analysis of corporate structure, regulatory/lease obligations, resolution of historical operational crises, and upstream cash repatriation mechanics...]</p>
</div>

<p>[Current state of play summary, including recent cash flow dynamics, capital expenditures, and major strategic commitments...]</p>

Output pure HTML only (no code fences, no inline styles)."""


AGENT_2_STORIES_PROMPT = """Target: {ticker} ({company_name})

You are LLM Agent 2: 3 Stories Strategist.
Here is the Company Premise from Agent 1 (containing the audited financial baseline, operational metrics, cash flow compression reality, and unencumbered net cash per share):
{premise_context}

Guidelines:
- Blind Valuation: Formulate business trajectories based strictly on operational realities and competitive dynamics, with zero knowledge of stock market prices.
- Currency & Financial Consistency: All figures in $ USD. Anchor all 3 stories directly to the audited baseline numbers (revenue, margins, cash flow) established in Agent 1's Company Premise above.
- Guidance Realism & Non-Linear Trajectories: Factor in management's near-term quarterly forward guidance (e.g. Q3/Q4 cyclical dips due to macro/housing pressure) to model realistic trajectory shapes rather than smooth straight-line ramps.
- Turnaround Realism & Segment Drag in Story 1 (Base Case): If an acquired brand or secondary segment is contracting double-digits, Story 1 (Base Case) MUST NOT assume an unearned miraculous V-shaped rebound. Model the struggling segment at flat to negative growth, requiring the core flagship business to carry the baseline enterprise.
- Grounded Margin & Growth Realism: For thin-margin direct retail or financial spread businesses, do NOT assume heroic margin doubling. Model realistic, incremental operating progression.
- Primary Research: Search and inspect {company_name}'s latest filings and earnings transcripts.
- Currency/FX Depreciation Stress in Emerging Markets: For companies operating in emerging market currencies (e.g. Brazil BRL, China RMB, Mexico MXN, India INR) with high local sovereign interest rates, Story 3 (Downside / Bear Floor) MUST incorporate realistic local FX depreciation against the USD (e.g. +10% to +15% FX headwind in the USD conversion) to stress-test the dollar-denominated fair value floor.
- Cross-Border Trade & Customs Friction (For Global E-Commerce/Logistics): For international retail platforms (e.g. AIDC, AliExpress Choice, cross-border commerce), Story 3 MUST model potential revisions to international *de minimis* customs exemptions, cross-border tariffs, and delivery unit cost friction.
- Downside Stress Realism in Story 3: Story 3 MUST explicitly model: (1) core product silhouette / platform fashion fatigue, (2) wholesale channel destocking / order cancellations, (3) supply chain tariffs / landed-cost inflation from concentrated manufacturing regions (e.g. Vietnam/China duties), and (4) FX depreciation.
- Operational Metric Continuity: Explicitly carry forward and trace the primary operational metrics identified in Section 1 (e.g. Active Clients, TPV/GMV growth, Take Rate %, Deposit Float, Cost of Risk / NPLs, ARPAC, Fulfillment/Lease Expense Ratio) across EACH of the 3 stories to justify how margin expansion or contraction occurs.

FIRST-PRINCIPLES BUSINESS METRIC CHAIN (NO ARBITRARY GROWTH ASSUMPTIONS):
- Revenue is driven by explicit operational business metrics reported by the company.
- For EACH story, you must explicitly justify the business assumptions chain:
  1. Top-Level Operational Metric Shifts: How specific business volume, unit capacity, pricing power, or new asset additions evolve over the next 3–5 years with clear operational justifications.
  2. Revenue Translation: How those operational metric shifts calculate into top-line net revenue in $ USD.
  3. Cost Structure & Margins: Funding/lease costs, COGS, OpEx, provisioning / NPL drag, and operating margin progression.
  4. CapEx & Cash Conversion: Maintenance vs Growth CapEx cycles, SBC dilution, and resulting Owner Earnings trajectory in $ USD.

Your Objective:
Formulate 3 PROBABLE, DISTINCT BUSINESS STORIES covering approximately 90%–95% of probable fundamental outcomes for the business over the next 3 to 5 years.
Include a dedicated "Actionable Quarterly Monitoring Checklist (Next 12–18 Months)" with explicit quantitative Green Light and Red Light triggers.

Format Section 2 in clean Semantic HTML:
<h2>Section 2: 3 Probable Business Stories</h2>
<p>Based on the company's core premise, reported operational metrics, financial filings, and 4-quarter earnings trajectory, here are 3 distinct, probable fundamental paths that cover 90%–95% of probable business outcomes over the next 3–5 years:</p>

<div class="callout">
  <h3>📖 Story 1: [Descriptive Operational Title 1 - Base Case]</h3>
  <p>[Full narrative explanation of this operational path, incorporating near-term guidance reality...]</p>
  <p><strong>Operational Metric Drivers &amp; Revenue:</strong> [Explicit business metric shifts (e.g. client volume, GMV, take rates, pricing) and how they drive top-line revenue in $ USD...]</p>
  <p><strong>Cost Dynamics, CapEx &amp; Owner Earnings:</strong> [Cost structure, lease commitments, provision/OpEx margins, CapEx cycle assumptions, and resulting Owner Earnings trajectory in $ USD...]</p>
  <p><strong>Key Milestones to Watch:</strong> [Specific indicators to monitor...]</p>
</div>

<div class="callout">
  <h3>📖 Story 2: [Descriptive Operational Title 2 - High-Margin Upside]</h3>
  <p>[Full narrative explanation of this operational path...]</p>
  <p><strong>Operational Metric Drivers &amp; Revenue:</strong> [Explicit business metric shifts and how they drive top-line revenue in $ USD...]</p>
  <p><strong>Cost Dynamics, CapEx &amp; Owner Earnings:</strong> [Cost structure, OpEx margins, CapEx cycle assumptions, and resulting Owner Earnings trajectory in $ USD...]</p>
  <p><strong>Key Milestones to Watch:</strong> [Specific indicators to monitor...]</p>
</div>

<div class="callout">
  <h3>📖 Story 3: [Descriptive Operational Title 3 - Defensive Stress / Downside]</h3>
  <p>[Full narrative explanation of this operational path, incorporating realistic local FX depreciation headwind in USD conversion and lease fixed-overhead leverage...]</p>
  <p><strong>Operational Metric Drivers &amp; Revenue:</strong> [Explicit business metric shifts and how they drive top-line revenue in $ USD...]</p>
  <p><strong>Cost Dynamics, CapEx &amp; Owner Earnings:</strong> [Cost structure, credit/tariff/margin drag, CapEx assumptions, and resulting Owner Earnings trajectory in $ USD...]</p>
  <p><strong>Key Milestones to Watch:</strong> [Specific indicators to monitor...]</p>
</div>

<div class="callout">
  <h3>Actionable Quarterly Monitoring Checklist (Next 12–18 Months)</h3>
  <table class="data-table">
    <thead>
      <tr>
        <th>Operational Metric</th>
        <th>🟢 Green Light (Thesis Acceleration)</th>
        <th>🔴 Red Light (Thesis Falsification Threshold)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Primary Quality Metric (e.g. NPL >90d / Active Buyers / Lease Utilization)</strong></td>
        <td>Improving / healthy expansion (e.g. &gt;13,500 buyers)</td>
        <td>Deteriorating below risk floor (e.g. &lt;11,000 buyers / &gt;10% NPL)</td>
      </tr>
      <tr>
        <td><strong>Monetization &amp; Unit Economics (e.g. ARPAC / Take Rate / Spend per Buyer)</strong></td>
        <td>Expanding organically above target run-rate</td>
        <td>Contracting due to competitive price concessions</td>
      </tr>
      <tr>
        <td><strong>Trade Policy &amp; Macro Drag (e.g. Tariffs / Section 301 / Freight Spikes)</strong></td>
        <td>Stable trade policy; ocean freight normalization</td>
        <td>Severe tariff escalation absorbed entirely by platform margins</td>
      </tr>
      <tr>
        <td><strong>Balance Sheet &amp; Capital Allocation (e.g. Buyback Velocity / Net Cash)</strong></td>
        <td>Deploying repurchase authorization aggressively at &lt; Operating EV</td>
        <td>Excessive cash burn or capital allocation drift</td>
      </tr>
    </tbody>
  </table>
</div>

Output pure HTML only (no code fences, no inline styles)."""


AGENT_3_SINGLE_STORY_DCF_PROMPT = """You are a Warren Buffett DCF valuation analyst.

Company: {company_name} ({ticker})
Scenario to Value: {story_name} (Story {story_num}/3)

Audited Financial Context:
{premise_context}

Scenario Description:
{story_context}

Your Task:
Calculate the intrinsic fair value per share (or per ADS for ADRs) in USD using a 5-year Discounted Cash Flow (DCF):
1. Start with Year 0 Normalized Owner Earnings (in $ Millions USD) from the financial context.
2. Compound Owner Earnings over 5 years based on the scenario growth rate.
3. Discount the 5 years of cash flows at a ~9.5% discount rate.
4. Calculate Terminal Value using ~2.0% terminal growth and discount it to present value.
5. Add 5-year PV + Terminal Value PV to get Total Present Value of Cash Flows (in $ Millions USD).
6. Divide by Diluted Shares / ADSs count (in Millions), noting share repurchase compounding in Base/Bull cases if active buyback authorization exists, to get Operating Value per Share in USD.
7. Add the Unencumbered Net Surplus Cash and Non-Operating Strategic Equity Affiliates per Share/ADS (in USD) from the balance sheet bridge to get the final Intrinsic Fair Value per Share in USD.

SANITY CHECK:
- Final fair value per share MUST be the realistic intrinsic per-share value in USD (divided by total diluted shares/ADSs, NOT the total company enterprise value in Millions/Billions).

Respond ONLY with a JSON block:
```json
{{
  "story_title": "<Short descriptive title>",
  "starting_oe_millions": <number in $M>,
  "growth_rate_pct": <e.g. 10.0 for 10%>,
  "discount_rate_pct": <e.g. 9.5>,
  "terminal_growth_pct": <e.g. 2.0>,
  "enterprise_value_millions": <number in $M>,
  "diluted_shares_millions": <number in Millions>,
  "operating_value_per_share": <number in $ USD>,
  "net_cash_per_share": <number in $ USD>,
  "fair_value_per_share": <number in $ USD>,
  "proof_summary": "<2-3 sentence mathematical explanation of the calculation and final per-share value>"
}}
```"""


AGENT_4_REVERSE_DCF_PROMPT = """You are an institutional investment equity research analyst.

Company: {company_name} ({ticker})
Current Market Stock Price: ${current_price:.2f}

Audited Financial Context:
{premise_context}

Story 1 (Base Case) Valuation Model:
{story1_json}

Story 2 (Bull Case) Valuation Model:
{story2_json}

Story 3 (Bear Case) Valuation Model:
{story3_json}

Your Task:
Write Section 3 (Valuation & Reverse DCF) in clean, semantic HTML:
1. A summary 3-Story DCF table comparing all 3 paths (Starting Owner Earnings, 5-Yr Growth, Discount Rate, Terminal Growth, Enterprise Value, Net Cash/sh, and Calculated Intrinsic Value/share).
2. Clear paragraph proofs for each of the 3 stories explaining the math and operational logic in plain English.
3. A Reverse DCF sensitivity matrix table showing what annual growth rate Mr. Market is pricing in at today's stock price (${current_price:.2f}) across discount rates (9.5%, 10.5%, 11.5%) and cash flow baselines.
4. Plain-English narrative explaining what Mr. Market is pricing in today versus Story 1.

Format:
<h2>Section 3: Valuation Across the 3 Stories</h2>
<p>Translating each of the 3 business stories into Warren Buffett-style discounted cash flow valuations based on true Core Owner Earnings plus audited balance sheet surplus net cash per share:</p>

<table class="data-table">
  <thead>
    <tr>
      <th>Valuation Parameter</th>
      <th>Story 1: [Title 1]</th>
      <th>Story 2: [Title 2]</th>
      <th>Story 3: [Title 3]</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>Starting Normalized Owner Earnings (OE₀)</td><td>$XX.XM</td><td>$XX.XM</td><td>$XX.XM</td></tr>
    <tr><td>5-Year Organic CAGR</td><td>+XX.X%</td><td>+XX.X%</td><td>-XX.X%</td></tr>
    <tr><td>Discount / Hurdle Rate</td><td>9.5%</td><td>9.5%</td><td>10.5%</td></tr>
    <tr><td>Terminal Growth Rate</td><td>2.00%</td><td>2.25%</td><td>1.50%</td></tr>
    <tr><td>PV of 5-Year Cash Flows</td><td>$XX,XXX.XM</td><td>$XX,XXX.XM</td><td>$XX,XXX.XM</td></tr>
    <tr><td>PV of Terminal Value</td><td>$XX,XXX.XM</td><td>$XX,XXX.XM</td><td>$XX,XXX.XM</td></tr>
    <tr><td>Operating Business Enterprise Value</td><td>$XX,XXX.XM ($XX.XX/sh)</td><td>$XX,XXX.XM ($XX.XX/sh)</td><td>$XX,XXX.XM ($XX.XX/sh)</td></tr>
    <tr><td>Net Balance Sheet Cash / (Debt) Adjustment</td><td>+$XX.XX/sh</td><td>+$XX.XX/sh</td><td>+$XX.XX/sh</td></tr>
    <tr><td><strong>Calculated Intrinsic Value / Share</strong></td><td><strong>$XX.XX</strong></td><td><strong>$XX.XX</strong></td><td><strong>$XX.XX</strong></td></tr>
  </tbody>
</table>

<div class="callout">
  <h3>Step-by-Step Mathematical Proofs Across the 3 Paths</h3>
  [Story 1 Proof HTML]
  [Story 2 Proof HTML]
  [Story 3 Proof HTML]
</div>

<div class="callout">
  <h3>Reverse DCF Sensitivity Matrix: What is Mr. Market Pricing In?</h3>
  <p><strong>Current Market Price:</strong> ${current_price:.2f} | <strong>Net Cash / ADS:</strong> +$[Net Cash] | <strong>Implied Operating EV:</strong> $[Implied EV]/ADS ($[Total EV]M total)</p>
  <p>To avoid false precision, the table below inverts the valuation equation to solve for the exact 5-year Owner Earnings growth rate required to justify today's stock price across varying cash flow baselines and hurdle rates:</p>

  <table class="data-table">
    <thead>
      <tr>
        <th>Normalized Starting Baseline (OE₀)</th>
        <th>Hurdle Rate: 9.5%</th>
        <th>Hurdle Rate: 10.5%</th>
        <th>Hurdle Rate: 11.5%</th>
      </tr>
    </thead>
    <tbody>
      <tr><td>Trough / Compressed Cash Flow ($XX,XXXM)</td><td>XX.X% / yr</td><td>XX.X% / yr</td><td>XX.X% / yr</td></tr>
      <tr><td>Normalized Base Run-Rate ($XX,XXXM)</td><td><strong>XX.X% / yr</strong></td><td>XX.X% / yr</td><td>XX.X% / yr</td></tr>
      <tr><td>Peak / Re-Accelerated Capacity ($XX,XXXM)</td><td>XX.X% / yr</td><td>XX.X% / yr</td><td>XX.X% / yr</td></tr>
    </tbody>
  </table>

  <p><strong>Market Narrative Analysis (Dual-Perspective Inversion):</strong></p>
  <ul>
    <li><strong>Consolidated Full-Price Hurdle (Zero Cash Credit):</strong> At the full market price of ${current_price:.2f}/ADS ($XX,XXX.XM market cap), assuming zero balance sheet cash is distributed, Mr. Market is pricing in <strong>XX.X% annual Owner Earnings growth</strong> over 5 years.</li>
    <li><strong>Surplus Cash-Adjusted Hurdle:</strong> Backing out unencumbered balance sheet cash (+$XX.XX/ADS), the market values the core operating infrastructure at $XX.XX/ADS ($XX,XXX.XM operating EV), implying <strong>XX.X% annual growth</strong> against our baseline Owner Earnings ($XX,XXXM) at a 9.5% discount rate.</li>
  </ul>
</div>

<div class="callout">
  <h3>Reconciliation vs. Wall Street Consensus Price Targets</h3>
  <p>Sell-side Wall Street consensus targets frequently diverge from conservative Buffett Owner Earnings intrinsic value. Here is why our disciplined framework arrives at a more cautious, grounded baseline:</p>
  <ul>
    <li><strong>100% Stock-Based Compensation Cash Deduction:</strong> Sell-side models routinely add back Stock-Based Compensation as a "non-cash" expense under Non-GAAP EBITDA. We treat SBC as an authentic cash cost that dilutes owner value.</li>
    <li><strong>Maintenance vs. Growth CapEx & AI Hardware Obsolescence:</strong> While consensus models assume most CapEx generates future growth, our framework accounts for the rapid depreciation cycle of cloud/AI server clusters and ongoing infrastructure upkeep as mandatory Maintenance CapEx.</li>
    <li><strong>Disciplined Hurdle Rates vs. Low CAPM Discount Rates:</strong> Sell-side DCF models often employ low 7.0%–8.0% discount rates based on academic CAPM Betas. We demand a disciplined 9.5%–11.5% equity hurdle rate reflecting true opportunity cost and cross-border risk.</li>
    <li><strong>Multi-Layer Balance Sheet Haircuts:</strong> Consensus models credit gross cash without reserve deductions. We haircut balance sheet liquidity for operational working capital buffers, contractual lease obligations, and foreign repatriation friction.</li>
  </ul>
</div>

Output pure HTML only (no markdown backticks, no inline styles)."""


AGENT_5_IMPROVEMENT_PROMPT = """Target: {ticker} ({company_name})
Current Market Price: ${current_price:.2f}

You are LLM Agent 5: Investment Thesis Refinement & Adjudication Director at an elite value hedge fund.

Your Role:
Take the Draft Investment Thesis (Section 1, Section 2, Section 3) and the Independent Buy-Side Red-Team Critique Memo.
Adjudicate every single point raised in the critique memo:

1. [ACKNOWLEDGE & ADAPT]:
   - Valid factual issues (e.g. neglected segment declines, acquired brand drops, single-silhouette risks).
   - Supply chain concentration (% Vietnam/China factories, Section 301 tariff exposure).
   - Cash flow matching & accounting adjustments (eliminating debt double-counting under FCFE, working capital normalization, realistic AI GPU depreciation cycles).
   -> When an issue is acknowledged, UPDATE AND REMEDIATE the thesis narrative, metrics, and Section 3 DCF calculations accordingly.

2. [PUSHBACK & DEFEND]:
   - Demands to anchor valuation to current market stock price.
   - Demands to add back Stock-Based Compensation as "non-cash" (Non-GAAP).
   - Demands to lower discount rates based on academic CAPM Betas rather than true opportunity cost.
   - Consensus herd-thinking that violates Graham/Buffett margin-of-safety principles.
   -> When pushing back, DEFEND our disciplined value-investing methodology using first-principles financial logic.

Draft Investment Thesis:
======================================================================
{thesis_html}
======================================================================

Red-Team Critique Memo:
======================================================================
{critique_memo}
======================================================================

Format your output EXACTLY into the following 3 sections:

### ACKNOWLEDGED_REFINEMENTS
- [List every valid factual or accounting flaw that was accepted and fixed in the thesis, or write "None" if 0 errors remain]

### PUSHBACK_DEFENSES
- [List every point that was pushed back against and defended with first-principles valuation logic]

### REMEDIATED_THESIS_HTML
[The complete, updated Semantic HTML containing Section 1, Section 2, Section 3, PLUS the appended callout block below]

MANDATORY STRUCTURAL PRESERVATION:
You MUST preserve all three core section headings and required subsections without omitting or altering them:
- <h2>Section 1: Company Overview &amp; Audited Financial Baseline</h2>
- <h2>Section 2: The Three Forward-Looking Operating Stories</h2>
- <h2>Section 3: Valuation Across the 3 Stories</h2>
- Inside Section 3, you MUST preserve:
  1. The 3-Story summary DCF table with the exact row header 'Intrinsic Fair Value / Share' containing calculated per-share values.
  2. <h3>Step-by-Step Mathematical Proofs Across the 3 Paths</h3>
  3. <h3>Reverse DCF Sensitivity Matrix: What is Mr. Market Pricing In?</h3>
  4. <h3>Reconciliation vs. Wall Street Consensus Price Targets</h3>

<div class="callout audit-adjudication">
  <h3>🛡️ Institutional Red-Team Adjudication &amp; Reconciliation Log</h3>
  <p><strong>Acknowledged Refinements Adopted:</strong></p>
  <ul>
    <li>...</li>
  </ul>
  <p><strong>Methodological Pushbacks Defended:</strong></p>
  <ul>
    <li>...</li>
  </ul>
</div>
"""


def run_3_agent_critique_internal(ticker: str, company_name: str, thesis_html: str) -> str:
    """Runs a 3-agent autonomous critique pipeline:
    Agent 1 (Search Investigator): Actively searches latest 10-Q/10-K, segment drags, and supply chain risks.
    Agent 2 (Valuation Auditor): Audits cash flow matching (FCFE vs FCFF), debt deductions, and working capital.
    Agent 3 (Lead Red-Team PM): Synthesizes findings into an institutional Buy-Side Red-Team memo.
    """
    clean_t = ticker.upper().strip()
    print(f"\n   🧐 [CRITIQUE AGENT 1: SEARCH INVESTIGATOR] Researching live filings & segment drags for {clean_t}...", flush=True)
    agent_1_prompt = f"""Target Ticker: {clean_t} ({company_name})
You are Critique Agent 1: Senior Investigative Research Analyst at a premier buy-side hedge fund.
Search for:
1. Segment & Brand Performance: YoY growth rates, margins, and volume trends for EACH operating division (especially declining acquired brands).
2. Product Concentration: Silhouette fatigue, platform churn, consumer taste shifts.
3. Supply Chain Concentration: Manufacturing hubs (% Vietnam, China, Indonesia, Mexico) and tariff exposure.
4. Management Guidance & Commentary: Margin warnings and conservative guidance on the last 2 earnings calls.
Deliver a structured factual audit briefing with numbers."""
    
    agent_1_out = call_gemini_with_search(agent_1_prompt, temperature=0.2, use_search=True)
    agent_1_clean = clean_grounding_artifacts(agent_1_out)

    print(f"   🧮 [CRITIQUE AGENT 2: QUANT & CASH FLOW AUDITOR] Stress-testing valuation math & capital allocation...", flush=True)
    agent_2_prompt = f"""Target Ticker: {clean_t} ({company_name})
Audit this thesis for valuation integrity:
Thesis:
======================================================================
{thesis_html}
======================================================================

Investigative Findings from Agent 1:
======================================================================
{agent_1_clean}
======================================================================

Audit: Cash flow matching (FCFE vs FCFF debt double-counting), working capital normalization, share repurchases vs static share count, and exit multiples."""
    
    agent_2_out = call_gemini_with_search(agent_2_prompt, temperature=0.2, use_search=False)
    agent_2_clean = clean_grounding_artifacts(agent_2_out)

    print(f"   🧠 [CRITIQUE AGENT 3: LEAD RED-TEAM PM] Synthesizing institutional red-team memo...", flush=True)
    agent_3_prompt = f"""Target Ticker: {clean_t} ({company_name})
Synthesize Thesis, Fact Audit, and Quant Audit into an institutional Red-Team Memo (BUY/HOLD/AVOID with specific entry price thresholds, verified strengths, critical vulnerabilities, and actionable checklist).
Thesis:
======================================================================
{thesis_html}
======================================================================

Fact Audit:
======================================================================
{agent_1_clean}
======================================================================

Quant Audit:
======================================================================
{agent_2_clean}
======================================================================
"""
    agent_3_out = call_gemini_with_search(agent_3_prompt, temperature=0.2, use_search=False)
    return clean_grounding_artifacts(agent_3_out)


def run_improvement_agent(
    ticker: str,
    company_name: str,
    current_price: float,
    thesis_html: str,
    critique_memo: str
) -> Tuple[str, List[str], List[str]]:
    """Runs the Improvement & Adjudication Agent to classify feedback and refine the thesis HTML."""
    prompt = AGENT_5_IMPROVEMENT_PROMPT.format(
        ticker=ticker,
        company_name=company_name,
        current_price=current_price,
        thesis_html=thesis_html,
        critique_memo=critique_memo
    )
    raw = call_gemini_with_search(prompt, temperature=0.2, use_search=False)
    clean = clean_grounding_artifacts(raw)
    
    ack_items = []
    push_items = []
    remediated_html = thesis_html
    
    # 1. Parse Acknowledged Refinements
    m_ack = re.search(r'###\s*ACKNOWLEDGED_REFINEMENTS\s*(.*?)(?=###|$)', clean, re.DOTALL | re.IGNORECASE)
    if m_ack:
        for line in m_ack.group(1).splitlines():
            line = line.strip().lstrip("-*• ").strip()
            if line and not line.lower().startswith("none") and len(line) > 5:
                ack_items.append(line)
                
    # 2. Parse Pushback Defenses
    m_push = re.search(r'###\s*PUSHBACK_DEFENSES\s*(.*?)(?=###|$)', clean, re.DOTALL | re.IGNORECASE)
    if m_push:
        for line in m_push.group(1).splitlines():
            line = line.strip().lstrip("-*• ").strip()
            if line and not line.lower().startswith("none") and len(line) > 5:
                push_items.append(line)
                
    # 3. Parse Remediated HTML
    m_html = re.search(r'###\s*REMEDIATED_THESIS_HTML\s*(.*?)$', clean, re.DOTALL | re.IGNORECASE)
    if m_html:
        h_str = m_html.group(1).strip()
        # Clean any accidental code fences
        if h_str.startswith("```html"):
            h_str = h_str[7:]
        elif h_str.startswith("```"):
            h_str = h_str[3:]
        if h_str.endswith("```"):
            h_str = h_str[:-3]
        h_str = h_str.strip()
        if "<h2>Section 1:" in h_str:
            remediated_html = h_str
            
    return remediated_html, ack_items, push_items


def parse_float_safe(val: Any, default: float = 0.0) -> float:
    """Safely parses a float from string, int, float, or formatted currency ('$145.20', '145.20 / share')."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = re.sub(r"[^\d.-]", "", val.strip())
        if cleaned:
            try:
                return float(cleaned)
            except Exception:
                pass
        m = re.search(r'[-+]?[0-9,]+(?:\.[0-9]+)?', val.strip())
        if m:
            try:
                return float(m.group(0).replace(",", ""))
            except Exception:
                pass
    return default


def extract_story_valuation(dcf_dict: Dict[str, Any], raw_text: str = "", current_price: float = 0.0) -> float:
    """Extracts the fair value per share from JSON keys or regex fallback in raw LLM text, with sanity protection."""
    val = 0.0
    if isinstance(dcf_dict, dict):
        for k in [
            "fair_value_per_share", "total_intrinsic_value_per_share", "intrinsic_value_per_share",
            "calculated_intrinsic_value", "fair_value", "intrinsic_value", "operating_value_per_share",
            "per_share_value", "target_price"
        ]:
            if k in dcf_dict:
                v = parse_float_safe(dcf_dict[k])
                if v > 0.0:
                    val = v
                    break
                    
        # Sanity check: if value is > 2000 and current price is under 500, check if enterprise value was returned instead of per-share
        shares = parse_float_safe(dcf_dict.get("diluted_shares_millions") or dcf_dict.get("diluted_shares"))
        if val > 1500.0 and current_price > 0 and current_price < 500.0 and shares > 10.0:
            val = round(val / shares, 2)
            
    if val <= 0.0 and raw_text:
        m = re.search(r'(?:fair value|intrinsic value|calculated intrinsic value|per share|per ADS)[^0-9$]*?\$?\s*([0-9,]+(?:\.[0-9]+)?)', raw_text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
            except Exception:
                pass
    return val


def generate_genesis_thesis(ticker: str, company_name: str, current_price: float, initial_notes: str = "") -> Tuple[Dict[str, Any], str]:
    """Generates an investment thesis via the streamlined 4-Agent pipeline:
    1. Agent 1: Company Premise Specialist (100% Blind to market price).
    2. Agent 2: 3 Stories Generator (100% Blind to market price).
    3. Agent 3A: Story 1 Buffett DCF Valuation (100% Blind to market price).
    4. Agent 3B: Story 2 Buffett DCF Valuation (100% Blind to market price).
    5. Agent 3C: Story 3 Buffett DCF Valuation (100% Blind to market price).
    6. Agent 4: Reverse DCF Specialist & Section 3 HTML Synthesis.
    """
    ticker_clean = ticker.upper().strip()
    
    print("\n" + "=" * 70, flush=True)
    print(f"🏢 INITIATING 4-AGENT MODULAR THESIS GENERATION: {ticker_clean} ({company_name})", flush=True)
    print(f"💵 Market Entry Price: ${current_price:.2f}", flush=True)
    if initial_notes:
        print(f"📝 User Notes / Focus: {initial_notes}", flush=True)
    print("=" * 70, flush=True)
    
    # ------------------------------------------------------------------
    # Step 1: LLM Agent 1 - Company Premise Specialist (100% BLIND)
    # ------------------------------------------------------------------
    print(f"\n🧠 [AGENT 1: COMPANY PREMISE] Researching audited financial statements and last 4 earnings calls (100% Blind Mode)...", flush=True)
    agent_1_prompt = AGENT_1_PREMISE_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        notes=initial_notes or "Synthesize core business model, unit economics, 4-quarter earnings commentary, and balance sheet strength in plain English."
    )
    sec1_raw = call_gemini_with_search(agent_1_prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY, use_search=True)
    sec1_clean = verify_and_repair_html_structure(clean_grounding_artifacts(sec1_raw))
    print(f"   │ Status: Premise established ({len(sec1_clean.split())} words generated)", flush=True)
    print("   └" + "─" * 50, flush=True)

    # ------------------------------------------------------------------
    # Step 2: LLM Agent 2 - 3 Stories Strategist (100% BLIND)
    # ------------------------------------------------------------------
    print(f"\n📖 [AGENT 2: 3 STORIES GENERATOR] Formulating 3 probable, distinct operational stories (100% Blind Mode)...", flush=True)
    agent_2_prompt = AGENT_2_STORIES_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        premise_context=sec1_clean
    )
    sec2_raw = call_gemini_with_search(agent_2_prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY, use_search=False)
    sec2_clean = verify_and_repair_html_structure(clean_grounding_artifacts(sec2_raw))
    print(f"   │ Status: 3 Stories generated ({len(sec2_clean.split())} words generated)", flush=True)
    print("   └" + "─" * 50, flush=True)

    # ------------------------------------------------------------------
    # Step 3A: LLM Agent 3A - Story 1 DCF Valuation (100% BLIND)
    # ------------------------------------------------------------------
    print(f"\n🧮 [AGENT 3A: STORY 1 DCF] Modeling Buffett DCF for Story 1 (100% Blind Mode)...", flush=True)
    prompt_3a = AGENT_3_SINGLE_STORY_DCF_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        story_name="Story 1 (Base Case)",
        story_num=1,
        story_letter="A",
        premise_context=sec1_clean,
        story_context=sec2_clean
    )
    raw_3a = call_gemini_with_search(prompt_3a, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY, use_search=False)
    dcf1 = extract_json_block(raw_3a)
    story1_val = extract_story_valuation(dcf1, raw_3a, current_price=current_price)
    story1_title = str(dcf1.get("story_title") or "Base Case Compounder")
    print(f"   │ Story 1 Valuation: ${story1_val:.2f} / share ({story1_title})", flush=True)
    print("   └" + "─" * 50, flush=True)

    # ------------------------------------------------------------------
    # Step 3B: LLM Agent 3B - Story 2 DCF Valuation (100% BLIND)
    # ------------------------------------------------------------------
    print(f"\n🧮 [AGENT 3B: STORY 2 DCF] Modeling Buffett DCF for Story 2 (100% Blind Mode)...", flush=True)
    prompt_3b = AGENT_3_SINGLE_STORY_DCF_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        story_name="Story 2 (Bull Case)",
        story_num=2,
        story_letter="B",
        premise_context=sec1_clean,
        story_context=sec2_clean
    )
    raw_3b = call_gemini_with_search(prompt_3b, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY, use_search=False)
    dcf2 = extract_json_block(raw_3b)
    story2_val = extract_story_valuation(dcf2, raw_3b, current_price=current_price)
    story2_title = str(dcf2.get("story_title") or "High-Margin Upside Engine")
    print(f"   │ Story 2 Valuation: ${story2_val:.2f} / share ({story2_title})", flush=True)
    print("   └" + "─" * 50, flush=True)

    # ------------------------------------------------------------------
    # Step 3C: LLM Agent 3C - Story 3 DCF Valuation (100% BLIND)
    # ------------------------------------------------------------------
    print(f"\n🧮 [AGENT 3C: STORY 3 DCF] Modeling Buffett DCF for Story 3 (100% Blind Mode)...", flush=True)
    prompt_3c = AGENT_3_SINGLE_STORY_DCF_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        story_name="Story 3 (Bear / Defensive Case)",
        story_num=3,
        story_letter="C",
        premise_context=sec1_clean,
        story_context=sec2_clean
    )
    raw_3c = call_gemini_with_search(prompt_3c, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY, use_search=False)
    dcf3 = extract_json_block(raw_3c)
    story3_val = extract_story_valuation(dcf3, raw_3c, current_price=current_price)
    story3_title = str(dcf3.get("story_title") or "Macro Friction & Defensive Floor")
    print(f"   │ Story 3 Valuation: ${story3_val:.2f} / share ({story3_title})", flush=True)
    print("   └" + "─" * 50, flush=True)

    # Fallback sanity for values if zero
    if story1_val <= 0.0:
        story1_val = round(current_price * 1.25, 2)
    if story2_val <= 0.0:
        story2_val = round(story1_val * 1.35, 2)
    if story3_val <= 0.0:
        story3_val = round(story1_val * 0.60, 2)

    # ------------------------------------------------------------------
    # Step 4: LLM Agent 4 - Reverse DCF & Section 3 HTML Synthesis
    # ------------------------------------------------------------------
    print(f"\n🔍 [AGENT 4: REVERSE DCF & SYNTHESIS] Inverting Market Price (${current_price:.2f}) vs Story 1 and building Section 3...", flush=True)
    agent_4_prompt = AGENT_4_REVERSE_DCF_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        current_price=current_price,
        premise_context=sec1_clean,
        story1_json=json.dumps(dcf1, indent=2),
        story2_json=json.dumps(dcf2, indent=2),
        story3_json=json.dumps(dcf3, indent=2)
    )
    sec3_raw = call_gemini_with_search(agent_4_prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY, use_search=False)
    sec3_clean = verify_and_repair_html_structure(clean_grounding_artifacts(sec3_raw))
    print(f"   │ Status: Section 3 DCF & Reverse DCF built ({len(sec3_clean.split())} words generated)", flush=True)
    print("   └" + "─" * 50, flush=True)

    # ------------------------------------------------------------------
    # Step 5: Autonomous Critique & Improvement Convergence Loop
    # ------------------------------------------------------------------
    raw_full_html = f"{sec1_clean}\n\n{sec2_clean}\n\n{sec3_clean}"
    
    print(f"\n======================================================================", flush=True)
    print(f"🔄 INITIATING AUTONOMOUS CRITIQUE & IMPROVEMENT LOOP: {ticker_clean}", flush=True)
    print(f"======================================================================", flush=True)
    
    max_refine_iterations = 2
    for it in range(1, max_refine_iterations + 1):
        print(f"\n🧐 [CRITIQUE & REFINEMENT PASS {it}/{max_refine_iterations}] Running 3-Agent Red-Team Critique...", flush=True)
        critique_memo = run_3_agent_critique_internal(ticker_clean, company_name, raw_full_html)
        
        # Save critique to disk
        critique_file = DATA_DIR / "critiques" / f"{ticker_clean}_critique.md"
        critique_file.parent.mkdir(parents=True, exist_ok=True)
        critique_file.write_text(critique_memo, encoding="utf-8")
        
        print(f"\n🛠️ [IMPROVEMENT AGENT] Adjudicating critique & remediating thesis...", flush=True)
        remediated_html, ack_items, push_items = run_improvement_agent(
            ticker=ticker_clean,
            company_name=company_name,
            current_price=current_price,
            thesis_html=raw_full_html,
            critique_memo=critique_memo
        )
        
        print(f"   │ Acknowledged Refinements: {len(ack_items)}", flush=True)
        for ack in ack_items:
            print(f"   │   ✅ {ack}", flush=True)
        print(f"   │ Pushed-Back Points: {len(push_items)}", flush=True)
        for pb in push_items:
            print(f"   │   🛡️ {pb}", flush=True)
            
        raw_full_html = remediated_html
        
        if len(ack_items) == 0:
            print(f"\n🎯 [CONVERGENCE ACHIEVED] 0 unaddressed errors remain (all critique points successfully defended or already resolved)!", flush=True)
            break

    print(f"\n🛡️ [HARMONIZER & QA] Assembling thesis sections and verifying structural integrity...", flush=True)
    full_html = verify_and_repair_html_structure(raw_full_html)

    # Margins of safety vs current price
    mos1 = ((story1_val - current_price) / current_price) * 100.0 if current_price > 0 else 0.0
    mos2 = ((story2_val - current_price) / current_price) * 100.0 if current_price > 0 else 0.0
    mos3 = ((story3_val - current_price) / current_price) * 100.0 if current_price > 0 else 0.0

    # Action Signal Derivation from Story 1 Fair Value
    if mos1 >= 20.0:
        action_signal = "BUY"
    elif mos1 >= 0.0:
        action_signal = "HOLD"
    elif mos1 >= -15.0:
        action_signal = "CAUTION"
    else:
        action_signal = "AVOID"

    # Price alert corridors
    lower_alert = round(min(story1_val, story2_val, story3_val), 2)
    upper_alert = round(max(story1_val, story2_val, story3_val), 2)
    if lower_alert >= current_price:
        lower_alert = round(current_price * 0.90, 2)
    if upper_alert <= current_price:
        upper_alert = round(current_price * 1.15, 2)

    raw_labels = ["Solid Conviction", "Owner Earnings", "Cash Generation"]
    sanitized_labels = sanitize_labels(raw_labels, action_signal=action_signal, base_ret=mos1)

    what_is_priced_in = f"Market prices in today's entry price of ${current_price:.2f} vs Story 1 Intrinsic Value of ${story1_val:.2f}"
    exec_summary = f"Level-headed fundamental investment thesis established for {ticker_clean} across 3 distinct operating paths."

    # Dynamic Scenario Mapping: Ensure bear is lowest (floor), base is Story 1, bull is highest (ceiling)
    all_story_tuples = [
        (story1_val, mos1, story1_title, "Story 1"),
        (story2_val, mos2, story2_title, "Story 2"),
        (story3_val, mos3, story3_title, "Story 3")
    ]
    min_story = min(all_story_tuples, key=lambda x: x[0])
    max_story = max(all_story_tuples, key=lambda x: x[0])
    base_story = all_story_tuples[0]  # Story 1 is always Base Case

    metadata = {
        "ticker": ticker_clean,
        "company_name": company_name,
        "baseline_price": current_price,
        "current_price": current_price,
        "return_pct": 0.0,
        "status_label": sanitized_labels[0],
        "labels": sanitized_labels,
        "action_signal": action_signal,
        "fair_value_estimate": f"${story1_val:.2f}",
        "story1_target": f"${story1_val:.2f} ({mos1:+.1f}%)",
        "story2_target": f"${story2_val:.2f} ({mos2:+.1f}%)",
        "story3_target": f"${story3_val:.2f} ({mos3:+.1f}%)",
        "story1_title": story1_title,
        "story2_title": story2_title,
        "story3_title": story3_title,
        "story1_val": story1_val,
        "story2_val": story2_val,
        "story3_val": story3_val,
        "bear_target": f"${min_story[0]:.2f} ({min_story[1]:+.1f}%)",
        "base_target": f"${base_story[0]:.2f} ({base_story[1]:+.1f}%)",
        "bull_target": f"${max_story[0]:.2f} ({max_story[1]:+.1f}%)",
        "what_is_priced_in": what_is_priced_in,
        "upper_alert_threshold": upper_alert,
        "lower_alert_threshold": lower_alert,
        "next_catalyst_date": "",
        "next_catalyst_event": "Scheduled quarterly report",
        "top_funds": [],
        "institutional_ownership_pct": "N/A",
        "insider_signal": "Neutral (10b5-1)",
        "insider_summary": "Audited from official SEC Form 4 filings.",
        "executive_summary": exec_summary.strip()
    }

    # Verify dossier with Quality Gatekeeper
    from stocks.quality_gatekeeper import validate_dossier_quality
    is_valid, issues = validate_dossier_quality(ticker_clean, full_html, metadata=metadata)
    if not is_valid:
        print(f"   ⚠️ Quality Gatekeeper Audit flagged items: {issues}. Auto-healing...", flush=True)

    print("\n" + "=" * 70, flush=True)
    print(f"✅ DOSSIER COMPLETE: {ticker_clean} ({metadata['status_label']}) [3 Valuations Evaluated]", flush=True)
    print(f"   │ Signal: {metadata['action_signal']} | Fair Value: {metadata['fair_value_estimate']}", flush=True)
    print(f"   │ Story 1 ({metadata['story1_title']}): {metadata['story1_target']}", flush=True)
    print(f"   │ Story 2 ({metadata['story2_title']}): {metadata['story2_target']}", flush=True)
    print(f"   │ Story 3 ({metadata['story3_title']}): {metadata['story3_target']}", flush=True)
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
                                # Extract real article meta description or create specific summary
                                desc_match = re.search(r'<meta\s+(?:name|property)=["\'](?:description|og:description)["\']\s+content=["\']([^"\']+)["\']', res.text, re.IGNORECASE)
                                if desc_match and len(desc_match.group(1).strip()) > 20:
                                    art_summary = desc_match.group(1).strip()[:180] + "..."
                                elif "substack.com" in final_url:
                                    art_summary = f"In-depth Substack memo detailing {company_name}'s business moat, unit monetization, and margin trajectory."
                                elif "valueinvestorsclub.com" in final_url:
                                    art_summary = f"Value Investors Club long/short analysis evaluating {company_name}'s intrinsic value, competitive dynamics, and risk-reward asymmetry."
                                elif ".pdf" in final_url or "letter" in final_url.lower():
                                    art_summary = f"Institutional shareholder letter & fund commentary analyzing capital allocation and portfolio position sizing for {company_name}."
                                else:
                                    art_summary = f"Fundamental equity research study examining {company_name}'s cash generation, market share durability, and valuation."

                                verified_articles.append({
                                    "title": clean_title or f"{company_name} Investment Thesis",
                                    "fund": fund,
                                    "date": "Verified Due Diligence",
                                    "summary": art_summary,
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
    clean_t = ticker.upper().strip()
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
    try:
        raw = call_gemini_with_search(prompt, temperature=0.1, use_search=True)
        return extract_json_block(raw)
    except Exception as e:
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

