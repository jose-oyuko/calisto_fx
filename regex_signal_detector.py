"""
Telegram Trading Signal Detector
Uses regex pattern matching to detect BUY NOW / SELL NOW entry signals.
All other messages are treated as noise.

Output format matches the LLM config.yaml signal schema.
"""

import re
from typing import Union
from llm import NewSignal, NoSignal


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Supported trading pairs (extend as needed)
KNOWN_PAIRS = [
    "XAUUSD", "GOLD",
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD",
    "USDCAD", "GBPJPY", "EURJPY", "EURGBP", "AUDCAD", "AUDNZD",
    "BTCUSD", "ETHUSD",
]

# Map aliases to standard pair names
PAIR_ALIASES = {
    "GOLD": "XAUUSD",
}

# Regex for optional pair at the start of the message
PAIR_PATTERN = r"(?P<pair>" + "|".join(KNOWN_PAIRS) + r")[\s,]*"

# Direction: BUY or SELL (also accept LONG/SHORT as synonyms)
DIRECTION_MAP = {
    "BUY":  "BUY",
    "LONG": "BUY",
    "SELL": "SELL",
    "SHORT": "SELL",
}
DIRECTION_PATTERN = r"(?P<action>BUY|SELL|LONG|SHORT)"

# Market execution keywords
MARKET_PATTERN = r"(?:NOW|MARKET|AT\s+MARKET|IMMEDIATELY|INSTANT(?:LY)?)"

# Optional SL
SL_PATTERN = r"(?:SL|STOP(?:\s+LOSS)?|STOP)\s*[:\-]?\s*(?P<sl>\d+(?:\.\d+)?)"

# Optional TP (first level only — no partials)
TP_PATTERN = r"(?:TP|TAKE\s+PROFIT|TARGET|TGT)\s*[:\-]?\s*(?P<tp>\d+(?:\.\d+)?)"

# Master entry signal pattern:
# [optional pair] DIRECTION [optional pair] NOW/MARKET
# Two separate pair patterns to avoid duplicate named group error in Python re
ENTRY_SIGNAL_PATTERN = re.compile(
    r"(?:(?P<pair_pre>" + "|".join(KNOWN_PAIRS) + r")[\s,]*)?"  # pair BEFORE direction
    + DIRECTION_PATTERN                                            # BUY / SELL
    + r"[\s,]*"
    + r"(?:(?P<pair_post>" + "|".join(KNOWN_PAIRS) + r")[\s,]*)?" # pair AFTER direction
    + r"[\s,]*"
    + MARKET_PATTERN,                                              # NOW / MARKET / etc.
    re.IGNORECASE,
)

SL_RE = re.compile(SL_PATTERN, re.IGNORECASE)
TP_RE = re.compile(TP_PATTERN, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_pair(raw: str | None) -> str:
    """Return the canonical pair name, defaulting to XAUUSD."""
    if not raw:
        return "XAUUSD"
    upper = raw.upper()
    return PAIR_ALIASES.get(upper, upper)


def _extract_sl(message: str) -> float | None:
    m = SL_RE.search(message)
    return float(m.group("sl")) if m else None


def _extract_tp(message: str) -> float | None:
    m = TP_RE.search(message)
    return float(m.group("tp")) if m else None


# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------

def detect_signal(message: str) -> Union[NewSignal, NoSignal]:
    """
    Analyse a Telegram message and return a trading signal dict.

    Parameters
    ----------
    message : str
        Raw message text received from the Telegram group.

    Returns
    -------
    dict
        Signal dict matching the config.yaml output schema:
        - signal_type : "new_signal" | "none"
        - pair        : str  (only when new_signal)
        - action      : "BUY" | "SELL"  (only when new_signal)
        - entry_price : 0  (always 0 — market execution)
        - stop_loss   : float | None
        - take_profit : float | None
        - execution_type : "immediate"
        - confidence  : float
        - reasoning   : str
        - timestamp   : ISO-8601 UTC string
    """
    if not message or not message.strip():
        return _noise("Empty message received.", confidence=1.0)

    clean = message.strip()

    match = ENTRY_SIGNAL_PATTERN.search(clean)

    if not match:
        return _noise(
            f"No BUY/SELL NOW pattern found. Treated as noise: '{clean[:80]}'",
            confidence=0.97,
        )

    # Extract direction
    raw_action = match.group("action").upper()
    action = DIRECTION_MAP.get(raw_action, raw_action)

    # Extract pair — check pair_pre first, then pair_post (e.g. "BUY GOLD NOW")
    raw_pair = match.group("pair_pre") or match.group("pair_post")
    pair = _normalise_pair(raw_pair)

    # Extract optional SL / TP from the full message
    sl = _extract_sl(clean)
    tp = _extract_tp(clean)

    parts = [f"Immediate {action} market signal on {pair}."]
    if sl:
        parts.append(f"SL extracted: {sl}.")
    if tp:
        parts.append(f"TP extracted: {tp}.")
    if not raw_pair:
        parts.append("No pair specified — defaulted to XAUUSD.")

    return NewSignal(
        signal_type="new_signal",
        pair=pair,
        action=action,
        entry_price=0.0,
        stop_loss=sl,
        take_profit=tp,
        tp_levels=None,
        lot_size=None,
        execution_type="immediate",
        confidence=0.95,
        reasoning=" ".join(parts),
    )


def _noise(reason: str, confidence: float = 0.95) -> NoSignal:
    return NoSignal(
        signal_type="none",
        confidence=confidence,
        reasoning=reason,
    )


# ---------------------------------------------------------------------------
# Pretty printer (optional convenience)
# ---------------------------------------------------------------------------

def print_signal(message: str) -> None:
    """Detect and pretty-print the signal for a given message."""
    result = detect_signal(message)
    print(result)



# ---------------------------------------------------------------------------
# LLM output parser
# ---------------------------------------------------------------------------

def parse_llm_signal(llm_output: str) -> dict:
    """
    Parse the string repr that the LLM returns into a plain dict,
    matching the same structure that detect_signal() returns.

    The LLM returns a Pydantic-style repr like:
        signal_type='new_signal' pair='XAUUSD' action='BUY' entry_price=0.0 ...

    Parameters
    ----------
    llm_output : str
        Raw string returned by the LLM signal interpreter.

    Returns
    -------
    dict
        Same schema as detect_signal() output.
    """
    result = {}

    # Match  key='string value'  or  key="string value"
    str_pattern = re.compile(r"(\w+)=[\'\"](.*?)[\'\"](\s|$)")
    for m in str_pattern.finditer(llm_output):
        result[m.group(1)] = m.group(2)

    # Match  key=123  or  key=1.23  (numeric, not inside quotes)
    num_pattern = re.compile(r"(\w+)=(-?\d+\.\d+|-?\d+)(?:\s|$)")
    for m in num_pattern.finditer(llm_output):
        key = m.group(1)
        if key not in result:          # don't overwrite already-parsed strings
            raw = m.group(2)
            result[key] = float(raw) if "." in raw else int(raw)

    # Match  key=None
    none_pattern = re.compile(r"(\w+)=None(?:\s|$)")
    for m in none_pattern.finditer(llm_output):
        key = m.group(1)
        if key not in result:
            result[key] = None

    # Match  key=True / key=False
    bool_pattern = re.compile(r"(\w+)=(True|False)(?:\s|$)")
    for m in bool_pattern.finditer(llm_output):
        key = m.group(1)
        if key not in result:
            result[key] = m.group(2) == "True"

    return result

# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_messages = [
        # --- Should produce new_signal ---
        "BUY NOW",
        "SELL NOW",
        "BUY GOLD NOW",
        "XAUUSD BUY NOW",
        "SELL NOW SL 4700 TP 4550",
        "XAUUSD SELL NOW, SL 4700, TP 4550",
        "EURUSD BUY NOW SL 1.0800 TP 1.0950",
        "LONG NOW",
        "SHORT NOW",
        "BUY MARKET",
        "SELL AT MARKET",

        # --- Should produce none ---
        "BUY at 4450, SL 4400, TP 4500",
        "XAUUSD SELL RANGE: 4435-4450",
        "Move SL to breakeven",
        "Take partials",
        "Close 50%",
        "Close all",
        "SL 4500, TP 4600",
        "Gold looking bullish today",
        "SET BE AND TAKE PARTIALS",
        "We are no longer in this trade",
        "",
    ]

    separator = "-" * 60
    for msg in test_messages:
        print(separator)
        print(f"INPUT : {repr(msg)}")
        result = detect_signal(msg)
        print(f"OUTPUT: {result}")
    print(separator)