"""Strict deterministic QA for underwritten theses.

Every thesis must pass ALL checks here before it can be saved. Nothing is "auto-healed"
by inventing numbers: failures are fed back to the model for a repair pass, and if the
thesis still fails after the retry budget, it is rejected and the previous version stays live.

Lessons encoded here (each one came from a real defect we shipped):
- WMT/NVR: synthetic "$1,000.0M" revenue fallbacks -> inputs must be real, never defaulted.
- AML: GBX pence treated as USD -> price × shares must reconcile with reported market cap.
- NFLX: pre-split share count after a 10-for-1 split -> share basis cross-checked independently.
- MELI: fintech deposit inflows counted as Owner Earnings -> OCF distortion guard + fair value band.
- WBD/KHC/VZ: empty prose sections -> minimum section length + numbered step structure.
- AMD/BMBL: prose numbers drifting from structured fields -> prose must cite the exact verified figures.
- Signed-dollar / parenthetical "$(0.30)" LaTeX corruption -> rendered HTML must contain no \\( or placeholders.
- Hand-edited fair values -> step-6 arithmetic (OE × multiple + net cash = FV) is recomputed and must match.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


class ThesisQAError(Exception):
    """Raised when a thesis cannot pass QA within its retry budget."""

    def __init__(self, message: str, issues: Optional[List[str]] = None):
        super().__init__(message)
        self.issues = issues or []

    def __str__(self) -> str:
        base = super().__str__()
        if self.issues:
            return base + " | " + "; ".join(self.issues[:8])
        return base


REQUIRED_INPUT_FIELDS = [
    "market_cap_mil", "diluted_shares_mil", "trailing_revenue_ttm_mil",
    "operating_cash_flow_ttm_mil", "net_income_ttm_mil", "dna_ttm_mil",
    "capex_ttm_mil", "sbc_ttm_mil", "cash_mil", "debt_mil", "equity_mil",
]

BANNED_FALLBACK_PHRASES = [
    "active commercial volume units",
    "unit monetization and take-rate yield",
    "$1,000.0m in annualized run-rate",
]

MONEY_RE = re.compile(
    r"(?P<sign>[-+−])?\s?\$\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<mag>billion|million|trillion|[BMKT](?![a-z]))?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _num(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    cleaned = re.sub(r"[^\d.\-]", "", str(val))
    try:
        return float(cleaned) if cleaned not in ("", "-", ".", "-.") else None
    except ValueError:
        return None


def money_values(text: str, per_share_only: bool = False) -> List[float]:
    """Extracts signed dollar figures from prose, expressed in raw dollars (B/M/K are not scaled)."""
    vals = []
    for m in MONEY_RE.finditer(text or ""):
        if per_share_only and m.group("mag"):
            continue
        v = float(m.group("num").replace(",", ""))
        sign = m.group("sign")
        if sign in ("-", "−"):
            v = -v
        vals.append(v)
    return vals


def _close(a: float, b: float, rel: float, abs_tol: float = 0.0) -> bool:
    return abs(a - b) <= max(abs(b) * rel, abs_tol)


def _any_close(values: List[float], target: float, rel: float, abs_tol: float = 0.011) -> bool:
    return any(_close(abs(v), abs(target), rel, abs_tol) for v in values)


def _numbered_steps(text: str) -> Dict[int, str]:
    """Splits a numbered-step section into {step_number: step_text}."""
    steps: Dict[int, str] = {}
    parts = re.split(r"(?:^|\n)\s*(?:\*\*)?(\d)[\.\)]\s+", text or "")
    # parts = [preamble, n1, body1, n2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        try:
            steps[int(parts[i])] = parts[i + 1]
        except ValueError:
            continue
    return steps


# ---------------------------------------------------------------------------
# Gate 1: financial inputs (before any prose is drafted)
# ---------------------------------------------------------------------------

def validate_financial_inputs(audit: Dict[str, Any], price: float) -> List[str]:
    issues: List[str] = []
    if not audit:
        return ["Extraction returned no parseable JSON."]
    if not price or price <= 0:
        return [f"Live price is invalid (${price})."]

    for f in REQUIRED_INPUT_FIELDS:
        if _num(audit.get(f)) is None:
            issues.append(f"Required field '{f}' is missing/null — find it in the latest filing.")
    if issues:
        return issues

    mcap = _num(audit["market_cap_mil"])
    shares = _num(audit["diluted_shares_mil"])
    rev = _num(audit["trailing_revenue_ttm_mil"])
    ocf = _num(audit["operating_cash_flow_ttm_mil"])
    sbc = _num(audit["sbc_ttm_mil"])
    cash = _num(audit["cash_mil"])
    debt = _num(audit["debt_mil"])

    if shares <= 0:
        issues.append("diluted_shares_mil must be > 0.")
    if mcap <= 0:
        issues.append("market_cap_mil must be > 0.")
    if rev < 0:
        issues.append("trailing_revenue_ttm_mil cannot be negative.")
    if cash < 0 or debt < 0 or sbc < 0:
        issues.append("cash_mil, debt_mil and sbc_ttm_mil must be non-negative.")
    if issues:
        return issues

    implied = price * shares
    if not _close(implied, mcap, 0.20):
        issues.append(
            f"Share basis mismatch: price ${price:.2f} × {shares:,.1f}M shares = ${implied:,.0f}M, "
            f"but market_cap_mil = ${mcap:,.0f}M (>20% apart). Check ADR ratio, post-split share count, "
            f"or pence/foreign-currency quoting, then report shares on the same basis as the USD price."
        )
    if rev == 0 and mcap > 20000:
        issues.append("Revenue reported as $0 for a >$20B company — almost certainly an extraction error.")
    if rev > 0:
        if ocf > rev * 3.0:
            issues.append(f"OCF (${ocf:,.0f}M) exceeds 300% of revenue (${rev:,.0f}M) — units/currency likely wrong.")
        if rev >= 300 and sbc > rev * 0.6:
            issues.append(f"SBC (${sbc:,.0f}M) exceeds 60% of revenue — units likely wrong.")
    lq = _num(audit.get("latest_quarter_revenue_mil"))
    if lq and rev > 0 and not (0.10 * rev <= lq <= 1.02 * rev):
        issues.append(
            f"Latest quarter revenue (${lq:,.0f}M) is inconsistent with TTM revenue (${rev:,.0f}M); "
            f"a single quarter cannot exceed TTM or be under 10% of it."
        )
    return issues


_SEC_TICKER_MAP: Optional[Dict[str, str]] = None
_SEC_FACTS_CACHE: Dict[str, str] = {}


def fetch_sec_edgar_summary(ticker: str) -> str:
    """Fetches authoritative recent 10-K/10-Q/20-F XBRL line items directly from SEC EDGAR (data.sec.gov)."""
    global _SEC_TICKER_MAP
    t_key = ticker.upper().strip()
    if t_key in _SEC_FACTS_CACHE:
        return _SEC_FACTS_CACHE[t_key]
    try:
        import requests
        headers = {"User-Agent": "StocksPortfolioAudit research@example.com"}
        if _SEC_TICKER_MAP is None:
            r_map = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=10)
            if r_map.status_code == 200:
                raw_map = r_map.json()
                _SEC_TICKER_MAP = {v["ticker"].upper(): f"{int(v['cik_str']):010d}" for v in raw_map.values()}
                _SEC_TICKER_MAP.setdefault("SQ", "0001512673")
            else:
                _SEC_TICKER_MAP = {"SQ": "0001512673"}
        cik = _SEC_TICKER_MAP.get(t_key) or _SEC_TICKER_MAP.get(t_key.replace(".", "-"))
        if not cik:
            _SEC_FACTS_CACHE[t_key] = ""
            return ""
        r_facts = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", headers=headers, timeout=12)
        if r_facts.status_code != 200:
            _SEC_FACTS_CACHE[t_key] = ""
            return ""
        data = r_facts.json().get("facts", {})
        concepts = [
            ("Revenue", [
                "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenuesNetOfInterestExpense", "HealthCareOrganizationRevenue", "Revenue",
            ]),
            ("GrossProfit", ["GrossProfit"]),
            ("NetIncome", ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"]),
            ("OperatingCashFlow", ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"]),
            ("D&A", [
                "DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                "Depreciation", "AmortizationOfIntangibleAssets",
            ]),
            ("CapEx", [
                "PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
                "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
            ]),
            ("SBC", [
                "ShareBasedCompensation", "AllocatedShareBasedCompensationExpense",
                "ExpenseFromShareBasedPaymentTransactions",
            ]),
            ("Cash&STInvestments", [
                "CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsAndShortTermInvestments",
                "MarketableSecuritiesCurrent", "ShortTermInvestments", "CashAndCashEquivalents",
            ]),
            ("Debt", [
                "LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtCurrent", "DebtCurrent",
                "ShortTermBorrowings", "LongTermDebtAndCapitalLeaseObligations",
            ]),
            ("Equity", [
                "StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                "Equity",
            ]),
            ("DilutedShares", [
                "WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding",
                "EntityCommonStockSharesOutstanding",
            ]),
        ]
        lines = [f"OFFICIAL SEC EDGAR XBRL FACTS FOR {t_key} (CIK {cik}):"]
        for label, tags in concepts:
            for ns in ("us-gaap", "ifrs-full", "dei"):
                ns_dict = data.get(ns, {})
                for tag in tags:
                    if tag not in ns_dict:
                        continue
                    units = ns_dict[tag].get("units", {})
                    for u_name, entries in units.items():
                        valid = [
                            e for e in entries
                            if e.get("form") in ("10-K", "10-Q", "20-F", "40-F") and e.get("val") is not None
                        ]
                        if not valid:
                            continue
                        recent = sorted(valid, key=lambda x: (x.get("end", ""), x.get("filed", "")))[-5:]
                        fmt_items = []
                        for r in recent:
                            val = float(r["val"])
                            fx_note = (
                                f" [FOREIGN CURRENCY {u_name} — CONVERT TO USD!]"
                                if u_name.upper() not in ("USD", "SHARES", "PURE", "USD/SHARES")
                                else ""
                            )
                            val_str = f"{val / 1e6:,.2f}M {u_name}{fx_note}" if abs(val) >= 1e5 else f"{val:,.2f} {u_name}{fx_note}"
                            span = f"{r.get('start', '')}..{r.get('end', '')}" if r.get("start") else f"as of {r.get('end', '')}"
                            fmt_items.append(f"[{r.get('form')} {r.get('fp', '')} {span}: {val_str}]")
                        lines.append(f"- {label} ({tag}): " + "; ".join(fmt_items))
        out = "\n".join(lines) if len(lines) > 1 else ""
        _SEC_FACTS_CACHE[t_key] = out
        return out
    except Exception:
        return ""


_CROSS_CHECK_SEARCH_CACHE: Dict[str, str] = {}
_CROSS_CHECK_JSON_CACHE: Dict[str, Dict[str, Any]] = {}


def cross_check_financials(ticker: str, company: str, price: float, audit: Dict[str, Any],
                           reconciliation_notes: str = "") -> List[str]:
    """Independent second extraction of the core figures. Disagreement => reject and re-extract."""
    from stocks.gemini_agent import call_gemini_direct, parse_json_robust

    t_key = ticker.upper().strip()
    sec_summary = fetch_sec_edgar_summary(t_key)
    search_prompt = (
        f"Search Google for the latest reported 10-Q/10-K/20-F and earnings release financials for {ticker} ({company}) "
        f"trading at ${price:.2f} USD. Report the exact figures (converted to MILLIONS USD at spot FX if foreign, and "
        f"using ADR/ADS-equivalent post-split diluted share count matching the ${price:.2f} share price) for:\n"
        f"1. Trailing 12-Month (TTM) Revenue ($M USD, sum of latest 4 quarters)\n"
        f"2. Diluted Shares Outstanding (Millions, matching ${price:.2f}/share)\n"
        f"3. Trailing 12-Month Operating Cash Flow (OCF) ($M USD)\n"
        f"4. Total Cash, Cash Equivalents & Short-Term Marketable Securities ($M USD)\n"
        f"5. Total Short-Term & Long-Term Debt ($M USD)\n"
        f"List each figure clearly with its filing source."
    )
    check: Dict[str, Any] = _CROSS_CHECK_JSON_CACHE.get(t_key) or {}
    if not check:
        for _attempt in range(2):
            try:
                if t_key not in _CROSS_CHECK_SEARCH_CACHE or _attempt > 0:
                    _CROSS_CHECK_SEARCH_CACHE[t_key] = call_gemini_direct(prompt=search_prompt, use_search=True)
                raw_search = _CROSS_CHECK_SEARCH_CACHE[t_key]
                recon_block = f"\n\nADDITIONAL FILING EVIDENCE:\n{reconciliation_notes}\n" if reconciliation_notes else ""
                fmt_prompt = (
                    f"From the authoritative SEC EDGAR XBRL facts and independent search findings below for {ticker} ({company}) "
                    f"at ${price:.2f} USD (market cap ~${(audit.get('market_cap_mil') or 0):,.0f}M), "
                    f"extract the 5 statutory figures in MILLIONS USD:\n"
                    f"- Convert any foreign currency (DKK, EUR, GBP, BRL, RMB, JPY, CAD, ISK) to USD at spot FX.\n"
                    f"- Share count must match the ${price:.2f} USD price basis.\n"
                    f"- For 20-F / foreign filers, SEC XBRL only contains annual 20-F entries and omits recent 2026 6-K quarters; "
                    f"always use the MOST RECENT 2026 TTM (sum of latest 4 quarters) and latest balance sheet figures from the search findings.\n\n"
                    f"{sec_summary}\n\n{raw_search}{recon_block}\n\n"
                    f'Return ONLY valid JSON:\n```json\n{{"trailing_revenue_ttm_mil": float, "diluted_shares_mil": float, '
                    f'"operating_cash_flow_ttm_mil": float, "cash_mil": float, "debt_mil": float}}\n```'
                )
                check = parse_json_robust(call_gemini_direct(prompt=fmt_prompt, use_search=False)) or {}
                found = sum(1 for k in ("trailing_revenue_ttm_mil", "diluted_shares_mil", "operating_cash_flow_ttm_mil", "cash_mil")
                            if _num(check.get(k)) is not None)
            except Exception as e:
                if _attempt == 1:
                    return [f"Independent cross-check call failed: {e}"]
                continue
            if found >= 3:
                _CROSS_CHECK_JSON_CACHE[t_key] = check
                break

    issues: List[str] = []
    tolerances = {
        "trailing_revenue_ttm_mil": 0.15,
        "diluted_shares_mil": 0.10,
        "operating_cash_flow_ttm_mil": 0.35,
    }
    compared = 0
    for field, tol in tolerances.items():
        a, b = _num(audit.get(field)), _num(check.get(field))
        if a is None or b is None:
            continue
        compared += 1
        if not _close(a, b, tol, abs_tol=5.0):
            issues.append(
                f"Independent cross-check disagrees on {field}: primary={a:,.1f} vs check={b:,.1f} "
                f"(>{int(tol*100)}% apart). Re-verify from the primary filing."
            )
    a_nc = (_num(audit.get("cash_mil")) or 0) - (_num(audit.get("debt_mil")) or 0)
    if _num(check.get("cash_mil")) is not None and _num(check.get("debt_mil")) is not None:
        compared += 1
        b_nc = _num(check["cash_mil"]) - _num(check["debt_mil"])
        scale = max(abs(a_nc), abs(b_nc), (_num(audit.get("market_cap_mil")) or 0) * 0.05, 50.0)
        if abs(a_nc - b_nc) > 0.35 * scale:
            issues.append(
                f"Independent cross-check disagrees on net cash: primary={a_nc:,.0f}M vs check={b_nc:,.0f}M."
            )
    if compared < 2:
        issues.append("Independent cross-check returned too few figures to verify the extraction.")
    return issues


# ---------------------------------------------------------------------------
# Prompt contract
# ---------------------------------------------------------------------------

def build_numeric_contract(*, current_price: float, shares: float, oe_per_share: float, oe_total: float,
                           net_cash_per_share: float, net_cash_total: float, p_oe: float,
                           annualized_runrate: float) -> str:
    def sd(v: float, nd: int = 2) -> str:
        return f"-${abs(v):,.{nd}f}" if v < 0 else f"${v:,.{nd}f}"

    pe = f"{p_oe:.1f}x P/OE" if p_oe > 0 else "N/M P/OE (negative Owner Earnings)"
    return f"""=== NUMERIC CONSISTENCY CONTRACT (machine-verified; any violation rejects the thesis) ===
Use these EXACT verified figures wherever you cite them. Do not restate them differently.
- Current price: ${current_price:,.2f}  (Section 1 must cite this exact price)
- Diluted shares: {shares:,.1f}M  (any share count you mention must match within 10%)
- Starting Owner Earnings OE₀: {sd(oe_per_share)}/share ({sd(oe_total, 1)}M total)  (cite in Section 2 step 1 and Section 4)
- Net cash/(debt): {sd(net_cash_per_share)}/share ({sd(net_cash_total, 0)}M)
- Current multiple: {pe}
- Annualized revenue run-rate: ${annualized_runrate:,.1f}M
Rules:
1. Write negative dollars as -$12.34 (never $-12.34, never $(12.34)). No LaTeX, no $...$ math.
2. Section 2 has exactly steps 1–5; its step 5 must state the downside floor, and that dollar figure must equal "bear_floor_target".
3. Section 4 has exactly steps 1–6; step 6 must show "Year 3 OE $A/sh × Mx = $B" and "$B + Ending Net Cash $C/sh = $FV", where A×M≈B, B+C≈FV, and FV equals "fair_value_target".
4. "irr_3y_pct" must equal ((fair_value_target / {current_price:.2f})^(1/3) − 1) × 100, and step 6 must state that same IRR.
5. bear_floor_target > 0 and bear_floor_target ≤ fair_value_target ≤ bull_upside_target.
6. Never leave template placeholders like [X], [M], $[OE_3]. Never invent a figure you did not find; say "not disclosed" instead.
==========================================================================================="""


# ---------------------------------------------------------------------------
# Gate 2: final thesis output
# ---------------------------------------------------------------------------

def implied_irr_pct(fv: float, price: float) -> float:
    if fv <= 0 or price <= 0:
        return -100.0
    return ((fv / price) ** (1.0 / 3.0) - 1.0) * 100.0


def derive_action_signal(fv: float, price: float, oe_per_share: float) -> str:
    """Deterministic signal from the verified fair value; never trusted from the model."""
    irr = implied_irr_pct(fv, price)
    if oe_per_share <= 0:
        return "AVOID" if irr < 15.0 else "CAUTION"
    if irr >= 12.0:
        return "BUY"
    if irr >= 5.0:
        return "HOLD"
    if irr >= 0.0:
        return "CAUTION"
    return "AVOID"


def validate_thesis_output(info: Dict[str, Any], price: float) -> List[str]:
    issues: List[str] = []
    s1 = info.get("market_pricing_in") or ""
    s2 = info.get("why_it_might_be_right") or ""
    s3 = info.get("how_things_are_going_now") or ""
    s4 = info.get("what_if_it_keeps_going_that_way") or ""
    all_text = "\n".join([s1, s2, s3, s4])

    for name, txt, min_len in [("Section 1", s1, 350), ("Section 2", s2, 300),
                               ("Section 3", s3, 350), ("Section 4", s4, 500)]:
        if len(txt.strip()) < min_len:
            issues.append(f"{name} is too short ({len(txt.strip())} chars < {min_len}).")
    if issues:
        return issues

    # Structure
    steps2, steps4 = _numbered_steps(s2), _numbered_steps(s4)
    if sorted(steps2.keys()) != [1, 2, 3, 4, 5]:
        issues.append(f"Section 2 must have numbered steps 1–5 on separate lines (found {sorted(steps2.keys())}).")
    if sorted(steps4.keys()) != [1, 2, 3, 4, 5, 6]:
        issues.append(f"Section 4 must have numbered steps 1–6 on separate lines (found {sorted(steps4.keys())}).")

    # Placeholders / fallback text / bad formatting
    if re.search(r"\$?\[[A-Za-z][A-Za-z0-9_ ]*\]", all_text):
        issues.append("Unfilled template placeholder found (e.g. [X], $[OE_3]).")
    low = all_text.lower()
    for phrase in BANNED_FALLBACK_PHRASES:
        if phrase in low:
            issues.append(f"Synthetic fallback text present: '{phrase}'.")
    if re.search(r"\$[-+]\d|\$\(\d", all_text):
        issues.append("Malformed signed dollar ($-12 or $(12)); write -$12.")
    if "\\(" in all_text or "\\[" in all_text:
        issues.append("LaTeX delimiters present in prose.")

    # Structured targets
    fv = _num(info.get("fair_value_target"))
    bear = _num(info.get("bear_floor_target"))
    bull = _num(info.get("bull_upside_target"))
    irr = _num(info.get("irr_3y_pct"))
    if fv is None or fv <= 0:
        issues.append("fair_value_target missing or non-positive.")
        return issues
    if bear is None or bear <= 0:
        issues.append("bear_floor_target missing or non-positive.")
    if bull is None or bull <= 0:
        issues.append("bull_upside_target missing or non-positive.")
    if bear and bull and not (bear <= fv * 1.001 and fv <= bull * 1.001 and bear < bull):
        issues.append(f"Targets out of order: bear ${bear:.2f} ≤ FV ${fv:.2f} ≤ bull ${bull:.2f} required.")

    oe_sh = _num(info.get("normalized_oe_per_share")) or 0.0
    shares = _num(info.get("diluted_shares_mil")) or 0.0
    p_oe = _num(info.get("p_oe")) or 0.0

    # Fair value sanity band (MELI lesson). Wide on purpose; outside it the math is almost always wrong.
    ratio = fv / price
    lo = 0.20 if oe_sh > 0 else 0.03
    if not (lo <= ratio <= 3.5):
        issues.append(
            f"Fair value ${fv:.2f} is {ratio:.2f}× the price ${price:.2f} (allowed {lo}–3.5×). "
            f"Re-check Owner Earnings normalization, share basis, and the exit multiple."
        )

    # IRR consistency
    implied = implied_irr_pct(fv, price)
    if irr is None or abs(irr - implied) > 3.0:
        issues.append(f"irr_3y_pct ({irr}) must equal the implied 3-year IRR from FV/price ({implied:.1f}%).")

    # Section 1 must cite the live price
    if not _any_close(money_values(s1, per_share_only=True), price, 0.01):
        issues.append(f"Section 1 must cite the current price ${price:,.2f}.")
    m_pe = re.search(r"(\d+(?:\.\d+)?)x\s*(?:trailing\s+|normalized\s+)?(?:P/OE|price[- ]to[- ]owner)", s1, re.IGNORECASE)
    if p_oe > 0 and m_pe and not _close(float(m_pe.group(1)), p_oe, 0.15, 0.3):
        issues.append(f"Section 1 cites {m_pe.group(1)}x P/OE but verified P/OE is {p_oe:.1f}x.")

    # OE₀ must be cited consistently
    if abs(oe_sh) >= 0.01:
        if not _any_close(money_values(steps2.get(1, s2), per_share_only=True), oe_sh, 0.03):
            issues.append(f"Section 2 step 1 must cite starting Owner Earnings of ${oe_sh:.2f}/share.")

    # Share counts mentioned anywhere must match (excluding buyback/issuance deltas)
    if shares > 0:
        for m in re.finditer(r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(M|million|B|billion)\s+(?:diluted\s+|post-split\s+|weighted[- ]average\s+)*(?:shares|ADS|ADSs|ADRs)\b",
                             all_text, re.IGNORECASE):
            prefix = all_text[max(0, m.start() - 40):m.start()].lower()
            if any(w in prefix for w in ("repurchas", "retir", "bought back", "buyback", "issu", "reduc", "by ")):
                continue
            val = float(m.group(1).replace(",", ""))
            if m.group(2).lower().startswith("b"):
                val *= 1000.0
            if not _close(val, shares, 0.10):
                issues.append(f"Prose cites {m.group(0)!r} but verified diluted shares are {shares:,.1f}M.")
                break

    # Section 2 step 5 must state the bear target
    if bear and 5 in steps2 and not _any_close(money_values(steps2[5], per_share_only=True), bear, 0.01, 0.02):
        issues.append(f"Section 2 step 5 must state the downside floor ${bear:,.2f} (= bear_floor_target).")

    # Section 4 step 6 arithmetic: A × M = B ; B + C = FV
    step6 = steps4.get(6, "")
    if step6:
        if not _any_close(money_values(step6, per_share_only=True), fv, 0.01, 0.02):
            issues.append(f"Section 4 step 6 must state the fair value ${fv:,.2f} (= fair_value_target).")
        mults = list(re.finditer(
            r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:/\s*(?:sh|share)|per share)?[^\n$]{0,40}?[×x\*]\s*(\d+(?:\.\d+)?)\s*x?",
            step6,
        ))
        if not mults:
            issues.append("Section 4 step 6 lacks an explicit 'Year 3 OE $A/sh × Mx' calculation.")
        else:
            signed = money_values(step6, per_share_only=True)
            nc0 = _num(info.get("net_cash_per_share")) or 0.0
            step5_ps = money_values(steps4.get(5, ""), per_share_only=True)
            candidates = []
            for m_obj in mults:
                a = float(m_obj.group(1).replace(",", ""))
                m_val = float(m_obj.group(2))
                cap = a * m_val
                reconciling = [c for c in signed + [0.0] if _close(cap + c, fv, 0.02, 0.05)]
                candidates.append((abs(cap + nc0 - fv), a, m_val, cap, reconciling))
            # Pick a candidate that reconciles cleanly, or otherwise the one closest to Fair Value
            candidates.sort(key=lambda t: (0 if t[4] else 1, t[0]))
            _, a, m_val, cap, reconciling = candidates[0]
            if not (3.0 <= m_val <= 35.0):
                issues.append(f"Exit multiple {m_val}x is outside the 3–35x discipline band.")
            if not reconciling:
                issues.append(
                    f"Step 6 arithmetic does not reconcile: ${a:,.2f} × {m_val}x = ${cap:,.2f}, "
                    f"and no stated net-cash figure brings it to the fair value ${fv:,.2f}."
                )
            else:
                # Anti-gaming: ending net cash must be reachable from verified starting net cash
                # plus (at most) ~3 years of owner cash generation.
                cash_gen = 3.0 * max(oe_sh, a, 0.0) * 1.5
                lo_nc = nc0 - abs(nc0) * 0.5 - 3.0 * abs(min(oe_sh, 0.0)) * 1.5 - 0.05
                hi_nc = nc0 + cash_gen + 0.05
                reachable = [c for c in reconciling if lo_nc <= c <= hi_nc]
                if not reachable:
                    issues.append(
                        f"Ending net cash used in step 6 ({', '.join(f'${c:,.2f}' for c in reconciling)}/sh) is not "
                        f"reachable from verified starting net cash {nc0:+.2f}/sh plus ≤3 years of Owner Earnings "
                        f"(plausible range {lo_nc:+.2f} to {hi_nc:+.2f}/sh). Do not adjust net cash to hit a target."
                    )
                elif step5_ps and not any(abs(c) < 0.01 or _any_close(step5_ps, c, 0.03, 0.10) for c in reachable):
                    issues.append(
                        f"Step 6 uses ending net cash {', '.join(f'${c:,.2f}' for c in reachable)}/sh, which does not "
                        f"match the ending net cash per share stated in step 5."
                    )
        m_irr = re.search(r"(-?\d+(?:\.\d+)?)\s*%[^.\n]{0,60}?(?:per annum|annualized|IRR)|(?:IRR|annualized return)[^.\n%]{0,60}?(-?\d+(?:\.\d+)?)\s*%",
                          step6, re.IGNORECASE)
        if m_irr:
            stated = float(m_irr.group(1) or m_irr.group(2))
            if abs(abs(stated) - abs(implied)) > 1.5 or (implied < -1 and stated > 1):
                issues.append(f"Step 6 states IRR {stated}% but FV/price implies {implied:.1f}%.")
        else:
            issues.append("Section 4 step 6 must state the expected 3-year annualized return (IRR).")

    # Recency: Section 3 must reference current or prior year results
    yr = datetime.now().year
    if not re.search(rf"\b(?:{yr}|{yr-1})\b|\bFY ?(?:{str(yr)[2:]}|{str(yr+1)[2:]}|{str(yr-1)[2:]})\b", s3):
        issues.append(f"Section 3 does not reference {yr-1}/{yr} results — likely stale.")

    return issues


def validate_rendered_html(html: str) -> List[str]:
    issues = []
    if "\\(" in html or "\\)" in html:
        issues.append("Rendered HTML contains LaTeX \\( \\) delimiters (signed-dollar corruption).")
    if "««" in html or "»»" in html:
        issues.append("Rendered HTML contains unexpanded placeholder tokens.")
    if "<p>—</p>" in html:
        issues.append("Rendered HTML contains an empty section.")
    return issues


# ---------------------------------------------------------------------------
# Repair pass (keeps verified inputs fixed; fixes only the listed defects)
# ---------------------------------------------------------------------------

def repair_thesis_sections(ticker: str, company: str, price: float, info: Dict[str, Any],
                           issues: List[str]) -> Dict[str, Any]:
    from stocks.gemini_agent import call_gemini_direct, parse_json_robust
    import json as _json

    current = {k: info.get(k) for k in [
        "fair_value_target", "bear_floor_target", "bull_upside_target", "irr_3y_pct",
        "market_pricing_in", "why_it_might_be_right", "how_things_are_going_now",
        "what_if_it_keeps_going_that_way",
    ]}
    prompt = f"""You wrote the investment thesis JSON below for {ticker} ({company}) at ${price:.2f}.
A deterministic QA gate rejected it. Fix EVERY listed defect. Keep all analysis, facts, and verified figures;
change only what is necessary. Recompute any downstream numbers so every equation is arithmetically exact.

{info.get('numeric_contract', '')}

QA DEFECTS TO FIX:
- """ + "\n- ".join(issues) + f"""

CURRENT THESIS JSON:
{_json.dumps(current, indent=2)}

Respond STRICTLY with the corrected JSON using the same keys."""
    fixed = parse_json_robust(call_gemini_direct(prompt=prompt, use_search=False)) or {}
    out = dict(info)
    for k in current:
        if fixed.get(k) not in (None, ""):
            out[k] = fixed[k]
    return out
