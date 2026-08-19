#!/usr/bin/env python3
"""Standalone Local Thesis Critique & Feedback Auditor.

Reads all investment theses in data/theses/, sends the full analysis to Gemini
using Google Search grounding and our model ladder, and captures detailed buy-side critique.
"""

import sys
import json
import re
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

CRITIQUES_DIR = PROJECT_ROOT / "data" / "critiques"
CRITIQUES_DIR.mkdir(parents=True, exist_ok=True)


def critique_thesis(ticker: str, thesis_data: List[Dict[str, Any]]) -> str:
    """Dispatches full thesis to Gemini and returns institutional critique."""
    if not thesis_data:
        return f"No thesis history found for {ticker}."
    
    latest = thesis_data[-1]
    company_name = latest.get("company_name", ticker)
    current_price = latest.get("price_at_version") or latest.get("current_price", 0.0)
    full_html = latest.get("full_html_content", "")
    
    prompt = f"""Target: {ticker} ({company_name})
Current Market Entry Price: ${current_price:.2f}

You are an institutional buy-side managing director and veteran value investor conducting a rigorous peer-review of this complete investment thesis.

Here is the full investment memo, operational storylines, and First-Principles DCF valuation:

======================================================================
{full_html}
======================================================================

Please provide a comprehensive, institutional-grade critique:
1. Overall Read: What is your honest, unfiltered assessment of this thesis?
2. Math & Valuation Audit: Does the math reconcile internally? (Owner Earnings baseline, share count, net cash per share, DCF cash flows, terminal value, and fair value). Flag any discrepancies, units mismatches, or round-number plugs.
3. Operational & Competitive Realism: Are the 1P/3P unit economics, take rates, margin trajectories, and competitor dynamics (e.g. Douyin, PDD, Alibaba, Amazon, Temu) accurately characterized against the company's latest quarterly 10-Q/6-K and annual 10-K/20-F filings?
4. Material Missing Risks / Blindspots: What sovereign, regulatory, capital repatriation (VIE/HFCAA), debt structure, or market-share risks are overlooked or under-weighted?
5. Strategic Takeaways: What specific improvements would make this thesis truly bulletproof?

Format your critique with clear headers and bullet points. Be rigorous, blunt, and constructive.
"""
    print(f"\n" + "=" * 70)
    print(f"🧐 DISPATCHING THESIS CRITIQUE TO GEMINI FOR: {ticker} ({company_name})")
    print(f"=" * 70, flush=True)
    
    critique = call_gemini_with_search(prompt, temperature=0.2)
    clean_critique = clean_grounding_artifacts(critique)
    
    # Save critique to file
    critique_file = CRITIQUES_DIR / f"{ticker}_critique.md"
    critique_file.write_text(clean_critique, encoding="utf-8")
    print(f"✅ Critique saved to: {critique_file}", flush=True)
    
    return clean_critique


def run_all_critiques():
    """Iterates through all theses in data/theses/ and runs critiques."""
    theses_dir = PROJECT_ROOT / "data" / "theses"
    thesis_files = sorted(list(theses_dir.glob("*.json")))
    
    if not thesis_files:
        print("❌ No thesis files found in data/theses/")
        return
    
    print(f"🔍 Found {len(thesis_files)} thesis files to critique: {[f.stem for f in thesis_files]}")
    
    results = {}
    for tf in thesis_files:
        ticker = tf.stem.upper()
        try:
            with open(tf, "r", encoding="utf-8") as f:
                data = json.load(f)
            critique = critique_thesis(ticker, data)
            results[ticker] = critique
        except Exception as e:
            print(f"❌ Error critiquing {ticker}: {e}")
            
    print("\n" + "=" * 70)
    print("🏁 ALL THESIS CRITIQUES COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    run_all_critiques()
