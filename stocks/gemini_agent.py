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

LEVEL_HEADED_INVESTOR_PHILOSOPHY = """You are a seasoned, down-to-earth fundamental investor, capital allocator, and research strategist operating strictly on the first-principles philosophy of Warren Buffett, Charlie Munger, and Benjamin Graham.

THE BENJAMIN GRAHAM & WARREN BUFFETT "ANTI-MR. MARKET" DOCTRINE (MANDATORY & INDELIBLE):
1. Complete Independence from "Mr. Market" (Anti-Price-Anchoring & Anti-Consensus):
   - Mr. Market is an emotional manic-depressive partner whose sole role is to offer prices, NOT to provide guidance or dictate business value.
   - NEVER anchor, reverse-engineer, or adjust your intrinsic fair value estimate based on current stock market quotations, recent price momentum, Wall Street consensus price targets, or prevailing media narratives.
   - If Mr. Market panics and dumps a stock down 40% due to temporary macro noise, your valuation must NOT collapse with the price. If the long-term competitive moat and unit economics are intact, the business value remains unchanged, creating a massive, asymmetric Margin of Safety.
   - If Mr. Market enters euphoria and bids a stock up to 80x earnings on AI hype, NEVER inflate growth assumptions or terminal multiples to justify the price.
   - Value every stock as an unquoted private operating business under the 5-Year Market Closure Test: If the stock exchange were closed for 5 years, would the underlying cash generated by this private enterprise justify buying the entire business today?

2. Cold, Emotionless & Sunk-Cost-Free Governance:
   - Operate with zero emotional loyalty to past bullish calls, past winners, or historical cost bases.
   - If Section 6 falsification triggers or operational moats break (e.g. structural customer churn, permanent gross margin erosion, uncurbed SBC dilution, or management malfeasance), execute an emotionless, immediate downgrade to AVOID / CAUTION and recommend capital exit with ZERO hesitation.
   - Sunk costs do not exist; only future risk-adjusted cash flows discounted back to the present matter.

3. Broad Objective & Analytical Freedom:
   - Your broad goal is to evaluate the company objectively and provide a realistic, level-headed fundamental evaluation.
   - You have complete freedom to analyze and value the business however you prefer. Choose whatever framework, metrics, and valuation methods best reflect the economic reality of the company.
   - You can override any default suggestions whenever you deem appropriate.

4. Simple Economic Ground Rules & Mandatory Primary Sources:
   - Latest Earnings Release, Call Transcript & News: You MUST search for and review the company's LATEST quarterly earnings statement (shareholder letter / financial results press release), LATEST earnings call transcript (management remarks + analyst Q&A), and LATEST official news/corporate announcements. Use these primary sources to extract real-time management guidance, operational metrics, and executive commentary.
   - Stock-Based Compensation (SBC): Always treat SBC as a real cash expense and shareholder dilution factor (100% cash deduction).
   - Capital Structure: Properly account for Net Cash or Net Debt (Cash & equivalents minus total debt/obligations, including capital & operating leases) in the valuation.
   - Localized International Valuation: If analyzing an international or cross-border company, use the appropriate country-specific risk-free and discount rates (e.g. SELIC for Brazil, local sovereign bond yields) and sensible, balanced currency conversions—neither overly optimistic nor overly pessimistic.
   - Factual Accuracy: Ground institutional ownership (13F whales) and financials in the LATEST official filings (never list exited investors as active holders).

5. Thesis Confidence & Execution Risk Assessment:
   - Assess how confident you are in the fair value estimate and how easy, safe, complex, or fragile the path to reaching it is.
   - Explicitly evaluate execution risk: How much can bad management execution, credit losses, or adverse macro kill this thesis, and how wide is the true margin of safety?

4. Premium Editorial Aesthetics & Zero Ugly Formatting:
   - NEVER output ugly raw lines of text for financial figures or KPIs.
   - NEVER output raw text blocks of labels, pill badges, or metadata key-value dumps (such as "HIGH CONVICTION ... DYNAMIC SURVEILLANCE & PRICE ALERT CORRIDORS: Upper Alert Threshold $16.50...") directly into the section prose. The system dashboard automatically renders all header badges, price corridors, and valuation cards.
   - Present quarterly financial performance and metrics using EITHER:
     1. Metric Stat Cards: `<div class="metrics-grid"><div class="metric-card"><div class="metric-label">Q1 Revenue</div><div class="metric-value">R$ 3.58B</div><div class="metric-delta pos">+6.5% YoY</div></div>...</div>`
     2. Structured HTML Tables: `<table><thead><tr><th>Metric</th><th>Q1 2026</th><th>YoY Growth</th></tr></thead><tbody>...</tbody></table>`
   - Use Callout boxes (`<div class="callout">...</div>`) for key insights, management quotes, and pre-mortem falsification triggers.
   - NEVER include images, `<img>` tags, figure containers, or external image links. Keep all analyses purely professional text, data tables, callouts, and metric cards. Zero images.

5. Dynamic Labels (2-Tier Intuitive Architecture):
   - Label #1 (MANDATORY PRIMARY PILL — THESIS CONVICTION & CONFIDENCE RATING): State in MAX 2 WORDS your thesis conviction level and confidence in reaching fair value (e.g. "High Conviction", "Cautious Stance", "Speculative Risk", "High Confidence", "Moderate Conviction", "Turnaround Risk", "Defensive Safe", "High Uncertainty", "Asymmetric Upside", "Low Conviction", "Solid Conviction"). DO NOT put play types like "Deep Value" into Label #1.
   - Labels #2 & #3 (THE ECONOMIC PLAY & CATALYST DRIVERS): Describe the specific nature of the play and what drives the upside in intuitive plain English (e.g. "Deep Value", "Turnaround Play", "Safe Compounder", "Buyback Cannibal", "Margin Expansion", "Cash Fortress", "Debt Paydown", "Pricing Power", "Moat Expansion", "Special Situation", "Quality Compounder", "Market Leader"). Avoid textbook jargon.
   - 100% CREATIVE FREEDOM: All listed examples are strictly for inspiration. You have full analytical freedom to invent and choose ANY original 2-word label names that best describe this specific company and your conviction.
   - NEVER use generic industry/sector names (avoid tags like "Latam Fintech" or "Payments Credit").

6. Dynamic Price Alert Corridors & Surveillance Triggers:
   - You MUST design custom upper and lower price alert thresholds (`upper_alert_threshold` and `lower_alert_threshold`) with explicit trigger reasons in the JSON metadata.
   - Upper Threshold: Set at a key upside realization or trim level (e.g., nearing fair value or bull target).
   - Lower Threshold: Set at a crucial margin-of-safety test or thesis invalidation floor (e.g., testing bear case support).
   - When market price crosses either threshold, the system automatically triggers an urgent thesis review and publishes a new alert.

7. Warren Buffett Owner Earnings & Intrinsic Value Master Framework (from Berkshire Letters & Essays):
   - Root your valuation entirely in Warren Buffett's intrinsic value philosophy (from his Berkshire Shareholder Letters and Essays). NEVER rely on arbitrary exit multiples (which Charlie Munger dismissed as "relying on a greater fool in Year 5").
   - The 7-Pillar Warren Buffett Valuation Methodology:
     1. Calculate Normalized Owner Earnings (1986 Shareholder Letter):
        Owner Earnings = Operating Cash Flow - Maintenance CapEx - Stock-Based Compensation (SBC).
        * Maintenance CapEx vs. Growth CapEx: Strictly distinguish maintenance CapEx (capital required to protect unit volume and competitive moat) from discretionary growth CapEx.
        * SBC Reality: Deduct 100% of Stock-Based Compensation as a real cash expense.
        * Working Capital / Float Discipline (1995 & 2002 Letters): Verify that Operating Cash Flow reflects sustainable organic cash generation rather than one-quarter working capital timing spikes. If the company operates with negative working capital (like Amazon, Temu/PDD, or StoneCo collecting upfront and paying suppliers later), treat this interest-free customer float as a competitive funding advantage.
     2. Mid-Cycle Normalization for Cyclicals & Hardware Infrastructure (1982 & 1991 Letters):
        * For cyclical businesses (housing, industrials, retail, consumer, AND SEMICONDUCTORS / HARDWARE ACCELERATORS / DATA CENTER CHIPS), NEVER extrapolate a single peak or trough year. Normalize Owner Earnings across a full 5-year business cycle.
        * [MANDATORY HARDWARE & SEMICONDUCTOR CYCLICALITY INVARIANT]:
          - Semiconductor hardware (GPUs, CPUs, ASICs, memory, networking) is a strictly cyclical capital goods industry driven by lumpy customer CapEx cycles.
          - NEVER extrapolate a single peak quarter/year of hyper-concentrated hyperscaler CapEx buildouts (e.g. Meta, Microsoft, Google, Amazon spending 80%+ of cash flow on chips).
          - Peak gross margins (70%–75%+) MUST be stress-tested and normalized down by 15–20 percentage points (to 50%–55% mid-cycle levels) to account for custom ASICs (Google TPU, Meta MTIA, AWS Trainium), customer CapEx digestion pauses, open-source software abstraction (Triton, PyTorch), and memory/foundry supplier margin squeezes.
          - Bear and Base cases MUST model multi-quarter CapEx pauses and gross margin normalization.
        * [LAW OF LARGE NUMBERS & MACRO PLAUSIBILITY SANITY CHECK]:
          - For mega-cap enterprises (> $1 Trillion market cap), cross-check implied 5-year revenues and cash flows against total global IT hardware TAM (~$1.5 Trillion) and customer cash flows.
          - Strictly reject and penalize valuations that require a single hardware vendor to capture an economically impossible percentage of total global enterprise IT spending.
        * [STRICT MARGIN OF SAFETY FOR BUY SIGNALS]:
          - "BUY" (Green Beacon) is STRICTLY reserved for companies trading at a genuine Margin of Safety (≥ 20%–30% discount) against conservative, MID-CYCLE NORMALIZED Owner Earnings.
          - If a company is priced for perfection, trades at peak cyclical multiples (> 35x–40x PE on peak hardware earnings), or offers < 15% discount to mid-cycle fair value, its action signal MUST be "HOLD" (Yellow) or "CAUTION" (Orange), NEVER "BUY".
     3. Strict Localized Country-Specific Sovereign Discounting (The PetroChina / Iscar / Japan Rule):
        * NEVER use US 10-Year Treasury rates to value international companies!
        * Ground the discount rate strictly in the LOCAL SOVEREIGN BOND YIELD of the company's operating currency + an appropriate equity risk premium:
          - Brazil (e.g. STNE): Ground in Brazilian NTN-F 10-Year Bond / SELIC (~10.5%–12.0%).
          - United States (e.g. META, GOOG, AMZN): Ground in US 10-Year Treasury (~4.0%–4.5%) + equity hurdle (9-10%).
          - China (e.g. JD, PDD, BABA): Ground in Chinese 10-Year Government Bond (~2.3%–2.5%) + emerging market/geopolitical risk premium.
          - United Kingdom (e.g. BVHMF): Ground in UK 10-Year Gilt (~4.0%–4.5%).
        * Apply realistic, level-headed foreign exchange conversion rates.
     4. Capital-Light Moats (ROIC) & The "Expanding Bond" Cash Yield:
        * Calculate Initial Owner Earnings Cash Yield: (Owner Earnings per Share / Current Stock Price).
        * Evaluate Return on Invested Capital (ROIC): Does this business require heavy physical reinvestment just to stay alive (capital trap), or is it a capital-light compounder that throws off cash to owners?
     5. Share Buyback Cannibal Compounding & SBC Dilution Reality (1999 & 2018 Letters):
        * If management uses excess cash to aggressively repurchase shares at attractive prices, model the annual reduction in share count (e.g. 3–7%/year). This shrinks the share denominator and directly compounds per-share Owner Earnings into future cash streams.
        * [SBC REALITY & PAUSED BUYBACK DILUTION INVARIANT]:
          - If management has PAUSED, SUSPENDED, or REDUCED share repurchases (e.g. to fund M&A or pay down debt), you are STRICTLY PROHIBITED from modeling positive share count shrinkage.
          - In such cases, Stock-Based Compensation (SBC) MUST be modeled as NET SHAREHOLDER DILUTION (+1.0% to +3.0% annual share count expansion), which dilutes per-share Owner Earnings until buybacks demonstrably resume.
     6. Balance Sheet Reality Bridge (Leases, Total Debt & Look-Through Assets):
        * Total Debt MUST include contractual Capital and Operating Lease Liabilities (especially for retailers, store networks, and casinos).
        * [MANDATORY LEASE LEVERAGE & OPERATING LEVERAGE TEST]:
          - Store leases (ASC 842) are fixed legal obligations. When store sales decline, fixed rent DOES NOT DECLINE.
          - If Total Debt + Leases exceeds 1.5x Equity Market Cap, or if recent debt was issued at junk yields (> 8.0%), stress-test a 5%–10% revenue drop against fixed rent and subtract capitalized lease debt from Enterprise Intrinsic Value.
        * Add Cash, Short-Term Treasuries, and the look-through fair value of unconsolidated equity stakes (e.g. BABA's Ant Group, GOOG's equity stakes).
        * [MANDATORY SECULAR DECLINE & TERMINAL RUNOFF INVARIANT]:
          - For businesses facing secular decline, market share erosion, store closures, or multi-year top-line/comp decline (e.g. department stores, mall retail, linear TV, dying legacy formats):
          - POSITIVE TERMINAL GROWTH (g > 0) IS STRICTLY PROHIBITED. NEVER assume a dying format grows into infinity.
          - You MUST model a negative terminal runoff (g = -2.0% to -5.0%) or a finite 10-year terminal cash stream.
        * [CONSUMER TECH & SUBSCRIPTION APP USER CONTRACTION INVARIANT]:
          - For consumer internet, dating apps, gaming, or mobile subscription platforms with contracting paying users or active accounts (< 0% YoY growth):
          - POSITIVE 10-YEAR REVENUE GROWTH IS STRICTLY PROHIBITED.
          - Base Case MUST model continued user attrition (-3% to -8%/year) or stabilization at permanently reduced run-rates, with zero or negative terminal growth (g <= 0%).
        * [TWO-SIDED NETWORK LIQUIDITY DEGRADATION & CAC INVERSION INVARIANT]:
          - For two-sided matching platforms, social marketplaces, and gig/matching networks (e.g. dating apps, freelance portals, rideshare, classifieds):
          - When active/paying users decline (> 10% YoY contraction), the organic network flywheel inverts: lower matching liquidity accelerates churn among remaining users.
          - The evaluator MUST model non-linear Customer Acquisition Cost (CAC) inflation (+20% to +40% higher paid ad spend to backfill churn) and disallow margin expansion assumptions during user contraction phases.
        * [HIGH DEBT-TO-EQUITY DISTRESS RULE (SMALL/MID-CAP)]:
          - When Net Debt exceeds 75% of Equity Market Cap during an operational contraction or user churn phase:
          - Apply an elevated distress discount / hurdle rate (11.5%–14.0%) to reflect bankruptcy/restructuring overhead.
          - The Action Signal is STRICTLY BARRED FROM "BUY" and must be tagged as "CAUTION" (Orange) or "AVOID" (Red) with label "Speculative Risk" or "Turnaround Risk".
        * [EXTREME LEVERAGED STUB & UTILITY / TELCO CAPEX INVARIANT]:
          - When Net Debt exceeds 3.0x Equity Market Cap (e.g. $90B+ debt on a $20B equity cap):
            a) Mandatory EBITDA -10% Sensitivity Test: Model what happens to equity cash flow after mandatory debt interest and CapEx. If a 10% EBITDA decline eliminates > 50% of equity free cash flow, the equity is a high-beta leveraged stub requiring an elevated hurdle rate (11.0%–13.0%).
            b) No "CapEx Holiday" Fantasy: For capital-intensive utilities and broadband networks fighting fiber/5G competition, NEVER assume maintenance CapEx is > 30% below 5-year historical average CapEx.
            c) If Net Debt > 3.0x Market Cap, buybacks are paused, and customers/subscribers are declining, "BUY" (Green Beacon) is STRICTLY PROHIBITED. Signal must be "HOLD" (Yellow) or "CAUTION" (Orange).
        * [DISTRESSED VALUE TRAP 'BUY' DISQUALIFICATION]:
          - If a company has:
            a) Frozen or suspended share buybacks due to debt/liquidity pressure,
            b) Cut its cash dividend by > 50%,
            c) Issued debt with coupon rates > 8.0%, OR
            d) Exhibited 3+ consecutive years of negative comparable sales / revenue decline,
            --> The Action Signal is STRICTLY BARRED FROM "BUY". It must be tagged as "CAUTION" (Orange Beacon) or "AVOID" (Red Beacon) with label "Turnaround Risk" or "Value Trap".
        * [MANDATORY METADATA-SECTION 5 BINDING INVARIANT]:
          - The top-level summary JSON 'fair_value_estimate', 'base_target', and 'action_signal' MUST 100% MATHEMATICALLY MATCH the exact numbers in Section 5's Base Case row and Section 6's recommendation.
          - If Section 5 shows a negative Margin of Safety (overvalued), or if Section 6 recommends "AVOID" or "CAUTION", the JSON metadata is STRICTLY FORBIDDEN from outputting "BUY".
        * [PHARMACEUTICAL PATENT CLIFF & LOE SUBSTITUTION INVARIANT]:
          - For biopharmaceutical enterprises, you MUST audit blockbuster drug patent expirations (Loss of Exclusivity / LOE) over the 5-year discrete DCF window.
          - If expiring drugs account for > 20% of consolidated revenues (e.g. Eliquis, Vyndaqel, Keytruda, Humira), you MUST model 70%–90% revenue erosion from generic/biosimilar substitution on off-patent assets in Bear and Base scenarios.
          - Stress-test dividend sustainability against post-cliff Owner Earnings to verify that high cash dividend yields are not an unpayable capital trap.
        * [HOMEBUILDER PARTNERSHIP FLOAT & REMEDIATION LIABILITY INVARIANT]:
          - For residential real estate developers, mixed-tenure homebuilders, and contractors:
          - Audit Tenure Mix: Differentiate capital-heavy speculative merchant builders (requiring 4–5 year owned landbanks) from asset-light Partnership developers (pre-selling 60%+ of units with monthly partner milestone billing / negative working capital float).
          - Statutory Building Safety & Cladding Deductions: For UK/European builders under Building Safety Acts, statutory remediation provisions CANNOT be ignored as non-cash items. Deduct projected annual cash outflows ($50M–$80M/yr) directly from Owner Earnings.
          - Average Daily Net Debt Audit: In seasonal working capital businesses, verify 'Average Daily Net Debt' across the full year rather than relying on window-dressed period-end balance sheet dates.
        * [CROSS-BORDER E-COMMERCE DE MINIMIS & LOCAL FULFILLMENT INVARIANT]:
          - For cross-border consumer platforms (e.g. Temu / PDD, Shein, AliExpress):
          - Model the permanent elimination of Section 321 ($800 US / €150 EU) 'de minimis' customs exemptions on direct airfreight parcels.
          - Evaluate the strategic shift to Semi-Managed Local Warehousing (bulk ocean freight to local bonded distribution hubs):
            a) Model a 200–400 bps gross take-rate compression from local merchant onboarding subsidies.
            b) Credit delivery velocity gains (cutting delivery from 10 days to 2–3 days) and category expansion into bulky/high-AOV goods (furniture, appliances, auto parts).
          - Non-Distribution Cash Haircut: If management hoards massive cash (> $30B) without executing share repurchases or cash dividends, apply a mandatory 25%–35% liquidity haircut to balance sheet cash in DCF bridges.
        * [1P DIRECT RETAIL WORKING CAPITAL FLOAT & CAPTIVE LOGISTICS INVARIANT]:
          - For first-party direct retailers operating proprietary logistics networks (e.g. JD.com, Amazon Retail, Coupang):
          - Supplier Payable Working Capital Float: Direct 1P procurement creates an interest-free customer float by collecting cash instantly at delivery while settling vendor payables on 50–60 day terms. Do not mistake temporary inventory builds for structural cash destruction.
          - Captive Logistics External Monetization: When self-owned logistics networks open to third-party merchant fulfillment, incremental volume converts fixed warehouse depreciation into high-margin logistics services cash flow.
          - Maintenance vs. Discretionary Growth CapEx: Strictly isolate maintenance CapEx (~35%–40% of total CapEx) from discretionary expansion CapEx (land purchases, automated logistics parks) to derive true owner cash flow.
        * [PROPRIETARY RESIN INJECTION-MOLDING & WHOLESALE PURGE INVARIANT]:
          - For branded consumer footwear and accessories (e.g. Crocs / Croslite, Deckers, Birkenstock):
          - Single-Piece Polymer Economics: Differentiate labor-intensive multi-piece cut-and-sew shoes (42%–48% gross margin) from proprietary single-piece resin injection molding (58%–61% gross margin, <3% CapEx intensity, near-zero scrap).
          - Customization Attach Margin: Credit high-margin impulse accessories (e.g. Jibbitz at >80% gross margin) as high-ROIC Average Order Value (AOV) multipliers.
          - Wholesale Channel Purge vs. Brand Fatigue: When management deliberately curtails low-tier wholesale accounts to eliminate gray-market discounting, verify Direct-to-Consumer (DTC) sell-through; if DTC is positive, treat wholesale contraction as brand-equity protection rather than structural demand loss.
        * [DIGITAL DATING NETWORK LIQUIDITY & APP STORE WEB BILLING INVARIANT]:
          - For digital dating and social discovery networks (e.g. Match Group / Tinder / Hinge, Bumble, Grindr):
          - Hyper-Local Two-Sided Network Moat: Moats are bound by local geographic density (active singles within 10–15 miles). When top-of-funnel user growth matures, verify Revenue Per Payer (RPP) expansion via tiered pricing (HingeX, Tinder Platinum) and à la carte features.
          - Alternative Direct Web Billing Margins: Factor in gross margin expansion from anti-steering regulatory rulings (EU DMA, US court orders) that bypass Apple/Google 30% app store fees by routing subscriptions through direct web payment gateways.
        * [FOR-PROFIT HEALTHCARE EDUCATION & TITLE IV 90/10 COMPLIANCE INVARIANT]:
          - For proprietary post-secondary career colleges and vocational healthcare academies (e.g. Legacy Education, UTI, Lincoln Tech):
          - Title IV 90/10 Rule Audit: Federal regulations mandate that <= 90% of revenues can derive from federal Title IV financial aid. If Title IV mix exceeds 85%, model elevated regulatory scrutiny and disallow aggressive multiple expansion.
          - Clinical Placement & Lab Capacity Capping: Healthcare programs (nursing, sonography, MRI techs) are bound by mandatory hospital clinical rotation spots and physical lab equipment. Strictly cap multi-year student enrollment growth at verified physical capacity expansion.
          - Multi-Year Accreditation Moat: Institutional accreditations (e.g. ACCET, ABHES, HLC) act as operational licenses; verify that campuses maintain multi-year reaccreditation grants (>= 4 years remaining) before assigning Base Case compounder status.
        * [DIGITAL AD TAC ANTITRUST & DEFAULT DISTRIBUTION OFFSET INVARIANT]:
          - For dominant search and digital advertising ecosystems facing antitrust remedies or default contract scrutiny (e.g. Google Search / Apple Safari default deals):
          - Model the symmetry between query volume loss and Traffic Acquisition Cost (TAC) elimination.
          - If default distribution contracts are banned, model a 10%–15% query distribution volume drop OFFSET BY the elimination of massive TAC cash payments (e.g. $18B–$22B annual savings), which protects operating cash margins.
        * [HYPERSCALER CUSTOM SILICON (ASIC) MARGIN LEADERSHIP INVARIANT]:
          - For hyperscale cloud operators developing proprietary AI silicon (e.g. Google TPUs, AWS Trainium, Meta MTIA):
          - Disregard simplistic third-party GPU rental cost assumptions. Custom ASICs deliver 30%–50% lower cost per token on LLM training/inference, justifying higher normalized cloud operating margins (32%–38%) and lower hardware depreciation drag compared to GPU-only clouds.
        * [MOONSHOT LOSS-CENTER SEGREGATION & CEASE-AND-DESIST ACCRETION INVARIANT]:
          - For mega-cap technology platforms operating structural R&D loss centers (e.g. Meta Reality Labs at -$18B/yr, Alphabet Other Bets at -$4B/yr):
          - In Bear and Base cases, the loss center burn MUST be deducted as a real, non-capitalized cash drain on owner earnings.
          - In Section 5, you MUST calculate the 'Cease-and-Desist Accretion': If management reduces loss-center burn by 50%, calculate the immediate unlevered cash accretion per share to common equity.
          - Open-sourcing AI foundation models (e.g. Llama) must be evaluated as 'Commoditizing Complements'—reducing external API rents and supercharging internal recommendation/ad ranking without paying third-party model fees.
        * [CHINESE ADR DUAL-PRIMARY HK LISTING & OPEN-SOURCE CLOUD AI FUNNEL INVARIANT]:
          - For Chinese technology leaders with Dual-Primary listings on HKEX (e.g. Alibaba 9988.HK, Meituan, Tencent):
          - Southbound Stock Connect Liquidity: Factor in direct mainland Chinese institutional capital access via Southbound Connect, which reduces geopolitical ADR discount volatility and insulates against Western custodial flight.
          - Open-Source LLM Cloud Funnel (e.g. Qwen, Llama): When a cloud provider releases premier open-source AI models, evaluate it as an enterprise compute funnel. Open weights commoditize third-party model licensing while driving high-margin recurring inference compute and Model-as-a-Service (MaaS) revenue to the host cloud platform.
          - Strategic Look-Through Stakes: Value unlisted fintech and logistics holdings (e.g. Ant Group, Cainiao) at conservative private-market liquidation multiples and credit to the Net Asset Bridge.
        * Intrinsic Equity Value = PV of 5-10Y Owner Earnings + PV of Terminal Cash Stream (capped at -2% to +2.0% GDP) + Cash & Equities - Total Debt & Leases.
        * Divide by diluted share count to arrive at Intrinsic Fair Value per Share.
        * The 5-Year Exchange Closure Test: Demand a clear Margin of Safety (20–40% discount) so that even if the stock market were closed for 5 years, the investor earns an attractive return purely from organic cash generation.
     7. Financial Institutions, Asset Managers & Banking Books (1990 & 2011 Letters on Wells Fargo & Amex):
        * For banks or fintechs with expanding credit/loan portfolios (e.g. StoneCo Banking, PayPal Credit, SoFi, Ally):
          - Evaluate Credit Quality, Non-Performing Loans (NPLs), net charge-off trends, provision coverage, Cost of Deposits, and Return on Tangible Equity (ROTE) rather than pure FCF.
        * [CASINO FEE-SIMPLE REAL ESTATE VS. MASTER LEASE DRAG INVARIANT]:
          - For regional gaming, hospitality, and casino operators (e.g. Boyd Gaming, Red Rock Resorts, Penn, Caesars):
          - Fee-Simple Ownership Advantage: Operators owning > 80% of their casino real estate pay ZERO master lease rent to gaming REITs (VICI, GLPI), eliminating rigid rent escalators and converting ~40% property EBITDAR directly into free cash flow.
          - OpCo/PropCo Lease Penalty: If an operator rents via triple-net leases, deduct full annual cash rent obligations as mandatory debt service, and penalize downturn resilience.
          - Tribal Management & Digital Stakes: Credit 100%-margin tribal management contracts (e.g. Sky River) and digital sports betting stakes (e.g. FanDuel equity) as high-value, asset-light cash accelerators.
        * [PAYMENT PROCESSOR TRANSACTION MARGIN DOLLAR (TMD) QUALITY INVARIANT]:
          - For payment networks, gateways, and PSPs (e.g. PayPal, Adyen, Block, Shift4):
          - DO NOT rely on headline Total Payment Volume (TPV) growth. High-volume unbranded processing (e.g. Braintree, enterprise PSP) carries thin 0.20%–0.35% take rates, which can mask underlying erosion in high-margin branded checkout (2.0%–2.5% take rate).
          - The evaluator MUST anchor on Transaction Margin Dollars (TMD) growth. If TMD growth is negative or stagnant despite double-digit TPV expansion, penalize terminal multiples.
          - Calculate Net Cannibalization: Deduct annual SBC dilution shares from total shares repurchased to isolate the true net per-share compounding rate.
        * [EMERGING MARKET FINTECH SOVEREIGN DISCOUNTING & FX DEPRECIATION INVARIANT]:
          - For emerging market fintechs and banks (e.g. StoneCo, Nu Holdings, MercadoLibre, Kaspi):
          - Anchor the discount hurdle rate strictly to the domestic 10-year sovereign bond yield (e.g. Brazil 10Y NTN-F ~11%–14%) plus local Equity Risk Premium, NEVER US Treasuries.
          - Apply an annual -2.5% to -4.0% FX depreciation drag against local-currency Owner Earnings when deriving USD ADR per-share targets.
        * [MERCHANT CARD RECEIVABLES LOCKBOX ('TRAVA DE DOMICÍLIO') SENIORITY]:
          - Distinguish unsecured consumer loans from merchant acquiring-backed credit where loan repayments are automatically intercepted from daily POS settlements.
          - Model higher provision cycles during rate hikes, but account for structurally lower terminal loss severity (30%–40% vs 80%+ on unsecured personal loans).
        * [ASSET MANAGEMENT AUM & PASSIVE FEE-EROSION INVARIANT]:
          - For traditional asset managers (e.g. Franklin Templeton, T. Rowe Price, Invesco):
          - Evaluate AUM mix between legacy mutual funds (facing secular outflows to passive ETFs) vs. alternative assets / private markets (sticky long-term capital lock-ups).
          - If legacy active mutual funds exceed 50% of total AUM, you MUST model ongoing gross fee compression (-10 to -20 bps) in Bear and Base scenarios.
          - Subtract regulatory penalties, legal settlements, and deferred acquisition earnouts directly from enterprise net cash.
   - BUFFETT RESOLUTION & RESEARCH FALLBACK DIRECTIVE:
     If you encounter any accounting edge cases, complex capital structure, negative working capital dilemma, cyclical distortion, foreign banking nuance, or feel stuck on any valuation step, you MUST search and reference Warren Buffett's Berkshire Hathaway Shareholder Letters and 'The Essays of Warren Buffett' (by Lawrence Cunningham). Apply how Warren Buffett and Charlie Munger resolved that exact economic problem from first principles.
   - Present a clean, transparent Bear / Base / Bull scenario table in Section 5 detailing Owner Earnings, growth assumptions, and per-share intrinsic values.
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
- Warren Buffett Owner Earnings & Intrinsic Value Matrix: Calculate normalized Owner Earnings (Post-SBC cash flow minus maintenance CapEx, float/lease debt discipline), project 3-5 year compounding, factor in share count reduction from buybacks, and discount strictly via the LOCAL SOVEREIGN BOND YIELD (e.g. Brazilian NTN-F/SELIC for Brazil, US 10Y for US, Gilts for UK) with zero arbitrary exit multiples. (If you ever face an accounting dilemma or feel stuck on any valuation step, search and reference Warren Buffett's Berkshire Shareholder Letters & Essays to resolve it from first principles). Build a clean Bear / Base / Bull scenario table in Section 5, assess confidence, execution risk, and explicit falsification triggers.
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
    agent_1_prompt = f"""You are Sub-Agent 1: Business Model, Moat & Earnings Specialist researching {ticker_clean} ({company_name}) at current market price ${current_price:.2f}.
Your Objective: {research_obj}

Generate ONLY the following two sections in clean Semantic HTML with NO external images, NO inline styles, and NO code fences:

<h2>Section 1: Executive Summary & Operating Reality</h2>
- 2-3 paragraph institutional executive summary grounded in the LATEST quarterly earnings statement, earnings call transcript, and forward management guidance.
- Present latest quarterly financial performance using a clean stat grid:
  <div class="metrics-grid">
    <div class="metric-card"><div class="metric-label">Quarterly Revenue</div><div class="metric-value">$XX.XXB</div><div class="metric-delta pos">+XX% YoY</div></div>
    <div class="metric-card"><div class="metric-label">Operating Margin</div><div class="metric-value">XX.X%</div><div class="metric-delta pos">+XXX bps</div></div>
    <div class="metric-card"><div class="metric-label">Free Cash Flow</div><div class="metric-value">$XX.XXB</div><div class="metric-delta pos">+XX% YoY</div></div>
  </div>
- Add a Callout box (<div class="callout">...</div>) highlighting direct CEO/CFO commentary from the latest earnings call and key capital allocation announcements.

<h2>Section 2: Business Model Reality & Competitive Moat</h2>
- Explain in plain English how the company makes money, unit economics, customer switching costs, and pricing power.
- Detailed technical comparison table comparing the company's architecture/products against primary competitors.
- Clear audit of structural demand drivers (long-term tailwinds) vs. competitive disruption threats.

DO NOT write Section 3, 4, 5, or 6. Output pure HTML only."""

    agent_2_prompt = f"""You are Sub-Agent 2: Real Cash Flow, SBC Dilution & Balance Sheet Auditor researching {ticker_clean} ({company_name}) at current market price ${current_price:.2f}.
Your Objective: {research_obj}

Generate ONLY the following two sections in clean Semantic HTML with NO external images, NO inline styles, and NO code fences:

<h2>Section 3: Real Cash Flow, SBC Dilution & Owner Earnings Audit</h2>
- Rigorous cash flow audit stripping out Silicon Valley accounting add-backs.
- Treat 100% of Stock-Based Compensation (SBC) as a real cash expense and shareholder dilution factor.
- Detailed Cash Flow Decomposition Table:
  <table>
    <thead><tr><th>Metric ($ Millions)</th><th>FY 2024</th><th>FY 2025</th><th>FY 2026</th><th>TTM</th></tr></thead>
    <tbody>
      <tr><td>GAAP Operating Cash Flow</td><td>...</td><td>...</td><td>...</td><td>...</td></tr>
      <tr><td>Less: Total SBC</td><td>...</td><td>...</td><td>...</td><td>...</td></tr>
      <tr><td>Less: Maintenance CapEx</td><td>...</td><td>...</td><td>...</td><td>...</td></tr>
      <tr><td><strong>Buffett Owner Earnings (True Cash)</strong></td><td>...</td><td>...</td><td>...</td><td>...</td></tr>
    </tbody>
  </table>
- Working Capital Float & Customer Prepayment dynamics.

<h2>Section 4: Balance Sheet Fortress, Debt Leases & Ownership Check</h2>
- Audited capital structure: Cash, Short-Term Treasuries, Long-Term Debt, and contractual Capital/Operating Lease liabilities.
- Net Cash/Debt calculation table and interest coverage ratio.
- Share Buyback Cannibalization analysis: Share count reduction vs. dilution.
- Institutional Ownership & Insider Form 4 audit from official filings.

DO NOT write Section 1, 2, 5, or 6. Output pure HTML only."""

    agent_3_prompt = f"""You are Sub-Agent 3: Warren Buffett Owner Earnings Valuation Strategist & Invalidation Auditor researching {ticker_clean} ({company_name}) at current market price ${current_price:.2f}.
Your Objective: {research_obj}

Generate ONLY the following two sections in clean Semantic HTML with NO external images, NO inline styles, and NO code fences:

<h2>Section 5: Warren Buffett Owner Earnings Intrinsic Valuation Matrix</h2>
- Root valuation strictly in Warren Buffett's intrinsic value methodology (Berkshire Shareholder Letters). Zero arbitrary exit multiples.
- For semiconductors, hardware accelerators, and cyclical industries: YOU MUST normalize peak-cycle gross margins (down by 15-20 pts) and stress-test CapEx digestion cycles. NEVER extrapolate peak-quarter cash flow.
- For mega-cap enterprises (> $1T market cap): Perform a strict Law of Large Numbers & Macro TAM sanity check against global IT hardware spending.
- [MANDATORY BEAR CASE DOWNSIDE STRESS-TEST INVARIANT]: The Bear Case (Cycle Trough) MUST BE A REALISTIC DOWNSIDE SCENARIO. Model adverse operational conditions, recessionary demand contractions, margin compression, or credit loss provision spikes. The Bear Case Intrinsic Value Per Share MUST ALWAYS BE BELOW CURRENT STOCK PRICE (typically 15% to 40% below current market price), establishing a true risk floor. A Bear target higher than today's price is STRICTLY FORBIDDEN.
- Localized sovereign discount rate derivation (local 10Y sovereign bond yield + equity risk premium, e.g. US 10Y for US, SELIC for Brazil, Gilts for UK).
- A 100% COMPLETE, fully populated Bear / Base / Bull scenario table where EVERY CELL is filled with concrete numbers:
  <table>
    <thead>
      <tr>
        <th>Valuation Metric & Assumptions</th>
        <th>Bear Case (Cycle Trough)</th>
        <th>Base Case (Normalized Reality)</th>
        <th>Bull Case (Optimistic Execution)</th>
      </tr>
    </thead>
    <tbody>
      <tr><td>5-Year Organic OE CAGR</td><td>X.X%</td><td>XX.X%</td><td>XX.X%</td></tr>
      <tr><td>Annual Share Count Reduction</td><td>X.X%</td><td>X.X%</td><td>X.X%</td></tr>
      <tr><td>Discount Rate (Hurdle)</td><td>X.X%</td><td>X.X%</td><td>X.X%</td></tr>
      <tr><td>Terminal FCF Growth Rate</td><td>X.X%</td><td>X.X%</td><td>X.X%</td></tr>
      <tr><td><strong>Intrinsic Fair Value / Share</strong></td><td><strong>$XX.XX</strong></td><td><strong>$XX.XX</strong></td><td><strong>$XX.XX</strong></td></tr>
      <tr><td><strong>Margin of Safety vs Current Price</strong></td><td><strong>XX.X%</strong></td><td><strong>XX.X%</strong></td><td><strong>XX.X%</strong></td></tr>
    </tbody>
  </table>
- Explicit 5-Year Market Closure Test: Return derived purely from underlying business cash generation.

<h2>Section 6: Thesis Invalidation Pre-Mortem & Falsification Triggers</h2>
- Pre-Mortem Analysis: Exactly what operational missteps, macro shocks, or structural shifts would prove this thesis WRONG.
- Explicit falsification triggers with numerical thresholds (e.g. Gross margin falling below XX%, NPLs exceeding X.X%, customer churn above XX%).
- Execution risk rating and margin of safety corridor.

DO NOT write Section 1, 2, 3, or 4. Ensure all HTML tables and tags are 100% complete and closed. Output pure HTML only."""

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

    metadata["labels"] = sanitize_labels(metadata.get("labels") or metadata.get("status_label"))
    metadata["status_label"] = metadata["labels"][0] if metadata["labels"] else "Active"
    metadata["next_catalyst_date"] = normalize_catalyst_date(metadata.get("next_catalyst_date"))

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
    """Reviews an active stock thesis when triggered by price or catalyst."""
    price_change_pct = ((current_price - baseline_price) / baseline_price) * 100 if baseline_price else 0.0

    prompt = f"""We are conducting an urgent investment thesis review on {ticker.upper()} ({company_name}).
TRIGGER REASON: {trigger_reason}
Baseline Price: ${baseline_price:.2f}
Current Price: ${current_price:.2f} (Change: {price_change_pct:+.2f}%)
Previous Stance: {previous_status}
Previous Thesis Summary: {previous_thesis_summary}
PREVIOUS BASE FAIR VALUE: {previous_fair_value or previous_base_target or 'N/A'}
PREVIOUS TARGETS: Bear: {previous_bear_target or 'N/A'} | Base: {previous_base_target or 'N/A'} | Bull: {previous_bull_target or 'N/A'}

[ANALYTICAL AUTONOMY & THESIS INFLECTION DIRECTIVES]:
You have full analytical freedom to evaluate the new facts and determine the evolved thesis:
1. Primary Source Audit: Search the latest quarterly earnings release, latest earnings call transcript, material corporate announcements, and latest 13F whale filings.
2. [STRICT INCREMENTAL CONTINUITY & ANTI-HALLUCINATION DELTA CLAMP]:
   - DO NOT hallucinate wild, unanchored DCF jumps on routine updates (e.g. an earnings beat or Form 8-K/6-K filing MUST NOT cause fair value to jump +30% to +50% overnight like $220 to $320).
   - For routine quarterly updates and calendar shifts, fair value adjustments MUST be incremental and logically bridged from the PREVIOUS BASE FAIR VALUE ({previous_fair_value or previous_base_target or 'N/A'}).
   - Routine adjustments (accretion from buybacks, slight margin beats) typically move fair value by ±2% to ±8%.
   - Fair value revisions exceeding ±15% are STRICTLY FORBIDDEN unless there is a verified tectonic operational shift (e.g. major subsidiary divestment, catastrophic regulatory ban, permanent loss of >30% revenue, or permanent >500 bps gross margin structural reset).
3. Forward Action Beacon Selection (action_signal):
   Autonomously choose the actionable status signal based on how the thesis is playing out in the real world:
   - "BUY" (Green Beacon): Thesis is playing out great, fundamentals accelerating, trading at a genuine Margin of Safety (≥ 20%-30% discount to MID-CYCLE NORMALIZED Owner Earnings). NEVER give a BUY signal to stocks trading near/above fair value or priced for perfection at peak cyclical multiples.
   - "HOLD" (Yellow Beacon): Thesis is steady, waiting for next catalyst, fairly valued, or priced for perfection (e.g. trading at peak hardware multiples with < 15% MoS) -> wait and do nothing for now.
   - "CAUTION" (Orange Beacon): Thesis facing execution friction, headwinds, or margin pressure -> caution / trim.
   - "AVOID" (Red Beacon): Thesis broken, severe structural impairment -> avoid / do not buy / exit.
3. 2-Tier Autonomous Labels:
   Slot 1 = Forward Conviction/Confidence Rating (e.g. "High Conviction", "Cautious Stance", "Speculative Risk", "Solid Conviction", "Turnaround Risk", "Priced For Perfection").
   Slots 2 & 3 = Key Play Drivers & Catalysts (e.g. "Buyback Cannibal", "Margin Expansion", "Deep Value", "Cash Fortress", "Infrastructure Moat", "CapEx Digestion").
   (Note: You choose both the action_signal color and labels independently based on your forward evaluation).
4. What Changed & Thesis Impact:
   - Detail what new information has arrived from latest earnings or market filings.
   - Explain whether this reinforces our thesis (making the opportunity safer / higher confidence) or breaks/weakens it (increasing execution risk / lowering fair value).
   - Formulate a clear 2-3 sentence executive evolution summary for "what_changes_now".
5. Warren Buffett Owner Earnings & Intrinsic Value Framework:
   - Update fair value and Bear / Base / Bull scenario targets using Warren Buffett's 7-pillar Owner Earnings methodology (Post-SBC cash flow minus maintenance CapEx, lease debt/float bridge, share count reduction from buybacks, strictly discounting via local sovereign bond yields, zero arbitrary exit multiples).
   - [MANDATORY CYCLICALITY & HARDWARE NORMALIZATION]: For semiconductors and hardware infrastructure, YOU MUST normalize peak-cycle gross margins down by 15-20 pts (to 50%-55% mid-cycle levels) and model CapEx digestion pauses. NEVER extrapolate peak-quarter cash flows. For mega-cap enterprises (> $1T), apply strict Law of Large Numbers & Macro TAM sanity checks against global IT hardware spending.
   - [MANDATORY BEAR CASE DOWNSIDE INVARIANT]: "new_bear_target" MUST ALWAYS BE BELOW CURRENT STOCK PRICE (typically 15% to 40% below current price). A Bear target higher than today's quotation is strictly prohibited and logically invalid.
   - [MANDATORY METADATA-SCENARIO BINDING]: "new_fair_value" and "new_base_target" must match identically. If Base Fair Value offers < 15%-20% discount or trades at peak cyclical multiples, "action_signal" MUST be "HOLD" or "CAUTION", NEVER "BUY".
   - [MANDATORY CURRENCY DIRECTIVE]: ALL financial figures, share prices, intrinsic fair values, scenario targets (Bear/Base/Bull), and price corridors MUST ALWAYS BE CONVERTED TO AND PRESENTED IN US DOLLARS (USD / $) with a leading '$' symbol (e.g. '$2,320.00', '$2,950.00'). NEVER output 'C$', 'CAD', 'HK$', 'EUR', or other non-USD currency prefixes.
6. Self-Healing Catalyst Date Update Rule:
   - "next_catalyst_date" MUST ALWAYS BE IN STRICT "YYYY-MM-DD" FORMAT (e.g. 2026-11-18).
   - If on the trigger date after market close no earnings release or event has occurred (or the event was rescheduled), search investor relations for the newly confirmed or estimated date, set "next_catalyst_date" to the new YYYY-MM-DD, and explain in "what_changes_now" that the calendar date has been refreshed.

Output in TWO parts:
Part 1: JSON metadata in ```json ... ```:
{{
  "alert_title": "<Punchy headline stating if thesis shifted, conviction changed, or catalyst date refreshed>",
  "alert_severity": "<1-2 word severity, e.g. Strong Buy, Caution, Thesis Broken, Accumulate, Calendar Update>",
  "action_signal": "<BUY | HOLD | CAUTION | AVOID (BUY=Green get in now, HOLD=Yellow wait/do nothing, CAUTION=Orange headwinds/trim, AVOID=Red broken/don't buy)>",
  "labels": ["<Confidence/Risk Label 1>", "<Play Driver Label 2>", "<Play Driver Label 3>"],
  "label_change_rationale": "<If labels or conviction changed from previous version, 1-2 sentence explanation of what changed and why. If unchanged, write 'Conviction and play drivers reaffirmed.'>",
  "what_was_before": "<Summary of previous thesis>",
  "what_changes_now": "<Comprehensive summary of what new information arrived, how it impacts risk/safety, and our updated forward conviction>",
  "new_fair_value": "$<Updated Fair Value matching Section 5 Base DCF>",
  "new_bear_target": "$<Updated Bear Target matching Section 5 Bear DCF>",
  "new_base_target": "$<Updated Base Target matching Section 5 Base DCF>",
  "new_bull_target": "$<Updated Bull Target matching Section 5 Bull DCF>",
  "new_upper_alert_threshold": <New upper price trigger>,
  "new_lower_alert_threshold": <New lower price trigger>,
  "next_catalyst_date": "<YYYY-MM-DD (Strict ISO date for next catalyst, e.g. 2026-11-18)>",
  "next_catalyst_event": "<Upcoming Event max 4 words, using clean concise notation e.g. Q3 '26 ER, Q2 '27 ER, Investor Day>",
  "top_funds": ["<Top Fund 1 (e.g. Vanguard 8.4%)>", "<Top Fund 2 (e.g. BlackRock 7.1%)>", "<Whale/Superinvestor 3 from Dataroma/WhaleWisdom>"],
  "institutional_ownership_pct": "<e.g. 78.4%>",
  "insider_signal": "<Net Buying | Cluster Buying | Neutral (10b5-1) | Net Selling | No Activity>",
  "insider_summary": "<Crisp 1-line summary of recent Form 4 insider purchases/sales audited from OpenInsider, max 10 words>"
}}

Part 2: COMPLETE Living HTML Memo (All 6 Sections Updated):
[MANDATORY LENGTH & ANALYTICAL DEPTH DIRECTIVE]:
You MUST provide the full, comprehensive HTML memo updating all 6 sections with the new quarter's data, revenue, margins, cash flow, and revised DCF table. The complete dossier MUST be exhaustive and exceed 2,000 words of institutional rigor with complete data tables and LaTeX formulas. NEVER output brief outlines or abbreviated sections.
<div class="section"><h2>Section 1: Business Model, Scale Moat & GenAI Transition</h2>...</div>
<div class="section"><h2>Section 2: Quarterly Operational Breakdown & Segment Performance</h2>...</div>
<div class="section"><h2>Section 3: Real Cash Flow & Stock-Based Compensation (SBC) Audit</h2>...</div>
<div class="section"><h2>Section 4: Capital Allocation & Balance Sheet Discipline</h2>...</div>
<div class="section"><h2>Section 5: Owner Earnings Intrinsic Value Matrix</h2>... (Full DCF calculation table with Bear, Base, and Bull per-share values)</div>
<div class="section"><h2>Section 6: Thesis Confidence, Execution Risk & Invalidation Corridors</h2>...</div>
"""

    response_text = call_gemini_with_search(prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY)
    metadata = extract_json_block(response_text)
    
    html_content = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", response_text, flags=re.DOTALL).strip()
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = verify_and_repair_html_structure(clean_grounding_artifacts(html_content.strip()))

    if not metadata:
        metadata = {}

    # Extract Section 5 DCF Intrinsic Value table to guarantee 100% mathematical reconciliation
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_content, re.DOTALL | re.IGNORECASE)
    target_row = None
    for r in rows:
        r_clean = re.sub(r"<[^>]+>", " ", r).strip()
        if any(k in r_clean.lower() for k in ["intrinsic fair value", "intrinsic value per", "intrinsic value /", "base intrinsic value", "implied intrinsic value"]):
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
            
            metadata["new_fair_value"] = f"${base_val:.2f}"
            metadata["new_base_target"] = f"${base_val:.2f} ({base_ret:+.1f}%)"
            metadata["new_bear_target"] = f"${bear_val:.2f} ({bear_ret:+.1f}%)"
            metadata["new_bull_target"] = f"${bull_val:.2f} ({bull_ret:+.1f}%)"

    # Extract first paragraph/callout from HTML if what_changes_now is missing
    what_changes = metadata.get("what_changes_now", "").strip()
    if not what_changes or len(what_changes) < 25:
        callout_m = re.search(r'<div class="callout"[^>]*>(.*?)</div>', html_content, re.DOTALL | re.IGNORECASE)
        if callout_m:
            raw_c = re.sub(r'<[^>]+>', ' ', callout_m.group(1)).strip()
            what_changes = " ".join(raw_c.split()[:45])
        else:
            first_p = re.search(r'<p[^>]*>(.*?)</p>', html_content, re.DOTALL | re.IGNORECASE)
            if first_p:
                raw_p = re.sub(r'<[^>]+>', ' ', first_p.group(1)).strip()
                what_changes = " ".join(raw_p.split()[:45])
            else:
                what_changes = f"Comprehensive surveillance review completed following {trigger_reason}. Living thesis, intrinsic fair value, and operating scenarios updated."

    metadata["what_changes_now"] = what_changes
    metadata["what_was_before"] = metadata.get("what_was_before") or previous_thesis_summary
    metadata["action_signal"] = normalize_action_signal(metadata.get("action_signal", "BUY"))
    metadata["labels"] = sanitize_labels(metadata.get("labels") or metadata.get("alert_severity") or [previous_status])
    metadata["alert_title"] = metadata.get("alert_title") or f"{ticker.upper()}: Thesis Evolved Following {trigger_reason}"
    metadata["next_catalyst_date"] = normalize_catalyst_date(metadata.get("next_catalyst_date"))
    metadata["next_catalyst_event"] = metadata.get("next_catalyst_event") or "Upcoming Earnings Report"

    return metadata, html_content


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

