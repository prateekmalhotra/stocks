"""Gemini 3.6 Flash Institutional Research Agent with Google Search Grounding."""

import os
import json
import re
import requests
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from dotenv import load_dotenv

load_dotenv()


def get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY is not set in environment or .env file.")
    return key


def call_gemini_with_search(prompt: str, system_instruction: str = "") -> str:
    """Calls Gemini 3.6 Flash via REST API with Google Search Grounding enabled."""
    api_key = get_api_key()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
    
    payload: Dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0.4,
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
        candidate = res_json["candidates"][0]
        text = candidate["content"]["parts"][0]["text"]
        return text
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected response structure from Gemini API: {res_json}") from e


def extract_json_block(text: str) -> Dict[str, Any]:
    """Extracts a JSON object from markdown code fences or raw text."""
    # Look for ```json ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    
    # Fallback to finding outer braces
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except Exception:
            pass
            
    return {}


# ==================== GENESIS THESIS PROMPT ====================

COLUMBIA_ANALYST_SYSTEM_PROMPT = """You are a Principal Investment Analyst and Partner at a concentrated fundamental value investment fund (in the tradition of Graham & Dodd and Columbia Business School). 

You write institutional-grade, intellectually rigorous investment theses that stand up to the highest scrutiny. You never write generic filler, platitudes, or superficial overviews. 

CORE INVESTMENT PHILOSOPHIES YOU RIGOROUSLY ENFORCE:
1. SBC (Stock-Based Compensation) is a CASH EXPENSE: Never treat SBC as a harmless non-cash add-back. You must treat SBC as real economic dilution that reduces true Owner Earnings.
2. Balance Sheet & True Net Debt Bridge: Always bridge Enterprise Value to Equity Value (EV = Market Cap + Debt + Preferred + Minorities - Cash & Equivalents). Analyze debt maturities, interest coverage, and liquidity runway.
3. Capital Allocation: Evaluate whether share buybacks are accretive (buying below intrinsic value) or destructive. Track net share count trajectory.
4. Triangulated Valuation & Asymmetry:
   - Scenario Modeling: Bear Case, Base Case, Bull Case with explicit EV/EBITDA or P/FCF multiples, implied target prices, and 2-3 year annualized IRRs.
   - Earnings Power Value (EPV) / Normalized FCF: Sustainable operating margin capitalized at WACC.
   - Fair Value Estimate: A level-headed, defensible intrinsic value per share.
5. Socratic Self-Questioning & Devil's Advocate:
   - Identify the Variant Perception: What does consensus believe vs. what is the actual reality?
   - Poke brutal holes into your own thesis: What are the specific metrics in the next 10-Q/10-K that would prove you wrong and invalidate this thesis?
6. Dynamic Alert Triggers:
   - Establish an Upper Alert Threshold ($) (e.g. Breakout / Catalyst confirmed)
   - Establish a Lower Alert Threshold ($) (e.g. Deep Discount / Margin of safety entry or stop-loss check)
   - Identify upcoming catalyst dates (e.g. next earnings, major product release, FDA/regulatory decision)
   - Assign a fluid, descriptive Status Label (e.g. 'High Conviction Compounder', 'Deep Value Re-rating', 'High-Risk Turnaround', 'Wait for Pullback').
"""


def generate_genesis_thesis(ticker: str, company_name: str, current_price: float, initial_notes: str = "") -> Tuple[Dict[str, Any], str]:
    """Generates the initial comprehensive Genesis Living Thesis using Gemini 3.6 Flash with Search."""
    prompt = f"""Perform a comprehensive institutional equity research due diligence on {ticker.upper()} ({company_name}).
Current Stock Price: ${current_price:.2f}
Additional context/user notes: {initial_notes if initial_notes else 'None provided.'}

Use Google Search to find real-time financial metrics, latest 10-K/10-Q filings, recent earnings reports, balance sheet items (Cash, Debt), share count trends, SBC, and major industry news.

You MUST produce your output in TWO parts:
Part 1: A JSON metadata block at the top enclosed in ```json ... ``` with this exact structure:
{{
  "ticker": "{ticker.upper()}",
  "company_name": "{company_name}",
  "status_label": "<Fluid custom status label, e.g. High Conviction Compounder>",
  "fair_value_estimate": "$<Fair Value>",
  "bear_target": "$<Bear Price> (<Downside %>)",
  "base_target": "$<Base Price> (<Upside %>)",
  "bull_target": "$<Bull Price> (<Upside %>)",
  "upper_alert_threshold": <Float number of upper trigger price, e.g. 155.0>,
  "lower_alert_threshold": <Float number of lower trigger price, e.g. 118.0>,
  "upper_trigger_reason": "<Why wake up if price crosses above this>",
  "lower_trigger_reason": "<Why wake up if price drops below this>",
  "next_catalyst_date": "<YYYY-MM-DD or Month Year of next major catalyst/earnings>",
  "next_catalyst_event": "<Description of upcoming catalyst>",
  "executive_summary": "<2-3 sentence punchy summary of why this is or is not an attractive investment right now>"
}}

Part 2: The complete, richly styled, dark-mode Living Thesis HTML body content.
The HTML content must be structured into clear sections:
1. Executive Summary & Variant Perception (What consensus thinks vs What we believe)
2. Business Moat, Pricing Power & Unit Economics
3. Balance Sheet Forensics & Net Debt Bridge (Cash, Debt, Maturities, Liquidity)
4. True Owner Earnings & SBC Audit (SBC impact, Maintenance Capex vs Growth Capex, Share Count Trajectory)
5. Valuation Triangulation & Scenario Matrix (Table with Bear / Base / Bull, Multiples, Implied Share Prices, IRRs)
6. Socratic Cross-Examination & Pre-Mortem (The Devil's Advocate: How could this fail? Specific invalidation triggers)
7. Catalyst Timeline & Monitoring Boundaries (Upper trigger, Lower trigger, Next catalyst date)

Use clean HTML tags (<div class="section">, <h2>, <table>, <ul>, <p>, <blockquote>, <span class="badge">). Do NOT include full <html><body> tags, just the inner container content. Use semantic classes.
"""

    response_text = call_gemini_with_search(prompt, system_instruction=COLUMBIA_ANALYST_SYSTEM_PROMPT)
    metadata = extract_json_block(response_text)
    
    # Clean out the json block to isolate the HTML content
    html_content = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", response_text, flags=re.DOTALL).strip()
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = html_content.strip()

    # Fill fallback metadata if needed
    if not metadata:
        metadata = {
            "ticker": ticker.upper(),
            "company_name": company_name,
            "status_label": "Watchlist Candidate",
            "fair_value_estimate": f"${current_price:.2f}",
            "bear_target": f"${current_price * 0.8:.2f} (-20%)",
            "base_target": f"${current_price * 1.25:.2f} (+25%)",
            "bull_target": f"${current_price * 1.6:.2f} (+60%)",
            "upper_alert_threshold": round(current_price * 1.15, 2),
            "lower_alert_threshold": round(current_price * 0.88, 2),
            "upper_trigger_reason": "Upside momentum / valuation expansion",
            "lower_trigger_reason": "Downside support test / discount zone",
            "next_catalyst_date": "Next Earnings",
            "next_catalyst_event": "Quarterly earnings report and guidance",
            "executive_summary": f"Initial research dossier generated for {ticker.upper()} at ${current_price:.2f}."
        }

    return metadata, html_content


# ==================== THESIS REVIEW / ALERT PROMPT ====================

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
    """Reviews an active stock when a price threshold, catalyst date, or major swing is triggered."""
    price_change_pct = ((current_price - baseline_price) / baseline_price) * 100 if baseline_price else 0.0

    prompt = f"""We are performing an autonomous Living Thesis Review on {ticker.upper()} ({company_name}).
TRIGGER EVENT: {trigger_reason}
Baseline Price (at Genesis/Last Review): ${baseline_price:.2f}
Current Price: ${current_price:.2f} (Total Change: {price_change_pct:+.2f}%)
Previous Status: {previous_status}
Previous Thesis Summary: {previous_thesis_summary}

Use Google Search to research what happened to {ticker.upper()} recently: breaking news, earnings results, analyst revisions, executive changes, macro factors, or industry developments explaining the move.

Evaluate the core question:
- Has the investment thesis been VALIDATED, STRENGTHENED, INTACT (Mr. Market Discount Opportunity), or COMPROMISED/DENTED?

Produce your output in TWO parts:
Part 1: A JSON metadata block enclosed in ```json ... ```:
{{
  "alert_title": "<Concise Punchy Alert Headline, e.g. NVDA Breaks $155 Threshold on Hyperscaler CapEx Spike>",
  "alert_severity": "<Fluid LLM Severity/Category, e.g. HIGH CONVICTION ACCUMULATION, THESIS VALIDATED, DENTED - CAUTION, or TAKE PROFIT>",
  "what_was_before": "<Summary of previous thesis, valuation stance, and assumptions>",
  "what_changes_now": "<What new information arrived, how the thesis changes, and our new forward action>",
  "new_status_label": "<New fluid status label, e.g. Compounding On Track, Discount Opportunity, High-Risk Hold, Cut Position>",
  "new_fair_value": "$<Updated Fair Value>",
  "new_bear_target": "$<Updated Bear>",
  "new_base_target": "$<Updated Base>",
  "new_bull_target": "$<Updated Bull>",
  "new_upper_alert_threshold": <New Float upper price trigger, e.g. 175.0>,
  "new_lower_alert_threshold": <New Float lower price trigger, e.g. 135.0>,
  "next_catalyst_date": "<Upcoming Date>",
  "next_catalyst_event": "<Upcoming Event Description>"
}}

Part 2: The Updated Living Thesis HTML content incorporating this new update, noting the dated evolution card at the top followed by the refreshed thesis.
"""

    response_text = call_gemini_with_search(prompt, system_instruction=COLUMBIA_ANALYST_SYSTEM_PROMPT)
    metadata = extract_json_block(response_text)
    
    html_content = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", response_text, flags=re.DOTALL).strip()
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = html_content.strip()

    if not metadata:
        metadata = {
            "alert_title": f"{ticker.upper()} Price & Thesis Review (${current_price:.2f})",
            "alert_severity": "THESIS REVIEW",
            "what_was_before": previous_thesis_summary,
            "what_changes_now": f"Stock moved to ${current_price:.2f} ({price_change_pct:+.1f}%). Thesis reviewed.",
            "new_status_label": previous_status,
            "new_fair_value": f"${current_price * 1.15:.2f}",
            "new_bear_target": f"${current_price * 0.85:.2f}",
            "new_base_target": f"${current_price * 1.25:.2f}",
            "new_bull_target": f"${current_price * 1.5:.2f}",
            "new_upper_alert_threshold": round(current_price * 1.15, 2),
            "new_lower_alert_threshold": round(current_price * 0.88, 2),
            "next_catalyst_date": "Next Earnings",
            "next_catalyst_event": "Scheduled earnings report"
        }

    return metadata, html_content
