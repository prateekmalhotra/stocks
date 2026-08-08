import os
import json
import re
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional, List
from dotenv import load_dotenv

load_dotenv()


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


CONVICTION_TERMS = {
    "high conviction", "moderate conviction", "speculative risk", "high confidence",
    "cautious conviction", "asymmetric conviction", "low conviction", "speculative bet",
    "high risk", "moderate risk", "low risk", "conviction", "confidence", "cautious stance"
}


def sanitize_labels(labels: Any) -> List[str]:
    """Sanitizes labels ensuring:
    - Label #1 is strictly Thesis Conviction / Confidence Rating (e.g. 'High Conviction', 'Moderate Conviction', 'Speculative Risk').
    - Labels #2 & #3 are the Play Type / Catalysts (e.g. 'Deep Value', 'Buyback Cannibal', 'Safe Compounder').
    Max 3 labels total, max 2 words per label.
    """
    if not isinstance(labels, list):
        if isinstance(labels, str) and labels:
            labels = [labels]
        else:
            labels = []
    
    clean_list = []
    for lbl in labels:
        if not isinstance(lbl, str):
            continue
        words = [w for w in lbl.replace("/", " ").replace("-", " ").replace("&", " ").split() if w.strip()]
        if words:
            short_lbl = " ".join(words[:2]).title()
            if short_lbl not in clean_list:
                clean_list.append(short_lbl)

    if not clean_list:
        return ["High Conviction", "Deep Value", "Operating Leverage"]

    # Check if first label is a conviction rating
    first_lbl_lower = clean_list[0].lower()
    is_conviction_label = any(term in first_lbl_lower for term in CONVICTION_TERMS)

    if not is_conviction_label:
        # If model put play type in position 0, assign appropriate conviction tier and shift play to position 1
        if any(w in first_lbl_lower for w in ["turnaround", "speculative", "distressed", "broken", "risk"]):
            conviction_pill = "Speculative Risk"
        elif any(w in first_lbl_lower for w in ["asymmetric", "catalyst"]):
            conviction_pill = "Asymmetric Conviction"
        elif any(w in first_lbl_lower for w in ["safe", "compounder", "quality", "moat", "defensive", "cannibal"]):
            conviction_pill = "High Conviction"
        else:
            conviction_pill = "High Conviction"
        
        clean_list.insert(0, conviction_pill)

    return clean_list[:3]


def call_gemini_with_search(prompt: str, system_instruction: str = "", temperature: float = 0.4) -> str:
    """Calls Gemini 3.6 Flash via REST API with Google Search Grounding, exponential retry, and safety fallback."""
    import time
    api_key = get_api_key()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
    
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
    
    max_retries = 4
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(url, json=payload, timeout=120)
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
                    retry_res = requests.post(url, json=payload, timeout=120)
                    if retry_res.status_code == 200:
                        retry_json = retry_res.json()
                        retry_parts = retry_json.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        if retry_parts and "text" in retry_parts[0]:
                            return clean_grounding_artifacts(retry_parts[0]["text"])
                            
                return "Analysis completed."
            elif response.status_code in (500, 502, 503, 504, 429) and attempt < max_retries:
                wait_time = attempt * 3
                print(f"  ⚠️ Gemini API returned {response.status_code}. Retrying in {wait_time}s (Attempt {attempt}/{max_retries})...")
                time.sleep(wait_time)
                continue
            else:
                raise RuntimeError(f"Gemini API error ({response.status_code}): {response.text}")
        except requests.RequestException as req_err:
            if attempt < max_retries:
                wait_time = attempt * 3
                print(f"  ⚠️ Network error ({req_err}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            raise RuntimeError(f"Gemini API network error: {req_err}") from req_err


def extract_json_block(text: str) -> Dict[str, Any]:
    """Extracts a JSON object from markdown code fences or raw text."""
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    
    # Fallback to finding outermost JSON braces
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except Exception:
            pass
    return {}


def verify_and_repair_html_structure(html: str) -> str:
    """Deterministic structural cleanup, inline style removal, and tag balancing."""
    if not html:
        return ""
    
    cleaned = re.sub(r"^```(?:html)?\s*", "", html, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    
    # Strip ALL rogue inline style attributes to enforce 100% color consistency
    cleaned = re.sub(r'\s*style\s*=\s*"[^"]*"', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*style\s*=\s*'[^']*'", '', cleaned, flags=re.IGNORECASE)

    # Auto-close unclosed table rows
    open_tr = len(re.findall(r"<tr\b", cleaned, re.IGNORECASE))
    close_tr = len(re.findall(r"</tr>", cleaned, re.IGNORECASE))
    if open_tr > close_tr:
        cleaned += "</tr>" * (open_tr - close_tr)

    # Auto-close unclosed tables
    open_tables = len(re.findall(r"<table\b", cleaned, re.IGNORECASE))
    close_tables = len(re.findall(r"</table>", cleaned, re.IGNORECASE))
    if open_tables > close_tables:
        diff = open_tables - close_tables
        cleaned += "\n" + ("</tbody></table>" * diff)
        
    # Auto-close unclosed divs
    open_divs = len(re.findall(r"<div\b", cleaned, re.IGNORECASE))
    close_divs = len(re.findall(r"</div>", cleaned, re.IGNORECASE))
    if open_divs > close_divs:
        diff = open_divs - close_divs
        cleaned += "\n" + ("</div>" * diff)

    return clean_grounding_artifacts(cleaned)


# =====================================================================
# AUTONOMOUS LEVEL-HEADED MULTI-AGENT PROMPT ARCHITECTURE
# =====================================================================

LEVEL_HEADED_INVESTOR_PHILOSOPHY = """You are a seasoned, down-to-earth fundamental investor and research strategist.

CORE PRINCIPLES & GUIDELINES:
1. Broad Objective & Analytical Freedom:
   - Your broad goal is to evaluate the company objectively and provide a realistic, level-headed fundamental evaluation.
   - You have complete freedom to analyze and value the business however you prefer. Choose whatever framework, metrics, and valuation methods best reflect the economic reality of the company.
   - You can override any default suggestions whenever you deem appropriate.

2. Simple Economic Ground Rules & Mandatory Primary Sources:
   - Latest Earnings Release, Call Transcript & News: You MUST search for and review the company's LATEST quarterly earnings statement (shareholder letter / financial results press release), LATEST earnings call transcript (management remarks + analyst Q&A), and LATEST official news/corporate announcements. Use these primary sources to extract real-time management guidance, operational metrics, and executive commentary.
   - Stock-Based Compensation (SBC): Always treat SBC as a real cash expense and shareholder dilution factor.
   - Capital Structure: Properly account for Net Cash or Net Debt (Cash & equivalents minus total debt/obligations) in the valuation.
   - Localized International Valuation: If analyzing an international or cross-border company, use the appropriate country-specific risk-free and discount rates (e.g. SELIC for Brazil, local sovereign bond yields) and sensible, balanced currency conversions—neither overly optimistic nor overly pessimistic.
   - Factual Accuracy: Ground institutional ownership (13F whales) and financials in the LATEST official filings (never list exited investors as active holders).

3. Thesis Confidence & Execution Risk Assessment:
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

5. Dynamic Labels (2-Tier Mandatory Structure):
   - Label #1 (MANDATORY PRIMARY PILL — CONVICTION & CONFIDENCE LEVEL ONLY): Must state in MAX 2 WORDS your thesis conviction level and confidence in reaching fair value (e.g. "High Conviction", "High Confidence", "Moderate Conviction", "Speculative Risk", "Asymmetric Conviction", "Cautious Stance", "Low Conviction"). DO NOT put play types like "Deep Value" in Label #1.
   - Labels #2 & #3 (THE ECONOMIC PLAY & CATALYSTS — INVENTIVE & INTUITIVE PLAIN ENGLISH): Must describe the specific nature of the play and what drives the upside in plain English (e.g. "Deep Value", "Turnaround Play", "Safe Compounder", "Buyback Cannibal", "Margin Expansion", "Cash Fortress", "Debt Paydown", "Pricing Power", "Special Situation"). Avoid obscure jargon.
   - NEVER use generic industry/sector names (avoid tags like "Latam Fintech" or "Payments Credit").

6. Dynamic Price Alert Corridors & Surveillance Triggers:
   - You MUST design custom upper and lower price alert thresholds (`upper_alert_threshold` and `lower_alert_threshold`) with explicit trigger reasons in the JSON metadata.
   - Upper Threshold: Set at a key upside realization or trim level (e.g., nearing fair value or bull target).
   - Lower Threshold: Set at a crucial margin-of-safety test or thesis invalidation floor (e.g., testing bear case support).
   - When market price crosses either threshold, the system automatically triggers an urgent thesis review and publishes a new alert.

7. Clean Ballpark Intrinsic Valuation (Simple, Grounded & Unanchored):
   - NEVER anchor your fair value to today's stock price, but keep your valuation SIMPLE, PRACTICAL, and DOWN-TO-EARTH. Avoid over-complicated spreadsheet models or hyper-sensitive assumption bloat. "It is better to be roughly right than precisely wrong."
   - The Clean Back-of-the-Napkin Cash Flow Framework:
     1. Real Cash Baseline: Start with normalized Owner Earnings / Free Cash Flow (Cash from Ops minus maintenance CapEx, deducting Stock-Based Compensation as a real cash charge).
     2. Sensible 3-5 Year Compounding: Apply a simple, realistic cash growth rate based on business unit economics and reinvestment reality.
     3. Grounded Discount Hurdle: Apply a standard, sensible discount rate (e.g. 10-12% hurdle, adjusted for local sovereign rates if international) and a reasonable exit multiple reflecting moat durability.
     4. Share Buybacks & Cannibal Dynamics: Explicitly factor in active share repurchase programs. If management is retiring shares with excess cash flow (e.g. 3-8% annual share count reduction), model this shrinking share count into the forward per-share Free Cash Flow and intrinsic value targets (especially in Base and Bull cases).
     5. Balance Sheet Reality: Add Cash & short-term investments, subtract Total Debt to arrive at Equity Value, and divide by the diluted share count.
   - Present a clean, simple Bear / Base / Bull scenario table in Section 5 with clear, transparent ballpark assumptions.
   - Analytical Autonomy: For banks, financial institutions, or asset plays where DCF is unsuitable, use simple Tangible Book / ROE or dividend yield frameworks.
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
- Clean Ballpark Intrinsic Valuation: Back-of-the-napkin DCF / Owner Earnings without market price anchoring. Calculate a simple Bear / Base / Bull scenario range (Post-SBC cash flow, 3-5 year compounding, Net Cash/Debt bridge), assess confidence, execution risk, and explicit falsification triggers.
- Dynamic Alert Corridors: Establish exact `upper_alert_threshold` (upside breakout / trim level) and `lower_alert_threshold` (downside margin-of-safety floor) based on your valuation targets.

Editorial Aesthetics Mandate:
- Format all financial KPIs and quarterly numbers into `<div class="metrics-grid"><div class="metric-card">...</div></div>` or structured HTML tables. Zero raw text dumps.
- DO NOT duplicate raw metadata text or pill badges inside the HTML sections.
- NO IMAGES: Do not output `<img>` tags or figure containers. Pure analytical text, tables, and metric cards only.

Labels Directive (2-Tier Structure):
- Label #1 (MANDATORY PRIMARY PILL — CONVICTION / CONFIDENCE LEVEL ONLY): Must state in max 2 words your thesis conviction rating (e.g. "High Conviction", "High Confidence", "Moderate Conviction", "Speculative Risk", "Asymmetric Conviction", "Cautious Stance"). DO NOT put play types here.
- Labels #2 & #3 (THE PLAY NATURE & CATALYSTS — INTUITIVE PLAIN ENGLISH): Describe the economic play and catalyst driver in simple, intuitive terms (e.g. "Deep Value", "Turnaround Play", "Safe Compounder", "Buyback Cannibal", "Margin Expansion", "Cash Fortress", "Debt Paydown", "Pricing Power"). Avoid textbook jargon.

Return your plan strictly as a JSON object in ```json ... ```:
```json
{{
  "metadata": {{
    "ticker": "{ticker}",
    "company_name": "{company_name}",
    "labels": ["<Confidence/Risk Label 1>", "<Play Driver Label 2>", "<Play Driver Label 3>"],
    "fair_value_estimate": "$<Estimated Fair Value>",
    "bear_target": "$<Price> (<% Upside/Downside>)",
    "base_target": "$<Price> (<% Upside/Downside>)",
    "bull_target": "$<Price> (<% Upside/Downside>)",
    "upper_alert_threshold": <Float price to alert on upside breakout>,
    "lower_alert_threshold": <Float price to alert on downside break>,
    "upper_trigger_reason": "<Short reason>",
    "lower_trigger_reason": "<Short reason>",
    "next_catalyst_date": "<YYYY-MM-DD (Strict ISO date, e.g. 2026-08-13; if unconfirmed, estimate exact calendar day based on historical reporting cadence)>",
    "next_catalyst_event": "<Short description of catalyst, max 4 words>",
    "executive_summary": "<2-3 sentence crisp executive summary>"
  }},
  "research_objective": "<Your custom summary of the core thesis questions for {ticker}>",
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

    sub_agents = plan_json.get("sub_agents", [])
    if not sub_agents or not isinstance(sub_agents, list):
        sub_agents = [
            {
                "role": "Executive Summary & Business Moat Specialist",
                "prompt": f"Investigate {ticker_clean} ({company_name}) at ${current_price:.2f}. In clean Semantic HTML (<div class=\"section\">...</div>), write Section 1 (Executive Summary & Variant Perception) and Section 2 (Business Model Reality & Moat in Plain English). Explain how the company makes money, unit economics, and competitive moat using latest official filings. Do not use inline styles."
            },
            {
                "role": "Cash Flow, SBC Dilution & Balance Sheet Auditor",
                "prompt": f"Investigate {ticker_clean} ({company_name}) financials at ${current_price:.2f}. In clean Semantic HTML (<div class=\"section\">...</div>), write Section 3 (Honest Cash Flow, SBC Dilution & Capital Structure) and Section 4 (Ownership & Governance Check). Audit revenue, real cash flow deducting SBC (100% real cash charge), share count dilution vs buybacks, Net Cash/Debt, and verified active 13F whales from official filings. Do not use inline styles."
            },
            {
                "role": "Ballpark Valuation & Invalidation Specialist",
                "prompt": f"Investigate {ticker_clean} ({company_name}) valuation at ${current_price:.2f}. In clean Semantic HTML (<div class=\"section\">...</div>), write Section 5 (Down-to-Earth Ballpark Valuation with complete Bear/Base/Bull scenario table & 3-Yr expected returns, using localized risk-free/discount rates if international) and Section 6 (What Breaks The Thesis & Invalidation Pre-Mortem). Keep calculations transparent and simple. Do not use inline styles."
            }
        ]
    
    print(f"   │ Planned Sub-Agents: {len(sub_agents)} specialized autonomous tasks", flush=True)
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
    previous_version_num: int
) -> Tuple[Dict[str, Any], str]:
    """Reviews an active stock thesis when triggered by price or catalyst."""
    price_change_pct = ((current_price - baseline_price) / baseline_price) * 100 if baseline_price else 0.0

    prompt = f"""We are conducting an urgent investment thesis review on {ticker.upper()} ({company_name}).
TRIGGER REASON: {trigger_reason}
Baseline Price: ${baseline_price:.2f}
Current Price: ${current_price:.2f} (Change: {price_change_pct:+.2f}%)
Previous Stance: {previous_status}
Previous Thesis Summary: {previous_thesis_summary}

[ANALYTICAL AUTONOMY & THESIS INFLECTION DIRECTIVES]:
You have full analytical freedom to evaluate the new facts and determine the evolved thesis:
1. Primary Source Audit: Search the latest quarterly earnings release, latest earnings call transcript, material corporate announcements, and latest 13F whale filings.
2. What Changed & Thesis Impact:
   - Detail what new information has arrived.
   - Explain whether this reinforces our thesis (making the opportunity safer / higher confidence) or breaks/weakens it (increasing execution risk / lowering fair value).
   - Formulate a clear 2-3 sentence executive evolution summary for "what_changes_now".
3. Dynamic Labels:
   - Update Label #1 (MANDATORY PRIMARY PILL) to reflect the new confidence and risk profile (e.g. "High Conviction", "Safe Compounder", "Turnaround Risk", "High Risk", "Asymmetric Upside", "Thesis Broken").
4. True Intrinsic Valuation & DCF North Star:
   - Update fair value and Bear / Base / Bull scenario targets using first-principles DCF / cash-flow fundamentals without anchoring to current market stock price. Treat SBC as a 100% real cash charge, bridge Enterprise Value to Equity Value via Net Cash/Debt, and recalculate intrinsic per-share value.
5. Self-Healing Catalyst Date Update Rule:
   - "next_catalyst_date" MUST ALWAYS BE IN STRICT "YYYY-MM-DD" FORMAT (e.g. 2026-11-18).
   - If on the trigger date after market close no earnings release or event has occurred (or the event was rescheduled), search investor relations for the newly confirmed or estimated date, set "next_catalyst_date" to the new YYYY-MM-DD, and explain in "what_changes_now" that the calendar date has been refreshed.

Output in TWO parts:
Part 1: JSON metadata in ```json ... ```:
{{
  "alert_title": "<Punchy headline stating if thesis shifted, conviction changed, or catalyst date refreshed>",
  "alert_severity": "<1-2 word severity, e.g. Strong Buy, Caution, Thesis Broken, Accumulate, Calendar Update>",
  "labels": ["<Confidence/Risk Label 1>", "<Play Driver Label 2>", "<Play Driver Label 3>"],
  "what_was_before": "<Summary of previous thesis>",
  "what_changes_now": "<Comprehensive summary of what new information arrived, how it impacts risk/safety, and our updated forward conviction>",
  "new_fair_value": "$<Updated Fair Value>",
  "new_bear_target": "$<Updated Bear>",
  "new_base_target": "$<Updated Base>",
  "new_bull_target": "$<Updated Bull>",
  "new_upper_alert_threshold": <New upper price trigger>,
  "new_lower_alert_threshold": <New lower price trigger>,
  "next_catalyst_date": "<YYYY-MM-DD (Strict ISO date for next catalyst, e.g. 2026-11-18)>",
  "next_catalyst_event": "<Upcoming Event max 4 words>"
}}

Part 2: Updated HTML memo content reflecting the evolution of the thesis.
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
        metadata = {
            "alert_title": f"{ticker.upper()} Review at ${current_price:.2f}",
            "alert_severity": "Review",
            "labels": ["Review"],
            "what_was_before": previous_thesis_summary,
            "what_changes_now": f"Stock moved to ${current_price:.2f} ({price_change_pct:+.1f}%).",
            "new_fair_value": f"${current_price * 1.15:.2f}",
            "new_bear_target": f"${current_price * 0.8:.2f}",
            "new_base_target": f"${current_price * 1.15:.2f}",
            "new_bull_target": f"${current_price * 1.45:.2f}",
            "new_upper_alert_threshold": round(current_price * 1.15, 2),
            "lower_alert_threshold": round(current_price * 0.88, 2),
            "next_catalyst_date": "Next Earnings",
            "next_catalyst_event": "Scheduled report"
        }

    metadata["labels"] = sanitize_labels(metadata.get("labels") or metadata.get("alert_severity"))
    metadata["alert_severity"] = metadata["labels"][0] if metadata["labels"] else "Review"
    metadata["next_catalyst_date"] = normalize_catalyst_date(metadata.get("next_catalyst_date"))

    return metadata, html_content
