"""
stocks.moving_average_surveillance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Autonomous Technical Reversal & Quad-Moving Average Breakout Surveillance Engine.

Features:
- High-conviction Major Institutional MA Reclaim Filter (reclaiming 50D or 200D SMA).
- 0.5% Minimum Breakout Clearance Buffer (eliminates hovering noise and whipsaws).
- 14-Day Trailing Cooldown State Machine (prevents alert bombardment & duplicate alerts).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from stocks.models import AlertItem, TaskItem, WatchlistStock
from stocks.data_store import load_watchlist, load_alerts, add_alert, DATA_DIR
from stocks.queue_manager import enqueue_task
from stocks.tracker import fetch_all_chart_ranges_cached

REGIMES_FILE = DATA_DIR / "ma_regimes.json"
COOLDOWN_DAYS = 14


def load_ma_regimes() -> Dict[str, Any]:
    """Loads persistent moving average regime and cooldown state."""
    if not REGIMES_FILE.exists():
        return {}
    try:
        with open(REGIMES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_ma_regimes(regimes: Dict[str, Any]):
    """Persists moving average regime and cooldown state."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(REGIMES_FILE, "w", encoding="utf-8") as f:
            json.dump(regimes, f, indent=2)
    except Exception:
        pass


def compute_sma(prices: List[float], period: int) -> float:
    """Computes simple moving average for the given period."""
    if not prices:
        return 0.0
    n = min(period, len(prices))
    return sum(prices[-n:]) / n


def detect_quad_ma_reversal(ticker: str, points: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Analyzes historical daily candles to detect a High-Conviction Bullish Quad-MA Reversal.
    
    A stock qualifies if:
    1. Current price is ABOVE ALL 4 moving averages: 5D, 21D, 50D, and 200D SMAs with >= 0.5% clearance.
    2. In recent sessions (T-1 to T-3), price was trading BELOW a MAJOR institutional moving average
       (the 50-day SMA or 200-day SMA), representing a true regime breakout rather than a micro-wiggle.
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

    max_ma_curr = max(sma5_curr, sma21_curr, sma50_curr, sma200_curr)

    # Condition 1: Currently ABOVE ALL 4 Moving Averages with >= 0.5% clearance buffer
    if p_curr < max_ma_curr * 1.005:
        return None

    # Condition 2: Must be a MAJOR institutional reclaim (was below 50D SMA or 200D SMA in prior 3 sessions)
    was_below_major = (
        p_prev <= sma50_prev or p_prev <= sma200_prev or
        p_prev3 <= sma50_prev3 or p_prev3 <= sma200_prev3
    )

    if not was_below_major:
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
        reclaimed = ["50D SMA", "21D SMA"]

    # Metrics & clearance margins
    clearance_max_pct = ((p_curr - max_ma_curr) / max_ma_curr) * 100.0 if max_ma_curr > 0 else 0.0
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
        "clearance_max_pct": round(clearance_max_pct, 2),
        "clearance_200_pct": round(clearance_200_pct, 2),
        "clearance_50_pct": round(clearance_50_pct, 2),
        "clearance_21_pct": round(clearance_21_pct, 2),
        "clearance_5_pct": round(clearance_5_pct, 2),
        "vel_5d_pct": round(vel_5d_pct, 2)
    }


def check_moving_average_reversal_triggers(watchlist: Optional[Dict[str, WatchlistStock]] = None) -> int:
    """
    Autonomous Surveillance Check:
    Scans all watchlist stocks for Quad-MA Bullish Reversal Crossovers with 14-day Cooldown.
    Emits formal AlertItems only for fresh, high-conviction regime breakouts.
    """
    if watchlist is None:
        watchlist = load_watchlist()

    if not watchlist:
        return 0

    triggered_count = 0
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    existing_regimes = load_ma_regimes()
    existing_alerts = load_alerts()

    # Fast set of already alerted tickers in memory/history within cooldown
    cooldown_tickers = set()
    for tk, r_data in existing_regimes.items():
        last_dt_str = r_data.get("last_alert_timestamp") or r_data.get("last_alert_date", "")
        if last_dt_str:
            try:
                last_dt = datetime.fromisoformat(last_dt_str) if "T" in last_dt_str else datetime.strptime(last_dt_str[:10], "%Y-%m-%d")
                if (now - last_dt).total_seconds() < (COOLDOWN_DAYS * 86400):
                    cooldown_tickers.add(tk.upper())
            except Exception:
                pass

    for a in existing_alerts:
        if "Quad-MA" in a.title or "Reversal" in a.title:
            try:
                a_dt = datetime.strptime(a.timestamp[:10], "%Y-%m-%d")
                if (now - a_dt).total_seconds() < (COOLDOWN_DAYS * 86400):
                    cooldown_tickers.add(a.ticker.upper())
            except Exception:
                pass

    for ticker, stock in watchlist.items():
        ticker_clean = ticker.upper().strip()
        if ticker_clean in cooldown_tickers:
            continue

        current_price = stock.current_price or stock.baseline_price or 100.0

        try:
            chart_ranges = fetch_all_chart_ranges_cached(ticker_clean, current_price)
            daily_points = chart_ranges.get("1Y") or chart_ranges.get("MAX") or []
            
            reversal = detect_quad_ma_reversal(ticker_clean, daily_points)
            if not reversal:
                continue

            p_curr = reversal["price"]
            p_prev = reversal["prev_price"]
            reclaimed_str = reversal["reclaimed_str"]
            sma5 = reversal["sma5"]
            sma21 = reversal["sma21"]
            sma50 = reversal["sma50"]
            sma200 = reversal["sma200"]
            vel_5d = reversal["vel_5d_pct"]
            clearance_max = reversal["clearance_max_pct"]

            trigger_reason = (
                f"Technical Trend Reversal: Price (${p_curr:.2f}) has reclaimed {reclaimed_str} "
                f"and crossed UP ALL 4 Moving Averages (5D: ${sma5:.2f}, 21D: ${sma21:.2f}, "
                f"50D: ${sma50:.2f}, 200D: ${sma200:.2f}) with +{clearance_max:.1f}% clearance and {vel_5d:+.1f}% 5-day velocity."
            )
            what_before = f"Consolidating or trading below {reclaimed_str} (Previous close: ${p_prev:.2f})."
            what_now = (
                f"Major institutional regime flip confirmed: Cleared entire moving average stack (5D/21D/50D/200D). "
                f"Confirms bottoming structure, institutional accumulation, and technical alignment with fundamental margin of safety."
            )

            print(f"🚨 [MA REVERSAL BREAKOUT] {ticker_clean}: Bullish Reversal! Price (${p_curr:.2f}) crossed UP all 4 moving averages ({reclaimed_str}) with +{clearance_max:.1f}% clearance!")

            # Deterministic fingerprint & alert ID
            year_week = now.strftime("%Y_W%W")
            alert = AlertItem(
                id=f"ma_reversal_{ticker_clean}_{year_week}",
                ticker=ticker_clean,
                timestamp=now.strftime("%Y-%m-%d %H:%M"),
                title=f"🚀 Quad-MA Bullish Reversal: {ticker_clean} Crossed UP All 4 Moving Averages",
                severity="Breakout",
                labels=["Technical Reversal", "Quad-MA Breakout", "Major Reclaim"],
                action_signal="BUY",
                trigger_reason=trigger_reason,
                what_was_before=what_before,
                what_changes_now=what_now,
                price_at_alert=p_curr,
                price_change_pct=round(((p_curr - p_prev) / p_prev) * 100.0, 2) if p_prev > 0 else 0.0,
                report_url=f"reports/{ticker_clean}.html"
            )

            add_alert(alert)
            cooldown_tickers.add(ticker_clean)

            # Update regime state machine
            existing_regimes[ticker_clean] = {
                "last_alert_timestamp": now.isoformat(),
                "last_alert_date": today_str,
                "last_alert_price": p_curr,
                "last_reclaimed": reversal["reclaimed"]
            }
            save_ma_regimes(existing_regimes)

            enqueue_task(TaskItem(
                id=f"trigger_ma_{ticker_clean}_{year_week}",
                task_type="MA_REVERSAL_TRIGGER",
                ticker=ticker_clean,
                notes=trigger_reason
            ))

            triggered_count += 1

        except Exception:
            pass

    return triggered_count


def get_all_ma_reversals(watchlist: Optional[Dict[str, WatchlistStock]] = None) -> List[Dict[str, Any]]:
    """Scans and returns all watchlist stocks currently in a high-conviction Quad-MA reversal breakout state."""
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


def get_recent_quad_ma_status(ticker: str, current_price: float = 0.0, max_days: int = 21) -> Optional[Dict[str, Any]]:
    """
    Checks if a stock has completed a Quad-MA cross UP within the last `max_days` sessions (default 21).
    Returns metadata (days_ago, clearance_pct) if currently above all 4 MAs, else None.
    """
    clean_t = ticker.upper().strip()
    try:
        chart_ranges = fetch_all_chart_ranges_cached(clean_t, current_price or 100.0)
        points = chart_ranges.get("1Y") or chart_ranges.get("MAX") or []
        if not points or len(points) < 50:
            return None
            
        prices = [float(p["price"]) for p in points if p.get("price") and float(p["price"]) > 0]
        if len(prices) < 50:
            return None
            
        p_curr = prices[-1]
        sma5_curr = compute_sma(prices, 5)
        sma21_curr = compute_sma(prices, 21)
        sma50_curr = compute_sma(prices, 50)
        n200 = min(200, len(prices))
        sma200_curr = compute_sma(prices, n200)
        
        max_ma = max(sma5_curr, sma21_curr, sma50_curr, sma200_curr)
        # Price must currently be above all 4 moving averages
        if p_curr < max_ma * 1.002:
            return None
            
        lookback = min(max_days, len(prices) - 50)
        found_cross = None
        for offset in range(1, lookback + 1):
            sub_prices = prices[:-offset] if offset > 0 else prices
            p_then = sub_prices[-1]
            s50 = compute_sma(sub_prices, 50)
            n_200 = min(200, len(sub_prices))
            s200 = compute_sma(sub_prices, n_200)
            s21 = compute_sma(sub_prices, 21)
            s5 = compute_sma(sub_prices, 5)
            
            if p_then <= s50 or p_then <= s200 or p_then <= s21 or p_then <= s5:
                found_cross = offset
                break
                
        if found_cross is not None:
            clearance_pct = round(((p_curr - max_ma) / max_ma) * 100.0, 1)
            return {
                "is_active": True,
                "ticker": clean_t,
                "days_ago": found_cross,
                "clearance_pct": clearance_pct,
                "current_price": p_curr,
                "sma5": round(sma5_curr, 2),
                "sma21": round(sma21_curr, 2),
                "sma50": round(sma50_curr, 2),
                "sma200": round(sma200_curr, 2)
            }
    except Exception:
        pass
    return None

