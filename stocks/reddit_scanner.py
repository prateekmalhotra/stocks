"""Weekly r/ValueInvesting Subreddit Scanner & Autonomous Coverage Ingestion Engine."""

import os
import re
import json
from datetime import datetime
from pathlib import Path
from typing import List, Set

from stocks.gemini_agent import call_gemini_with_search
from stocks.data_store import load_watchlist
from stocks.main import cmd_add
from stocks.dashboard import render_all

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Non-equity, benchmark, or user-excluded noise
EXCLUDED_TICKERS: Set[str] = {
    "SPY", "QQQ", "VOO", "VTI", "IWM", "DIA", "VT", "VEA", "VWO", "SCHD",
    "TLT", "IEF", "SHY", "BIL", "BND", "AGG", "GLD", "SLV", "USO", "UNG",
    "BTC", "ETH", "USDT", "USDC", "GOOG", "GOOGL", "CASH", "USD", "EUR", "CAD"
}


def scan_reddit_valueinvesting() -> List[str]:
    """Asks Gemini with Google Search Grounding to scan r/ValueInvesting for all trending/hot tickers."""
    prompt = """Perform an exhaustive real-time search across the Reddit community r/ValueInvesting (https://www.reddit.com/r/ValueInvesting) for all stock tickers currently being discussed, pitched, debated, or trending in hot and top recent posts.

OBJECTIVE:
Extract the maximum possible number of distinct individual company stock tickers (US and global ADRs). Optimize strictly for high recall and breadth (catch ALL genuine company tickers mentioned in investment theses, deep value ideas, compounders, earnings reactions, and portfolio reviews).

INSTRUCTIONS:
1. Search across recent hot discussions, weekly idea threads, and individual thesis write-ups on r/ValueInvesting.
2. Extract all valid 1-5 letter equity tickers (e.g., GCT, FICO, CMCSA, MEDP, BTI, UNH, ASML, TXN, ELF, SMRT, etc.).
3. Do NOT include broad market ETFs (like SPY, QQQ, VOO) or macroeconomic acronyms (like GDP, CPI, FED).
4. Return ONLY a single raw JSON array of uppercase ticker strings, with no surrounding markdown formatting or text.

Example format:
["GCT", "FICO", "CMCSA", "MEDP", "BTI", "UNH", "ASML", "TXN", "ELF", "SMRT"]
"""

    system_instruction = "You are a specialized institutional quantitative researcher. Extract all valid equity stock tickers discussed on r/ValueInvesting into a strict JSON list of strings."
    
    print("🌐 Querying Gemini with Google Search Grounding for r/ValueInvesting ticker mentions...")
    raw_response = call_gemini_with_search(prompt, system_instruction=system_instruction, temperature=0.2)
    
    # Extract JSON list from response
    match = re.search(r"\[\s*\"[A-Z0-9\.\-]+(?:\s*,\s*\"[A-Z0-9\.\-]+\")*\s*\]", raw_response)
    if match:
        try:
            tickers = json.loads(match.group(0))
            return [t.upper().strip().replace("$", "") for t in tickers if isinstance(t, str)]
        except Exception:
            pass

    # Fallback regex extraction of quoted tickers
    fallback_tickers = re.findall(r'"([A-Z]{1,5})"', raw_response)
    if fallback_tickers:
        return list(dict.fromkeys(fallback_tickers))
        
    # Additional fallback for uppercase words
    words = re.findall(r'\b([A-Z]{1,5})\b', raw_response)
    return list(dict.fromkeys([w for w in words if w not in EXCLUDED_TICKERS]))


def run_weekly_reddit_coverage_sync(max_new: int = 0, auto_ingest: bool = True) -> List[str]:
    """Scans r/ValueInvesting, filters existing watchlist stocks, and triggers coverage on all new candidates."""
    print("=" * 90)
    print(f"📡 [REDDIT VALUE SCANNER] Initiating Friday Surveillance at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
    print("=" * 90)

    watchlist = load_watchlist()
    existing_tickers = set(watchlist.keys())
    print(f"📊 Active Watchlist: {len(existing_tickers)} stocks currently monitored.")

    scraped_tickers = scan_reddit_valueinvesting()
    print(f"🔍 Discovered {len(scraped_tickers)} raw ticker mentions from r/ValueInvesting: {', '.join(scraped_tickers)}")

    # Filter out already tracked, excluded, or invalid tickers
    new_tickers = []
    skipped_existing = []
    
    for t in scraped_tickers:
        clean_t = t.upper().strip().replace("$", "")
        if not clean_t or len(clean_t) > 5:
            continue
        if clean_t in EXCLUDED_TICKERS:
            continue
        if clean_t in existing_tickers:
            skipped_existing.append(clean_t)
            continue
        if clean_t not in new_tickers:
            new_tickers.append(clean_t)

    print(f"\n⏭️ [SKIPPED - ALREADY MONITORED] ({len(skipped_existing)}): {', '.join(skipped_existing) if skipped_existing else 'None'}")
    print(f"✨ [NEW CANDIDATES DISCOVERED] ({len(new_tickers)}): {', '.join(new_tickers) if new_tickers else 'None'}")

    if not new_tickers:
        print("\n✅ All trending r/ValueInvesting stocks are already in our coverage universe. Zero actions needed.")
        return []

    # Ingest all new discovered stocks (or limit if max_new is explicitly set > 0)
    if max_new and max_new > 0:
        to_ingest = new_tickers[:max_new]
    else:
        to_ingest = new_tickers

    print(f"\n🚀 Initiating Genesis Research & Living Thesis Pipeline for all {len(to_ingest)} new stocks: {', '.join(to_ingest)}...")

    if auto_ingest:
        cmd_add(to_ingest, notes="Auto-discovered via r/ValueInvesting weekly trending surveillance scanner.")
        print(f"\n🎨 Re-rendering master dashboard and research reports...")
        render_all()
        print(f"✅ Successfully ingested {len(to_ingest)} new stocks from r/ValueInvesting into coverage universe!")

    return to_ingest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scan r/ValueInvesting and ingest new stock coverage.")
    parser.add_argument("--max", type=int, default=0, help="Max new stocks to ingest in one batch (default: 0 = ingest all new candidates)")
    parser.add_argument("--dry-run", action="store_true", help="Only scan and display without ingesting")
    args = parser.parse_args()

    run_weekly_reddit_coverage_sync(max_new=args.max, auto_ingest=not args.dry_run)

