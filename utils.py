"""
Utility functions for the Telegram Trading Bot
"""

import logging
import yaml
import re
from pathlib import Path
from typing import Optional, Dict, Any, Union
from datetime import datetime
from dotenv import load_dotenv
import os


class Config:
    """Configuration loader and manager"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Load configuration from YAML file and environment variables
        
        Args:
            config_path: Path to the config.yaml file
        """
        # Load environment variables
        load_dotenv()
        
        # Load YAML config
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        with open(config_file, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Load sensitive data from environment
        self.telegram_api_id = os.getenv('TELEGRAM_API_ID')
        self.telegram_api_hash = os.getenv('TELEGRAM_API_HASH')
        self.telegram_phone = os.getenv('TELEGRAM_PHONE')
        self.anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')
        self.mt5_account = os.getenv('MT5_ACCOUNT')
        self.mt5_password = os.getenv('MT5_PASSWORD')
        self.mt5_server = os.getenv('MT5_SERVER')
        self.environment = os.getenv('ENVIRONMENT', 'development')
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get config value using dot notation (e.g., 'llm.model')
        
        Args:
            key_path: Dot-separated path to config value
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        keys = key_path.split('.')
        value = self.config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value


def setup_logging(config: Config) -> logging.Logger:
    """
    Setup logging configuration
    
    Args:
        config: Configuration object
        
    Returns:
        Configured logger
    """
    log_level = getattr(logging, config.get('logging.level', 'INFO'))
    log_format = config.get('logging.format')
    
    # Create logs directory if it doesn't exist
    Path('logs').mkdir(exist_ok=True)
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[]
    )
    
    logger = logging.getLogger('TradingBot')
    logger.setLevel(log_level)
    
    # Console handler with UTF-8 encoding
    if config.get('logging.console', True):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(log_format))
        # Force UTF-8 encoding for console to handle emojis/unicode
        if hasattr(console_handler.stream, 'reconfigure'):
            try:
                console_handler.stream.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass  # Fallback if reconfigure fails
        logger.addHandler(console_handler)
    
    # File handler with UTF-8 encoding
    if config.get('logging.file', True):
        file_handler = logging.FileHandler(
            config.get('logging.file_path'),
            encoding='utf-8',
            errors='replace'
        )
        file_handler.setFormatter(logging.Formatter(log_format))
        logger.addHandler(file_handler)
    
    return logger


def parse_price(price_str: Union[str, float, int]) -> Optional[float]:
    """
    Parse price from various formats
    
    Args:
        price_str: Price as string, float, or int
        
    Returns:
        Parsed price as float or None if invalid
        
    Examples:
        "1.0850" -> 1.0850
        "1.08500" -> 1.0850
        "10850" (pips) -> 1.0850 (assumes 5-digit broker)
        1.0850 -> 1.0850
    """
    if isinstance(price_str, (float, int)):
        return float(price_str)
    
    if not isinstance(price_str, str):
        return None
    
    # Remove whitespace and common separators
    price_str = price_str.strip().replace(',', '.')
    
    # Try direct float conversion
    try:
        price = float(price_str)
        
        # If price is very large (like 10850), assume it's in pips for 5-digit broker
        if price > 1000:
            # Convert pips to price (assuming XXXYYY format where last 2 digits are pips)
            price = price / 10000
        
        return price
    except ValueError:
        return None


def parse_lot_size(lot_str: Union[str, float, int]) -> Optional[float]:
    """
    Parse lot size from various formats
    
    Args:
        lot_str: Lot size as string, float, or int
        
    Returns:
        Parsed lot size as float or None if invalid
        
    Examples:
        "0.01" -> 0.01
        "1" -> 1.0
        "0.1 lot" -> 0.1
    """
    if isinstance(lot_str, (float, int)):
        return float(lot_str)
    
    if not isinstance(lot_str, str):
        return None
    
    # Remove 'lot' or 'lots' suffix
    lot_str = re.sub(r'\s*(lot|lots)\s*', '', lot_str, flags=re.IGNORECASE)
    lot_str = lot_str.strip()
    
    try:
        return float(lot_str)
    except ValueError:
        return None


def parse_symbol(symbol_str: str) -> Optional[str]:
    """
    Parse and normalize trading symbol/pair
    
    Args:
        symbol_str: Symbol as string (e.g., "EUR/USD", "EURUSD", "EUR-USD")
        
    Returns:
        Normalized symbol (e.g., "EURUSD") or None if invalid
    """
    if not isinstance(symbol_str, str):
        return None
    
    # Remove common separators and spaces
    symbol = symbol_str.upper().replace('/', '').replace('-', '').replace(' ', '')
    
    # Common forex pairs (6 characters) or commodities/indices
    if len(symbol) >= 6:
        return symbol
    
    return None


def validate_lot_size(lot_size: float, config: Config) -> tuple[bool, str]:
    """
    Validate lot size against risk parameters
    
    Args:
        lot_size: Lot size to validate
        config: Configuration object
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    min_lot = config.get('risk.min_lot_size', 0.01)
    max_lot = config.get('risk.max_lot_size', 5.0)
    
    if lot_size < min_lot:
        return False, f"Lot size {lot_size} is below minimum {min_lot}"
    
    if lot_size > max_lot:
        return False, f"Lot size {lot_size} exceeds maximum {max_lot}"
    
    return True, ""


def calculate_risk_reward(entry: float, stop_loss: float, take_profit: float, 
                         action: str) -> float:
    """
    Calculate risk-reward ratio
    
    Args:
        entry: Entry price
        stop_loss: Stop loss price
        take_profit: Take profit price
        action: "BUY" or "SELL"
        
    Returns:
        Risk-reward ratio (reward / risk)
    """
    if action.upper() == "BUY":
        risk = abs(entry - stop_loss)
        reward = abs(take_profit - entry)
    else:  # SELL
        risk = abs(stop_loss - entry)
        reward = abs(entry - take_profit)
    
    if risk == 0:
        return 0
    
    return reward / risk


def format_timestamp(dt: datetime = None) -> str:
    """
    Format timestamp for display
    
    Args:
        dt: Datetime object (uses current time if None)
        
    Returns:
        Formatted timestamp string
    """
    if dt is None:
        dt = datetime.now()
    
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def colorize(text: str, color: str) -> str:
    """
    Add ANSI color codes to text for terminal output
    
    Args:
        text: Text to colorize
        color: Color name (red, green, yellow, blue, cyan, magenta)
        
    Returns:
        Colorized text string
    """
    colors = {
        'red': '\033[91m',
        'green': '\033[92m',
        'yellow': '\033[93m',
        'blue': '\033[94m',
        'cyan': '\033[96m',
        'magenta': '\033[95m',
        'reset': '\033[0m'
    }
    
    color_code = colors.get(color.lower(), '')
    reset_code = colors['reset']
    
    return f"{color_code}{text}{reset_code}"


def sanitize_for_logging(text: str, max_length: int = 200) -> str:
    """
    Sanitize text for safe logging (remove problematic Unicode characters)
    
    Args:
        text: Text to sanitize
        max_length: Maximum length to keep
        
    Returns:
        Sanitized text safe for logging
    """
    # Truncate if too long
    if len(text) > max_length:
        text = text[:max_length] + '...'
    
    # Replace problematic characters with safe alternatives
    # This handles emojis and other Unicode characters that might cause encoding issues
    try:
        # Try to encode as ASCII, replacing non-ASCII characters
        text = text.encode('ascii', errors='replace').decode('ascii')
    except Exception:
        # If that fails, just remove problematic characters
        text = ''.join(char if ord(char) < 128 else '?' for char in text)
    
    return text


def print_trade_summary(trade_data: Dict[str, Any], color: bool = True) -> None:
    """
    Print a formatted trade summary
    
    Args:
        trade_data: Dictionary containing trade information
        color: Whether to use colored output
    """
    pair = trade_data.get('pair', 'N/A')
    action = trade_data.get('action', 'N/A')
    entry = trade_data.get('entry_price', 0)
    sl = trade_data.get('stop_loss', 0)
    tp = trade_data.get('take_profit', 0)
    lot_size = trade_data.get('lot_size', 0)
    
    if color:
        action_colored = colorize(action, 'green' if action == 'BUY' else 'red')
        print(f"\n{'='*50}")
        print(f"  {action_colored} {pair}")
        print(f"  Entry: {entry} | SL: {sl} | TP: {tp}")
        print(f"  Lot Size: {lot_size}")
        print(f"{'='*50}\n")
    else:
        print(f"\n{'='*50}")
        print(f"  {action} {pair}")
        print(f"  Entry: {entry} | SL: {sl} | TP: {tp}")
        print(f"  Lot Size: {lot_size}")
        print(f"{'='*50}\n")


# Example usage and testing
if __name__ == "__main__":
    # Test price parsing
    print("Testing price parsing:")
    print(f"  '1.0850' -> {parse_price('1.0850')}")
    print(f"  '10850' -> {parse_price('10850')}")
    print(f"  1.0850 -> {parse_price(1.0850)}")
    
    # Test lot size parsing
    print("\nTesting lot size parsing:")
    print(f"  '0.01' -> {parse_lot_size('0.01')}")
    print(f"  '1 lot' -> {parse_lot_size('1 lot')}")
    
    # Test symbol parsing
    print("\nTesting symbol parsing:")
    print(f"  'EUR/USD' -> {parse_symbol('EUR/USD')}")
    print(f"  'GBPUSD' -> {parse_symbol('GBPUSD')}")
    print(f"  'XAU-USD' -> {parse_symbol('XAU-USD')}")
    
    # Test risk-reward calculation
    print("\nTesting risk-reward calculation:")
    rr = calculate_risk_reward(1.0850, 1.0800, 1.0950, "BUY")
    print(f"  BUY @ 1.0850, SL: 1.0800, TP: 1.0950 -> RR: {rr:.2f}")
