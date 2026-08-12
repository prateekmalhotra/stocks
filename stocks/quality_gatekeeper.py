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

    # 4. Bear / Base / Bull Scenario Valuation Matrix Presence
    has_scenarios = any(k in html.lower() for k in ["bear case", "base case", "bull case"])
    if not has_scenarios:
        issues.append("Missing complete Bear / Base / Bull scenario valuation matrix in Section 5.")

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
            if is_valid:
                passed_count += 1
            else:
                failures.append({"ticker": ticker, "issues": issues, "word_count": len(html.split())})
        except Exception as e:
            failures.append({"ticker": ticker, "issues": [f"Exception loading JSON: {e}"]})
            
    return passed_count, len(failures), failures


def main():
    print("=" * 90)
    print("🛡️ RUNNING INSTITUTIONAL ZERO-DEFECT QUALITY GATEKEEPER AUDIT")
    print("=" * 90)
    
    passed_count, failed_count, failures = audit_all_theses_directory()
    total = passed_count + failed_count
    
    print(f"\n📊 Quality Gatekeeper Results: {passed_count}/{total} PASSED | {failed_count} FLAGGED\n")
    
    if failures:
        print("❌ FAILED QUALITY GATE FOR THE FOLLOWING DOSSIERS:")
        for f in failures:
            print(f"\n🚨 [{f['ticker']}] ({f.get('word_count', 0)} words):")
            for issue in f["issues"]:
                print(f"    └─ {issue}")
        print("\n❌ CI/CD Quality Gate Failed: Fix the above defects before deploying to GitHub Pages.")
        sys.exit(1)
    else:
        print("✅ ALL DOSSIERS PASSED 100% OF INSTITUTIONAL QUALITY PILLARS!")
        print("✨ Approved for deployment to GitHub Pages.")
        sys.exit(0)


if __name__ == "__main__":
    main()
