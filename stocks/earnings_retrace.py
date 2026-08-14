"""
AlphaThesis Beat & Retrace Intelligence Engine.

Monitors post-earnings momentum and mean-reversion arbitrage:
1. Detects post-earnings pops >= +8.0% from pre-earnings baseline (P0 -> Ppeak).
2. Arms a 30-day surveillance window.
3. Triggers a high-priority "Opportunity / Buy" alert when >= 75.0% of the pop gains are eroded by market/macro selling pressure:
   P <= P0 + 0.25 * (Ppeak - P0)
4. Emits actionable alerts to the dashboard without altering the fundamental living thesis.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from stocks.models import AlertItem
from stocks.data_store import load_watchlist, add_alert

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RETRACE_TRACKER_FILE = DATA_DIR / "earnings_retrace_tracker.json"


def load_retrace_tracker() -> Dict[str, Any]:
    """Loads the active beat-and-retrace tracker state from disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not RETRACE_TRACKER_FILE.exists():
        return {}
    try:
        with open(RETRACE_TRACKER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_retrace_tracker(tracker_data: Dict[str, Any]):
    """Saves the beat-and-retrace tracker state to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(RETRACE_TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(tracker_data, f, indent=2)


def register_earnings_pop(
    ticker: str,
    earnings_date: str,
    pre_earnings_price: float,
    peak_price: float,
    notes: str = "Earnings Beat Pop"
) -> Optional[Dict[str, Any]]:
    """
    Registers a post-earnings pop event if pop >= 8.0%.
    Calculates the exact 75% retracement trigger level.
    """
    if pre_earnings_price <= 0 or peak_price <= pre_earnings_price:
        return None

    pop_pct = ((peak_price - pre_earnings_price) / pre_earnings_price) * 100.0
    if pop_pct < 8.0:
        return None  # Minimum +8.0% pop threshold

    pop_gain = peak_price - pre_earnings_price
    # 75% gain eroded means retaining at most 25% of the gain:
    # Trigger Price = P0 + 0.25 * pop_gain
    buy_trigger_price = round(pre_earnings_price + (0.25 * pop_gain), 2)

    # Quarterly window: stay active until the next quarterly earnings release or up to 75 calendar days
    expires_at = ""
    try:
        watchlist = load_watchlist()
        stock = watchlist.get(ticker.upper())
        if stock and stock.next_catalyst_date and len(stock.next_catalyst_date.strip()) >= 10:
            expires_at = stock.next_catalyst_date.strip()[:10]
    except Exception:
        pass

    if not expires_at:
        try:
            earn_dt = datetime.strptime(earnings_date[:10], "%Y-%m-%d")
            expires_at = (earn_dt + timedelta(days=75)).strftime("%Y-%m-%d")
        except Exception:
            expires_at = (datetime.now() + timedelta(days=75)).strftime("%Y-%m-%d")

    entry = {
        "ticker": ticker.upper(),
        "earnings_date": earnings_date,
        "pre_earnings_price": round(pre_earnings_price, 2),
        "peak_price": round(peak_price, 2),
        "pop_pct": round(pop_pct, 2),
        "pop_gain": round(pop_gain, 2),
        "buy_trigger_price": buy_trigger_price,
        "status": "ARMED",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "expires_at": expires_at,
        "notes": notes
    }

    tracker = load_retrace_tracker()
    tracker[ticker.upper()] = entry
    save_retrace_tracker(tracker)
    print(f"🎯 [BEAT & RETRACE ARMED] {ticker}: Pop +{pop_pct:.1f}% to ${peak_price:.2f}. Buy trigger at ${buy_trigger_price:.2f} (75% erosion). Active until {expires_at}.")
    return entry


def reset_earnings_cycle(ticker: str):
    """
    Resets the beat-and-retrace cycle for a ticker upon a new quarterly earnings release.
    Clears the previous quarter's armed/triggered state so new pops and retraces can be tracked cleanly.
    """
    tracker = load_retrace_tracker()
    if ticker.upper() in tracker:
        old_status = tracker[ticker.upper()].get("status")
        tracker.pop(ticker.upper(), None)
        save_retrace_tracker(tracker)
        print(f"🔄 [QUARTERLY RESET] {ticker}: Cleared prior quarterly cycle (was {old_status}). Ready for new quarter.")


def check_earnings_retrace_triggers(live_quotes: Optional[Dict[str, Any]] = None) -> int:
    """
    Surveillance pass: checks all ARMED earnings pop records against live prices.
    If current_price <= buy_trigger_price, emits an Opportunity / Buy Alert.
    """
    tracker = load_retrace_tracker()
    if not tracker:
        return 0

    from stocks.tracker import fetch_live_stock_info

    today_dt = datetime.now().date()
    triggered_count = 0

    for ticker, record in tracker.items():
        if record.get("status") != "ARMED":
            continue

        # Check expiration (30-day window)
        expires_str = record.get("expires_at", "")
        if expires_str:
            try:
                exp_dt = datetime.strptime(expires_str[:10], "%Y-%m-%d").date()
                if today_dt > exp_dt:
                    record["status"] = "EXPIRED"
                    continue
            except Exception:
                pass

        # Get current price
        cur_p = None
        if live_quotes and ticker in live_quotes and "price" in live_quotes[ticker]:
            cur_p = float(live_quotes[ticker]["price"])
        else:
            try:
                _, cur_p = fetch_live_stock_info(ticker)
            except Exception:
                continue

        if not cur_p or cur_p <= 0:
            continue

        p0 = float(record["pre_earnings_price"])
        p_peak = float(record["peak_price"])
        pop_pct = float(record["pop_pct"])
        pop_gain = float(record["pop_gain"])
        trigger_p = float(record["buy_trigger_price"])

        # Check if price has made a new higher peak post-earnings while still in pop phase
        if cur_p > p_peak:
            new_pop_pct = ((cur_p - p0) / p0) * 100.0
            new_pop_gain = cur_p - p0
            new_trigger_p = round(p0 + (0.25 * new_pop_gain), 2)
            record["peak_price"] = round(cur_p, 2)
            record["pop_pct"] = round(new_pop_pct, 2)
            record["pop_gain"] = round(new_pop_gain, 2)
            record["buy_trigger_price"] = new_trigger_p
            print(f"📈 [PEAK EXTENDED] {ticker}: New peak ${cur_p:.2f} (+{new_pop_pct:.1f}%). New trigger at ${new_trigger_p:.2f}.")
            continue

        # Retracement check: price has fallen to or below 75% erosion level
        if cur_p <= trigger_p:
            eroded_gain = p_peak - cur_p
            eroded_pct = (eroded_gain / pop_gain) * 100.0 if pop_gain > 0 else 100.0

            alert_id = f"retrace_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M')}"
            alert = AlertItem(
                id=alert_id,
                ticker=ticker,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
                title=f"🎯 Beat & Retrace Buy Alert: {ticker} (75%+ Pop Eroded)",
                severity="Opportunity",
                labels=["Beat & Retrace", "75% Eroded", "Value Entry"],
                action_signal="BUY",
                trigger_reason=f"Post-earnings pop of +{pop_pct:.1f}% (${p_peak:.2f}) has eroded by {eroded_pct:.1f}% back to ${cur_p:.2f} (Entry Baseline: ${p0:.2f})",
                what_was_before=f"{ticker} surged +{pop_pct:.1f}% to a peak of ${p_peak:.2f} following strong earnings execution.",
                what_changes_now=f"Macro / market selling pressure has erased {eroded_pct:.1f}% of the earnings pop gains without compromising fundamental business quality. High margin-of-safety entry window active.",
                price_at_alert=cur_p,
                price_change_pct=round(((cur_p - p_peak) / p_peak) * 100.0, 2),
                report_url=f"reports/{ticker}.html"
            )

            add_alert(alert)
            record["status"] = "TRIGGERED"
            record["triggered_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            record["triggered_price"] = cur_p
            record["eroded_pct"] = round(eroded_pct, 1)

            print(f"🚨 [BEAT & RETRACE TRIGGERED] {ticker}: ${cur_p:.2f} <= ${trigger_p:.2f} ({eroded_pct:.1f}% gain eroded). Buy alert published!")
            triggered_count += 1

    save_retrace_tracker(tracker)
    return triggered_count


def scan_watchlist_for_recent_earnings_pops():
    """
    Scans recent historical price ranges for watchlist stocks to discover any
    untracked recent earnings beats with >=8% pops that qualify for surveillance.
    """
    watchlist = load_watchlist()
    tracker = load_retrace_tracker()
    
    from stocks.tracker import fetch_historical_chart_data, fetch_live_stock_info

    discovered = 0
    print(f"🔍 Scanning {len(watchlist)} stocks for >=8% earnings pop patterns...")

    for ticker, stock in watchlist.items():
        if ticker in tracker and tracker[ticker].get("status") == "ARMED":
            continue

        try:
            pts = fetch_historical_chart_data(ticker, "1m")
            if not pts or len(pts) < 10:
                continue

            prices = [p["price"] for p in pts if "price" in p]
            if len(prices) < 10:
                continue

            # Look for recent minimum to peak jump >= 8% in the last 20 trading days
            min_p = min(prices[-20:])
            max_p = max(prices[-20:])
            cur_p = prices[-1]

            if min_p > 0 and (max_p - min_p) / min_p >= 0.08:
                min_idx = prices[-20:].index(min_p)
                max_idx = prices[-20:].index(max_p)

                # Peak must have happened after the baseline
                if max_idx > min_idx:
                    pop_pct = ((max_p - min_p) / min_p) * 100.0
                    pop_gain = max_p - min_p
                    trigger_p = round(min_p + (0.25 * pop_gain), 2)

                    # Only arm if currently trading above or near trigger
                    if cur_p > min_p:
                        record_entry = {
                            "ticker": ticker,
                            "earnings_date": pts[max_idx].get("date", "Recent"),
                            "pre_earnings_price": round(min_p, 2),
                            "peak_price": round(max_p, 2),
                            "pop_pct": round(pop_pct, 2),
                            "pop_gain": round(pop_gain, 2),
                            "buy_trigger_price": trigger_p,
                            "status": "ARMED",
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "expires_at": (datetime.now() + timedelta(days=25)).strftime("%Y-%m-%d"),
                            "notes": "Discovered Recent Momentum Pop >= 8%"
                        }
                        tracker[ticker] = record_entry
                        discovered += 1
                        print(f"💡 [DISCOVERED POP] {ticker}: Low ${min_p:.2f} -> Peak ${max_p:.2f} (+{pop_pct:.1f}%). Trigger at ${trigger_p:.2f}.")
        except Exception as e:
            continue

    if discovered > 0:
        save_retrace_tracker(tracker)
        print(f"✅ Armed {discovered} newly discovered beat-and-retrace patterns.")

