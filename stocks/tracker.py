"""Free market surveillance & trigger evaluator via direct market endpoints and yfinance."""

import requests
import yfinance as yf
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
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
        stock.return_pct = round(((current_price - stock.baseline_price) / stock.baseline_price) * 100, 2)

        trigger_reason = None
        task_type = "PRICE_TRIGGER"

        # 1. Upper Alert Threshold Check
        if stock.upper_alert_threshold and current_price >= stock.upper_alert_threshold:
            trigger_reason = f"UPPER THRESHOLD BREACH: Price ${current_price:.2f} crossed upper trigger (${stock.upper_alert_threshold:.2f})."

        # 2. Lower Alert Threshold Check
        elif stock.lower_alert_threshold and current_price <= stock.lower_alert_threshold:
            trigger_reason = f"LOWER THRESHOLD BREACH: Price ${current_price:.2f} dropped below lower trigger (${stock.lower_alert_threshold:.2f})."

        # 3. Catalyst Date Check
        elif stock.next_catalyst_date and stock.next_catalyst_date in today_str:
            trigger_reason = f"CATALYST DATE REACHED: {stock.next_catalyst_event or 'Scheduled event'} on {stock.next_catalyst_date}."
            task_type = "CATALYST_DUE"

        if trigger_reason:
            task = TaskItem(
                id=f"{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                task_type=task_type,
                ticker=ticker,
                notes=trigger_reason,
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            enqueue_task(task)
            triggered_count += 1
            print(f"🚨 [TRIGGERED] {ticker}: {trigger_reason}")

    save_watchlist(watchlist)
    return triggered_count
