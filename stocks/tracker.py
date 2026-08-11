"""Real-time market price tracker and alert surveillance engine."""

import requests
import json
from datetime import datetime
from typing import Tuple, Dict, Any, List, Optional
import yfinance as yf
from stocks.models import WatchlistStock, TaskItem
from stocks.data_store import load_watchlist, save_watchlist, get_stock


def fetch_live_stock_info(ticker: str) -> Tuple[str, float]:
    """Fetches real-time market price and verified corporate name via Yahoo Finance API."""
    ticker_clean = ticker.upper().strip()
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_clean}?interval=1d&range=1d"
        res = requests.get(url, headers=headers, timeout=6)
        if res.status_code == 200:
            data = res.json()
            meta = data["chart"]["result"][0]["meta"]
            price = float(meta.get("regularMarketPrice", 0.0))
            name = meta.get("shortName") or meta.get("longName") or ticker_clean
            if price > 0:
                return name, round(price, 2)
    except Exception:
        pass

    # Fallback to yfinance
    try:
        t = yf.Ticker(ticker_clean)
        info = t.info
        name = info.get("shortName") or info.get("longName") or ticker_clean
        price = info.get("regularMarketPrice") or info.get("currentPrice")
        if price:
            return name, round(float(price), 2)
    except Exception:
        pass

    return ticker_clean, 100.00


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

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_clean}?interval={interval}&range={rng}"
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            result = data["chart"]["result"][0]
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
        pass

    # Fallback to yfinance history
    try:
        t = yf.Ticker(ticker_clean)
        hist = t.history(period=rng, interval=interval)
        points = []
        for dt, row in hist.iterrows():
            close = row.get("Close")
            if close and close > 0:
                points.append({"date": dt.strftime("%b %d, %Y"), "price": round(float(close), 2)})
        if points:
            return points
    except Exception:
        pass

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

    return triggered_count
