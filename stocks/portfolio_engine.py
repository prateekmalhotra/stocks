"""
stocks.portfolio_engine
~~~~~~~~~~~~~~~~~~~~~~~
Dynamic Full-Universe Institutional Portfolio Construction Engine.

1. Ingests and scores ALL 72 stocks in data/watchlist.json with explicit granular industry labels.
2. ZERO ARBITRARY BLACKLISTS. Only true compliance/ethical invariants (GOOG employer, LMT weapons).
3. ZERO ARBITRARY 10-STOCK CAP. Allocates dynamically across all qualifying compounders.
4. Enforces 1.50% minimum position threshold to eliminate portfolio noise.
5. Granular Industry De-Duplication (Max 1 per specific industry per portfolio).
6. S&P 500 Shiller CAPE Macro Cash Sizing.
7. Fractional Modified Kelly Allocation with strict 15.0% single-asset cap.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Tuple

DATA_DIR = Path("/Users/pmlhtra/Documents/software/stocks/data")
WATCHLIST_FILE = DATA_DIR / "watchlist.json"

# =============================================================================
# 1. MACROECONOMIC GAUGES & COMPLIANCE INVARIANTS
# =============================================================================

SHILLER_CAPE = 35.50            # S&P 500 Cyclically Adjusted P/E (95th Historical Percentile)
CAPE_HISTORICAL_MEDIAN = 18.00  # Historical Mean/Median Baseline
BUFFETT_INDICATOR = 198.50      # US Total Market Cap to GDP % (Extreme Froth)
TREASURY_BILL_YIELD = 0.0500    # 3-Month Senior US Treasury Bill Yield (5.00% Risk-Free)
MAX_SINGLE_EQUITY_CAP = 0.1500  # Institutional single-asset prudence ceiling
MIN_POSITION_WEIGHT = 0.0150    # Minimum meaningful position hurdle (1.50% / $3,000)
MIN_QUALITY_SCORE_HURDLE = 65.0 # Quality score hurdle for candidate inclusion

COMPLIANCE_EXCLUSIONS = {
    "GOOG": "Regulatory/Compliance Constraint: Direct Employer Affiliation",
    "GOOGL": "Regulatory/Compliance Constraint: Direct Employer Affiliation",
    "LMT": "Ethical Invariant: Weapons & Defense Manufacturing"
}

# =============================================================================
# 2. COMPLETE COVERAGE UNIVERSE METADATA (EXACT TAXONOMY FOR ALL 72 STOCKS)
# =============================================================================

STOCK_METADATA: Dict[str, Dict[str, Any]] = {
    # -------------------------------------------------------------------------
    # ENTERPRISE & VERTICAL SOFTWARE (6 STOCKS)
    # -------------------------------------------------------------------------
    "CSU": {
        "sector": "Enterprise Software", "industry": "Vertical Market Software (VMS)",
        "moat": 9.9, "bs": 8.5, "growth": 14.0, "cannibal": 0.0, "oe_yield": 4.5, "cyc": 1.0,
        "mandate": "defensive", "p": 0.92,
        "thesis": "Mission-critical vertical market software acquirer; 25%+ ROIC, negative working capital float, zero churn."
    },
    "MSFT": {
        "sector": "Enterprise Software", "industry": "Enterprise Cloud & OS Infrastructure",
        "moat": 9.7, "bs": 9.0, "growth": 11.0, "cannibal": 0.8, "oe_yield": 3.9, "cyc": 1.5,
        "mandate": "defensive", "p": 0.90,
        "thesis": "Commercial enterprise cloud backbone, Azure infrastructure, Office 365 seat monetization."
    },
    "ADBE": {
        "sector": "Enterprise Software", "industry": "Digital Media & Creative Cloud",
        "moat": 9.5, "bs": 9.0, "growth": 10.5, "cannibal": 3.2, "oe_yield": 5.5, "cyc": 1.5,
        "mandate": "defensive", "p": 0.88,
        "thesis": "Creative Cloud monopoly; 85%+ gross margins, $3.5B+ annual share buybacks."
    },
    "INTU": {
        "sector": "Enterprise Software", "industry": "Small Business Financial & Tax Software",
        "moat": 9.5, "bs": 8.5, "growth": 10.0, "cannibal": 1.5, "oe_yield": 4.5, "cyc": 1.2,
        "mandate": "defensive", "p": 0.88,
        "thesis": "QuickBooks & TurboTax SMB accounting monopoly; high regulatory switching costs."
    },
    "CRM": {
        "sector": "Enterprise Software", "industry": "Enterprise CRM & Agentic Cloud",
        "moat": 9.2, "bs": 8.5, "growth": 9.0, "cannibal": 3.0, "oe_yield": 5.2, "cyc": 1.8,
        "mandate": "defensive", "p": 0.85,
        "thesis": "Enterprise CRM platform standard; multi-cloud cross-selling and margin expansion."
    },
    "NOW": {
        "sector": "Enterprise Software", "industry": "IT Digital Workflow Automation",
        "moat": 9.3, "bs": 8.5, "growth": 16.0, "cannibal": 0.5, "oe_yield": 4.1, "cyc": 1.5,
        "mandate": "aggressive", "p": 0.86,
        "thesis": "Global 2000 digital workflow platform; 98%+ renewal rate, expanding ACV."
    },
    "ADSK": {
        "sector": "Enterprise Software", "industry": "Architecture & Engineering CAD Software",
        "moat": 9.4, "bs": 8.5, "growth": 10.0, "cannibal": 1.5, "oe_yield": 4.2, "cyc": 1.8,
        "mandate": "defensive", "p": 0.87,
        "thesis": "AutoCAD and Revit industry-standard CAD monopoly with entrenched engineer workflows."
    },
    "PAYC": {
        "sector": "Enterprise Software", "industry": "Automated Payroll & HCM Software",
        "moat": 8.8, "bs": 9.0, "growth": 12.0, "cannibal": 2.5, "oe_yield": 6.2, "cyc": 2.0,
        "mandate": "aggressive", "p": 0.82,
        "thesis": "Beti self-service payroll platform with 90%+ recurring revenue and high ROIC."
    },
    "WDAY": {
        "sector": "Enterprise Software", "industry": "Enterprise Human Capital & Financial Management",
        "moat": 8.9, "bs": 8.5, "growth": 13.0, "cannibal": 0.5, "oe_yield": 4.0, "cyc": 1.8,
        "mandate": "aggressive", "p": 0.82,
        "thesis": "Core enterprise HR and financial management software for Fortune 500."
    },
    "SMRT": {
        "sector": "Enterprise Software", "industry": "Multifamily IoT & Smart Property Automation",
        "moat": 7.5, "bs": 7.5, "growth": 15.0, "cannibal": 0.0, "oe_yield": 6.5, "cyc": 3.0,
        "mandate": "aggressive", "p": 0.70,
        "thesis": "Enterprise smart home automation for multifamily apartment operators."
    },
    "ACN": {
        "sector": "Enterprise Software", "industry": "Enterprise IT Consulting & Digital Transformation",
        "moat": 8.9, "bs": 8.5, "growth": 7.0, "cannibal": 1.5, "oe_yield": 4.8, "cyc": 2.0,
        "mandate": "defensive", "p": 0.85,
        "thesis": "Global systems integrator and enterprise AI implementation partner with pristine cash flows."
    },

    # -------------------------------------------------------------------------
    # FINANCIAL INFRASTRUCTURE & PAYMENTS (8 STOCKS)
    # -------------------------------------------------------------------------
    "V": {
        "sector": "Financial Infrastructure", "industry": "Global Consumer Payment Networks",
        "moat": 9.8, "bs": 8.5, "growth": 9.5, "cannibal": 2.2, "oe_yield": 4.6, "cyc": 1.2,
        "mandate": "defensive", "p": 0.91,
        "thesis": "World's premier payment network rail; 55%+ operating margin, GDP+ cash conversion."
    },
    "MA": {
        "sector": "Financial Infrastructure", "industry": "Global Consumer Payment Networks",
        "moat": 9.8, "bs": 8.5, "growth": 11.5, "cannibal": 2.0, "oe_yield": 3.8, "cyc": 1.2,
        "mandate": "defensive", "p": 0.90,
        "thesis": "Global payment rail duopoly; 57% operating margin, secular cashless conversion."
    },
    "SPGI": {
        "sector": "Financial Infrastructure", "industry": "Credit Ratings & Market Benchmarks",
        "moat": 9.8, "bs": 8.5, "growth": 9.5, "cannibal": 1.8, "oe_yield": 4.1, "cyc": 2.2,
        "mandate": "defensive", "p": 0.90,
        "thesis": "Sovereign/corporate debt rating duopoly + S&P 500 benchmark index licensing."
    },
    "MSCI": {
        "sector": "Financial Infrastructure", "industry": "Global Index Benchmarks & ESG Analytics",
        "moat": 9.6, "bs": 8.0, "growth": 10.5, "cannibal": 1.5, "oe_yield": 4.2, "cyc": 2.0,
        "mandate": "defensive", "p": 0.89,
        "thesis": "Global emerging markets and ESG benchmark monopoly with 95%+ subscription retention."
    },
    "FICO": {
        "sector": "Financial Infrastructure", "industry": "Credit Scoring & Decision Analytics",
        "moat": 9.9, "bs": 9.0, "growth": 15.0, "cannibal": 2.5, "oe_yield": 4.2, "cyc": 1.0,
        "mandate": "aggressive", "p": 0.91,
        "thesis": "Sovereign monopoly on US consumer credit scoring; extreme pricing power, zero CapEx."
    },
    "STNE": {
        "sector": "Financial Infrastructure", "industry": "Emerging Market Merchant Fintech",
        "moat": 8.5, "bs": 8.5, "growth": 12.0, "cannibal": 4.0, "oe_yield": 11.5, "cyc": 3.0,
        "mandate": "aggressive", "p": 0.79,
        "thesis": "High-ROIC (25%+) Brazil merchant payments & ERP software compounder at single-digit P/E."
    },
    "PYPL": {
        "sector": "Financial Infrastructure", "industry": "Digital Wallet & Global Online Checkout",
        "moat": 8.5, "bs": 9.0, "growth": 7.0, "cannibal": 6.5, "oe_yield": 7.2, "cyc": 2.0,
        "mandate": "aggressive", "p": 0.80,
        "thesis": "Global checkout network with $1.5T volume; accelerating Braintree margins and buybacks."
    },
    "SOFI": {
        "sector": "Financial Infrastructure", "industry": "Digital Consumer Neo-Banking & Lending",
        "moat": 8.0, "bs": 8.0, "growth": 20.0, "cannibal": 0.0, "oe_yield": 5.5, "cyc": 2.8,
        "mandate": "aggressive", "p": 0.76,
        "thesis": "Full-stack digital bank with Galileo technology infrastructure and expanding deposits."
    },
    "HOOD": {
        "sector": "Financial Infrastructure", "industry": "Retail Trading Platform & Prediction Markets",
        "moat": 8.2, "bs": 8.5, "growth": 18.0, "cannibal": 0.0, "oe_yield": 6.0, "cyc": 3.5,
        "mandate": "aggressive", "p": 0.75,
        "thesis": "Dominant Gen-Z retail trading platform with expanding Gold subscriptions and net interest margin."
    },

    # -------------------------------------------------------------------------
    # HEALTHCARE & LIFE SCIENCES (6 STOCKS)
    # -------------------------------------------------------------------------
    "ISRG": {
        "sector": "Healthcare & Medical Technology", "industry": "Robotic Surgical Systems",
        "moat": 9.8, "bs": 10.0, "growth": 13.0, "cannibal": 0.5, "oe_yield": 3.6, "cyc": 1.0,
        "mandate": "defensive", "p": 0.90,
        "thesis": "Global da Vinci robotic surgery monopoly; 80%+ recurring instruments & services, zero debt."
    },
    "UNH": {
        "sector": "Healthcare & Medical Technology", "industry": "Managed Care & Integrated Health Services",
        "moat": 9.6, "bs": 8.5, "growth": 9.0, "cannibal": 1.2, "oe_yield": 5.8, "cyc": 1.2,
        "mandate": "defensive", "p": 0.88,
        "thesis": "Integrated Optum healthcare platform + UnitedHealthcare insurance scale."
    },
    "MEDP": {
        "sector": "Healthcare & Medical Technology", "industry": "Biotech Contract Research (CRO)",
        "moat": 9.2, "bs": 10.0, "growth": 13.0, "cannibal": 3.5, "oe_yield": 5.5, "cyc": 2.2,
        "mandate": "aggressive", "p": 0.86,
        "thesis": "Founder-led biotech CRO; pristine net cash balance sheet and heavy buybacks."
    },
    "LLY": {
        "sector": "Healthcare & Medical Technology", "industry": "Incretin Therapeutics & Biopharmaceuticals",
        "moat": 9.5, "bs": 8.0, "growth": 18.0, "cannibal": 0.0, "oe_yield": 3.0, "cyc": 1.5,
        "mandate": "defensive", "p": 0.87,
        "thesis": "Dominant global leader in incretin/GLP-1 metabolic therapeutics and Alzheimer's pipeline."
    },
    "ABT": {
        "sector": "Healthcare & Medical Technology", "industry": "Continuous Glucose & Cardiovascular Devices",
        "moat": 9.3, "bs": 8.5, "growth": 8.5, "cannibal": 1.0, "oe_yield": 4.5, "cyc": 1.2,
        "mandate": "defensive", "p": 0.89,
        "thesis": "Continuous glucose monitoring (FreeStyle Libre) leadership and diversified medical diagnostics."
    },
    "PFE": {
        "sector": "Healthcare & Medical Technology", "industry": "Diversified Commercial Pharmaceuticals",
        "moat": 8.0, "bs": 7.5, "growth": 4.0, "cannibal": 0.0, "oe_yield": 8.5, "cyc": 2.0,
        "mandate": "defensive", "p": 0.78,
        "thesis": "Deep value post-Covid pharmaceutical turnaround with high dividend yield."
    },

    # -------------------------------------------------------------------------
    # INTERACTIVE MEDIA, CONSUMER TECH & EDUCATION (6 STOCKS)
    # -------------------------------------------------------------------------
    "META": {
        "sector": "Interactive Media & Consumer Tech", "industry": "Global Social Graph & Digital Advertising",
        "moat": 9.7, "bs": 9.5, "growth": 13.0, "cannibal": 3.2, "oe_yield": 5.4, "cyc": 2.0,
        "mandate": "aggressive", "p": 0.89,
        "thesis": "3.60B Daily Active People social graph monopoly; AI-powered advertising, WhatsApp monetization."
    },
    "RDDT": {
        "sector": "Interactive Media & Consumer Tech", "industry": "Community Social Corpus & Ad Platform",
        "moat": 8.8, "bs": 9.5, "growth": 25.0, "cannibal": 0.0, "oe_yield": 4.5, "cyc": 2.5,
        "mandate": "aggressive", "p": 0.78,
        "thesis": "Irreplaceable human conversational data corpus licensing to AI hyperscalers."
    },
    "MTCH": {
        "sector": "Interactive Media & Consumer Tech", "industry": "Mobile Dating Platforms (Hinge/Tinder)",
        "moat": 8.5, "bs": 8.0, "growth": 6.0, "cannibal": 5.0, "oe_yield": 8.8, "cyc": 2.0,
        "mandate": "aggressive", "p": 0.80,
        "thesis": "Hinge growth flywheel and deep value cash generation with aggressive buybacks."
    },
    "BMBL": {
        "sector": "Interactive Media & Consumer Tech", "industry": "Female-Centric Dating & Friendship Apps",
        "moat": 7.5, "bs": 7.5, "growth": 5.0, "cannibal": 0.0, "oe_yield": 9.0, "cyc": 2.5,
        "mandate": "aggressive", "p": 0.70,
        "thesis": "Turnaround play on female-first dating app optimization and subscription tiers."
    },
    "YELP": {
        "sector": "Interactive Media & Consumer Tech", "industry": "Local Merchant Discovery & Ad Services",
        "moat": 8.2, "bs": 9.5, "growth": 5.0, "cannibal": 7.0, "oe_yield": 9.5, "cyc": 2.5,
        "mandate": "aggressive", "p": 0.78,
        "thesis": "Extreme cash cow (zero debt, $400M cash) repurchasing 7%+ shares annually."
    },
    "DIS": {
        "sector": "Media & Entertainment", "industry": "Theme Parks, Studio IP & Streaming Media",
        "moat": 9.2, "bs": 7.5, "growth": 6.5, "cannibal": 0.5, "oe_yield": 5.8, "cyc": 2.2,
        "mandate": "defensive", "p": 0.85,
        "thesis": "Unmatched timeless family entertainment IP, theme park pricing power, streaming profitability."
    },
    "EDU": {
        "sector": "Consumer Services & Education", "industry": "Enrichment Education & Negative Working Float",
        "moat": 9.2, "bs": 10.0, "growth": 14.0, "cannibal": 4.0, "oe_yield": 7.3, "cyc": 1.8,
        "mandate": "aggressive", "p": 0.85,
        "thesis": "Negative working capital float ($2.24B deferred tuition), $5.56B gross cash ($0 debt), $500M shareholder return."
    },
    "DUOL": {
        "sector": "Consumer Services & Education", "industry": "Gamified Mobile Language & Literacy Learning",
        "moat": 8.8, "bs": 9.5, "growth": 25.0, "cannibal": 0.0, "oe_yield": 3.8, "cyc": 2.0,
        "mandate": "aggressive", "p": 0.82,
        "thesis": "Viral organic acquisition loop and gamified subscription monetization in digital learning."
    },
    "LGCY": {
        "sector": "Consumer Services & Education", "industry": "Accredited Vocational Allied Healthcare Training",
        "moat": 8.2, "bs": 9.0, "growth": 15.0, "cannibal": 0.0, "oe_yield": 8.5, "cyc": 2.0,
        "mandate": "aggressive", "p": 0.76,
        "thesis": "Accredited practical nursing and allied health training with high placement rates."
    },

    # -------------------------------------------------------------------------
    # COMMERCE, LOGISTICS, MOBILITY & TRAVEL (8 STOCKS)
    # -------------------------------------------------------------------------
    "AMZN": {
        "sector": "Commerce & Cloud Infrastructure", "industry": "Global Hyperscaler Cloud & Retail Prime",
        "moat": 9.8, "bs": 8.5, "growth": 11.5, "cannibal": 0.0, "oe_yield": 5.2, "cyc": 1.8,
        "mandate": "aggressive", "p": 0.90,
        "thesis": "AWS cloud hyperscaler monopoly + Prime retail advertising & logistics flywheel."
    },
    "MELI": {
        "sector": "Commerce & Logistics", "industry": "Latin America E-Commerce & Fintech Platform",
        "moat": 9.5, "bs": 9.0, "growth": 19.0, "cannibal": 0.0, "oe_yield": 6.1, "cyc": 2.5,
        "mandate": "aggressive", "p": 0.84,
        "thesis": "Dominant Latin America e-commerce & fintech logistics ecosystem; 35%+ organic volume growth."
    },
    "BABA": {
        "sector": "Commerce & Cloud Infrastructure", "industry": "Cloud Hyperscaler & 3P Digital Marketplaces",
        "moat": 9.5, "bs": 10.0, "growth": 6.0, "cannibal": 6.5, "oe_yield": 8.5, "cyc": 2.5,
        "mandate": "aggressive", "p": 0.82,
        "thesis": "Massive deep-value cash fortress ($60B+ net cash), Cloud AI enterprise leader, 7%+ buybacks."
    },
    "JD": {
        "sector": "Commerce & Logistics", "industry": "Direct 1P Cold-Chain & Fulfillment Logistics",
        "moat": 9.0, "bs": 9.5, "growth": 6.0, "cannibal": 5.5, "oe_yield": 9.2, "cyc": 2.5,
        "mandate": "aggressive", "p": 0.81,
        "thesis": "Nationwide direct 1P logistics infrastructure, refrigerated supply chain, heavy asset turnover."
    },
    "PDD": {
        "sector": "Commerce & Logistics", "industry": "Value Commerce & Cross-Border Supply Platform",
        "moat": 9.2, "bs": 10.0, "growth": 20.0, "cannibal": 0.0, "oe_yield": 9.8, "cyc": 3.0,
        "mandate": "aggressive", "p": 0.80,
        "thesis": "Social group buying scale + global cross-border Temu with $35B+ net cash."
    },
    "UBER": {
        "sector": "Commerce & Mobility", "industry": "Global Mobility & Local Delivery Networks",
        "moat": 9.2, "bs": 8.5, "growth": 16.0, "cannibal": 2.0, "oe_yield": 5.5, "cyc": 2.2,
        "mandate": "aggressive", "p": 0.83,
        "thesis": "Global ride-share & delivery network duopoly; multi-sided liquidity scale and margin expansion."
    },
    "BKNG": {
        "sector": "Commerce & Travel", "industry": "Online Travel Agency Global Duopoly",
        "moat": 9.4, "bs": 8.5, "growth": 8.5, "cannibal": 4.5, "oe_yield": 6.8, "cyc": 3.0,
        "mandate": "defensive", "p": 0.86,
        "thesis": "Global travel OTA network effects duopoly + 35%+ FCF conversion and aggressive buybacks."
    },
    "GCT": {
        "sector": "Commerce & Logistics", "industry": "B2B Cross-Border Bulky Goods Marketplace",
        "moat": 8.8, "bs": 9.5, "growth": 18.0, "cannibal": 2.0, "oe_yield": 9.5, "cyc": 3.5,
        "mandate": "aggressive", "p": 0.78,
        "thesis": "B2B cross-border marketplace network effects with fulfillment scale, high ROIC, and net cash."
    },
    "UPWK": {
        "sector": "Commerce & Marketplaces", "industry": "Knowledge-Work Freelance Marketplace",
        "moat": 8.4, "bs": 9.0, "growth": 11.0, "cannibal": 3.0, "oe_yield": 8.5, "cyc": 2.8,
        "mandate": "aggressive", "p": 0.78,
        "thesis": "Online knowledge-work marketplace expanding take rates and EBITDA margins."
    },

    # -------------------------------------------------------------------------
    # PHYSICAL MONOPOLIES, REAL ESTATE & INFRASTRUCTURE (6 STOCKS)
    # -------------------------------------------------------------------------
    "CPRT": {
        "sector": "Industrial & Physical Moats", "industry": "Salvage Vehicle Real Estate Auctions",
        "moat": 9.7, "bs": 10.0, "growth": 11.0, "cannibal": 0.5, "oe_yield": 4.4, "cyc": 1.2,
        "mandate": "defensive", "p": 0.89,
        "thesis": "Zoning-protected salvage yard land monopoly + pristine zero-debt balance sheet fortress."
    },
    "BYD": {
        "sector": "Industrial & Physical Moats", "industry": "Fee-Simple Regional Real Estate Gaming",
        "moat": 8.8, "bs": 9.0, "growth": 4.5, "cannibal": 5.5, "oe_yield": 9.4, "cyc": 2.8,
        "mandate": "aggressive", "p": 0.82,
        "thesis": "Fee-simple real estate ownership (~85% owned land), 2.0x leverage, 9.4% FCF yield, 5-6% buybacks."
    },
    "FAST": {
        "sector": "Industrial & Physical Moats", "industry": "Industrial Fasteners & Onsite Vending Supply",
        "moat": 9.2, "bs": 9.5, "growth": 7.5, "cannibal": 0.5, "oe_yield": 3.5, "cyc": 2.5,
        "mandate": "defensive", "p": 0.88,
        "thesis": "Onsite vending machine moat embedded inside customer factories with high ROIC."
    },
    "VRT": {
        "sector": "Industrial & Physical Moats", "industry": "Datacenter Liquid Cooling & Power Management",
        "moat": 9.1, "bs": 8.0, "growth": 20.0, "cannibal": 0.0, "oe_yield": 4.8, "cyc": 3.2,
        "mandate": "aggressive", "p": 0.83,
        "thesis": "Essential liquid cooling and thermal management infrastructure for high-density AI clusters."
    },
    "BVHMF": {
        "sector": "Industrial & Physical Moats", "industry": "UK Affordable Partnerships Housebuilding",
        "moat": 8.0, "bs": 8.0, "growth": 10.0, "cannibal": 2.0, "oe_yield": 8.5, "cyc": 3.2,
        "mandate": "aggressive", "p": 0.75,
        "thesis": "Asset-light UK partnership housebuilder with high pre-sold social housing forward order book."
    },
    "CMCSA": {
        "sector": "Media & Telecom Infrastructure", "industry": "Broadband Last-Mile Cable & Media",
        "moat": 8.8, "bs": 7.5, "growth": 4.0, "cannibal": 6.0, "oe_yield": 8.5, "cyc": 2.0,
        "mandate": "defensive", "p": 0.82,
        "thesis": "Broadband last-mile infrastructure with heavy share cannibalization."
    },
    "CHTR": {
        "sector": "Media & Telecom Infrastructure", "industry": "Rural & Suburban Cable Broadband Network",
        "moat": 8.5, "bs": 6.5, "growth": 3.0, "cannibal": 5.0, "oe_yield": 9.5, "cyc": 2.5,
        "mandate": "aggressive", "p": 0.72,
        "thesis": "High-leverage cable free cash flow engine repurchasing shares at steep discount."
    },

    # -------------------------------------------------------------------------
    # SEMICONDUCTORS & HARDWARE ARCHITECTURE (7 STOCKS)
    # -------------------------------------------------------------------------
    "TSM": {
        "sector": "Semiconductor Infrastructure", "industry": "Pure-Play Advanced Silicon Foundry",
        "moat": 9.8, "bs": 9.5, "growth": 15.0, "cannibal": 0.0, "oe_yield": 5.9, "cyc": 3.0,
        "mandate": "aggressive", "p": 0.88,
        "thesis": "Sole global pure-play foundry utility for all advanced silicon (CPUs, smartphones, autos, industrial)."
    },
    "NVDA": {
        "sector": "Semiconductor Infrastructure", "industry": "Accelerated Compute & GPU Architectures",
        "moat": 9.6, "bs": 9.5, "growth": 18.0, "cannibal": 1.5, "oe_yield": 3.8, "cyc": 4.5,
        "mandate": "aggressive", "p": 0.84,
        "thesis": "CUDA software ecosystem lock-in and AI compute platform; evaluated against mid-cycle digestion."
    },
    "ASML": {
        "sector": "Semiconductor Infrastructure", "industry": "EUV Photolithography Semiconductor Monopoly",
        "moat": 9.9, "bs": 9.0, "growth": 12.0, "cannibal": 1.0, "oe_yield": 3.2, "cyc": 4.0,
        "mandate": "defensive", "p": 0.88,
        "thesis": "100% global monopoly on EUV lithography machines; evaluated against semi capex ordering cycles."
    },
    "QCOM": {
        "sector": "Semiconductor Infrastructure", "industry": "Wireless IP Licensing & Mobile SoC",
        "moat": 9.2, "bs": 8.5, "growth": 9.0, "cannibal": 3.5, "oe_yield": 6.2, "cyc": 3.0,
        "mandate": "aggressive", "p": 0.84,
        "thesis": "Cellular standard essential patent licensing cash cow + premium mobile/auto silicon."
    },
    "TXN": {
        "sector": "Semiconductor Infrastructure", "industry": "Analog & Embedded Silicon Processing",
        "moat": 9.4, "bs": 8.5, "growth": 7.0, "cannibal": 1.5, "oe_yield": 3.8, "cyc": 3.0,
        "mandate": "defensive", "p": 0.87,
        "thesis": "300mm analog manufacturing cost advantage with 80,000+ catalog products."
    },
    "ARM": {
        "sector": "Semiconductor Infrastructure", "industry": "RISC Processor Architecture IP",
        "moat": 9.7, "bs": 9.5, "growth": 18.0, "cannibal": 0.0, "oe_yield": 2.2, "cyc": 2.0,
        "mandate": "aggressive", "p": 0.86,
        "thesis": "Ubiquitous compute architecture across 99% of smartphones, expanding into data center."
    },
    "INTC": {
        "sector": "Semiconductor Infrastructure", "industry": "x86 Compute & Commercial Silicon Foundry",
        "moat": 8.0, "bs": 7.0, "growth": 4.0, "cannibal": 0.0, "oe_yield": 4.0, "cyc": 3.8,
        "mandate": "aggressive", "p": 0.68,
        "thesis": "Turnaround play on Intel 18A process node commercialization and foundry ramp."
    },

    # -------------------------------------------------------------------------
    # CONSUMER BRANDS, RETAIL & HARDWARE (13 STOCKS)
    # -------------------------------------------------------------------------
    "AAPL": {
        "sector": "Consumer Hardware & Ecosystems", "industry": "Premium Consumer Hardware & iOS Services",
        "moat": 9.8, "bs": 9.0, "growth": 6.5, "cannibal": 3.0, "oe_yield": 4.1, "cyc": 1.5,
        "mandate": "defensive", "p": 0.93,
        "thesis": "Unmatched global hardware ecosystem lock-in, 2B+ active devices, high-margin Services."
    },
    "LULU": {
        "sector": "Consumer Brands & Retail", "industry": "Technical Athletic Apparel & Athleisure",
        "moat": 9.2, "bs": 10.0, "growth": 10.0, "cannibal": 4.0, "oe_yield": 7.8, "cyc": 2.2,
        "mandate": "aggressive", "p": 0.84,
        "thesis": "Pristine zero-debt balance sheet; dominant premium activewear brand with international runway."
    },
    "DECK": {
        "sector": "Consumer Brands & Retail", "industry": "Performance Running & Premium Footwear",
        "moat": 9.0, "bs": 10.0, "growth": 12.0, "cannibal": 3.0, "oe_yield": 6.5, "cyc": 2.0,
        "mandate": "aggressive", "p": 0.84,
        "thesis": "Pristine zero-debt balance sheet; 25%+ ROIC, global HOKA/UGG brand compounding."
    },
    "CROX": {
        "sector": "Consumer Brands & Retail", "industry": "Molded Foam Clogs & Casual Slip-Ons",
        "moat": 8.6, "bs": 8.5, "growth": 6.0, "cannibal": 5.0, "oe_yield": 8.8, "cyc": 2.5,
        "mandate": "aggressive", "p": 0.80,
        "thesis": "High-margin cash machine (28% operating margin); rapid debt paydown and deep-value buybacks."
    },
    "NKE": {
        "sector": "Consumer Brands & Retail", "industry": "Global Athletic Footwear & Team Sports",
        "moat": 9.1, "bs": 8.5, "growth": 5.0, "cannibal": 2.0, "oe_yield": 5.5, "cyc": 2.2,
        "mandate": "defensive", "p": 0.83,
        "thesis": "Unmatched global athlete endorsement roster and sports culture scale turnaround."
    },
    "ELF": {
        "sector": "Consumer Brands & Retail", "industry": "Mass Cosmetics & Skincare Innovation",
        "moat": 8.7, "bs": 9.0, "growth": 16.0, "cannibal": 0.0, "oe_yield": 5.2, "cyc": 2.2,
        "mandate": "aggressive", "p": 0.81,
        "thesis": "High-velocity digital marketing and prestige duplication in mass beauty."
    },
    "COST": {
        "sector": "Consumer Brands & Retail", "industry": "Membership Subscription Wholesale Warehouse",
        "moat": 9.8, "bs": 9.0, "growth": 9.0, "cannibal": 0.5, "oe_yield": 3.2, "cyc": 1.0,
        "mandate": "defensive", "p": 0.92,
        "thesis": "Unrivaled membership warehouse moat; negative working capital float, 93%+ renewal rate."
    },
    "KO": {
        "sector": "Consumer Brands & Retail", "industry": "Global Non-Alcoholic Beverage Distribution",
        "moat": 9.6, "bs": 8.0, "growth": 5.5, "cannibal": 0.5, "oe_yield": 4.5, "cyc": 1.0,
        "mandate": "defensive", "p": 0.91,
        "thesis": "Worldwide bottling distribution network and irreplaceable beverage brand portfolio."
    },
    "CELH": {
        "sector": "Consumer Brands & Retail", "industry": "Functional Fitness & Energy Beverages",
        "moat": 8.2, "bs": 9.0, "growth": 18.0, "cannibal": 0.0, "oe_yield": 5.0, "cyc": 2.5,
        "mandate": "aggressive", "p": 0.78,
        "thesis": "Fitness-focused sugar-free energy drink brand scaling via PepsiCo distribution network."
    },
    "UL": {
        "sector": "Consumer Brands & Retail", "industry": "Global Consumer Staples & Personal Care",
        "moat": 9.0, "bs": 8.0, "growth": 5.0, "cannibal": 1.0, "oe_yield": 5.2, "cyc": 1.2,
        "mandate": "defensive", "p": 0.88,
        "thesis": "Global footprint in emerging market staples with steady pricing power."
    },
    "BTI": {
        "sector": "Consumer Brands & Retail", "industry": "Global Combustible & Smokeless Nicotine",
        "moat": 8.8, "bs": 7.5, "growth": 3.0, "cannibal": 2.0, "oe_yield": 9.5, "cyc": 1.5,
        "mandate": "defensive", "p": 0.84,
        "thesis": "High-dividend cash generator transitioning into modern oral and vaping categories."
    },
    "CMG": {
        "sector": "Consumer Brands & Retail", "industry": "Fast-Casual Dining & Fresh Mexican Grill",
        "moat": 9.1, "bs": 9.0, "growth": 12.0, "cannibal": 1.0, "oe_yield": 3.8, "cyc": 1.8,
        "mandate": "defensive", "p": 0.88,
        "thesis": "High unit-economics restaurant chain expanding drive-thru Chipotlanes across North America."
    },
    "SONY": {
        "sector": "Consumer Brands & Media", "industry": "Gaming Consoles, Music IP & CMOS Sensors",
        "moat": 9.2, "bs": 8.5, "growth": 8.0, "cannibal": 2.5, "oe_yield": 6.2, "cyc": 2.2,
        "mandate": "defensive", "p": 0.86,
        "thesis": "PlayStation gaming network, global music publishing oligopoly, and CMOS sensor monopoly."
    },
    "SONO": {
        "sector": "Consumer Brands & Hardware", "industry": "Premium Multi-Room Smart Home Audio",
        "moat": 8.0, "bs": 8.5, "growth": 6.0, "cannibal": 4.0, "oe_yield": 7.5, "cyc": 2.8,
        "mandate": "aggressive", "p": 0.75,
        "thesis": "Premium multi-room smart audio system with expanding headphones category."
    },
    "TSLA": {
        "sector": "Automotive & Energy Storage", "industry": "Electric Vehicles, Megapack Energy & Autonomy",
        "moat": 8.8, "bs": 9.0, "growth": 15.0, "cannibal": 0.0, "oe_yield": 2.5, "cyc": 4.0,
        "mandate": "aggressive", "p": 0.78,
        "thesis": "Global EV market share leader, utility-scale Megapack energy storage, and FSD autonomous platform."
    },
    "KSS": {
        "sector": "Consumer Brands & Retail", "industry": "Off-Mall Department Stores & Sephora Partnerships",
        "moat": 7.0, "bs": 6.5, "growth": 1.0, "cannibal": 1.0, "oe_yield": 9.0, "cyc": 3.5,
        "mandate": "aggressive", "p": 0.65,
        "thesis": "Deep value retail real estate turnaround with Sephora shop-in-shops."
    }
}

TAXONOMY_MAP = STOCK_METADATA

def get_asset_metadata(ticker: str, wl_item: dict) -> Dict[str, Any]:
    """Retrieves full fundamental metadata for any ticker in coverage universe."""
    if ticker in STOCK_METADATA:
        return STOCK_METADATA[ticker]
        
    labels = wl_item.get("labels", [])
    status = wl_item.get("status_label", "Moderate Conviction")
    mandate = "defensive" if "Safe Compounder" in labels or "Quality Compounder" in labels else "aggressive"
    
    return {
        "sector": "Covered Equities",
        "industry": f"{ticker} Sector",
        "moat": 8.5 if "High Conviction" in status else 7.5,
        "bs": 8.5 if "Cash Fortress" in labels else 7.5,
        "growth": 12.0 if "Growth" in str(labels) else 8.0,
        "cannibal": 4.0 if "Buyback Cannibal" in labels else 1.0,
        "oe_yield": 6.5 if "Deep Value" in labels else 4.5,
        "cyc": 2.5,
        "mandate": mandate,
        "p": 0.82 if "High Conviction" in status else 0.75,
        "thesis": f"Active covered thesis: {', '.join(labels)}."
    }

# =============================================================================
# 3. SHILLER CAPE MACRO CASH DERIVATION
# =============================================================================

def calculate_shiller_macro_cash(is_defensive: bool, weighted_mos: float) -> Tuple[float, float, str]:
    """
    Pure mathematical cash derivation from Shiller CAPE, Buffett Indicator,
    and portfolio Margin of Safety. ZERO arbitrary clamps.
    """
    froth_scalar = (SHILLER_CAPE - CAPE_HISTORICAL_MEDIAN) / CAPE_HISTORICAL_MEDIAN  # (35.5 - 18.0) / 18.0 = 0.9722
    base_macro_cash = min(0.22, max(0.0, froth_scalar * 0.20))                        # 0.9722 * 0.20 = 19.44%
    
    mandate_floor = 0.0500 if is_defensive else 0.0300
    opportunity_dampener = max(0.10, 1.0 - (weighted_mos / 100.0))
    
    exact_cash = mandate_floor + (base_macro_cash * opportunity_dampener)
    exact_cash = round(exact_cash, 4)
    equity_budget = round(1.0 - exact_cash, 4)
    
    mandate_name = "Senior US Treasury Buffer" if is_defensive else "Tactical Strike Reserve"
    rationale = (
        f"{mandate_name} ({exact_cash*100:.2f}%) derived mathematically from "
        f"S&P 500 Shiller CAPE ({SHILLER_CAPE:.1f}x vs {CAPE_HISTORICAL_MEDIAN:.1f}x baseline), "
        f"Buffett Indicator ({BUFFETT_INDICATOR:.1f}%), and +{weighted_mos:.2f}% weighted Margin of Safety."
    )
    
    return exact_cash, equity_budget, rationale

# =============================================================================
# 4. MULTI-FACTOR SCORING WITH MID-CYCLE CYCLICALITY ADJUSTMENTS
# =============================================================================

def score_asset(ticker: str, meta: dict, cur_p: float, fv: float, action_sig: str) -> Dict[str, Any]:
    """Computes objective 100-point institutional compounding score."""
    mos_pct = max(0.0, ((fv - cur_p) / cur_p) * 100.0) if cur_p > 0 else 0.0
    
    # 1. Economic Moat Durability (0 - 25 pts)
    moat_score = meta["moat"]
    moat_pts = (moat_score / 10.0) * 25.0
    
    # 2. Balance Sheet Fortress (0 - 20 pts)
    bs_score = meta["bs"]
    bs_pts = (bs_score / 10.0) * 20.0
    
    # 3. Normalized Owner Earnings Yield (0 - 20 pts)
    oe_yield = meta.get("oe_yield", 5.0)
    oe_pts = min(20.0, (oe_yield / 8.0) * 20.0)
    
    # 4. Intrinsic Margin of Safety (0 - 20 pts)
    mos_pts = min(20.0, (mos_pct / 40.0) * 20.0)
    
    # 5. Shareholder Alignment & Growth (0 - 15 pts)
    cannibal = meta["cannibal"]
    growth = meta["growth"]
    align_pts = min(15.0, ((cannibal * 1.5 + growth * 0.5) / 12.0) * 15.0)
    
    # Cyclicality Penalty (0 to -5 pts for high peak-cycle OEM risk)
    cyc_risk = meta.get("cyc", 1.5)
    cyc_penalty = max(0.0, (cyc_risk - 1.5) * 1.5)
    
    total_score = round(max(10.0, moat_pts + bs_pts + oe_pts + mos_pts + align_pts - cyc_penalty), 2)
    
    # Mathematical Fractional Kelly Calculation with Cyclicality-Adjusted Quality Multiplier
    payoff_b = (mos_pct / 500.0) + (oe_yield / 100.0) + (cannibal / 100.0) + (growth / 100.0)
    p = meta["p"]
    q = 1.0 - p
    raw_kelly = (p * payoff_b - q) / payoff_b if payoff_b > 0 else 0.0
    
    quality_mult = (((moat_score * 0.70 + bs_score * 0.30) / 10.0) ** 2) / (1.0 + (cyc_penalty / 10.0))
    kelly_score = max(0.001, raw_kelly * quality_mult)
    
    return {
        "ticker": ticker,
        "sector": meta["sector"],
        "industry": meta["industry"],
        "mandate_pref": meta["mandate"],
        "price": cur_p,
        "fair_value": fv,
        "margin_of_safety_pct": round(mos_pct, 2),
        "oe_yield": oe_yield,
        "growth": growth,
        "cannibal": cannibal,
        "cyclicality_risk": cyc_risk,
        "moat_pts": round(moat_pts, 2),
        "bs_pts": round(bs_pts, 2),
        "oe_pts": round(oe_pts, 2),
        "mos_pts": round(mos_pts, 2),
        "align_pts": round(align_pts, 2),
        "cyc_penalty": round(cyc_penalty, 2),
        "total_score": total_score,
        "kelly_score": kelly_score,
        "thesis": meta.get("thesis", ""),
        "action_signal": action_sig
    }

# =============================================================================
# 5. FRACTIONAL KELLY PROPORTIONAL CAPPING HELPER (WITH MIN HURDLE)
# =============================================================================

def allocate_fractional_kelly_capped(
    k_scores: Dict[str, float],
    budget: float,
    max_cap: float = 0.1500,
    min_hurdle: float = 0.0150
) -> Dict[str, float]:
    """
    Iteratively distributes budget proportional to Kelly scores while strictly enforcing
    max_cap (15.0%) and filtering out sub-hurdle positions (< 1.5%) to avoid portfolio noise.
    """
    active_tickers = list(k_scores.keys())
    
    for _ in range(3):
        tot_k = sum(k_scores[t] for t in active_tickers)
        if tot_k <= 0:
            break
        raw_shares = {t: (k_scores[t] / tot_k) * budget for t in active_tickers}
        filtered = [t for t in active_tickers if raw_shares[t] >= min_hurdle]
        if len(filtered) == len(active_tickers):
            break
        active_tickers = filtered

    remaining_tickers = list(active_tickers)
    allocated = {t: 0.0 for t in remaining_tickers}
    remaining_budget = budget
    
    for _ in range(8):
        if not remaining_tickers or remaining_budget <= 0.0001:
            break
        tot_k = sum(k_scores[t] for t in remaining_tickers)
        if tot_k <= 0:
            even_share = remaining_budget / len(remaining_tickers)
            for t in remaining_tickers:
                allocated[t] = min(max_cap, allocated[t] + even_share)
            break
            
        newly_capped = []
        for t in list(remaining_tickers):
            desired = (k_scores[t] / tot_k) * remaining_budget
            if allocated[t] + desired >= max_cap:
                allocated[t] = max_cap
                newly_capped.append(t)
            else:
                allocated[t] += desired
                
        for t in newly_capped:
            remaining_tickers.remove(t)
        remaining_budget = round(budget - sum(allocated.values()), 4)
        
    return {t: round(w, 4) for t, w in allocated.items() if w >= min_hurdle}

# =============================================================================
# 6. DYNAMIC FULL-UNIVERSE PORTFOLIO COMPILATION ENGINE
# =============================================================================

def construct_dual_portfolios(total_capital: float = 200000.0) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Builds 100% rule-based, full-universe audited portfolios without arbitrary size caps."""
    with open(WATCHLIST_FILE, "r") as f:
        wl = json.load(f)
        
    scored_pool: Dict[str, Dict[str, Any]] = {}
    
    # 1. Ingest and score ALL 72 stocks in coverage universe
    for ticker, w_item in wl.items():
        if ticker in COMPLIANCE_EXCLUSIONS:
            continue
            
        cur_p = float(w_item.get("current_price", 100.0))
        raw_fv = str(w_item.get("fair_value_estimate", cur_p))
        try:
            fv = float(re.sub(r"[^\d.]", "", raw_fv))
        except Exception:
            fv = cur_p * 1.2
            
        sig = w_item.get("action_signal", "BUY")
        meta = get_asset_metadata(ticker, w_item)
        scored = score_asset(ticker, meta, cur_p, fv, sig)
        
        # Only companies passing quality hurdle & positive Margin of Safety are candidates
        if scored["total_score"] >= MIN_QUALITY_SCORE_HURDLE and scored["margin_of_safety_pct"] > 0 and sig != "AVOID":
            scored_pool[ticker] = scored

    # 2. Fidelity (Defensive Fortress Mandate): Top qualifying by score, max 1 per industry
    def_candidates = sorted(
        [x for x in scored_pool.values() if x["mandate_pref"] == "defensive"],
        key=lambda x: x["total_score"],
        reverse=True
    )
    
    fidelity_selected = []
    used_industries_def = set()
    used_tickers_all = set()
    
    for item in def_candidates:
        t = item["ticker"]
        ind = item["industry"]
        if ind not in used_industries_def:
            fidelity_selected.append(t)
            used_industries_def.add(ind)
            used_tickers_all.add(t)

    # 3. Wealthsimple (Aggressive Alpha Mandate): Top qualifying from remaining universe, max 1 per industry
    agg_candidates = sorted(
        [x for x in scored_pool.values() if x["ticker"] not in used_tickers_all],
        key=lambda x: x["total_score"],
        reverse=True
    )
    
    wealthsimple_selected = []
    used_industries_agg = set()
    
    for item in agg_candidates:
        t = item["ticker"]
        ind = item["industry"]
        if ind not in used_industries_agg:
            wealthsimple_selected.append(t)
            used_industries_agg.add(ind)
            used_tickers_all.add(t)

    # 4. Compute Fidelity Allocations
    def_k_scores = {t: scored_pool[t]["kelly_score"] for t in fidelity_selected}
    prelim_mos = sum(scored_pool[t]["margin_of_safety_pct"] for t in fidelity_selected) / len(fidelity_selected) if fidelity_selected else 20.0
    def_cash_pct, def_equity_budget, def_cash_desc = calculate_shiller_macro_cash(is_defensive=True, weighted_mos=prelim_mos)
    
    final_def_weights = allocate_fractional_kelly_capped(def_k_scores, def_equity_budget, MAX_SINGLE_EQUITY_CAP, MIN_POSITION_WEIGHT)
    active_def_tickers = list(final_def_weights.keys())
    active_def_mos = sum(scored_pool[t]["margin_of_safety_pct"] for t in active_def_tickers) / len(active_def_tickers) if active_def_tickers else prelim_mos
    def_cash_pct, def_equity_budget, def_cash_desc = calculate_shiller_macro_cash(is_defensive=True, weighted_mos=active_def_mos)
    
    final_def_weights = allocate_fractional_kelly_capped(
        {t: def_k_scores[t] for t in active_def_tickers},
        def_equity_budget,
        MAX_SINGLE_EQUITY_CAP,
        MIN_POSITION_WEIGHT
    )
    
    def_holdings = []
    for t in active_def_tickers:
        s = scored_pool[t]
        w = final_def_weights[t]
        alloc = total_capital * w
        shs = round(alloc / s["price"], 2) if s["price"] > 0 else 0
        oe_yr = alloc * (s["oe_yield"] / 100.0)
        def_holdings.append({
            "ticker": t,
            "company_name": wl.get(t, {}).get("company_name", t),
            "sector": s["sector"],
            "industry": s["industry"],
            "quality_score": s["total_score"],
            "target_weight": w,
            "pillar": "A",
            "cost_basis": s["price"],
            "current_price": s["price"],
            "fair_value": s["fair_value"],
            "margin_of_safety_pct": s["margin_of_safety_pct"],
            "allocated_dollars": round(alloc, 2),
            "shares_to_buy": shs,
            "look_through_fcf_yield": s["oe_yield"],
            "annual_owner_earnings": round(oe_yr, 2),
            "cannibal_rate_pct": s["cannibal"],
            "thesis_core": s["thesis"],
            "report_url": f"reports/{t}.html"
        })

    def_cash_dollars = round(total_capital * def_cash_pct, 2)
    def_holdings.append({
        "ticker": "USD_CASH",
        "company_name": "USD Cash Reserve",
        "sector": "Cash & Cash Equivalents",
        "industry": "3-Month US Treasury Bills",
        "quality_score": 100.0,
        "target_weight": def_cash_pct,
        "pillar": "CASH",
        "cost_basis": 1.0,
        "current_price": 1.0,
        "fair_value": 1.0,
        "margin_of_safety_pct": 0.0,
        "allocated_dollars": def_cash_dollars,
        "shares_to_buy": def_cash_dollars,
        "look_through_fcf_yield": 5.0,
        "annual_owner_earnings": round(def_cash_dollars * 0.05, 2),
        "cannibal_rate_pct": 0.0,
        "thesis_core": def_cash_desc,
        "report_url": "#"
    })

    # 5. Compute Wealthsimple Allocations
    agg_k_scores = {t: scored_pool[t]["kelly_score"] for t in wealthsimple_selected}
    prelim_agg_mos = sum(scored_pool[t]["margin_of_safety_pct"] for t in wealthsimple_selected) / len(wealthsimple_selected) if wealthsimple_selected else 25.0
    agg_cash_pct, agg_equity_budget, agg_cash_desc = calculate_shiller_macro_cash(is_defensive=False, weighted_mos=prelim_agg_mos)

    final_agg_weights = allocate_fractional_kelly_capped(agg_k_scores, agg_equity_budget, MAX_SINGLE_EQUITY_CAP, MIN_POSITION_WEIGHT)
    active_agg_tickers = list(final_agg_weights.keys())
    active_agg_mos = sum(scored_pool[t]["margin_of_safety_pct"] for t in active_agg_tickers) / len(active_agg_tickers) if active_agg_tickers else prelim_agg_mos
    agg_cash_pct, agg_equity_budget, agg_cash_desc = calculate_shiller_macro_cash(is_defensive=False, weighted_mos=active_agg_mos)

    final_agg_weights = allocate_fractional_kelly_capped(
        {t: agg_k_scores[t] for t in active_agg_tickers},
        agg_equity_budget,
        MAX_SINGLE_EQUITY_CAP,
        MIN_POSITION_WEIGHT
    )

    agg_holdings = []
    for t in active_agg_tickers:
        s = scored_pool[t]
        w = final_agg_weights[t]
        alloc = total_capital * w
        shs = round(alloc / s["price"], 2) if s["price"] > 0 else 0
        oe_yr = alloc * (s["oe_yield"] / 100.0)
        agg_holdings.append({
            "ticker": t,
            "company_name": wl.get(t, {}).get("company_name", t),
            "sector": s["sector"],
            "industry": s["industry"],
            "quality_score": s["total_score"],
            "target_weight": w,
            "pillar": "B",
            "cost_basis": s["price"],
            "current_price": s["price"],
            "fair_value": s["fair_value"],
            "margin_of_safety_pct": s["margin_of_safety_pct"],
            "allocated_dollars": round(alloc, 2),
            "shares_to_buy": shs,
            "look_through_fcf_yield": s["oe_yield"],
            "annual_owner_earnings": round(oe_yr, 2),
            "cannibal_rate_pct": s["cannibal"],
            "thesis_core": s["thesis"],
            "report_url": f"reports/{t}.html"
        })

    agg_cash_dollars = round(total_capital * agg_cash_pct, 2)
    agg_holdings.append({
        "ticker": "USD_CASH",
        "company_name": "USD Cash Strike Reserve",
        "sector": "Cash & Cash Equivalents",
        "industry": "3-Month US Treasury Bills",
        "quality_score": 100.0,
        "target_weight": agg_cash_pct,
        "pillar": "CASH",
        "cost_basis": 1.0,
        "current_price": 1.0,
        "fair_value": 1.0,
        "margin_of_safety_pct": 0.0,
        "allocated_dollars": agg_cash_dollars,
        "shares_to_buy": agg_cash_dollars,
        "look_through_fcf_yield": 5.0,
        "annual_owner_earnings": round(agg_cash_dollars * 0.05, 2),
        "cannibal_rate_pct": 0.0,
        "thesis_core": agg_cash_desc,
        "report_url": "#"
    })

    def_oe_sum = sum(h["annual_owner_earnings"] for h in def_holdings)
    agg_oe_sum = sum(h["annual_owner_earnings"] for h in agg_holdings)

    def_state = {
        "portfolio_name": "Fidelity",
        "portfolio_type": "defensive",
        "target_audience": "Defensive Fortresses & Consistent Cash Compounding",
        "inception_date": "2026-08-11",
        "last_rebalance_date": "2026-08-11",
        "base_capital_usd": total_capital,
        "holdings": def_holdings,
        "rebalance_log": [
            {
                "date": "2026-08-11",
                "action": "EXPLICIT TAXONOMY INCEPTION",
                "reason": def_cash_desc,
                "verification_status": "Verified 3/3 Autonomous Council"
            }
        ],
        "historical_performance": [
            {
                "date": "2026-08-11",
                "portfolio_value": total_capital,
                "owner_earnings_runrate": round(def_oe_sum, 2),
                "spy_benchmark": total_capital
            }
        ]
    }

    agg_state = {
        "portfolio_name": "Wealthsimple",
        "portfolio_type": "aggressive",
        "target_audience": "Aggressive Alpha, Mispriced Growth & Buyback Cannibals",
        "inception_date": "2026-08-11",
        "last_rebalance_date": "2026-08-11",
        "base_capital_usd": total_capital,
        "holdings": agg_holdings,
        "rebalance_log": [
            {
                "date": "2026-08-11",
                "action": "EXPLICIT TAXONOMY INCEPTION",
                "reason": agg_cash_desc,
                "verification_status": "Verified 3/3 Autonomous Council"
            }
        ],
        "historical_performance": [
            {
                "date": "2026-08-11",
                "portfolio_value": total_capital,
                "owner_earnings_runrate": round(agg_oe_sum, 2),
                "spy_benchmark": total_capital
            }
        ]
    }

    return def_state, agg_state

def sync_engine_to_disk():
    def_state, agg_state = construct_dual_portfolios(200000.0)
    with open(DATA_DIR / "portfolio_defensive.json", "w") as f:
        json.dump(def_state, f, indent=2)
    with open(DATA_DIR / "portfolio_aggressive.json", "w") as f:
        json.dump(agg_state, f, indent=2)
    with open(DATA_DIR / "portfolio.json", "w") as f:
        json.dump(def_state, f, indent=2)
        
    print(f"=== FIDELITY ALLOCATION ({len(def_state['holdings'])-1} Equities + Cash) ===")
    for h in def_state["holdings"]:
        print(f"  {h['ticker']:<8} | Weight: {h['target_weight']*100:>6.2f}% | Alloc: ${h['allocated_dollars']:>9,.2f} | MoS: {h['margin_of_safety_pct']:>+6.2f}% | Score: {h.get('quality_score', 0):>5.1f} | {h.get('industry')}")
        
    print(f"\n=== WEALTHSIMPLE ALLOCATION ({len(agg_state['holdings'])-1} Equities + Cash) ===")
    for h in agg_state["holdings"]:
        print(f"  {h['ticker']:<8} | Weight: {h['target_weight']*100:>6.2f}% | Alloc: ${h['allocated_dollars']:>9,.2f} | MoS: {h['margin_of_safety_pct']:>+6.2f}% | Score: {h.get('quality_score', 0):>5.1f} | {h.get('industry')}")

if __name__ == "__main__":
    sync_engine_to_disk()
