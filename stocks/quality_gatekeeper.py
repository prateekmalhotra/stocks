"""Institutional 7-Pillar Quality Gatekeeper for Stock Research Dossiers.

Enforces zero-defect standards on every research dossier before it can be added to
the watchlist, saved to disk, or deployed to GitHub Pages.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple

THESES_DIR = Path(__file__).resolve().parent.parent / "data" / "theses"

def validate_dossier_quality(ticker: str, html: str) -> Tuple[bool, List[str]]:
    """Strictly audits a research dossier across 7 quality dimensions."""
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

    # 4. Bear / Base / Bull Scenario Valuation Matrix & Reverse DCF Presence
    has_scenarios = any(k in html.lower() for k in ["bear case", "base case", "bull case"])
    if not has_scenarios:
        issues.append("Missing complete Bear / Base / Bull scenario valuation matrix in Section 5.")
        
    has_reverse_dcf = any(k in html.lower() for k in ["priced in", "market-implied", "reverse dcf", "g_implied", "g_{implied}"])
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
        if any(k in r_clean.lower() for k in ["intrinsic fair value", "intrinsic value / share", "base intrinsic value"]):
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
            is_valid, issues = validate_dossier_quality(ticker, html)
            
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
                is_valid, issues = validate_dossier_quality(ticker, html)
                if is_valid:
                    passed_count += 1
                else:
                    failures.append({"ticker": ticker, "issues": issues, "word_count": len(html.split())})
            except Exception as e:
                failures.append({"ticker": ticker, "issues": [f"Exception loading JSON: {e}"]})

        total = passed_count + len(failures)
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
