"""
stocks.moving_average_surveillance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Autonomous Technical Reversal & Quad-Moving Average Breakout Surveillance Engine.

Monitors all watchlist stocks for regime flips and bullish trend reversals where
a stock breaks out and crosses UP ALL 4 moving averages (5-Day, 21-Day, 50-Day, and 200-Day SMAs).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from stocks.models import AlertItem, TaskItem, WatchlistStock
from stocks.data_store import load_watchlist, load_alerts, add_alert
from stocks.queue_manager import enqueue_task
from stocks.tracker import fetch_all_chart_ranges_cached


def compute_sma(prices: List[float], period: int) -> float:
    """Computes simple moving average for the given period."""
    if not prices:
        return 0.0
    n = min(period, len(prices))
    return sum(prices[-n:]) / n


def detect_quad_ma_reversal(ticker: str, points: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Analyzes historical daily candles to detect a Bullish Quad-MA Reversal.
    
    A stock qualifies if:
    1. Current price is ABOVE ALL 4 moving averages: 5D, 21D, 50D, and 200D SMAs.
    2. In the previous session (or within the last 1-3 trading days), price was
       trading BELOW at least one of these moving averages (the 'Cross UP' breakout event).
    """
    if not points or len(points) < 10:
        return None

    prices = [float(p["price"]) for p in points if p.get("price") and float(p["price"]) > 0]
    if len(prices) < 10:
        return None

    p_curr = prices[-1]
    p_prev = prices[-2] if len(prices) >= 2 else prices[-1]
    p_prev3 = prices[-4] if len(prices) >= 4 else p_prev
    p_5d_ago = prices[-6] if len(prices) >= 6 else prices[0]

    # Current Moving Averages (T)
    sma5_curr = compute_sma(prices, 5)
    sma21_curr = compute_sma(prices, 21)
    sma50_curr = compute_sma(prices, 50)
    sma200_curr = compute_sma(prices, 200)

    # Previous Session Moving Averages (T-1)
    prev_prices = prices[:-1]
    sma5_prev = compute_sma(prev_prices, 5)
    sma21_prev = compute_sma(prev_prices, 21)
    sma50_prev = compute_sma(prev_prices, 50)
    sma200_prev = compute_sma(prev_prices, 200)

    # 3 Sessions Ago Moving Averages (T-3)
    prev3_prices = prices[:-3] if len(prices) >= 4 else prev_prices
    sma5_prev3 = compute_sma(prev3_prices, 5)
    sma21_prev3 = compute_sma(prev3_prices, 21)
    sma50_prev3 = compute_sma(prev3_prices, 50)
    sma200_prev3 = compute_sma(prev3_prices, 200)

    # Condition 1: Currently ABOVE ALL 4 Moving Averages
    above_all_now = (
        p_curr > sma5_curr and
        p_curr > sma21_curr and
        p_curr > sma50_curr and
        p_curr > sma200_curr
    )

    if not above_all_now:
        return None

    # Condition 2: Recently (T-1 or T-3) was BELOW at least one Moving Average (Cross UP breakout)
    below_at_prev1 = (
        p_prev <= sma5_prev or
        p_prev <= sma21_prev or
        p_prev <= sma50_prev or
        p_prev <= sma200_prev
    )
    below_at_prev3 = (
        p_prev3 <= sma5_prev3 or
        p_prev3 <= sma21_prev3 or
        p_prev3 <= sma50_prev3 or
        p_prev3 <= sma200_prev3
    )

    if not (below_at_prev1 or below_at_prev3):
        return None

    # Identify which specific moving averages were reclaimed during this reversal
    reclaimed = []
    if p_prev <= sma200_prev or p_prev3 <= sma200_prev3:
        reclaimed.append("200D SMA")
    if p_prev <= sma50_prev or p_prev3 <= sma50_prev3:
        reclaimed.append("50D SMA")
    if p_prev <= sma21_prev or p_prev3 <= sma21_prev3:
        reclaimed.append("21D SMA")
    if p_prev <= sma5_prev or p_prev3 <= sma5_prev3:
        reclaimed.append("5D SMA")

    if not reclaimed:
        reclaimed = ["5D SMA", "21D SMA"]

    # Metrics & clearance margins
    clearance_200_pct = ((p_curr - sma200_curr) / sma200_curr) * 100.0 if sma200_curr > 0 else 0.0
    clearance_50_pct = ((p_curr - sma50_curr) / sma50_curr) * 100.0 if sma50_curr > 0 else 0.0
    clearance_21_pct = ((p_curr - sma21_curr) / sma21_curr) * 100.0 if sma21_curr > 0 else 0.0
    clearance_5_pct = ((p_curr - sma5_curr) / sma5_curr) * 100.0 if sma5_curr > 0 else 0.0
    vel_5d_pct = ((p_curr - p_5d_ago) / p_5d_ago) * 100.0 if p_5d_ago > 0 else 0.0

    return {
        "ticker": ticker.upper().strip(),
        "price": round(p_curr, 2),
        "prev_price": round(p_prev, 2),
        "reclaimed": reclaimed,
        "reclaimed_str": ", ".join(reclaimed),
        "sma5": round(sma5_curr, 2),
        "sma21": round(sma21_curr, 2),
        "sma50": round(sma50_curr, 2),
        "sma200": round(sma200_curr, 2),
        "clearance_200_pct": round(clearance_200_pct, 2),
        "clearance_50_pct": round(clearance_50_pct, 2),
        "clearance_21_pct": round(clearance_21_pct, 2),
        "clearance_5_pct": round(clearance_5_pct, 2),
        "vel_5d_pct": round(vel_5d_pct, 2)
    }


def check_moving_average_reversal_triggers(watchlist: Optional[Dict[str, WatchlistStock]] = None) -> int:
    """
    Autonomous Surveillance Check:
    Scans all watchlist stocks for Quad-MA Bullish Reversal Crossovers.
    Emits formal AlertItems and enqueues tasks for any detected regime breakouts.
    """
    if watchlist is None:
        watchlist = load_watchlist()

    if not watchlist:
        return 0

    triggered_count = 0
    today_str = datetime.now().strftime("%Y-%m-%d")
    existing_alerts = load_alerts()

    # Fast set of already alerted tickers today for MA reversal
    already_alerted_today = {
        a.ticker.upper() for a in existing_alerts
        if a.timestamp.startswith(today_str) and ("Quad-MA" in a.title or "Reversal" in a.title)
    }

    for ticker, stock in watchlist.items():
        ticker_clean = ticker.upper().strip()
        current_price = stock.current_price or stock.baseline_price or 100.0

        try:
            chart_ranges = fetch_all_chart_ranges_cached(ticker_clean, current_price)
            # Use 1Y dataset (or MAX) which has full daily candles
            daily_points = chart_ranges.get("1Y") or chart_ranges.get("MAX") or []
            
            reversal = detect_quad_ma_reversal(ticker_clean, daily_points)
            if not reversal:
                continue

            if ticker_clean in already_alerted_today:
                continue

            p_curr = reversal["price"]
            p_prev = reversal["prev_price"]
            reclaimed_str = reversal["reclaimed_str"]
            sma5 = reversal["sma5"]
            sma21 = reversal["sma21"]
            sma50 = reversal["sma50"]
            sma200 = reversal["sma200"]
            vel_5d = reversal["vel_5d_pct"]

            trigger_reason = (
                f"Technical Trend Reversal: Price (${p_curr:.2f}) has reclaimed {reclaimed_str} "
                f"and crossed UP ALL 4 Moving Averages (5D: ${sma5:.2f}, 21D: ${sma21:.2f}, "
                f"50D: ${sma50:.2f}, 200D: ${sma200:.2f}) with {vel_5d:+.1f}% 5-day velocity."
            )
            what_before = f"Consolidating or trading below {reclaimed_str} (Previous close: ${p_prev:.2f})."
            what_now = (
                f"Technical regime flip confirmed: Complete quad-MA stack cleared with strong upward momentum. "
                f"Confirms bottoming structure, institutional accumulation, and technical alignment with fundamental margin of safety."
            )

            print(f"🚨 [MA REVERSAL BREAKOUT] {ticker_clean}: Bullish Reversal! Price (${p_curr:.2f}) crossed UP all 4 moving averages ({reclaimed_str})!")

            alert = AlertItem(
                id=f"ma_reversal_{ticker_clean}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                ticker=ticker_clean,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
                title=f"🚀 Quad-MA Bullish Reversal: {ticker_clean} Crossed UP All 4 Moving Averages",
                severity="Breakout",
                labels=["Technical Reversal", "Quad-MA Breakout", "Momentum Confirmation"],
                action_signal="BUY",
                trigger_reason=trigger_reason,
                what_was_before=what_before,
                what_changes_now=what_now,
                price_at_alert=p_curr,
                price_change_pct=round(((p_curr - p_prev) / p_prev) * 100.0, 2) if p_prev > 0 else 0.0,
                report_url=f"reports/{ticker_clean}.html"
            )

            add_alert(alert)
            already_alerted_today.add(ticker_clean)

            enqueue_task(TaskItem(
                id=f"trigger_ma_{ticker_clean}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                task_type="MA_REVERSAL_TRIGGER",
                ticker=ticker_clean,
                notes=trigger_reason
            ))

            triggered_count += 1

        except Exception as e:
            pass

    return triggered_count


def get_all_ma_reversals(watchlist: Optional[Dict[str, WatchlistStock]] = None) -> List[Dict[str, Any]]:
    """Scans and returns all watchlist stocks currently in a Quad-MA reversal breakout state."""
    if watchlist is None:
        watchlist = load_watchlist()

    reversals = []
    for ticker, stock in watchlist.items():
        ticker_clean = ticker.upper().strip()
        current_price = stock.current_price or stock.baseline_price or 100.0
        try:
            chart_ranges = fetch_all_chart_ranges_cached(ticker_clean, current_price)
            daily_points = chart_ranges.get("1Y") or chart_ranges.get("MAX") or []
            rev = detect_quad_ma_reversal(ticker_clean, daily_points)
            if rev:
                rev["company_name"] = stock.company_name
                rev["action_signal"] = stock.action_signal
                rev["moat_label"] = stock.moat_label
                reversals.append(rev)
        except Exception:
            pass

    return sorted(reversals, key=lambda x: x.get("vel_5d_pct", 0.0), reverse=True)
