# Quick Start Guide

Get your Telegram Trading Bot running in 5 minutes!

## Prerequisites Checklist

Before starting, make sure you have:

- [ ] Python 3.9+ installed
- [ ] MetaTrader 5 terminal installed (Windows only)
- [ ] Telegram account
- [ ] Anthropic API key ([Get one here](https://console.anthropic.com/))
- [ ] Telegram API credentials ([Get here](https://my.telegram.org/apps))
- [ ] MT5 demo/live account credentials

## Step 1: Install Dependencies

```bash
# Navigate to project directory
cd telegram_trading_bot

# Install required packages
pip install -r requirements.txt
```

**Note**: If you get errors on Windows, you might need to install Microsoft C++ Build Tools.

## Step 2: Setup Environment Variables

1. Copy the example file:
   ```bash
   copy .env.example .env      # Windows
   cp .env.example .env        # Linux/Mac
   ```

2. Edit `.env` and fill in your credentials:
   ```env
   # Telegram API (from https://my.telegram.org/apps)
   TELEGRAM_API_ID=12345678
   TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
   TELEGRAM_PHONE=+1234567890
   
   # Anthropic API (from https://console.anthropic.com/)
   ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx
   
   # MT5 Credentials (optional here, can be entered at runtime)
   MT5_ACCOUNT=12345678
   MT5_PASSWORD=YourPassword
   MT5_SERVER=YourBroker-Demo
   
   # Environment
   ENVIRONMENT=development
   ```

### Getting Telegram API Credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Click "Create Application"
4. Fill in the form:
   - App title: TradingBot
   - Short name: tradingbot
   - Platform: Other
5. Copy your `api_id` and `api_hash`

### Getting Anthropic API Key

1. Go to https://console.anthropic.com/
2. Sign up or log in
3. Go to API Keys section
4. Create a new API key
5. Copy the key (starts with `sk-ant-`)

## Step 3: Configure Settings (Optional)

Edit `config.yaml` to customize:

- **Risk parameters**: Max lot size, max trades, etc.
- **LLM settings**: Model, temperature, prompts
- **MT5 settings**: Magic number, slippage
- **Logging**: Log levels, file paths

**For testing, keep defaults - they're safe!**

## Step 4: Prepare MT5

1. **Open MetaTrader 5 terminal**
2. **Log in to your account** (demo recommended for testing)
3. **Keep MT5 running** (bot needs it to be open)
4. **Verify you can see charts** and account info

**Important**: The bot cannot connect to MT5 if the terminal is closed!

## Step 5: Run the Bot

```bash
python main.py
```

### What Happens Next:

1. **Trade Manager initializes** - Shows count of existing trades
2. **LLM initializes** - Confirms Claude model is ready
3. **Telegram connection** - You might need to:
   - Enter phone number (if not in .env)
   - Enter verification code sent to Telegram
   - Enter 2FA password (if enabled)
4. **Group selection** - Choose which Telegram group to monitor
5. **MT5 connection** - Enter credentials if not in .env
6. **Bot starts listening** - Ready to receive signals!

### First-Time Telegram Login

When you run the bot for the first time:

```
[3/4] Connecting to Telegram...
Telegram API ID: [enter if not in .env]
Telegram API Hash: [enter if not in .env]
Phone number: [enter with country code, e.g., +1234567890]

Please enter the code sent to +1234567890:
Code: 12345

✓ Connected to Telegram

Fetching your chats/groups...

Found 15 groups/channels:

  1. [Supergroup] Crypto Trading Signals
  2. [Group] Forex Daily Tips
  3. [Channel] Premium Signals
  ...

Select group to monitor (1-15): 2

✓ Selected: Forex Daily Tips
```

## Step 6: Using the REPL

Once the bot is running, you'll see:

```
TradingBot>
```

Try these commands:

```bash
# Show help
help

# Check bot status
status

# View account balance
balance

# See active positions
positions

# View trading stats
stats

# Pause message processing
pause

# Resume processing
resume

# Exit the bot
exit
```

## Testing the Bot

### Send a Test Signal

In your selected Telegram group, send a test message:

```
EURUSD BUY at 1.0850
SL: 1.0800
TP: 1.0950
```

### Expected Output:

```
[14:23:45] New message from SignalProvider:
  EURUSD BUY at 1.0850...
  Analyzing with LLM...

  📊 NEW SIGNAL DETECTED
  Pair: EURUSD
  Action: BUY
  Entry: 1.0850
  SL: 1.0800 | TP: 1.0950
  Confidence: 95%
  Reasoning: Clear trading signal with all required parameters
  Risk-Reward Ratio: 2.00

  ⚡ EXECUTING TRADE...
  ✓ TRADE EXECUTED
  Ticket: 123456
  Trade ID: a1b2c3d4...

==================================================
  BUY EURUSD
  Entry: 1.0850 | SL: 1.08 | TP: 1.095
  Lot Size: 0.1
==================================================
```

### Test a Modification:

```
Move SL to breakeven on EUR trade
```

### Test a Close:

```
Close EURUSD position
```

## Common Issues & Solutions

### Issue: "ModuleNotFoundError: No module named 'MetaTrader5'"

**Solution**: MT5 package only works on Windows. If you're on Linux/Mac:
- Use a Windows VM
- Or modify code to use MT5 Web API
- Or test other components separately

### Issue: "MT5 initialization failed"

**Solutions**:
1. Make sure MT5 terminal is **open and logged in**
2. Try restarting MT5 terminal
3. Check if you're using the correct server name
4. Verify account credentials

### Issue: "Failed to connect to Telegram"

**Solutions**:
1. Check internet connection
2. Verify API credentials in `.env`
3. Make sure phone number includes country code (e.g., +1)
4. Try deleting `trading_bot_session.session` file and reconnecting

### Issue: "ANTHROPIC_API_KEY not found"

**Solutions**:
1. Check `.env` file exists in the same folder as `main.py`
2. Verify the key is correct (should start with `sk-ant-`)
3. Make sure there are no spaces around the `=` sign
4. Try setting it directly: `export ANTHROPIC_API_KEY=sk-ant-...` (Linux/Mac)

### Issue: "No trading signal detected" for valid signals

**Solutions**:
1. Check `config.yaml` - the LLM prompt might need adjustment
2. Review logs in `logs/trading_bot.log`
3. The signal format might be unusual - check LLM reasoning
4. Increase LLM temperature slightly in config (e.g., 0.2)

### Issue: Bot not processing new messages

**Solutions**:
1. Check if bot is paused - type `resume` in REPL
2. Verify you're in the correct group
3. Check internet connection
4. Restart the bot

## Safety Tips

### Before Going Live:

1. ✅ **Test thoroughly on demo account** (minimum 1 week)
2. ✅ **Start with minimum lot size** (0.01)
3. ✅ **Set conservative risk limits** in config.yaml
4. ✅ **Monitor actively** for first few days
5. ✅ **Have emergency stop** - keep MT5 open to close manually
6. ✅ **Review all trades** in REPL before end of day

### Risk Management Checklist:

- [ ] Max lot size set appropriately (default: 1.0)
- [ ] Max open trades limited (default: 5)
- [ ] Minimum R:R ratio configured (default: 1.0)
- [ ] Stop loss required (default: true)
- [ ] Demo account being used for testing

## Next Steps

### After successful testing:

1. **Review trade logs** in `logs/trades.log`
2. **Check statistics** with `stats` command
3. **Analyze bot decisions** - was signal interpretation accurate?
4. **Adjust risk parameters** in config.yaml if needed
5. **Consider adding notifications** (email/SMS when trade executed)

### Customization Ideas:

- Modify LLM prompts in `config.yaml` for your signal provider's style
- Adjust risk parameters based on your trading strategy
- Add additional REPL commands in `main.py`
- Implement trade journaling features
- Add performance metrics and reporting

## Getting Help

### Check logs first:

```bash
# Application logs
tail -f logs/trading_bot.log

# Trade-specific logs
tail -f logs/trades.log
```

### Debug mode:

In `config.yaml`, change:
```yaml
logging:
  level: "DEBUG"  # Was "INFO"
```

Then restart the bot to see detailed logs.

## Stopping the Bot

**Graceful shutdown:**

```
TradingBot> exit
```

This will:
1. Stop listening to Telegram
2. Save all trades
3. Disconnect from MT5
4. Close cleanly

**Emergency stop:**

Press `Ctrl+C` twice, then manually close positions in MT5 if needed.

---

## You're Ready! 🚀

Start the bot with:

```bash
python main.py
```

Monitor carefully, trade safely, and good luck!

For issues or questions, check:
- `logs/trading_bot.log` for errors
- `README.md` for detailed documentation
- `config.yaml` comments for settings explanations
