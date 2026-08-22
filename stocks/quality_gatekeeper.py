"""Institutional 7-Pillar Quality Gatekeeper for Stock Research Dossiers.

Enforces zero-defect standards on every research dossier before it can be added to
the watchlist, saved to disk, or deployed to GitHub Pages.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

THESES_DIR = Path(__file__).resolve().parent.parent / "data" / "theses"


def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        if isinstance(val, (int, float)):
            return float(val)
        cleaned = re.sub(r"[^\d.-]", "", str(val))
        return float(cleaned) if cleaned else default
    except (ValueError, TypeError):
        return default


def auto_heal_dossier_and_metadata(ticker: str, html: str, metadata: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any]]:
    """Deterministically auto-heals HTML formatting, table cell closures, LaTeX syntax, and metadata consistency in-place."""
    if not html:
        return html, metadata or {}
    
    from stocks.gemini_agent import verify_and_repair_html_structure
    healed_html = verify_and_repair_html_structure(html)
    
    # 1. Auto-close truncated <td> tags before </tr>
    healed_html = re.sub(r"(<td\b[^>]*>(?:(?!</td>|<td\b).)*?)(?=\s*</tr>)", r"\1</td>", healed_html, flags=re.DOTALL | re.IGNORECASE)
    
    # 2. Fix stripped cents (e.g. .50 -> $0.50)
    healed_html = re.sub(r"(?<=\s|\()\b\.(\d{2})\b", r"$0.\1", healed_html)
    
    # 3. Strip rogue fences and broken <em> <strong> combinations
    healed_html = healed_html.replace("```html", "").replace("```", "")
    healed_html = re.sub(r'<em>\s*<strong>', '<strong>', healed_html, flags=re.IGNORECASE)
    healed_html = re.sub(r'</strong>\s*</em>', '</strong>', healed_html, flags=re.IGNORECASE)
    
    # 4. Harmonize metadata in memory
    meta = dict(metadata) if metadata else {}
    if meta:
        exp_v = meta.get("expected_val")
        if exp_v is None:
            m_exp = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)", str(meta.get("expected_fair_value") or meta.get("present_fair_value") or meta.get("fair_value_estimate") or ""))
            if m_exp:
                try:
                    exp_v = float(m_exp.group(1).replace(",", ""))
                except Exception:
                    pass
        if exp_v is not None:
            try:
                exp_f = float(exp_v)
                meta["expected_val"] = exp_f
                if not meta.get("fair_value_estimate") or meta.get("fair_value_estimate") == "$0.00":
                    meta["fair_value_estimate"] = f"${exp_f:.2f}"
                if not meta.get("expected_fair_value"):
                    meta["expected_fair_value"] = f"${exp_f:.2f}"
            except (ValueError, TypeError):
                pass
                
        stories = meta.get("stories", [])
        if stories and len(stories) >= 1:
            for idx, s in enumerate(stories, start=1):
                if not meta.get(f"story{idx}_target"):
                    meta[f"story{idx}_target"] = s.get("target", "")

        # Harmonize net debt row in Section 3 table if $0.00 was plugged
        net_cash_val = meta.get("net_cash_per_share")
        if net_cash_val is not None:
            try:
                nc_f = float(net_cash_val)
                if abs(nc_f) >= 0.50:
                    nc_formatted = f"+${nc_f:.2f}/share" if nc_f > 0 else f"-${abs(nc_f):.2f}/share"
                    def _fix_nc_row(m_row):
                        row_txt = m_row.group(0)
                        if "$0.00" in row_txt:
                            return re.sub(r'<td>\s*\$0\.00\s*(?:/share)?\s*</td>', f'<td>{nc_formatted}</td>', row_txt, flags=re.IGNORECASE)
                        return row_txt
                    healed_html = re.sub(r'<tr>\s*<td>\s*(?:Net\s+Balance\s+Sheet\s+Cash\s*/\s*\(Debt\)|Net\s+Debt/Cash\s+Adjustment).*?</tr>', _fix_nc_row, healed_html, flags=re.DOTALL | re.IGNORECASE)
            except Exception:
                pass

    return healed_html, meta


def validate_dossier_quality(ticker: str, html: str, metadata: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[str]]:
    """Strictly audits a research dossier across institutional quality dimensions."""
    issues = []
    if not html or not isinstance(html, str):
        return False, ["HTML content is completely empty or not a string."]

    from stocks.gemini_agent import verify_and_repair_html_structure
    html, metadata = auto_heal_dossier_and_metadata(ticker, html, metadata)

    # 1. Word Count & Analytical Depth
    words = html.split()
    word_count = len(words)
    if word_count < 180:
        issues.append(f"Insufficient analytical depth ({word_count} words < 180 word minimum).")

    # 2. Complete 4-Section Single-Agent Architecture
    missing_sections = []
    required_sections = [
        "What the Market is Pricing In",
        "Why the Market Might Be Right",
        "How Things Are Going Now",
        "What If It Keeps Going That Way"
    ]
    for s_name in required_sections:
        if s_name.lower() not in html.lower():
            missing_sections.append(s_name)
                
    if missing_sections:
        issues.append(f"Missing core architectural sections: {', '.join(missing_sections)}.")

    # 3. Table Structural Integrity & Truncated Cells
    broken_table_matches = re.findall(r"<td[^>]*>[^<]*</tr\b", html, re.IGNORECASE)
    if broken_table_matches:
        issues.append(f"Found {len(broken_table_matches)} truncated <td> cells before </tr> tags.")

    open_tr = len(re.findall(r"<tr\b", html, re.IGNORECASE))
    close_tr = len(re.findall(r"</tr>", html, re.IGNORECASE))
    if open_tr != close_tr:
        issues.append(f"Mismatched <tr> tags ({open_tr} opened vs {close_tr} closed).")

    open_table = len(re.findall(r"<table\b", html, re.IGNORECASE))
    close_table = len(re.findall(r"</table>", html, re.IGNORECASE))
    if open_table != close_table:
        issues.append(f"Mismatched <table> tags ({open_table} opened vs {close_table} closed).")

    # 4. Clean Semantic Lists (No Raw Markdown Bullets or Nested ULs)
    stray_bullets = len(re.findall(r"^\s*[*•-]\s+\*\*", html, flags=re.MULTILINE))
    if stray_bullets > 0:
        issues.append(f"Found {stray_bullets} unrendered markdown bullet lines (* **).")

    stray_em_strong = len(re.findall(r"<em>\s*<strong>", html, flags=re.IGNORECASE))
    if stray_em_strong > 0:
        issues.append(f"Found {stray_em_strong} broken <em> <strong> combinations.")

    # 6. No Rogue Dashboard Header Injections
    if "investor-dashboard" in html or "price-corridors" in html:
        issues.append("Contains redundant rogue investor-dashboard / price-corridors container.")

    # 7. No Raw Code Fences
    if "```" in html:
        issues.append("Contains unrendered markdown code fences (```).")

    # 8. List & Tag Balance Integrity (Zero Unclosed Lists)
    open_ul = len(re.findall(r"<ul(?:\s|>)", html, re.IGNORECASE))
    close_ul = len(re.findall(r"</ul>", html, re.IGNORECASE))
    if open_ul != close_ul:
        issues.append(f"Mismatched <ul> tags ({open_ul} opened vs {close_ul} closed).")

    open_ol = len(re.findall(r"<ol(?:\s|>)", html, re.IGNORECASE))
    close_ol = len(re.findall(r"</ol>", html, re.IGNORECASE))
    if open_ol != close_ol:
        issues.append(f"Mismatched <ol> tags ({open_ol} opened vs {close_ol} closed).")

    open_li = len(re.findall(r"<li(?:\s|>)", html, re.IGNORECASE))
    close_li = len(re.findall(r"</li>", html, re.IGNORECASE))
    if open_li != close_li:
        issues.append(f"Mismatched <li> tags ({open_li} opened vs {close_li} closed).")

    # 9. Dangling Truncated Tail Check
    trimmed = html.strip()
    if trimmed.endswith("<") or re.search(r"<[a-zA-Z0-9_-]+(?:\s+[^>]*)?$", trimmed):
        issues.append("HTML ends with an incomplete/cut-off opening tag at tail.")
    
    if re.search(r"<li>\s*<strong>[^<]{2,40}$", trimmed):
        issues.append("Dossier ends with an incomplete dangling list item.")

    valid_tail_endings = (">", ".", "!", "?", "</div>", "</p>", "</li>", "</ul>", "</ol>", "</table>", "</section>")
    if not trimmed.endswith(valid_tail_endings):
        issues.append("Dossier text appears truncated mid-sentence at tail.")

    # 10. Valuation Corridor Harmonization & Price Alignment
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
    base_val = None
    for r in rows:
        r_clean = re.sub(r"<[^>]+>", " ", r).strip()
        if any(k in r_clean.lower() for k in ["intrinsic fair value", "intrinsic value / share", "intrinsic value per share", "base intrinsic value", "fair value / share", "fair value per share", "fair value target"]):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", r, re.DOTALL)
            extracted_nums = []
            for td in tds:
                cleaned = re.sub(r"<[^>]+>", "", td).strip()
                num_match = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)", cleaned)
                if num_match:
                    try:
                        extracted_nums.append(float(num_match.group(1).replace(",", "")))
                    except ValueError:
                        pass
            if len(extracted_nums) >= 1:
                base_val = extracted_nums[0]
            break

    # 10b. Arithmetic Sum Integrity Check (PV of Operating + Net Cash == Intrinsic Value)
    proof_matches = re.findall(r"\$(\d+(?:\.\d+)?)\s*\+\s*\$(\d+(?:\.\d+)?)\s*=\s*\$(\d+(?:\.\d+)?)", html)
    for op_s, cash_s, tot_s in proof_matches:
        op_f, cash_f, tot_f = float(op_s), float(cash_s), float(tot_s)
        if abs((op_f + cash_f) - tot_f) > 0.05:
            issues.append(f"Arithmetic Error: Claimed ${op_s} + ${cash_s} = ${tot_s} (actual sum: ${op_f+cash_f:.2f}).")

    # 11. No Unexpanded Tokenizer / LLM Synthetic Artifacts & Foreign Script Leaks
    if re.search(r"««[A-Z_0-9]+»»", html) or "««" in html or "»»" in html:
        issues.append("Contains unexpanded tokenizer/LLM placeholder artifacts (e.g. ««CURRENCY...»» or ««INLINE_BLOCK...»»).")

    if re.search(r'[\u0400-\u04FF]', html):
        issues.append("Contains stray Cyrillic/foreign script characters in English report.")

    if re.search(r'\$\s*(?:Millions|Billions)?\s*(?:CNY|RMB)\b', html, re.IGNORECASE):
        issues.append("Contains contradictory currency labeling (e.g. '$ Millions CNY'). Use clean 'RMB Millions (¥)' or '$ Millions USD'.")

    # 12. Stripped Currency Decimals & Formatting Integrity Check
    stripped_cents = re.findall(r"(?:^|\s|\()\.\d{2}\b", html)
    if stripped_cents:
        issues.append(f"Contains stripped currency numbers missing dollar signs or integer amounts ({stripped_cents[:3]}).")

    orphaned_magnitude = re.findall(r"\b(?:a|the|exceeding|of|to)\s+[BM]\b", html, re.IGNORECASE)
    if orphaned_magnitude:
        issues.append(f"Contains corrupted magnitude words where numbers were stripped ({orphaned_magnitude[:3]}).")

    # 13. Metadata Alignment & Signal Consistency Check
    if metadata:
        p_in = metadata.get("what_is_priced_in", "")
        if not p_in or str(p_in).strip() in ("", "N/A"):
            issues.append("Metadata field 'what_is_priced_in' is empty or unpopulated.")

        act_signal = str(metadata.get("action_signal", "")).upper()
        exec_summary = str(metadata.get("executive_summary", "")).lower()
        if act_signal == "AVOID":
            bullish_keywords = ["attractive entry", "attractive risk-adjusted entry", "deep value", "strong buy", "screaming buy", "undervalued opportunity"]
            for bk in bullish_keywords:
                if bk in exec_summary:
                    issues.append(f"Signal Contradiction: Action signal is AVOID but executive summary contains '{bk}'.")

        # 14. Canonical Moat Rating & Label Quality Check
        CANONICAL_MOAT_LABELS = {
            "Wide Moat", "Narrow Moat", "Weak Moat", "No Moat",
            "Strong Moat", "Moderate Moat"
        }
        CANONICAL_CONVICTION_TIERS = {
            "High Conviction", "Solid Conviction", "Moderate Conviction",
            "Cautious Stance", "Turnaround Play", "Speculative Risk"
        }
        ALL_VALID_STATUS = CANONICAL_MOAT_LABELS | CANONICAL_CONVICTION_TIERS
        status_lbl = metadata.get("status_label") or (metadata.get("labels", [""])[0] if metadata.get("labels") else "")
        if not status_lbl or status_lbl in ["Active", "Review", "Stock", "Alert", "None", "TBD", "Status"]:
            issues.append(f"Non-canonical status_label '{status_lbl}'. Must strictly be one of: {sorted(list(CANONICAL_MOAT_LABELS))}.")
        elif status_lbl not in ALL_VALID_STATUS:
            issues.append(f"Invalid Moat/Status Label '{status_lbl}'. Must strictly be one of: {sorted(list(CANONICAL_MOAT_LABELS))}.")

        labels = metadata.get("labels", [])
        if not labels or labels[0] not in ALL_VALID_STATUS:
            issues.append(f"Label Slot 1 '{labels[0] if labels else None}' must strictly be a canonical Moat Rating.")

        # 14b. Canonical Pricing Power Tier Check
        CANONICAL_PRICING_POWER_TIERS = {
            "Absolute Pricing Power", "Strong Pricing Power", "Inflation Pass-Through",
            "Constrained Pricing Power", "Price Taker"
        }
        pp_tier = metadata.get("pricing_power_tier")
        if pp_tier and pp_tier not in CANONICAL_PRICING_POWER_TIERS:
            issues.append(f"Invalid Pricing Power Tier '{pp_tier}'. Must strictly be one of: {sorted(list(CANONICAL_PRICING_POWER_TIERS))}.")

        # 14c. Canonical Cash Flow Predictability Tier Check
        CANONICAL_PREDICTABILITY_TIERS = {
            "High Predictability", "Moderate Predictability",
            "Low Predictability", "Highly Unpredictable"
        }
        pred_tier = metadata.get("predictability_tier")
        if pred_tier and pred_tier not in CANONICAL_PREDICTABILITY_TIERS:
            issues.append(f"Invalid Cash Flow Predictability Tier '{pred_tier}'. Must strictly be one of: {sorted(list(CANONICAL_PREDICTABILITY_TIERS))}.")

    # 15. Grounded Unit Economics Check (Strict Ban on Lazy Top-Down Hand-Waving)
    cagr_shortcuts = re.findall(r"(?:assuming\s+(?:top-line\s+growth\s+slows\s+to\s+a\s+steady|a\s+steady\s+\d+(?:\.\d+)?%\s+cagr|growth\s+slows\s+to\s+\d+(?:\.\d+)?%\s+cagr|top-line\s+grows\s+at\s+\d+(?:\.\d+)?%|revenue\s+compounds\s+at\s+\d+(?:\.\d+)?%))", html, re.IGNORECASE)
    if cagr_shortcuts:
        issues.append(f"Contains lazy top-down CAGR shortcut ('{cagr_shortcuts[0]}'). Demand explicit bottom-up unit economics (Units × Yield ➔ Revenue − Cash Costs ➔ Total Owner Earnings).")

    unit_keywords = [
        "user", "dau", "mau", "subscriber", "seat", "client", "merchant", "buyer", "seller",
        "store", "door", "club", "box", "unit", "volume", "arpu", "take rate", "take-rate",
        "price per", "pricing", "arr", "tpv", "gmv", "comp sales", "tuition",
        "asp", "retention", "nrr", "margin", "revenue", "segment", "division",
        "cloud", "search", "services", "sotp", "sum of the parts", "sum-of-the-parts"
    ]
    has_unit_anchors = any(k in html.lower() for k in unit_keywords)
    if not has_unit_anchors:
        issues.append("Dossier lacks bottom-up unit economics / SOTP drivers (e.g. buyers, sellers, users, seats, merchants, ARPU, segment revenues, take rate, TPV, GMV).")

    # 15b. Grounded 3-Year Continuation & Target Verification
    has_target = "target" in html.lower() or "fair value" in html.lower() or "return" in html.lower() or "irr" in html.lower()
    if not has_target:
        issues.append("Section 4 lacks an explicit Intrinsic Fair Value Target or Expected Return.")

    # 15c. Cash Bridge Balance Sheet Sanity
    if "cash bridge" in html.lower() or "ending net cash" in html.lower() or "starting net cash" in html.lower():
        if "buyback" in html.lower() and re.search(r"starting\s+net\s+(?:debt|cash\s+of\s+-\$)", html, re.IGNORECASE):
            # If net debt is heavy and aggressive buybacks are modeled (> $200M)
            if re.search(r"(?:repurchasing|buybacks\s+of\s+\$)[2-9]\d\d(?:\.\d+)?M", html, re.IGNORECASE):
                issues.append("Capital Allocation Warning: Modeled large share buybacks while company is in significant starting net debt.")

    # 18. Storyline Targets & Alert Corridor Validity
    if metadata:
        def _parse_p(val_str: Optional[str]) -> Optional[float]:
            if not val_str: return None
            m = re.search(r"\$?\s*([+-]?[\d,]+(?:\.\d+)?)", str(val_str))
            if m:
                try:
                    c = re.sub(r"[^\d.-]", "", m.group(1))
                    if c and c not in (".", "-"):
                        return float(c)
                except Exception:
                    pass
            return None
        
        s1 = _parse_p(metadata.get("story1_target") or metadata.get("base_target"))
        s2 = _parse_p(metadata.get("story2_target") or metadata.get("bear_target"))
        s3 = _parse_p(metadata.get("story3_target") or metadata.get("bull_target"))
        
        for idx, s_val in enumerate([s1, s2, s3], start=1):
            if s_val is not None and s_val <= 0:
                issues.append(f"Storyline {idx} calculated valuation (${s_val:.2f}) must be positive (> $0.00).")
                
        lower_alert = metadata.get("lower_alert_threshold")
        upper_alert = metadata.get("upper_alert_threshold")
        if lower_alert is not None and upper_alert is not None and lower_alert >= upper_alert:
            issues.append(f"Corridor Invariant Failure: Lower Alert (${lower_alert:.2f}) must be strictly less than Upper Alert (${upper_alert:.2f}).")

    # 19. Script & Interactive Chart Block Health Check
    if "<script" in html:
        open_scripts = len(re.findall(r"<script\b", html, re.IGNORECASE))
        close_scripts = len(re.findall(r"</script>", html, re.IGNORECASE))
        if open_scripts != close_scripts:
            issues.append(f"Mismatched <script> tags ({open_scripts} opened vs {close_scripts} closed).")

    # 20. Economic Reality & Liquidity Floor Check
    if metadata:
        s_vals = [s for s in [s1, s2, s3] if s is not None and s > 0]
        cur_p = _parse_p(metadata.get("price_at_version") or metadata.get("current_price"))
        if cur_p and len(s_vals) >= 3:
            min_s = min(s_vals)
            status_low = str(metadata.get("status_label", "")).lower()
            if min_s < (cur_p * 0.20) and not any(k in status_low for k in ["speculative", "turnaround", "weak moat", "no moat", "cautious"]):
                issues.append(f"Economic Reality Failure: Bear scenario target (${min_s:.2f}) represents an irrational {-((cur_p-min_s)/cur_p*100):.1f}% collapse on a going-concern business.")

    # 22. Storyline 1 & Expected Value Harmonization Check
    if metadata:
        fv_str = metadata.get("fair_value_estimate", "")
        s1_str = metadata.get("story1_target", "")
        exp_v = metadata.get("expected_val")
        if exp_v is None:
            exp_v = _parse_p(metadata.get("expected_fair_value") or metadata.get("present_fair_value") or metadata.get("fair_value_estimate"))
        if fv_str:
            fv_num = _parse_p(fv_str)
            s1_num = _parse_p(s1_str) if s1_str else None
            exp_num = float(exp_v) if exp_v is not None else None
            # Valid if headline fair value matches either Expected Value or Story 1
            matches_exp = exp_num is not None and abs(fv_num - exp_num) <= 0.10
            matches_s1 = s1_num is not None and abs(fv_num - s1_num) <= 0.10
            if not matches_exp and not matches_s1 and s1_num is not None:
                issues.append(f"Storyline Target Inconsistency: Headline Fair Value (${fv_num:.2f}) does not match Expected Value (${exp_num or 0:.2f}) or Storyline 1 Target (${s1_num:.2f}).")

    # 23. Prohibition of Promotional Buzzwords & Unearned Spin
    banned_spin_phrases = [
        "intentional reset",
        "turnaround taking hold",
        "turnaround is taking hold",
        "poised for explosive growth",
        "poised for growth",
        "temporary pullback",
        "will stabilize as product",
        "will halt as new product",
    ]
    for phrase in banned_spin_phrases:
        if phrase in html.lower():
            issues.append(f"Dossier contains unearned promotional spin phrase '{phrase}'. Must strictly use cold, forensic, unvarnished prose.")

    return len(issues) == 0, issues


def audit_all_theses_directory() -> Tuple[int, int, List[Dict[str, Any]]]:
    """Audits all thesis files on disk and returns (passed_count, failed_count, failure_details)."""
    thesis_files = sorted(list(THESES_DIR.glob("*.json")))
    passed_count = 0
    failures = []
    
    for tf in thesis_files:
        ticker = tf.stem.upper()
        try:
            import json
            with open(tf, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data or not isinstance(data, list):
                failures.append({"ticker": ticker, "issues": ["Empty or invalid JSON array."]})
                continue
            v = data[-1]
            html = v.get("full_html_content", "")
            is_valid, issues = validate_dossier_quality(ticker, html, metadata=v)
            
            # Check metadata fields completeness
            for req_field in ["bear_target", "base_target", "bull_target"]:
                if not v.get(req_field):
                    issues.append(f"Missing required metadata field: {req_field}")
                    is_valid = False

            if is_valid:
                passed_count += 1
            else:
                failures.append({"ticker": ticker, "issues": issues, "word_count": len(html.split())})
        except Exception as e:
            failures.append({"ticker": ticker, "issues": [f"Exception loading JSON: {e}"]})
            
    return passed_count, len(failures), failures


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Institutional Quality Gatekeeper")
    parser.add_argument("--tickers", nargs="*", default=[], help="Specific tickers to validate (e.g. CHGG)")
    parser.add_argument("--strict", action="store_true", help="Fail with exit code 1 on any failure")
    parser.add_argument("--heal", action="store_true", help="Auto-repair/re-generate flagged dossiers instead of failing")
    args = parser.parse_args()

    print("=" * 90)
    print("🛡️ RUNNING INSTITUTIONAL ZERO-DEFECT QUALITY GATEKEEPER AUDIT")
    print("=" * 90)

    target_tickers = []
    if args.tickers:
        for t in args.tickers:
            for clean_t in re.split(r"[,;\s]+", t):
                if clean_t.strip():
                    target_tickers.append(clean_t.upper().strip())

    if target_tickers:
        print(f"🎯 Auditing Target Tickers: {', '.join(target_tickers)}")
        passed_count = 0
        failures = []
        for ticker in target_tickers:
            tf = THESES_DIR / f"{ticker}.json"
            if not tf.exists():
                failures.append({"ticker": ticker, "issues": ["Thesis JSON file does not exist on disk."]})
                continue
            try:
                import json
                with open(tf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not data or not isinstance(data, list):
                    failures.append({"ticker": ticker, "issues": ["Empty or invalid JSON array."]})
                    continue
                v = data[-1]
                html = v.get("full_html_content", "")
                is_valid, issues = validate_dossier_quality(ticker, html, metadata=v)
                if is_valid:
                    passed_count += 1
                else:
                    failures.append({"ticker": ticker, "issues": issues, "word_count": len(html.split())})
            except Exception as e:
                failures.append({"ticker": ticker, "issues": [f"Exception loading JSON: {e}"]})

        # Auto-Healing pass if requested and issues detected
        if failures and args.heal:
            print(f"\n🔄 [AUTONOMOUS HEALING] Quality Gatekeeper detected {len(failures)} flagged ticker(s). Running autonomous regeneration...", flush=True)
            from stocks.queue_manager import _handle_genesis_task
            from stocks.dashboard import render_all
            for f in failures:
                t = f["ticker"]
                print(f"   🛠️ Auto-regenerating complete thesis for {t}...", flush=True)
                _handle_genesis_task(t, notes="")
            render_all()
            print("✅ Autonomous healing pass completed. Re-verifying...")
            failures = []
            for ticker in target_tickers:
                tf = THESES_DIR / f"{ticker}.json"
                if tf.exists():
                    import json
                    with open(tf, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data:
                        v = data[-1]
                        is_valid, issues = validate_dossier_quality(ticker, v.get("full_html_content", ""), metadata=v)
                        if not is_valid:
                            failures.append({"ticker": ticker, "issues": issues, "word_count": len(v.get("full_html_content", "").split())})

        total = len(target_tickers)
        passed_count = total - len(failures)
        print(f"\n📊 Target Gatekeeper Results: {passed_count}/{total} PASSED | {len(failures)} FLAGGED\n")
        if failures:
            print("❌ QUALITY GATE FLAGGED ISSUES ON TARGET DOSSIERS:")
            for f in failures:
                print(f"\n🚨 [{f['ticker']}] ({f.get('word_count', 0)} words):")
                for issue in f["issues"]:
                    print(f"    └─ {issue}")
            if args.strict:
                sys.exit(1)
        else:
            print("✅ TARGET DOSSIER(S) PASSED 100% OF QUALITY PILLARS!")
            sys.exit(0)
    else:
        passed_count, failed_count, failures = audit_all_theses_directory()
        total = passed_count + failed_count
        print(f"\n📊 Global Gatekeeper Audit: {passed_count}/{total} PASSED | {failed_count} FLAGGED\n")
        if failures:
            print("⚠️ QUALITY AUDIT REPORT (Legacy Dossier Warnings):")
            for f in failures:
                print(f"\n🚨 [{f['ticker']}] ({f.get('word_count', 0)} words):")
                for issue in f["issues"]:
                    print(f"    └─ {issue}")
            if args.strict:
                sys.exit(1)
            else:
                print("\nℹ️ Non-strict mode: Existing warnings reported without blocking workflow.")
                sys.exit(0)
        else:
            print("✅ ALL DOSSIERS PASSED 100% OF INSTITUTIONAL QUALITY PILLARS!")
            sys.exit(0)


if __name__ == "__main__":
    main()
