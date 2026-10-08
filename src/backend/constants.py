"""Shared application constants and controlled vocabularies."""

from enum import StrEnum

SENTIMENT_HALF_LIFE_HOURS = 72.0
SENTIMENT_HALF_LIFE_MS = SENTIMENT_HALF_LIFE_HOURS * 60.0 * 60.0 * 1000.0
GRAPH_PROPAGATION_SCALE = 0.15
SCORE_EPSILON = 1e-6
MAX_NEWS_EVENT_DOCUMENTS = 25_000
STOCK_SELECTOR_TOP_K = 5
STOCK_SELECTOR_TEMPERATURE = 0.07

FLANG_ROBERTA = "SALT-NLP/FLANG-Roberta"
DEFAULT_SENTIMENT_LABELS = ("negative", "neutral", "positive")
KAGGLE_MODEL_HANDLES = {
    "sentiment_classification": "arjunverma14142/flang-roberta-sentiment-classification/pyTorch/default",
    "sentiment_scorer": "arjunverma14142/flang-roberta-sentiment-scorer/pyTorch/default",
    "flang_laya": "arjunverma14142/flang-laya/pyTorch/default",
    "stock_selector": "arjunverma14142/flang-roberta-stock-selector/pyTorch/default",
}

JEV_BASE_URL = "https://opencode.ai/zen/v1"
JEV_MODEL = "jev-1.13-free"
JEV_MAX_RETRIES = 2
JEV_TIMEOUT_SECONDS = 90.0
ALPACA_NEWS_STREAM_URL = "wss://stream.data.alpaca.markets/v1beta1/news"
FINNHUB_COMPANY_NEWS_URL = "https://finnhub.io/api/v1/company-news"
BLUESKY_JETSTREAM_URL = "wss://jetstream2.us-east.bsky.network/subscribe"


class SentimentTag(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"

class NewsAnalysisStatus(StrEnum):
    QUEUED = "queued"
    PENDING_ANALYSIS = "pending_analysis"
    APPLYING_SCORES = "applying_scores"
    COMPLETE = "complete"

class NewsCategory(StrEnum):
    EARNINGS = "earnings"
    MERGERS_ACQUISITIONS = "mergers_acquisitions"
    PRODUCT_INNOVATION = "product_innovation"
    REGULATION_LEGAL = "regulation_legal"
    MACROECONOMIC = "macroeconomic"
    ANALYST_RATINGS = "analyst_ratings"
    CORPORATE_ACTIONS = "corporate_actions"
    OPERATIONS_SUPPLY_CHAIN = "operations_supply_chain"
    MARKET_TRADING = "market_trading"
    GEOPOLITICAL_EVENT = "geopolitical_event"

SP100_COMPANIES = {
    "AAPL": "Apple Inc.", "ABBV": "AbbVie Inc.", "ABT": "Abbott Laboratories",
    "ACN": "Accenture plc", "ADBE": "Adobe Inc.", "AMAT": "Applied Materials, Inc.",
    "AMD": "Advanced Micro Devices, Inc.", "AMGN": "Amgen Inc.", "AMT": "American Tower Corporation",
    "AMZN": "Amazon.com, Inc.", "ANET": "Arista Networks, Inc.", "AVGO": "Broadcom Inc.",
    "AXP": "American Express Company", "BA": "The Boeing Company", "BAC": "Bank of America Corporation",
    "BKNG": "Booking Holdings Inc.", "BLK": "BlackRock, Inc.", "BMY": "Bristol Myers Squibb Company",
    "BNY": "The Bank of New York Mellon Corporation", "BRK.B": "Berkshire Hathaway Inc.",
    "C": "Citigroup Inc.", "CAT": "Caterpillar Inc.", "CMCSA": "Comcast Corporation",
    "COF": "Capital One Financial Corporation", "COP": "ConocoPhillips", "COST": "Costco Wholesale Corporation",
    "CRM": "Salesforce, Inc.", "CSCO": "Cisco Systems, Inc.", "CVS": "CVS Health Corporation",
    "CVX": "Chevron Corporation", "DE": "Deere & Company", "DELL": "Dell Technologies Inc.",
    "DHR": "Danaher Corporation", "DIS": "The Walt Disney Company", "DUK": "Duke Energy Corporation",
    "EMR": "Emerson Electric Co.", "FDX": "FedEx Corporation", "GD": "General Dynamics Corporation",
    "GE": "GE Aerospace", "GEV": "GE Vernova Inc.", "GILD": "Gilead Sciences, Inc.",
    "GM": "General Motors Company", "GOOG": "Alphabet Inc. Class C", "GOOGL": "Alphabet Inc. Class A",
    "GS": "The Goldman Sachs Group, Inc.", "HD": "The Home Depot, Inc.",
    "IBM": "International Business Machines Corporation", "INTC": "Intel Corporation",
    "INTU": "Intuit Inc.", "ISRG": "Intuitive Surgical, Inc.", "JNJ": "Johnson & Johnson",
    "JPM": "JPMorgan Chase & Co.", "KO": "The Coca-Cola Company", "LIN": "Linde plc",
    "LLY": "Eli Lilly and Company", "LMT": "Lockheed Martin Corporation", "LOW": "Lowe's Companies, Inc.",
    "LRCX": "Lam Research Corporation", "MA": "Mastercard Incorporated", "MCD": "McDonald's Corporation",
    "MDLZ": "Mondelez International, Inc.", "MDT": "Medtronic plc", "META": "Meta Platforms, Inc.",
    "MMM": "3M Company", "MO": "Altria Group, Inc.", "MRK": "Merck & Co., Inc.",
    "MS": "Morgan Stanley", "MSFT": "Microsoft Corporation", "MU": "Micron Technology, Inc.",
    "NEE": "NextEra Energy, Inc.", "NFLX": "Netflix, Inc.", "NOW": "ServiceNow, Inc.",
    "NVDA": "NVIDIA Corporation", "ORCL": "Oracle Corporation", "PANW": "Palo Alto Networks, Inc.",
    "PEP": "PepsiCo, Inc.", "PFE": "Pfizer Inc.", "PG": "The Procter & Gamble Company",
    "PLTR": "Palantir Technologies Inc.", "PM": "Philip Morris International Inc.",
    "QCOM": "QUALCOMM Incorporated", "RTX": "RTX Corporation", "SBUX": "Starbucks Corporation",
    "SCHW": "The Charles Schwab Corporation", "SNDK": "Sandisk Corporation",
    "SO": "The Southern Company", "T": "AT&T Inc.", "TMO": "Thermo Fisher Scientific Inc.",
    "TMUS": "T-Mobile US, Inc.", "TSLA": "Tesla, Inc.", "TXN": "Texas Instruments Incorporated",
    "UBER": "Uber Technologies, Inc.", "UNH": "UnitedHealth Group Incorporated",
    "UNP": "Union Pacific Corporation", "UPS": "United Parcel Service, Inc.",
    "USB": "U.S. Bancorp", "V": "Visa Inc.", "VZ": "Verizon Communications Inc.",
    "WFC": "Wells Fargo & Company", "WMT": "Walmart Inc.", "XOM": "Exxon Mobil Corporation",
}
SP100_SET = frozenset(SP100_COMPANIES)
