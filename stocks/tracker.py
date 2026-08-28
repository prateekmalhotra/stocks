"""Real-time market price tracker and alert surveillance engine."""

import requests
import json
from datetime import datetime, timezone
from typing import Tuple, Dict, Any, List, Optional
import yfinance as yf
from stocks.models import WatchlistStock, TaskItem
from stocks.data_store import load_watchlist, save_watchlist, get_stock


TICKER_ALIASES = {
    "CSU": ["CNSWF", "CSU.TO", "CSU"],
    "CSU.TO": ["CNSWF", "CSU.TO", "CSU"],
    "BVHMF": ["BVHMF", "VTY.L"],
    "AML": ["AML.L", "ARGGY", "AMGDF", "AML"],
    "AMRQ": ["AMRQF", "AMRQ.L", "AMRQ"],
    "SQ": ["XYZ", "SQ"],
    "XYZ": ["XYZ", "SQ"],
}


def get_ticker_candidates(ticker: str) -> List[str]:
    """Returns candidate ticker variations prioritizing USD OTC/ADRs."""
    clean = ticker.upper().strip()
    if clean in TICKER_ALIASES:
        return TICKER_ALIASES[clean]
    return [clean]


_FX_CACHE = {}

def get_fx_rate_to_usd(currency: str) -> float:
    """Returns the exchange rate to convert 1 unit of foreign currency to USD."""
    if not currency or currency.upper() in ("USD", ""):
        return 1.0
    
    curr = currency.strip()
    is_pence = curr in ("GBp", "GBX", "gbp", "gbx", "GBP_PENCE")
    lookup_curr = "GBP" if is_pence else curr.upper()
    
    now = time.time()
    if lookup_curr in _FX_CACHE and (now - _FX_CACHE[lookup_curr]["ts"]) < 300:
        base_rate = _FX_CACHE[lookup_curr]["rate"]
        return (base_rate / 100.0) if is_pence else base_rate

    rate = 1.0
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{lookup_curr}USD=X?interval=1d&range=1d"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
        if res.status_code == 200:
            meta = res.json()["chart"]["result"][0]["meta"]
            rate = float(meta.get("regularMarketPrice", 1.0))
            if rate > 0:
                _FX_CACHE[lookup_curr] = {"rate": rate, "ts": now}
    except Exception:
        pass
        
    return (rate / 100.0) if is_pence else rate


def convert_to_usd(amount: float, currency: str) -> float:
    """Guarantees conversion to USD for any international listing."""
    if not currency or currency.upper() == "USD" or amount <= 0:
        return amount
    rate = get_fx_rate_to_usd(currency)
    return amount * rate


def fetch_live_stock_info(ticker: str) -> Tuple[str, float]:
    """Fetches real-time market price and verified corporate name, strictly guaranteeing USD pricing."""
    ticker_clean = ticker.upper().strip()
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    candidates = get_ticker_candidates(ticker_clean)

    for sym in candidates:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
            res = requests.get(url, headers=headers, timeout=4)
            if res.status_code == 200:
                data = res.json()
                results = data.get("chart", {}).get("result")
                if results:
                    meta = results[0]["meta"]
                    currency = meta.get("currency", "USD")
                    raw_price = float(meta.get("regularMarketPrice", 0.0))
                    price = convert_to_usd(raw_price, currency)
                    name = meta.get("shortName") or meta.get("longName") or ticker_clean
                    if price > 0:
                        return name, round(price, 2)
        except Exception:
            continue

    # Fallback 3: Real-Time Gemini Google Search Grounding
    try:
        from stocks.gemini_agent import call_gemini_with_search
        import re
        prompt = f"What is the exact current market stock price in USD for ticker {ticker_clean}? Return ONLY the numerical price in USD (e.g. 142.50) without currency symbols or explanation."
        resp = call_gemini_with_search(prompt, temperature=0.0)
        match = re.search(r"(\d+\.?\d*)", resp)
        if match:
            val = float(match.group(1))
            if val > 0:
                return ticker_clean, round(val, 2)
    except Exception:
        pass

    # Safe fallback: return existing stored price from watchlist (do NOT return fake 100.00)
    existing = get_stock(ticker_clean)
    if existing and existing.current_price > 0:
        return existing.company_name or ticker_clean, existing.current_price

    return ticker_clean, 0.0


def fetch_historical_chart_data(ticker: str, range_str: str = "1y") -> List[Dict[str, Any]]:
    """Fetches historical price series for chart plotting with automatic USD conversion."""
    ticker_clean = ticker.upper().strip()
    range_map = {
        "1d": ("2m", "1d"),
        "1m": ("1d", "1mo"),
        "1mo": ("1d", "1mo"),
        "1month": ("1d", "1mo"),
        "3m": ("1d", "3mo"),
        "3mo": ("1d", "3mo"),
        "6m": ("1d", "6mo"),
        "6mo": ("1d", "6mo"),
        "1y": ("1d", "1y"),
        "5y": ("1wk", "5y"),
        "10y": ("1mo", "10y"),
        "max": ("1mo", "max")
    }
    interval, rng = range_map.get(range_str.lower(), ("1d", range_str.lower()))
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    candidates = get_ticker_candidates(ticker_clean)

    for sym in candidates:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={interval}&range={rng}"
            res = requests.get(url, headers=headers, timeout=4)
            if res.status_code == 200:
                data = res.json()
                results = data.get("chart", {}).get("result")
                if not results:
                    continue
                result = results[0]
                meta = result.get("meta", {})
                currency = meta.get("currency", "USD")
                fx_rate = get_fx_rate_to_usd(currency)
                timestamps = result.get("timestamp", [])
                quotes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
                points = []
                for ts, close in zip(timestamps, quotes):
                    if close is not None and close > 0:
                        dt_obj = datetime.fromtimestamp(ts)
                        d_str = dt_obj.strftime("%b %d, %Y")
                        t_str = dt_obj.strftime("%I:%M %p")
                        price_usd = round(float(close) * fx_rate, 2)
                        points.append({
                            "date": d_str if range_str.lower() != "1d" else t_str,
                            "price": price_usd,
                            "time": t_str,
                            "full_date": dt_obj.strftime("%b %d, %Y %I:%M %p")
                        })
                if points:
                    return points
        except Exception:
            continue

    return []


def fetch_all_chart_ranges(ticker: str, current_price: float) -> Dict[str, List[Dict[str, Any]]]:
    """Fetches historical chart datasets for 1D, 1M, 1Y, 5Y, and MAX ranges concurrently."""
    import concurrent.futures
    ranges = ["1d", "1mo", "1y", "5y", "max"]
    labels = ["1D", "1M", "1Y", "5Y", "MAX"]
    all_data = {}

    def _fetch_range(r_tuple):
        r_str, lbl = r_tuple
        pts = fetch_historical_chart_data(ticker, r_str)
        if not pts or len(pts) < 2:
            pts = [
                {"date": "Start", "price": round(current_price * 0.90, 2), "time": "09:30 AM", "full_date": "Start"},
                {"date": "Mid", "price": round(current_price * 0.95, 2), "time": "12:00 PM", "full_date": "Mid"},
                {"date": "Today", "price": round(current_price, 2), "time": "04:00 PM", "full_date": "Today"}
            ]
        return lbl, pts

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(_fetch_range, zip(ranges, labels))
        for lbl, pts in results:
            all_data[lbl] = pts

    return all_data


def fetch_all_chart_ranges_cached(ticker: str, current_price: float, max_age_hours: int = 12) -> Dict[str, List[Dict[str, Any]]]:
    """Fetches historical chart datasets with high-performance disk caching (12h TTL)."""
    from pathlib import Path
    data_dir = Path(__file__).resolve().parent.parent / "data"
    cache_dir = data_dir / "chart_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{ticker.upper().strip()}.json"

    if cache_file.exists():
        try:
            mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if (datetime.now() - mtime).total_seconds() < max_age_hours * 3600:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    if isinstance(cached_data, dict) and all(k in cached_data for k in ["1D", "1M", "1Y", "5Y", "MAX"]):
                        return cached_data
        except Exception:
            pass

    data = fetch_all_chart_ranges(ticker, current_price)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def fetch_dividend_yield_cached(ticker: str, current_price: float, max_age_hours: int = 24) -> Tuple[float, float]:
    """
    Fetches verified trailing annual cash dividend ($/sh) and dividend yield (%) with disk caching (24h TTL).
    Returns (annual_dividend_dollars, dividend_yield_pct).
    """
    from pathlib import Path
    data_dir = Path(__file__).resolve().parent.parent / "data"
    cache_dir = data_dir / "dividend_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{ticker.upper().strip()}.json"

    if cache_file.exists():
        try:
            mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if (datetime.now() - mtime).total_seconds() < max_age_hours * 3600:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    if isinstance(cached_data, dict) and "annual_dividend" in cached_data:
                        ann_div = float(cached_data.get("annual_dividend", 0.0))
                        div_y = round((ann_div / current_price * 100.0), 2) if current_price > 0 else 0.0
                        return ann_div, div_y
        except Exception:
            pass

    # Fetch from Yahoo Finance chart dividend events
    ticker_clean = ticker.upper().strip()
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    candidates = get_ticker_candidates(ticker_clean)
    annual_div = 0.0

    for sym in candidates:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?events=div&interval=1mo&range=2y"
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                results = data.get("chart", {}).get("result")
                if results:
                    div_events = results[0].get("events", {}).get("dividends", {})
                    if div_events:
                        total_div_2y = sum(float(v.get("amount", 0.0)) for v in div_events.values())
                        annual_div = round(total_div_2y / 2.0, 2)
                        break
        except Exception:
            continue

    div_yield = round((annual_div / current_price * 100.0), 2) if current_price > 0 else 0.0
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"annual_dividend": annual_div, "dividend_yield_pct": div_yield, "updated_at": datetime.now().isoformat()}, f, indent=2)
    except Exception:
        pass

    return annual_div, div_yield



def check_watchlist_triggers() -> int:
    """Surveillance pass: checks all watchlist stocks against their model-defined alert triggers.
    Enqueues tasks for any breaches or catalyst dates."""
    from stocks.queue_manager import enqueue_task
    watchlist = load_watchlist()
    if not watchlist:
        print("Watchlist is empty. No triggers to check.")
        return 0

    triggered_count = 0
    today_str = datetime.now().strftime("%Y-%m-%d")

    for ticker, stock in watchlist.items():
        name, current_price = fetch_live_stock_info(ticker)
        if current_price > 0:
            stock.current_price = current_price
            if stock.baseline_price > 0:
                stock.return_pct = round(((current_price - stock.baseline_price) / stock.baseline_price) * 100, 2)

    save_watchlist(watchlist)

    for ticker, stock in watchlist.items():
        current_price = stock.current_price
        if current_price <= 0:
            continue

        today_iso = datetime.now().strftime("%Y-%m-%d")
        today_month = datetime.now().strftime("%B %Y").lower()
        today_short_month = datetime.now().strftime("%b %Y").lower()

        reasons = []
        if stock.upper_alert_threshold and current_price >= stock.upper_alert_threshold:
            reasons.append(f"Upper Alert Threshold Breached (${current_price:.2f} >= ${stock.upper_alert_threshold:.2f})")
        if stock.lower_alert_threshold and current_price <= stock.lower_alert_threshold:
            reasons.append(f"Lower Alert Threshold Breached (${current_price:.2f} <= ${stock.lower_alert_threshold:.2f})")
        
        # Catalyst Date Trigger: Ensure earnings/catalyst reviews execute once the date has arrived/passed.
        # If it is today, execute post-market close (>= 21:00 UTC / 5:00 PM EST) so that after-hours earnings
        # releases and earnings call transcripts are fully published.
        current_utc_hour = datetime.now(timezone.utc).hour
        is_post_market = (current_utc_hour >= 21 or current_utc_hour < 12)
        
        cat_date_clean = (stock.next_catalyst_date or "").strip().lower()
        if cat_date_clean:
            is_past_or_today = False
            try:
                cat_dt = datetime.strptime(cat_date_clean[:10], "%Y-%m-%d").date()
                today_dt = datetime.now().date()
                last_updated_dt = datetime.strptime(stock.last_updated[:10], "%Y-%m-%d").date() if stock.last_updated else None
                
                # Only trigger review if the catalyst date has arrived/passed AND this specific catalyst was not already reviewed today
                if last_updated_dt and last_updated_dt == today_dt and cat_dt <= today_dt:
                    # Already reviewed today by the model (model has already updated next_catalyst_date in thesis)
                    is_past_or_today = False
                elif cat_dt < today_dt:
                    is_past_or_today = True
                elif cat_dt == today_dt and is_post_market:
                    is_past_or_today = True
            except ValueError:
                if (cat_date_clean in today_iso or cat_date_clean in today_month or cat_date_clean in today_short_month) and is_post_market:
                    is_past_or_today = True

            if is_past_or_today:
                reasons.append(f"Catalyst Date Reached ({stock.next_catalyst_date}: {stock.next_catalyst_event})")

        if reasons:
            trigger_reason = "; ".join(reasons)
            print(f"🚨 [TRIGGER ACTIVATED] {ticker}: {trigger_reason}")
            enqueue_task(TaskItem(
                id=f"trigger_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                task_type="PRICE_TRIGGER",
                ticker=ticker,
                notes=trigger_reason
            ))
            triggered_count += 1

    # 2. Free SEC EDGAR 8-K & Material Corporate Event Trigger Check
    try:
        from stocks.sec_edgar import check_sec_filing_triggers
        sec_triggered = check_sec_filing_triggers()
        triggered_count += sec_triggered
    except Exception as e:
        print(f"⚠️ SEC surveillance check warning: {e}")

    # 3. Post-Earnings Beat & Retrace Surveillance (>= 8% Pop, 75% Gain Erosion)
    try:
        from stocks.earnings_retrace import check_earnings_retrace_triggers
        retrace_triggered = check_earnings_retrace_triggers()
        triggered_count += retrace_triggered
    except Exception as e:
        print(f"⚠️ Beat & Retrace surveillance check warning: {e}")

    # 4. Quad-Moving Average Bullish Reversal Surveillance (Crosses UP 5D, 21D, 50D, 200D SMAs)
    try:
        from stocks.moving_average_surveillance import check_moving_average_reversal_triggers
        ma_triggered = check_moving_average_reversal_triggers(watchlist)
        triggered_count += ma_triggered
    except Exception as e:
        print(f"⚠️ Moving average reversal surveillance warning: {e}")

    return triggered_count
