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
    """Sends ONLY the investment thesis to Gemini 3.7 Flash (fallback to 3.6 Flash) asking for feedback."""
    thesis_html = get_thesis_content_for_ticker(ticker)
    if not thesis_html:
        msg = f"❌ No thesis content found for {ticker} in data/theses/ or public/reports/."
        print(msg)
        return msg
        
    prompt = f"""Can you please give feedback on my investment thesis?

Target: {ticker}

Investment Thesis:
======================================================================
{thesis_html}
======================================================================
"""
    print("\n" + "=" * 75)
    print(f"🧐 DISPATCHING THESIS FEEDBACK REQUEST FOR: {ticker} (Model: gemini-3.7-flash -> gemini-3.6-flash)")
    print("=" * 75, flush=True)

    try:
        feedback = call_gemini_with_search(
            prompt=prompt,
            temperature=0.2,
            override_model="gemini-3.7-flash",
            use_search=True
        )
        clean_fb = clean_grounding_artifacts(feedback)
        
        # Save feedback
        out_file = CRITIQUES_DIR / f"{ticker}_critique.md"
        out_file.write_text(clean_fb, encoding="utf-8")
        print(f"\n✅ Feedback captured and saved to: {out_file}\n")
        print("-------------------- FEEDBACK OUTPUT --------------------")
        print(clean_fb)
        print("---------------------------------------------------------\n", flush=True)
        return clean_fb
    except Exception as e:
        err_msg = f"❌ Failed to get feedback for {ticker}: {e}"
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

