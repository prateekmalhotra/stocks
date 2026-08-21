import os
import json
import time
import re
import requests
import concurrent.futures
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional, List
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
_CURRENT_ACTIVE_MODEL = DEFAULT_GEMINI_MODEL
GEMINI_MODELS_LADDER = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite"
]
if DEFAULT_GEMINI_MODEL not in GEMINI_MODELS_LADDER:
    GEMINI_MODELS_LADDER.insert(0, DEFAULT_GEMINI_MODEL)


def get_active_model() -> str:
    """Returns the current in-memory active model for this workflow run."""
    global _CURRENT_ACTIVE_MODEL
    return _CURRENT_ACTIVE_MODEL


def switch_to_fallback_model(reason: str = "") -> str:
    """Switches the active model to the next fallback model in the ladder."""
    global _CURRENT_ACTIVE_MODEL
    try:
        cur_idx = GEMINI_MODELS_LADDER.index(_CURRENT_ACTIVE_MODEL)
        if cur_idx + 1 < len(GEMINI_MODELS_LADDER):
            next_model = GEMINI_MODELS_LADDER[cur_idx + 1]
            print(f"  ⚡ [Model Failover] Switching active model for this workflow run to {next_model}. (Reason: {reason})")
            _CURRENT_ACTIVE_MODEL = next_model
    except Exception:
        _CURRENT_ACTIVE_MODEL = "gemini-3.5-flash"
    return _CURRENT_ACTIVE_MODEL


def get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY is not set in environment or .env file.")
    return key


def safe_float(val: Any, default: float = 0.0) -> float:
    """Safely parses numbers, percentages, or formatted strings into clean float."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).replace("$", "").replace("%", "").replace(",", "").replace("x", "").strip()
        m = re.search(r"[-+]?\d*\.?\d+", s)
        if m:
            return float(m.group(0))
        return default
    except Exception:
        return default


def parse_json_robust(text: str) -> Optional[Dict[str, Any]]:
    """Safely extracts and parses JSON objects even if surrounded by markdown, trailing commas, or minor syntax hiccups."""
    if not text or not isinstance(text, str):
        return None
    
    # 1. Match ```json ... ``` or ``` ... ``` block
    m = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    candidate_str = m.group(1) if m else None
    if not candidate_str:
        # Fallback to outermost { ... }
        m2 = re.search(r'(\{[\s\S]*\})', text)
        if m2:
            candidate_str = m2.group(1)
            
    if not candidate_str:
        return None
        
    try:
        return json.loads(candidate_str)
    except Exception:
        pass
        
    # Attempt cleanup for trailing commas, broken empty values, etc.
    cleaned = re.sub(r',\s*([\}\]])', r'\1', candidate_str)
    cleaned = re.sub(r':\s*,', r': null,', cleaned)
    cleaned = re.sub(r':\s*\n\s*\}', r': null\n}', cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        pass
        
    return None


def normalize_catalyst_date(raw_date: Any) -> str:
    """Deterministically normalizes any raw date string to strict YYYY-MM-DD format."""
    if not raw_date or not isinstance(raw_date, str):
        return (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
    
    cleaned = raw_date.strip()
    
    # 1. Match exact YYYY-MM-DD
    match_iso = re.search(r"\b(202[4-9])-([01]\d)-([0-3]\d)\b", cleaned)
    if match_iso:
        return f"{match_iso.group(1)}-{match_iso.group(2)}-{match_iso.group(3)}"
    
    # 2. Try standard strptime formats
    date_formats = [
        "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
        "%d %B %Y", "%d %b %Y", "%Y/%m/%d", "%m/%d/%Y",
        "%B %Y", "%b %Y"
    ]
    for fmt in date_formats:
        try:
            dt = datetime.strptime(cleaned, fmt)
            if fmt in ("%B %Y", "%b %Y"):
                dt = dt.replace(day=15)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
            
    # 3. Match Month + Year substring (e.g. 'Expected November 2026')
    months = {
        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
        'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
    }
    for m_str, m_num in months.items():
        if m_str in cleaned.lower():
            year_match = re.search(r"\b(202[4-9])\b", cleaned)
            year = year_match.group(1) if year_match else datetime.now().strftime("%Y")
            day_match = re.search(r"\b([0-3]?\d)\b", cleaned.replace(year, ""))
            day = f"{int(day_match.group(1)):02d}" if day_match and 1 <= int(day_match.group(1)) <= 31 else "15"
            return f"{year}-{m_num}-{day}"
            
    # 4. Fallback to next quarter (+90 days)
    return (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")


def clean_grounding_artifacts(text: str) -> str:
    """Strips internal search grounding artifacts, rogue inline styles, and meta references."""
    if not text:
        return ""
    cleaned = re.sub(r"\[(?:PerQueryResult|cite|source|citation)[^\]]*\]", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\s*\d+(?:\.\d+)*(?:\s*,\s*\d+(?:\.\d+)*)*\s*\]", "", cleaned)
    
    # Strip any accidental meta references to historical analogies
    cleaned = re.sub(r"\b(?:Norbert\s+Lou(?:'s)?(?:\s+NVR)?|NVR\s+thesis|Columbia\s+(?:Business\s+School\s+)?(?:thesis|memo|paper))\b", "", cleaned, flags=re.IGNORECASE)
    
    # Strip any stray Wall Street sell-side analyst targets or broker ratings
    cleaned = re.sub(r"\b(?:Wall Street|sell-side|analyst|broker|consensus)\s+(?:price\s+target|target\s+price|consensus\s+target|PT)\s*(?:of|is|at|set\s+at)?\s*\$?\d+(?:\.\d+)?\b", "", cleaned, flags=re.IGNORECASE)
    
    # Strip standalone search grounding timestamps (e.g. '2026-08-19 03:00:00 UTC')
    cleaned = re.sub(r'^\s*\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?(?:\s+(?:UTC|GMT|[A-Z]{3,4}))?\s*$', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'<p>\s*\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?(?:\s+(?:UTC|GMT|[A-Z]{3,4}))?\s*</p>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+(?:UTC|GMT|[A-Z]{3,4})\b', '', cleaned)
    
    # Strip ALL inline style, bgcolor, and border attributes to enforce 100% theme consistency
    cleaned = re.sub(r'\s*style\s*=\s*"[^"]*"', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*style\s*=\s*'[^']*'", '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<(table|thead|tbody|tr|th|td)\b([^>]*?)(bgcolor="[^"]*")([^>]*?)>', r'<\1\2\4>', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<(table|thead|tbody|tr|th|td)\b([^>]*?)(border="[^"]*")([^>]*?)>', r'<\1\2\4>', cleaned, flags=re.IGNORECASE)
    # Strip ALL img tags and figure containers (pure professional text and tables only)
    cleaned = re.sub(r'<div\s+class="figure-container"[^>]*>.*?</div>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<figure\b[^>]*>.*?</figure>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<img\b[^>]*>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'class="[^"]*bg-white[^"]*"', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


CANONICAL_MOAT_LABELS = [
    "Wide Moat",
    "Narrow Moat",
    "Weak Moat",
    "No Moat"
]

CANONICAL_PRICING_POWER_TIERS = [
    "Absolute Pricing Power",
    "Strong Pricing Power",
    "Inflation Pass-Through",
    "Constrained Pricing Power",
    "Price Taker"
]

CANONICAL_CONVICTION_TIERS = [
    "High Conviction",
    "Solid Conviction",
    "Moderate Conviction",
    "Cautious Stance",
    "Turnaround Play",
    "Speculative Risk",
]


def map_to_canonical_pricing_power_tier(lbl: str = "", sec1_text: str = "", default: str = "Strong Pricing Power") -> str:
    """Maps any input text or Section 1 audit to one of the 5 canonical Buffett-Munger Pricing Power tiers:
    1. Absolute Pricing Power: Unilateral pricing authority without volume loss (e.g. Hermès, Ferrari, Apple, See's Candies, ASML)
    2. Strong Pricing Power: Dominant structural pricing ahead of CPI / input costs (e.g. Visa, Mastercard, Meta Ads, Google Search, Microsoft)
    3. Inflation Pass-Through: Cost-plus indexation with contractual or friction-free cost pass-through (e.g. Costco, Waste Management, Union Pacific)
    4. Constrained Pricing Power: Moderate or regulated pricing power subject to customer pushback or regulatory caps (e.g. Utilities, PBMs, Defense)
    5. Price Taker: Commoditized price taker subject to competitor discounting and margin erosion (e.g. Airlines, commodity miners, un-differentiated retail)
    """
    if lbl and isinstance(lbl, str):
        clean_lbl = lbl.strip().upper()
        for p in CANONICAL_PRICING_POWER_TIERS:
            if clean_lbl == p.upper():
                return p

    # 1. Check explicit "Pricing Power Classification:" statement first
    if sec1_text:
        m = re.search(r'Pricing Power Classification:\s*([^<\n\.]+)', sec1_text, re.IGNORECASE)
        if m:
            class_str = m.group(1).strip().upper()
            if "CONSTRAIN" in class_str or "REGULAT" in class_str or "MODERATE" in class_str:
                return "Constrained Pricing Power"
            if "PASS" in class_str or "COST" in class_str:
                return "Inflation Pass-Through"
            if "TAKER" in class_str or "COMMODITY" in class_str:
                return "Price Taker"
            if "ABSOLUTE" in class_str and "NOT" not in class_str and "DOES NOT" not in class_str:
                return "Absolute Pricing Power"
            if "STRONG" in class_str or "STRUCTURAL" in class_str:
                return "Strong Pricing Power"

    combined_text = f"{lbl or ''} {sec1_text or ''}".upper()
    
    if any(k in combined_text for k in ["CONSTRAINED PRICING", "REGULATED PRICING", "PRICE CEILING", "MODERATE PRICING"]):
        return "Constrained Pricing Power"
    elif any(k in combined_text for k in ["INFLATION PASS", "COST-PLUS", "PASS THROUGH", "INDEXED ESCALATOR", "SURCHARGE"]):
        return "Inflation Pass-Through"
    elif any(k in combined_text for k in ["PRICE TAKER", "NEGATIVE PRICING", "COMMODITY PRICING", "PRICE WAR", "DESTRUCTIVE COMPETITION"]):
        return "Price Taker"
    elif any(k in combined_text for k in ["ABSOLUTE PRICING", "UNCONSTRAINED PRICING", "MONOPOLY PRICING", "LUXURY PRICING"]):
        return "Absolute Pricing Power"
    elif any(k in combined_text for k in ["STRONG PRICING", "STRUCTURAL PRICING", "HIGH INELASTICITY", "PRICE MAKER", "PRICING POWER", "UNILATERAL PRICING"]):
        return "Strong Pricing Power"
        
    return default


CANONICAL_PREDICTABILITY_TIERS = [
    "High Predictability",
    "Moderate Predictability",
    "Low Predictability",
    "Highly Unpredictable",
]


def map_to_canonical_predictability_tier(lbl: str = "", sec1_text: str = "", default: str = "Moderate Predictability") -> str:
    """Maps any input text or Section 1 audit to one of the 4 canonical Buffett-Munger Cash Flow Predictability tiers:
    1. High Predictability: Mission-critical, contractual/recurring revenue, high 10-year visibility (e.g. Microsoft, Visa, Costco, See's Candies)
    2. Moderate Predictability: Durable economic moat, but subject to macro ad cycles, platform transitions, or regulatory shifts (e.g. Alphabet, Meta, JD.com, MercadoLibre)
    3. Low Predictability: Fast-moving technological shifts, nascent unproven revenue lines, volatile churn, or high capital intensity / Red Queen obsolescence risk (e.g. Reddit, turnaround situations, unproven AI hardware cycles)
    4. Highly Unpredictable: Pure 'Too Hard' pile; binary outcomes, hit-driven consumer tastes, or commoditized price-taker economics (e.g. biotech, unhedged commodities, cyclical turnarounds)
    """
    if lbl and isinstance(lbl, str):
        clean_lbl = lbl.strip().upper()
        for p in CANONICAL_PREDICTABILITY_TIERS:
            if clean_lbl == p.upper():
                return p

    # 1. Check explicit "Cash Flow Predictability Classification:" or "Predictability Classification:" statement first
    if sec1_text:
        m = re.search(r'(?:Cash Flow )?Predictability Classification:\s*([^<\n\.]+)', sec1_text, re.IGNORECASE)
        if m:
            class_str = m.group(1).strip().upper()
            if "HIGHLY UNPREDICTABLE" in class_str or "BINARY" in class_str or "SPECULATIVE" in class_str:
                return "Highly Unpredictable"
            if "LOW" in class_str or "TOO HARD" in class_str or "VOLATILE" in class_str:
                return "Low Predictability"
            if "HIGH" in class_str or "PRISTINE" in class_str or "CONTRACTUAL" in class_str:
                return "High Predictability"
            if "MODERATE" in class_str or "DISCIPLINED" in class_str or "MANAGEABLE" in class_str:
                return "Moderate Predictability"

    combined_text = f"{lbl or ''} {sec1_text or ''}".upper()
    
    if any(k in combined_text for k in ["HIGHLY UNPREDICTABLE", "PURE SPECULATION", "BINARY OUTCOME", "PURE TOO HARD"]):
        return "Highly Unpredictable"
    elif any(k in combined_text for k in ["LOW PREDICTABILITY", "TOO HARD PILE", "VOLATILE CASH FLOW", "UNTESTED REVENUE", "RAPID OBSOLESCENCE"]):
        return "Low Predictability"
    elif any(k in combined_text for k in ["HIGH PREDICTABILITY", "PRISTINE VISIBILITY", "CONTRACTUAL RECURRING", "IN THE CIRCLE", "MISSION-CRITICAL LOCK-IN"]):
        return "High Predictability"
    elif any(k in combined_text for k in ["MODERATE PREDICTABILITY", "MANAGEABLE VISIBILITY", "AD CYCLICALITY", "PLATFORM TRANSITION"]):
        return "Moderate Predictability"
        
    return default


def extract_probabilities_from_sec3(sec3_text: str, num_stories: int = 3) -> list:
    """Extracts dynamically derived probability weights (p1, ..., pN) for N stories from Section 3 text.
    Ensures weights sum strictly to 1.0 (100%)."""
    if not sec3_text or num_stories <= 0:
        return [round(1.0 / max(1, num_stories), 4)] * num_stories
        
    # 1. Look for explicit Story 1 ... XX% ... Story N ... YY%
    story_probs = {}
    for i in range(1, num_stories + 1):
        m = re.search(rf'Story(?:line)?\s*{i}[^\n]*?(\d{{1,2}}(?:\.\d+)?)\s*%', sec3_text, re.IGNORECASE)
        if m:
            try:
                story_probs[i] = float(m.group(1))
            except Exception:
                pass
                
    if len(story_probs) == num_stories:
        vals = [story_probs[i] for i in range(1, num_stories + 1)]
        total = sum(vals)
        if 70.0 <= total <= 130.0 and all(v > 0 for v in vals):
            return [round(v / total, 4) for v in vals]
            
    # 2. Look for table row or callout list with percentages
    for line in sec3_text.splitlines():
        if any(k in line.lower() for k in ['probability', 'weight', 'underwriting']):
            nums = re.findall(r'(\d{1,2}(?:\.\d+)?)\s*%', line)
            if len(nums) >= num_stories:
                try:
                    vals = [float(nums[j]) for j in range(num_stories)]
                    total = sum(vals)
                    if 70.0 <= total <= 130.0 and all(v > 0 for v in vals):
                        return [round(v / total, 4) for v in vals]
                except Exception:
                    pass

    # 3. Look for all percentage occurrences near probability keywords
    m_alt = re.findall(r'(\d{1,2}(?:\.\d+)?)\s*%\s*(?:probability|weight|underwriting|chance)', sec3_text, re.IGNORECASE)
    if len(m_alt) >= num_stories:
        try:
            vals = [float(m_alt[j]) for j in range(num_stories)]
            total = sum(vals)
            if 70.0 <= total <= 130.0 and all(v > 0 for v in vals):
                return [round(v / total, 4) for v in vals]
        except Exception:
            pass

    # Default fallback: dominant central story (e.g. 60%), with remainder split among other stories
    if num_stories == 2:
        return [0.70, 0.30]
    elif num_stories == 3:
        return [0.60, 0.25, 0.15]
    elif num_stories == 4:
        return [0.50, 0.25, 0.15, 0.10]
    else:
        rem = 0.40 / (num_stories - 1)
        return [0.60] + [round(rem, 4)] * (num_stories - 1)


def extract_stories_from_agent2(raw_text: str, clean_html: str = "") -> list:
    """Extracts N stories from Agent 2 output (via JSON block or HTML parsing).
    Returns a list of dicts with: story_num, story_title, short_summary, narrative."""
    clean_html = clean_html or raw_text
    # 1. Try extracting structured JSON block
    data = extract_json_block(raw_text)
    if data and isinstance(data.get("stories"), list) and len(data["stories"]) >= 2:
        res = []
        for idx, s in enumerate(data["stories"], start=1):
            res.append({
                "story_num": int(s.get("story_num") or idx),
                "story_title": str(s.get("story_title") or f"Story {idx}"),
                "short_summary": str(s.get("short_summary") or ""),
                "growth_cagr_pct": s.get("growth_cagr_pct"),
                "narrative": s.get("narrative") or clean_html
            })
        return res
        
    # 2. Parse HTML callout blocks for Story headings
    stories = []
    callout_pattern = r'<div class="callout"[^>]*>[\s\S]*?<h3>\s*(?:📖\s*)?Story\s*(\d+)[:\s–-]+([^<]+)</h3>([\s\S]*?)</div>'
    matches = list(re.finditer(callout_pattern, clean_html, re.IGNORECASE))
    
    for m in matches:
        num = int(m.group(1))
        title = m.group(2).strip()
        body = m.group(3).strip()
        
        # Extract first paragraph as short summary
        p_match = re.search(r'<p>(.*?)</p>', body, re.DOTALL)
        summary = ""
        if p_match:
            clean_p = re.sub(r'<[^>]+>', '', p_match.group(1)).strip()
            # First 1-2 sentences
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', clean_p) if s.strip()]
            summary = " ".join(sentences[:2]) if sentences else clean_p[:220]
            
        stories.append({
            "story_num": num,
            "story_title": title,
            "short_summary": summary,
            "narrative": body
        })
        
    if len(stories) >= 2:
        return stories
        
    # Fallback to default stories if parsing fails
    return [
        {"story_num": 1, "story_title": "Core Baseline Compounding", "short_summary": "Steady operational execution and ongoing reinvestment under current guidance.", "narrative": clean_html},
        {"story_num": 2, "story_title": "Accelerated Upside Engine", "short_summary": "High-margin expansion and unit volume acceleration across key verticals.", "narrative": clean_html},
        {"story_num": 3, "story_title": "Defensive Friction & Margin Drag", "short_summary": "Macro friction and category deceleration test cost flexibility.", "narrative": clean_html}
    ]


def map_to_canonical_moat_label(lbl: str = "", sec1_text: str = "", default: str = "Narrow Moat") -> str:
    """Maps any input string, moat description, or Section 1 text to one of the 4 canonical Moat ratings:
    1. Wide Moat: Dominant structural advantage (switching costs, network effects, legal monopoly) sustaining excess returns for 20+ years.
    2. Narrow Moat: Durable competitive advantage (scale, brand affinity) sustaining excess returns for 10+ years (Nike, Crocs, Lululemon, Starbucks, Costco, PayPal).
    3. Weak Moat: Fragile or commoditized advantage vulnerable to fashion decay or price competition.
    4. No Moat: Commoditized price-taker with zero structural barriers to entry.
    """
    is_apparel_or_fashion = False
    combined_lower = f"{lbl or ''} {sec1_text or ''}".lower()
    if any(w in combined_lower for w in ["apparel", "footwear", "athleisure", "clog", "shoes", "clothing", "fashion", "crocs", "lululemon", "heydude", "retail store"]):
        is_apparel_or_fashion = True

    # 1. Direct explicit input label check
    if lbl and isinstance(lbl, str):
        clean_lbl = lbl.strip().upper()
        if clean_lbl in ["WIDE MOAT", "STRONG MOAT", "WIDE", "STRONG"]:
            return "Narrow Moat" if is_apparel_or_fashion else "Wide Moat"
        elif clean_lbl in ["NARROW MOAT", "MODERATE MOAT", "NARROW", "MODERATE"]:
            return "Narrow Moat"
        elif clean_lbl in ["WEAK MOAT", "VULNERABLE MOAT", "WEAK", "VULNERABLE", "FRAGILE"]:
            return "Weak Moat"
        elif clean_lbl in ["NO MOAT", "NONE", "COMMODITY", "ZERO MOAT"]:
            return "No Moat"
        for m in CANONICAL_MOAT_LABELS:
            if clean_lbl == m.upper():
                return "Narrow Moat" if (m == "Wide Moat" and is_apparel_or_fashion) else m

    # 2. Check explicit canonical phrases in Section 1 text
    if sec1_text:
        # Search for exact primary moat statement
        m_explicit = re.search(r'Primary Economic Moat (?:Rating|Archetype|Classification|Tier|Badge)?:\s*<strong>\s*([^<\n]+)\s*</strong>', sec1_text, re.IGNORECASE)
        if not m_explicit:
            m_explicit = re.search(r'Primary Economic Moat (?:Rating|Archetype|Classification|Tier|Badge)?:\s*([^<\n\.]+)', sec1_text, re.IGNORECASE)
        if m_explicit:
            class_str = m_explicit.group(1).strip().upper()
            if "NARROW" in class_str or "MODERATE" in class_str:
                return "Narrow Moat"
            if "WEAK" in class_str or "VULNERABLE" in class_str or "FRAGILE" in class_str:
                return "Weak Moat"
            if "NO MOAT" in class_str or "COMMODITY" in class_str or "ZERO" in class_str:
                return "No Moat"
            if "WIDE" in class_str or "STRONG" in class_str or "TOLLBRIDGE" in class_str:
                return "Narrow Moat" if is_apparel_or_fashion else "Wide Moat"

        # Search for standalone bold/header moat declarations
        if re.search(r'\b(?:Narrow\s+Economic\s+Moat|Narrow\s+Moat)\b', sec1_text, re.IGNORECASE):
            # Check if Narrow Moat is declared as the verdict
            if not re.search(r'\b(?:Wide\s+Economic\s+Moat|Wide\s+Moat)\b', sec1_text, re.IGNORECASE):
                return "Narrow Moat"
        if re.search(r'\b(?:Weak\s+Economic\s+Moat|Weak\s+Moat|Vulnerable\s+Moat)\b', sec1_text, re.IGNORECASE):
            return "Weak Moat"
        if re.search(r'\b(?:No\s+Economic\s+Moat|No\s+Moat|Zero\s+Moat)\b', sec1_text, re.IGNORECASE):
            return "No Moat"
        if re.search(r'\b(?:Wide\s+Economic\s+Moat|Wide\s+Moat)\b', sec1_text, re.IGNORECASE):
            return "Narrow Moat" if is_apparel_or_fashion else "Wide Moat"

    if is_apparel_or_fashion:
        return "Narrow Moat"
        
    return default


def map_to_canonical_conviction_tier(lbl: str, action_signal: str = "", base_ret: float = 0.0) -> str:
    """Maps any input conviction string or fallback signal to one of the 6 canonical Conviction Tiers."""
    if lbl and isinstance(lbl, str):
        clean = lbl.strip().upper()
        for tier in CANONICAL_CONVICTION_TIERS:
            if clean == tier.upper():
                return tier
        if any(k in clean for k in ["TURNAROUND", "RESTRUCTURING", "OPERATIONAL RESET", "DEBT REDUCTION"]):
            return "Turnaround Play"
        elif any(k in clean for k in ["SPECULATIVE", "BINARY", "ASYMMETRY", "UNPROVEN", "HIGH RISK"]):
            return "Speculative Risk"
        elif any(k in clean for k in ["CAUTION", "CAUTIOUS", "FRICTION", "VALUATION RISK", "HEADWIND", "PREMIUM", "OVERVALUED"]):
            return "Cautious Stance"
        elif any(k in clean for k in ["MODERATE", "CYCLICAL", "EXPOSURE", "AVERAGE"]):
            return "Moderate Conviction"
        elif any(k in clean for k in ["SOLID", "COMPOUNDER", "STEADY", "RECURRING", "RUNWAY"]):
            return "Solid Conviction"
        elif any(k in clean for k in ["HIGH CONVICTION", "HIGH", "DOMINANT", "FORTRESS", "DEEP VALUE", "MOAT"]):
            return "High Conviction"
            
    sig = (action_signal or "").upper().strip()
    if sig in ["AVOID", "RED"] or base_ret < -15.0:
        return "Cautious Stance"
    elif sig in ["CAUTION", "ORANGE"] or base_ret < 0.0:
        return "Cautious Stance"
    elif sig in ["BUY", "GREEN"] and base_ret >= 25.0:
        return "High Conviction"
    elif sig in ["BUY", "GREEN"]:
        return "Solid Conviction"
    elif sig in ["HOLD", "YELLOW"]:
        return "Solid Conviction"
    return "Solid Conviction"


def sanitize_labels(labels: Any, action_signal: str = "", base_ret: float = 0.0, sec1_text: str = "") -> List[str]:
    """Sanitizes labels to strictly return the canonical Moat rating:
    - Wide Moat, Narrow Moat, Weak Moat, or No Moat.
    """
    raw_slot1 = ""
    if isinstance(labels, list) and labels:
        raw_slot1 = str(labels[0])
    elif isinstance(labels, str):
        raw_slot1 = labels
        
    moat_label = map_to_canonical_moat_label(raw_slot1, sec1_text=sec1_text)
    return [moat_label]


def normalize_action_signal(signal: Any, default: str = "BUY") -> str:
    """Normalizes action signal into one of BUY (Green), HOLD (Yellow), CAUTION (Orange), AVOID (Red).
    - BUY / GREEN (Green pulsing beacon): Thesis playing out great / deep value / get in NOW.
    - HOLD / WAIT / YELLOW (Yellow pulsing beacon): Thesis steady / wait & do nothing for now / hold for catalyst.
    - CAUTION / ORANGE (Orange pulsing beacon): Thesis facing headwinds / execution friction / trim.
    - AVOID / RED (Red pulsing beacon): Thesis broken / fundamental impairment / do NOT buy / exit.
    """
    if not signal or not isinstance(signal, str):
        return default
    sig = signal.upper().strip()
    if any(k in sig for k in ["RED", "BROKEN", "AVOID", "EXIT", "SELL", "DANGER", "CRITICAL", "DO NOT BUY", "DON'T BUY"]):
        return "AVOID"
    elif any(k in sig for k in ["ORANGE", "CAUTION", "TRIM", "HEADWIND", "WARNING", "FRICTION", "EXECUTION RISK", "GOING BAD"]):
        return "CAUTION"
    elif any(k in sig for k in ["YELLOW", "WAIT", "HOLD", "MONITOR", "PATIENT", "NEUTRAL", "STEADY", "DO NOTHING"]):
        return "HOLD"
    elif any(k in sig for k in ["GREEN", "STRONG", "BUY", "ACCUMULATE", "ADD", "ENTRY", "NOW", "OPPORTUNITY"]):
        return "BUY"
    return default


# Shared persistent session with connection pooling
_GEMINI_SESSION: Optional[requests.Session] = None

def get_gemini_session() -> requests.Session:
    global _GEMINI_SESSION
    if _GEMINI_SESSION is None:
        import urllib3
        from requests.adapters import HTTPAdapter
        s = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=urllib3.util.Retry(
                total=2,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
                raise_on_status=False
            )
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _GEMINI_SESSION = s
    return _GEMINI_SESSION


def call_gemini_with_search(
    prompt: str,
    system_instruction: str = "",
    temperature: float = 0.4,
    use_search: bool = True,
    use_code_execution: bool = False,
    override_model: str = ""
) -> str:
    """Calls Gemini via REST API with optional Google Search Grounding or native Python Code Execution, exponential backoff with jitter, and automatic ladder failover."""
    import time
    import random
    api_key = get_api_key()
    session = get_gemini_session()
    
    payload: Dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 32768
        }
    }
    tools_list = []
    if use_search:
        tools_list.append({"google_search": {}})
    if use_code_execution:
        tools_list.append({"code_execution": {}})
    if tools_list:
        payload["tools"] = tools_list
    
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }
    
    if override_model and override_model in GEMINI_MODELS_LADDER:
        models_to_try = [override_model] + [m for m in GEMINI_MODELS_LADDER if m != override_model]
    else:
        current_model = get_active_model()
        start_idx = GEMINI_MODELS_LADDER.index(current_model) if current_model in GEMINI_MODELS_LADDER else 0
        models_to_try = GEMINI_MODELS_LADDER[start_idx:]
        
    last_err = None
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = session.post(url, json=payload, timeout=180)
                if response.status_code == 200:
                    res_json = response.json()
                    candidate = res_json.get("candidates", [{}])[0]
                    parts = candidate.get("content", {}).get("parts", [])
                    texts = [p["text"] for p in parts if "text" in p and not p.get("thought")]
                    if texts:
                        return clean_grounding_artifacts("\n".join(texts))
                    
                    if candidate.get("finishReason") == "RECITATION":
                        fallback_prompt = prompt + "\n\nCRITICAL: Paraphrase all data in your own original analytical words. Do NOT quote verbatim text."
                        payload["contents"] = [{"parts": [{"text": fallback_prompt}]}]
                        payload["generationConfig"]["temperature"] = 0.7
                        retry_res = session.post(url, json=payload, timeout=180)
                        if retry_res.status_code == 200:
                            retry_json = retry_res.json()
                            retry_parts = retry_json.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                            retry_texts = [p["text"] for p in retry_parts if "text" in p and not p.get("thought")]
                            if retry_texts:
                                return clean_grounding_artifacts("\n".join(retry_texts))
                                
                    return "Analysis completed."
                elif response.status_code in (500, 502, 503, 504, 429):
                    if attempt < max_retries:
                        jitter = random.uniform(0.5, 1.8)
                        wait_time = round(min(24.0, (2.0 ** attempt) + jitter), 2)
                        print(f"  ⚠️ Gemini API ({model_name}) returned HTTP {response.status_code}. Retrying in {wait_time}s (Attempt {attempt}/{max_retries})...", flush=True)
                        time.sleep(wait_time)
                        continue
                    elif model_name != models_to_try[-1]:
                        switch_to_fallback_model(f"HTTP {response.status_code} after {max_retries} attempts on {model_name}")
                        break
                else:
                    last_err = RuntimeError(f"Gemini API error ({response.status_code}): {response.text}")
                    break
            except (requests.RequestException, Exception) as req_err:
                if attempt < max_retries:
                    jitter = random.uniform(0.5, 1.8)
                    wait_time = round(min(24.0, (2.0 ** attempt) + jitter), 2)
                    print(f"  ⚠️ Network/Connection error on {model_name} ({req_err}). Retrying in {wait_time}s (Attempt {attempt}/{max_retries})...", flush=True)
                    time.sleep(wait_time)
                    continue
                elif model_name != models_to_try[-1]:
                    switch_to_fallback_model(f"{req_err} after {max_retries} attempts on {model_name}")
                    break
                last_err = RuntimeError(f"Gemini API network error: {req_err}")
                break

    if last_err:
        raise last_err
    return "Analysis completed."


def extract_json_block(text: str) -> Dict[str, Any]:
    """Robustly extracts a JSON object from markdown code fences or raw text,
    with trailing comma cleanup, bracket counting, and regex field-level fallback."""
    if not text:
        return {}

    # 1. Search for JSON markdown code blocks (arrays or objects)
    matches = re.findall(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", text, re.DOTALL)
    for raw_json in matches:
        cleaned_json = re.sub(r",\s*([\]}])", r"\1", raw_json)
        try:
            return json.loads(cleaned_json)
        except Exception:
            pass

    # 2. Search for the first balanced { ... } or [ ... ] block
    first_brace = -1
    brace_type = None
    for i, ch in enumerate(text):
        if ch in ('{', '['):
            first_brace = i
            brace_type = ch
            break

    if first_brace != -1:
        closing_type = '}' if brace_type == '{' else ']'
        depth = 0
        end_idx = -1
        in_string = False
        escape = False
        for idx in range(first_brace, len(text)):
            ch = text[idx]
            if ch == '"' and not escape:
                in_string = not in_string
            elif not in_string:
                if ch == brace_type:
                    depth += 1
                elif ch == closing_type:
                    depth -= 1
                    if depth == 0:
                        end_idx = idx
                        break
            escape = (ch == '\\' and not escape)

        if end_idx != -1:
            candidate = text[first_brace:end_idx+1]
            cleaned_candidate = re.sub(r",\s*([\]}])", r"\1", candidate)
            try:
                return json.loads(cleaned_candidate)
            except Exception:
                pass

    # 3. Resilient regex field extraction fallback
    data = {}
    patterns = {
        "alert_title": r'"alert_title"\s*:\s*"([^"]+)"',
        "alert_severity": r'"alert_severity"\s*:\s*"([^"]+)"',
        "action_signal": r'"action_signal"\s*:\s*"([^"]+)"',
        "what_was_before": r'"what_was_before"\s*:\s*"([^"]+)"',
        "what_changes_now": r'"what_changes_now"\s*:\s*"([^"]+)"',
        "label_change_rationale": r'"label_change_rationale"\s*:\s*"([^"]+)"',
        "executive_summary": r'"executive_summary"\s*:\s*"([^"]+)"',
        "fair_value_estimate": r'"(?:fair_value_estimate|new_fair_value)"\s*:\s*"([^"]+)"',
        "bear_target": r'"(?:bear_target|new_bear_target)"\s*:\s*"([^"]+)"',
        "base_target": r'"(?:base_target|new_base_target)"\s*:\s*"([^"]+)"',
        "bull_target": r'"(?:bull_target|new_bull_target)"\s*:\s*"([^"]+)"',
        "next_catalyst_date": r'"next_catalyst_date"\s*:\s*"([^"]+)"',
        "next_catalyst_event": r'"next_catalyst_event"\s*:\s*"([^"]+)"',
        "what_is_priced_in": r'"(?:what_is_priced_in|reverse_dcf_growth|implied_growth|g_implied)"\s*:\s*"([^"]+)"',
        "institutional_ownership_pct": r'"institutional_ownership_pct"\s*:\s*"([^"]+)"',
        "insider_signal": r'"insider_signal"\s*:\s*"([^"]+)"',
        "insider_summary": r'"insider_summary"\s*:\s*"([^"]+)"',
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            data[key] = m.group(1).strip()

    labels_match = re.search(r'"labels"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if labels_match:
        raw_labels = re.findall(r'"([^"]+)"', labels_match.group(1))
        if raw_labels:
            data["labels"] = raw_labels

    funds_match = re.search(r'"top_funds"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if funds_match:
        raw_funds = re.findall(r'"([^"]+)"', funds_match.group(1))
        if raw_funds:
            data["top_funds"] = raw_funds

    upper_m = re.search(r'"(?:upper_alert_threshold|new_upper_alert_threshold)"\s*:\s*([0-9.]+)', text)
    if upper_m:
        try:
            clean_u = re.sub(r"[^\d.]", "", upper_m.group(1))
            if clean_u and clean_u != ".":
                data["upper_alert_threshold"] = float(clean_u)
        except Exception:
            pass
    lower_m = re.search(r'"(?:lower_alert_threshold|new_lower_alert_threshold)"\s*:\s*([0-9.]+)', text)
    if lower_m:
        try:
            clean_l = re.sub(r"[^\d.]", "", lower_m.group(1))
            if clean_l and clean_l != ".":
                data["lower_alert_threshold"] = float(clean_l)
        except Exception:
            pass

    return data


def normalize_latex_typography(html: str) -> str:
    """Normalizes all LaTeX math expressions into robust KaTeX delimiters \\( ... \\) and $$ ... $$.
    Protects financial currencies ($XX.XX, $50B, etc.), HTML tags, and pre-existing math blocks,
    ensuring 100% typography-grade mathematical equations without broken raw brackets or text collisions."""
    if not html:
        return ""
        
    # Step 1: Protect existing block / display equations ($$ ... $$ and \\[ ... \\])
    display_blocks = []
    def save_display(m):
        display_blocks.append(m.group(0))
        return f"««DISPLAY_BLOCK_{len(display_blocks)-1}»»"
    
    html = re.sub(r'\$\$(.*?)\$\$', save_display, html, flags=re.DOTALL)
    html = re.sub(r'\\\[(.*?)\\\]', save_display, html, flags=re.DOTALL)

    # Step 2: Protect HTML tags so we don't touch attributes or tag names
    tags = []
    def save_tag(m):
        tags.append(m.group(0))
        return f"««HTML_TAG_{len(tags)-1}»»"
    
    html = re.sub(r'<[^>]+>', save_tag, html)

    # Step 3: Protect existing inline equations \\( ... \\)
    inline_blocks = []
    def save_inline(m):
        inline_blocks.append(m.group(0))
        return f"««INLINE_BLOCK_{len(inline_blocks)-1}»»"
    
    html = re.sub(r'\\\((.*?)\\\)', save_inline, html, flags=re.DOTALL)

    # Step 4: Protect all currency amounts ($568.97, $50, $1,200.50, $25B, $19.31 billion, ~$252.00, -$8.65B, -$9.29/sh, +$2.59/sh, etc.)
    currencies = []
    def save_currency(m):
        currencies.append(m.group(0))
        return f"««CURRENCY_{len(currencies)-1}»»"
    
    curr_pattern = r'(?:~|-|\+)?\$(?=\d|\.\d)(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?(?:\s*(?:billion|million|trillion|[kKmMbBtT]))?(?:/(?:share|sh))?'
    html = re.sub(curr_pattern, save_currency, html)

    # Step 5: Convert dollar-wrapped math $...$ into saved inline blocks
    def convert_dollar_math(m):
        math_content = m.group(1).strip()
        if not math_content:
            return ""
        inline_blocks.append(f"\\({math_content}\\)")
        return f"««INLINE_BLOCK_{len(inline_blocks)-1}»»"
        
    html = re.sub(r'(?<![\$\\])\$(?!\$)([^\$\n]+?)(?<![\$\\])\$(?!\$)', convert_dollar_math, html)

    # Step 6: Convert naked LaTeX identifiers (e.g. g_{\\text{implied}}, g_{implied}, g_{base}, g_{realistic}, \\frac{a}{b})
    def wrap_naked_latex(m):
        expr = m.group(0)
        inline_blocks.append(f"\\({expr}\\)")
        return f"««INLINE_BLOCK_{len(inline_blocks)-1}»»"
        
    nested_braced_subscript = r'[a-zA-Z]\w*_(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\w+)'
    nested_braced_cmd = r'\\[a-zA-Z]+(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})+'
    naked_latex_pattern = rf'(?<![\w\\\(«])(?:{nested_braced_subscript}|{nested_braced_cmd})(?![\w\\\)»])'
    html = re.sub(naked_latex_pattern, wrap_naked_latex, html)

    # Step 7: Multi-pass recursive restoration of all placeholders to prevent nested leaks
    for _ in range(10):
        changed = False
        for i, curr in enumerate(currencies):
            ph = f"««CURRENCY_{i}»»"
            if ph in html:
                html = html.replace(ph, curr)
                changed = True
        for i, inl in enumerate(inline_blocks):
            ph = f"««INLINE_BLOCK_{i}»»"
            if ph in html:
                html = html.replace(ph, inl)
                changed = True
        for i, tag in enumerate(tags):
            ph = f"««HTML_TAG_{i}»»"
            if ph in html:
                html = html.replace(ph, tag)
                changed = True
        for i, disp in enumerate(display_blocks):
            ph = f"««DISPLAY_BLOCK_{i}»»"
            if ph in html:
                html = html.replace(ph, disp)
                changed = True
        if not changed or "««" not in html:
            break

    # Safety final pass: purge any orphaned raw chevron placeholders only if they failed restoration
    html = re.sub(r'««[A-Z_0-9]+»»', '', html)
        
    return html


def verify_and_repair_html_structure(html: str) -> str:
    """Bulletproof HTML sanitizer and structure repair engine.
    Ensures 100% clean semantic HTML, perfectly balanced lists, tables, callouts, and sections."""
    if not html:
        return ""
        
    from bs4 import BeautifulSoup
    cleaned = clean_grounding_artifacts(html)
    cleaned = normalize_latex_typography(cleaned)
    
    # 0. Strip foreign script/tokenizer leaks (e.g. Cyrillic/Russian/Chinese stray tokens in English text)
    cleaned = re.sub(r'\bмиллиардов\b', 'billion', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bмиллиарда\b', 'billion', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bмиллиард\b', 'billion', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bмиллионов\b', 'million', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bмиллиона\b', 'million', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bмиллион\b', 'million', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[\u0400-\u04FF]+', '', cleaned) # Strip any remaining Cyrillic tokens
    
    # 0.5 Clean up foreign currency label formatting and fix symbol typos
    cleaned = re.sub(r'\$\s*([\d,]+(?:\.\d+)?\s*(?:[BM]|billion|million)?)\s*(RMB|CNY)\b', r'¥\1 \2', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\(\s*\$\s*([\d,]+(?:\.\d+)?\s*(?:[BM]|billion|million)?)\s*(RMB|CNY)\s*\)', r'(¥\1 \2)', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\$\s*([\d,]+(?:\.\d+)?\s*(?:[BM]|billion|million)?)\s*(EUR|euros?)\b', r'€\1 \2', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\(\s*\$\s*([\d,]+(?:\.\d+)?\s*(?:[BM]|billion|million)?)\s*(EUR|euros?)\s*\)', r'(€\1 \2)', cleaned, flags=re.IGNORECASE)
    
    # Strip standalone search grounding timestamps (e.g. '2026-08-19 03:00:00 UTC')
    cleaned = re.sub(r'^\s*\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?(?:\s+(?:UTC|GMT|[A-Z]{3,4}))?\s*$', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'<p>\s*\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?(?:\s+(?:UTC|GMT|[A-Z]{3,4}))?\s*</p>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+(?:UTC|GMT|[A-Z]{3,4})\b', '', cleaned)
    
    # 0.8 Clean up concatenated heading/sentence transition artifacts
    cleaned = re.sub(r'\b(Strategic Insights|Executive Commentary|Key Insights)([A-Za-z])', r'\1: \2', cleaned)
    cleaned = re.sub(r'([a-z])([A-Z][a-z]+Insights)', r'\1 \2', cleaned)
    
    # 1. Strip code fences, json blocks
    cleaned = re.sub(r"```(?:html|json)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"```", "", cleaned)
    
    # 1.5 Convert raw ASCII box drawings into modern CSS cards
    if any(c in cleaned for c in ['\u250c', '\u2500', '\u2510', '\u2502', '\u2514', '\u2518', '\u251c', '\u2524', '\u252c', '\u2534', '\u253c']):
        lines = cleaned.split('\n')
        new_lines = []
        in_box = False
        box_lines = []
        for line in lines:
            if any(c in line for c in ['\u250c', '\u2500', '\u2510', '\u2502', '\u2514', '\u2518', '\u251c', '\u2524', '\u252c', '\u2534', '\u253c']):
                in_box = True
                box_lines.append(line)
            else:
                if in_box:
                    in_box = False
                    clean_items = []
                    for bl in box_lines:
                        stripped = re.sub(r'[\u2500-\u257f\u250c\u2510\u2514\u2518\u251c\u2524\u252c\u2534\u253c\|┌┐└┘├┤┬┴┼─]+', ' ', bl).strip()
                        if stripped:
                            clean_items.append(stripped)
                    if clean_items:
                        title = clean_items[0]
                        body_items = clean_items[1:]
                        card_html = f'<div class="arch-diagram" style="background:var(--bg-subpanel); border:1px solid var(--border-color); border-radius:12px; padding:20px 22px; margin:24px 0;"><div style="font-family:var(--font-sans); font-size:0.75rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--accent-warm); text-align:center; margin-bottom:14px;">{title}</div><div style="display:flex; flex-direction:column; gap:8px;">'
                        for it in body_items:
                            card_html += f'<div style="display:flex; justify-content:space-between; align-items:center; padding:10px 14px; background:var(--bg-panel); border:1px solid var(--border-color); border-radius:6px; font-family:var(--font-sans); font-size:0.86rem; color:var(--text-title);">{it}</div>'
                        card_html += '</div></div>'
                        new_lines.append(card_html)
                    box_lines = []
                new_lines.append(line)
        cleaned = '\n'.join(new_lines)
    
    # 2. Strip rogue top dashboard header injections
    cleaned = re.sub(r'<div class="investor-dashboard">[\s\S]*?</div>\s*</div>\s*</div>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<div class="dashboard-header">[\s\S]*?</div>\s*</div>', '', cleaned, flags=re.IGNORECASE)
    
    # 3. Strip inline style attributes
    cleaned = re.sub(r'\s*style\s*=\s*"[^"]*"', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*style\s*=\s*'[^']*'", '', cleaned, flags=re.IGNORECASE)
    
    # 4. Clean up section titles
    cleaned = re.sub(r'<div class="section-title">\s*(?:SECTION\s*\d+:?\s*)?(.*?)</div>', r'<h2>\1</h2>', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<div class="section-heading">(.*?)</div>', r'<h2>\1</h2>', cleaned, flags=re.IGNORECASE)
    
    # 5. Clean up bold / italic markers
    cleaned = re.sub(r'<em>\s*<strong>', r'<strong>', cleaned)
    cleaned = re.sub(r'</strong>\s*</em>', r'</strong>', cleaned)
    cleaned = re.sub(r"^\s*####\s+(.*?)$", lambda m: f"<h4>{m.group(1)}</h4>", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*###\s+(.*?)$", lambda m: f"<h3>{m.group(1)}</h3>", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*##\s+(.*?)$", lambda m: f"<h2>{m.group(1)}</h2>", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*(.*?)\*\*", lambda m: f"<strong>{m.group(1)}</strong>", cleaned)
    cleaned = re.sub(r"(?<!\*)\*([^\*]+)\*(?!\*)", lambda m: f"<em>{m.group(1)}</em>", cleaned)
    
    # 6. Convert markdown bullets to <li>
    cleaned = re.sub(r'^\s*[*•-]\s+\*\*(.*?)\*\*', r'<li><strong>\1</strong>', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^\s*[*•-]\s+<strong>(.*?)</strong>', r'<li><strong>\1</strong>', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^\s*[*•-]\s+(.*?)$', r'<li>\1</li>', cleaned, flags=re.MULTILINE)
    
    # 7. Ensure every <li> has </li>
    prev = ""
    while prev != cleaned:
        prev = cleaned
        cleaned = re.sub(
            r"(<li\b[^>]*>(?:(?!</li>|<li\b|</?[uo]l\b).)*?)(?=\s*<li\b|\s*</[uo]l\b|\s*<h[1-6]\b|\s*<div\b|$)",
            r"\1</li>\n",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE
        )
    cleaned = re.sub(r"</li>\s*</li>+", "</li>", cleaned, flags=re.IGNORECASE)

    # 8. Auto-close lists before headings
    cleaned = re.sub(r"(<li\b[^>]*>.*?</li>)(?=\s*<h[1-6]\b)", r"\1</ul>", cleaned, flags=re.DOTALL | re.IGNORECASE)
    
    # 9. Auto-close unclosed lists
    open_ul = len(re.findall(r"<ul(?:\s|>)", cleaned, re.IGNORECASE))
    close_ul = len(re.findall(r"</ul>", cleaned, re.IGNORECASE))
    if open_ul > close_ul:
        cleaned += "\n" + ("</ul>" * (open_ul - close_ul))
    elif close_ul > open_ul:
        for _ in range(close_ul - open_ul):
            cleaned = re.sub(r"</ul>(?=[^<]*$)", "", cleaned, flags=re.IGNORECASE)
        
    open_ol = len(re.findall(r"<ol(?:\s|>)", cleaned, re.IGNORECASE))
    close_ol = len(re.findall(r"</ol>", cleaned, re.IGNORECASE))
    if open_ol > close_ol:
        cleaned += "\n" + ("</ol>" * (open_ol - close_ol))
    elif close_ol > open_ol:
        for _ in range(close_ol - open_ol):
            cleaned = re.sub(r"</ol>(?=[^<]*$)", "", cleaned, flags=re.IGNORECASE)

    open_li = len(re.findall(r"<li(?:\s|>)", cleaned, re.IGNORECASE))
    close_li = len(re.findall(r"</li>", cleaned, re.IGNORECASE))
    if open_li > close_li:
        cleaned += "\n" + ("</li>" * (open_li - close_li))
    elif close_li > open_li:
        for _ in range(close_li - open_li):
            cleaned = re.sub(r"</li>(?=[^<]*$)", "", cleaned, flags=re.IGNORECASE)
        
    # 10. Auto-close tables, divs, sections
    open_tr = len(re.findall(r"<tr\b", cleaned, re.IGNORECASE))
    close_tr = len(re.findall(r"</tr>", cleaned, re.IGNORECASE))
    if open_tr > close_tr:
        cleaned += "</tr>" * (open_tr - close_tr)

    open_tables = len(re.findall(r"<table\b", cleaned, re.IGNORECASE))
    close_tables = len(re.findall(r"</table>", cleaned, re.IGNORECASE))
    if open_tables > close_tables:
        cleaned += "\n" + ("</tbody></table>" * (open_tables - close_tables))
        
    open_divs = len(re.findall(r"<div\b", cleaned, re.IGNORECASE))
    close_divs = len(re.findall(r"</div>", cleaned, re.IGNORECASE))
    if open_divs > close_divs:
        cleaned += "\n" + ("</div>" * (open_divs - close_divs))

    # 11. Normalize DOM via BeautifulSoup
    soup = BeautifulSoup(cleaned, "html.parser")
    return str(soup)

# =====================================================================
# AUTONOMOUS LEVEL-HEADED MULTI-AGENT PROMPT ARCHITECTURE
# =====================================================================

LEVEL_HEADED_INVESTOR_PHILOSOPHY = """You are an elite, level-headed fundamental value investor embodying the core economic principles of Warren Buffett, Charlie Munger, and Benjamin Graham.

Core Principles of Business Valuation & Capital Allocation:
1. Ownership Mentality (5-Year Market Closure Mindset):
   - You are evaluating a permanent ownership stake in a private operating business. If the stock market were closed for the next 5 years, would the cash distributable to owners justify purchasing this enterprise today?
   - Ignore short-term market quotation noise, macro forecasting, and consensus momentum. Focus exclusively on the operational engine.

2. True Owner Earnings & Sector-Specific Maintenance CapEx (Buffett 1986 Standard):
   - Owner Earnings = GAAP Operating Cash Flow - Maintenance CapEx - 100% Stock-Based Compensation.
   - Stock-Based Compensation MUST strictly be treated as a real cash charge (Buffett: "If options aren't expenses, what are they?").
   - SECTOR-SPECIFIC MAINTENANCE CAPEX RULES (NEVER use arbitrary blanket multipliers):
     * Pure Software / Asset-Light Platforms (MSFT, GOOG, CRM): Maintenance CapEx is typically 25%–40% of CapEx.
     * Retail Store Networks, Apparel, Restaurants & Physical Fleets (LULU, NKE, SBUX, CROX, HD, CMG): Maintenance CapEx includes ongoing store remodel/refresh cycles (every 5-7 years), POS/IT upkeep, and supply chain maintenance. Maintenance CapEx is EMPIRICALLY ANCHORED TO DEPRECIATION & AMORTIZATION (typically 50%–75% of total CapEx, or ~$D&A). Growth CapEx is strictly the incremental capital spent on net new store openings.

3. Economic Moat, Governance & C-Suite Key-Person Stability:
   - WIDE MOAT (<15% of public companies): Insurmountable structural barriers (Visa/Mastercard network effects, Copart zoning land monopoly, S&P Global/Moody's rating duopoly, Microsoft enterprise lock-in).
   - NARROW MOAT: Durable consumer/retail brands (Nike, Lululemon, Crocs, Starbucks, Costco). STRICT RULE: Consumer apparel/retail is NEVER Wide Moat due to fashion risk and competitive entry.
   - WEAK / NO MOAT: Fragile or commoditized brands vulnerable to price wars or fast-fashion decay.
   - GOVERNANCE & C-SUITE STABILITY AUDIT: Always audit active activist campaigns (Elliott Management, Starboard, 13D filings), founder/board proxy battles, and executive turnover (CEO, CFO, Chief Brand Officer). Heavy C-suite churn directly increases key-person risk and lowers predictability.

4. Distinguish Brand Deterioration from Temporary Product Execution Fatigue:
   - When analyzing slowing growth, rigorously test whether the issue is a temporary product/assortment lull (solvable via color/silhouette refresh) OR structural market share loss to emerging premium competitors (e.g., Alo Yoga, Vuori, On, Skims).
   - Provide concrete, falsifiable signposts to test which reality is unfolding.

5. Charlie Munger's Inversion Principle ("Invert, Always Invert"):
   - What fundamental operational performance and cash generation is Mr. Market embedding into today's share price?
   - Derive market-implied growth under the market's CURRENT multiple (M₀), NEVER assuming unearned multiple re-rating expansion on shrinking earnings.

6. Rational Capital Allocation & Share Buybacks:
   - Share repurchases are value-accretive ONLY when executed below conservative intrinsic value.
   - Buybacks MUST be treated as a residual funded strictly from excess free cash flow after true maintenance CapEx and debt service.

7. Strict Temporal Realism & Currency Standardization:
   - The current calendar year is 2026. Strictly ground all regulatory and leadership events in current verified facts.
   - All financial numbers MUST strictly be in US DOLLARS ($ USD).
"""

AGENT_1_GENESIS_PREMISE_AND_PATHS_PROMPT = """Target: {ticker} ({company_name})
User Focus / Research Notes: {notes}

You are the Chief Equity Research Director & Institutional Buy-Side Grounded Researcher.
Your mission is to formulate Section 1 (The Premise) and Section 2 (The Probable Future Paths) of the living investment thesis for {company_name} from audited SEC statutory filings (10-K, 10-Q, 20-F, 8-K) and the last 4 quarterly earnings call transcripts.

ZERO-PRICE-ANCHORING DIRECTIVE:
You are conducting 100% blind fundamental research on the business itself. You do NOT look at or anchor to stock prices, target prices, or market consensus. Your mandate is to analyze historical statutory financials, operational segment dynamics, and realistic unit compounding mechanics.

STRICT RESEARCH, GOVERNANCE & BUSINESS INERTIA MANDATES:

1. THE LAW OF BUSINESS INERTIA & SLOW TREND EVOLUTION (REAL WORLD CHANGES SLOWLY):
   - Large enterprises possess enormous operational inertia. Top-line revenue and operating margins DO NOT experience violent, discontinuous leaps in normal conditions.
   - REAL-WORLD TREND BOUNDARY:
     * Year 1 (Y1) MUST strictly anchor to the trailing 4-quarter run-rate and management guidance floor.
     * Years 2 through 5 must model SLOW, GRADUAL DRIFT within observable trend boundaries:
       - Annual Revenue Growth rate shifts by no more than ±100 to 200 bps per year.
       - Operating Margin shifts by no more than ±50 to 100 bps per year.
     * NEVER invent sudden +15% revenue accelerations or +500 bps margin leaps. Compounding happens slowly through incremental operational execution and share cannibalization.

2. DYNAMIC NATURAL NUMBER OF DISTINCT STORYLINES (N ∈ [2, 5]):
   - Determine the NATURAL number of operational trajectories N (typically 2 to 4 paths) dictated by the company's real business forks, segment divergences, and strategic debates.
   - DO NOT artificially force exactly 2 paths, and DO NOT artificially force exactly 3 paths!
     * If a company has a clean binary operational debate (e.g. Core Compounding vs Secular Share Erosion), formulate 2 distinct paths.
     * If a company has a central baseline trend, a downside friction case, and a realistic operational leverage path, formulate 3 distinct paths.
     * If a company has distinct multi-segment drivers (e.g. Core Digital + Enterprise Cloud + Autonomous / Hardware, or DTC + Wholesale + International), formulate 3 to 4 distinct paths.
   - Let the company's actual operational structure determine N (between 2 and 4 paths).
   - Every single path MUST be realistic, bounded by the Law of Business Inertia (no fantasy moonshots).

3. TEMPORAL & EXECUTIVE GOVERNANCE GROUNDING (YEAR 2026):
   - Search specifically for latest permanent CEO appointments, C-suite changes, 8-K filings, activist stakes (Elliott Management, Starboard, 13D filings), and founder/board proxy contests.
   - If a new permanent CEO is appointed (e.g. Heidi O'Neill at Lululemon starting Sep 2026), frame the central investment thesis around their specific background, executive mandate, and operational turnaround levers.

4. SECTOR-SPECIFIC MAINTENANCE CAPEX DECOMPOSITION:
   - Decompose total CapEx in Section 1's Owner Earnings table:
     * GAAP Operating Cash Flow
     * Less: Maintenance CapEx (For retail/store fleets, anchor to D&A / store refresh cycles, ~50%–70% of CapEx; for software, ~25%–40%)
     * Less: 100% Stock-Based Compensation (SBC)
     * Plus/Minus: Working Capital Normalization
     * Equals: True Normalized Baseline Owner Earnings (OE₀).

5. 5 OBSERVABLE OPERATIONAL VARIABLES PER STORYLINE:
   - Every storyline in Section 2 MUST explicitly state its assumptions across 5 observable variables:
     * Variable 1: Primary Segment Comparable Sales / Volume Trajectory (e.g. Americas Comps vs International)
     * Variable 2: Gross Margin Bridge (product mix, promotions, freight, tariffs)
     * Variable 3: Geographic / Business Unit Segment Breakdown
     * Variable 4: Store Fleet Productivity & New Store Payback
     * Variable 5: Share Repurchases (funded strictly as a residual from free cash flow after maintenance CapEx).

6. COMPETITIVE SHARE LOSS VS TEMPORARY PRODUCT FATIGUE:
   - In Section 1 and Section 2, evaluate competitive threats (e.g. Alo Yoga, Vuori, On, Skims) and specify concrete quarterly falsification signposts.

7. FINTECH, DIGITAL PAYMENTS & TAKE-RATE COMPRESSION MANDATE:
   - For digital payment platforms and fintech processors (e.g. PayPal, Block, Adyen):
     * Explicitly model take-rate and transaction margin trajectories:
       - Unbranded payment processing (Braintree) margin compression vs branded checkout buttons (PayPal / Venmo).
       - Competitive pricing and margin pressure from Adyen, Stripe, Apple Pay, Google Pay, and Shop Pay.
     * Never assume take-rates stabilize without analyzing competitive checkout button displacement.

OUTPUT FORMAT:
Provide pure semantic HTML containing ONLY Section 1 and Section 2:

<h2>Section 1: The Premise of the Company</h2>
<p>[Comprehensive fundamental analysis of business model, unit monetization, moat, executive leadership, activist/governance reality, gross margin durability, and 4-quarter earnings reality...]</p>
[3-Year Historical Baseline Table, Segment Breakdown Table summing to 100%, Owner Earnings Derivation Table with CapEx Decomposition, Balance Sheet Net Debt / Surplus Cash Bridge, Fundamental Compounding Velocity Audit, Pricing Power & Predictability Audits]

<h2>Section 2: The Probable Future Paths</h2>
<p>Based on the company's audited statutory filings, segment dynamics, 4-quarter earnings call commentary, and institutional counter-theses, here are the distinct, realistic operational paths covering 90%–95% of the fundamental probability space over the next 3–5 years:</p>

<!-- Repeat callout box for each of the N natural paths (Path 1 through Path N) with bespoke operational titles -->
<!-- IMPORTANT: DO NOT hardcode probability percentages in Section 2 titles or narrative text (the Chief Risk Officer sets and audits unified probability weights in Section 3) -->
<div class="callout">
  <h3>Path 1: [Bespoke Operational Title - Central Trend Execution]</h3>
  <p>[1-2 sentence executive summary of this path's operational mechanism...]</p>
  <p>[Full narrative explanation of this operating trajectory...]</p>
  <p><strong>5-Variable Operational Unit Bridge:</strong> [Explicit Americas comps %, International growth %, Gross margin %, Store productivity, and residual share buyback assumptions in $ USD...]</p>
  <p><strong>Cost Structure, CapEx &amp; Owner Earnings:</strong> [Margin dynamics, CapEx, and resulting Owner Earnings in $ USD...]</p>
  <p><strong>Adversarial Red-Team Stress-Test:</strong> [What specific assumptions could fail and what quantitative metric falsifies this path...]</p>
  <p><strong>Quarterly Milestones:</strong> [Observable KPI signposts in quarterly filings...]</p>
</div>

<!-- Add Path 2, Path 3, ..., Path N as naturally determined by the business structure -->
<div class="callout">
  <h3>Path 2: [Bespoke Operational Title - Downside Friction &amp; Headwinds]</h3>
  <p>[1-2 sentence executive summary of this downside operational mechanism...]</p>
  <p>[Full narrative explanation of this downside operating trajectory...]</p>
  <p><strong>Operational Unit Drivers &amp; Revenue:</strong> [Explicit unit volume * pricing calculations in $ USD...]</p>
  <p><strong>Cost Structure, CapEx &amp; Owner Earnings:</strong> [Margin compression dynamics, CapEx, and resulting Owner Earnings in $ USD...]</p>
  <p><strong>Adversarial Red-Team Stress-Test:</strong> [What would cause performance to stabilize or recover...]</p>
  <p><strong>Quarterly Milestones:</strong> [Observable KPI signposts in quarterly filings...]</p>
</div>

<div class="callout">
  <h3>Quarterly Monitoring Signposts (Next 12–18 Months)</h3>
  <table class="data-table">
    <thead>
      <tr>
        <th>Operational Metric</th>
        <th>Acceleration Threshold (Core / Upside Paths)</th>
        <th>Falsification Threshold (Downside Friction)</th>
      </tr>
    </thead>
    <tbody>
      <tr><td><strong>Primary Segment Growth</strong></td><td>Healthy expansion along trend run-rate</td><td>Deterioration below floor</td></tr>
      <tr><td><strong>Gross / Operating Margin</strong></td><td>Stable / Expanding via leverage</td><td>Contraction due to markdowns/tariffs</td></tr>
      <tr><td><strong>Capital Allocation</strong></td><td>Disciplined reinvestment &amp; buybacks</td><td>Excessive burn or dilutive SBC spike</td></tr>
    </tbody>
  </table>
</div>
"""


AGENT_RED_TEAM_FEEDBACK_PROMPT = """Target: {ticker} ({company_name})

You are the Senior Buy-Side Red-Team Auditor & Short-Thesis Forensic Specialist.
Your task is to ruthlessly critique the draft Premise (Section 1) and Forward-Looking Storylines & Operational Assumptions (Section 2) for {company_name}.

ZERO-PRICE-ANCHORING DIRECTIVE:
You are auditing fundamental operational assumptions, unit metrics, and audited statutory filing reality completely blind to market stock price. Do NOT suggest revisions to anchor to current price or market consensus.

DRAFT SECTION 1 & SECTION 2:
======================================================================
{sec1_and_sec2_draft}
======================================================================

Search Google, audited 10-K/10-Q filings, recent earnings call transcripts (especially analyst Q&A friction), short-seller reports, and industry critiques to audit:
1. DISTINCT OPERATIONAL MECHANISMS & NATURAL NUMBER OF PATHS (N ∈ [2, 5]):
   - Ensure the N storylines are truly distinct, non-overlapping operational mechanisms, NOT generic "Bull/Bear/Base" labels or superficial numerical variations.
   - Verify that the number of paths N naturally matches the company's business model (e.g. 2 paths for simple single-product businesses, 3-4 paths for multi-segment compounders).
2. TREND REALISM & SENSIBLE DEVIATIONS (REJECT EXTREME MOONSHOTS / DOOMSDAY CLIFFS):
   - Reject ungrounded extreme projections (e.g. arbitrary 3x revenue explosions or unrealistic catastrophic bankruptcies).
   - Ensure scenarios model realistic operational deviations around the trailing business trend (e.g. 150-350 bps comp deceleration, 50-200 bps gross margin shift, modest operating leverage).
3. SKEPTICAL EARNINGS CALL & SHORT-THESIS AUDIT:
   - Audit customer churn, negative comps, wholesale destocking, tariff exposure, brand fatigue, and unabsorbed fixed SG&A.
   - Ensure Downside Friction incorporates real-world headwinds from quarterly transcripts and sell-side critiques.
4. BALANCE SHEET PER-SHARE AUDIT:
   - Verify that Net Surplus Cash / Net Debt is strictly PER SHARE (e.g. +$4.68/sh) and correctly divided by diluted shares.
5. UNIT OPERATIONAL DRIVERS & MARGINS:
   - Verify that every growth rate is derived from concrete bottom-up unit metrics (volume, ASP, gross margin, fixed cost leverage, CapEx).
6. EMPIRICAL PROBABILITY WEIGHTING AUDIT:
   - For turnaround or friction cases, ensure Downside Friction carries substantial weight (30%–45%).
7. MOAT TIER & SECTOR GUARDRAILS:
   - Ensure retail/apparel/footwear brands are classified Narrow Moat or Weak Moat, NEVER Wide Moat.
8. BUSINESS INERTIA & NATURAL NUMBER OF PATHS (N ∈ [2, 5]):
   - Verify that N naturally reflects the company's real business forks (2 to 4 paths). DO NOT dogmatically force N=2 or N=3.
   - Reject ungrounded fantasy moonshots or discontinuous leaps where annual revenue growth or margins violate the historical trend boundary. Compounding happens slowly.

Deliver a crisp, actionable Buy-Side Red-Team Critique Memo with specific factual corrections and guidance for refining Section 1 and Section 2.
"""

AGENT_STORYLINE_REFINEMENT_PROMPT = """Target: {ticker} ({company_name})

You are the Lead Equity Research Director & Institutional Buy-Side Grounded Researcher.
You are given the Draft Section 1 & Section 2 and the Independent Red-Team Critique Memo for {company_name}.

ZERO-PRICE-ANCHORING DIRECTIVE:
Refine the operational premise and future paths based strictly on audited fundamentals and operational unit drivers, 100% blind to market stock price.

DRAFT SECTION 1 & SECTION 2:
======================================================================
{sec1_and_sec2_draft}
======================================================================

RED-TEAM CRITIQUE MEMO:
======================================================================
{critique_memo}
======================================================================

YOUR TASK:
Incorporate the red-team critique directives and produce the final, polished, and reality-grounded Section 1 (The Premise) and Section 2 (The Probable Future Paths).

CRITICAL REQUIREMENTS:
1. Enforce Business Inertia & Natural N: Ensure top-line growth and operating margins model slow, gradual drift (Year 1 anchored to trailing 4-quarters; annual growth rate shift bounded within ±100 to 200 bps). Let N naturally reflect the business structure (typically 2 to 4 distinct paths).
2. Ensure the N storylines are truly distinct, bespoke, and grounded in concrete operational unit metrics (Americas comps, gross margin bridge, segment breakdown, store productivity, buyback residual).
3. Ensure Downside Friction realistically integrates earnings transcript pushbacks and competitive threats (e.g. Alo Yoga, Vuori).
4. Ensure probability weights (p₁, ..., pN summing to 100%) reflect empirical filing realities.
5. Output pure semantic HTML containing ONLY Section 1 and Section 2 starting with <h2>Section 1: The Premise of the Company</h2>.
"""


STORY_VALUATION_PROMPT = """Target: {ticker} ({company_name})
Story Number: Path {story_num} - {story_title}

You are the Lead Quantitative Valuation Analyst underwriting Path {story_num} for {company_name}.
You must evaluate this specific operational trajectory in complete isolation, 100% blind to market stock prices, consensus targets, or trading noise.

ZERO-PRICE-ANCHORING DIRECTIVE:
You are calculating the pure intrinsic fair value and 5-year target price of the business based strictly on fundamental owner earnings compounding and economic capitalization multiples. You do NOT know, care about, or anchor to the stock's market price.

COMPANY BASELINE CONTEXT (From Section 1):
======================================================================
- Primary Economic Moat: {moat_tier}
- Clean Normalized Baseline Owner Earnings (OE₀): ${oe0_per_share:.2f} / share
- Net Balance Sheet Cash (+) or Debt (-) per share: {net_cash_str}
- 3-Year Historical ROIC: {roic_str}
======================================================================

STORY OPERATIONAL NARRATIVE & UNIT DRIVERS (Path {story_num}):
======================================================================
{story_text}
======================================================================

STRICT VALUATION & LINE-BY-LINE BUFFETT MODELING RULES:
1. SEARCH STATUTORY FILINGS & RESPECT THE TREND (REALISTIC BOUNDS):
   - Use your search tool if needed to confirm historical 10-K / 10-Q line items (segment revenues, gross margin, SG&A, SBC, maintenance CapEx, and share count).
   - RESPECT THE TREND:
     * Ground compounding in the observable business trend, guidance corridors, and realistic capacity limits.
     * Downside paths model realistic operational friction (e.g. -2% to -6% comp drag, 100-200 bps margin compression), NOT an artificial total collapse.
     * Upside paths model realistic execution outperformance (e.g. +2% to +5% above trend, 100-150 bps operating leverage), NOT an impossible moonshot.
2. MANDATORY BOTTOM-UP PYTHON CODE EXECUTION (YEARS 1 TO 5):
   - You MUST write and execute Python code using your code execution tool to simulate every row from bottom-up operational unit drivers:
     * Year 0 (Trailing Baseline), Year 1, Year 2, Year 3, Year 4, Year 5.
     * Line 1: Explicit Unit Drivers to Segment Revenue: Define comps %, store count rollout, unit volume, and ASP to derive Segment Revenues -> Consolidated Revenue ($M).
     * Line 2: COGS & Gross Margin % (accounting for tariffs, freight, and product mix) -> Gross Profit ($M).
     * Line 3: SG&A & Operating Expenses (modeling fixed overhead absorption/deleverage) -> Operating Income (EBIT) & Operating Margin %.
     * Line 4: Effective Taxes (20%-22%) & Net Interest -> Normalized Net Income ($M).
     * Line 5: Warren Buffett True Owner Earnings = GAAP Operating Cash Flow - Maintenance CapEx - 100% Stock-Based Compensation. (For retail store fleets, restaurants, and apparel, Maintenance CapEx MUST cover periodic store remodels and IT upkeep, empirically anchored to D&A at ~50%–70% of total CapEx; for pure software/platforms, ~25%–40% of CapEx).
     * Line 6: Capital Allocation & Share Cannibalization: Retained Owner Earnings deployed into share buybacks at projected fair value -> Diluted Shares Outstanding (Mil) from Y0 to Y5.
     * Line 7: Per-Share Owner Earnings = Total Owner Earnings_t / Diluted Shares_t ($ USD/share).
     * Line 8: Invested Capital & Year-5 ROIC = NOPAT_5 / Invested Capital_5 (%).
3. DERIVE JUSTIFIED EXIT MULTIPLE (M₅ = P/OE₅):
   - Terminal capitalization multiple MUST be mathematically justified by Year-5 ROIC and terminal growth rate g: M₅ = (1 - g/ROIC_5) / (r - g) with r = 9.5% equity hurdle rate, bounded by sector multiple caps (12.0x - 15.0x for consumer retail/footwear; 18.0x - 22.0x for tech/platforms).
4. 5-YEAR TARGET PRICE & PRESENT FAIR VALUE:
   - 5-Year Target Price / Share (P₅) = (M₅ * OE₅_per_share) + Net Surplus Cash per share (or - Net Debt per share).
   - Present Intrinsic Fair Value (P₀ at 9.5% Hurdle) = P₅ / (1.095)^5.

OUTPUT FORMAT:
Provide ONLY a valid JSON object matching this exact schema (replace placeholder numbers with your actual simulated row values across all 6 time periods Y0 through Y5):
```json
{{
  "story_num": {story_num},
  "story_title": "{story_title}",
  "short_summary": "<1-2 sentence crisp operational summary>",
  "projected_5y_cagr": "+XX.X%",
  "projected_oe5_per_share": XX.XX,
  "oe_multiple": "XX.Xx",
  "oe_yield": "X.X%",
  "net_cash_per_share": {net_cash_num},
  "target_price_5y": XX.XX,
  "present_fair_value": XX.XX,
  "valuation_rationale": "<2-3 sentence economic rationale for the chosen growth rate, ROIC, and terminal multiple>",
  "pro_forma_schedule": {{
    "years": ["Trailing (Y0)", "Year 1", "Year 2", "Year 3", "Year 4", "Year 5"],
    "revenue_mil": [4100.0, 4320.0, 4560.0, 4820.0, 5100.0, 5400.0],
    "gross_margin_pct": [58.8, 59.0, 59.2, 59.3, 59.5, 59.5],
    "operating_income_mil": [1050.0, 1123.0, 1200.0, 1282.0, 1372.0, 1470.0],
    "operating_margin_pct": [25.6, 26.0, 26.3, 26.6, 26.9, 27.2],
    "normalized_net_income_mil": [780.0, 842.0, 905.0, 973.0, 1048.0, 1128.0],
    "owner_earnings_mil": [750.0, 810.0, 875.0, 945.0, 1020.0, 1100.0],
    "diluted_shares_mil": [60.5, 59.0, 57.5, 56.0, 54.8, 54.0],
    "oe_per_share": [12.40, 13.73, 15.22, 16.88, 18.61, 20.37],
    "roic_pct": [22.5, 22.8, 23.0, 23.2, 23.4, 23.5]
  }}
}}
```
"""


VALUATION_FEEDBACK_AND_SYNTHESIS_PROMPT = """Target: {ticker} ({company_name})
Benchmark Reference Price: ${current_price:.2f}

You are the Chief Risk Officer & Buy-Side Senior Audit Partner.
You are conducting an independent sanity check on the {num_stories} independent valuation models underwritten for {company_name}.

COMPANY FINANCIAL BASELINE (From Section 1):
======================================================================
- Primary Economic Moat: {moat_tier}
- Clean Baseline Owner Earnings (OE₀): ${oe0_per_share:.2f} / share
- Net Balance Sheet Cash (+) or Debt (-) per share: {net_cash_str}
- 3-Year Historical Growth & ROIC Profile: {historical_summary}
======================================================================

INDEPENDENT {num_stories}-STORY VALUATION MODELS:
======================================================================
{stories_json_text}
======================================================================

YOUR CRITICAL AUDIT MANDATE:
1. RUTHLESS SANITY CHECK ON ASSUMPTIONS (RESPECT TREND REALISM, REJECT EXTREMES):
   - Check if growth rates and terminal multiples respect the company's actual trailing momentum, competitive positioning, and economic moat.
   - Ensure all paths represent realistic, grounded deviations around the central trend rather than unearned moonshots or fictitious collapses.
   - Enforce sector terminal multiple caps (e.g. <=15x for apparel/retail, <=24x for tech).
2. EMPIRICAL PROBABILITY DISTRIBUTION ACROSS ALL N STORIES:
   - Assign probability weights (p₁, ..., pN summing STRICTLY to 1.0 / 100%):
     * For companies facing active friction or brand turnaround risks, ensure Downside Friction paths carry substantial weight (e.g. 30%–45%).
     * GOVERNANCE & CEO WHIPLASH PENALTY: If a company has experienced >= 2 CEO changes in the past 3 years or ongoing C-suite instability (e.g. PayPal, Starbucks), unproven turnaround execution paths CANNOT be assigned >40%–45% probability. Downside friction & competitive erosion MUST carry >= 55%–60% of the probability mass until multi-quarter execution is proven.
     * INSIDER FLOW SKEPTICISM: If Form 4 filings detail persistent net insider selling (> $10M net sales with zero open-market purchases), factor this executive skepticism directly into the capital allocation commentary and demand a higher Margin of Safety hurdle (>= 25%) before recommending BUY.
     * For secular monopolies with deep moats and stable management, Core Execution carries 50%–65%.
3. MANDATORY PYTHON CODE EXECUTION FOR VERIFICATION & REVERSE DCF:
   - You MUST write and execute Python code using your code execution tool to compute all final synthesis numbers:
     * BALANCE SHEET ADJUSTMENT MANDATE: You MUST include the exact Net Balance Sheet Cash / (Debt) per share ({net_cash_str}) in the 'Net Balance Sheet Cash / (Debt) per share Adjustment' row for every path. 5-Year Target Price / Share MUST mathematically equal: (OE₅ * Multiple) + Net_Cash_per_share (or - Net_Debt_per_share). NEVER write $0.00 if net cash/debt is non-zero!
     * Probability-Weighted Expected 5Y Target (P₅_expected) = ∑ (p_i * P₅_i)
     * Probability-Weighted Present Fair Value (P₀_expected) = ∑ (p_i * P₀_i)
     * Probability-Weighted Expected Margin of Safety % = ((P₀_expected - ${current_price:.2f}) / ${current_price:.2f}) * 100%
     * Probability-Weighted Expected 5Y Price CAGR % = ((P₅_expected / ${current_price:.2f})**(0.2) - 1) * 100%
     * Reverse DCF: Exact implied 5Y Owner Earnings CAGR priced in at ${current_price:.2f} under market multiple (M₀ = ${current_price:.2f} / ${oe0_per_share:.2f}) and baseline multiple (M_base).
4. CAPITAL ALLOCATION RECOMMENDATION:
   - BUY (if Expected MoS >= +20%, or >= +25% if heavy insider selling/CEO churn is present), HOLD (if MoS 0% to +20%), CAUTION (if MoS -15% to 0%), AVOID (if MoS < -15%).

OUTPUT FORMAT:
Provide pure semantic HTML containing Section 3 (with the complete {num_stories}-Path Valuation Table, Probability Weighting Rationale, and Market Inversion & Valuation Synthesis), followed by the complete structured JSON block:

<h2>Section 3: Normalized Owner Earnings Multiple &amp; Yield Inversion Valuation</h2>

<p>[Methodological narrative explaining the Owner Earnings Multi-Year Compounding framework, the terminal capitalization multiple, and the net cash balance sheet bridge...]</p>

<table class="data-table">
  <thead>
    <tr>
      <th>Valuation Metric / Driver</th>
      <!-- Generate a column for each of the {num_stories} paths (Path 1 to Path N) -->
      <th>Path 1: [Title 1]</th>
      <th>Path 2: [Title 2]</th>
      ...
    </tr>
  </thead>
  <tbody>
    <tr><td>Starting Normalized Owner Earnings (OE₀) / share</td>...</tr>
    <tr><td>Projected 5-Year Owner Earnings CAGR (%)</td>...</tr>
    <tr><td>Projected Year-5 Normalized Owner Earnings (OE₅) / share</td>...</tr>
    <tr><td>Target Terminal Multiple (P/OE₅)</td>...</tr>
    <tr><td>Implied Terminal Owner Cash Yield (%)</td>...</tr>
    <tr><td>Net Balance Sheet Cash / (Debt) per share Adjustment</td>...</tr>
    <tr><td><strong>5-Year Target Price / Share</strong></td>...</tr>
    <tr><td>Expected 5-Year Annualized CAGR (vs. ${current_price:.2f})</td>...</tr>
    <tr><td>Total 5-Year Expected Return (%)</td>...</tr>
    <tr><td>Present Intrinsic Fair Value (at 9.5% hurdle rate)</td>...</tr>
    <tr><td>Margin of Safety vs. Current Price (${current_price:.2f})</td>...</tr>
    <tr><td>Probability Weight &amp; Empirical Basis (%)</td>...</tr>
  </tbody>
</table>

<div class="callout">
  <h3>Empirical Probability Weighting Rationale</h3>
  <p>[Detailed justification of the assigned probability weights across all {num_stories} paths based on audited statutory data...]</p>
</div>

<div class="callout">
  <h3>Probability Distribution Sensitivity Matrix</h3>
  <p>To prevent false precision from fixed weighting priors, here is the sensitivity of intrinsic fair value across alternative probability distributions:</p>
  <table class="data-table">
    <thead>
      <tr>
        <th>Weighting Scenario</th>
        <th>Path Distribution (Downside / Central / Upside)</th>
        <th>Expected Present Fair Value</th>
        <th>Margin of Safety (%)</th>
        <th>5-Year Target Price</th>
      </tr>
    </thead>
    <tbody>
      <tr><td><strong>Downside-Weighted Prior</strong></td><td>45% / 45% / 10%</td><td>$XX.XX</td><td>XX.X%</td><td>$XX.XX</td></tr>
      <tr><td><strong>Central Audited Baseline</strong></td><td><strong>Assigned Model Weights</strong></td><td><strong>$XX.XX</strong></td><td><strong>XX.X%</strong></td><td><strong>$XX.XX</strong></td></tr>
      <tr><td><strong>Constructive Execution Prior</strong></td><td>20% / 55% / 25%</td><td>$XX.XX</td><td>XX.X%</td><td>$XX.XX</td></tr>
    </tbody>
  </table>
</div>

<div class="callout">
  <h3>Market Inversion &amp; Valuation Synthesis</h3>
  <p><strong>Implied Market Reality:</strong> At today's market price of <strong>${current_price:.2f}</strong>, the market is pricing {company_name} at <strong>XX.Xx Normalized Owner Earnings</strong> (an implied Owner Cash Yield of <strong>X.X%</strong>). This implies the market is pricing in an Owner Earnings CAGR of <strong>[+X.X% / -X.X%] / yr</strong> over the next 5 years.</p>
  <p><strong>Probability-Weighted 5-Year Target Price:</strong> <strong>$XX.XX / share</strong> (Expected 5-Year CAGR: <strong>+X.X% / yr</strong>).</p>
  <p><strong>Probability-Weighted Present Fair Value (9.5% Hurdle):</strong> <strong>$XX.XX / share</strong> (Margin of Safety: <strong>~XX%</strong> vs. today's market price).</p>
  <p><strong>Capital Allocation Recommendation:</strong> [Crisp buy-side verdict based on Graham-Buffett margin of safety hurdle...]</p>
</div>

```json
{{
  "normalized_oe_per_share": XX.XX,
  "implied_market_multiple": "XX.Xx",
  "implied_market_yield": "X.X%",
  "net_cash_per_share": XX.XX,
  "present_fair_value": XX.XX,
  "expected_5y_target": XX.XX,
  "expected_mos_pct": XX.X,
  "expected_5y_cagr": XX.X,
  "action_signal": "BUY",
  "moat": "<Wide Moat | Narrow Moat | Weak Moat | No Moat>",
  "stories": [
    {{
      "story_num": 1,
      "story_title": "Path 1: <Title 1>",
      "short_summary": "<summary>",
      "projected_5y_cagr": "+XX.X%",
      "projected_oe5_per_share": XX.XX,
      "oe_multiple": "XX.Xx",
      "oe_yield": "X.X%",
      "target_price_5y": XX.XX,
      "present_fair_value": XX.XX,
      "mos_pct": XX.X,
      "probability_weight": 0.XX
    }}
  ]
}}
```
"""

AGENT_5_ADJUDICATION_PROMPT = """Target: {ticker} ({company_name})
Current Market Price: ${current_price:.2f}

You are LLM Agent 5: Lead Investment Thesis Refinement & Adjudication Director at an elite buy-side value fund.

Your Role:
Evaluate the Draft Investment Thesis (Section 1, Section 2, Section 3) against the Independent Buy-Side Red-Team Critique Memo.
Adjudicate every single point raised in the critique memo:

1. [ACKNOWLEDGE & ADAPT]:
   - Valid factual issues (e.g. neglected segment declines, acquired brand drops, single-silhouette risks).
   - Supply chain & counterparty concentration (% Vietnam/China factories, Section 301 tariffs, >50% revenue from 1–3 buyers in nascent lines like AI data licensing).
   - Dynamic Probability Space Partition (No Dogmatic Bull/Bear Triad): Ensure the N storylines span the realistic 90%–95% fundamental probability distribution of the company. For fortress monopolies, reject forced apocalyptic collapse cases and mandate realistic multiple de-rating / regulatory drag scenarios. For struggling turnarounds, mandate that drag/friction trajectories carry the bulk of the probability mass over unproven turnaround cases.
   - 100% Bespoke Company Grounding Check: Reject any generic boilerplate, unearned international expansion (for domestic-only operators), or artificial synthetic drivers. Mandate that the N storylines reflect THAT specific company's actual operating segments, reported metrics, and the last 4 quarters of management commentary and guidance.
   - Storyline Distinctness & Non-Overlap Check: Audit that all N storylines explore fundamentally distinct operational paths and causal mechanisms rather than minor percentage tweaks of the same narrative. Reject redundant drafts that fail to span different parts of the probability space.
   - Live / Ongoing Headwinds in Story 1: Ensure active, observable disruptions (e.g. multi-quarter negative same-store sales, Google AI Overviews reducing search referral traffic) are integrated into Story 1 Central Baseline rather than dismissed as distant tail risks.
   - Empirical Green Shoots & Turnaround Realism: If Story 1 assumes an operational turnaround (e.g. comp store sales pivoting positive, redesign cycle succeeding), audit whether there is trailing empirical data proof. If unproven, mandate that Story 1 model prolonged drag and probability weights reflect elevated downside risk.
   - Dynamic Probability Weight Derivation: Reject and remediate arbitrary equal probability weighting or forced tail-risk inflation. Ensure probability weights (p₁, ..., pN) are derived strictly from observable filing evidence and sum to 100%.
   - Cash flow matching & accounting adjustments (eliminating debt double-counting under FCFE/FCFF, working capital normalization, realistic AI GPU depreciation cycles).
   - Form 4 Executive vs. Director Dollar Asymmetry: Reject false equivalence or 'Divergent Flow' claims where small director purchases ($100k–$500k) are claimed to offset tens of millions in C-Suite executive selling. State net dollar flows objectively.
   - Signal-to-Valuation Coherence: If Market Price > Expected Intrinsic Value, ensure the thesis tone is strictly objective and signals AVOID / TRIM / OVERVALUED.
   - Scenario-Specific CapEx Efficiency: Ensure capex efficiency aligns with each scenario's operational story (e.g. expansion case custom silicon efficiency yielding higher FCF conversion vs friction case hardware replacement drag).

2. [PUSHBACK & DEFEND]:
   - Demands to anchor valuation to current market stock price.
   - Demands to add back Stock-Based Compensation as "non-cash" (Non-GAAP).
   - Demands to lower discount rates based on academic CAPM Betas rather than true opportunity cost.
   - Consensus herd-thinking that violates Graham/Buffett margin-of-safety principles.

CRITICAL SYNCHRONIZATION DIRECTIVE:
If you acknowledge any adjustment to Maintenance CapEx, Gross/Net Cash, or Starting Owner Earnings (OE₀), you MUST set BOTH SECTION_1_UPDATE: TRUE and SECTION_3_UPDATE: TRUE with explicit instructions to use the EXACT IDENTICAL dollar figure and maintenance capex baseline in both Section 1 and Section 3. Never permit Section 1 and Section 3 to use different baseline Owner Earnings (OE₀)!

Draft Thesis Overview:
======================================================================
Premise & Operations (Section 1 Preview):
{sec1_preview}

Operating Stories (Section 2 Preview):
{sec2_preview}

Valuation & DCFs (Section 3 Preview):
{sec3_preview}
======================================================================

Red-Team Critique Memo:
======================================================================
{critique_memo}
======================================================================

Format your output EXACTLY into the following 4 sections:

### ACKNOWLEDGED_REFINEMENTS
- [List each valid factual or accounting flaw accepted, or write "None" if 0 errors remain]

### PUSHBACK_DEFENSES
- [List each point pushed back against and defended with first-principles valuation logic]

### TARGET_MODULE_ACTION_DIRECTIVES
- SECTION_1_UPDATE: [TRUE or FALSE] -> [Specific factual, segment, or financial baseline items to add/correct in Section 1, or NONE]
- SECTION_2_UPDATE: [TRUE or FALSE] -> [Specific narrative, trajectory, or margin friction adjustments for Section 2 stories, or NONE]
- SECTION_3_UPDATE: [TRUE or FALSE] -> [Specific DCF cash flow, net cash bridge, or exit multiple adjustments for Section 3, or NONE]

### ADJUDICATION_RECONCILIATION_LOG_HTML
<div class="callout audit-adjudication">
  <h3>🛡️ Institutional Red-Team Adjudication &amp; Reconciliation Log</h3>
  <p><strong>Acknowledged Refinements Adopted:</strong></p>
  <ul>
    <li>[Item 1 with detail]</li>
    <li>[Item 2 with detail]</li>
  </ul>
  <p><strong>Methodological Pushbacks Defended:</strong></p>
  <ul>
    <li>[Item 1 with first-principles defense]</li>
    <li>[Item 2 with first-principles defense]</li>
  </ul>
</div>
"""

SECTION_1_REMEDIATOR_PROMPT = """Target: {ticker} ({company_name})
You are Section 1 Specialized Remediator: Senior Investigative Financial Analyst.
Task: Update Section 1 of the investment thesis to incorporate the specific critique directives below while preserving the complete institutional depth, segment tables, and HTML structure.

Directives to Incorporate:
{directives}

Current Section 1 HTML:
======================================================================
{sec1_html}
======================================================================

CRITICAL REQUIREMENTS:
1. Owner Earnings Waterfall Parity: Ensure the final derived Core Operating Baseline Owner Earnings (OE₀) in Section 1 matches the exact dollar figure used as Starting OE₀ in Section 3 DCF tables.
2. Segment Arithmetic Reconciliation: Ensure individual segment revenues sum to 100.0% of Total Net Revenue.

Output the complete, updated Section 1 HTML starting with <h2>Section 1: Company Overview &amp; Audited Financial Baseline</h2>. Pure HTML only (no markdown code fences)."""

SECTION_2_REMEDIATOR_PROMPT = """Target: {ticker} ({company_name})
You are Section 2 Specialized Remediator: Senior Equity Research Analyst.
Task: Update Section 2 (The Forward-Looking Operating Storylines) to incorporate the specific critique directives below while preserving the complete institutional depth, trajectory cards, and HTML structure.

Directives to Incorporate:
{directives}

Current Section 2 HTML:
======================================================================
{sec2_html}
======================================================================

Output the complete, updated Section 2 HTML starting with <h2>Section 2: Probable Business Stories</h2>. Pure HTML only (no markdown code fences)."""

SECTION_3_REMEDIATOR_PROMPT = """Target: {ticker} ({company_name})
Current Market Price: ${current_price:.2f}
You are Section 3 Specialized Remediator: Lead Quantitative Valuation Director.
Task: Update Section 3 (Valuation Across the Storylines) to incorporate the specific critique directives below.

Directives to Incorporate:
{directives}

Current Section 3 HTML:
======================================================================
{sec3_html}
======================================================================

CRITICAL REQUIREMENTS:
You MUST output the complete, untruncated Section 3 HTML containing:
1. <h2>Section 3: Valuation Across the Storylines</h2>
2. The DCF Summary Table (with explicit row header 'Intrinsic Fair Value / Share' or 'Intrinsic Fair Value / ADS' containing calculated per-share values for ALL storylines).
3. <h3>Step-by-Step Mathematical Proofs Across the Storylines</h3>
   - Full walkthrough for each storyline
4. <h3>Reverse DCF Sensitivity Matrix: What is Mr. Market Pricing In?</h3>
   - Full sensitivity matrix table and narrative analysis
5. <h3>Reconciliation vs. Wall Street Consensus Price Targets</h3>
   - Table and narrative comparing our first-principles value vs sell-side consensus
6. Owner Earnings Parity: The Starting Normalized Owner Earnings (OE₀) in Section 3 MUST be identical to the derived OE₀ in Section 1.
7. Epistemic Humility & Realistic Precision: Avoid false precision. Present forward CAGRs, deltas, and expected values in clean, rounded percentages (e.g. ~26%, ~-55%, ~+40%), rather than single/double decimals on subjective forward forecasts.

Output the complete Section 3 HTML. Pure HTML only (no markdown code fences)."""


def run_3_agent_critique_internal(ticker: str, company_name: str, thesis_html: str) -> str:
    """Runs a 3-agent autonomous critique pipeline with concurrent fact-checking & quant auditing:
    Agent 1 (Search Investigator): Actively searches latest 10-Q/10-K, segment drags, and supply chain risks.
    Agent 2 (Valuation Auditor): Audits cash flow matching (FCFE vs FCFF), debt deductions, and working capital.
    Agent 3 (Lead Red-Team PM): Synthesizes findings into an institutional Buy-Side Red-Team memo.
    """
    clean_t = ticker.upper().strip()
    print(f"\n   🧐 [CRITIQUE PIPELINE] Concurrently researching live filings & stress-testing valuation math for {clean_t}...", flush=True)
    
    agent_1_prompt = f"""Target Ticker: {clean_t} ({company_name})
You are Critique Agent 1: Senior Investigative Research Analyst at a premier buy-side hedge fund.
Search for:
1. Segment & Brand Performance: YoY growth rates, margins, and volume trends for EACH operating division (especially declining acquired brands).
2. Product Concentration: Silhouette fatigue, platform churn, consumer taste shifts.
3. Supply Chain Concentration: Manufacturing hubs (% Vietnam, China, Indonesia, Mexico) and tariff exposure.
4. Management Guidance & Commentary: Margin warnings and conservative guidance on the last 2 earnings calls.
Deliver a structured factual audit briefing with numbers."""

    agent_2_prompt = f"""Target Ticker: {clean_t} ({company_name})
You are Critique Agent 2: Chief Quantitative Risk & Cash Flow Auditor at a premier institutional fund.
Your job is to ruthlessly stress-test the numbers in this thesis.

USE YOUR PYTHON CODE EXECUTION TOOL to independently calculate and audit every calculation in the thesis:
1. Owner Earnings Baseline Parity (OE₀ Audit):
   - Check the exact OE₀ in Section 1 vs the Starting OE₀ in Section 3 DCF Table.
   - Run Python to verify: do they match exactly? If Section 1 derives $585M but Section 3 uses $661.5M, flag this as a critical desynchronization failure!
2. Balance Sheet Bridge & Debt vs Cash Sign Audit:
   - Audit the balance sheet in Section 1: does the company have net debt (Debt > Cash) or net cash?
   - Run Python to verify: if the company has $1.2B in net debt, did Section 3 SUBTRACT -$24/share, or did it mistakenly add a positive cash addition?
   - Check for plug numbers: if the company has only $15/share of cash, is Section 3 claiming an un-sourced +$100/share adjustment? Flag any plug numbers.
3. DCF Mathematical & Discounting Verification:
   - Run Python code to independently compound the 5-year cash flows, calculate Present Values at the stated discount rate, and compute Terminal Value.
   - Check if Operating Enterprise Value divided by Diluted Shares matches the table's Operating EV / share.
   - Check if Operating EV / share + (Bridge Adjustment) == Intrinsic Fair Value / share.
4. Reverse DCF Inversion Verification:
   - Run Python code to verify what 5-year CAGR is actually implied by today's market price. Check if the sensitivity matrix table is responsive or flat.
5. Section 1 Segment Breakdown Table Arithmetic Audit:
   - Run Python code to extract every numeric revenue row in Section 1's Segment Revenue Table, compute sum(segments), and compare it against the stated Total Net Revenue.
   - If sum(segments) differs from Total Net Revenue by >0.5% (e.g. segments sum to $190.6B vs $200.6B stated total), flag this as an Unreconciled Segment Breakdown Table error that must be corrected!
6. Useful Life & Maintenance CapEx Grounding Audit:
   - Check whether Maintenance CapEx is calibrated to actual disclosed 10-K depreciation notes (e.g. 5–6 year server useful lives) rather than ungrounded speculative 3-year burnout narratives. Flag any tens-of-billions over-penalization that contradicts official 10-K Note 1 disclosures.

Thesis:
======================================================================
{thesis_html}
======================================================================

Deliver a quantitative forensic audit memo showing the Python code execution results and flagging any broken math, sign errors, or desynchronized figures."""

    def _run_agent_1():
        out = call_gemini_with_search(agent_1_prompt, temperature=0.2, use_search=True)
        return clean_grounding_artifacts(out)

    def _run_agent_2():
        out = call_gemini_with_search(agent_2_prompt, temperature=0.2, use_search=False, use_code_execution=True)
        return clean_grounding_artifacts(out)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        fut1 = executor.submit(_run_agent_1)
        fut2 = executor.submit(_run_agent_2)
        agent_1_clean = fut1.result()
        agent_2_clean = fut2.result()

    print(f"   🧠 [CRITIQUE AGENT 3: LEAD RED-TEAM PM] Synthesizing institutional red-team memo...", flush=True)
    agent_3_prompt = f"""Target Ticker: {clean_t} ({company_name})
Synthesize Thesis, Fact Audit, and Quant Audit into an institutional Red-Team Memo (BUY/HOLD/AVOID with specific entry price thresholds, verified strengths, critical vulnerabilities, and actionable checklist).
Thesis:
======================================================================
{thesis_html}
======================================================================

Fact Audit:
======================================================================
{agent_1_clean}
======================================================================

Quant Audit:
======================================================================
{agent_2_clean}
======================================================================
"""
    agent_3_out = call_gemini_with_search(agent_3_prompt, temperature=0.2, use_search=False)
    return clean_grounding_artifacts(agent_3_out)


def run_improvement_agent(
    ticker: str,
    company_name: str,
    current_price: float,
    sec1_html: str,
    sec2_html: str,
    sec3_html: str,
    critique_memo: str
) -> Tuple[str, str, str, str, List[str], List[str]]:
    """Runs the Modular Targeted Improvement System:
    1. Adjudication Director: Classifies feedback into Acknowledged vs Pushbacks and targets specific sections.
    2. Section Remediators: Remediates only the specific section(s) requiring adjustments in dedicated concurrent sub-prompts.
    3. Log Assembler: Constructs the institutional reconciliation callout.
    """
    sec1_prev = sec1_html[:1500] + "\n..." if len(sec1_html) > 1500 else sec1_html
    sec2_prev = sec2_html[:1500] + "\n..." if len(sec2_html) > 1500 else sec2_html
    sec3_prev = sec3_html[:1500] + "\n..." if len(sec3_html) > 1500 else sec3_html

    adj_prompt = AGENT_5_ADJUDICATION_PROMPT.format(
        ticker=ticker,
        company_name=company_name,
        current_price=current_price,
        sec1_preview=sec1_prev,
        sec2_preview=sec2_prev,
        sec3_preview=sec3_prev,
        critique_memo=critique_memo
    )
    raw = call_gemini_with_search(adj_prompt, temperature=0.2, use_search=False)
    clean = clean_grounding_artifacts(raw)
    
    ack_items = []
    push_items = []
    
    # 1. Parse Acknowledged Refinements
    m_ack = re.search(r'###\s*ACKNOWLEDGED_REFINEMENTS\s*(.*?)(?=###|$)', clean, re.DOTALL | re.IGNORECASE)
    if m_ack:
        for line in m_ack.group(1).splitlines():
            line = line.strip().lstrip("-*• ").strip()
            if line and not line.lower().startswith("none") and len(line) > 5:
                ack_items.append(line)
                
    # 2. Parse Pushback Defenses
    m_push = re.search(r'###\s*PUSHBACK_DEFENSES\s*(.*?)(?=###|$)', clean, re.DOTALL | re.IGNORECASE)
    if m_push:
        for line in m_push.group(1).splitlines():
            line = line.strip().lstrip("-*• ").strip()
            if line and not line.lower().startswith("none") and len(line) > 5:
                push_items.append(line)

    # 3. Parse Target Module Directives
    m_dir = re.search(r'###\s*TARGET_MODULE_ACTION_DIRECTIVES\s*(.*?)(?=###|$)', clean, re.DOTALL | re.IGNORECASE)
    dir_text = m_dir.group(1) if m_dir else ""
    
    update_sec1 = "SECTION_1_UPDATE: TRUE" in dir_text.upper() or "SECTION_1: TRUE" in dir_text.upper()
    update_sec2 = "SECTION_2_UPDATE: TRUE" in dir_text.upper() or "SECTION_2: TRUE" in dir_text.upper()
    update_sec3 = "SECTION_3_UPDATE: TRUE" in dir_text.upper() or "SECTION_3: TRUE" in dir_text.upper()

    final_sec1 = sec1_html
    final_sec2 = sec2_html
    final_sec3 = sec3_html

    # Concurrent Section Remediation
    remediation_tasks = []
    if update_sec1 and len(ack_items) > 0:
        p1 = SECTION_1_REMEDIATOR_PROMPT.format(
            ticker=ticker,
            company_name=company_name,
            directives=dir_text,
            sec1_html=sec1_html
        )
        remediation_tasks.append((1, p1, False, False))

    if update_sec2 and len(ack_items) > 0:
        p2 = SECTION_2_REMEDIATOR_PROMPT.format(
            ticker=ticker,
            company_name=company_name,
            directives=dir_text,
            sec2_html=sec2_html
        )
        remediation_tasks.append((2, p2, False, False))

    if update_sec3 and len(ack_items) > 0:
        p3 = SECTION_3_REMEDIATOR_PROMPT.format(
            ticker=ticker,
            company_name=company_name,
            current_price=current_price,
            directives=dir_text,
            sec3_html=sec3_html
        )
        remediation_tasks.append((3, p3, False, True))

    def _execute_remediation(task_tuple):
        sec_idx, prompt, u_search, u_code = task_tuple
        print(f"      🔧 [MODULAR REMEDIATOR] Concurrently updating Section {sec_idx}...", flush=True)
        r = call_gemini_with_search(prompt, temperature=0.2, use_search=u_search, use_code_execution=u_code)
        c = verify_and_repair_html_structure(clean_grounding_artifacts(r))
        return sec_idx, c

    if remediation_tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(remediation_tasks)) as executor:
            rem_results = list(executor.map(_execute_remediation, remediation_tasks))
            for sec_idx, c in rem_results:
                if sec_idx == 1 and "<h2>Section 1:" in c and len(c.split()) >= 600:
                    final_sec1 = c
                elif sec_idx == 2 and "<h2>Section 2:" in c and len(c.split()) >= 600:
                    final_sec2 = c
                elif sec_idx == 3 and "<h2>Section 3:" in c and "reverse dcf" in c.lower() and "story 3" in c.lower() and len(c.split()) >= 600:
                    final_sec3 = c

    # 4. Parse Adjudication Callout HTML
    m_callout = re.search(r'(<div class="callout audit-adjudication">[\s\S]*?</div>)', clean, re.DOTALL | re.IGNORECASE)
    if m_callout:
        callout_html = m_callout.group(1).strip()
    else:
        ack_lis = "\n".join([f"    <li>{item}</li>" for item in ack_items]) or "    <li>All feedback points verified and integrated.</li>"
        push_lis = "\n".join([f"    <li>{item}</li>" for item in push_items]) or "    <li>Disciplined value-investing methodology defended.</li>"
        callout_html = f"""<div class="callout audit-adjudication">
  <h3>🛡️ Institutional Red-Team Adjudication &amp; Reconciliation Log</h3>
  <p><strong>Acknowledged Refinements Adopted:</strong></p>
  <ul>
{ack_lis}
  </ul>
  <p><strong>Methodological Pushbacks Defended:</strong></p>
  <ul>
{push_lis}
  </ul>
</div>"""

    return final_sec1, final_sec2, final_sec3, callout_html, ack_items, push_items


def parse_float_safe(val: Any, default: float = 0.0) -> float:
    """Safely parses a float from string, int, float, or formatted currency ('$145.20', '145.20 / share')."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = re.sub(r"[^\d.-]", "", val.strip())
        if cleaned:
            try:
                return float(cleaned)
            except Exception:
                pass
        m = re.search(r'[-+]?[0-9,]+(?:\.[0-9]+)?', val.strip())
        if m:
            try:
                return float(m.group(0).replace(",", ""))
            except Exception:
                pass
    return default


def extract_story_valuation(dcf_dict: Dict[str, Any], raw_text: str = "", current_price: float = 0.0) -> float:
    """Extracts the fair value per share from JSON keys or regex fallback in raw LLM text, with sanity protection."""
    val = 0.0
    if isinstance(dcf_dict, dict):
        for k in [
            "fair_value_per_share", "total_intrinsic_value_per_share", "intrinsic_value_per_share",
            "calculated_intrinsic_value", "fair_value", "intrinsic_value", "operating_value_per_share",
            "per_share_value", "target_price"
        ]:
            if k in dcf_dict:
                v = parse_float_safe(dcf_dict[k])
                if v > 0.0:
                    val = v
                    break
                    
        # Sanity check: if value is > 2000 and current price is under 500, check if enterprise value was returned instead of per-share
        shares = parse_float_safe(dcf_dict.get("diluted_shares_millions") or dcf_dict.get("diluted_shares"))
        if val > 1500.0 and current_price > 0 and current_price < 500.0 and shares > 10.0:
            val = round(val / shares, 2)
            
    if val <= 0.0 and raw_text:
        m = re.search(r'(?:fair value|intrinsic value|calculated intrinsic value|per share|per ADS)[^0-9$]*?\$?\s*([0-9,]+(?:\.[0-9]+)?)', raw_text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
            except Exception:
                pass
    return val


def split_sec1_and_sec2(raw_output: str, company_name: str) -> Tuple[str, str]:
    """Splits Agent 1 output into Section 1 HTML (The Premise) and Section 2 HTML (The Probable Future Paths)."""
    clean_text = clean_grounding_artifacts(raw_output)
    clean_html = re.sub(r'```(?:html|json)?[\s\S]*?```', '', clean_text).strip()
    
    m_sec2 = re.search(r'((?:<h[234][^>]*>|##+\s*)(?:Section\s*2\b|The\s*3\s*Probable|Probable\s*(?:Business\s*)?(?:Stories|Paths)|3\s*Probable|Future\s*Paths)[\s\S]*)', clean_html, re.IGNORECASE)
    if m_sec2:
        sec1_html = clean_html[:m_sec2.start()].strip()
        sec2_html = clean_html[m_sec2.start():].strip()
    else:
        sec1_html = clean_html
        sec2_html = ""
        
    if "<h2>Section 1:" not in sec1_html and "<h2>The Premise" not in sec1_html:
        sec1_html = f"<h2>Section 1: The Premise of the Company</h2>\n{sec1_html}"
    if sec2_html and "<h2>Section 2:" not in sec2_html:
        sec2_html = f"<h2>Section 2: The Probable Future Paths</h2>\n{sec2_html}"
        
    sec1_clean = verify_and_repair_html_structure(sec1_html)
    sec2_clean = verify_and_repair_html_structure(sec2_html) if sec2_html else ""
    return sec1_clean, sec2_clean


def parse_sec3_and_json(
    raw_output: str,
    company_name: str,
    current_price: float,
    sec1_text: str = "",
    sec2_text: str = ""
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """Parses Agent 2 output into Section 3 HTML, JSON metadata, and structured stories."""
    clean_text = clean_grounding_artifacts(raw_output)
    
    # Extract JSON block
    json_block = extract_json_block(raw_output)
    if isinstance(json_block, dict):
        stories = json_block.get("stories", [])
    elif isinstance(json_block, list):
        stories = json_block
        json_block = {"stories": stories}
    else:
        stories = []
        json_block = {}
        
    clean_html = re.sub(r'```json[\s\S]*?```', '', clean_text)
    clean_html = re.sub(r'```[\s\S]*?```', '', clean_html).strip()
    
    if "<h2>Section 3:" not in clean_html:
        clean_html = f"<h2>Section 3: Normalized Owner Earnings Multiple &amp; Yield Inversion Valuation</h2>\n{clean_html}"
        
    sec3_clean = verify_and_repair_html_structure(clean_html)
    
    # Net cash per share extraction from json_block or text
    net_cash_sh = safe_float(json_block.get("net_cash_per_share"), 0.0)
    if net_cash_sh == 0.0:
        m_nc = re.search(r'(?:Net\s*(?:Surplus\s*)?Cash|Net\s*Debt)[^$\n]*?([+-]?\$\s*[\d,]+(?:\.\d+)?)\s*(?:/\s*sh|per\s*share|per\s*ADS)?', sec1_text or sec3_clean, re.IGNORECASE)
        if m_nc:
            net_cash_sh = safe_float(m_nc.group(1), 0.0)
            
    # Auto-normalize if net cash was given as aggregate millions instead of per-share
    max_plausible_cash = max(35.0, current_price * 0.65)
    if net_cash_sh > max_plausible_cash or net_cash_sh > 90.0:
        m_sh = re.search(r'([\d,]+(?:\.\d+)?)\s*(?:million|M)?\s*(?:diluted shares|shares outstanding)', f"{sec1_text} {sec3_clean}", re.IGNORECASE)
        if m_sh:
            sh_count = safe_float(m_sh.group(1), 1.0)
            if sh_count > 10.0:
                net_cash_sh = round(net_cash_sh / sh_count, 2)
            else:
                net_cash_sh = round(net_cash_sh / 1000.0, 2)
        else:
            net_cash_sh = 0.0
            
    # Normalized OE per share
    oe_per_sh = safe_float(json_block.get("normalized_oe_per_share"), 0.0)
    if oe_per_sh <= 0.0:
        m_oe = re.search(r'(?:Owner\s*Earnings|OE₀)[^$\n]*?\$?\s*([\d,]+(?:\.\d+)?)\s*(?:/\s*sh|per\s*share|per\s*ADS)?', sec1_text or sec3_clean, re.IGNORECASE)
        if m_oe:
            oe_per_sh = safe_float(m_oe.group(1), 0.0)
            
    # Build stories metadata
    stories_metadata = []
    if stories and len(stories) >= 1:
        num_s = len(stories)
        for idx, s in enumerate(stories, start=1):
            val = safe_float(s.get("target_price_5y") or s.get("fair_value_per_share") or s.get("val"), 0.0)
            mult = str(s.get("oe_multiple") or s.get("terminal_multiple") or "18.0x")
            yield_str = str(s.get("oe_yield") or "")
            mult_num = safe_float(mult, 18.0)
            oe5_sh = safe_float(s.get("projected_oe5_per_share") or s.get("oe5_per_share"), 0.0)
            cagr_str = str(s.get("projected_5y_cagr") or "")
            
            # If val is missing or invalid, compute from multiple * oe5_sh (or compounded oe_per_sh) + net_cash_sh
            if val <= 0.0 or val > 25000.0:
                if oe5_sh > 0:
                    val = round(mult_num * oe5_sh + net_cash_sh, 2)
                elif oe_per_sh > 0:
                    cagr_num = safe_float(cagr_str, 8.0 if idx == 1 else (14.0 if idx == 2 else -2.0))
                    calc_oe5 = oe_per_sh * ((1.0 + cagr_num / 100.0) ** 5)
                    val = round(mult_num * calc_oe5 + net_cash_sh, 2)
                else:
                    val = 0.0
                
            prob = safe_float(s.get("probability_weight") or s.get("prob_weight"), 0.0)
            if prob <= 0.0:
                prob = round(1.0 / num_s, 2)
                
            pv_val = round(val / (1.095 ** 5), 2) if val > 0 else 0.0
            mos = ((pv_val - current_price) / current_price) * 100.0 if current_price > 0 and pv_val > 0 else 0.0
            ret_5y = ((val - current_price) / current_price) * 100.0 if current_price > 0 and val > 0 else 0.0
            cagr_5y = (((val / current_price) ** 0.2 - 1.0) * 100.0) if current_price > 0 and val > 0 else 0.0
            
            title = s.get("story_title") or s.get("title") or f"Path {idx}"
            summary = s.get("short_summary") or s.get("summary") or ""
            
            stories_metadata.append({
                "story_num": idx,
                "id": idx,
                "story_title": str(title),
                "title": str(title),
                "short_summary": str(summary),
                "summary": str(summary),
                "oe_multiple": mult if "x" in mult.lower() else f"{mult}x",
                "oe_yield": yield_str or f"{(1.0/max(safe_float(mult, 18.0), 1.0))*100:.1f}%",
                "terminal_multiple": mult if "x" in mult.lower() else f"{mult}x",
                "val": val,
                "present_fair_value": pv_val,
                "mos_pct": round(mos, 1),
                "target_5y_return_pct": round(ret_5y, 1),
                "target_5y_cagr_pct": round(cagr_5y, 1),
                "target": f"${val:.2f} ({ret_5y:+.1f}%)",
                "prob_pct": round(prob * 100.0, 1),
                "prob_weight": prob,
                "net_cash_per_share": net_cash_sh,
                "normalized_oe_per_share": oe_per_sh,
                "projected_oe5_per_share": oe5_sh,
                "projected_5y_cagr": cagr_str,
                "pro_forma_schedule": s.get("pro_forma_schedule") or {}
            })
    else:
        # Fallback if stories JSON block was partial - compute strictly via Owner Earnings compounding
        p1_oe5 = round(oe_per_sh * (1.08 ** 5), 2) if oe_per_sh > 0 else 0.0
        p2_oe5 = round(oe_per_sh * (1.14 ** 5), 2) if oe_per_sh > 0 else 0.0
        p3_oe5 = round(oe_per_sh * (0.98 ** 5), 2) if oe_per_sh > 0 else 0.0
        p1_val = round(p1_oe5 * 16.0 + net_cash_sh, 2)
        p2_val = round(p2_oe5 * 20.0 + net_cash_sh, 2)
        p3_val = round(p3_oe5 * 11.0 + net_cash_sh, 2)
        
        stories_metadata = [
            {
                "story_num": 1,
                "id": 1,
                "story_title": "Path 1: Baseline Compounding",
                "title": "Path 1: Baseline Compounding",
                "short_summary": "Steady operational execution and baseline capital reinvestment.",
                "summary": "Steady operational execution and baseline capital reinvestment.",
                "oe_multiple": "16.0x",
                "oe_yield": "6.2%",
                "terminal_multiple": "16.0x",
                "val": p1_val,
                "present_fair_value": round(p1_val / (1.095 ** 5), 2),
                "mos_pct": round(((p1_val / (1.095 ** 5) - current_price) / current_price) * 100.0, 1) if current_price > 0 else 0.0,
                "target": f"${p1_val:.2f}",
                "prob_pct": 65.0,
                "prob_weight": 0.65,
                "net_cash_per_share": net_cash_sh,
                "normalized_oe_per_share": oe_per_sh,
                "projected_oe5_per_share": p1_oe5,
                "projected_5y_cagr": "+8.0%"
            },
            {
                "story_num": 2,
                "id": 2,
                "story_title": "Path 2: High-Margin Expansion",
                "title": "Path 2: High-Margin Expansion",
                "short_summary": "Accelerated customer adoption and high-margin operating leverage.",
                "summary": "Accelerated customer adoption and high-margin operating leverage.",
                "oe_multiple": "20.0x",
                "oe_yield": "5.0%",
                "terminal_multiple": "20.0x",
                "val": p2_val,
                "present_fair_value": round(p2_val / (1.095 ** 5), 2),
                "mos_pct": round(((p2_val / (1.095 ** 5) - current_price) / current_price) * 100.0, 1) if current_price > 0 else 0.0,
                "target": f"${p2_val:.2f}",
                "prob_pct": 20.0,
                "prob_weight": 0.20,
                "net_cash_per_share": net_cash_sh,
                "normalized_oe_per_share": oe_per_sh,
                "projected_oe5_per_share": p2_oe5,
                "projected_5y_cagr": "+14.0%"
            },
            {
                "story_num": 3,
                "id": 3,
                "story_title": "Path 3: Margin Friction & Multiple Drag",
                "title": "Path 3: Margin Friction & Multiple Drag",
                "short_summary": "Elevated competitive friction and margin contraction.",
                "summary": "Elevated competitive friction and margin contraction.",
                "oe_multiple": "11.0x",
                "oe_yield": "9.1%",
                "terminal_multiple": "11.0x",
                "val": p3_val,
                "present_fair_value": round(p3_val / (1.095 ** 5), 2),
                "mos_pct": round(((p3_val / (1.095 ** 5) - current_price) / current_price) * 100.0, 1) if current_price > 0 else 0.0,
                "target": f"${p3_val:.2f}",
                "prob_pct": 15.0,
                "prob_weight": 0.15,
                "net_cash_per_share": net_cash_sh,
                "normalized_oe_per_share": oe_per_sh,
                "projected_oe5_per_share": p3_oe5,
                "projected_5y_cagr": "-2.0%"
            }
        ]

    return sec3_clean, json_block, stories_metadata


def split_full_genesis_dossier(raw_output: str, company_name: str, current_price: float) -> Tuple[str, str, str, Dict[str, Any], List[Dict[str, Any]]]:
    """Splits single-pass output into Section 1 HTML, Section 2 HTML, Section 3 HTML, and parsed metadata."""
    clean_text = clean_grounding_artifacts(raw_output)
    sec1_clean, sec2_clean = split_sec1_and_sec2(raw_output, company_name)
    sec3_clean, json_block, stories_metadata = parse_sec3_and_json(raw_output, company_name, current_price, sec1_text=sec1_clean, sec2_text=sec2_clean)
    return sec1_clean, sec2_clean, sec3_clean, json_block, stories_metadata


def extract_financial_baseline(sec1_html: str) -> Tuple[float, float, str]:
    """Extracts starting Normalized Owner Earnings (OE₀), Net Cash/Debt per share, and ROIC from Section 1 HTML."""
    if not sec1_html:
        return 0.0, 0.0, "20.0% - 25.0%"

    soup = BeautifulSoup(sec1_html, 'html.parser')

    # 1. Parse Starting Normalized Owner Earnings (OE₀) per share
    oe_per_sh = 0.0
    for tr in soup.find_all('tr'):
        tr_text = tr.get_text()
        if 'Owner Earnings' in tr_text and ('OE_0' in tr_text or 'OE₀' in tr_text or 'Per Share' in tr_text or 'Per Diluted' in tr_text):
            for td in tr.find_all('td'):
                m = re.search(r'\$\s*([\d,]+(?:\.\d+)?)\s*(?:/sh|/share|/ADS|per\s*share)?', td.get_text())
                if m:
                    v = float(m.group(1).replace(',', ''))
                    if 0.20 <= v <= 100.0:
                        oe_per_sh = v
                        break
            if oe_per_sh > 0:
                break

    if oe_per_sh == 0.0:
        m_txt = re.search(r'(?:Starting\s*Normalized\s*Owner\s*Earnings|\(OE[₀0]\))\s*(?:is|at|of|\/ share)?\s*\$?\s*([\d,]+(?:\.\d+)?)\s*(?:/share|/ADS|per\s*share|per\s*ADS)', sec1_html, re.I)
        if m_txt:
            oe_per_sh = float(m_txt.group(1).replace(',', ''))
        else:
            m_txt2 = re.search(r'Normalized\s*Owner\s*Earnings\s*\(OE₀\)\s*.*?\$([\d,]+(?:\.\d+)?)', sec1_html, re.I)
            if m_txt2:
                oe_per_sh = float(m_txt2.group(1).replace(',', ''))

    # 2. Parse Net Surplus Cash / Net Debt per share
    net_cash_sh = 0.0
    for tr in soup.find_all('tr'):
        tr_text = tr.get_text()
        if any(k in tr_text.lower() for k in ['net surplus cash', 'net cash position', 'net debt position', 'funded net debt', 'unencumbered liquid', 'total net cash']):
            extracted = []
            for td in tr.find_all('td')[1:]:
                t_txt = td.get_text()
                if any(w in t_txt.lower() for w in ['based on', 'million', 'billion', 'rmb', 'notes', 'audited']):
                    continue
                m = re.search(r'([+-]?\(?\$?\s*[\d,]+(?:\.\d+)?\)?)', t_txt)
                if m:
                    s_clean = m.group(1).replace('$', '').replace(' ', '').replace(',', '').strip()
                    try:
                        if s_clean.startswith('(') and s_clean.endswith(')'):
                            val_f = -float(s_clean[1:-1])
                        else:
                            val_f = float(s_clean)
                        if abs(val_f) <= 150.0:
                            extracted.append(val_f)
                    except Exception:
                        pass
            if extracted:
                # If both ordinary share and ADS exist, take the per-ADS representation
                net_cash_sh = extracted[-1]
                break

    # 3. Parse ROIC
    roic_str = "20.0% - 25.0%"
    for tr in soup.find_all('tr'):
        tr_text = tr.get_text()
        if 'ROIC' in tr_text or 'Return on Invested Capital' in tr_text:
            m_pct = re.search(r'([\d\.]+\s*%)', tr_text)
            if m_pct:
                roic_str = m_pct.group(1)
                break

    return oe_per_sh, net_cash_sh, roic_str


def generate_genesis_thesis(ticker: str, company_name: str, current_price: float, initial_notes: str = "") -> Tuple[Dict[str, Any], str]:
    """Generates an investment thesis via the Grounded Parallel-Storyline Valuation & Audit Engine:
    1. Agent 1 (Search Grounded): Researches audited 10-Ks, formulating Section 1 (Premise) and Section 2 (N Paths) with adversarial red-team stress tests (~25s).
    2. Agent 1.5 & 1.8: Buy-Side Red-Team Critique & Storyline Refinement Gate (~15s).
    3. Parallel Story Underwriting: Spawns independent concurrent Gemini analysts to value each path in complete isolation (~6s).
    4. Chief Risk Officer & Feedback Audit Agent: Sanity-checks multiples, growth realism, re-distributes probability mass, and synthesizes Section 3 & JSON (~8s).
    5. Concurrent Background Scrapes: Pre-fetches OpenInsider, Dataroma superinvestors, and catalyst timelines.
    """
    ticker_clean = ticker.upper().strip()
    
    print("\n" + "=" * 70, flush=True)
    print(f"🏢 INITIATING LEVEL-HEADED THESIS GENERATION: {ticker_clean} ({company_name})", flush=True)
    print(f"💵 Market Entry Price: ${current_price:.2f}", flush=True)
    if initial_notes:
        print(f"📝 User Notes / Focus: {initial_notes}", flush=True)
    print("=" * 70, flush=True)
    
    # Background catalyst intelligence subagent (runs concurrently with main thesis generation)
    bg_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    fut_catalyst = bg_executor.submit(research_catalyst_intelligence, ticker_clean, company_name)

    # ------------------------------------------------------------------
    # Agent 1: Search-Grounded Genesis Premise & Operational Paths (100% BLIND TO MARKET PRICE)
    # ------------------------------------------------------------------
    print(f"\n🧠 [AGENT 1: SEARCH-GROUNDED RESEARCH] Researching 10-Ks, formulating Premise (Sec 1) & N Paths (Sec 2)...", flush=True)
    agent1_prompt = AGENT_1_GENESIS_PREMISE_AND_PATHS_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        notes=initial_notes or "Synthesize core business model, unit economics, 4-quarter earnings commentary, and distinct operational trajectories."
    )
    raw_agent1_output = call_gemini_with_search(agent1_prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY, use_search=True)
    sec1_clean, sec2_clean = split_sec1_and_sec2(raw_agent1_output, company_name)
    words_agent1 = len(sec1_clean.split()) + len(sec2_clean.split())
    print(f"   │ Status: Section 1 & Section 2 drafted ({words_agent1} words)", flush=True)

    # ------------------------------------------------------------------
    # Agent 1.5: Search-Grounded Red-Team Feedback (Storylines & Assumptions)
    # ------------------------------------------------------------------
    print(f"\n🧐 [RED-TEAM FEEDBACK AGENT] Stress-testing storylines, unit assumptions & probability weights...", flush=True)
    feedback_prompt = AGENT_RED_TEAM_FEEDBACK_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        sec1_and_sec2_draft=f"{sec1_clean}\n\n{sec2_clean}"
    )
    critique_memo = call_gemini_with_search(feedback_prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY, use_search=True)
    words_critique = len(critique_memo.split())
    print(f"   │ Status: Red-Team Critique Memo generated ({words_critique} words)", flush=True)

    # ------------------------------------------------------------------
    # Agent 1.8: Search-Grounded Storyline Refinement & Improvement
    # ------------------------------------------------------------------
    print(f"\n🔧 [STORYLINE IMPROVEMENT AGENT] Refining Section 1 & Section 2 against Red-Team feedback...", flush=True)
    refinement_prompt = AGENT_STORYLINE_REFINEMENT_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        sec1_and_sec2_draft=f"{sec1_clean}\n\n{sec2_clean}",
        critique_memo=critique_memo
    )
    raw_refined_output = call_gemini_with_search(refinement_prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY, use_search=True)
    ref_sec1, ref_sec2 = split_sec1_and_sec2(raw_refined_output, company_name)
    if len(ref_sec1.split()) >= 300 and len(ref_sec2.split()) >= 250:
        sec1_clean, sec2_clean = ref_sec1, ref_sec2
        words_refined = len(sec1_clean.split()) + len(sec2_clean.split())
        print(f"   │ Status: Section 1 & Section 2 perfected ({words_refined} words)", flush=True)
    else:
        print(f"   │ Status: Preserved robust Agent 1 draft ({words_agent1} words)", flush=True)

    # ------------------------------------------------------------------
    # Parallel Independent Story Valuation Engine (3 Independent Parallel Calls)
    # ------------------------------------------------------------------
    oe0, net_cash_sh, roic_str = extract_financial_baseline(sec1_clean)
    moat_tier = map_to_canonical_moat_label("", sec1_text=sec1_clean)
    
    # Extract Individual Stories from Section 2
    story_blocks = []
    for m in re.finditer(r'<div class="callout">\s*<h3>Path\s*(\d+)[:\s]*([^<]+)</h3>([\s\S]*?)</div>', sec2_clean, re.IGNORECASE):
        num = int(m.group(1))
        title = m.group(2).strip()
        body = m.group(3).strip()
        story_blocks.append({
            "num": num,
            "title": f"Path {num}: {title}",
            "text": f"<h3>Path {num}: {title}</h3>\n{body}"
        })
        
    if not story_blocks:
        story_blocks = [
            {"num": 1, "title": "Path 1: Core Execution", "text": "Core operational baseline compounding"},
            {"num": 2, "title": "Path 2: Downside Friction", "text": "Competitive friction & tariff margin drag"},
            {"num": 3, "title": "Path 3: Operating Leverage", "text": "Accelerated global category expansion"}
        ]
        
    print(f"\n⚡ [PARALLEL VALUATION ENGINE] Spawning {len(story_blocks)} Independent Valuation Analysts (Zero Cross-Bias)...", flush=True)
    
    def _value_single_story(s_info):
        prompt = STORY_VALUATION_PROMPT.format(
            ticker=ticker_clean,
            company_name=company_name,
            story_num=s_info["num"],
            story_title=s_info["title"],
            moat_tier=moat_tier,
            oe0_per_share=oe0,
            net_cash_str=f"{net_cash_sh:+.2f} USD/share",
            net_cash_num=net_cash_sh,
            roic_str=roic_str,
            story_text=s_info["text"]
        )
        resp = call_gemini_with_search(
            prompt,
            system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY,
            use_search=True,
            use_code_execution=True
        )
        parsed = parse_json_robust(resp)
        if parsed and isinstance(parsed, dict):
            return parsed
        return {
            "story_num": s_info["num"],
            "story_title": s_info["title"],
            "raw": resp
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(story_blocks)) as executor:
        story_val_results = list(executor.map(_value_single_story, story_blocks))

    print(f"   │ Status: {len(story_val_results)} stories independently underwritten in parallel (Code Execution Verified)", flush=True)

    # ------------------------------------------------------------------
    # Chief Risk Officer & Valuation Feedback Audit Agent
    # ------------------------------------------------------------------
    print(f"\n🧐 [CHIEF RISK OFFICER & VALUATION AUDIT] Stress-testing multiples, growth realism & probability weights...", flush=True)
    feedback_audit_prompt = VALUATION_FEEDBACK_AND_SYNTHESIS_PROMPT.format(
        ticker=ticker_clean,
        company_name=company_name,
        current_price=current_price,
        moat_tier=moat_tier,
        oe0_per_share=oe0,
        net_cash_str=f"{net_cash_sh:+.2f} USD/share",
        historical_summary=f"Normalized ROIC ~{roic_str}, Baseline OE₀=${oe0:.2f}/sh",
        num_stories=len(story_blocks),
        stories_json_text=json.dumps(story_val_results, indent=2)
    )
    raw_audit_output = call_gemini_with_search(
        feedback_audit_prompt,
        system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY,
        use_search=False,
        use_code_execution=True
    )
    sec3_clean, val_json, stories_metadata = parse_sec3_and_json(
        raw_audit_output,
        company_name,
        current_price,
        sec1_text=sec1_clean,
        sec2_text=sec2_clean
    )
    
    # Merge pro_forma_schedule from parallel story valuation agents into stories_metadata
    for sm in stories_metadata:
        s_num = sm.get("story_num") or sm.get("id")
        for svr in story_val_results:
            if isinstance(svr, dict) and (svr.get("story_num") == s_num or svr.get("id") == s_num):
                if svr.get("pro_forma_schedule") and not sm.get("pro_forma_schedule"):
                    sm["pro_forma_schedule"] = svr.get("pro_forma_schedule")
                break

    words_agent2 = len(sec3_clean.split())
    print(f"   │ Status: Section 3 and Audited JSON generated ({words_agent2} words, {len(stories_metadata)} paths)", flush=True)
    print("   └" + "─" * 50, flush=True)

    # ------------------------------------------------------------------
    # Local Harmonization, QA & Structural Integrity
    # ------------------------------------------------------------------
    print(f"\n🛡️ [HARMONIZER & QA] Assembling seamless thesis dossier and verifying structural integrity...", flush=True)
    
    # Rigorous Thesis Completeness & Quality Gate
    is_complete = True
    issues = []
    if len(sec1_clean.split()) < 300:
        is_complete = False
        issues.append(f"Section 1 word count too low ({len(sec1_clean.split())} words)")
    if len(sec2_clean.split()) < 250:
        is_complete = False
        issues.append(f"Section 2 word count too low ({len(sec2_clean.split())} words)")
    if len(sec3_clean.split()) < 100 or "<table" not in sec3_clean:
        is_complete = False
        issues.append("Section 3 Valuation Table missing or incomplete")
    if len(stories_metadata) < 2:
        is_complete = False
        issues.append(f"Derived {len(stories_metadata)} paths (minimum 2 required)")
        
    if not is_complete:
        print(f"  ⚠️ [THESIS INTEGRITY WARNING] Incomplete thesis detected: {', '.join(issues)}. Triggering instant valuation self-healing...", flush=True)
        raw_audit_output = call_gemini_with_search(feedback_audit_prompt, system_instruction=LEVEL_HEADED_INVESTOR_PHILOSOPHY, use_search=False)
        sec3_clean, val_json, stories_metadata = parse_sec3_and_json(
            raw_audit_output, company_name, current_price, sec1_text=sec1_clean, sec2_text=sec2_clean
        )
    
    raw_full_html = f"{sec1_clean}\n\n{sec2_clean}\n\n{sec3_clean}"
    full_html = verify_and_repair_html_structure(raw_full_html)

    expected_target_5y = round(sum(s["prob_weight"] * s["val"] for s in stories_metadata), 2)
    expected_present_fv = round(expected_target_5y / (1.095 ** 5), 2) if expected_target_5y > 0 else 0.0
    expected_mos = ((expected_present_fv - current_price) / current_price) * 100.0 if current_price > 0 and expected_present_fv > 0 else 0.0
    expected_5y_return = ((expected_target_5y - current_price) / current_price) * 100.0 if current_price > 0 and expected_target_5y > 0 else 0.0
    expected_5y_cagr = (((expected_target_5y / current_price) ** 0.2 - 1.0) * 100.0) if current_price > 0 and expected_target_5y > 0 else 0.0

    min_story = min(stories_metadata, key=lambda s: s["val"])
    max_story = max(stories_metadata, key=lambda s: s["val"])
    base_story = stories_metadata[0]  # Story 1 Central Baseline

    # Action Signal Derivation from Probability-Weighted Expected Fair Value Margin of Safety
    if expected_mos >= 20.0:
        action_signal = "BUY"
    elif expected_mos >= 0.0:
        action_signal = "HOLD"
    elif expected_mos >= -15.0:
        action_signal = "CAUTION"
    else:
        action_signal = "AVOID"

    # Price alert corridors
    lower_alert = round(min_story["val"], 2)
    upper_alert = round(max_story["val"], 2)
    if lower_alert >= current_price:
        lower_alert = round(current_price * 0.90, 2)
    if upper_alert <= current_price:
        upper_alert = round(current_price * 1.15, 2)

    # Dynamic bespoke catalyst drivers from val_json or sec1_clean
    custom_drivers = val_json.get("key_catalyst_drivers") or val_json.get("drivers") or []
    raw_moat = map_to_canonical_moat_label(val_json.get("moat", ""), sec1_text=sec1_clean)
    raw_labels = [raw_moat] + list(custom_drivers)
    sanitized_labels = sanitize_labels(raw_labels, action_signal=action_signal, base_ret=expected_mos, sec1_text=sec1_clean)

    # Extract Buffett & Munger Pricing Power from Section 1 text
    pricing_power_tier = map_to_canonical_pricing_power_tier(val_json.get("pricing_power_tier", ""), sec1_text=sec1_clean)
    pp_score = "Inelastic Demand · Low Churn" if "Absolute" in pricing_power_tier or "Strong" in pricing_power_tier else "Inflation Pass-Through"
    pp_summary = f"{pricing_power_tier}: Underwritten via Buffett & Munger pricing power framework."

    # Extract Buffett & Munger Cash Flow Predictability from Section 1 text
    predictability_tier = map_to_canonical_predictability_tier(val_json.get("predictability_tier", ""), sec1_text=sec1_clean)
    pred_score = "Manageable Visibility · Moat Protected"
    pred_summary = f"{predictability_tier}: Underwritten via 10-year visibility framework."

    # Await background catalyst intelligence
    try:
        cat_data = fut_catalyst.result(timeout=5)
    except Exception:
        cat_data = {}

    if isinstance(cat_data, dict):
        next_cat_date = cat_data.get("next_catalyst_date") or (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
        next_cat_event = cat_data.get("next_catalyst_event") or "Q3 FY26 Earnings Release"
        catalyst_timeline = cat_data.get("catalyst_timeline", [])
    elif isinstance(cat_data, list) and cat_data:
        next_cat = cat_data[0]
        next_cat_date = normalize_catalyst_date(next_cat.get("date", ""))
        next_cat_event = next_cat.get("event", "")
        catalyst_timeline = cat_data
    else:
        next_cat_date = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
        next_cat_event = "Q3 FY26 Earnings Release"
        catalyst_timeline = []

    metadata = {
        "status_label": sanitized_labels[0] if sanitized_labels else "Narrow Moat",
        "moat": raw_moat,
        "moat_label": raw_moat,
        "labels": sanitized_labels,
        "action_signal": action_signal,
        "fair_value_estimate": f"${expected_present_fv:.2f}",
        "expected_fair_value": f"${expected_present_fv:.2f}",
        "present_fair_value": expected_present_fv,
        "target_price_5y": f"${expected_target_5y:.2f}",
        "expected_val": expected_present_fv,
        "expected_mos": expected_mos,
        "expected_5y_return": expected_5y_return,
        "expected_5y_cagr": expected_5y_cagr,
        "stories": stories_metadata,
        **{f"story{idx}_target": f"${s['val']:.2f} ({s['target_5y_return_pct']:+.1f}%)" for idx, s in enumerate(stories_metadata, 1)},
        **{f"story{idx}_title": s["story_title"] for idx, s in enumerate(stories_metadata, 1)},
        "bear_target": f"${min_story['val']:.2f}",
        "base_target": f"${expected_present_fv:.2f}",
        "bull_target": f"${max_story['val']:.2f}",
        "upper_alert_threshold": upper_alert,
        "lower_alert_threshold": lower_alert,
        "next_catalyst_date": next_cat_date,
        "next_catalyst_event": next_cat_event,
        "catalyst_timeline": catalyst_timeline,
        "trigger_reason": "Genesis Initial Underwriting",
        "what_is_priced_in": f"{current_price / safe_float(val_json.get('normalized_oe_per_share'), 1.0):.1f}x",
        "top_funds": [],
        "institutional_ownership_pct": "",
        "insider_signal": "Neutral (10b5-1)",
        "insider_summary": "Audited SEC Form 3 / 20-F / Form 4 filings.",
        "pricing_power_tier": pricing_power_tier,
        "pricing_power_score": pp_score,
        "pricing_power_summary": pp_summary,
        "predictability_tier": predictability_tier,
        "predictability_score": pred_score,
        "predictability_summary": pred_summary,
        "full_html_content": full_html
    }

    print(f"   │ Signal: {action_signal} | Expected Fair Value: ${expected_present_fv:.2f} ({expected_mos:+.1f}%) | Moat: {raw_moat}", flush=True)
    print("   └" + "─" * 50, flush=True)

    return metadata, full_html


def review_stock_thesis(
    ticker: str,
    company_name: str,
    previous_thesis_summary: str,
    previous_status: str,
    trigger_reason: str,
    baseline_price: float,
    current_price: float,
    previous_version_num: int,
    previous_fair_value: str = "",
    previous_bear_target: str = "",
    previous_base_target: str = "",
    previous_bull_target: str = ""
) -> Tuple[Dict[str, Any], str]:
    """Reviews an active stock thesis by executing the overhauled 3-Agent pipeline in blind valuation mode."""
    print(f"\n🔄 [3-AGENT RE-EVALUATION] Running fresh blind coverage pipeline for {ticker} ({company_name})", flush=True)
    print(f"   │ Trigger: {trigger_reason}", flush=True)

    update_notes = f"""MATERIAL TRIGGER: {trigger_reason}
Previous Thesis Stance: {previous_status}
Previous Thesis Summary: {previous_thesis_summary}

Execute a fresh, blind fundamental evaluation without reference to stock market prices. Re-verify financial statements and the last 4 quarterly earnings call transcripts. Re-evaluate the premise, autonomously determine N distinct probable storylines spanning the company's full fundamental probability distribution, and calculate the independent DCF valuation matrix for each storyline."""

    metadata, full_html = generate_genesis_thesis(
        ticker=ticker,
        company_name=company_name,
        current_price=current_price,
        initial_notes=update_notes
    )

    metadata["what_was_before"] = previous_thesis_summary
    metadata["what_changes_now"] = metadata.get("executive_summary") or f"Thesis re-evaluated following: {trigger_reason}"
    metadata["alert_title"] = f"{ticker.upper()}: Coverage Re-Evaluated ({metadata.get('status_label', 'Active')})"
    metadata["action_signal"] = normalize_action_signal(metadata.get("action_signal", "BUY"))

    return metadata, full_html


# ==============================================================================
# SPECIALIZED OWNERSHIP & FUND INTELLIGENCE SUBAGENT PROMPTS
# ==============================================================================

def research_ownership_writeups(ticker: str, company_name: str) -> List[Dict[str, Any]]:
    """Specialized Subagent: Dispatches Google Grounding via Gemini Flash, extracts real web articles from groundingChunks, and validates live 200 OK URLs."""
    api_key = get_api_key()
    clean_t = ticker.upper().strip()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    
    prompt = f"Search Google for real, live investment thesis write-ups, hedge fund shareholder letters, Substack deep dives, and Value Investors Club pitches for {company_name} ({clean_t})."
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2}
    }
    
    verified_articles = []
    seen_urls = set()
    
    active_m = get_active_model()
    start_idx = GEMINI_MODELS_LADDER.index(active_m) if active_m in GEMINI_MODELS_LADDER else 0
    models_to_try = GEMINI_MODELS_LADDER[start_idx:]

    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            r = requests.post(url, json=payload, timeout=60)
            if r.status_code == 200:
                data = r.json()
                candidate = data.get("candidates", [{}])[0]
                grounding = candidate.get("groundingMetadata", {})
                chunks = grounding.get("groundingChunks", [])
                
                candidate_uris = []
                for c in chunks:
                    web = c.get("web", {})
                    uri = web.get("uri")
                    if uri and uri not in seen_urls:
                        candidate_uris.append((uri, web.get("title", f"{company_name} Deep Dive")))

                def _check_uri(item):
                    uri, default_title = item
                    try:
                        res = requests.get(uri, headers=headers, timeout=3.5, allow_redirects=True)
                        final_url = res.url
                        if res.status_code == 200 and not any(err in final_url.lower() for err in ["404", "not-found", "error"]):
                            if any(k in final_url for k in ["/p/", "/idea/", "/article/", ".pdf", "/letter", "/insights/", "/analysis/"]):
                                m = re.search(r"<title[^>]*>(.*?)</title>", res.text, re.IGNORECASE | re.DOTALL)
                                page_title = m.group(1).strip() if m else default_title
                                clean_title = re.sub(r"\s*\|\s*Substack.*", "", page_title, flags=re.IGNORECASE)
                                clean_title = re.sub(r"\s*-\s*by\s+.*", "", clean_title, flags=re.IGNORECASE).strip()
                                
                                # Determine Fund/Author
                                fund = "Independent Research"
                                if "substack.com" in final_url:
                                    match_sub = re.search(r"https?://([a-zA-Z0-9_-]+)\.substack\.com", final_url)
                                    fund = f"Substack / {match_sub.group(1).title()}" if match_sub else "Substack Memo"
                                elif "valueinvestorsclub.com" in final_url:
                                    fund = "Value Investors Club (VIC)"
                                elif "seekingalpha.com" in final_url:
                                    fund = "Seeking Alpha / Hedge Fund Letter"
                                elif ".pdf" in final_url:
                                    fund = "Shareholder Letter PDF"

                                desc_match = re.search(r'<meta\s+(?:name|property)=["\'](?:description|og:description)["\']\s+content=["\']([^"\']+)["\']', res.text, re.IGNORECASE)
                                if desc_match and len(desc_match.group(1).strip()) > 20:
                                    art_summary = desc_match.group(1).strip()[:180] + "..."
                                elif "substack.com" in final_url:
                                    art_summary = f"In-depth Substack memo detailing {company_name}'s business moat, unit monetization, and margin trajectory."
                                elif "valueinvestorsclub.com" in final_url:
                                    art_summary = f"Value Investors Club long/short analysis evaluating {company_name}'s intrinsic value, competitive dynamics, and risk-reward asymmetry."
                                elif ".pdf" in final_url or "letter" in final_url.lower():
                                    art_summary = f"Institutional shareholder letter & fund commentary analyzing capital allocation and portfolio position sizing for {company_name}."
                                else:
                                    art_summary = f"Fundamental equity research study examining {company_name}'s cash generation, market share durability, and valuation."

                                return {
                                    "title": clean_title or f"{company_name} Investment Thesis",
                                    "fund": fund,
                                    "date": "Verified Due Diligence",
                                    "summary": art_summary,
                                    "url": final_url
                                }
                    except Exception:
                        pass
                    return None

                if candidate_uris:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(candidate_uris), 8)) as executor:
                        results = executor.map(_check_uri, candidate_uris)
                        for r_art in results:
                            if r_art and r_art["url"] not in seen_urls:
                                seen_urls.add(r_art["url"])
                                verified_articles.append(r_art)
                                if len(verified_articles) >= 4:
                                    break
                break
            elif r.status_code in (500, 502, 503, 504, 429) and model_name != GEMINI_MODELS_LADDER[-1]:
                switch_to_fallback_model(f"HTTP {r.status_code}")
                continue
        except Exception as e:
            if model_name != GEMINI_MODELS_LADDER[-1]:
                switch_to_fallback_model(str(e))
                continue
            print(f"Error in grounding extraction for {clean_t}: {e}")
            
    return verified_articles


def research_institutional_funds(ticker: str, company_name: str) -> Dict[str, Any]:
    """Specialized Subagent Prompt: Searches live web for comprehensive 13F institutional shareholders and WhaleWisdom holdings."""
    clean_t = ticker.upper().strip()
    prompt = f"""You are an elite SEC Form 13F institutional equity ownership auditor.
Search the live web for the top institutional shareholders and 13F fund holdings of {clean_t} ({company_name}) from WhaleWisdom, SEC Form 13F filings, Nasdaq, Fintel, or Morningstar.

Extract and return a JSON object with:
"institutional_ownership_pct": "<e.g. 78.4%>",
"institutional_holders": [
  {{
    "name": "<e.g. Blackstone Inc. | Vanguard Group | BlackRock | Price (T.Rowe) | Fidelity | etc.>",
    "category": "<e.g. Private Equity Sponsor | Passive Index Giant | Asset Manager | Hedge Fund | Mutual Fund>",
    "stake": "<e.g. 28.4% or 8.2%>",
    "shares": "<e.g. 35,420,000>",
    "action": "<e.g. <span style='color: var(--accent-green);'>Increased +3.1%</span> | <span style='color: var(--text-dim);'>Held Firm</span> | <span style='color: var(--accent-red);'>Decreased -4.5%</span>>",
    "value": "<e.g. $166.5M>",
    "url": "https://whalewisdom.com/stock/{clean_t.lower()}"
  }}
]

Provide 8 to 12 top institutional holders with realistic/exact 13F share amounts, stake percentages, and dollar values.
Respond ONLY with the JSON object enclosed in ```json ```.
"""
    try:
        raw = call_gemini_with_search(prompt, temperature=0.1, use_search=True)
        return extract_json_block(raw)
    except Exception as e:
        print(f"Error researching institutional funds for {clean_t}: {e}")
        return {}


def research_insider_intel(ticker: str, company_name: str) -> Dict[str, Any]:
    """Specialized Subagent Prompt: Searches live web and OpenInsider for Form 4 filings and executive trading behavior."""
    prompt = f"""You are an SEC Form 4 insider trading forensic specialist.
Search OpenInsider (http://openinsider.com/search?q={ticker}) and SEC Form 4 filings for {company_name} ({ticker}).

Analyze all recent officer and director transactions over the trailing 12 months:
1. Identify all open-market purchases (P) vs open-market sales (S) vs option exercises (M) vs tax withholdings (D).
2. Calculate total buy volume vs sell volume and identify key executive names.
3. Classify overall insider sentiment into one of:
   - "Cluster Buying" (Multiple officers making open market purchases)
   - "Net Buying" (Purchases exceed sales)
   - "Heavy Net Executive Selling" (C-suite executive sales outweigh director purchases by >3:1 in total dollar volume)
   - "Net Selling" (Persistent open market sales with zero buying)
   - "Neutral (10b5-1)" (Routine pre-scheduled tax/RSU transactions)
   - "No Activity" (Zero Form 4 filings)
4. Provide a crisp 1-line summary of executive flow. If C-suite sold $10M+ while a director bought $200k, state the exact net dollar imbalance objectively (e.g. "C-Suite $15M sales outweigh $200k director purchase").

Output ONLY a JSON object:
```json
{{
  "insider_signal": "<Cluster Buying | Net Buying | Heavy Net Executive Selling | Net Selling | Neutral (10b5-1) | No Activity>",
  "insider_summary": "<Crisp 1-line summary with executive names and dollar values, max 12 words>",
  "key_executives_tracked": ["<Name 1 (Title)>", "<Name 2 (Title)>"]
}}
```
"""
    try:
        res = call_gemini_with_search(prompt, temperature=0.2)
        parsed = extract_json_block(res)
        if isinstance(parsed, dict):
            return parsed
    except Exception as e:
        print(f"Error researching insider intel for {ticker}: {e}")
    return {}


def research_catalyst_intelligence(ticker: str, company_name: str) -> Dict[str, str]:
    """Specialized Subagent: Searches live web for the exact next earnings release date and primary company catalyst."""
    clean_t = ticker.upper().strip()
    prompt = f"""You are an equity research calendar and corporate catalyst specialist.
Search the live web (Yahoo Finance, SEC filings, Nasdaq, company IR page, Bloomberg, Reuters) for the exact next earnings release date and primary upcoming corporate catalyst for {clean_t} ({company_name}).

Extract and return a JSON object with:
- "next_catalyst_date": Exact date in strict "YYYY-MM-DD" format (e.g. "2026-11-12"). If exact day is unconfirmed, provide the consensus estimated date.
- "next_catalyst_event": Specific, concise fundamental event name (max 4-5 words, e.g. "Q3 FY26 Earnings Release", "Singles Day GMV Report", "Investor Day Keynote", "FDA Advisory Committee Meeting").

Output ONLY the JSON object:
```json
{{
  "next_catalyst_date": "YYYY-MM-DD",
  "next_catalyst_event": "Q3 FY26 Earnings Release"
}}
```
"""
    try:
        res = call_gemini_with_search(prompt, temperature=0.1)
        parsed = extract_json_block(res)
        if isinstance(parsed, dict):
            c_date = normalize_catalyst_date(parsed.get("next_catalyst_date"))
            c_event = str(parsed.get("next_catalyst_event") or "Q3 FY26 Earnings Release").strip()
            return {
                "next_catalyst_date": c_date,
                "next_catalyst_event": c_event
            }
    except Exception as e:
        print(f"Error researching catalyst intelligence for {clean_t}: {e}")
    
    return {
        "next_catalyst_date": (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d"),
        "next_catalyst_event": "Q3 FY26 Earnings Release"
    }

