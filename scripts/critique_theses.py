#!/usr/bin/env python3
"""Standalone Local Thesis Critique & Feedback Auditor.

Iterates through all stocks on the watchlist (and data/theses/),
extracts only the investment thesis, and queries Gemini 3.7 Flash (with fallback to 3.6 Flash)
with the simple feedback prompt: 'Can you please give feedback on my investment thesis?'
Saves all feedback to data/critiques/{ticker}_critique.md.
"""

import sys
import json
import os
from pathlib import Path
from typing import Dict, Any, List

# Ensure stocks package is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stocks.gemini_agent import (
    call_gemini_with_search,
    clean_grounding_artifacts
)
from stocks.data_store import load_watchlist

DATA_DIR = PROJECT_ROOT / "data"
THESES_DIR = DATA_DIR / "theses"
CRITIQUES_DIR = DATA_DIR / "critiques"
CRITIQUES_DIR.mkdir(parents=True, exist_ok=True)


def get_thesis_content_for_ticker(ticker: str) -> str:
    """Retrieves the full investment thesis HTML or text for a ticker."""
    clean_t = ticker.upper().strip()
    thesis_file = THESES_DIR / f"{clean_t}.json"
    
    if thesis_file.exists():
        try:
            with open(thesis_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    return data[-1].get("full_html_content", "")
                elif isinstance(data, dict):
                    return data.get("full_html_content", "")
        except Exception as e:
            print(f"⚠️ Error reading {thesis_file}: {e}")
            
    # Fallback to public report HTML if available
    report_file = PROJECT_ROOT / "public" / "reports" / f"{clean_t}.html"
    if report_file.exists():
        try:
            return report_file.read_text(encoding="utf-8")
        except Exception as e:
            print(f"⚠️ Error reading {report_file}: {e}")
            
    return ""


def critique_stock_thesis(ticker: str) -> str:
    """Runs a 3-agent autonomous critique pipeline:
    Agent 1 (Search Investigator): Actively searches latest 10-Q/10-K, segment drags, and supply chain risks.
    Agent 2 (Valuation Auditor): Audits cash flow matching (FCFE vs FCFF), debt deductions, and working capital.
    Agent 3 (Lead Red-Team PM): Synthesizes findings into an institutional Buy-Side Red-Team memo.
    """
    thesis_html = get_thesis_content_for_ticker(ticker)
    if not thesis_html:
        msg = f"❌ No thesis content found for {ticker} in data/theses/ or public/reports/."
        print(msg)
        return msg

    clean_t = ticker.upper().strip()
    print("\n" + "=" * 75)
    print(f"🏢 INITIATING 3-AGENT AUTONOMOUS CRITIQUE FOR: {clean_t}")
    print("=" * 75, flush=True)

    # -------------------------------------------------------------
    # AGENT 1: Investigative Fact-Checking & Headwind Researcher
    # -------------------------------------------------------------
    print(f"🔍 [CRITIQUE AGENT 1: FACT & HEADWIND INVESTIGATOR] Searching live filings & segment performance for {clean_t}...")
    agent_1_prompt = f"""Target Ticker: {clean_t}

You are Critique Agent 1: Senior Investigative Research Analyst at a premier buy-side hedge fund.
Your task is to conduct an independent, deep-dive factual investigation using Google Search to uncover current real-world headwinds, operating pain points, and vulnerabilities for {clean_t}.

Actively search for and document:
1. Segment & Brand Performance: What are the exact YoY revenue growth rates, margins, and volume trends for EACH operating brand/division over the last 2-4 quarters? (Specifically identify any declining acquired brands, e.g. double-digit revenue drops or inventory write-downs).
2. Product & Category Concentration: Is the company vulnerable to single-silhouette fashion fatigue, platform churn, or shifting consumer demographics?
3. Supply Chain & Manufacturing Concentration: Where are the company's primary manufacturing hubs located (% in Vietnam, China, Indonesia, Mexico, etc.)? What is the current exposure to Section 301 tariffs or freight cost friction?
4. Management Execution & Guidance: What were the key warnings, conservative guidance statements, or margin headwinds discussed on the last 2 earnings calls?

Deliver a structured factual audit briefing with concrete numbers and citations."""

    try:
        agent_1_output = call_gemini_with_search(
            prompt=agent_1_prompt,
            temperature=0.2,
            use_search=True
        )
        agent_1_clean = clean_grounding_artifacts(agent_1_output)
        print(f"   │ Status: Factual Headwind Audit completed ({len(agent_1_clean.split())} words)")
    except Exception as e:
        print(f"   ⚠️ Agent 1 Search error: {e}")
        agent_1_clean = f"Independent search notes unavailable due to API error: {e}"

    # -------------------------------------------------------------
    # AGENT 2: Valuation Model & Cash Flow Sanity Auditor
    # -------------------------------------------------------------
    print(f"🧮 [CRITIQUE AGENT 2: QUANT & CASH FLOW AUDITOR] Stress-testing valuation math & capital allocation...")
    agent_2_prompt = f"""Target Ticker: {clean_t}

You are Critique Agent 2: Senior Valuation & Accounting Specialist.
Audit the following investment thesis for mathematical integrity, cash flow matching, and valuation consistency.

Investment Thesis:
======================================================================
{thesis_html}
======================================================================

Investigative Findings from Agent 1:
======================================================================
{agent_1_clean}
======================================================================

Specifically audit:
1. Cash Flow Matching & Debt Consistency:
   - Does starting Owner Earnings begin from post-interest GAAP Operating Cash Flow (FCFE) or un-levered cash flow (FCFF)?
   - If starting with post-interest cash flow, is Net Debt improperly deducted a second time from enterprise present value (creating a double-penalty)?
2. Working Capital & Baseline Realism:
   - Did trailing cash flow benefit from temporary inventory liquidations or working capital swings?
   - Is starting Owner Earnings (OE₀) a defensible steady-state run rate?
3. Capital Allocation & Share Count:
   - How are share repurchases modeled vs. static share count assumptions?
4. Exit Multiples & Hurdle Rates:
   - Are terminal growth rates and hurdle rates realistic for this industry cyclicality?

Deliver a rigorous quantitative audit report with specific formula checks."""

    try:
        agent_2_output = call_gemini_with_search(
            prompt=agent_2_prompt,
            temperature=0.2,
            use_search=False
        )
        agent_2_clean = clean_grounding_artifacts(agent_2_output)
        print(f"   │ Status: Valuation & Accounting Audit completed ({len(agent_2_clean.split())} words)")
    except Exception as e:
        print(f"   ⚠️ Agent 2 Audit error: {e}")
        agent_2_clean = f"Valuation audit notes unavailable due to API error: {e}"

    # -------------------------------------------------------------
    # AGENT 3: Lead Portfolio Manager Red-Team Synthesis
    # -------------------------------------------------------------
    print(f"🧠 [CRITIQUE AGENT 3: LEAD RED-TEAM PM] Synthesizing comprehensive institutional memo...")
    agent_3_prompt = f"""Target Ticker: {clean_t}

You are Critique Agent 3: Chief Investment Officer & Lead Portfolio Manager at an elite value hedge fund.
Synthesize the original Investment Thesis, Agent 1's Investigative Fact Audit, and Agent 2's Quantitative Valuation Audit into a definitive, institutional-grade Red-Team Memo.

Investment Thesis:
======================================================================
{thesis_html}
======================================================================

Agent 1 (Factual & Headwind Investigation):
======================================================================
{agent_1_clean}
======================================================================

Agent 2 (Valuation & Accounting Audit):
======================================================================
{agent_2_clean}
======================================================================

Deliver a sharp, honest, buy-side memo structured as follows:
1. Executive Assessment & Recommended Stance (BUY / HOLD / AVOID) with explicit target entry price thresholds.
2. Verified Strengths of the Thesis (what is mathematically and operationally sound).
3. Critical Vulnerabilities, Fatal Blind Spots & Value-Trap Risks (highlighting segment drags, supply chain risks, and unearned turnaround assumptions).
4. Actionable Refinements Checklist (concrete, prioritized steps to elevate the thesis to 100/100 buy-side standard)."""

    try:
        final_feedback = call_gemini_with_search(
            prompt=agent_3_prompt,
            temperature=0.2,
            use_search=False
        )
        clean_fb = clean_grounding_artifacts(final_feedback)
        
        # Save feedback
        out_file = CRITIQUES_DIR / f"{clean_t}_critique.md"
        out_file.write_text(clean_fb, encoding="utf-8")
        print(f"\n✅ Final Red-Team Critique saved to: {out_file}\n")
        print("-------------------- FINAL RED-TEAM CRITIQUE --------------------")
        print(clean_fb)
        print("-----------------------------------------------------------------\n", flush=True)
        return clean_fb
    except Exception as e:
        err_msg = f"❌ Failed to synthesize final feedback for {clean_t}: {e}"
        print(err_msg)
        return err_msg


def run_all_watchlist_critiques():
    """Iterates through all stocks on watchlist and collects feedback on their investment theses."""
    watchlist = load_watchlist()
    tickers_to_process = list(watchlist.keys())
    
    # Also check if there are any theses in data/theses/ not explicitly in watchlist.json
    for tf in THESES_DIR.glob("*.json"):
        t = tf.stem.upper()
        if t not in tickers_to_process:
            tickers_to_process.append(t)
            
    if not tickers_to_process:
        print("ℹ️ Watchlist and theses directory are currently empty.")
        print("Please generate or add stocks to watchlist first.")
        return
        
    print(f"🔍 Found {len(tickers_to_process)} stocks to evaluate: {tickers_to_process}")
    
    results = {}
    for ticker in tickers_to_process:
        results[ticker] = critique_stock_thesis(ticker)
        
    print("\n" + "=" * 75)
    print(f"🏁 COMPLETED THESIS FEEDBACK EVALUATION FOR {len(results)} STOCKS.")
    print(f"📂 Feedback files written to: {CRITIQUES_DIR}/")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    run_all_watchlist_critiques()

