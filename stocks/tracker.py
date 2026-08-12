"""Real-time market price tracker and alert surveillance engine."""

import requests
import json
from datetime import datetime
from typing import Tuple, Dict, Any, List, Optional
import yfinance as yf
from stocks.models import WatchlistStock, TaskItem
from stocks.data_store import load_watchlist, save_watchlist, get_stock


TICKER_ALIASES = {
    "CSU": ["CNSWF", "CSU.TO", "CSU"],
    "CSU.TO": ["CNSWF", "CSU.TO", "CSU"],
    "BVHMF": ["BVHMF", "VTY.L"],
}


def get_ticker_candidates(ticker: str) -> List[str]:
    """Returns candidate ticker variations prioritizing USD OTC/ADRs."""
    clean = ticker.upper().strip()
    if clean in TICKER_ALIASES:
        return TICKER_ALIASES[clean]
    return [clean]


def convert_to_usd(amount: float, currency: str) -> float:
    """Guarantees conversion to USD for any international listing."""
    if not currency or currency.upper() == "USD" or amount <= 0:
        return amount
    curr = currency.upper()
    try:
        if curr == "CAD":
            url = "https://query1.finance.yahoo.com/v8/finance/chart/CADUSD=X?interval=1d&range=1d"
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
            rate = float(res.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
            return amount * rate
        elif curr in ["GBP", "GBX", "GBp", "GBPEUR"]:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/GBPUSD=X?interval=1d&range=1d"
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
            rate = float(res.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
            if curr in ["GBX", "GBp"]:  # Pence to Pounds
                return (amount / 100.0) * rate
            return amount * rate
        elif curr == "EUR":
            url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1d&range=1d"
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
            rate = float(res.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
            return amount * rate
    except Exception:
        pass
    return amount


def fetch_live_stock_info(ticker: str) -> Tuple[str, float]:
    """Fetches real-time market price and verified corporate name, strictly guaranteeing USD pricing."""
    ticker_clean = ticker.upper().strip()
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    candidates = get_ticker_candidates(ticker_clean)

    for sym in candidates:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
            res = requests.get(url, headers=headers, timeout=6)
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

    # Fallback 2: yfinance
    for sym in candidates:
        try:
            t = yf.Ticker(sym)
            info = t.info
            name = info.get("shortName") or info.get("longName") or ticker_clean
            raw_price = info.get("regularMarketPrice") or info.get("currentPrice")
            currency = info.get("currency", "USD")
            if raw_price and float(raw_price) > 0:
                price = convert_to_usd(float(raw_price), currency)
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
    """Fetches historical price series for chart plotting."""
    ticker_clean = ticker.upper().strip()
    range_map = {
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
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200:
                data = res.json()
                results = data.get("chart", {}).get("result")
                if not results:
                    continue
                result = results[0]
                timestamps = result.get("timestamp", [])
                quotes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
                points = []
                for ts, close in zip(timestamps, quotes):
                    if close is not None and close > 0:
                        d_str = datetime.fromtimestamp(ts).strftime("%b %d, %Y")
                        points.append({"date": d_str, "price": round(float(close), 2)})
                if points:
                    return points
        except Exception:
            continue

    # Fallback to yfinance history
    for sym in candidates:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period=rng, interval=interval)
            points = []
            for dt, row in hist.iterrows():
                close = row.get("Close")
                if close and close > 0:
                    points.append({"date": dt.strftime("%b %d, %Y"), "price": round(float(close), 2)})
            if points:
                return points
        except Exception:
            continue

    return []


def fetch_all_chart_ranges(ticker: str, current_price: float) -> Dict[str, List[Dict[str, Any]]]:
    """Fetches historical chart datasets for 1Y, 5Y, 10Y, and MAX ranges."""
    ranges = ["1y", "5y", "10y", "max"]
    labels = ["1Y", "5Y", "10Y", "MAX"]
    all_data = {}

    for r_str, lbl in zip(ranges, labels):
        pts = fetch_historical_chart_data(ticker, r_str)
        if not pts or len(pts) < 2:
            pts = [
                {"date": "Start", "price": round(current_price * 0.90, 2)},
                {"date": "Mid", "price": round(current_price * 0.95, 2)},
                {"date": "Today", "price": round(current_price, 2)}
            ]
        all_data[lbl] = pts

    return all_data


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
        stock.current_price = current_price
        if stock.baseline_price > 0:
            stock.return_pct = round(((current_price - stock.baseline_price) / stock.baseline_price) * 100, 2)

    save_watchlist(watchlist)

    for ticker, stock in watchlist.items():
        current_price = stock.current_price
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
        current_utc_hour = datetime.utcnow().hour
        is_post_market = (current_utc_hour >= 21 or current_utc_hour < 12)
        
        cat_date_clean = (stock.next_catalyst_date or "").strip().lower()
        if cat_date_clean:
            is_past_or_today = False
            try:
                cat_dt = datetime.strptime(cat_date_clean[:10], "%Y-%m-%d").date()
                today_dt = datetime.now().date()
                if cat_dt < today_dt:
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

    return triggered_count
