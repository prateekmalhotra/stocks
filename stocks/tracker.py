"""Free market surveillance & trigger evaluator via direct market endpoints and yfinance."""

import requests
import yfinance as yf
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List
from stocks.models import WatchlistStock, TaskItem
from stocks.data_store import load_watchlist, save_watchlist, enqueue_task


def fetch_live_stock_info(ticker: str) -> Tuple[str, float]:
    """Fetches company name and current live/closing price for free with zero API key."""
    ticker_clean = ticker.upper().strip()
    
    # 1. Primary: Direct Yahoo Finance v8 JSON API (Ultra-fast and reliable)
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_clean}?interval=1d&range=5d"
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
            name = meta.get("shortName") or meta.get("longName") or ticker_clean
            if price and price > 0:
                return name, round(float(price), 2)
    except Exception:
        pass

    # 2. Fallback: yfinance Ticker
    try:
        t = yf.Ticker(ticker_clean)
        price = getattr(t.fast_info, "last_price", None)
        if price and price > 0:
            name = ticker_clean
            try:
                name = t.info.get("shortName") or ticker_clean
            except Exception:
                pass
            return name, round(float(price), 2)
    except Exception:
        pass

    return ticker_clean, 100.0


def fetch_historical_chart_data(ticker: str, range_str: str = "1y") -> List[Dict[str, Any]]:
    """Fetches clean daily historical closing prices for native minimalist charting."""
    ticker_clean = ticker.upper().strip()
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_clean}?interval=1d&range={range_str}"
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
        hist = t.history(period=range_str)
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


def check_watchlist_triggers() -> int:
    """Surveillance pass: checks all watchlist stocks against their model-defined alert triggers.
    Enqueues tasks for any breaches or catalyst dates."""
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

        # Evaluate Triggers
        reasons = []
        if stock.upper_alert_threshold and current_price >= stock.upper_alert_threshold:
            reasons.append(f"Upper Alert Threshold Breached (${current_price:.2f} >= ${stock.upper_alert_threshold:.2f})")
        if stock.lower_alert_threshold and current_price <= stock.lower_alert_threshold:
            reasons.append(f"Lower Alert Threshold Breached (${current_price:.2f} <= ${stock.lower_alert_threshold:.2f})")
        if stock.next_catalyst_date and stock.next_catalyst_date in today_str:
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
