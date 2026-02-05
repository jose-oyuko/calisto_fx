"""
Test script to check if MT5 supports real-time events for TP monitoring

Run this script while you have an open position to test different monitoring methods.
"""

import MetaTrader5 as mt5
import time
from datetime import datetime


def test_tick_subscription():
    """Test 1: Check if tick subscription works"""
    print("\n" + "="*70)
    print("TEST 1: Tick Subscription (Real-time price updates)")
    print("="*70)
    
    symbol = "XAUUSD"
    
    # Subscribe to ticks
    if not mt5.symbol_select(symbol, True):
        print(f"❌ Failed to select {symbol}")
        return False
    
    print(f"✓ Subscribed to {symbol} ticks")
    print("Listening for 10 seconds...")
    
    start_time = time.time()
    tick_count = 0
    last_price = None
    
    while time.time() - start_time < 10:
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            if last_price != tick.bid:
                tick_count += 1
                last_price = tick.bid
                timestamp = datetime.fromtimestamp(tick.time).strftime('%H:%M:%S')
                print(f"  [{timestamp}] Bid: {tick.bid}, Ask: {tick.ask}")
        time.sleep(0.1)  # Check every 100ms
    
    print(f"\n✓ Received {tick_count} tick updates in 10 seconds")
    
    if tick_count > 0:
        print("✅ RESULT: Real-time ticks work!")
        return True
    else:
        print("❌ RESULT: No ticks received - real-time may not work")
        return False


def test_position_monitoring():
    """Test 2: Check if we can monitor position changes"""
    print("\n" + "="*70)
    print("TEST 2: Position Monitoring")
    print("="*70)
    
    positions = mt5.positions_get()
    
    if not positions or len(positions) == 0:
        print("⚠ No open positions found")
        print("💡 Please open a test position and run this test again")
        return None
    
    position = positions[0]
    print(f"Monitoring position: {position.symbol} (Ticket: {position.ticket})")
    print(f"Entry: {position.price_open}, Current: {position.price_current}")
    print(f"SL: {position.sl}, TP: {position.tp}")
    print("\nWatching for changes for 10 seconds...")
    
    last_price = position.price_current
    updates = 0
    
    for i in range(10):
        time.sleep(1)
        positions = mt5.positions_get(ticket=position.ticket)
        
        if not positions or len(positions) == 0:
            print(f"  [{i+1}s] Position closed!")
            return True
        
        current = positions[0]
        if current.price_current != last_price:
            updates += 1
            print(f"  [{i+1}s] Price update: {last_price} → {current.price_current}")
            last_price = current.price_current
    
    print(f"\n✓ Detected {updates} price updates")
    
    if updates > 0:
        print("✅ RESULT: Can monitor position updates in real-time")
        return True
    else:
        print("⚠ RESULT: No price updates detected (market may be slow)")
        return None


def test_history_deals():
    """Test 3: Check if we can detect when positions close"""
    print("\n" + "="*70)
    print("TEST 3: Deal Detection (for TP hits)")
    print("="*70)
    
    from datetime import datetime, timedelta
    
    # Get deals from last hour
    now = datetime.now()
    from_date = now - timedelta(hours=1)
    
    deals = mt5.history_deals_get(from_date, now)
    
    if deals is None:
        print("❌ Failed to get deal history")
        return False
    
    print(f"✓ Found {len(deals)} deals in last hour")
    
    if len(deals) > 0:
        print("\nRecent deals:")
        for deal in deals[-5:]:  # Show last 5
            deal_type = "BUY" if deal.type == 0 else "SELL"
            entry_or_exit = "ENTRY" if deal.entry == 0 else "EXIT"
            timestamp = datetime.fromtimestamp(deal.time).strftime('%H:%M:%S')
            print(f"  [{timestamp}] {deal_type} {entry_or_exit} {deal.symbol} @ {deal.price}")
        
        print("\n✅ RESULT: Can detect closed positions via deal history")
        return True
    else:
        print("⚠ No recent deals - can't test detection")
        return None


def test_polling_speed():
    """Test 4: Measure polling performance"""
    print("\n" + "="*70)
    print("TEST 4: Polling Speed Test")
    print("="*70)
    
    symbol = "XAUUSD"
    iterations = 100
    
    print(f"Testing {iterations} price checks...")
    
    start = time.time()
    for _ in range(iterations):
        tick = mt5.symbol_info_tick(symbol)
    elapsed = time.time() - start
    
    avg_time = (elapsed / iterations) * 1000  # Convert to ms
    calls_per_second = iterations / elapsed
    
    print(f"✓ Average time per call: {avg_time:.2f}ms")
    print(f"✓ Can make ~{calls_per_second:.0f} calls/second")
    
    if avg_time < 50:
        print("✅ RESULT: Fast enough for 1-2 second monitoring")
        interval = "1-2 seconds"
    elif avg_time < 100:
        print("✅ RESULT: Good for 5 second monitoring")
        interval = "5 seconds"
    else:
        print("⚠ RESULT: Recommend 10+ second monitoring")
        interval = "10+ seconds"
    
    return interval


def main():
    print("\n" + "="*70)
    print("MT5 REAL-TIME EVENT TESTING")
    print("="*70)
    print("\nThis will test if your MT5 broker supports real-time monitoring")
    print("for automatic TP partial closes.\n")
    
    # Initialize MT5
    if not mt5.initialize():
        print("❌ Failed to initialize MT5")
        print("Make sure MT5 is running and you're logged in")
        return
    
    print("✓ MT5 initialized")
    
    # Get account info
    account_info = mt5.account_info()
    if account_info:
        print(f"✓ Connected to: {account_info.server}")
        print(f"  Account: {account_info.login}")
        print(f"  Balance: {account_info.balance} {account_info.currency}")
    
    # Run tests
    results = {}
    
    results['ticks'] = test_tick_subscription()
    results['positions'] = test_position_monitoring()
    results['deals'] = test_history_deals()
    results['speed'] = test_polling_speed()
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    print(f"\n1. Real-time ticks: {'✅ YES' if results['ticks'] else '❌ NO'}")
    print(f"2. Position updates: {'✅ YES' if results['positions'] else '⚠ UNKNOWN' if results['positions'] is None else '❌ NO'}")
    print(f"3. Deal detection: {'✅ YES' if results['deals'] else '⚠ UNKNOWN' if results['deals'] is None else '❌ NO'}")
    print(f"4. Recommended interval: {results['speed']}")
    
    print("\n" + "="*70)
    print("RECOMMENDATION")
    print("="*70)
    
    if results['ticks'] and results['positions']:
        print("\n✅ Your broker supports REAL-TIME monitoring!")
        print("\nBest approach:")
        print("  • Use event-based monitoring for instant TP detection")
        print("  • Check every 1-2 seconds for maximum responsiveness")
        print("  • Can reliably catch all TP levels")
    elif results['ticks']:
        print("\n✅ Your broker has real-time ticks")
        print("\nGood approach:")
        print("  • Use tick monitoring with 2-5 second checks")
        print("  • Will catch most TP levels accurately")
    else:
        print("\n⚠ Limited real-time support")
        print("\nRecommended approach:")
        print("  • Use polling every 5-10 seconds")
        print("  • Set MT5 TP to last level as safety net")
        print("  • This is still reliable for your use case")
    
    # Cleanup
    mt5.shutdown()
    print("\n✓ Tests complete!")


if __name__ == "__main__":
    main()
