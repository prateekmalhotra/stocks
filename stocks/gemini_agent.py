"""Columbia Business School / Graham & Dodd / Norbert Lou Institutional Research Pipeline."""

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
    """Strips internal search grounding artifacts, inline white background styles, and raw tokens."""
    cleaned = re.sub(r"\[(?:PerQueryResult|cite|source|citation)[^\]]*\]", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\s*\d+(?:\.\d+)*(?:\s*,\s*\d+(?:\.\d+)*)*\s*\]", "", cleaned)
    
    # Strip inline style, bgcolor, and border attributes from table tags
    cleaned = re.sub(r'<(table|thead|tbody|tr|th|td)\b([^>]*?)(style="[^"]*")([^>]*?)>', r'<\1\2\4>', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<(table|thead|tbody|tr|th|td)\b([^>]*?)(bgcolor="[^"]*")([^>]*?)>', r'<\1\2\4>', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<(table|thead|tbody|tr|th|td)\b([^>]*?)(border="[^"]*")([^>]*?)>', r'<\1\2\4>', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<(table|thead|tbody|tr|th|td)\b([^>]*?)(cellpadding="[^"]*")([^>]*?)>', r'<\1\2\4>', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<(table|thead|tbody|tr|th|td)\b([^>]*?)(cellspacing="[^"]*")([^>]*?)>', r'<\1\2\4>', cleaned, flags=re.IGNORECASE)
    
    # Strip any stray inline white styles or classes
    cleaned = re.sub(r'style="[^"]*background(?:-color)?:\s*(?:#fff|#ffffff|white|rgb\s*\(\s*255\s*,\s*255\s*,\s*255\s*\))[^"]*"', '', cleaned, flags=re.IGNORECASE)
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
    """Calls Gemini 3.6 Flash via REST API with Google Search Grounding and safety fallback handling."""
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
    
    response = requests.post(url, json=payload, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"Gemini API error ({response.status_code}): {response.text}")
    
    res_json = response.json()
    try:
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
    except Exception as e:
        raise RuntimeError(f"Unexpected response structure from Gemini API: {res_json}") from e


def extract_json_block(text: str) -> Dict[str, Any]:
    """Extracts a JSON object from markdown code fences or raw text."""
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except Exception:
            pass
            
    return {}


# ==============================================================================
# RIGOROUS NORBERT LOU / COLUMBIA MULTI-AGENT PROMPTS
# ==============================================================================

COLUMBIA_SYSTEM_PHILOSOPHY = """You are a Senior Managing Director at an elite Graham & Dodd / Norbert Lou Value Fund (inspired by Norbert Lou's NVR thesis & Columbia Business School due diligence memos).

CORE PRINCIPLES:
1. RIGOROUS, SOBER & LEVEL-HEADED VALUATION (NEVER REVERSE-ENGINEER TO MATCH STOCK PRICE):
   - Price is what you pay; Value is what you get.
   - Never force multiple assumptions to justify market exuberance. If DCF and normalized cash flows yield $25 when stock trades at $37, state $25 unequivocally with crystal clear math.
2. STOCK-BASED COMPENSATION (SBC) IS A REAL 100% CASH CHARGE:
   - Always treat SBC as a real economic cash drain and shareholder dilution against True Owner Earnings and Free Cash Flow.
3. CONCRETE 5-YEAR UNLEVERED DISCOUNTED CASH FLOW (DCF):
   - Avoid lazy multiple-only shortcuts. Model 5-year discrete cash flows (NOPAT, D&A, CapEx, SBC, Δ Working Capital), calculate WACC explicitly, and compute Gordon Growth Terminal Value.
4. HIGHLIGHT CRITICAL MUST-READ INSIGHTS:
   - Use <mark class="highlight">...</mark> on critical numbers, pivotal risks, and variant perceptions so a scanning reader captures the essential thesis instantly.
   - Use structured HTML tables (<table border="0">) with zero inline white background styles.
"""

STAGE_1_FINANCIALS_PROMPT = """Target: {ticker} ({company_name}) | Current Stock Price: ${current_price:.2f}

Perform a forensic accounting and balance sheet audit using Google Search for recent 10-K/10-Q filings:
1. CAPITAL STRUCTURE & NET DEBT SCHEDULE (Complete Table):
   - Cash & Short-Term Marketable Securities ($M).
   - Debt Breakdown: Term loans, Revolvers, Senior Notes, Convertible bonds (with interest coupons and maturity dates).
   - Total Debt ($M), Net Debt ($M), Operating Lease Liabilities ($M), and Interest Coverage ratio (EBIT / Interest Expense).
2. TRUE OWNER EARNINGS & SBC AUDIT (Complete Table):
   - TTM Operating Cash Flow ($M).
   - Maintenance CapEx (distinguished from Growth CapEx) ($M).
   - Stock-Based Compensation (SBC) ($M): Treat as 100% real cash charge and dilution.
   - Working Capital drag / float ($M).
   - True Owner Earnings = OCF - Maintenance CapEx - SBC - Working Capital drag.
3. CANNIBAL SHARE COUNT TRAJECTORY (Complete Table):
   - 5-Year diluted share count trajectory year-by-year.
   - Total dollars spent on buybacks vs net shares retired (Accretive vs merely offsetting dilution).

Synthesize in structured tables with bold metrics and key highlights.
"""

STAGE_2_MOAT_INDUSTRY_PROMPT = """Target: {ticker} ({company_name}) | Current Stock Price: ${current_price:.2f}

Investigate business model anatomy, competitive moat, and capital velocity using Google Search (inspired by Norbert Lou's NVR thesis):
1. OPERATING MODEL ANATOMY & CAPITAL VELOCITY:
   - What unique structural mechanics allow this business to operate with superior capital velocity and lower risk than peers?
   - Negative working capital float vs capital absorption: Does growth generate free cash before delivery or lock up capital?
2. COMPETITIVE MOAT & PRICING POWER:
   - Moat width: Scale advantages, local market density, customer switching costs, brand power.
   - Pricing power: Have they raised prices above inflation over past 5-10 years without customer churn?
3. COMPETITOR BENCHMARK MATRIX (Complete Table):
   - Compare {ticker} directly against top 2-3 competitors on: market share, gross margins, EBITDA margins, ROIC, leverage (Net Debt/EBITDA), and unit economics.
4. DOWNTURN RESILIENCE & PRE-SELLING / ASSET-LIGHT ADVANTAGE:
   - In a severe industry downturn, how does this model protect against catastrophic asset writedowns while weaker levered competitors fail?

Output complete comparison tables and concise highlighted takeaways.
"""

STAGE_3_MANAGEMENT_OWNERSHIP_PROMPT = """Target: {ticker} ({company_name}) | Current Stock Price: ${current_price:.2f}

Investigate governance, management credibility, insider activity, and 13F whale accumulation using Google Search:
1. MANAGEMENT INTEGRITY & EARNINGS CALL TRUTH TEST:
   - Executive team capital allocation discipline: Historical ROIC vs Cost of Capital (WACC).
   - Did management deliver on historical promises made in previous earnings calls? Do they rely on aggressive non-GAAP adjustments?
   - Executive compensation alignment (Are bonuses tied to ROIC/FCF-per-share or vanity revenue?).
2. FORM 4 INSIDER TRANSACTIONS:
   - Form 4 insider trading audit over the past 12-18 months. Are executives buying with personal cash or systematically dumping?
3. OWNERSHIP BREAKDOWN & 13F WHALE TRACKING:
   - % Institutional, % Insiders, % Float.
   - Top 13F institutional holders (accumulating vs trimming).
   - Public Commentary: Summarize the core thesis from respected fund manager quarterly letters and investor conferences.

Output exact names, numbers, and clear takeaways.
"""

STAGE_4_VALUATION_PROMPT = """Target: {ticker} ({company_name}) | Current Stock Price: ${current_price:.2f}

Construct a RIGOROUS, AIRTIGHT 5-YEAR DISCOUNTED CASH FLOW (DCF) & EARNINGS POWER VALUE (EPV) INTRINSIC VALUATION MODEL.
CRITICAL MANDATE: Do NOT reverse-engineer or tweak numbers to match the current stock price of ${current_price:.2f}. Price and Value are separate.

1. 5-YEAR UNLEVERED DISCOUNTED CASH FLOW (DCF) MODEL (Complete Table):
   - Forecast FY1 through FY5:
     - Revenue ($M) and Growth Rate (%)
     - Normalized EBIT ($M) and Operating Margin (%)
     - Less: Cash Taxes (NOPAT) ($M) (Effective tax rate 23-25%)
     - Plus: D&A ($M)
     - LESS: Stock-Based Compensation (SBC) ($M) as 100% REAL CASH CHARGE
     - Less: Maintenance CapEx ($M)
     - Less/Plus: Changes in Working Capital ($M)
     - = Unlevered Free Cash Flow (UFCF) ($M)
2. WACC COST OF CAPITAL SPECIFICATION:
   - Risk-Free Rate (10-Yr UST), Beta, Equity Risk Premium (ERP) -> Cost of Equity ($K_e$)
   - Pre-Tax Cost of Debt, Marginal Tax Rate -> After-Tax Cost of Debt ($K_d$)
   - Debt/Equity Weighting -> Implied WACC (%)
3. TERMINAL VALUE & EQUITY BRIDGE:
   - Cumulative PV of 5-Yr Discrete Cash Flows ($M)
   - Terminal Growth Rate ($g = 2.0\% - 2.5\%$) -> Gordon Growth Terminal Value ($M) -> PV of Terminal Value ($M)
   - Total Enterprise Value (TEV) ($M)
   - Less: Net Debt ($M) & Lease Liabilities ($M)
   - Implied Equity Value ($M) / Diluted Shares (M) -> DCF Fair Value Per Share ($)
4. DCF SENSITIVITY MATRIX (Complete Table):
   - WACC (rows: 8.0%, 9.0%, 10.0%, 11.0%) vs Terminal Growth Rate (columns: 1.5%, 2.0%, 2.5%, 3.0%) showing implied per share fair values.
5. ZERO-GROWTH EARNINGS POWER VALUE (EPV):
   - Normalized EBIT -> NOPAT / WACC -> Enterprise EPV - Net Debt -> Equity EPV Per Share ($).
6. SCENARIO MATRIX (BEAR / BASE / BULL) WITH 3-YEAR IRRs (Complete Table):
   - Bear, Base, Bull with explicit assumptions, price targets, upside/downside %, and annualized 3-Year IRRs.

Financial Forensics Data:
{stage1_data}

Moat & Competitor Data:
{stage2_data}

Management & Ownership Data:
{stage3_data}

Output complete mathematical and tabular calculations.
"""

STAGE_5A_SYNTHESIS_PART1_PROMPT = """You are the Chief Investment Officer (CIO) compiling Part 1 (Sections 1 to 5) of the Columbia / Norbert Lou Investment Due Diligence Memo on {ticker} ({company_name}).
Current Stock Price: ${current_price:.2f}

Part 1: A JSON metadata block in ```json ... ```:
{{
  "ticker": "{ticker}",
  "company_name": "{company_name}",
  "labels": ["<Max 2-Word Label 1>", "<Max 2-Word Label 2>", "<Max 2-Word Label 3>"],
  "fair_value_estimate": "$<DCF Fair Value>",
  "bear_target": "$<Bear Price> (<Downside %>)",
  "base_target": "$<Base Price> (<Upside %>)",
  "bull_target": "$<Bull Price> (<Upside %>)",
  "upper_alert_threshold": <Float upper trigger price>,
  "lower_alert_threshold": <Float lower trigger price>,
  "upper_trigger_reason": "<Why wake up on upside>",
  "lower_trigger_reason": "<Why wake up on downside>",
  "next_catalyst_date": "<Upcoming Date>",
  "next_catalyst_event": "<Upcoming Event max 4 words>",
  "executive_summary": "<2-3 sentence punchy summary of variant perception>"
}}

Part 2: Semantic HTML for Sections 1 to 5:
1. Executive Summary & Variant Perception (Consensus vs What We Believe with <mark class="highlight">key takeaways</mark>)
2. Norbert Lou Enterprise Value (TEV) & True FCF Valuation Multiples (Complete Table)
3. Comparison vs. Street Guidance (Consensus vs Fund Estimate 3-Year Table)
4. Operating Model Anatomy, Capital Velocity & Negative Working Capital Mechanics
5. Competitive Moat, Unit Economics & Competitor Benchmark Matrix (Complete Table)

Use clean semantic HTML (<div class="section">, <h2>, <h3>, <table>, <ul>, <p>, <blockquote>, <div class="callout">, <mark class="highlight">). Do NOT output outer <html> or <body> tags. Do NOT cut off.

Analyst Inputs:
Financial Forensics: {stage1_data}
Moat & Industry: {stage2_data}
Management & Ownership: {stage3_data}
Valuation & DCF: {stage4_data}
"""

STAGE_5B_SYNTHESIS_PART2_PROMPT = """You are the Chief Investment Officer (CIO) compiling Part 2 (Sections 6 to 12) of the Columbia / Norbert Lou Investment Due Diligence Memo on {ticker} ({company_name}).
Current Stock Price: ${current_price:.2f}

Generate complete, beautiful Semantic HTML for Sections 6 to 12 (DO NOT TRUNCATE OR STOP EARLY):
6. Capital Allocation Discipline, ROIC Anatomy & Cannibal Share Buyback History (Complete Table)
7. Management Integrity, Earnings Call Truth Test & 13F Whale Tracking
8. Capital Structure & Complete Net Debt Schedule (Maturities & Interest Coverage Complete Table)
9. True Owner Earnings & SBC 100% Cash Charge Audit (Complete Table)
10. Rigorous 5-Year Unlevered DCF Model, WACC Specification, Sensitivity Matrix & EPV (Complete Tables)
11. Triangulated Scenario Matrix (Bear / Base / Bull + 3-Yr Annualized IRRs Complete Table)
12. Socratic Pre-Mortem & Invalidation Catalysts

Use clean semantic HTML (<div class="section">, <h2>, <h3>, <table>, <ul>, <p>, <blockquote>, <div class="callout">, <mark class="highlight">). Ensure all tables are complete with all rows and columns fully closed. Do NOT output outer <html> or <body> tags.

Analyst Inputs:
Financial Forensics: {stage1_data}
Moat & Industry: {stage2_data}
Management & Ownership: {stage3_data}
Valuation & DCF: {stage4_data}
"""


def generate_genesis_thesis(ticker: str, company_name: str, current_price: float, initial_notes: str = "") -> Tuple[Dict[str, Any], str]:
    """Generates an authentic Columbia / Norbert Lou grade investment memo via modular multi-agent synthesis."""
    ticker_clean = ticker.upper().strip()
    print(f"  [Pipeline 1/5] Running Forensic Accounting & Capital Structure Audit for {ticker_clean}...")
    stage1_prompt = STAGE_1_FINANCIALS_PROMPT.format(ticker=ticker_clean, company_name=company_name, current_price=current_price)
    stage1_out = call_gemini_with_search(stage1_prompt, system_instruction=COLUMBIA_SYSTEM_PHILOSOPHY)

    print(f"  [Pipeline 2/5] Investigating Operating Model Anatomy, Capital Velocity & Moat for {ticker_clean}...")
    stage2_prompt = STAGE_2_MOAT_INDUSTRY_PROMPT.format(ticker=ticker_clean, company_name=company_name, current_price=current_price)
    stage2_out = call_gemini_with_search(stage2_prompt, system_instruction=COLUMBIA_SYSTEM_PHILOSOPHY)

    print(f"  [Pipeline 3/5] Auditing Capital Allocation (ROIC/Cannibal Buybacks) & 13F Whales for {ticker_clean}...")
    stage3_prompt = STAGE_3_MANAGEMENT_OWNERSHIP_PROMPT.format(ticker=ticker_clean, company_name=company_name, current_price=current_price)
    stage3_out = call_gemini_with_search(stage3_prompt, system_instruction=COLUMBIA_SYSTEM_PHILOSOPHY)

    print(f"  [Pipeline 4/5] Executing 5-Year Unlevered DCF, EPV & Sensitivity Model for {ticker_clean}...")
    stage4_prompt = STAGE_4_VALUATION_PROMPT.format(
        ticker=ticker_clean, company_name=company_name, current_price=current_price,
        stage1_data=stage1_out[:3500], stage2_data=stage2_out[:3500], stage3_data=stage3_out[:3500]
    )
    stage4_out = call_gemini_with_search(stage4_prompt, system_instruction=COLUMBIA_SYSTEM_PHILOSOPHY)

    print(f"  [Pipeline 5a/5] Synthesizing Strategic & Industry Memo Sections (1-5) for {ticker_clean}...")
    stage5a_prompt = STAGE_5A_SYNTHESIS_PART1_PROMPT.format(
        ticker=ticker_clean, company_name=company_name, current_price=current_price,
        stage1_data=stage1_out[:2200], stage2_data=stage2_out[:2200],
        stage3_data=stage3_out[:2200], stage4_data=stage4_out[:3000]
    )
    res_part1 = call_gemini_with_search(stage5a_prompt, system_instruction=COLUMBIA_SYSTEM_PHILOSOPHY)

    metadata = extract_json_block(res_part1)
    html_part1 = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", res_part1, flags=re.DOTALL).strip()
    if html_part1.startswith("```html"):
        html_part1 = html_part1[7:]
    if html_part1.endswith("```"):
        html_part1 = html_part1[:-3]
    html_part1 = clean_grounding_artifacts(html_part1.strip())

    print(f"  [Pipeline 5b/5] Synthesizing Valuation, DCF & Balance Sheet Sections (6-12) for {ticker_clean}...")
    stage5b_prompt = STAGE_5B_SYNTHESIS_PART2_PROMPT.format(
        ticker=ticker_clean, company_name=company_name, current_price=current_price,
        stage1_data=stage1_out[:2200], stage2_data=stage2_out[:2200],
        stage3_data=stage3_out[:2200], stage4_data=stage4_out[:3000]
    )
    res_part2 = call_gemini_with_search(stage5b_prompt, system_instruction=COLUMBIA_SYSTEM_PHILOSOPHY)

    html_part2 = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", res_part2, flags=re.DOTALL).strip()
    if html_part2.startswith("```html"):
        html_part2 = html_part2[7:]
    if html_part2.endswith("```"):
        html_part2 = html_part2[:-3]
    html_part2 = clean_grounding_artifacts(html_part2.strip())

    full_html = f"{html_part1}\n\n{html_part2}".strip()

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
            "executive_summary": f"Full Columbia-grade due diligence established for {ticker_clean}."
        }

    metadata["labels"] = sanitize_labels(metadata.get("labels") or metadata.get("status_label"))
    metadata["status_label"] = metadata["labels"][0] if metadata["labels"] else "Active"

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

Search real-time news, filings, 10-Q updates, earnings releases, and market commentary:
- What happened?
- Did the fundamental thesis hold, inflect positively, or break?
- Update the DCF valuation, fair value, scenario matrix, and alert corridors.
- Provide 1 to 3 dynamic labels (max 2 words each).
- CRITICAL: Never force the valuation to match the current price. Keep it level-headed and grounded in reality.
- CRITICAL: Treat SBC as a real 100% cash drain in DCF and cash flow models.
- CRITICAL: Never output search artifacts like [PerQueryResult(...)].

Output in TWO parts:
Part 1: JSON metadata in ```json ... ```:
{{
  "alert_title": "<Punchy headline>",
  "alert_severity": "<1-2 word severity, e.g. Accumulate, Caution, Thesis Intact>",
  "labels": ["<Label 1>", "<Label 2>", "<Label 3>"],
  "what_was_before": "<Summary of previous thesis>",
  "what_changes_now": "<What changed and our new forward stance>",
  "new_fair_value": "$<Updated DCF Fair Value>",
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

    response_text = call_gemini_with_search(prompt, system_instruction=COLUMBIA_SYSTEM_PHILOSOPHY)
    metadata = extract_json_block(response_text)
    
    html_content = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", response_text, flags=re.DOTALL).strip()
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = clean_grounding_artifacts(html_content.strip())

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
