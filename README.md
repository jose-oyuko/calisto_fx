# Telegram Trading Bot

An automated trading bot that listens to Telegram groups for trading signals, interprets them using Claude AI, and executes trades on MetaTrader 5.

## Features

- 🤖 Automated signal detection from Telegram groups
- 🧠 AI-powered signal interpretation using Anthropic Claude
- 📊 Direct MT5 trade execution
- 🔄 Trade modification support (SL/TP updates)
- 💼 Trade state management and tracking
- 🖥️ Interactive REPL command interface
- ⚙️ Configurable risk management

## Project Structure

```
telegram_trading_bot/
├── main.py                 # Entry point and orchestration
├── telegram.py             # Telegram client integration
├── llm.py                  # LLM signal interpretation
├── mt5.py                  # MT5 connection and execution
├── trade_manager.py        # Trade state management
├── utils.py                # Helper functions
├── config.yaml             # Configuration settings
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (create from .env.example)
├── logs/                   # Log files
└── data/                   # Trade data persistence
```

## Installation

### Prerequisites

- Python 3.9 or higher
- MetaTrader 5 terminal installed and running
- Telegram account
- Anthropic API key

### Step 1: Clone and Setup

```bash
# Create project directory
mkdir telegram_trading_bot
cd telegram_trading_bot

# Copy all project files here
```

### Step 2: Install Dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Step 3: Configuration

1. **Get Telegram API Credentials**
   - Go to https://my.telegram.org/apps
   - Create a new application
   - Note your `api_id` and `api_hash`

2. **Get Anthropic API Key**
   - Go to https://console.anthropic.com/
   - Create an API key

3. **Setup Environment Variables**
   ```bash
   # Copy the example file
   cp .env.example .env
   
   # Edit .env with your credentials
   nano .env  # or use any text editor
   ```

4. **Configure Settings**
   - Edit `config.yaml` to adjust:
     - Risk parameters (lot sizes, max trades)
     - LLM model settings
     - MT5 settings (magic number, slippage)
     - Logging preferences

## Usage

### Starting the Bot

```bash
python main.py
```

On first run, you'll be prompted for:
1. Telegram login (phone number + verification code)
2. MT5 login (account number, password, server)
3. Group selection (choose which Telegram group to monitor)

### REPL Commands

Once running, you can use these commands:

- `status` - Show active trades
- `balance` - Display MT5 account balance
- `positions` - Show current open positions
- `close <ticket>` - Manually close a trade
- `trades` - Show trade history
- `pause` - Pause message processing
- `resume` - Resume message processing
- `help` - Show all available commands
- `exit` - Gracefully shutdown the bot

### Example Signal Formats

The bot can interpret signals like:

```
EURUSD BUY at 1.0850
SL: 1.0800
TP: 1.0950
```

```
SELL GBPUSD @ 1.2650, SL 1.2700, TP 1.2550
```

```
Gold (XAUUSD) LONG
Entry: 1950
Stop: 1945
Target: 1965
```

Follow-up messages:
```
Move SL to breakeven on EUR trade
```

```
Close 50% of EURUSD position
```

## Configuration

### Risk Management

Edit `config.yaml` to adjust risk parameters:

```yaml
risk:
  max_lot_size: 1.0          # Maximum lot per trade
  min_lot_size: 0.01         # Minimum lot size
  default_lot_size: 0.1      # Default if not specified
  max_open_trades: 5         # Max concurrent trades
  max_daily_trades: 10       # Max trades per day
```

### LLM Settings

Adjust AI interpretation:

```yaml
llm:
  model: "claude-sonnet-4-20250514"
  temperature: 0.1           # Lower = more consistent
  max_tokens: 2000
```

## Safety Features

- ✅ Requires explicit SL and TP for all trades
- ✅ Validates lot sizes against configured limits
- ✅ Checks risk-reward ratios
- ✅ Maximum concurrent trades limit
- ✅ Comprehensive logging for audit trail
- ✅ Demo account support for testing

## Logging

Logs are stored in the `logs/` directory:

- `trading_bot.log` - General application logs
- `trades.log` - Trade-specific events

## Data Persistence

Trade data is stored in `data/trades.json` and includes:
- Trade history
- Current positions
- Signal details
- Execution results

## Troubleshooting

### MT5 Connection Issues

- Ensure MT5 terminal is running
- Check that you're logged into MT5 manually first
- Verify server name matches your broker

### Telegram Connection Issues

- Verify API credentials in `.env`
- Check phone number format (+country_code)
- Ensure you have access to the group

### Signal Not Detected

- Check LLM interpretation in logs
- Verify signal format matches examples
- Review `config.yaml` prompts

## Development

### Testing

Always test with a demo account first:

1. Set `ENVIRONMENT=development` in `.env`
2. Use MT5 demo account credentials
3. Start with small lot sizes (0.01)

### Adding Custom Logic

- Modify `llm.py` for different signal formats
- Adjust `trade_manager.py` for custom tracking
- Extend `main.py` REPL for additional commands

## Warning

⚠️ **Trading carries significant risk. This bot is provided as-is without any guarantees. Always:**
- Test thoroughly on demo accounts
- Start with small position sizes
- Monitor the bot actively
- Have proper risk management
- Never risk more than you can afford to lose

## License

MIT License - Use at your own risk

## Support

For issues or questions:
- Check logs in `logs/` directory
- Review configuration in `config.yaml`
- Verify credentials in `.env`

---

**Disclaimer**: This software is for educational purposes. Trading financial instruments carries risk. Past performance does not guarantee future results.
