# Follow-Up Signals - How They Work

## Overview

The bot can handle follow-up messages that modify or close existing trades. Here's what's supported and how it works.

## Supported Follow-Up Actions

### 1. Partial Close (Take Profits)
**Messages like:**
- "Secured 30% partials"
- "Close 50% of position"
- "Take 25% profit"

**What happens:**
1. LLM detects it's a CLOSE signal with percentage
2. Bot finds the matching active trade  
3. Calculates volume to close (e.g., 30% of 0.1 = 0.03 lots)
4. Closes that portion in MT5
5. Updates remaining lot size in trade_manager

**Expected output:**
```
🚪 CLOSE SIGNAL DETECTED
Action: partial_close
Close %: 30.0%
Matched to: BUY XAUUSD (Ticket: 123456)
Closing 30% = 0.03 lots

⚡ CLOSING POSITION...
✓ POSITION CLOSED
Close Price: 4710.50
Trade partially closed - 0.07 lots remaining
```

### 2. Full Close
**Messages like:**
- "Position closed"
- "Close all"
- "Exit the trade"
- "Take profits and close"

**What happens:**
1. LLM detects CLOSE signal with 100%
2. Bot finds matching trade
3. Closes entire position
4. Marks trade as closed in database

### 3. Move SL to Breakeven
**Messages like:**
- "Move SL to breakeven"
- "BE now"
- "Secure breakeven"

**What happens:**
1. LLM detects MODIFY signal
2. Bot identifies this means new_sl = entry_price
3. Modifies position in MT5
4. Updates trade record

**Expected output:**
```
🔧 MODIFY SIGNAL DETECTED
Action: modify_sl
Matched to: BUY XAUUSD (Ticket: 123456)
Moving SL to breakeven: 4695.50

⚡ MODIFYING POSITION...
✓ POSITION MODIFIED
New SL: 4695.50
```

### 4. Adjust SL/TP
**Messages like:**
- "Move SL to 4700"
- "Adjust TP to 4750"
- "New stop at 4680"

**What happens:**
1. LLM extracts new SL or TP value
2. Bot modifies position in MT5
3. Records modification in trade history

## How Trade Matching Works

The bot matches follow-up messages to trades by:

1. **Explicit pair mention**: "Close EURUSD" → finds EURUSD trade
2. **Recent context**: If only 1 active trade, assumes it's that one
3. **Order of signals**: "First trade" refers to oldest active trade

**Example matching:**
```
Active trades:
1. BUY XAUUSD @ 4695.50 (10 minutes old)
2. SELL EURUSD @ 1.0850 (5 minutes old)

Message: "Close 30% partials"
→ Matches EURUSD (most recent)

Message: "Move SL to BE on gold"
→ Matches XAUUSD (mentioned "gold")
```

## Common Issues & Solutions

### Issue: "Position not found"

**What it means:**
The position was already closed (by TP/SL or manually)

**What the bot does:**
- Checks MT5 history to confirm it's closed
- Updates database to mark as closed
- Shows the close price from history

**Output:**
```
⚠ CLOSE NOTICE
Position 123456 not found (may be already closed or invalid ticket)
ℹ Updating trade status to closed in database
Trade marked as closed
```

**This is NOT an error** - it's expected when signals come after auto-close.

### Issue: Partial close of wrong amount

**Cause:** LLM might interpret percentages differently

**Solution:** 
- Check `status` command to see current lot size
- If wrong, use manual `close <ticket>` command

### Issue: Can't find trade to modify

**Causes:**
1. Trade was already closed
2. Multiple active trades and reference unclear
3. Bot didn't track the original trade

**Solutions:**
1. Check `status` to see active trades
2. Use `close <ticket>` for manual control
3. Be more specific: "Close EURUSD" not just "Close"

## Best Practices

### For Signal Providers

**Good messages:**
```
✓ "Close 50% of EURUSD position"
✓ "Move XAUUSD SL to 4700"
✓ "Secured 30% partials on gold"
✓ "Close all EUR trades"
```

**Ambiguous messages:**
```
✗ "Close some"
✗ "Move it"
✗ "BE" (without context)
✗ "Done" (too vague)
```

### For Bot Users

1. **Monitor active trades**: Use `status` regularly
2. **Verify closes**: Check MT5 after close signals
3. **Manual override**: Use REPL commands if auto-handling fails
4. **Keep records**: Trade history in `data/trades.json`

## Technical Details

### Trade Lifecycle

```
NEW SIGNAL
    ↓
[PENDING] ──→ [ACTIVE] (when filled)
    ↓
Partial Close → [ACTIVE] (reduced lot size)
    ↓
Full Close → [CLOSED]
```

### Modification History

Each modification is recorded:
```json
{
  "type": "partial_close",
  "timestamp": "2026-02-02T14:44:15",
  "details": {
    "percent": 30,
    "volume": 0.03,
    "price": 4710.50,
    "remaining_lots": 0.07
  }
}
```

### Volume Calculations

Partial close example:
- Original: 0.10 lots
- Close 30%: 0.10 × 0.30 = 0.03 lots
- Remaining: 0.10 - 0.03 = 0.07 lots

The bot normalizes to broker's volume step (usually 0.01).

## Debugging Follow-Up Signals

If a follow-up signal isn't working:

1. **Check logs**: `logs/trading_bot.log`
2. **Verify LLM interpretation**: Look for "Detected X signal"
3. **Check active trades**: `status` command
4. **Verify MT5 positions**: `positions` command
5. **Compare tickets**: Ensure trade_manager matches MT5

## Summary

The bot handles follow-up signals well, with smart matching and graceful handling of already-closed positions. The "position not found" message is usually EXPECTED behavior when TP/SL already closed the trade.

Key points:
- ✅ Partial closes work and update lot size
- ✅ Full closes mark trade as closed
- ✅ SL/TP modifications update both MT5 and database
- ✅ Already-closed positions handled gracefully
- ✅ All modifications logged for audit trail

