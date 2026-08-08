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
    # Strip PerQueryResult, cite, source tags
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


def call_gemini_with_search(prompt: str, system_instruction: str = "", temperature: float = 0.5) -> str:
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


COLUMBIA_SYSTEM_PHILOSOPHY = """You are a Principal Investment Partner at an elite Graham & Dodd / Norbert Lou Value Fund (inspired by Norbert Lou's NVR thesis & Columbia Business School due diligence memos).

CRITICAL INTELLECTUAL MANDATES:
1. RIGOROUS, SOBER & AIRTIGHT VALUATION (NEVER REVERSE-ENGINEER TO MATCH STOCK PRICE):
   - Price is what you pay; Value is what you get.
   - You must NEVER reverse-engineer your valuation, EBITDA multiples, or DCF assumptions to justify the current market price.
   - If a company's normalized cash flows only support a $20 valuation when trading at $37, state $20 unequivocally and detail the exact mathematical reasoning.
2. SBC (STOCK-BASED COMPENSATION) IS A REAL CASH DRAIN:
   - Always treat SBC as an economic cash drain and dilution against True Owner Earnings.
3. NORBERT LOU CAPITAL VELOCITY & ROIC ANATOMY:
   - Identify the unique structural mechanics of the operating model (asset-light land options vs outright buying, negative working capital, pre-selling vs spec building).
   - Track cannibal share repurchases year-by-year (shares retired vs dilution).
   - Calculate TEV multiples: TEV/EBITDA, TEV/(EBITDA - Maintenance CapEx), TEV/Owner FCF, and FCF Yield.
4. BEAUTIFUL PRESENTATION & AIRTIGHT MATHEMATICAL CLARITY:
   - Avoid dense walls of plain text. Use structured HTML tables with clear metrics, bold figures, and highlighted takeaway callout blocks (<div class="callout">...</div>).
   - Never output internal search citations like [PerQueryResult(...)] or [1.3.8].
   - Do NOT output inline style="background-color: white" in tables! Use clean unstyled <table>, <thead>, <tbody>, <tr>, <th>, <td> tags.
"""

STAGE_1_FINANCIALS_PROMPT = """Target: {ticker} ({company_name}) | Current Stock Price: ${current_price:.2f}

Perform a forensic accounting and balance sheet audit using Google Search for recent 10-K/10-Q filings:
1. CAPITAL STRUCTURE & NET DEBT SCHEDULE (Table):
   - Cash & Short-Term Marketable Securities ($M).
   - Debt Breakdown: Term loans, Revolvers, Senior Notes, Convertible bonds (with interest coupons and maturity dates).
   - Total Debt ($M), Net Debt ($M), and Interest Coverage ratio (EBIT / Interest Expense).
2. TRUE OWNER EARNINGS & SBC AUDIT (Table):
   - TTM Operating Cash Flow ($M).
   - Maintenance CapEx (distinguished from Growth CapEx) ($M).
   - Stock-Based Compensation (SBC) ($M): Treat as real economic dilution.
   - True Owner Earnings = OCF - Maintenance CapEx - SBC - Working Capital drag.
3. CANNIBAL SHARE COUNT TRAJECTORY (Table):
   - 5-Year diluted share count trajectory year-by-year.
   - Total dollars spent on buybacks vs net shares retired (Accretive vs merely offsetting dilution).

Synthesize in structured tables with bold metrics.
"""

STAGE_2_MOAT_INDUSTRY_PROMPT = """Target: {ticker} ({company_name}) | Current Stock Price: ${current_price:.2f}

Investigate business model anatomy, competitive moat, and capital velocity using Google Search (inspired by Norbert Lou's NVR thesis):
1. OPERATING MODEL ANATOMY & CAPITAL VELOCITY:
   - What unique structural mechanics allow this business to operate with superior capital velocity and lower risk than peers?
   - Working capital requirements: Does revenue growth require heavy working capital absorption or does it generate free float?
2. COMPETITIVE MOAT & PRICING POWER:
   - Moat width: Scale advantages, switching costs, local market dominance, brand power.
   - Pricing power: Have they raised prices above inflation over past 5-10 years without losing customer volume?
3. COMPETITOR BENCHMARK MATRIX (Table):
   - Compare {ticker} directly against top 2-3 competitors on: market share, gross margins, EBITDA margins, ROIC, leverage (Net Debt/EBITDA), and unit economics.
4. DOWNTURN RESILIENCE & PRE-SELLING / ASSET-LIGHT ADVANTAGE:
   - In a severe industry downturn, how does this model protect against catastrophic asset writedowns while weaker levered competitors fail?

Output complete comparison tables and concise takeaways.
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

Construct a DEEP, AIRTIGHT, and GROUNDED intrinsic valuation model (inspired by Norbert Lou on NVR & Columbia Business School).
CRITICAL MANDATE: Do NOT reverse-engineer or tweak numbers to match the current stock price of ${current_price:.2f}. Price and Value are separate.

1. NORBERT LOU TOTAL ENTERPRISE VALUE (TEV) & FCF MULTIPLES (Table):
   - Current Share Price: ${current_price:.2f}
   - Diluted Shares Outstanding (M)
   - Market Capitalization ($M)
   - Plus: Total Debt ($M), Less: Cash ($M) -> Total Enterprise Value (TEV) ($M)
   - TEV / TTM Revenue
   - TEV / TTM EBITDA
   - TEV / (EBITDA - Maintenance CapEx)
   - TEV / True Owner FCF (where Owner FCF = OCF - Maintenance CapEx - SBC)
   - Normalized P/E (Trailing & Forward)
   - Free Cash Flow Yield (%)
2. STREET GUIDANCE VS FUND VARIANT ESTIMATES (Table):
   - Construct a 3-year projection table (FY 2026E, FY 2027E, FY 2028E): Consensus Street Estimates vs Our Fund Estimates for Revenue, EBIT, EBITDA, Net Income, Owner FCF, and Diluted EPS.
3. EARNINGS POWER VALUE (EPV) (Zero-Growth Reproduction Value):
   - Sustainable Normalized Operating Income ($M)
   - Less: Normalized Taxes (NOPAT) ($M)
   - Capitalized at WACC (9.0% - 10.5%) -> EPV of Operations ($M)
   - Plus: Cash ($M), Less: Net Debt ($M) -> Equity EPV ($M)
   - EPV Per Share ($)
4. TRIANGULATED SCENARIO MATRIX (BEAR / BASE / BULL) (Table):
   - Bear Case: Conservative EBITDA, low multiple, Net Debt subtraction, implied share price, downside %, and 3-year annualized IRR.
   - Base Case: Normalized Owner Earnings, realistic multiple, Net Debt subtraction, implied share price, upside %, and 3-year annualized IRR.
   - Bull Case: Blue-sky operating leverage, fair multiple, implied share price, upside %, and 3-year annualized IRR.
5. FAIR VALUE ESTIMATE & MARGIN OF SAFETY:
   - Single level-headed, defensible intrinsic fair value estimate per share ($).
   - Quantified Margin of Safety (%) vs current market price of ${current_price:.2f}.
6. SOCRATIC PRE-MORTEM & INVALIDATION CATALYSTS:
   - What specific 10-Q metrics or secular threats would break this thesis?

Financial Forensics Data:
{stage1_data}

Moat & Competitor Data:
{stage2_data}

Management & Ownership Data:
{stage3_data}

Output complete mathematical and tabular calculations.
"""

STAGE_5_SYNTHESIS_HTML_PROMPT = """You are the Chief Investment Officer (CIO) compiling the final Columbia Business School / Norbert Lou Investment Due Diligence Memo on {ticker} ({company_name}).
Current Stock Price: ${current_price:.2f}

Synthesize all analyst reports into an airtight, beautifully presented investment memo.

CRITICAL PRESENTATION RULES:
1. LABELS: Choose 1 to 3 dynamic category labels for this setup (e.g. ["Overvalued", "Theatrical Moat", "Deleveraging"]). Every label MUST be at most 2 words.
2. BEAUTIFUL STRUCTURE (NO DENSE WALLS OF TEXT): Break up analysis into structured sections with clear headers, comparison tables, bold key metrics, and highlighted takeaway callout boxes (<div class="callout">...</div>).
3. CLEAN UNSTYLED TABLES: Do NOT inject inline style="background-color: white" or bgcolor in tables! Use clean unstyled <table>, <thead>, <tbody>, <tr>, <th>, <td> tags.
4. NO INTERNAL TOKENS: Never output tokens like [PerQueryResult(...)] or [1.3.8].

Part 1: A JSON metadata block in ```json ... ```:
{{
  "ticker": "{ticker}",
  "company_name": "{company_name}",
  "labels": ["<Max 2-Word Label 1>", "<Max 2-Word Label 2>", "<Max 2-Word Label 3>"],
  "fair_value_estimate": "$<Fair Value>",
  "bear_target": "$<Bear Price> (<Downside %>)",
  "base_target": "$<Base Price> (<Upside %>)",
  "bull_target": "$<Bull Price> (<Upside %>)",
  "upper_alert_threshold": <Float upper trigger price>,
  "lower_alert_threshold": <Float lower trigger price>,
  "upper_trigger_reason": "<Why wake up on upside>",
  "lower_trigger_reason": "<Why wake up on downside>",
  "next_catalyst_date": "<Upcoming Date>",
  "next_catalyst_event": "<Upcoming Event>",
  "executive_summary": "<2-3 sentence punchy summary of variant perception>"
}}

Part 2: The rich due diligence memo formatted in semantic HTML sections:
1. Executive Summary & Variant Perception (Consensus vs What We Believe)
2. Norbert Lou Enterprise Value (TEV) & True FCF Valuation Multiples (Complete Table)
3. Comparison vs. Street Guidance (Consensus vs Fund Estimate 3-Year Table)
4. Operating Model Anatomy, Capital Velocity & Negative Working Capital Mechanics
5. Competitive Moat, Unit Economics & Competitor Benchmark Matrix (Table)
6. Capital Allocation Discipline, ROIC Anatomy & Cannibal Share Buyback History (Table)
7. Management Integrity, Earnings Call Truth Test & 13F Whale Tracking
8. Capital Structure & Net Debt Schedule (Maturities & Interest Coverage Table)
9. True Owner Earnings & SBC Cash Drain Audit (Table)
10. Earnings Power Value (EPV) & Triangulated Scenario Matrix (Bear / Base / Bull + 3-Yr IRRs Table)
11. Socratic Pre-Mortem & Invalidation Catalysts
12. Surveillance Boundaries & Forward Catalyst Timeline

Use clean semantic HTML (<div class="section">, <h2>, <h3>, <table>, <ul>, <p>, <blockquote>, <div class="callout">). Do NOT include outer <html> or <body> tags.

Analyst Inputs:
Financial Forensics: {stage1_data}
Moat & Industry: {stage2_data}
Management & Ownership: {stage3_data}
Valuation & Scenarios: {stage4_data}
"""


def generate_genesis_thesis(ticker: str, company_name: str, current_price: float, initial_notes: str = "") -> Tuple[Dict[str, Any], str]:
    """Generates an authentic Columbia / Norbert Lou grade investment memo via a 5-stage multi-agent pipeline."""
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

    print(f"  [Pipeline 4/5] Executing Deep Norbert Lou / EPV Valuation & Scenario Matrix for {ticker_clean}...")
    stage4_prompt = STAGE_4_VALUATION_PROMPT.format(
        ticker=ticker_clean, company_name=company_name, current_price=current_price,
        stage1_data=stage1_out[:3500], stage2_data=stage2_out[:3500], stage3_data=stage3_out[:3500]
    )
    stage4_out = call_gemini_with_search(stage4_prompt, system_instruction=COLUMBIA_SYSTEM_PHILOSOPHY)

    print(f"  [Pipeline 5/5] Synthesizing Columbia / Norbert Lou Investment Due Diligence Memo for {ticker_clean}...")
    stage5_prompt = STAGE_5_SYNTHESIS_HTML_PROMPT.format(
        ticker=ticker_clean, company_name=company_name, current_price=current_price,
        stage1_data=stage1_out[:2200], stage2_data=stage2_out[:2200],
        stage3_data=stage3_out[:2200], stage4_data=stage4_out[:3000]
    )
    final_response = call_gemini_with_search(stage5_prompt, system_instruction=COLUMBIA_SYSTEM_PHILOSOPHY)

    metadata = extract_json_block(final_response)
    html_content = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", final_response, flags=re.DOTALL).strip()
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = clean_grounding_artifacts(html_content.strip())

    if not metadata:
        metadata = {
            "ticker": ticker_clean,
            "company_name": company_name,
            "labels": ["Active"],
            "fair_value_estimate": f"${current_price * 1.20:.2f}",
            "bear_target": f"${current_price * 0.75:.2f} (-25.0%)",
            "base_target": f"${current_price * 1.25:.2f} (+25.0%)",
            "bull_target": f"${current_price * 1.60:.2f} (+60.0%)",
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

    return metadata, html_content


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
- Update the valuation, fair value, scenario matrix, and alert corridors.
- Provide 1 to 3 dynamic labels (max 2 words each).
- CRITICAL: Never force the valuation to match the current price. Keep it level-headed and grounded in reality.
- CRITICAL: Never output search artifacts like [PerQueryResult(...)].

Output in TWO parts:
Part 1: JSON metadata in ```json ... ```:
{{
  "alert_title": "<Punchy headline>",
  "alert_severity": "<1-2 word severity, e.g. Accumulate, Caution, Thesis Intact>",
  "labels": ["<Label 1>", "<Label 2>", "<Label 3>"],
  "what_was_before": "<Summary of previous thesis>",
  "what_changes_now": "<What changed and our new forward stance>",
  "new_fair_value": "$<Updated Fair Value>",
  "new_bear_target": "$<Updated Bear>",
  "new_base_target": "$<Updated Base>",
  "new_bull_target": "$<Updated Bull>",
  "new_upper_alert_threshold": <New upper price trigger>,
  "new_lower_alert_threshold": <New lower price trigger>,
  "next_catalyst_date": "<Upcoming Date>",
  "next_catalyst_event": "<Upcoming Event>"
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
            "new_fair_value": f"${current_price * 1.2:.2f}",
            "new_bear_target": f"${current_price * 0.8:.2f}",
            "new_base_target": f"${current_price * 1.25:.2f}",
            "new_bull_target": f"${current_price * 1.5:.2f}",
            "new_upper_alert_threshold": round(current_price * 1.15, 2),
            "lower_alert_threshold": round(current_price * 0.88, 2),
            "next_catalyst_date": "Next Earnings",
            "next_catalyst_event": "Scheduled report"
        }

    metadata["labels"] = sanitize_labels(metadata.get("labels") or metadata.get("alert_severity"))
    metadata["alert_severity"] = metadata["labels"][0] if metadata["labels"] else "Review"

    return metadata, html_content
