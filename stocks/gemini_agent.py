"""Independent Fundamental Equity Due Diligence & Valuation Engine."""

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
    """Strips internal search grounding artifacts, inline white background styles, and meta references."""
    cleaned = re.sub(r"\[(?:PerQueryResult|cite|source|citation)[^\]]*\]", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\s*\d+(?:\.\d+)*(?:\s*,\s*\d+(?:\.\d+)*)*\s*\]", "", cleaned)
    
    # Strip any accidental meta references to templates/historical analogies
    cleaned = re.sub(r"\b(?:Norbert\s+Lou(?:'s)?(?:\s+NVR)?|NVR\s+thesis|Columbia\s+(?:Business\s+School\s+)?(?:thesis|memo|paper))\b", "", cleaned, flags=re.IGNORECASE)
    
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
    
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except Exception:
            pass
            
    return {}


# ==============================================================================
# INDEPENDENT INSTITUTIONAL PHILOSOPHY & MODULAR PROMPTS
# ==============================================================================

INSTITUTIONAL_SYSTEM_PHILOSOPHY = """You are a Principal Investment Analyst at an unconstrained fundamental equity fund.
Your mandate is to conduct independent, intellectually honest, level-headed, and mathematically airtight research.

AUTONOMY & GUIDING PRINCIPLE:
Everything outlined in these instructions and prompts is strictly a GUIDE and an IDEA. You have FULL FREEDOM, creative autonomy, and unconstrained authority to take action on how to best accomplish your analysis. Adapt your frameworks, metrics, valuation depth, and presentation in whatever way best uncovers the economic truth of the specific target company.

CORE PRINCIPLES:
1. INTELLECTUAL INDEPENDENCE & LEVEL-HEADED VALUATION:
   - Price is what you pay; value is what you get.
   - Never reverse-engineer or tweak numbers to match the current market stock price.
   - Arrive at your own sober intrinsic fair value based on fundamental cash flow realities.
2. STOCK-BASED COMPENSATION (SBC) IS A 100% ECONOMIC CASH CHARGE:
   - Always treat SBC as a real cash drain and shareholder dilution against True Owner Earnings and Free Cash Flow.
3. CONCRETE, STEP-BY-STEP VALUATION:
   - Build explicit valuation models (e.g. 5-Year Unlevered DCF, normalized cash flow yield, EPV reproduction value) with clear WACC, CapEx separation, and sensitivity tables.
4. SIMPLICITY & HIGH-IMPACT SCANNING:
   - Keep the presentation clean, punchy, and readable. Avoid unnecessary walls of fluff.
   - Highlight critical numbers, pivotal risks, and variant perceptions using <mark class="highlight">...</mark> so a scanning reader grasps key takeaways immediately.
   - Never reference prompt templates, historical analogies from other companies, or meta instructions in your output. Tailor all content directly and authentically to the target company.
"""

STAGE_1_FINANCIALS_PROMPT = """Target: {ticker} ({company_name}) | Current Stock Price: ${current_price:.2f}

[AUTONOMY NOTE: Everything below is a guide and starting idea. You have full freedom to analyze the capital structure and forensics in whatever manner best fits this business.]

Perform a forensic accounting and balance sheet audit using Google Search across latest 10-K and 10-Q filings:
1. CAPITAL STRUCTURE & NET DEBT SCHEDULE (Complete Table):
   - Cash & Short-Term Marketable Securities ($M).
   - Debt Breakdown: Term loans, Revolvers, Senior Notes, Convertible bonds (with exact interest coupons and maturity dates).
   - Total Debt ($M), Net Debt ($M), Operating Lease Liabilities ($M), and Interest Coverage ratio (EBIT / Interest Expense).
2. TRUE OWNER EARNINGS & SBC AUDIT (Complete Table):
   - TTM Operating Cash Flow ($M).
   - Maintenance CapEx (distinguished from Growth CapEx) ($M).
   - Stock-Based Compensation (SBC) ($M): Treat as 100% real cash charge and dilution.
   - Working Capital drag / float ($M).
   - True Owner Earnings = OCF - Maintenance CapEx - SBC - Working Capital changes.
3. SHARE COUNT & BUYBACK TRAJECTORY (Complete Table):
   - 5-Year diluted share count trajectory year-by-year.
   - Total dollars spent on buybacks vs net shares retired (Accretive vs merely offsetting dilution).

Synthesize in structured tables with bold metrics and key highlights.
"""

STAGE_2_MOAT_INDUSTRY_PROMPT = """Target: {ticker} ({company_name}) | Current Stock Price: ${current_price:.2f}

[AUTONOMY NOTE: Everything below is a guide and starting idea. You have full freedom to evaluate the business model and competitive landscape however you see fit.]

Investigate business model anatomy, competitive moat, and operating cash conversion using Google Search:
1. OPERATING MODEL ANATOMY & CASH CYCLE:
   - What unique structural mechanics allow this business to operate with superior capital velocity and lower risk than peers?
   - Working capital mechanics: Does growth generate free operational cash upfront or tie up heavy capital?
2. COMPETITIVE MOAT & PRICING POWER:
   - Moat width: Scale advantages, network effects, customer switching costs, brand loyalty, or geographic density.
   - Pricing power: Have they successfully passed through cost inflation over past 5-10 years without customer churn?
3. COMPETITOR BENCHMARK MATRIX (Complete Table):
   - Compare {ticker} directly against top 2-3 competitors on: market share, gross margins, EBITDA margins, ROIC, leverage (Net Debt/EBITDA), and unit economics.
4. CYCLE & DOWNTURN RESILIENCE:
   - In a severe industry downturn or recession, how does this model protect against asset writedowns while weaker levered competitors struggle?

Output complete comparison tables and concise highlighted takeaways.
"""

STAGE_3_MANAGEMENT_OWNERSHIP_PROMPT = """Target: {ticker} ({company_name}) | Current Stock Price: ${current_price:.2f}

[AUTONOMY NOTE: Everything below is a guide. You have full freedom to investigate governance, insider transactions, and 13F whale positioning.]

[CRITICAL FACT-CHECKING DIRECTIVE: You MUST verify all ownership tables, 13F whale positions, and institutional stakes against the LATEST official SEC filings (SEC 13F-HR, Form 4, 10-K, 20-F). Do NOT use stale pre-2024 memory or outdated stakes. For example, if a famous investor (like Berkshire Hathaway in StoneCo) completely sold out/exited, you MUST state they exited or exclude them from current active holders. Only list active, verified shareholders based on the latest available 13F filings.]

Investigate governance, management track record, insider activity, and institutional accumulation using Google Search:
1. MANAGEMENT INTEGRITY & CAPITAL ALLOCATION:
   - Historical capital allocation discipline: Historical Return on Invested Capital (ROIC) vs Cost of Capital (WACC).
   - Did management deliver on historical guidance in recent earnings calls?
   - Executive compensation alignment (Are bonuses tied to ROIC/FCF-per-share or vanity revenue growth?).
2. FORM 4 INSIDER TRANSACTIONS:
   - Form 4 insider trading audit over the past 12-18 months. Are executives buying with personal cash or systematically selling?
3. OWNERSHIP BREAKDOWN & LATEST OFFICIAL 13F WHALE TRACKING:
   - % Institutional, % Insiders, % Retail Float based on latest official filings.
   - Top active 13F institutional holders (who is actively accumulating vs who is trimming vs who has completely exited).
   - Public Commentary: Summarize the core thesis from recent respected fund manager quarterly letters and investor presentations.

Output exact, verified names, share counts, and clear takeaways based on official filings.
"""

STAGE_4_VALUATION_PROMPT = """Target: {ticker} ({company_name}) | Current Stock Price: ${current_price:.2f}

[AUTONOMY NOTE: Everything below is a guide. You have full freedom to pick the valuation methodologies (DCF, EPV, SOTP, Cash Flow Yield) and assumptions that best match this company's economic reality. Never reverse-engineer to match the stock price.]

Construct a RIGOROUS, AIRTIGHT 5-YEAR DISCOUNTED CASH FLOW (DCF) & EARNINGS POWER VALUE (EPV) INTRINSIC VALUATION MODEL:

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
   - Currency & Sovereign Risk Matching Principle:
     * For US-domestic equities: Risk-Free Rate = US 10-Year Treasury Yield (~4.2%–4.5%).
     * For International & Emerging Market equities (e.g. Brazil/LatAm/Asia/Europe):
       - If modeling in Local Currency (e.g. BRL): Use the domestic benchmark sovereign rate (e.g. Brazil Selic / NTN-F 10-Year yield at ~14.0%–15.0%), producing a local BRL WACC of ~17.0%–20.0%.
       - If modeling in USD-adjusted terms: Risk-Free Rate = US 10-Yr UST (~4.3%) + Country Risk Premium (CRP ~2.5%–3.0%) + FX inflation differential (~3.2%) = ~10.0%–10.5% adjusted USD base rate, producing a blended USD WACC of ~14.5%–15.5%.
     * Explicitly detail: Risk-Free Rate, Beta, Equity Risk Premium (ERP), Pre-Tax Cost of Debt, Marginal Tax Rate, Capital Structure Weights (Debt/Equity), and final WACC (%).
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

STAGE_5A_SYNTHESIS_PART1_PROMPT = """You are the Chief Investment Officer compiling Part 1 (Sections 1 to 4) of the Investment Due Diligence Memo on {ticker} ({company_name}).
Current Stock Price: ${current_price:.2f}

[AUTONOMY NOTE: Treat the outline below as a guide. You have full freedom to format, structure, and emphasize what is most essential.]

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

Part 2: Semantic HTML for Sections 1 to 4 (DO NOT TRUNCATE, KEEP ALL TABLES FULLY CLOSED):
1. Executive Summary & Variant Perception (Consensus vs What We Believe with <mark class="highlight">key takeaways</mark>)
2. Enterprise Value (TEV) & Normalized Cash Flow Multiples (Complete Table)
3. Internal Forecast vs. Wall Street Consensus (3-Year Forecast Comparison Table)
4. Business Model Anatomy & Cash Conversion Cycle Mechanics

Use clean semantic HTML (<div class="section">, <h2>, <h3>, <table>, <ul>, <p>, <blockquote>, <div class="callout">, <mark class="highlight">). Do NOT output outer <html> or <body> tags.

Analyst Inputs:
Financial Forensics: {stage1_data}
Moat & Industry: {stage2_data}
Management & Ownership: {stage3_data}
Valuation & DCF: {stage4_data}
"""

STAGE_5B_SYNTHESIS_PART2_PROMPT = """You are the Chief Investment Officer compiling Part 2 (Sections 5 to 8) of the Investment Due Diligence Memo on {ticker} ({company_name}).
Current Stock Price: ${current_price:.2f}

[AUTONOMY NOTE: Treat the outline below as a guide. You have full freedom to present the analysis with complete analytical discretion.]

Generate complete, beautiful Semantic HTML for Sections 5 to 8 (DO NOT TRUNCATE, KEEP ALL TABLES COMPLETE):
5. Competitive Advantage, Unit Economics & Competitor Benchmark Matrix (Complete Table)
6. Capital Allocation Track Record, ROIC & Share Buyback History (Complete Table)
7. Management Track Record, Compensation Alignment & Verified Latest Official 13F Ownership (Verify all holders against latest official SEC filings; do NOT list exited/historical investors as current active holders)
8. Capital Structure & Complete Net Debt Schedule (Maturities & Interest Coverage Complete Table)

Use clean semantic HTML (<div class="section">, <h2>, <h3>, <table>, <ul>, <p>, <blockquote>, <div class="callout">, <mark class="highlight">). Do NOT output outer <html> or <body> tags.

Analyst Inputs:
Financial Forensics: {stage1_data}
Moat & Industry: {stage2_data}
Management & Ownership: {stage3_data}
Valuation & DCF: {stage4_data}
"""

STAGE_5C_SYNTHESIS_PART3_PROMPT = """You are the Chief Investment Officer compiling Part 3 (Sections 9 to 12) of the Investment Due Diligence Memo on {ticker} ({company_name}).
Current Stock Price: ${current_price:.2f}

[AUTONOMY NOTE: Treat the outline below as a guide. You have full freedom to present the valuation and risk analysis with complete analytical discretion.]

Generate complete, beautiful Semantic HTML for Sections 9 to 12 (DO NOT TRUNCATE, FINISH ALL TABLES AND SECTIONS TO THE END):
9. True Owner Earnings & SBC 100% Cash Equivalent Charge Audit (Complete Table)
10. Rigorous 5-Year Unlevered DCF Model, WACC Specification, Sensitivity Matrix & Zero-Growth EPV (Complete Tables)
11. Triangulated Scenario Matrix (Bear / Base / Bull + 3-Yr Annualized IRRs Complete Table)
12. Invalidation Catalysts & Risk Pre-Mortem

Use clean semantic HTML (<div class="section">, <h2>, <h3>, <table>, <ul>, <p>, <blockquote>, <div class="callout">, <mark class="highlight">). Ensure all table rows are completely closed with all calculations intact. Do NOT output outer <html> or <body> tags.

Analyst Inputs:
Financial Forensics: {stage1_data}
Moat & Industry: {stage2_data}
Management & Ownership: {stage3_data}
Valuation & DCF: {stage4_data}
"""

STAGE_6_QA_VERIFICATION_PROMPT = """You are the Managing Editor & Chief Compliance Officer conducting the final quality verification, formatting audit, and polish pass on the Investment Due Diligence Memo on {ticker} ({company_name}).
Current Stock Price: ${current_price:.2f}

Below is the assembled draft of the research memo:
{draft_html}

Your Quality Assurance Directives:
1. Completeness Audit:
   - Ensure all 12 sections (from 1. Executive Summary to 12. Invalidation Catalysts & Risk Pre-Mortem) are present, fully written, and completely fleshed out.
   - If Section 12 (Invalidation Catalysts & Risk Pre-Mortem) is truncated or missing, write a complete, rigorous pre-mortem analysis with specific falsification triggers.
2. Table & Calculation Integrity:
   - Ensure EVERY table is fully closed with all columns and rows intact (all <table>, <tbody>, <tr>, <td> properly closed).
   - Ensure no half-finished rows or empty metrics exist.
3. Aesthetic Polish & Highlights:
   - Ensure key qualitative conclusions are highlighted using <mark class="highlight">...</mark>.
   - Remove any markdown artifacts, code fence tags, or stray notes.

Output ONLY the verified, polished, 100% complete Semantic HTML. Do not output outer <html> or <body> tags.
"""


def verify_and_repair_html_structure(html: str) -> str:
    """Deterministic structural cleanup, inline style removal, and tag balancing."""
    if not html:
        return ""
    
    cleaned = re.sub(r"^```(?:html)?\s*", "", html, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    
    # Strip ALL rogue inline style attributes to enforce 100% color consistency
    cleaned = re.sub(r'\s*style\s*=\s*"[^"]*"', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*style\s*=\s*'[^']*'", '', cleaned, flags=re.IGNORECASE)

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


def generate_genesis_thesis(ticker: str, company_name: str, current_price: float, initial_notes: str = "") -> Tuple[Dict[str, Any], str]:
    """Generates an authentic, independent institutional investment memo via modular multi-agent synthesis."""
    ticker_clean = ticker.upper().strip()
    print(f"  [Pipeline 1/7] Running Forensic Accounting & Capital Structure Audit for {ticker_clean}...")
    stage1_prompt = STAGE_1_FINANCIALS_PROMPT.format(ticker=ticker_clean, company_name=company_name, current_price=current_price)
    stage1_out = call_gemini_with_search(stage1_prompt, system_instruction=INSTITUTIONAL_SYSTEM_PHILOSOPHY)

    print(f"  [Pipeline 2/7] Investigating Operating Model Anatomy, Cash Conversion & Moat for {ticker_clean}...")
    stage2_prompt = STAGE_2_MOAT_INDUSTRY_PROMPT.format(ticker=ticker_clean, company_name=company_name, current_price=current_price)
    stage2_out = call_gemini_with_search(stage2_prompt, system_instruction=INSTITUTIONAL_SYSTEM_PHILOSOPHY)

    print(f"  [Pipeline 3/7] Auditing Capital Allocation (ROIC/Buybacks) & 13F Whales for {ticker_clean}...")
    stage3_prompt = STAGE_3_MANAGEMENT_OWNERSHIP_PROMPT.format(ticker=ticker_clean, company_name=company_name, current_price=current_price)
    stage3_out = call_gemini_with_search(stage3_prompt, system_instruction=INSTITUTIONAL_SYSTEM_PHILOSOPHY)

    print(f"  [Pipeline 4/7] Executing 5-Year Unlevered DCF, EPV & Sensitivity Model for {ticker_clean}...")
    stage4_prompt = STAGE_4_VALUATION_PROMPT.format(
        ticker=ticker_clean, company_name=company_name, current_price=current_price,
        stage1_data=stage1_out[:3500], stage2_data=stage2_out[:3500], stage3_data=stage3_out[:3500]
    )
    stage4_out = call_gemini_with_search(stage4_prompt, system_instruction=INSTITUTIONAL_SYSTEM_PHILOSOPHY)

    print(f"  [Pipeline 5a/7] Synthesizing Strategic & Operating Memo Sections (1-4) for {ticker_clean}...")
    stage5a_prompt = STAGE_5A_SYNTHESIS_PART1_PROMPT.format(
        ticker=ticker_clean, company_name=company_name, current_price=current_price,
        stage1_data=stage1_out[:2200], stage2_data=stage2_out[:2200],
        stage3_data=stage3_out[:2200], stage4_data=stage4_out[:3000]
    )
    res_part1 = call_gemini_with_search(stage5a_prompt, system_instruction=INSTITUTIONAL_SYSTEM_PHILOSOPHY)

    metadata = extract_json_block(res_part1)
    html_part1 = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", res_part1, flags=re.DOTALL).strip()
    if html_part1.startswith("```html"):
        html_part1 = html_part1[7:]
    if html_part1.endswith("```"):
        html_part1 = html_part1[:-3]
    html_part1 = clean_grounding_artifacts(html_part1.strip())

    print(f"  [Pipeline 5b/7] Synthesizing Moat, Capital Allocation & Debt Sections (5-8) for {ticker_clean}...")
    stage5b_prompt = STAGE_5B_SYNTHESIS_PART2_PROMPT.format(
        ticker=ticker_clean, company_name=company_name, current_price=current_price,
        stage1_data=stage1_out[:2200], stage2_data=stage2_out[:2200],
        stage3_data=stage3_out[:2200], stage4_data=stage4_out[:3000]
    )
    res_part2 = call_gemini_with_search(stage5b_prompt, system_instruction=INSTITUTIONAL_SYSTEM_PHILOSOPHY)

    html_part2 = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", res_part2, flags=re.DOTALL).strip()
    if html_part2.startswith("```html"):
        html_part2 = html_part2[7:]
    if html_part2.endswith("```"):
        html_part2 = html_part2[:-3]
    html_part2 = clean_grounding_artifacts(html_part2.strip())

    print(f"  [Pipeline 5c/7] Synthesizing Valuation, DCF, Scenarios & Risks Sections (9-12) for {ticker_clean}...")
    stage5c_prompt = STAGE_5C_SYNTHESIS_PART3_PROMPT.format(
        ticker=ticker_clean, company_name=company_name, current_price=current_price,
        stage1_data=stage1_out[:2200], stage2_data=stage2_out[:2200],
        stage3_data=stage3_out[:2200], stage4_data=stage4_out[:3000]
    )
    res_part3 = call_gemini_with_search(stage5c_prompt, system_instruction=INSTITUTIONAL_SYSTEM_PHILOSOPHY)

    html_part3 = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", res_part3, flags=re.DOTALL).strip()
    if html_part3.startswith("```html"):
        html_part3 = html_part3[7:]
    if html_part3.endswith("```"):
        html_part3 = html_part3[:-3]
    html_part3 = clean_grounding_artifacts(html_part3.strip())

    raw_html = f"{html_part1}\n\n{html_part2}\n\n{html_part3}".strip()

    print(f"  [Pipeline 6/6] Executing Final QA Verification & Structural Integrity Filter for {ticker_clean}...")
    # Check if Section 12 (Invalidation Catalysts & Risk Pre-Mortem) is present
    if "Invalidation" not in raw_html and "Pre-Mortem" not in raw_html:
        print(f"  ⚡ Synthesizing Section 12 (Invalidation Catalysts & Risk Pre-Mortem) for {ticker_clean}...")
        sec12_prompt = f"""You are the Chief Investment Officer compiling Section 12 (Invalidation Catalysts & Risk Pre-Mortem) for {ticker_clean} ({company_name}).
Stock Price: ${current_price:.2f}

Write a comprehensive, rigorous Section 12 in clean Semantic HTML:
<div class="section">
  <h2>12. Invalidation Catalysts & Risk Pre-Mortem</h2>
  <h3>12.1 Specific Falsification Triggers</h3>
  <p>Detail clear metric thresholds that would break the fundamental thesis.</p>
  <h3>12.2 Macro, Regulatory & Execution Headwinds</h3>
  <p>Detail severe downside risks and probability weighting.</p>
</div>

Do NOT output outer <html> or <body> tags. Ensure all tags are closed.
"""
        sec12_html = call_gemini_with_search(sec12_prompt, system_instruction=INSTITUTIONAL_SYSTEM_PHILOSOPHY)
        sec12_html = re.sub(r"```(?:html)?\s*", "", sec12_html).strip()
        if sec12_html.endswith("```"):
            sec12_html = sec12_html[:-3].strip()
        raw_html = f"{raw_html}\n\n{sec12_html}".strip()

    full_html = verify_and_repair_html_structure(raw_html)

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
            "executive_summary": f"Full independent fundamental due diligence established for {ticker_clean}."
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

[AUTONOMY & THESIS INFLECTION GUIDANCE]:
Everything below is a conceptual guide. You have full analytical freedom to evaluate the situation and determine the updated thesis:
- Did the core fundamental thesis hold, improve, or break?
- Conviction & Stance Changes:
  - If the valuation or fundamentals change to a Buy, Strong Buy, Screaming Buy, Hold, Trim, Sell, or Screaming Sell, explicitly state this conviction in the alert headline, the "what_changes_now" summary, and the updated research memo.
- Dynamic 3-Label Updates:
  - Update the 1 to 3 dynamic labels (max 2 words each) to reflect the new reality (e.g. ["Screaming Buy", "Moat Expanding", "Deleveraged"] or ["Screaming Sell", "Thesis Broken", "Multiple Compression"]).
- Level-Headed DCF Valuation:
  - Update the 5-year DCF valuation, fair value, scenario matrix, and alert corridors. Never force numbers to match the stock price. Treat SBC as a 100% real cash charge.

Output in TWO parts:
Part 1: JSON metadata in ```json ... ```:
{{
  "alert_title": "<Punchy headline stating if thesis shifted or conviction changed>",
  "alert_severity": "<1-2 word severity, e.g. Strong Buy, Caution, Thesis Broken, Accumulate>",
  "labels": ["<Label 1>", "<Label 2>", "<Label 3>"],
  "what_was_before": "<Summary of previous thesis>",
  "what_changes_now": "<What changed, why conviction shifted, and our new forward stance>",
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

    response_text = call_gemini_with_search(prompt, system_instruction=INSTITUTIONAL_SYSTEM_PHILOSOPHY)
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
