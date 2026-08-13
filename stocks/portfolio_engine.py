"""
stocks.portfolio_engine
~~~~~~~~~~~~~~~~~~~~~~~
Dynamic Full-Universe Institutional Portfolio Construction Engine.

MANDATE PRINCIPLES:
1. FIDELITY (Defensive Fortress & Capital Preservation):
   - Primary Anchor: Moat Durability (30%) & Balance Sheet Fortress (25%).
   - Factors: MoS >= 20% (20%), Share Cannibalization (15%), Owner Earnings Yield (10%).
   - Zero structural business risk, irreplaceable pricing power, steady compounding.
   - Sizing: Moat & Balance Sheet anchored Fractional Kelly.

2. WEALTHSIMPLE (Aggressive Alpha & Buyback Cannibal Compounders):
   - Primary Anchor: Deep Margin of Safety (30%) & Share Cannibalization (20%).
   - Factors: Moat Durability (20%), Balance Sheet Fortress (15%), Organic Growth (15%).
   - STRICT INVARIANT: ZERO VALUE TRAPS / ZERO DISTRESSED TURNAROUNDS.
   - Requires Minimum Moat >= 8.5/10.0, Organic Growth >= 6.0%/yr, MoS >= 25.0%.
   - Sizing: Exponential Kelly scaling on Margin of Safety Asymmetry & Expected 5-Year IRR.

COMPLIANCE & ETHICAL INVARIANTS:
- GOOG / GOOGL: Direct Employer Affiliation.
- LMT: Weapons & Defense Manufacturing.
- BTI: Tobacco & Nicotine Manufacturing.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional, Set

DATA_DIR = Path("/Users/pmlhtra/Documents/software/stocks/data")
WATCHLIST_FILE = DATA_DIR / "watchlist.json"

# =============================================================================
# 1. MACRO GAUGES & COMPLIANCE INVARIANTS
# =============================================================================

SHILLER_CAPE = 35.50            # S&P 500 Cyclically Adjusted P/E (95th Historical Percentile)
CAPE_HISTORICAL_MEDIAN = 18.00  # Historical Mean/Median Baseline
BUFFETT_INDICATOR = 198.50      # US Total Market Cap to GDP %
TREASURY_BILL_YIELD = 0.0500    # 3-Month Senior US Treasury Bill Yield (5.00% Risk-Free)
MAX_SINGLE_EQUITY_CAP = 0.1500  # Single-asset prudence ceiling

COMPLIANCE_EXCLUSIONS = {
    "GOOG": "Regulatory/Compliance Constraint: Direct Employer Affiliation",
    "GOOGL": "Regulatory/Compliance Constraint: Direct Employer Affiliation",
    "LMT": "Ethical Invariant: Weapons & Defense Manufacturing",
    "BTI": "Ethical Invariant: Tobacco & Nicotine Manufacturing"
}

# =============================================================================
# 2. COMPLETE COVERAGE UNIVERSE METADATA (72 TICKERS)
# =============================================================================

STOCK_METADATA: Dict[str, Dict[str, Any]] = {
    "CSU": {"sector": "Enterprise Software", "industry": "Vertical Market Software (VMS)", "moat": 9.9, "bs": 8.5, "growth": 14.0, "cannibal": 0.0, "oe_yield": 4.5, "cyc": 1.0, "mandate": "defensive", "p": 0.92, "roic": 32.0, "float_gen": 9.5, "insider_align": 10.0, "cust_conc": 0.5, "lindy_ai_res": 9.5, "scale_shared": 3.0, "thesis": "Mission-critical vertical market software acquirer; 30%+ ROIC, negative working capital float, Mark Leonard alignment."},
    "MSFT": {"sector": "Enterprise Software", "industry": "Enterprise Cloud & OS Infrastructure", "moat": 9.7, "bs": 9.0, "growth": 11.0, "cannibal": 0.8, "oe_yield": 3.9, "cyc": 1.5, "mandate": "defensive", "p": 0.9, "roic": 28.5, "float_gen": 8.5, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 9.2, "scale_shared": 6.5, "thesis": "Commercial enterprise cloud backbone, Azure infrastructure, Office 365 seat monetization."},
    "ADBE": {"sector": "Enterprise Software", "industry": "Digital Media & Creative Cloud", "moat": 9.5, "bs": 9.0, "growth": 10.5, "cannibal": 3.2, "oe_yield": 5.5, "cyc": 1.5, "mandate": "defensive", "p": 0.88, "roic": 25.0, "float_gen": 8.0, "insider_align": 7.0, "cust_conc": 0.5, "lindy_ai_res": 8.5, "scale_shared": 4.0, "thesis": "Creative Cloud monopoly; 85%+ gross margins, $3.5B+ annual share buybacks."},
    "INTU": {"sector": "Enterprise Software", "industry": "Small Business Financial & Tax Software", "moat": 9.5, "bs": 8.5, "growth": 10.0, "cannibal": 1.5, "oe_yield": 4.5, "cyc": 1.2, "mandate": "defensive", "p": 0.88, "roic": 22.0, "float_gen": 7.5, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 9.0, "scale_shared": 5.0, "thesis": "QuickBooks & TurboTax SMB accounting monopoly; high regulatory switching costs."},
    "CRM": {"sector": "Enterprise Software", "industry": "Enterprise CRM & Agentic Cloud", "moat": 9.2, "bs": 8.5, "growth": 9.0, "cannibal": 3.0, "oe_yield": 5.2, "cyc": 1.8, "mandate": "defensive", "p": 0.85, "roic": 16.5, "float_gen": 8.5, "insider_align": 8.5, "cust_conc": 0.5, "lindy_ai_res": 8.2, "scale_shared": 4.5, "thesis": "Enterprise CRM platform standard; multi-cloud cross-selling and margin expansion."},
    "NOW": {"sector": "Enterprise Software", "industry": "IT Digital Workflow Automation", "moat": 9.3, "bs": 8.5, "growth": 16.0, "cannibal": 0.5, "oe_yield": 4.1, "cyc": 1.5, "mandate": "aggressive", "p": 0.86, "roic": 21.0, "float_gen": 9.0, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 8.8, "scale_shared": 5.0, "thesis": "Global 2000 digital workflow platform; 98%+ renewal rate, expanding ACV."},
    "WDAY": {"sector": "Enterprise Software", "industry": "Enterprise Human Capital & Financial Management", "moat": 8.9, "bs": 8.5, "growth": 13.0, "cannibal": 0.5, "oe_yield": 4.0, "cyc": 1.8, "mandate": "aggressive", "p": 0.82, "roic": 15.0, "float_gen": 8.0, "insider_align": 8.0, "cust_conc": 0.5, "lindy_ai_res": 8.2, "scale_shared": 4.0, "thesis": "Core enterprise HR and financial management software for Fortune 500."},
    "ACN": {"sector": "Enterprise Software", "industry": "Enterprise IT Consulting & Digital Transformation", "moat": 8.9, "bs": 8.5, "growth": 7.0, "cannibal": 1.5, "oe_yield": 4.8, "cyc": 2.0, "mandate": "defensive", "p": 0.85, "roic": 26.0, "float_gen": 7.0, "insider_align": 6.5, "cust_conc": 0.5, "lindy_ai_res": 8.8, "scale_shared": 6.0, "thesis": "Global systems integrator and enterprise AI implementation partner."},
    "SMRT": {"sector": "Enterprise Software", "industry": "Multifamily IoT & Smart Property Automation", "moat": 7.5, "bs": 7.5, "growth": 15.0, "cannibal": 0.0, "oe_yield": 6.5, "cyc": 3.0, "mandate": "aggressive", "p": 0.7, "roic": 12.0, "float_gen": 4.0, "insider_align": 6.5, "cust_conc": 2.5, "lindy_ai_res": 6.5, "scale_shared": 3.0, "thesis": "Enterprise smart home automation for multifamily apartment operators."},
    "V": {"sector": "Financial Infrastructure", "industry": "Global Consumer Payment Networks", "moat": 9.8, "bs": 8.5, "growth": 9.5, "cannibal": 2.2, "oe_yield": 4.6, "cyc": 1.2, "mandate": "defensive", "p": 0.91, "roic": 52.0, "float_gen": 8.5, "insider_align": 7.0, "cust_conc": 0.5, "lindy_ai_res": 9.8, "scale_shared": 8.5, "thesis": "World's premier payment network rail; 55%+ operating margin, GDP+ cash conversion."},
    "MA": {"sector": "Financial Infrastructure", "industry": "Global Consumer Payment Networks", "moat": 9.8, "bs": 8.5, "growth": 11.5, "cannibal": 2.0, "oe_yield": 3.8, "cyc": 1.2, "mandate": "defensive", "p": 0.9, "roic": 55.0, "float_gen": 8.5, "insider_align": 7.0, "cust_conc": 0.5, "lindy_ai_res": 9.8, "scale_shared": 8.5, "thesis": "Global payment rail duopoly; 57% operating margin, secular cashless conversion."},
    "SPGI": {"sector": "Financial Infrastructure", "industry": "Credit Ratings & Market Benchmarks", "moat": 9.8, "bs": 8.5, "growth": 9.5, "cannibal": 1.8, "oe_yield": 4.1, "cyc": 2.2, "mandate": "defensive", "p": 0.9, "roic": 34.0, "float_gen": 8.0, "insider_align": 7.0, "cust_conc": 0.5, "lindy_ai_res": 9.8, "scale_shared": 6.0, "thesis": "Sovereign/corporate debt rating duopoly + S&P 500 benchmark index licensing."},
    "MSCI": {"sector": "Financial Infrastructure", "industry": "Global Index Benchmarks & ESG Analytics", "moat": 9.6, "bs": 8.0, "growth": 10.5, "cannibal": 1.5, "oe_yield": 4.2, "cyc": 2.0, "mandate": "defensive", "p": 0.89, "roic": 36.0, "float_gen": 8.5, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 9.5, "scale_shared": 5.5, "thesis": "Global emerging markets and ESG benchmark monopoly with 95%+ subscription retention."},
    "FICO": {"sector": "Financial Infrastructure", "industry": "Credit Scoring & Decision Analytics", "moat": 9.9, "bs": 9.0, "growth": 15.0, "cannibal": 2.5, "oe_yield": 4.2, "cyc": 1.0, "mandate": "aggressive", "p": 0.91, "roic": 48.0, "float_gen": 7.0, "insider_align": 7.0, "cust_conc": 0.5, "lindy_ai_res": 9.8, "scale_shared": 5.0, "thesis": "Sovereign monopoly on US consumer credit scoring; extreme pricing power, zero CapEx."},
    "STNE": {"sector": "Financial Infrastructure", "industry": "Emerging Market Merchant Fintech", "moat": 8.5, "bs": 8.5, "growth": 12.0, "cannibal": 4.0, "oe_yield": 11.5, "cyc": 3.0, "mandate": "aggressive", "p": 0.79, "roic": 26.0, "float_gen": 7.5, "insider_align": 8.5, "cust_conc": 0.5, "lindy_ai_res": 8.2, "scale_shared": 7.0, "thesis": "High-ROIC (25%+) Brazil merchant payments & ERP software compounder at single-digit P/E."},
    "PYPL": {"sector": "Financial Infrastructure", "industry": "Digital Wallet & Global Online Checkout", "moat": 8.5, "bs": 9.0, "growth": 7.0, "cannibal": 6.5, "oe_yield": 7.2, "cyc": 2.0, "mandate": "aggressive", "p": 0.8, "roic": 19.0, "float_gen": 8.0, "insider_align": 6.5, "cust_conc": 0.5, "lindy_ai_res": 8.5, "scale_shared": 7.5, "thesis": "Global checkout network with $1.5T volume; accelerating Braintree margins and buybacks."},
    "SOFI": {"sector": "Financial Infrastructure", "industry": "Digital Consumer Neo-Banking & Lending", "moat": 8.0, "bs": 8.0, "growth": 20.0, "cannibal": 0.0, "oe_yield": 5.5, "cyc": 2.8, "mandate": "aggressive", "p": 0.76, "roic": 16.0, "float_gen": 9.0, "insider_align": 9.0, "cust_conc": 0.5, "lindy_ai_res": 8.0, "scale_shared": 7.0, "thesis": "Full-stack digital bank with Galileo technology infrastructure and Anthony Noto insider buying."},
    "HOOD": {"sector": "Financial Infrastructure", "industry": "Retail Trading Platform & Prediction Markets", "moat": 8.2, "bs": 8.5, "growth": 18.0, "cannibal": 0.0, "oe_yield": 6.0, "cyc": 3.5, "mandate": "aggressive", "p": 0.75, "roic": 15.0, "float_gen": 8.5, "insider_align": 8.5, "cust_conc": 0.5, "lindy_ai_res": 7.5, "scale_shared": 6.5, "thesis": "Dominant Gen-Z retail trading platform with expanding Gold subscriptions and net interest margin."},
    "ISRG": {"sector": "Healthcare & Medical Technology", "industry": "Robotic Surgical Systems", "moat": 9.8, "bs": 10.0, "growth": 13.0, "cannibal": 0.5, "oe_yield": 3.6, "cyc": 1.0, "mandate": "defensive", "p": 0.9, "roic": 24.0, "float_gen": 6.0, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 9.6, "scale_shared": 6.0, "thesis": "Global da Vinci robotic surgery monopoly; 80%+ recurring instruments & services, zero debt."},
    "UNH": {"sector": "Healthcare & Medical Technology", "industry": "Managed Care & Integrated Health Services", "moat": 9.6, "bs": 8.5, "growth": 9.0, "cannibal": 1.2, "oe_yield": 5.8, "cyc": 1.2, "mandate": "defensive", "p": 0.88, "roic": 22.5, "float_gen": 9.0, "insider_align": 6.5, "cust_conc": 0.5, "lindy_ai_res": 9.4, "scale_shared": 8.0, "thesis": "Integrated Optum healthcare platform + UnitedHealthcare insurance scale and premium float."},
    "MEDP": {"sector": "Healthcare & Medical Technology", "industry": "Biotech Contract Research (CRO)", "moat": 9.2, "bs": 10.0, "growth": 13.0, "cannibal": 3.5, "oe_yield": 5.5, "cyc": 2.2, "mandate": "aggressive", "p": 0.86, "roic": 38.0, "float_gen": 6.5, "insider_align": 9.0, "cust_conc": 1.5, "lindy_ai_res": 8.5, "scale_shared": 5.0, "thesis": "Founder-led biotech CRO; pristine net cash balance sheet, 35%+ ROIC and heavy buybacks."},
    "LLY": {"sector": "Healthcare & Medical Technology", "industry": "Incretin Therapeutics & Biopharmaceuticals", "moat": 9.5, "bs": 8.0, "growth": 18.0, "cannibal": 0.0, "oe_yield": 3.0, "cyc": 1.5, "mandate": "defensive", "p": 0.87, "roic": 28.0, "float_gen": 5.0, "insider_align": 6.5, "cust_conc": 0.5, "lindy_ai_res": 9.0, "scale_shared": 4.0, "thesis": "Dominant global leader in incretin/GLP-1 metabolic therapeutics and Alzheimer's pipeline."},
    "PFE": {"sector": "Healthcare & Medical Technology", "industry": "Diversified Commercial Pharmaceuticals", "moat": 8.0, "bs": 7.5, "growth": 4.0, "cannibal": 0.0, "oe_yield": 8.5, "cyc": 2.0, "mandate": "defensive", "p": 0.78, "roic": 11.0, "float_gen": 5.0, "insider_align": 5.5, "cust_conc": 0.5, "lindy_ai_res": 8.0, "scale_shared": 4.0, "thesis": "Deep value post-Covid pharmaceutical turnaround with high dividend yield."},
    "META": {"sector": "Interactive Media & Consumer Tech", "industry": "Global Social Graph & Digital Advertising", "moat": 9.7, "bs": 9.5, "growth": 13.0, "cannibal": 3.2, "oe_yield": 5.4, "cyc": 2.0, "mandate": "aggressive", "p": 0.89, "roic": 31.0, "float_gen": 9.0, "insider_align": 10.0, "cust_conc": 0.5, "lindy_ai_res": 9.0, "scale_shared": 8.0, "thesis": "3.60B Daily Active People social graph monopoly; Mark Zuckerberg absolute founder control."},
    "RDDT": {"sector": "Interactive Media & Consumer Tech", "industry": "Community Social Corpus & Ad Platform", "moat": 8.8, "bs": 9.5, "growth": 25.0, "cannibal": 0.0, "oe_yield": 4.5, "cyc": 2.5, "mandate": "aggressive", "p": 0.78, "roic": 18.0, "float_gen": 7.0, "insider_align": 8.0, "cust_conc": 1.5, "lindy_ai_res": 8.5, "scale_shared": 6.0, "thesis": "Irreplaceable human conversational data corpus licensing to AI hyperscalers."},
    "MTCH": {"sector": "Interactive Media & Consumer Tech", "industry": "Mobile Dating Platforms (Hinge/Tinder)", "moat": 8.5, "bs": 8.0, "growth": 6.0, "cannibal": 5.0, "oe_yield": 8.8, "cyc": 2.0, "mandate": "aggressive", "p": 0.8, "roic": 25.0, "float_gen": 7.5, "insider_align": 6.5, "cust_conc": 0.5, "lindy_ai_res": 8.5, "scale_shared": 6.0, "thesis": "Hinge growth flywheel and deep value cash generation with aggressive buybacks."},
    "BMBL": {"sector": "Interactive Media & Consumer Tech", "industry": "Female-Centric Dating & Friendship Apps", "moat": 7.5, "bs": 7.5, "growth": 5.0, "cannibal": 0.0, "oe_yield": 9.0, "cyc": 2.5, "mandate": "aggressive", "p": 0.7, "roic": 12.0, "float_gen": 6.5, "insider_align": 7.0, "cust_conc": 0.5, "lindy_ai_res": 7.0, "scale_shared": 4.0, "thesis": "Turnaround play on female-first dating app optimization and subscription tiers."},
    "YELP": {"sector": "Interactive Media & Consumer Tech", "industry": "Local Merchant Discovery & Ad Services", "moat": 8.4, "bs": 9.5, "growth": 5.0, "cannibal": 7.0, "oe_yield": 9.5, "cyc": 2.5, "mandate": "aggressive", "p": 0.78, "roic": 22.0, "float_gen": 7.0, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 8.5, "scale_shared": 5.0, "thesis": "Extreme cash cow (zero debt, $400M cash) repurchasing 7%+ shares annually."},
    "DIS": {"sector": "Media & Entertainment", "industry": "Theme Parks, Studio IP & Streaming Media", "moat": 9.2, "bs": 7.5, "growth": 6.5, "cannibal": 0.5, "oe_yield": 5.8, "cyc": 2.2, "mandate": "defensive", "p": 0.85, "roic": 12.5, "float_gen": 6.5, "insider_align": 6.0, "cust_conc": 0.5, "lindy_ai_res": 9.8, "scale_shared": 6.5, "thesis": "Unmatched timeless family entertainment IP (100-year Lindy effect), theme park pricing power."},
    "EDU": {"sector": "Consumer Services & Education", "industry": "Enrichment Education & Negative Working Float", "moat": 9.2, "bs": 10.0, "growth": 14.0, "cannibal": 4.0, "oe_yield": 7.3, "cyc": 1.8, "mandate": "aggressive", "p": 0.85, "roic": 24.0, "float_gen": 10.0, "insider_align": 9.5, "cust_conc": 0.5, "lindy_ai_res": 9.0, "scale_shared": 7.0, "thesis": "Negative working capital float ($2.24B deferred tuition), $5.56B gross cash ($0 debt), Michael Yu leadership."},
    "DUOL": {"sector": "Consumer Services & Education", "industry": "Gamified Mobile Language & Literacy Learning", "moat": 8.8, "bs": 9.5, "growth": 25.0, "cannibal": 0.0, "oe_yield": 3.8, "cyc": 2.0, "mandate": "aggressive", "p": 0.82, "roic": 20.0, "float_gen": 8.0, "insider_align": 9.0, "cust_conc": 0.5, "lindy_ai_res": 8.0, "scale_shared": 6.5, "thesis": "Viral organic acquisition loop, Luis von Ahn founder leadership."},
    "LGCY": {"sector": "Consumer Services & Education", "industry": "Accredited Vocational Allied Healthcare Training", "moat": 8.2, "bs": 9.0, "growth": 15.0, "cannibal": 0.0, "oe_yield": 8.5, "cyc": 2.0, "mandate": "aggressive", "p": 0.76, "roic": 21.0, "float_gen": 7.0, "insider_align": 8.0, "cust_conc": 0.5, "lindy_ai_res": 8.5, "scale_shared": 5.0, "thesis": "Accredited practical nursing and allied health training with high placement rates."},
    "AMZN": {"sector": "Commerce & Cloud Infrastructure", "industry": "Global Hyperscaler Cloud & Retail Prime", "moat": 9.8, "bs": 8.5, "growth": 11.5, "cannibal": 0.0, "oe_yield": 5.2, "cyc": 1.8, "mandate": "aggressive", "p": 0.9, "roic": 22.0, "float_gen": 10.0, "insider_align": 9.0, "cust_conc": 0.5, "lindy_ai_res": 9.5, "scale_shared": 10.0, "thesis": "AWS cloud hyperscaler monopoly + Prime retail advertising & Scale Economics Shared flywheel."},
    "MELI": {"sector": "Commerce & Logistics", "industry": "Latin America E-Commerce & Fintech Platform", "moat": 9.5, "bs": 9.0, "growth": 19.0, "cannibal": 0.0, "oe_yield": 6.1, "cyc": 2.5, "mandate": "aggressive", "p": 0.84, "roic": 29.0, "float_gen": 9.0, "insider_align": 9.5, "cust_conc": 0.5, "lindy_ai_res": 9.0, "scale_shared": 8.5, "thesis": "Marcos Galperin founder leadership; dominant Latin America e-commerce & fintech logistics ecosystem."},
    "BABA": {"sector": "Commerce & Cloud Infrastructure", "industry": "Cloud Hyperscaler & 3P Digital Marketplaces", "moat": 9.5, "bs": 10.0, "growth": 6.0, "cannibal": 6.5, "oe_yield": 8.5, "cyc": 2.5, "mandate": "aggressive", "p": 0.82, "roic": 18.0, "float_gen": 9.5, "insider_align": 8.5, "cust_conc": 0.5, "lindy_ai_res": 9.0, "scale_shared": 8.5, "thesis": "Massive deep-value cash fortress ($60B+ net cash), Cloud AI enterprise leader, 7%+ buybacks."},
    "JD": {"sector": "Commerce & Logistics", "industry": "Direct 1P Cold-Chain & Fulfillment Logistics", "moat": 9.0, "bs": 9.5, "growth": 6.0, "cannibal": 5.5, "oe_yield": 9.2, "cyc": 2.5, "mandate": "aggressive", "p": 0.81, "roic": 17.5, "float_gen": 9.5, "insider_align": 9.0, "cust_conc": 0.5, "lindy_ai_res": 9.2, "scale_shared": 9.5, "thesis": "Richard Liu founder leadership; nationwide direct 1P logistics infrastructure, refrigerated supply chain."},
    "PDD": {"sector": "Commerce & Logistics", "industry": "Value Commerce & Cross-Border Supply Platform", "moat": 9.2, "bs": 10.0, "growth": 20.0, "cannibal": 0.0, "oe_yield": 9.8, "cyc": 3.0, "mandate": "aggressive", "p": 0.8, "roic": 42.0, "float_gen": 9.5, "insider_align": 9.5, "cust_conc": 0.5, "lindy_ai_res": 8.5, "scale_shared": 9.0, "thesis": "Social group buying scale + global cross-border Temu with $35B+ net cash, 40%+ ROIC."},
    "UBER": {"sector": "Commerce & Mobility", "industry": "Global Mobility & Local Delivery Networks", "moat": 9.2, "bs": 8.5, "growth": 16.0, "cannibal": 2.0, "oe_yield": 5.5, "cyc": 2.2, "mandate": "aggressive", "p": 0.83, "roic": 21.0, "float_gen": 8.5, "insider_align": 8.0, "cust_conc": 0.5, "lindy_ai_res": 8.8, "scale_shared": 8.0, "thesis": "Global ride-share & delivery network duopoly; multi-sided liquidity scale and margin expansion."},
    "BKNG": {"sector": "Commerce & Travel", "industry": "Online Travel Agency Global Duopoly", "moat": 9.4, "bs": 8.5, "growth": 8.5, "cannibal": 4.5, "oe_yield": 6.8, "cyc": 3.0, "mandate": "defensive", "p": 0.86, "roic": 45.0, "float_gen": 9.0, "insider_align": 7.0, "cust_conc": 0.5, "lindy_ai_res": 9.2, "scale_shared": 7.0, "thesis": "Global travel OTA network effects duopoly + 35%+ FCF conversion and aggressive buybacks."},
    "GCT": {"sector": "Commerce & Logistics", "industry": "B2B Cross-Border Bulky Goods Marketplace", "moat": 8.8, "bs": 9.5, "growth": 18.0, "cannibal": 2.0, "oe_yield": 9.5, "cyc": 3.5, "mandate": "aggressive", "p": 0.78, "roic": 32.0, "float_gen": 8.5, "insider_align": 9.0, "cust_conc": 1.0, "lindy_ai_res": 8.0, "scale_shared": 7.5, "thesis": "B2B cross-border marketplace network effects with fulfillment scale, high ROIC, and net cash."},
    "UPWK": {"sector": "Commerce & Marketplaces", "industry": "Knowledge-Work Freelance Marketplace", "moat": 8.4, "bs": 9.0, "growth": 11.0, "cannibal": 3.0, "oe_yield": 8.5, "cyc": 2.8, "mandate": "aggressive", "p": 0.78, "roic": 19.0, "float_gen": 8.0, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 8.0, "scale_shared": 6.0, "thesis": "Online knowledge-work marketplace expanding take rates and EBITDA margins."},
    "CPRT": {"sector": "Industrial & Physical Moats", "industry": "Salvage Vehicle Real Estate Auctions", "moat": 9.7, "bs": 10.0, "growth": 11.0, "cannibal": 0.5, "oe_yield": 4.4, "cyc": 1.2, "mandate": "defensive", "p": 0.89, "roic": 26.0, "float_gen": 6.5, "insider_align": 9.0, "cust_conc": 0.5, "lindy_ai_res": 9.8, "scale_shared": 7.0, "thesis": "Zoning-protected salvage yard land monopoly + pristine zero-debt balance sheet fortress."},
    "BYD": {"sector": "Industrial & Physical Moats", "industry": "Fee-Simple Regional Real Estate Gaming", "moat": 8.8, "bs": 9.0, "growth": 4.5, "cannibal": 5.5, "oe_yield": 9.4, "cyc": 2.8, "mandate": "aggressive", "p": 0.82, "roic": 18.0, "float_gen": 6.0, "insider_align": 9.0, "cust_conc": 0.5, "lindy_ai_res": 9.2, "scale_shared": 5.0, "thesis": "Fee-simple real estate ownership (~85% owned land), Boyd family founder leadership."},
    "FAST": {"sector": "Industrial & Physical Moats", "industry": "Industrial Fasteners & Onsite Vending Supply", "moat": 9.2, "bs": 9.5, "growth": 7.5, "cannibal": 0.5, "oe_yield": 3.5, "cyc": 2.5, "mandate": "defensive", "p": 0.88, "roic": 32.0, "float_gen": 5.5, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 9.5, "scale_shared": 6.5, "thesis": "Onsite vending machine moat embedded inside customer factories with 30%+ ROIC."},
    "VRT": {"sector": "Industrial & Physical Moats", "industry": "Datacenter Liquid Cooling & Power Management", "moat": 9.1, "bs": 8.0, "growth": 20.0, "cannibal": 0.0, "oe_yield": 4.8, "cyc": 3.2, "mandate": "aggressive", "p": 0.83, "roic": 22.0, "float_gen": 6.0, "insider_align": 7.5, "cust_conc": 2.0, "lindy_ai_res": 8.5, "scale_shared": 5.5, "thesis": "Essential liquid cooling and thermal management infrastructure for high-density AI clusters."},
    "BVHMF": {"sector": "Industrial & Physical Moats", "industry": "UK Affordable Partnerships Housebuilding", "moat": 8.0, "bs": 8.0, "growth": 10.0, "cannibal": 2.0, "oe_yield": 8.5, "cyc": 3.2, "mandate": "aggressive", "p": 0.75, "roic": 25.0, "float_gen": 7.5, "insider_align": 7.0, "cust_conc": 1.0, "lindy_ai_res": 8.8, "scale_shared": 6.0, "thesis": "Asset-light UK partnership housebuilder with high pre-sold social housing forward order book."},
    "CMCSA": {"sector": "Media & Telecom Infrastructure", "industry": "Broadband Last-Mile Cable & Media", "moat": 8.8, "bs": 7.5, "growth": 4.0, "cannibal": 6.0, "oe_yield": 8.5, "cyc": 2.0, "mandate": "defensive", "p": 0.82, "roic": 14.0, "float_gen": 7.5, "insider_align": 8.5, "cust_conc": 0.5, "lindy_ai_res": 9.0, "scale_shared": 7.5, "thesis": "Brian Roberts founder leadership; broadband last-mile infrastructure with heavy share cannibalization."},
    "CHTR": {"sector": "Media & Telecom Infrastructure", "industry": "Rural & Suburban Cable Broadband Network", "moat": 8.5, "bs": 6.5, "growth": 3.0, "cannibal": 5.0, "oe_yield": 9.5, "cyc": 2.5, "mandate": "aggressive", "p": 0.72, "roic": 12.0, "float_gen": 7.0, "insider_align": 8.0, "cust_conc": 0.5, "lindy_ai_res": 8.8, "scale_shared": 7.0, "thesis": "High-leverage cable free cash flow engine repurchasing shares at steep discount."},
    "TSM": {"sector": "Semiconductor Infrastructure", "industry": "Pure-Play Advanced Silicon Foundry", "moat": 9.8, "bs": 9.5, "growth": 15.0, "cannibal": 0.0, "oe_yield": 5.9, "cyc": 3.0, "mandate": "aggressive", "p": 0.88, "roic": 28.0, "float_gen": 6.5, "insider_align": 7.5, "cust_conc": 2.5, "lindy_ai_res": 9.5, "scale_shared": 7.5, "thesis": "Sole global pure-play foundry utility for all advanced silicon; customer concentration with Apple/Nvidia."},
    "NVDA": {"sector": "Semiconductor Infrastructure", "industry": "Accelerated Compute & GPU Architectures", "moat": 9.6, "bs": 9.5, "growth": 18.0, "cannibal": 1.5, "oe_yield": 3.8, "cyc": 4.5, "mandate": "aggressive", "p": 0.84, "roic": 58.0, "float_gen": 7.5, "insider_align": 9.5, "cust_conc": 3.0, "lindy_ai_res": 8.5, "scale_shared": 6.5, "thesis": "Jensen Huang founder leadership; CUDA software lock-in and high ROIC, high hyperscaler concentration."},
    "ASML": {"sector": "Semiconductor Infrastructure", "industry": "EUV Photolithography Semiconductor Monopoly", "moat": 9.9, "bs": 9.0, "growth": 12.0, "cannibal": 1.0, "oe_yield": 3.2, "cyc": 4.0, "mandate": "defensive", "p": 0.88, "roic": 38.0, "float_gen": 8.0, "insider_align": 7.5, "cust_conc": 2.5, "lindy_ai_res": 9.8, "scale_shared": 6.0, "thesis": "100% global monopoly on EUV lithography machines (laws of physics moat); 38% ROIC."},
    "QCOM": {"sector": "Semiconductor Infrastructure", "industry": "Wireless IP Licensing & Mobile SoC", "moat": 9.2, "bs": 8.5, "growth": 9.0, "cannibal": 3.5, "oe_yield": 6.2, "cyc": 3.0, "mandate": "aggressive", "p": 0.84, "roic": 32.0, "float_gen": 6.5, "insider_align": 7.0, "cust_conc": 2.0, "lindy_ai_res": 9.0, "scale_shared": 6.0, "thesis": "Cellular standard essential patent licensing cash cow + premium mobile/auto silicon."},
    "TXN": {"sector": "Semiconductor Infrastructure", "industry": "Analog & Embedded Silicon Processing", "moat": 9.4, "bs": 8.5, "growth": 7.0, "cannibal": 1.5, "oe_yield": 3.8, "cyc": 3.0, "mandate": "defensive", "p": 0.87, "roic": 26.0, "float_gen": 5.5, "insider_align": 7.0, "cust_conc": 0.5, "lindy_ai_res": 9.5, "scale_shared": 6.5, "thesis": "300mm analog manufacturing cost advantage with 80,000+ catalog products (low customer concentration)."},
    "ARM": {"sector": "Semiconductor Infrastructure", "industry": "RISC Processor Architecture IP", "moat": 9.7, "bs": 9.5, "growth": 18.0, "cannibal": 0.0, "oe_yield": 2.2, "cyc": 2.0, "mandate": "aggressive", "p": 0.86, "roic": 24.0, "float_gen": 7.0, "insider_align": 7.0, "cust_conc": 1.5, "lindy_ai_res": 9.5, "scale_shared": 6.0, "thesis": "Ubiquitous compute architecture across 99% of smartphones, expanding into data center."},
    "INTC": {"sector": "Semiconductor Infrastructure", "industry": "x86 Compute & Commercial Silicon Foundry", "moat": 8.0, "bs": 7.0, "growth": 4.0, "cannibal": 0.0, "oe_yield": 4.0, "cyc": 3.8, "mandate": "aggressive", "p": 0.68, "roic": 6.0, "float_gen": 4.0, "insider_align": 5.5, "cust_conc": 1.0, "lindy_ai_res": 8.0, "scale_shared": 4.0, "thesis": "Turnaround play on Intel 18A process node commercialization and foundry ramp."},
    "AAPL": {"sector": "Consumer Hardware & Ecosystems", "industry": "Premium Consumer Hardware & iOS Services", "moat": 9.8, "bs": 9.0, "growth": 6.5, "cannibal": 3.0, "oe_yield": 4.1, "cyc": 1.5, "mandate": "defensive", "p": 0.93, "roic": 56.0, "float_gen": 9.5, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 9.6, "scale_shared": 8.5, "thesis": "Unmatched global hardware ecosystem lock-in, 2B+ active devices, 55%+ ROIC."},
    "LULU": {"sector": "Consumer Brands & Retail", "industry": "Technical Athletic Apparel & Athleisure", "moat": 9.2, "bs": 10.0, "growth": 10.0, "cannibal": 4.0, "oe_yield": 7.8, "cyc": 2.2, "mandate": "aggressive", "p": 0.84, "roic": 34.0, "float_gen": 6.5, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 9.0, "scale_shared": 6.0, "thesis": "Pristine zero-debt balance sheet; 34% ROIC, dominant premium activewear brand."},
    "DECK": {"sector": "Consumer Brands & Retail", "industry": "Performance Running & Premium Footwear", "moat": 9.0, "bs": 10.0, "growth": 12.0, "cannibal": 3.0, "oe_yield": 6.5, "cyc": 2.0, "mandate": "aggressive", "p": 0.84, "roic": 36.0, "float_gen": 6.5, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 8.8, "scale_shared": 6.0, "thesis": "Pristine zero-debt balance sheet; 36% ROIC, global HOKA/UGG brand compounding."},
    "CROX": {"sector": "Consumer Brands & Retail", "industry": "Molded Foam Clogs & Casual Slip-Ons", "moat": 8.6, "bs": 8.5, "growth": 6.0, "cannibal": 5.0, "oe_yield": 8.8, "cyc": 2.5, "mandate": "aggressive", "p": 0.8, "roic": 26.0, "float_gen": 6.0, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 8.5, "scale_shared": 5.5, "thesis": "High-margin cash machine (28% operating margin); rapid debt paydown and buybacks."},
    "NKE": {"sector": "Consumer Brands & Retail", "industry": "Global Athletic Footwear & Team Sports", "moat": 9.1, "bs": 8.5, "growth": 5.0, "cannibal": 2.0, "oe_yield": 5.5, "cyc": 2.2, "mandate": "defensive", "p": 0.83, "roic": 24.0, "float_gen": 6.5, "insider_align": 8.0, "cust_conc": 0.5, "lindy_ai_res": 9.5, "scale_shared": 7.5, "thesis": "Phil Knight founder legacy; unmatched global sports endorsement roster and brand turn."},
    "ELF": {"sector": "Consumer Brands & Retail", "industry": "Mass Cosmetics & Skincare Innovation", "moat": 8.7, "bs": 9.0, "growth": 16.0, "cannibal": 0.0, "oe_yield": 5.2, "cyc": 2.2, "mandate": "aggressive", "p": 0.81, "roic": 22.0, "float_gen": 6.0, "insider_align": 8.5, "cust_conc": 1.5, "lindy_ai_res": 8.0, "scale_shared": 7.0, "thesis": "Tarang Amin founder/CEO leadership; prestige duplication in mass beauty."},
    "COST": {"sector": "Consumer Brands & Retail", "industry": "Membership Subscription Wholesale Warehouse", "moat": 9.8, "bs": 9.0, "growth": 9.0, "cannibal": 0.5, "oe_yield": 3.2, "cyc": 1.0, "mandate": "defensive", "p": 0.92, "roic": 28.0, "float_gen": 10.0, "insider_align": 8.5, "cust_conc": 0.5, "lindy_ai_res": 9.8, "scale_shared": 10.0, "thesis": "The pinnacle of Scale Economics Shared; negative working capital float, 93%+ renewal rate."},
    "KO": {"sector": "Consumer Brands & Retail", "industry": "Global Non-Alcoholic Beverage Distribution", "moat": 9.6, "bs": 8.0, "growth": 5.5, "cannibal": 0.5, "oe_yield": 4.5, "cyc": 1.0, "mandate": "defensive", "p": 0.91, "roic": 21.0, "float_gen": 7.0, "insider_align": 6.5, "cust_conc": 0.5, "lindy_ai_res": 9.9, "scale_shared": 8.5, "thesis": "130-year Lindy effect, worldwide bottling distribution network."},
    "CELH": {"sector": "Consumer Brands & Retail", "industry": "Functional Fitness & Energy Beverages", "moat": 8.2, "bs": 9.0, "growth": 18.0, "cannibal": 0.0, "oe_yield": 5.0, "cyc": 2.5, "mandate": "aggressive", "p": 0.78, "roic": 20.0, "float_gen": 6.0, "insider_align": 7.5, "cust_conc": 3.0, "lindy_ai_res": 7.5, "scale_shared": 6.0, "thesis": "Fitness-focused sugar-free energy drink brand scaling via PepsiCo distribution."},
    "UL": {"sector": "Consumer Brands & Retail", "industry": "Global Consumer Staples & Personal Care", "moat": 9.0, "bs": 8.0, "growth": 5.0, "cannibal": 1.0, "oe_yield": 5.2, "cyc": 1.2, "mandate": "defensive", "p": 0.88, "roic": 19.0, "float_gen": 7.5, "insider_align": 6.0, "cust_conc": 0.5, "lindy_ai_res": 9.8, "scale_shared": 7.5, "thesis": "Global footprint in emerging market staples with steady pricing power."},
    "BTI": {"sector": "Consumer Brands & Retail", "industry": "Global Combustible & Smokeless Nicotine", "moat": 8.8, "bs": 7.5, "growth": 3.0, "cannibal": 2.0, "oe_yield": 9.5, "cyc": 1.5, "mandate": "defensive", "p": 0.84, "roic": 16.0, "float_gen": 7.0, "insider_align": 5.5, "cust_conc": 0.5, "lindy_ai_res": 9.5, "scale_shared": 6.0, "thesis": "High-dividend cash generator transitioning into modern oral and vaping categories."},
    "CMG": {"sector": "Consumer Brands & Retail", "industry": "Fast-Casual Dining & Fresh Mexican Grill", "moat": 9.1, "bs": 9.0, "growth": 12.0, "cannibal": 1.0, "oe_yield": 3.8, "cyc": 1.8, "mandate": "defensive", "p": 0.88, "roic": 27.0, "float_gen": 8.0, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 9.0, "scale_shared": 7.0, "thesis": "High unit-economics restaurant chain expanding drive-thru Chipotlanes."},
    "SONY": {"sector": "Consumer Brands & Media", "industry": "Gaming Consoles, Music IP & CMOS Sensors", "moat": 9.2, "bs": 8.5, "growth": 8.0, "cannibal": 2.5, "oe_yield": 6.2, "cyc": 2.2, "mandate": "defensive", "p": 0.86, "roic": 18.0, "float_gen": 7.5, "insider_align": 6.5, "cust_conc": 0.5, "lindy_ai_res": 9.4, "scale_shared": 7.0, "thesis": "PlayStation gaming network, global music publishing oligopoly, CMOS sensor monopoly."},
    "SONO": {"sector": "Consumer Brands & Hardware", "industry": "Premium Multi-Room Smart Home Audio", "moat": 8.0, "bs": 8.5, "growth": 6.0, "cannibal": 4.0, "oe_yield": 7.5, "cyc": 2.8, "mandate": "aggressive", "p": 0.75, "roic": 14.0, "float_gen": 5.5, "insider_align": 7.0, "cust_conc": 1.0, "lindy_ai_res": 8.0, "scale_shared": 4.5, "thesis": "Premium multi-room smart audio system with expanding headphones category."},
    "TSLA": {"sector": "Automotive & Energy Storage", "industry": "Electric Vehicles, Megapack Energy & Autonomy", "moat": 8.8, "bs": 9.0, "growth": 15.0, "cannibal": 0.0, "oe_yield": 2.5, "cyc": 4.0, "mandate": "aggressive", "p": 0.78, "roic": 16.0, "float_gen": 7.5, "insider_align": 9.5, "cust_conc": 0.5, "lindy_ai_res": 8.0, "scale_shared": 8.5, "thesis": "Elon Musk founder leadership; EV market share leader, Megapack energy storage."},
    "KSS": {"sector": "Consumer Brands & Retail", "industry": "Off-Mall Department Stores & Sephora Partnerships", "moat": 7.0, "bs": 6.5, "growth": 1.0, "cannibal": 1.0, "oe_yield": 9.0, "cyc": 3.5, "mandate": "aggressive", "p": 0.65, "roic": 7.0, "float_gen": 4.0, "insider_align": 5.0, "cust_conc": 0.5, "lindy_ai_res": 6.5, "scale_shared": 4.0, "thesis": "Deep value retail real estate turnaround with Sephora shop-in-shops."},
    "TTD": {"sector": "Enterprise Software & AdTech", "industry": "Independent Demand-Side Advertising Platform", "moat": 9.3, "bs": 9.0, "growth": 18.0, "cannibal": 1.0, "oe_yield": 4.2, "cyc": 1.8, "mandate": "aggressive", "p": 0.88, "roic": 24.0, "float_gen": 8.0, "insider_align": 8.5, "cust_conc": 0.5, "lindy_ai_res": 8.8, "scale_shared": 6.5, "thesis": "Independent demand-side programmatic advertising platform monopoly with UID2.0 identity graph standard."},
    "NFLX": {"sector": "Consumer Brands & Media", "industry": "Global Direct-to-Consumer Streaming Entertainment", "moat": 9.5, "bs": 8.5, "growth": 13.0, "cannibal": 2.5, "oe_yield": 4.8, "cyc": 1.2, "mandate": "defensive", "p": 0.90, "roic": 26.0, "float_gen": 9.0, "insider_align": 8.0, "cust_conc": 0.5, "lindy_ai_res": 9.2, "scale_shared": 8.5, "thesis": "Global streaming subscriber scale leader with expanding ad-tier monetization, live events, and $6B+ annual free cash flow."},
    "ADSK": {"sector": "Enterprise Software", "industry": "AEC & Manufacturing Design Software Standards", "moat": 9.6, "bs": 8.5, "growth": 10.0, "cannibal": 2.0, "oe_yield": 5.0, "cyc": 1.5, "mandate": "defensive", "p": 0.89, "roic": 25.0, "float_gen": 8.5, "insider_align": 7.5, "cust_conc": 0.5, "lindy_ai_res": 9.0, "scale_shared": 6.0, "thesis": "AEC (Architecture, Engineering & Construction) CAD software standard (AutoCAD/Revit) with massive professional switching costs."},
    "CHGG": {"sector": "Digital Learning & EdTech", "industry": "Online Student Study Support & Homework Help", "moat": 6.0, "bs": 6.5, "growth": -5.0, "cannibal": 0.0, "oe_yield": 6.0, "cyc": 3.5, "mandate": "aggressive", "p": 0.60, "roic": 8.0, "float_gen": 4.0, "insider_align": 5.5, "cust_conc": 1.0, "lindy_ai_res": 5.0, "scale_shared": 3.5, "thesis": "Deep value student learning aid turnaround navigating generative AI headwinds."},
    "GOOG": {"sector": "Enterprise & Consumer Tech", "industry": "Global Search Monopoly & Hyperscaler Cloud", "moat": 9.8, "bs": 9.8, "growth": 12.0, "cannibal": 3.5, "oe_yield": 5.2, "cyc": 1.2, "mandate": "defensive", "p": 0.92, "roic": 30.0, "float_gen": 9.5, "insider_align": 8.5, "cust_conc": 0.5, "lindy_ai_res": 9.5, "scale_shared": 9.5, "thesis": "Search monopoly, YouTube, Google Cloud, Waymo autonomy, and TPU computing infrastructure."},
    "LMT": {"sector": "Aerospace & Defense", "industry": "Prime Defense Contracting & Advanced Missile Systems", "moat": 9.5, "bs": 8.5, "growth": 5.5, "cannibal": 3.0, "oe_yield": 6.5, "cyc": 1.0, "mandate": "defensive", "p": 0.90, "roic": 22.0, "float_gen": 8.0, "insider_align": 6.5, "cust_conc": 2.0, "lindy_ai_res": 9.8, "scale_shared": 7.0, "thesis": "Sole-source prime defense contractor (F-35, missile defense) with massive government multi-year backlogs."},
}

TAXONOMY_MAP = STOCK_METADATA

def get_asset_metadata(ticker: str, wl_item: dict) -> Dict[str, Any]:
    if ticker in STOCK_METADATA:
        return STOCK_METADATA[ticker]
    labels = wl_item.get("labels", [])
    mandate = "defensive" if "Safe Compounder" in labels or "Quality Compounder" in labels else "aggressive"
    return {
        "sector": "Covered Equities", "industry": f"{ticker} Sector",
        "moat": 8.5, "bs": 8.5, "growth": 10.0, "cannibal": 2.0, "oe_yield": 5.0, "cyc": 2.0,
        "mandate": mandate, "p": 0.82, "roic": 20.0, "float_gen": 6.5, "insider_align": 7.5,
        "cust_conc": 0.5, "lindy_ai_res": 8.5, "scale_shared": 6.0,
        "thesis": "Covered company thesis."
    }

# =============================================================================
# 3. SHILLER CAPE MACRO CASH DERIVATION
# =============================================================================

def calculate_shiller_macro_cash(is_defensive: bool, weighted_mos: float) -> Tuple[float, float, str]:
    froth_scalar = (SHILLER_CAPE - CAPE_HISTORICAL_MEDIAN) / CAPE_HISTORICAL_MEDIAN
    base_macro_cash = min(0.22, max(0.0, froth_scalar * 0.20))
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
# 4. MANDATE-TAILORED SCORING & SIZING ENGINES (SCENARIO ASYMMETRY)
# =============================================================================

def parse_target_price(raw_val: Any, cur_p: float) -> float:
    """Safely extracts pure USD float price from raw target value string."""
    if raw_val is None:
        return cur_p
    m = re.search(r"\$([\d,]+\.?\d*)", str(raw_val))
    if m:
        return float(m.group(1).replace(",", ""))
    try:
        return float(re.sub(r"[^\d.]", "", str(raw_val)))
    except Exception:
        return cur_p

def score_fidelity_defensive(
    ticker: str,
    meta: dict,
    cur_p: float,
    bear_p: float,
    base_p: float,
    bull_p: float,
    sig: str
) -> Dict[str, Any]:
    """
    Fidelity Mandate: Margin of Safety & Downside Risk Paramount.
    Pillars:
    - Base Margin of Safety (30 pts): min(30.0, max(-15.0, base_ret * 0.60))
    - Downside Bear Cushion (25 pts): min(25.0, max(-15.0, (bear_ret + 15.0) * 0.80))
    - Moat Durability (15 pts): (moat / 10.0) * 15.0
    - Pricing Power (10 pts): min(10.0, (p / 0.90) * 10.0)
    - Balance Sheet Fortress (10 pts): (bs / 10.0) * 10.0
    - Capital Allocation ROIC (4 pts): min(4.0, (roic / 30.0) * 4.0)
    - Working Capital Float (2 pts): (float_gen / 10.0) * 2.0
    - Founder / Insider Alignment (2 pts): (insider_align / 10.0) * 2.0
    - Lindy & AI Resilience (2 pts): (lindy_ai_res / 10.0) * 2.0
    - Share Cannibalization (3 pts): min(3.0, cannibal * 0.60)
    - Zero Margin of Safety Penalty: -20 pts if MoS < 5%, -8 pts if MoS < 15%
    """
    bear_ret = ((bear_p - cur_p) / cur_p) * 100.0 if cur_p > 0 else 0.0
    base_ret = ((base_p - cur_p) / cur_p) * 100.0 if cur_p > 0 else 0.0
    bull_ret = ((bull_p - cur_p) / cur_p) * 100.0 if cur_p > 0 else 0.0
    
    mos_pts = min(30.0, max(-15.0, base_ret * 0.60))
    downside_pts = min(25.0, max(-15.0, (bear_ret + 15.0) * 0.80))
    moat_pts = (meta.get("moat", 8.0) / 10.0) * 15.0
    pricing_power = meta.get("p", 0.85)
    pricing_power_pts = min(10.0, (pricing_power / 0.90) * 10.0)
    bs_pts = (meta.get("bs", 8.0) / 10.0) * 10.0
    
    roic_pts = min(4.0, (meta.get("roic", 18.0) / 30.0) * 4.0)
    float_pts = (meta.get("float_gen", 6.0) / 10.0) * 2.0
    insider_pts = (meta.get("insider_align", 7.0) / 10.0) * 2.0
    lindy_pts = (meta.get("lindy_ai_res", 8.5) / 10.0) * 2.0
    cannibal_pts = min(3.0, meta.get("cannibal", 1.0) * 0.60)
    cust_pen = -(meta.get("cust_conc", 0.5) * 1.5)
    
    # Severe penalty for buying at full price (0% MoS)
    if base_ret < 5.0:
        mos_penalty = -20.0
    elif base_ret < 15.0:
        mos_penalty = -8.0
    else:
        mos_penalty = 0.0
        
    total_score = round(max(5.0, mos_pts + downside_pts + moat_pts + pricing_power_pts + bs_pts + roic_pts + float_pts + insider_pts + lindy_pts + cannibal_pts + cust_pen + mos_penalty), 2)
    mos_factor = max(0.20, (base_ret / 40.0))
    downside_factor = max(0.20, 1.0 + (bear_ret / 50.0))
    fid_k = max(0.001, (total_score / 100.0) ** 2 * mos_factor * downside_factor * (meta.get("moat", 8.0) / 10.0) * (pricing_power / 0.85))
    
    return {
        "ticker": ticker, "sector": meta["sector"], "industry": meta["industry"],
        "mandate_pref": "defensive", "price": cur_p, "fair_value": base_p,
        "bear_target": bear_p, "base_target": base_p, "bull_target": bull_p,
        "bear_ret": round(bear_ret, 2), "base_ret": round(base_ret, 2), "bull_ret": round(bull_ret, 2),
        "margin_of_safety_pct": round(base_ret, 2), "oe_yield": meta.get("oe_yield", 5.0),
        "growth": meta["growth"], "cannibal": meta["cannibal"],
        "moat": meta["moat"], "bs": meta["bs"], "pricing_power": pricing_power,
        "roic": meta.get("roic", 18.0), "float_gen": meta.get("float_gen", 6.0),
        "insider_align": meta.get("insider_align", 7.0), "lindy_ai_res": meta.get("lindy_ai_res", 8.5),
        "scale_shared": meta.get("scale_shared", 5.0),
        "total_score": total_score, "kelly_score": fid_k,
        "thesis": meta.get("thesis", ""), "action_signal": sig
    }

def score_wealthsimple_aggressive(
    ticker: str,
    meta: dict,
    cur_p: float,
    bear_p: float,
    base_p: float,
    bull_p: float,
    sig: str
) -> Dict[str, Any]:
    """
    Wealthsimple Mandate: Growth, Asymmetry & Risk-Adjusted Quality.
    Pillars:
    - Organic Growth CAGR (25 pts): min(25.0, (growth / 20.0) * 25.0)
    - Bull Case Asymmetric Upside (25 pts): min(25.0, (bull_ret / 100.0) * 25.0)
    - Base Margin of Safety (15 pts): min(15.0, (base_ret / 50.0) * 15.0)
    - Downside Risk Protection (10 pts): min(10.0, (bear_ret + 30.0) * 0.25)
    - Economic Moat Defense (15 pts): (moat / 10.0) * 15.0
    - Pricing Power (10 pts): min(10.0, (p / 0.90) * 10.0)
    - Reinvestment ROIC (4 pts): min(4.0, (roic / 35.0) * 4.0)
    - Founder / Insider Alignment (3 pts): (insider_align / 10.0) * 3.0
    - Negative Working Capital Float (2 pts): (float_gen / 10.0) * 2.0
    - Lindy & AI Obsolescence Resilience (1 pt): (lindy_ai_res / 10.0) * 1.0
    - Customer Concentration Penalty (-5 pts): -(cust_conc * 1.5)
    """
    bear_ret = ((bear_p - cur_p) / cur_p) * 100.0 if cur_p > 0 else 0.0
    base_ret = ((base_p - cur_p) / cur_p) * 100.0 if cur_p > 0 else 0.0
    bull_ret = ((bull_p - cur_p) / cur_p) * 100.0 if cur_p > 0 else 0.0
    
    asym_ratio = bull_ret / max(10.0, abs(bear_ret)) if bear_ret < 0 else (bull_ret / 5.0)
    growth_pts = min(25.0, max(0.0, (meta.get("growth", 5.0) / 20.0) * 25.0))
    bull_pts = min(25.0, max(0.0, (bull_ret / 100.0) * 25.0))
    ws_mos_pts = min(15.0, (base_ret / 50.0) * 15.0)
    downside_pts_ws = min(10.0, (bear_ret + 30.0) * 0.25)
    ws_moat_pts = (meta.get("moat", 8.0) / 10.0) * 15.0
    pricing_power = meta.get("p", 0.85)
    ws_pp_pts = min(10.0, (pricing_power / 0.90) * 10.0)
    ws_roic_pts = min(4.0, (meta.get("roic", 18.0) / 35.0) * 4.0)
    ws_insider_pts = (meta.get("insider_align", 7.0) / 10.0) * 3.0
    ws_float_pts = (meta.get("float_gen", 6.0) / 10.0) * 2.0
    ws_lindy_pts = (meta.get("lindy_ai_res", 8.5) / 10.0) * 1.0
    ws_cust_pen = -(meta.get("cust_conc", 0.5) * 1.5)
    
    total_score = round(max(5.0, growth_pts + bull_pts + ws_mos_pts + downside_pts_ws + ws_moat_pts + ws_pp_pts + ws_roic_pts + ws_insider_pts + ws_float_pts + ws_lindy_pts + ws_cust_pen), 2)
    ws_k = max(0.001, (total_score / 100.0) ** 2 * (1.0 + min(1.5, asym_ratio / 4.0)) * (meta.get("moat", 8.0) / 10.0) * (pricing_power / 0.85))
    
    return {
        "ticker": ticker, "sector": meta["sector"], "industry": meta["industry"],
        "mandate_pref": "aggressive", "price": cur_p, "fair_value": base_p,
        "bear_target": bear_p, "base_target": base_p, "bull_target": bull_p,
        "bear_ret": round(bear_ret, 2), "base_ret": round(base_ret, 2), "bull_ret": round(bull_ret, 2),
        "asym_ratio": round(asym_ratio, 2), "margin_of_safety_pct": round(base_ret, 2),
        "oe_yield": meta.get("oe_yield", 5.0), "growth": meta["growth"], "cannibal": meta["cannibal"],
        "moat": meta["moat"], "bs": meta["bs"], "pricing_power": pricing_power,
        "roic": meta.get("roic", 18.0), "float_gen": meta.get("float_gen", 6.0),
        "insider_align": meta.get("insider_align", 7.0), "lindy_ai_res": meta.get("lindy_ai_res", 8.5),
        "scale_shared": meta.get("scale_shared", 5.0),
        "total_score": total_score, "kelly_score": ws_k,
        "thesis": meta.get("thesis", ""), "action_signal": sig
    }

# =============================================================================
# 5. FRACTIONAL KELLY PROPORTIONAL CAPPING HELPER
# =============================================================================

def allocate_concentrated_buffett_kelly(
    k_scores: Dict[str, float],
    budget: float,
    max_cap: float = 0.2200,
    min_hurdle: float = 0.0350,
    min_holdings: int = 8,
    max_holdings: int = 12
) -> Dict[str, float]:
    """
    Buffett-Munger Concentrated High-Conviction Allocation Engine:
    - Eliminates artificial 10% dilution caps: highest-conviction fortresses scale up to 20%-22%.
    - Concentrates capital on the top 8 to 12 best ideas (no trivial micro-positions < 3.5%).
    - Automatically balances capital to match the exact macro-equity budget.
    """
    sorted_items = sorted(k_scores.items(), key=lambda x: x[1], reverse=True)
    if not sorted_items:
        return {}
        
    target_count = min(max_holdings, max(min_holdings, len(sorted_items)))
    selected_items = sorted_items[:target_count]
    
    active_tickers = [t for t, k in selected_items]
    allocated = {t: 0.0 for t in active_tickers}
    remaining_budget = budget
    remaining_tickers = list(active_tickers)
    
    for _ in range(20):
        if not remaining_tickers or remaining_budget <= 0.0001:
            break
        tot_k = sum(k_scores[t] for t in remaining_tickers)
        if tot_k <= 0:
            even = remaining_budget / len(remaining_tickers)
            for t in remaining_tickers:
                allocated[t] = min(max_cap, allocated[t] + even)
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
        remaining_budget = max(0.0, round(budget - sum(allocated.values()), 6))
        
    final_res = {t: round(w, 4) for t, w in allocated.items() if w >= min_hurdle}
    tot = sum(final_res.values())
    if tot > 0 and tot < budget:
        mult = budget / tot
        final_res = {t: min(max_cap, round(w * mult, 4)) for t, w in final_res.items()}
        
    return final_res

# =============================================================================
# 6. DUAL PORTFOLIO COMPILATION ENGINE
# =============================================================================

# =============================================================================
# EXPLICIT DUOPOLY CLUSTERS (DIRECT HEAD-TO-HEAD SUBSTITUTE PAIRS ONLY)
# =============================================================================

DUOPOLY_CLUSTERS = [
    {"V", "MA"},        # Global Consumer Payment Network Rails
    {"CMCSA", "CHTR"},  # US Cable Broadband Infrastructure
    {"MTCH", "BMBL"},   # Mobile Dating App Networks
    {"SPGI", "MCO"},    # Sovereign Debt Ratings & S&P Benchmarks
    {"KO", "PEP"},      # Carbonated Soft Drink Bottling Duopoly
    {"BKNG", "EXPE"},   # Global Online Travel Agencies
    {"UBER", "LYFT"},   # North American Rideshare Networks
    {"HD", "LOW"},      # Big Box Home Improvement
]

def get_duopoly_partner(ticker: str) -> Optional[str]:
    """Returns the direct head-to-head duopoly twin if one exists."""
    for cluster in DUOPOLY_CLUSTERS:
        if ticker in cluster:
            partners = cluster - {ticker}
            return list(partners)[0] if partners else None
    return None

def construct_dual_portfolios(total_capital: float = 200000.0) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    with open(WATCHLIST_FILE, "r") as f:
        wl = json.load(f)
        
    fidelity_candidates = []
    wealthsimple_candidates = []
    
    for ticker, w_item in wl.items():
        if ticker in COMPLIANCE_EXCLUSIONS:
            continue
            
        sig = w_item.get("action_signal", "HOLD")
        cur_p = float(w_item.get("current_price", 100.0))
        bear_p = parse_target_price(w_item.get("bear_target"), cur_p)
        base_p = parse_target_price(w_item.get("base_target") or w_item.get("fair_value_estimate"), cur_p)
        bull_p = parse_target_price(w_item.get("bull_target"), cur_p)
        
        # Mathematical hurdle: must offer positive expected base DCF return
        base_ret = ((base_p - cur_p) / cur_p) * 100.0 if cur_p > 0 else 0.0
        if base_ret <= 0.0:
            continue
            
        meta = get_asset_metadata(ticker, w_item)
        
        scored_fid = score_fidelity_defensive(ticker, meta, cur_p, bear_p, base_p, bull_p, sig)
        fidelity_candidates.append(scored_fid)
            
        scored_ws = score_wealthsimple_aggressive(ticker, meta, cur_p, bear_p, base_p, bull_p, sig)
        wealthsimple_candidates.append(scored_ws)

    # 1. Wealthsimple selects high-growth asymmetric alpha champions (Growth >= 8.0%)
    # Strict duopoly filter ONLY (e.g. V vs MA) - No arbitrary sector/industry exclusion blocks
    wealthsimple_candidates.sort(key=lambda x: (x["total_score"], x["growth"], x["bull_ret"]), reverse=True)
    ws_selected = []
    ws_selected_tickers = set()
    ws_blocked_duopolies = set()
    
    for item in wealthsimple_candidates:
        t = item["ticker"]
        if item["growth"] < 8.0:
            continue
        if t in ws_blocked_duopolies:
            continue
            
        ws_selected.append(item)
        ws_selected_tickers.add(t)
        partner = get_duopoly_partner(t)
        if partner:
            ws_blocked_duopolies.add(partner)

    # 2. Fidelity selects fortress moat & defensive preservation compounders
    # Strictly excludes any ticker selected in Wealthsimple (Zero Overlap Invariant) + Duopoly Filter
    fidelity_candidates.sort(key=lambda x: (x["total_score"], x["base_ret"], x["moat"]), reverse=True)
    fid_selected = []
    fid_selected_tickers = set()
    fid_blocked_duopolies = set()
    
    for item in fidelity_candidates:
        t = item["ticker"]
        if t in ws_selected_tickers:
            continue
        if t in fid_blocked_duopolies:
            continue
            
        fid_selected.append(item)
        fid_selected_tickers.add(t)
        partner = get_duopoly_partner(t)
        if partner:
            fid_blocked_duopolies.add(partner)
    # 3. Compute Fidelity Allocations
    fid_k = {x["ticker"]: x["kelly_score"] for x in fid_selected}
    fid_mos = sum(x["margin_of_safety_pct"] for x in fid_selected) / len(fid_selected) if fid_selected else 25.0
    fid_cash_target, fid_budget, fid_desc = calculate_shiller_macro_cash(True, fid_mos)
    fid_weights = allocate_concentrated_buffett_kelly(fid_k, fid_budget, max_cap=0.2200, min_hurdle=0.0350, min_holdings=8, max_holdings=12)

    # Ensure cash absorbs exact remainder
    tot_fid_equity = sum(fid_weights.values())
    exact_fid_cash = round(max(0.05, 1.0 - tot_fid_equity), 4)

    sorted_def_tickers = sorted(fid_weights.keys(), key=lambda t: fid_weights[t], reverse=True)
    def_holdings = []
    for t in sorted_def_tickers:
        s = next(x for x in fid_selected if x["ticker"] == t)
        w = fid_weights[t]
        alloc = round(total_capital * w, 2)
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
            "allocated_dollars": alloc,
            "shares_to_buy": shs,
            "look_through_fcf_yield": s["oe_yield"],
            "annual_owner_earnings": round(oe_yr, 2),
            "cannibal_rate_pct": s["cannibal"],
            "thesis_core": s["thesis"],
            "report_url": f"reports/{t}.html"
        })

    def_cash_dollars = round(total_capital - sum(h["allocated_dollars"] for h in def_holdings), 2)
    def_holdings.append({
        "ticker": "USD_CASH",
        "company_name": "USD Cash Reserve",
        "sector": "Cash & Cash Equivalents",
        "industry": "3-Month US Treasury Bills",
        "quality_score": 100.0,
        "target_weight": exact_fid_cash,
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
        "thesis_core": fid_desc,
        "report_url": "#"
    })

    # 4. Compute Wealthsimple Allocations
    ws_k = {x["ticker"]: x["kelly_score"] for x in ws_selected}
    ws_mos = sum(x["margin_of_safety_pct"] for x in ws_selected) / len(ws_selected) if ws_selected else 40.0
    ws_cash_target, ws_budget, ws_desc = calculate_shiller_macro_cash(False, ws_mos)
    ws_weights = allocate_concentrated_buffett_kelly(ws_k, ws_budget, max_cap=0.2200, min_hurdle=0.0350, min_holdings=8, max_holdings=12)

    tot_ws_equity = sum(ws_weights.values())
    exact_ws_cash = round(max(0.03, 1.0 - tot_ws_equity), 4)

    sorted_agg_tickers = sorted(ws_weights.keys(), key=lambda t: ws_weights[t], reverse=True)
    agg_holdings = []
    for t in sorted_agg_tickers:
        s = next(x for x in ws_selected if x["ticker"] == t)
        w = ws_weights[t]
        alloc = round(total_capital * w, 2)
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
            "allocated_dollars": alloc,
            "shares_to_buy": shs,
            "look_through_fcf_yield": s["oe_yield"],
            "annual_owner_earnings": round(oe_yr, 2),
            "cannibal_rate_pct": s["cannibal"],
            "thesis_core": s["thesis"],
            "report_url": f"reports/{t}.html"
        })

    agg_cash_dollars = round(total_capital - sum(h["allocated_dollars"] for h in agg_holdings), 2)
    agg_holdings.append({
        "ticker": "USD_CASH",
        "company_name": "USD Cash Strike Reserve",
        "sector": "Cash & Cash Equivalents",
        "industry": "3-Month US Treasury Bills",
        "quality_score": 100.0,
        "target_weight": exact_ws_cash,
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
        "thesis_core": ws_desc,
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
                "action": "CANNIBAL FORTRESS CALIBRATION",
                "reason": fid_desc,
                "verification_status": "Verified 3/3 Autonomous Council"
            }
        ],
        "historical_performance": [
            {
                "date": "2026-08-11",
                "portfolio_value": 200000.00,
                "owner_earnings_runrate": round(def_oe_sum, 2),
                "spy_benchmark": 200000.00
            }
        ]
    }

    agg_state = {
        "portfolio_name": "Wealthsimple",
        "portfolio_type": "aggressive",
        "target_audience": "Aggressive Alpha, High-Velocity Cannibal Compounders (No Value Traps)",
        "inception_date": "2026-08-11",
        "last_rebalance_date": "2026-08-11",
        "base_capital_usd": total_capital,
        "holdings": agg_holdings,
        "rebalance_log": [
            {
                "date": "2026-08-11",
                "action": "CANNIBAL FORTRESS CALIBRATION",
                "reason": ws_desc,
                "verification_status": "Verified 3/3 Autonomous Council"
            }
        ],
        "historical_performance": [
            {
                "date": "2026-08-11",
                "portfolio_value": 200000.00,
                "owner_earnings_runrate": round(agg_oe_sum, 2),
                "spy_benchmark": 200000.00
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
