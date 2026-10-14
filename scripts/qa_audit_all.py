"""Publish gate: re-audit the latest stored thesis of every ticker with the strict QA checks.

Exit code 1 if any ticker's live thesis was not produced by the QA-gated pipeline (qa_passed != True)
or fails any deterministic check. Run before every push.

Usage: PYTHONPATH=. .venv/bin/python scripts/qa_audit_all.py [--tickers T1 T2]
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _num(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    c = re.sub(r"[^\d.\-]", "", str(s))
    try:
        return float(c) if c not in ("", "-", ".") else None
    except ValueError:
        return None


def audit_version(v: dict) -> list:
    from stocks.thesis_qa import validate_thesis_output, validate_rendered_html, implied_irr_pct
    issues = []
    if v.get("qa_passed") is not True:
        issues.append("Live version was not produced by the strict QA-gated pipeline.")
    price = _num(v.get("price_at_version")) or 0.0
    fv = _num(v.get("expected_val")) or _num(v.get("fair_value_estimate"))
    info = {
        "market_pricing_in": v.get("market_pricing_in"),
        "why_it_might_be_right": v.get("why_it_might_be_right"),
        "how_things_are_going_now": v.get("how_things_are_going_now"),
        "what_if_it_keeps_going_that_way": v.get("what_if_it_keeps_going_that_way"),
        "fair_value_target": fv,
        "bear_floor_target": _num(v.get("bear_target")),
        "bull_upside_target": _num(v.get("bull_target")),
        "irr_3y_pct": implied_irr_pct(fv or 0, price) if fv else None,
        "normalized_oe_per_share": v.get("owner_earnings_per_share"),
        "diluted_shares_mil": v.get("diluted_shares_mil"),
        "p_oe": v.get("p_oe"),
        "net_cash_per_share": v.get("net_cash_per_share"),
    }
    issues += validate_thesis_output(info, price)
    issues += validate_rendered_html(v.get("full_html_content") or "")
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="*", default=[])
    args = ap.parse_args()
    files = sorted((ROOT / "data" / "theses").glob("*.json"))
    if args.tickers:
        wanted = {t.upper() for t in args.tickers}
        files = [f for f in files if f.stem.upper() in wanted]
    failures = {}
    for f in files:
        data = json.loads(f.read_text())
        if not data:
            failures[f.stem] = ["empty history"]
            continue
        iss = audit_version(data[-1])
        if iss:
            failures[f.stem] = iss
    print(f"QA audit: {len(files) - len(failures)}/{len(files)} passed")
    for t, iss in sorted(failures.items()):
        print(f"  ✗ {t}: {iss[:4]}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
