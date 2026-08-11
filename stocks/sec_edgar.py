"""Free SEC EDGAR 8-K, 10-Q, and Material Event Surveillance Engine.

Integrates with the official, public domain SEC EDGAR REST API and real-time Atom stream
with zero subscription cost, rate-limiting safeguards, and local filing caching.
"""

import json
import time
import re
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from stocks.data_store import DATA_DIR, load_watchlist

SEC_HEADERS = {
    "User-Agent": "AlphaThesis Research Engine contact@alphathesis.local",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov"
}

SEC_WWW_HEADERS = {
    "User-Agent": "AlphaThesis Research Engine contact@alphathesis.local",
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov"
}

CIK_MAP_FILE = DATA_DIR / "sec_cik_map.json"
FILINGS_CACHE_FILE = DATA_DIR / "sec_filings_cache.json"

# Common SEC Form 8-K Item Definitions
ITEM_DESCRIPTIONS = {
    "1.01": "Entry into a Material Definitive Agreement (M&A / Commercial Contract)",
    "1.02": "Termination of a Material Definitive Agreement",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition (Official Earnings Release)",
    "2.05": "Costs Associated with Exit or Disposal Activities (Restructuring / Layoffs)",
    "3.01": "Notice of Delisting or Failure to Satisfy a Continued Listing Rule",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financial Statements (Restatement)",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure/Election of Directors or Principal Officers (CEO/CFO/Executive Change)",
    "5.03": "Amendments to Articles of Incorporation or Bylaws",
    "7.01": "Regulation FD Disclosure (Investor Presentation / Guidance Update)",
    "8.01": "Other Material Events",
    "9.01": "Financial Statements and Exhibits"
}


def load_cik_map() -> Dict[str, str]:
    """Loads ticker-to-CIK mapping from local cache or fetches from SEC."""
    if CIK_MAP_FILE.exists():
        try:
            with open(CIK_MAP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Fetch official mapping from SEC
    try:
        url = "https://www.sec.gov/files/company_tickers.json"
        r = requests.get(url, headers=SEC_WWW_HEADERS, timeout=10)
        if r.status_code == 200:
            raw = r.json()
            mapping = {item["ticker"].upper(): str(item["cik_str"]) for item in raw.values()}
            with open(CIK_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(mapping, f, indent=2)
            return mapping
    except Exception as e:
        print(f"⚠️ Warning: Failed to fetch SEC company tickers mapping: {e}")

    return {}


def load_filings_cache() -> Dict[str, List[str]]:
    """Loads previously seen SEC accession numbers."""
    if FILINGS_CACHE_FILE.exists():
        try:
            with open(FILINGS_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_filings_cache(cache: Dict[str, List[str]]):
    """Saves seen SEC accession numbers to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(FILINGS_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def get_cik_for_ticker(ticker: str, cik_map: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Gets zero-padded 10-digit CIK for a given stock ticker."""
    if cik_map is None:
        cik_map = load_cik_map()
    raw_cik = cik_map.get(ticker.upper())
    if raw_cik:
        return raw_cik.zfill(10)
    return None


def fetch_company_recent_filings(cik: str) -> Optional[Dict[str, Any]]:
    """Fetches recent submissions directly from the free SEC REST API."""
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    try:
        r = requests.get(url, headers=SEC_HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"⚠️ Failed to fetch SEC submissions for CIK {cik}: {e}")
    return None


def check_sec_filing_triggers() -> int:
    """Surveillance pass: checks SEC EDGAR for new material 8-K, 10-Q, or 10-K filings.
    Enqueues tasks for any newly discovered filings not in cache."""
    from stocks.queue_manager import enqueue_task
    from stocks.models import TaskItem

    watchlist = load_watchlist()
    if not watchlist:
        return 0

    cik_map = load_cik_map()
    filings_cache = load_filings_cache()
    triggered_count = 0
    updated_cache = False

    # Check each watchlist stock politely
    for ticker, stock in watchlist.items():
        cik = get_cik_for_ticker(ticker, cik_map)
        if not cik:
            continue

        cached_accs = set(filings_cache.get(ticker, []))
        
        # Polite rate limit sleep: ~0.12s between requests (well under SEC 10 req/s limit)
        time.sleep(0.12)
        data = fetch_company_recent_filings(cik)
        if not data:
            continue

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        items_list = recent.get("items", [])
        accessions = recent.get("accessionNumber", [])
        doc_descs = recent.get("primaryDocDescription", [])

        # If ticker is new to cache, seed current accessions without triggering avalanche
        if ticker not in filings_cache:
            filings_cache[ticker] = accessions[:15]
            updated_cache = True
            continue

        # Look for new filings in the top 5 recent submissions
        for i in range(min(5, len(forms))):
            form = forms[i]
            acc = accessions[i]
            f_date = filing_dates[i]
            raw_items = items_list[i] if i < len(items_list) else ""
            desc = doc_descs[i] if i < len(doc_descs) else ""

            if acc in cached_accs:
                continue

            # We care about 8-K (US Material events), 6-K (Foreign Private Issuer Material events), 
            # 10-Q/10-K (US Quarterly/Annual reports), 20-F/40-F (Foreign Annual reports)
            if form in ["8-K", "8-K/A", "6-K", "6-K/A", "10-Q", "10-K", "20-F", "40-F"]:
                # Parse Item labels
                item_meanings = []
                if raw_items:
                    for itm in str(raw_items).split(","):
                        itm_clean = itm.strip()
                        if itm_clean in ITEM_DESCRIPTIONS:
                            item_meanings.append(f"Item {itm_clean}: {ITEM_DESCRIPTIONS[itm_clean]}")
                        elif itm_clean:
                            item_meanings.append(f"Item {itm_clean}")

                item_summary = "; ".join(item_meanings) if item_meanings else (desc or "Foreign/Domestic Material Corporate Filing")
                trigger_reason = f"SEC {form} Filing ({f_date}): {item_summary} [Accession #{acc}]"

                print(f"🚨 [SEC FILING TRIGGER] {ticker}: {trigger_reason}")
                
                enqueue_task(TaskItem(
                    id=f"sec_{ticker}_{acc.replace('-', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    task_type="SEC_8K_TRIGGER",
                    ticker=ticker,
                    notes=trigger_reason
                ))
                
                # Mark as seen
                filings_cache.setdefault(ticker, []).append(acc)
                cached_accs.add(acc)
                triggered_count += 1
                updated_cache = True

    # Check international / OTC tickers without SEC CIKs via Free Corporate News Wire
    for ticker, stock in watchlist.items():
        if get_cik_for_ticker(ticker, cik_map):
            continue  # Already monitored via SEC EDGAR

        # Fetch free RSS headline feed
        try:
            from stocks.tracker import TICKER_ALIASES
            search_sym = TICKER_ALIASES.get(ticker, [ticker])[0]
            rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={search_sym}"
            r = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                items = root.findall("./channel/item")
                cached_news = set(filings_cache.get(ticker, []))
                
                if ticker not in filings_cache:
                    filings_cache[ticker] = [it.find("link").text for it in items[:10] if it.find("link") is not None]
                    updated_cache = True
                    continue

                for it in items[:3]:
                    link = it.find("link").text if it.find("link") is not None else ""
                    title = it.find("title").text if it.find("title") is not None else ""
                    pub_date = it.find("pubDate").text if it.find("pubDate") is not None else ""

                    if link and link not in cached_news:
                        # Check if title indicates material corporate news (earnings, results, acquisition, guidance)
                        title_lower = title.lower()
                        if any(kw in title_lower for kw in ["earnings", "results", "revenue", "guidance", "acquires", "acquisition", "quarter", "dividend", "financial report"]):
                            trigger_reason = f"International Corporate Wire ({pub_date}): {title}"
                            print(f"🚨 [INTL NEWS TRIGGER] {ticker}: {trigger_reason}")
                            enqueue_task(TaskItem(
                                id=f"news_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                                task_type="REVIEW",
                                ticker=ticker,
                                notes=trigger_reason
                            ))
                            triggered_count += 1

                        filings_cache.setdefault(ticker, []).append(link)
                        cached_news.add(link)
                        updated_cache = True
        except Exception:
            continue

    if updated_cache:
        save_filings_cache(filings_cache)

    return triggered_count
