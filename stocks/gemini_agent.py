"""Gemini 3.6 Flash Institutional Research Agent with Google Search Grounding & 13F/Insider Tracking."""

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


COLUMBIA_ANALYST_SYSTEM_PROMPT = """You are a Principal Investment Partner at a concentrated fundamental equity fund (Graham & Dodd / Columbia Business School methodology).

CORE MANDATES YOU MUST RIGOROUSLY EXECUTE:
1. SBC (Stock-Based Compensation) IS A CASH DRAIN: Treat SBC as real economic dilution that reduces True Owner Earnings.
2. Balance Sheet & Net Debt Bridge: Account for funded debt, operating leases, cash balances, maturities, and interest coverage.
3. Ownership, Insiders & 13F Smart Money Tracking:
   - Search for recent Form 4 Insider Buys / Sells by C-suite and Directors. (Are executives buying with their own cash?)
   - Ownership breakdown (% Institutional, % Insider/Founders, Float).
   - Notable Institutional / Hedge Fund 13F holders (Who is accumulating or trimming?).
   - Public Commentary: What are respected fund managers, activist investors, or quarterly investor letters saying about this stock?
4. Capital Allocation: Evaluate share buyback accretion vs dilution and ROIC.
5. Triangulated Valuation & Asymmetry:
   - Scenario Matrix: Bear, Base, Bull cases with explicit multiples, target prices, and 2-3 year annualized IRRs.
   - Fair Value Estimate: A defensible intrinsic value per share.
6. Socratic Self-Questioning & Variant Perception:
   - Contrast Consensus View vs Variant Reality.
   - Pre-Mortem: What specific 10-Q metrics would destroy this thesis?
7. Dynamic Alert Triggers:
   - Set Upper Threshold ($), Lower Threshold ($), and next major Catalyst Date.
   - Assign a fluid, descriptive status label.
"""


def generate_genesis_thesis(ticker: str, company_name: str, current_price: float, initial_notes: str = "") -> Tuple[Dict[str, Any], str]:
    """Generates the initial comprehensive Genesis Living Thesis using Gemini 3.6 Flash with Search."""
    prompt = f"""Conduct an institutional due diligence equity research thesis on {ticker.upper()} ({company_name}).
CURRENT STOCK PRICE: ${current_price:.2f}
Additional user notes: {initial_notes if initial_notes else 'None.'}

Use Google Search to retrieve:
- Real-time financial statements, latest 10-K/10-Q data, revenue, EBITDA, cash, debt, and SBC numbers.
- Insider Transactions (Recent Form 4 purchases/sales by CEO/CFO/Directors).
- Institutional Ownership & 13F Hedge Fund holdings (Top funds holding or accumulating; quotes/thesis from top fund letters).
- Industry dynamics, moat, pricing power, and upcoming catalyst dates.

You MUST produce your output in TWO parts:
Part 1: A JSON metadata block enclosed in ```json ... ```:
{{
  "ticker": "{ticker.upper()}",
  "company_name": "{company_name}",
  "status_label": "<Fluid status label, e.g. High Conviction Compounder, Deep Value Re-rating, Turnaround>",
  "fair_value_estimate": "$<Fair Value>",
  "bear_target": "$<Bear Price> (<Downside %>)",
  "base_target": "$<Base Price> (<Upside %>)",
  "bull_target": "$<Bull Price> (<Upside %>)",
  "upper_alert_threshold": <Float upper trigger price, e.g. 42.5>,
  "lower_alert_threshold": <Float lower trigger price, e.g. 31.0>,
  "upper_trigger_reason": "<Why wake up on upside break>",
  "lower_trigger_reason": "<Why wake up on downside drop>",
  "next_catalyst_date": "<Upcoming Date, e.g. November 2026>",
  "next_catalyst_event": "<Upcoming Event Description>",
  "executive_summary": "<2-3 sentence punchy summary of the thesis and variant perception>"
}}

Part 2: The rich HTML body content formatted in semantic HTML sections:
1. Executive Summary & Variant Perception (Consensus vs What We Believe)
2. Ownership Structure, Insider Buying & 13F Smart Money (Form 4 Insider transactions, % Institutional/Insider ownership, top funds holding/accumulating, and public fund commentary/quotes)
3. Business Moat, Pricing Power & Unit Economics
4. Balance Sheet Forensics & Net Debt Bridge (Cash, Debt schedule, Maturities, Liquidity runway)
5. True Owner Earnings & SBC Audit (SBC dilution as cash expense, Maintenance vs Growth CapEx)
6. Valuation Triangulation & Scenario Matrix (Bear / Base / Bull table with multiples, prices, IRRs)
7. Socratic Pre-Mortem & Downside Risks (Brutal cross-examination: How this thesis could fail)
8. Surveillance Boundaries & Catalyst Timeline (Upper trigger, Lower trigger, Next catalyst date)

Use clean semantic HTML (<div class="section">, <h2>, <h3>, <table>, <ul>, <p>, <blockquote>, <div class="callout">). Do NOT include outer <html> or <body> tags.
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
            "ticker": ticker.upper(),
            "company_name": company_name,
            "status_label": "Watchlist Candidate",
            "fair_value_estimate": f"${current_price * 1.25:.2f}",
            "bear_target": f"${current_price * 0.75:.2f} (-25.0%)",
            "base_target": f"${current_price * 1.25:.2f} (+25.0%)",
            "bull_target": f"${current_price * 1.6:.2f} (+60.0%)",
            "upper_alert_threshold": round(current_price * 1.15, 2),
            "lower_alert_threshold": round(current_price * 0.88, 2),
            "upper_trigger_reason": "Upside momentum breakout",
            "lower_trigger_reason": "Downside support / margin of safety test",
            "next_catalyst_date": "Next Earnings",
            "next_catalyst_event": "Quarterly earnings release",
            "executive_summary": f"Initial institutional research established for {ticker.upper()} at ${current_price:.2f}."
        }

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
    """Reviews an active stock when a price threshold, catalyst date, or major swing is triggered."""
    price_change_pct = ((current_price - baseline_price) / baseline_price) * 100 if baseline_price else 0.0

    prompt = f"""We are performing an autonomous Living Thesis Review on {ticker.upper()} ({company_name}).
TRIGGER EVENT: {trigger_reason}
Baseline Price (at Genesis/Last Review): ${baseline_price:.2f}
Current Price: ${current_price:.2f} (Total Change: {price_change_pct:+.2f}%)
Previous Status: {previous_status}
Previous Thesis Summary: {previous_thesis_summary}

Use Google Search to research what happened:
- Breaking news, earnings, management commentary, insider Form 4 activity, fund 13F changes, macro shifts.
- Is the thesis VALIDATED, INTACT (Discount Opportunity), or COMPROMISED?

Produce your output in TWO parts:
Part 1: A JSON metadata block in ```json ... ```:
{{
  "alert_title": "<Concise Punchy Alert Headline>",
  "alert_severity": "<Fluid LLM Severity, e.g. HIGH CONVICTION ACCUMULATION, THESIS VALIDATED, DENTED - CAUTION, or TAKE PROFIT>",
  "what_was_before": "<Summary of previous thesis and assumptions>",
  "what_changes_now": "<What new information arrived, how the thesis changes, and our new forward stance>",
  "new_status_label": "<New fluid status label>",
  "new_fair_value": "$<Updated Fair Value>",
  "new_bear_target": "$<Updated Bear>",
  "new_base_target": "$<Updated Base>",
  "new_bull_target": "$<Updated Bull>",
  "new_upper_alert_threshold": <New Float upper price trigger>,
  "new_lower_alert_threshold": <New Float lower price trigger>,
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
