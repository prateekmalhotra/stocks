"""Institutional 7-Pillar Quality Gatekeeper for Stock Research Dossiers.

Enforces zero-defect standards on every research dossier before it can be added to
the watchlist, saved to disk, or deployed to GitHub Pages.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

THESES_DIR = Path(__file__).resolve().parent.parent / "data" / "theses"

def validate_dossier_quality(ticker: str, html: str, metadata: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[str]]:
    """Strictly audits a research dossier across institutional quality dimensions."""
    issues = []
    if not html or not isinstance(html, str):
        return False, ["HTML content is completely empty or not a string."]

    from stocks.gemini_agent import verify_and_repair_html_structure
    html = verify_and_repair_html_structure(html)

    # 1. Word Count & Analytical Depth
    words = html.split()
    word_count = len(words)
    if word_count < 1800:
        issues.append(f"Insufficient analytical depth ({word_count} words < 1800 word institutional minimum).")

    # 2. Complete 6-Section Architecture
    missing_sections = []
    alt_names = {
        1: ["Executive Summary", "Operating Reality", "Variant Perception"],
        2: ["Business Model", "Moat", "Unit Economics"],
        3: ["Cash Flow", "Owner Earnings", "Stock-Based Compensation", "SBC"],
        4: ["Balance Sheet", "Capital Structure", "Net Cash", "Ownership"],
        5: ["Intrinsic Value", "Valuation Matrix", "Buffett Owner Earnings", "Scenario Valuation"],
        6: ["Invalidation", "Pre-Mortem", "Falsification", "What Breaks"]
    }
    for s_num in range(1, 7):
        pattern = rf"(?:<h2>|<h3>|<h4>|<section>|\b)[Ss]ection\s*{s_num}\b|#+\s*Section\s*{s_num}\b"
        if not re.search(pattern, html):
            found_alt = any(alt.lower() in html.lower() for alt in alt_names[s_num])
            if not found_alt:
                missing_sections.append(f"Section {s_num}")
                
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

    # 4. 3-Storyline / Scenario Valuation Matrix & Reverse DCF Presence
    has_scenarios = any(k in html.lower() for k in ["storyline", "storylines", "trajectory", "trajectories", "scenario", "scenarios", "bear case", "base case", "bull case"])
    if not has_scenarios:
        issues.append("Missing 3-Storyline / Scenario valuation matrix in Section 5.")
        
    has_reverse_dcf = any(k in html.lower() for k in [
        "priced in", "market-implied", "reverse dcf", "reverse-dcf", "g_implied", 
        "g_{implied}", "implied cagr", "implied growth", "market expectations", "what is priced in"
    ])
    if not has_reverse_dcf:
        issues.append("Missing Market-Implied Expectations / 'What is Priced In?' Reverse DCF analysis in Section 5.")

    # 5. Clean Semantic Lists (No Raw Markdown Bullets or Nested ULs)
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
            if len(extracted_nums) >= 2:
                base_val = extracted_nums[1]
            break

    if base_val:
        upper_match = re.search(r'(?:upper\s+threshold|trim\s+zone|target\s+realization).*?\$?\s*([\d,]+(?:\.\d+)?)', html, re.IGNORECASE)
        if upper_match:
            try:
                upper_val = float(upper_match.group(1).replace(",", ""))
                if upper_val < (base_val * 0.70):
                    issues.append(f"Valuation Corridor Contradiction: Section 6 Upper Trim Alert (${upper_val:.2f}) is significantly below Section 5 Base Case Intrinsic Fair Value (${base_val:.2f}).")
            except ValueError:
                pass

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

        # 14. Canonical Conviction Tier & Label Quality Check
        CANONICAL_CONVICTION_TIERS = {
            "High Conviction", "Solid Conviction", "Moderate Conviction",
            "Cautious Stance", "Turnaround Play", "Speculative Risk"
        }
        status_lbl = metadata.get("status_label") or (metadata.get("labels", [""])[0] if metadata.get("labels") else "")
        if not status_lbl or status_lbl in ["Active", "Review", "Stock", "Alert", "None", "TBD", "Status"]:
            issues.append(f"Non-canonical status_label '{status_lbl}'. Must strictly be one of: {sorted(list(CANONICAL_CONVICTION_TIERS))}.")
        elif status_lbl not in CANONICAL_CONVICTION_TIERS:
            issues.append(f"Invalid Conviction Tier '{status_lbl}'. Must strictly be one of: {sorted(list(CANONICAL_CONVICTION_TIERS))}.")

        labels = metadata.get("labels", [])
        if not labels or labels[0] not in CANONICAL_CONVICTION_TIERS:
            issues.append(f"Label Slot 1 '{labels[0] if labels else None}' must strictly be a canonical Conviction Tier.")

    # 15. Institutional Section 5 Completeness Check (Reverse DCF & 5-Year Market Closure Test)
    if "market closure test" not in html.lower():
        issues.append("Missing mandatory Section 5 subsection: 'The 5-Year Market Closure Test'.")
    if not any(k in html.lower() for k in ["priced in", "market-implied", "reverse dcf", "g_implied"]):
        issues.append("Missing mandatory Section 5 subsection: 'Market-Implied Expectations / Reverse DCF'.")

    # 16. Section 5 Unit Economics & 3-Scenario DCF Valuation Matrix Check
    s5_match = re.search(r"<h2>Section 5:.*?</h2>(.*?)(?=<h2>Section 6|$)", html, re.DOTALL | re.IGNORECASE)
    if s5_match:
        s5_text = s5_match.group(1)
        s5_tables = re.findall(r"<table.*?</table>", s5_text, re.DOTALL | re.IGNORECASE)
        if len(s5_tables) < 2:
            issues.append(f"Section 5 must contain at least 2 tables (Unit Economics Waterfall + DCF Matrix). Found {len(s5_tables)}.")
        
        # Verify explicit Intrinsic Fair Value / Share row
        has_fair_value_row = False
        for tbl in s5_tables:
            for r in re.findall(r"<tr.*?</tr>", tbl, re.DOTALL | re.IGNORECASE):
                r_txt = re.sub(r"<[^>]+>", " ", r).lower()
                if any(k in r_txt for k in ["intrinsic fair value", "intrinsic value / share", "intrinsic value per share", "fair value / share", "fair value per share", "fair value target"]):
                    nums = re.findall(r"\$\s*[\d,]+(?:\.\d+)?", r)
                    if len(nums) >= 2:
                        has_fair_value_row = True
                        break
        if not has_fair_value_row:
            issues.append("Section 5 DCF Table is missing the explicit 'Intrinsic Fair Value / Share' row with calculated per-share values.")

    # 17. Rejection of Synthetic Target Multipliers (Anti-Fallback Gate)
    if metadata:
        b_target = metadata.get("base_target", "")
        m_pct = re.search(r"\(([+-]?\d+(?:\.\d+)?)%\)", b_target)
        if m_pct and abs(float(m_pct.group(1)) - 15.0) < 0.2:
            bear_t = metadata.get("bear_target", "")
            if "(-25.0%)" in bear_t or "(-25.1%)" in bear_t:
                issues.append("Dossier contains uncalibrated synthetic fallback target multipliers (-25% / +15% / +50%). DCF table failed to parse.")

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
        
        s1 = _parse_p(metadata.get("story1_target") or metadata.get("bear_target"))
        s2 = _parse_p(metadata.get("story2_target") or metadata.get("base_target"))
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
            # If lowest storyline implies > 82% drop on a company that is not flagged as Distressed/Speculative
            if min_s < (cur_p * 0.18) and "speculative risk" not in str(metadata.get("status_label", "")).lower():
                issues.append(f"Economic Reality Failure: Storyline valuation target (${min_s:.2f}) represents an irrational {-((cur_p-min_s)/cur_p*100):.1f}% collapse on a going-concern business.")

    # 21. Cross-Sectional Balance Sheet & Share Count Consistency Check
    s4_match = re.search(r"<h2>Section 4:.*?</h2>(.*?)(?=<h2>Section 5|$)", html, re.DOTALL | re.IGNORECASE)
    if s4_match and s5_match:
        s4_txt = re.sub(r"<[^>]+>", " ", s4_match.group(1))
        s5_txt = re.sub(r"<[^>]+>", " ", s5_match.group(1))
        
        # Check Net Cash / Net Debt per share consistency
        s4_nd_m = re.search(r'(?:Net Cash Per (?:Diluted )?Share|Net Debt Per (?:Diluted )?Share|Net Cash Position|Net Debt Position|Net Cash|Net Debt).*?([+-]?\$?\s*\d+(?:\.\d+)?\s*(?:/sh|/share))', s4_txt, re.IGNORECASE)
        s5_nd_m = re.search(r'(?:Net Balance Sheet Debt/Cash Adjustment|Net Debt/Cash Adjustment).*?([+-]?\$?\s*\d+(?:\.\d+)?\s*(?:/sh|/share)?)', s5_txt, re.IGNORECASE)
        
        if s4_nd_m and s5_nd_m:
            try:
                s4_v = float(re.sub(r"[^\d.-]", "", s4_nd_m.group(1)))
                s5_v = float(re.sub(r"[^\d.-]", "", s5_nd_m.group(1)))
                if "net debt" in s4_nd_m.group(0).lower() and s4_v > 0:
                    s4_v = -s4_v
                if "net debt" in s5_nd_m.group(0).lower() and s5_v > 0:
                    s5_v = -s5_v
                # Check for significant discrepancy (> $0.50/share)
                if abs(s4_v - s5_v) > 0.50:
                    issues.append(f"Cross-Sectional Balance Sheet Discrepancy: Section 4 reports Net Cash/Debt of ${s4_v:+.2f}/sh, but Section 5 DCF uses ${s5_v:+.2f}/sh (diff: ${abs(s4_v - s5_v):.2f}).")
            except Exception:
                pass

    # 22. Storyline 1 Primary Target Harmonization Check
    if metadata:
        fv_str = metadata.get("fair_value_estimate", "")
        s1_str = metadata.get("story1_target", "")
        if fv_str and s1_str:
            fv_num = _parse_p(fv_str)
            s1_num = _parse_p(s1_str)
            if fv_num is not None and s1_num is not None and abs(fv_num - s1_num) > 0.05:
                issues.append(f"Storyline Target Inconsistency: Headline Fair Value (${fv_num:.2f}) does not match Storyline 1 Calculated Target (${s1_num:.2f}).")

    # 23. Discount Rate vs Growth Rate Decoupling Check (Rate Flattening Prevention)
    if s5_match:
        s5_t = s5_match.group(1)
        cagr_row = re.search(r'(?:5-Year Organic OE CAGR|5-Year CAGR).*?</tr>', s5_t, re.DOTALL | re.IGNORECASE)
        disc_row = re.search(r'(?:Discount Rate).*?</tr>', s5_t, re.DOTALL | re.IGNORECASE)
        if cagr_row and disc_row:
            cagr_nums = re.findall(r'([+-]?\d+(?:\.\d+)?%)', cagr_row.group(0))
            disc_nums = re.findall(r'(\d+(?:\.\d+)?%)', disc_row.group(0))
            if cagr_nums and disc_nums:
                try:
                    c1 = float(cagr_nums[0].replace("%", ""))
                    d1 = float(disc_nums[0].replace("%", ""))
                    if abs(c1 - d1) < 0.01 and c1 > 0:
                        issues.append(f"Rate Flattening Failure: Storyline 1 5-year CAGR ({c1:.1f}%) exactly matches Discount Rate ({d1:.1f}%), artificially neutralizing the discounting physics.")
                except Exception:
                    pass

    # 24. Exact Alert Corridor Harmonization Check
    if metadata:
        lower_alert = metadata.get("lower_alert_threshold")
        upper_alert = metadata.get("upper_alert_threshold")
        if lower_alert is not None and s_vals and cur_p:
            min_expected = min(s_vals)
            if min_expected < cur_p and abs(lower_alert - min_expected) > 0.05:
                issues.append(f"Corridor Discrepancy: Lower Alert Threshold (${lower_alert:.2f}) does not match exact Storyline Floor (${min_expected:.2f}).")

    # 25. Reverse DCF Metadata Synchronization Check
    if metadata and s5_match:
        p_in = str(metadata.get("what_is_priced_in", ""))
        s5_t = s5_match.group(1)
        m_meta_g = re.search(r"g_implied:\s*([+-]?\d+(?:\.\d+)?%)", p_in)
        m_sec5_g = re.search(r"(?:Market-Implied\s*5-Year\s*Owner\s*Earnings\s*CAGR|g_\{?(?:\\?text\{)?implied\}?\}?|g_implied).*?([+-]?\d+(?:\.\d+)?%)", s5_t, re.IGNORECASE)
        if m_meta_g and m_sec5_g:
            try:
                g_m = float(m_meta_g.group(1).replace("%", ""))
                g_s = float(m_sec5_g.group(1).replace("%", ""))
                if abs(g_m - g_s) > 1.0:
                    issues.append(f"Reverse DCF Synchronization Contradiction: Metadata header reports implied growth of {g_m:+.1f}%, but Section 5 Reverse DCF calculates {g_s:+.1f}%.")
            except Exception:
                pass

    # 26. Insider Narrative vs Ledger Consistency Check
    s4_match_all = re.search(r"<h2>Section 4:.*?</h2>(.*?)(?=<h2>Section 5|$)", html, re.DOTALL | re.IGNORECASE)
    if s4_match_all:
        s4_t = s4_match_all.group(1).lower()
        if "zero open-market insider sales" in s4_t or "zero insider sales" in s4_t or "no insider sales" in s4_t:
            # Check if Form 4 table right beside it actually lists sales
            if re.search(r"sale\s*-\s*open\s*market|s\s*-\s*sale", s4_t):
                issues.append("Insider Narrative Contradiction: Section 4 text claims 'zero insider sales' while adjacent Form 4 ledger documents open-market sales.")

    # 27. 3 Distinct Storylines Valuation Spread Check
    if metadata and s1 is not None and s2 is not None and s3 is not None:
        if abs(s1 - s2) < 0.05 and abs(s2 - s3) < 0.05:
            issues.append("Storyline Diversity Failure: All 3 storylines produced identical valuation targets. Storylines must represent 3 distinct operating trajectories.")

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
