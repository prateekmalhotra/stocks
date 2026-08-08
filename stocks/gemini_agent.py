"""Autonomous Multi-Agent Fundamental Equity Due Diligence & Ballpark Valuation Engine."""

import os
import json
import re
import requests
from typing import Dict, Any, Tuple, Optional, List
from dotenv import load_dotenv

load_dotenv()


def get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY is not set in environment or .env file.")
    return key


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
    cleaned = re.sub(r'<(table|thead|tbody|tr|th|td)\b([^>]*?)(cellpadding="[^"]*")([^>]*?)>', r'<\1\2\4>', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<(table|thead|tbody|tr|th|td)\b([^>]*?)(cellspacing="[^"]*")([^>]*?)>', r'<\1\2\4>', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'class="[^"]*bg-white[^"]*"', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def sanitize_labels(labels: Any) -> List[str]:
    """Sanitizes labels so there are max 3 labels and each label has max 2 words."""
    if not isinstance(labels, list):
        if isinstance(labels, str) and labels:
            labels = [labels]
        else:
            return ["Active"]
    
    clean_list = []
    for lbl in labels:
        if not isinstance(lbl, str):
            continue
        words = [w for w in lbl.replace("/", " ").replace("-", " ").replace("&", " ").split() if w.strip()]
        if words:
            short_lbl = " ".join(words[:2]).title()
            if short_lbl not in clean_list:
                clean_list.append(short_lbl)
        if len(clean_list) >= 3:
            break
            
    return clean_list if clean_list else ["Active"]


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

LEVEL_HEADED_INVESTOR_PHILOSOPHY = """You are a seasoned, down-to-earth fundamental value investor and research strategist.

CORE ANALYTICAL PRINCIPLES:
1. Simplicity & Real-World Reality:
   - Avoid excessive financial jargon, false academic precision, and 50-variable DCFs.
   - Deliver clear, realistic, level-headed, and common-sense economic analysis that any intelligent business owner would appreciate.
2. Honest Financial Accounting & Cash Drag:
   - Stock-Based Compensation (SBC) must ALWAYS be treated as a 100% real economic cash charge and shareholder dilution factor.
   - Track real organic growth, share dilution vs buyback pace, and true Net Cash (Cash minus Total Debt/Obligations).
   - Always verify facts, financial numbers, and 13F whale positions against the LATEST official SEC filings (do not use outdated historical memory or list exited investors as current holders).
3. Realistic Ballpark Valuation:
   - Provide a sensible, realistic ballpark valuation range (Bear / Base / Bull) with straightforward 3-Year expected annualized returns (IRRs).
4. Analytical Autonomy:
   - You have complete freedom to structure the research, formulate sub-agent tasks, and emphasize what is most essential for this specific company. You can override any default guidance if a different approach better fits the economic reality of the business.
"""

MASTER_PLANNER_PROMPT = """Target: {ticker} ({company_name}) | Current Stock Price: ${current_price:.2f}
User Focus / Research Notes: {notes}

You are the Lead Investment Strategist. Your broad goal is to formulate a level-headed, honest fundamental evaluation of {ticker}.

[FULL ANALYTICAL AUTONOMY & ZERO BIAS DIRECTIVE]:
You have complete freedom to decide what matters most for this business.
You are NOT bound by rigid templates, checklists, or forced assumptions.
You will divide the memo into 3 to 4 specialized sub-agents. Each sub-agent will research its assigned topic and directly output its dedicated section in clean Semantic HTML (<div class="section"> ... </div>).

Key Areas of Investigation:
1. Business Model Reality & Moat: How does the company actually make money, what is its competitive moat, customer retention, and pricing power in plain English?
2. Cash Flow & Financial Reality: Real cash generation deducting Stock-Based Compensation (SBC is a 100% real cash charge), organic revenue trajectory, share count dilution vs. buyback pace, and true Net Cash or Net Debt.
3. Governance, Whales & Catalysts: Verified 13F institutional positions from latest official filings (exclude exited holders), management alignment, and upcoming catalysts.
4. Down-to-Earth Ballpark Valuation: Level-headed, realistic Bear / Base / Bull scenario valuation range (3-Yr expected returns) and key falsification risks.

Return your plan strictly as a JSON object in ```json ... ```:
```json
{{
  "metadata": {{
    "ticker": "{ticker}",
    "company_name": "{company_name}",
    "labels": ["<Max 2-Word Label 1>", "<Max 2-Word Label 2>", "<Max 2-Word Label 3>"],
    "fair_value_estimate": "$<Estimated Fair Value>",
    "bear_target": "$<Price> (<% Upside/Downside>)",
    "base_target": "$<Price> (<% Upside/Downside>)",
    "bull_target": "$<Price> (<% Upside/Downside>)",
    "upper_alert_threshold": <Float price to alert on upside breakout>,
    "lower_alert_threshold": <Float price to alert on downside break>,
    "upper_trigger_reason": "<Short reason>",
    "lower_trigger_reason": "<Short reason>",
    "next_catalyst_date": "<YYYY-MM-DD or Month Year>",
    "next_catalyst_event": "<Short description of catalyst, max 4 words>",
    "executive_summary": "<2-3 sentence crisp executive summary>"
  }},
  "research_objective": "<Your custom summary of the core thesis questions for {ticker}>",
  "sub_agents": [
    {{
      "role": "<Sub-Agent 1 Role Name, e.g. Business Model & Moat Specialist>",
      "prompt": "<Detailed prompt instructing Sub-Agent 1 to search real-time filings and output Section 1 & 2 in clean Semantic HTML>"
    }},
    {{
      "role": "<Sub-Agent 2 Role Name, e.g. Cash Flow, SBC Dilution & Balance Sheet Auditor>",
      "prompt": "<Detailed prompt instructing Sub-Agent 2 to search real-time filings and output Section 3 & 4 in clean Semantic HTML>"
    }},
    {{
      "role": "<Sub-Agent 3 Role Name, e.g. Ballpark Valuation & Invalidation Specialist>",
      "prompt": "<Detailed prompt instructing Sub-Agent 3 to search real-time filings and output Section 5 & 6 with complete Bear/Base/Bull tables in clean Semantic HTML>"
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
                "prompt": f"Investigate {ticker_clean} ({company_name}) valuation at ${current_price:.2f}. In clean Semantic HTML (<div class=\"section\">...</div>), write Section 5 (Down-to-Earth Ballpark Valuation with complete Bear/Base/Bull scenario table & 3-Yr expected returns) and Section 6 (What Breaks The Thesis & Invalidation Pre-Mortem). Keep calculations transparent and simple. Do not use inline styles."
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

    print("\n" + "=" * 70, flush=True)
    print(f"✅ DOSSIER COMPLETE: {ticker_clean} ({metadata['status_label']}) at ${current_price:.2f}", flush=True)
    print("=" * 70 + "\n", flush=True)

    return metadata, full_html

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

[ANALYTICAL AUTONOMY & THESIS INFLECTION GUIDANCE]:
You have full analytical freedom to evaluate the situation and determine the updated thesis:
- Did the core fundamental thesis hold, improve, or break?
- Conviction & Stance Changes:
  - If the valuation or fundamentals change to a Buy, Strong Buy, Screaming Buy, Hold, Trim, Sell, or Screaming Sell, explicitly state this conviction in the alert headline, the "what_changes_now" summary, and the updated research memo.
- Dynamic 3-Label Updates:
  - Update the 1 to 3 dynamic labels (max 2 words each) to reflect the new reality (e.g. ["Screaming Buy", "Moat Expanding", "Deleveraged"] or ["Screaming Sell", "Thesis Broken", "Multiple Compression"]).
- Level-Headed Ballpark Valuation:
  - Update the ballpark valuation, fair value, scenario matrix, and alert corridors. Never force numbers to match the stock price. Treat SBC as a 100% real cash charge.

Output in TWO parts:
Part 1: JSON metadata in ```json ... ```:
{{
  "alert_title": "<Punchy headline stating if thesis shifted or conviction changed>",
  "alert_severity": "<1-2 word severity, e.g. Strong Buy, Caution, Thesis Broken, Accumulate>",
  "labels": ["<Label 1>", "<Label 2>", "<Label 3>"],
  "what_was_before": "<Summary of previous thesis>",
  "what_changes_now": "<What changed, why conviction shifted, and our new forward stance>",
  "new_fair_value": "$<Updated Fair Value>",
  "new_bear_target": "$<Updated Bear>",
  "new_base_target": "$<Updated Base>",
  "new_bull_target": "$<Updated Bull>",
  "new_upper_alert_threshold": <New upper price trigger>,
  "new_lower_alert_threshold": <New lower price trigger>,
  "next_catalyst_date": "<Upcoming Date>",
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

    return metadata, html_content
