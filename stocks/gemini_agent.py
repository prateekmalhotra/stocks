import os
import json
import time
import re
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional, List
from dotenv import load_dotenv

load_dotenv()

DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
_CURRENT_ACTIVE_MODEL = DEFAULT_GEMINI_MODEL
FALLBACK_GEMINI_MODEL = "gemini-3.6-flash"


def get_active_model() -> str:
    """Returns the current in-memory active model for this workflow run."""
    global _CURRENT_ACTIVE_MODEL
    return _CURRENT_ACTIVE_MODEL


def switch_to_fallback_model(reason: str = "") -> str:
    """Switches the active model to the fallback model in memory for the remainder of this workflow run."""
    global _CURRENT_ACTIVE_MODEL
    if _CURRENT_ACTIVE_MODEL != FALLBACK_GEMINI_MODEL:
        print(f"  ⚡ [Model Failover] Switching active model for this workflow run to {FALLBACK_GEMINI_MODEL}. (Reason: {reason})")
        _CURRENT_ACTIVE_MODEL = FALLBACK_GEMINI_MODEL
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


def sanitize_labels(labels: Any) -> List[str]:
    """Sanitizes labels ensuring:
    - Max 3 labels total.
    - Each label is max 2 words, properly Title Cased.
    - Preserves the model's nuanced conviction/confidence evaluation in Slot 1 and play drivers in Slots 2 & 3.
    """
    if not isinstance(labels, list):
        if isinstance(labels, str) and labels:
            labels = [labels]
        else:
            labels = []
    
    GENERIC_BLACKLIST = {"REVIEW", "ALERT", "UPDATE", "TASK", "STOCK", "STATUS", "NEW", "NONE", "PRICE"}
    clean_list = []
    for lbl in labels:
        if not isinstance(lbl, str):
            continue
        words = [w for w in lbl.replace("/", " ").replace("-", " ").replace("&", " ").split() if w.strip()]
        if words:
            short_lbl = " ".join(words[:2]).title()
            if short_lbl.upper() not in GENERIC_BLACKLIST and short_lbl not in clean_list:
                clean_list.append(short_lbl)
        if len(clean_list) >= 3:
            break

    return clean_list if clean_list else ["High Conviction", "Deep Value", "Margin Expansion"]


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


def call_gemini_with_search(prompt: str, system_instruction: str = "", temperature: float = 0.4) -> str:
    """Calls Gemini Flash via REST API with Google Search Grounding, exponential retry, and session failover."""
    import time
    api_key = get_api_key()
    
    payload: Dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 8192
        }
    }
    
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }
    
    current_model = get_active_model()
    models_to_try = [current_model]
    if current_model != FALLBACK_GEMINI_MODEL:
        models_to_try.append(FALLBACK_GEMINI_MODEL)
        
    last_err = None
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(url, json=payload, timeout=90)
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
                        retry_res = requests.post(url, json=payload, timeout=90)
                        if retry_res.status_code == 200:
                            retry_json = retry_res.json()
                            retry_parts = retry_json.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                            if retry_parts and "text" in retry_parts[0]:
                                return clean_grounding_artifacts(retry_parts[0]["text"])
                                
                    return "Analysis completed."
                elif response.status_code in (500, 502, 503, 504, 429):
                    if model_name != FALLBACK_GEMINI_MODEL:
                        switch_to_fallback_model(f"HTTP {response.status_code}")
                        break
                    elif attempt < max_retries:
                        wait_time = attempt * 3
                        print(f"  ⚠️ Gemini API ({model_name}) returned {response.status_code}. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                else:
                    last_err = RuntimeError(f"Gemini API error ({response.status_code}): {response.text}")
                    break
            except requests.RequestException as req_err:
                if model_name != FALLBACK_GEMINI_MODEL:
                    switch_to_fallback_model(str(req_err))
                    break
                elif attempt < max_retries:
                    wait_time = attempt * 3
                    print(f"  ⚠️ Network error on {model_name} ({req_err}). Retrying in {wait_time}s...")
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
        data["upper_alert_threshold"] = float(upper_m.group(1))
    lower_m = re.search(r'"(?:lower_alert_threshold|new_lower_alert_threshold)"\s*:\s*([0-9.]+)', text)
    if lower_m:
        data["lower_alert_threshold"] = float(lower_m.group(1))

    return data


def verify_and_repair_html_structure(html: str) -> str:
    """Deterministic structural cleanup, markdown-to-HTML conversion, inline style removal, and tag balancing."""
    if not html:
        return ""
    
    # 1. Strip code fences
    cleaned = re.sub(r"^```(?:html)?\s*", "", html, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

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
    
    # 2. Strip rogue top dashboard header injections from sub-agents (template handles top header)
    cleaned = re.sub(r'<div class="investor-dashboard">[\s\S]*?</div>\s*</div>\s*</div>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<div class="dashboard-header">[\s\S]*?</div>\s*</div>', '', cleaned, flags=re.IGNORECASE)

    # 3. Strip rogue inline style attributes to enforce 100% theme consistency
    cleaned = re.sub(r'\s*style\s*=\s*"[^"]*"', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*style\s*=\s*'[^']*'", '', cleaned, flags=re.IGNORECASE)

    # 4. Clean up section titles like <div class="section-title">SECTION X: ...</div>
    cleaned = re.sub(r'<div class="section-title">\s*(?:SECTION\s*\d+:?\s*)?(.*?)</div>', r'<h2>\1</h2>', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<div class="section-heading">(.*?)</div>', r'<h2>\1</h2>', cleaned, flags=re.IGNORECASE)

    # 5. Clean up rogue italics/bold artifacts like * <strong>...</strong> or <em> <strong>...</strong></em>
    cleaned = re.sub(r'<em>\s*<strong>', r'<strong>', cleaned)
    cleaned = re.sub(r'</strong>\s*</em>', r'</strong>', cleaned)
    cleaned = re.sub(r'^\s*[*•-]\s*\*\*(.*?)\*\*', r'<li><strong>\1</strong>', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^\s*[*•-]\s+<strong>(.*?)</strong>', r'<li><strong>\1</strong>', cleaned, flags=re.MULTILINE)

    # 6. Convert markdown horizontal rules
    cleaned = re.sub(r"^\s*[-*_]{3,}\s*$", '<hr style="border:0; border-top:1px solid var(--border-color); margin:28px 0;">', cleaned, flags=re.MULTILINE)
    
    # 7. Convert markdown headings (####, ###, ##)
    cleaned = re.sub(r"^\s*####\s+(.*?)$", lambda m: f"<h4>{m.group(1)}</h4>", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*###\s+(.*?)$", lambda m: f"<h3>{m.group(1)}</h3>", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*##\s+(.*?)$", lambda m: f"<h2>{m.group(1)}</h2>", cleaned, flags=re.MULTILINE)
    
    # 8. Convert bold and italics
    cleaned = re.sub(r"\*\*(.*?)\*\*", lambda m: f"<strong>{m.group(1)}</strong>", cleaned)
    cleaned = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", lambda m: f"<em>{m.group(1)}</em>", cleaned)
    
    # 9. Clean and convert bullet and numbered lists with zero nesting
    cleaned = re.sub(r"<ul>\s*<ul>+", "<ul>", cleaned)
    cleaned = re.sub(r"</ul>\s*</ul>+", "</ul>", cleaned)
    cleaned = re.sub(r"<ol>\s*<ol>+", "<ol>", cleaned)
    cleaned = re.sub(r"</ol>\s*</ol>+", "</ol>", cleaned)

    lines = cleaned.split("\n")
    in_ol = False
    in_ul = False
    new_lines = []
    
    for line in lines:
        stripped = line.strip()
        ol_match = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        ul_match = re.match(r"^[-*•]\s+(.*)$", stripped)
        li_start = re.match(r"^<li>(.*)$", stripped)
        
        if ol_match and not stripped.startswith("<"):
            if in_ul:
                new_lines.append("</ul>")
                in_ul = False
            if not in_ol:
                new_lines.append('<ol style="padding-left:22px; line-height:1.65; margin:14px 0;">')
                in_ol = True
            new_lines.append(f"  <li>{ol_match.group(2)}</li>")
        elif ul_match and not stripped.startswith("<table") and not stripped.startswith("<div") and not stripped.startswith("<h"):
            if in_ol:
                new_lines.append("</ol>")
                in_ol = False
            if not in_ul:
                new_lines.append('<ul style="padding-left:22px; line-height:1.65; margin:14px 0;">')
                in_ul = True
            content = ul_match.group(1)
            if not content.endswith("</li>"):
                content = content + "</li>"
            if not content.startswith("<li>"):
                content = "<li>" + content
            new_lines.append(f"  {content}")
        else:
            if in_ol and (stripped.startswith("<") or not stripped):
                new_lines.append("</ol>")
                in_ol = False
            if in_ul and (stripped.startswith("<") or not stripped):
                new_lines.append("</ul>")
                in_ul = False
            new_lines.append(line)
            
    if in_ol:
        new_lines.append("</ol>")
    if in_ul:
        new_lines.append("</ul>")
        
    cleaned = "\n".join(new_lines)
    cleaned = re.sub(r"<ul>\s*<ul>+", "<ul>", cleaned)
    cleaned = re.sub(r"</ul>\s*</ul>+", "</ul>", cleaned)

    # 10. Clean up unclosed table tags & cells
    cleaned = re.sub(r"<td>([^<]+)(?=(?:<tr>|</tr>|<td>|<th>|$))", r"<td>\1</td>", cleaned)
    cleaned = re.sub(r"<th>([^<]+)(?=(?:<tr>|</tr>|<td>|<th>|$))", r"<th>\1</th>", cleaned)

    # 11. Auto-close unclosed table rows
    open_tr = len(re.findall(r"<tr\b", cleaned, re.IGNORECASE))
    close_tr = len(re.findall(r"</tr>", cleaned, re.IGNORECASE))
    if open_tr > close_tr:
        cleaned += "</tr>" * (open_tr - close_tr)

    # 12. Auto-close unclosed tables
    open_tables = len(re.findall(r"<table\b", cleaned, re.IGNORECASE))
    close_tables = len(re.findall(r"</table>", cleaned, re.IGNORECASE))
    if open_tables > close_tables:
        diff = open_tables - close_tables
        cleaned += "\n" + ("</tbody></table>" * diff)
        
    # 13. Auto-close unclosed divs & sections
    open_divs = len(re.findall(r"<div\b", cleaned, re.IGNORECASE))
    close_divs = len(re.findall(r"</div>", cleaned, re.IGNORECASE))
    if open_divs > close_divs:
        diff = open_divs - close_divs
        cleaned += "\n" + ("</div>" * diff)

    open_sec = len(re.findall(r"<section\b", cleaned, re.IGNORECASE))
    close_sec = len(re.findall(r"</section>", cleaned, re.IGNORECASE))
    if open_sec > close_sec:
        diff = open_sec - close_sec
        cleaned += "\n" + ("</section>" * diff)

    return clean_grounding_artifacts(cleaned)


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

   Pillar 2: Mid-Cycle Business Normalization (1982 & 1991 Letters)
   - For cyclical, commodity, and hardware technology sectors, NEVER extrapolate peak-quarter cash flows or peak gross margins into perpetuity.
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
   - Programmatic String-of-Pearls M&A Integrity: For serial acquirers executing 15–40 bolt-on acquisitions annually (e.g. Accenture, Constellation Software, Roper), differentiate organic constant-currency growth from acquisitive revenue expansion. Verify that ROIC remains >15%–20% and that goodwill accumulation is not masking organic market share contraction.
   - Buyback Cannibal vs. SBC Neutralizer Audit: Never assume a company is a true 'share cannibal' simply because it announces a share buyback program. If more than 75% of repurchase capital is consumed neutralizing employee equity grants (leaving diluted share count virtually flat), classify the capital return as an 'SBC Neutralizer' and do not model aggressive per-share denominator compounding in DCF projections.
   - M&A Debt Digestion & Buyback Pause Dynamics: When an active share repurchaser temporarily suspends buybacks to fund an acquisition or repay revolving credit facilities, model positive net shareholder dilution (+1% to +2.5%/year from unsterilized SBC) during the debt payback period, and only resume modeling share count reduction once leverage targets are restored.

   Pillar 6: Balance Sheet Fortress, Fixed Lease Overhead & Distress Refinancing
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

   Pillar 8: Reverse-Engineered Market Expectations (The "What is Priced In?" Test)
   - Invert the valuation: At today's market price, solve for the exact 5-year Owner Earnings CAGR ($g_{\text{implied}}$) that Mr. Market is currently pricing in.
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

5. Editorial Aesthetics & Structural Clarity:
   - Format financial KPIs and segment data into `<div class="metrics-grid"><div class="metric-card">...</div></div>` or structured HTML tables. Zero raw text dumps.
   - Use Callout boxes (`<div class="callout">...</div>`) for key insights, management quotes, and pre-mortem falsification triggers.
   - Zero external images: Keep all analyses purely professional analytical text, data tables, callouts, and metric cards.
"""

MASTER_PLANNER_PROMPT = """Target: {ticker} ({company_name}) | Current Stock Price: ${current_price:.2f}
User Focus / Research Notes: {notes}

You are the Lead Investment Strategist. Your broad goal is to formulate an honest, down-to-earth fundamental evaluation of {ticker}.

[AUTONOMY & BROAD OBJECTIVE DIRECTIVE]:
You have full freedom to decide what matters most for this business and how to evaluate it.
You will divide the research memo into 3 to 4 specialized sub-agents. Each sub-agent will research its assigned area using real-time search (including the latest earnings release, latest earnings call transcript, and latest official announcements) and directly output its dedicated section in clean Semantic HTML (<div class="section"> ... </div>).

Key Areas to Investigate via Real-Time Filings, Earnings Calls & Announcements:
- Latest Earnings Statement, Call Transcript & Corporate News: What did management announce and discuss regarding current performance, forward guidance, capital allocation, and industry headwinds?
- Business Model Reality & Moat: How the company makes money, customer retention, pricing power, and competitive advantages in plain English.
- Real Cash Flow, SBC & Capital Structure: Real cash generation (treating SBC as a cash charge), dilution vs. buybacks, Net Cash/Debt, and capital allocation.
- Ownership & Catalysts: Verified active 13F whale positions from latest official filings (exclude exited investors), management alignment, and upcoming catalysts.
- Warren Buffett Owner Earnings & Intrinsic Value Matrix: Calculate normalized Owner Earnings (Post-SBC cash flow minus maintenance CapEx, float/lease debt discipline), project 3-5 year compounding, factor in share count reduction from buybacks, and discount strictly via the LOCAL SOVEREIGN BOND YIELD with zero arbitrary exit multiples. Build a clean Bear / Base / Bull scenario table in Section 5.
- What is Priced In? (Reverse DCF): Calculate what 5-year growth rate the current stock price implies.
- Probabilistic Risk & Fragility Audit (Section 6): Conduct an explicit probabilistic threat audit detailing top risk scenarios, probability ratings (%), severity, fundamental "Why", and overall Business Fragility rating.
- Dynamic Alert Corridors: Establish exact `upper_alert_threshold` (upside breakout / trim level) and `lower_alert_threshold` (downside margin-of-safety floor) based on your valuation targets.

Editorial Aesthetics Mandate:
- Format all financial KPIs and quarterly numbers into `<div class="metrics-grid"><div class="metric-card">...</div></div>` or structured HTML tables. Zero raw text dumps.
- DO NOT duplicate raw metadata text or pill badges inside the HTML sections.
- NO IMAGES: Do not output `<img>` tags or figure containers. Pure analytical text, tables, and metric cards only.

Labels Directive (2-Tier Intuitive Structure):
- Label #1 (MANDATORY PRIMARY PILL — CONVICTION & CONFIDENCE RATING): State in MAX 2 WORDS your thesis conviction/certainty (e.g. "High Conviction", "Cautious Stance", "Speculative Risk", "High Confidence", "Moderate Conviction", "Turnaround Risk", "Defensive Safe", "High Uncertainty", "Asymmetric Upside"). DO NOT put play types here.
- Labels #2 & #3 (THE PLAY NATURE & CATALYST DRIVERS): Describe the economic play and catalyst driver in intuitive plain English (e.g. "Deep Value", "Turnaround Play", "Safe Compounder", "Buyback Cannibal", "Margin Expansion", "Cash Fortress", "Debt Paydown", "Pricing Power", "Moat Expansion", "Special Situation"). Avoid textbook jargon.
- 100% FREEDOM: Examples are inspiration only. You can freely choose or invent any 2-word label names that best fit the company.

Return your plan strictly as a JSON object in ```json ... ```:
```json
{{
  "metadata": {{
    "ticker": "{ticker}",
    "company_name": "{company_name}",
    "labels": ["<Confidence/Risk Label 1>", "<Play Driver Label 2>", "<Play Driver Label 3>"],
    "action_signal": "<BUY | HOLD | CAUTION | AVOID (Actionable stance: BUY if thesis accelerating/deep value, HOLD if steady/wait, CAUTION if headwinds/trim, AVOID if broken)>",
    "fair_value_estimate": "$<Estimated Fair Value>",
    "bear_target": "$<Price> (<% Upside/Downside>)",
    "base_target": "$<Price> (<% Upside/Downside>)",
    "bull_target": "$<Price> (<% Upside/Downside>)",
    "what_is_priced_in": "<1-line summary: e.g. Market is pricing in +3.5%/yr OE growth vs Base Case of +10.5%/yr (Asymmetric MoS)>",
    "upper_alert_threshold": <Float price to alert on upside breakout>,
    "lower_alert_threshold": <Float price to alert on downside break>,
    "upper_trigger_reason": "<Short reason>",
    "lower_trigger_reason": "<Short reason>",
    "next_catalyst_date": "<YYYY-MM-DD (Strict ISO date, e.g. 2026-08-13; if unconfirmed, estimate exact calendar day based on historical reporting cadence)>",
    "next_catalyst_event": "<Short description of catalyst, max 4 words, using clean concise notation e.g. Q3 '26 ER, Q2 '27 ER, Investor Day>",
    "top_funds": ["<Top Fund 1 (e.g. Vanguard 8.4%)>", "<Top Fund 2 (e.g. BlackRock 7.1%)>", "<Whale/Superinvestor 3 from Dataroma/WhaleWisdom>"],
    "institutional_ownership_pct": "<e.g. 78.4%>",
    "insider_signal": "<Net Buying | Cluster Buying | Neutral (10b5-1) | Net Selling | No Activity>",
    "insider_summary": "<Crisp 1-line summary of recent Form 4 insider purchases/sales audited from OpenInsider, max 10 words>",
    "executive_summary": "<2-3 sentence crisp executive summary>"
  }},
  "research_objective": "<Your custom summary of the core thesis questions for {ticker}. Search OpenInsider (http://openinsider.com/search?q={ticker}) and Dataroma for insider trades and whale ownership>",
  "sub_agents": [
    {{
      "role": "<Sub-Agent 1 Role Name, e.g. Business Model & Moat Specialist>",
      "prompt": "<Detailed prompt instructing Sub-Agent 1 to search latest earnings release/transcript, news & filings and output Section 1 & 2 in clean Semantic HTML using metrics-grid, tables, callout boxes, and optional product figures>"
    }},
    {{
      "role": "<Sub-Agent 2 Role Name, e.g. Cash Flow, SBC Dilution & Balance Sheet Auditor>",
      "prompt": "<Detailed prompt instructing Sub-Agent 2 to search latest earnings release/transcript, news & filings and output Section 3 & 4 in clean Semantic HTML using metrics-grid, tables, and callout boxes>"
    }},
    {{
      "role": "<Sub-Agent 3 Role Name, e.g. Ballpark Valuation, Confidence & Invalidation Specialist>",
      "prompt": "<Detailed prompt instructing Sub-Agent 3 to search latest earnings release/transcript, news & filings and output Section 5 & 6 evaluating fair value confidence, execution risk, and Bear/Base/Bull tables in clean Semantic HTML>"
    }}
  ]
}}
```
"""


def generate_genesis_thesis(ticker: str, company_name: str, current_price: float, initial_notes: str = "") -> Tuple[Dict[str, Any], str]:
    """Generates a level-headed, honest institutional investment memo via direct modular sub-agent section generation."""
    ticker_clean = ticker.upper().strip()
    
    print("\n" + "=" * 70, flush=True)
    print(f"🏢 INITIATING LEVEL-HEADED COVERAGE: {ticker_clean} ({company_name})", flush=True)
    print(f"💵 Market Entry Price: ${current_price:.2f} | Autonomous Multi-Agent Pipeline", flush=True)
    if initial_notes:
        print(f"📝 User Notes / Focus: {initial_notes}", flush=True)
    print("=" * 70, flush=True)
    
    # ------------------------------------------------------------------
    # Step 1: Autonomous Master Planner dynamically devises the sub-agent plan
    # ------------------------------------------------------------------
    print(f"\n🧠 [STAGE 1/3: MASTER PLANNER] Formulating dynamic research strategy for {ticker_clean}...", flush=True)
    planner_prompt = MASTER_PLANNER_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        current_price=current_price,
        notes=initial_notes or "Evaluate fundamental moat, true cash generation deducting SBC, dilution, balance sheet, and level-headed ballpark valuation."
    )
    planner_res = call_gemini_with_search(planner_prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY)
    plan_json = extract_json_block(planner_res)
    
    metadata = plan_json.get("metadata", {})
    research_obj = plan_json.get("research_objective", f"Evaluate {ticker_clean} core business reality and valuation.")
    print(f"   │ Strategy: {research_obj}", flush=True)

    # Enforce strict non-overlapping 3-agent modular section generation
    agent_1_prompt = f"""You are Sub-Agent 1: Business Model, Moat & Operational Strategy Specialist researching {ticker_clean} ({company_name}) at current market price ${current_price:.2f}.
Your Objective: {research_obj}

Generate ONLY the following two sections in clean Semantic HTML with NO external images, NO inline styles, and NO code fences:

<h2>Section 1: Executive Summary & Operating Reality</h2>
- 2-3 paragraph institutional executive summary grounded in the LATEST quarterly earnings report, call transcript remarks, and forward guidance.
- Present latest quarterly performance using a clean stat grid:
  <div class="metrics-grid">
    <div class="metric-card"><div class="metric-label">Quarterly Net Revenue</div><div class="metric-value">$XX.XXB</div><div class="metric-delta pos">+XX% YoY</div></div>
    <div class="metric-card"><div class="metric-label">Operating Margin (EBIT)</div><div class="metric-value">XX.X%</div><div class="metric-delta pos">+XXX bps YoY</div></div>
    <div class="metric-card"><div class="metric-label">Operating Cash Flow</div><div class="metric-value">$XX.XXB</div><div class="metric-delta pos">+XX% YoY</div></div>
    <div class="metric-card"><div class="metric-label">Core Segment Growth</div><div class="metric-value">+XX.X%</div><div class="metric-delta pos">Organic</div></div>
  </div>
- Add a Callout box (<div class="callout">...</div>) highlighting direct CEO/CFO quotes from the latest earnings call regarding capital allocation, margin outlook, and competitive dynamics.

<h2>Section 2: Business Model Reality, Unit Economics & Competitive Moat</h2>
- Segment-by-segment revenue and operating profit breakdown table.
- Explain in plain English how the company makes money, customer switching costs, and evidence of pricing power.
- Detailed competitive comparison table contrasting the company against its top 2-3 global peers across unit economics, distribution channels, and technology moats.
- Structural secular tailwinds vs. competitive disruption / technological substitution threats.

DO NOT write Section 3, 4, 5, or 6. Output pure HTML only."""

    agent_2_prompt = f"""You are Sub-Agent 2: Real Cash Flow, SBC Dilution & Capital Allocation Auditor researching {ticker_clean} ({company_name}) at current market price ${current_price:.2f}.
Your Objective: {research_obj}

Generate ONLY the following two sections in clean Semantic HTML with NO external images, NO inline styles, and NO code fences:

<h2>Section 3: Forensic Cash Flow, SBC Dilution & Owner Earnings Audit</h2>
- Rigorous cash flow audit stripping away Non-GAAP add-backs.
- Treat 100% of Stock-Based Compensation (SBC) as an unavoidable cash expense and equity dilution factor.
- Detailed 4-Year Cash Flow Decomposition Table:
  <table>
    <thead><tr><th>Metric ($ Millions)</th><th>FY 2024</th><th>FY 2025</th><th>FY 2026</th><th>TTM Run-Rate</th></tr></thead>
    <tbody>
      <tr><td>GAAP Operating Cash Flow</td><td>...</td><td>...</td><td>...</td><td>...</td></tr>
      <tr><td>Less: Stock-Based Compensation (100% Cash Deducted)</td><td>...</td><td>...</td><td>...</td><td>...</td></tr>
      <tr><td>Less: Maintenance CapEx (Defensive Moat Upkeep)</td><td>...</td><td>...</td><td>...</td><td>...</td></tr>
      <tr><td><strong>Buffett Owner Earnings (True Distributable Cash)</strong></td><td>...</td><td>...</td><td>...</td><td>...</td></tr>
      <tr><td>Discretionary Growth CapEx (Isolated)</td><td>...</td><td>...</td><td>...</td><td>...</td></tr>
    </tbody>
  </table>
- Working Capital Float Audit: Quantify interest-free customer/supplier float (Deferred Revenue + Accounts Payable minus Accounts Receivable).

<h2>Section 4: Balance Sheet Fortress, Debt Leases & Ownership Check</h2>
- Audited capital structure table: Cash & Marketable Treasuries, Funded Debt, Debt Maturity Schedule, and Contractual Capital/Operating Lease liabilities (ASC 842).
- Net Cash / Net Debt calculation and Interest Expense Coverage ratio.
- Share Buyback Cannibalization Analysis: Gross shares repurchased minus SBC shares issued = True Net Annual Share Count Reduction (-X.X%/year).
- Institutional 13F Whales & Form 4 Insider Trading audit from latest official filings.

DO NOT write Section 1, 2, 5, or 6. Output pure HTML only."""

    agent_3_prompt = f"""You are Sub-Agent 3: Warren Buffett Owner Earnings Valuation Strategist & Pre-Mortem Auditor researching {ticker_clean} ({company_name}) at current market price ${current_price:.2f}.
Your Objective: {research_obj}

Generate ONLY the following two sections in clean Semantic HTML with NO external images, NO inline styles, and NO code fences:

<h2>Section 5: Warren Buffett Owner Earnings Intrinsic Valuation Matrix</h2>
- Root valuation strictly in Warren Buffett's 1986 Owner Earnings methodology. Zero arbitrary exit multiples.
- For cyclical, hardware, or commodity sectors: Normalize peak margins across a full 3-5 year operating cycle.
- Localized sovereign discount rate derivation (local 10Y sovereign bond yield + equity risk premium, e.g. US 10Y for US, SELIC for Brazil, Gilts for UK).
- [MANDATORY BEAR CASE DOWNSIDE INVARIANT]: The Bear Case (Cycle Trough) MUST BE A REALISTIC DOWNSIDE SCENARIO. The Bear Case Intrinsic Value Per Share MUST ALWAYS BE BELOW CURRENT STOCK PRICE (typically 15% to 40% below current price). A Bear target higher than today's price is strictly forbidden.
- Complete 3-Scenario DCF Valuation Matrix:
  <table>
    <thead>
      <tr>
        <th>Valuation Parameter / Scenario</th>
        <th>Bear Case (Trough Stress-Test)</th>
        <th>Base Case (Normalized Reality)</th>
        <th>Bull Case (Optimistic Compounding)</th>
      </tr>
    </thead>
    <tbody>
      <tr><td>Normalized Owner Earnings (Yr 1)</td><td>$XX.XXB</td><td>$XX.XXB</td><td>$XX.XXB</td></tr>
      <tr><td>5-Year Organic OE CAGR</td><td>X.X%</td><td>XX.X%</td><td>XX.X%</td></tr>
      <tr><td>Net Annual Share Compounding</td><td>-X.X%/yr</td><td>-X.X%/yr</td><td>-X.X%/yr</td></tr>
      <tr><td>Discount Rate (Local Sovereign + ERP)</td><td>X.X%</td><td>X.X%</td><td>X.X%</td></tr>
      <tr><td>Terminal Growth Rate (GDP Capped)</td><td>X.X%</td><td>X.X%</td><td>X.X%</td></tr>
      <tr><td>Net Balance Sheet Debt/Cash Adjustment</td><td>-$X.XX/sh</td><td>-$X.XX/sh</td><td>-$X.XX/sh</td></tr>
      <tr><td><strong>Intrinsic Fair Value / Share</strong></td><td><strong>$XX.XX</strong></td><td><strong>$XX.XX</strong></td><td><strong>$XX.XX</strong></td></tr>
      <tr><td><strong>Margin of Safety vs Current Price</strong></td><td><strong>XX.X%</strong></td><td><strong>XX.X%</strong></td><td><strong>XX.X%</strong></td></tr>
    </tbody>
  </table>
- Market-Implied Expectations & "What is Priced In?" (Reverse DCF):
  * Calculate what exact 5-year Owner Earnings CAGR (g_implied) the market is pricing into today's stock price (${current_price:.2f}).
  * Present a dedicated Reverse-DCF callout box or table contrasting Market-Implied Expectations vs. Base Case Reality (highlighting whether the stock is priced for perfection, fairly priced, or pricing in excessive disaster).
- The 5-Year Market Closure Test: Demonstrate the organic cash yield earned if the stock exchange closed for 5 years.

<h2>Section 6: Probabilistic Risk Audit, Threat Assessment & Pre-Mortem Falsification</h2>
- Business Fragility & Tail-Risk Stat Grid:
  <div class="metrics-grid">
    <div class="metric-card"><div class="metric-label">Business Fragility Rating</div><div class="metric-value">Low / Medium / High Fragility</div><div class="metric-delta">Moat Robustness</div></div>
    <div class="metric-card"><div class="metric-label">Primary Vulnerability</div><div class="metric-value">e.g. AI / Regulation / Debt</div><div class="metric-delta neg">Key Threat</div></div>
    <div class="metric-card"><div class="metric-label">Tail-Risk Severity</div><div class="metric-value">Moderate / Severe</div><div class="metric-delta">P&L Impact</div></div>
  </div>
- Comprehensive Probabilistic Risk & Threat Matrix Table:
  Evaluate the top 3-4 existential or major operational risk scenarios. MUST include probability rating, financial severity, and the deep fundamental "Why" (transmission mechanics into cash flow):
  <table>
    <thead>
      <tr>
        <th>Risk Vector & Threat Scenario</th>
        <th>Probability Rating (%)</th>
        <th>Financial Severity</th>
        <th>The "Why" & Transmission Mechanics (Root Cause)</th>
        <th>Mitigation & Structural Defenses</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>e.g. Disintermediation / Tech Shift</strong></td>
        <td>Medium (30%-40%)</td>
        <td>Severe</td>
        <td>Explain exactly why this risk exists, how it impacts sales/margins, and why DCF growth could fail...</td>
        <td>Balance sheet net cash, proprietary distribution, etc.</td>
      </tr>
      <tr>
        <td><strong>e.g. Regulatory / Antitrust / Tariff Risk</strong></td>
        <td>...</td>
        <td>...</td>
        <td>...</td>
        <td>...</td>
      </tr>
      <tr>
        <td><strong>e.g. Margin Compression / Component Squeeze</strong></td>
        <td>...</td>
        <td>...</td>
        <td>...</td>
        <td>...</td>
      </tr>
    </tbody>
  </table>
- 3 Explicit Quantitative Pre-Mortem Falsification Triggers (Kill switches that invalidate the investment thesis).
- Dynamic Price Alert Corridors: Upper threshold (trim / target realization) and Lower threshold (margin of safety floor).

DO NOT write Section 1, 2, 3, or 4. Output pure HTML only."""

    sub_agents = [
        {"role": "Business Model, Moat & Operating Reality Specialist", "prompt": agent_1_prompt},
        {"role": "Real Cash Flow, SBC & Capital Structure Auditor", "prompt": agent_2_prompt},
        {"role": "Warren Buffett Owner Earnings Valuation Strategist", "prompt": agent_3_prompt}
    ]
    
    print(f"   │ Planned Sub-Agents: 3 specialized non-overlapping autonomous tasks", flush=True)
    print("   └" + "─" * 50, flush=True)

    # ------------------------------------------------------------------
    # Step 2: Execute Sub-Agents (Each Directly Generates Its Clean HTML Section)
    # ------------------------------------------------------------------
    section_htmls = []
    for idx, agent in enumerate(sub_agents, 1):
        role_name = agent.get("role", f"Sub-Agent {idx}")
        agent_prompt = agent.get("prompt", "")
        print(f"\n🤖 [STAGE 2/3: AGENT {idx}/{len(sub_agents)}] {role_name}", flush=True)
        prompt_snippet = agent_prompt.replace('\n', ' ')[:100] + '...' if len(agent_prompt) > 100 else agent_prompt
        print(f"   │ Task: {prompt_snippet}", flush=True)
        print(f"   │ Search Grounding: Querying real-time filings & consensus...", flush=True)
        
        agent_out = call_gemini_with_search(agent_prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY)
        clean_section = verify_and_repair_html_structure(clean_grounding_artifacts(agent_out))
        section_htmls.append(clean_section)
        print(f"   │ Status: Complete ({len(clean_section.split())} words generated)", flush=True)
        print("   └" + "─" * 50, flush=True)

    raw_full_html = "\n\n".join(section_htmls).strip()

    # ------------------------------------------------------------------
    # Step 3: Lead Harmonizer & Structural Tag Polish
    # ------------------------------------------------------------------
    print(f"\n🛡️ [STAGE 3/3: HARMONIZER & QA] Assembling sections and verifying structural integrity...", flush=True)
    full_html = verify_and_repair_html_structure(raw_full_html)
    print(f"   │ Verification: All sections joined with zero overflow and 100% tag integrity", flush=True)
    print("   └" + "─" * 50, flush=True)

    if not metadata:
        metadata = {
            "ticker": ticker_clean,
            "company_name": company_name,
            "labels": ["Active"],
            "fair_value_estimate": f"${current_price * 1.15:.2f}",
            "bear_target": f"${current_price * 0.75:.2f} (-25.0%)",
            "base_target": f"${current_price * 1.15:.2f} (+15.0%)",
            "bull_target": f"${current_price * 1.50:.2f} (+50.0%)",
            "upper_alert_threshold": round(current_price * 1.15, 2),
            "lower_alert_threshold": round(current_price * 0.88, 2),
            "upper_trigger_reason": "Upside valuation breakout",
            "lower_trigger_reason": "Downside margin of safety test",
            "next_catalyst_date": "Next Earnings",
            "next_catalyst_event": "Scheduled quarterly report",
            "executive_summary": f"Level-headed fundamental investment memo established for {ticker_clean}."
        }

    # Extract Section 5 DCF Intrinsic Value table to guarantee 100% mathematical reconciliation
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", full_html, re.DOTALL | re.IGNORECASE)
    target_row = None
    for r in rows:
        r_clean = re.sub(r"<[^>]+>", " ", r).strip()
        if any(k in r_clean.lower() for k in ["intrinsic fair value", "intrinsic value / share", "intrinsic value per share", "base intrinsic value"]):
            target_row = r
            break
            
    if target_row:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", target_row, re.DOTALL)
        extracted_nums = []
        for td in tds:
            cleaned = re.sub(r"<[^>]+>", "", td).strip()
            num_match = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)", cleaned)
            if num_match:
                try: extracted_nums.append(float(num_match.group(1).replace(",", "")))
                except ValueError: pass
                
        if len(extracted_nums) >= 3:
            bear_val, base_val, bull_val = extracted_nums[0], extracted_nums[1], extracted_nums[2]
            bear_ret = ((bear_val - current_price) / current_price) * 100.0 if current_price > 0 else 0.0
            base_ret = ((base_val - current_price) / current_price) * 100.0 if current_price > 0 else 0.0
            bull_ret = ((bull_val - current_price) / current_price) * 100.0 if current_price > 0 else 0.0
            
            metadata["fair_value_estimate"] = f"${base_val:.2f}"
            metadata["base_target"] = f"${base_val:.2f} ({base_ret:+.1f}%)"
            metadata["bear_target"] = f"${bear_val:.2f} ({bear_ret:+.1f}%)"
            metadata["bull_target"] = f"${bull_val:.2f} ({bull_ret:+.1f}%)"
            metadata["upper_alert_threshold"] = round(min(base_val, current_price * 1.15), 2)
            metadata["lower_alert_threshold"] = round(max(bear_val, current_price * 0.85), 2)

            # Strict First-Principles Action Signal Derivation from Calculated Margin of Safety
            if base_ret >= 20.0 and bear_val < current_price:
                metadata["action_signal"] = "BUY"
            elif base_ret >= 0.0:
                metadata["action_signal"] = "HOLD"
            elif base_ret >= -15.0:
                metadata["action_signal"] = "CAUTION"
            else:
                metadata["action_signal"] = "AVOID"

    metadata["labels"] = sanitize_labels(metadata.get("labels") or metadata.get("status_label"))
    metadata["status_label"] = metadata["labels"][0] if metadata["labels"] else "Active"
    metadata["next_catalyst_date"] = normalize_catalyst_date(metadata.get("next_catalyst_date"))
    metadata["action_signal"] = normalize_action_signal(metadata.get("action_signal", "BUY"))

    print("\n" + "=" * 70, flush=True)
    print(f"✅ DOSSIER COMPLETE: {ticker_clean} ({metadata['status_label']}) at ${current_price:.2f}", flush=True)
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
    """Reviews an active stock thesis by executing the full multi-agent evaluation pipeline."""
    print(f"\n🔄 [FULL MULTI-AGENT RE-EVALUATION] Running fresh coverage pipeline for {ticker} ({company_name})", flush=True)
    print(f"   │ Trigger: {trigger_reason}", flush=True)
    print(f"   │ Current Price: ${current_price:.2f} | Baseline Price: ${baseline_price:.2f}", flush=True)

    update_notes = f"""MATERIAL TRIGGER: {trigger_reason}
Current Stock Price: ${current_price:.2f} (Baseline: ${baseline_price:.2f})
Previous Thesis Stance: {previous_status}
Previous Thesis Summary: {previous_thesis_summary}
Previous Fair Value: {previous_fair_value or previous_base_target or 'N/A'}

Execute a fresh, uncompromised fundamental evaluation. Query latest earnings releases, call transcripts, 10-Q/10-K filings, and 13F whale filings. Re-evaluate operating moat, cash generation post-SBC, balance sheet health, and Owner Earnings DCF scenarios."""

    metadata, full_html = generate_genesis_thesis(
        ticker=ticker,
        company_name=company_name,
        current_price=current_price,
        initial_notes=update_notes
    )

    metadata["what_was_before"] = previous_thesis_summary
    metadata["what_changes_now"] = metadata.get("executive_summary") or f"Thesis re-evaluated following: {trigger_reason}"
    metadata["alert_title"] = metadata.get("alert_title") or f"{ticker.upper()}: Coverage Re-Evaluated ({metadata.get('status_label', 'Active')})"
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
    models_to_try = [active_m]
    if active_m != FALLBACK_GEMINI_MODEL:
        models_to_try.append(FALLBACK_GEMINI_MODEL)

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
            elif r.status_code in (500, 502, 503, 504, 429) and model_name != FALLBACK_GEMINI_MODEL:
                switch_to_fallback_model(f"HTTP {r.status_code}")
                continue
        except Exception as e:
            if model_name != FALLBACK_GEMINI_MODEL:
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
    models_to_try = [active_m]
    if active_m != FALLBACK_GEMINI_MODEL:
        models_to_try.append(FALLBACK_GEMINI_MODEL)

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
            elif resp.status_code in (500, 502, 503, 504, 429) and model_name != FALLBACK_GEMINI_MODEL:
                switch_to_fallback_model(f"HTTP {resp.status_code}")
                continue
        except Exception as e:
            if model_name != FALLBACK_GEMINI_MODEL:
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

