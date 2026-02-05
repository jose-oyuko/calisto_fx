"""
Main Trading Bot - Orchestrates Telegram, LLM, and MT5 integration with REPL interface
"""

import os
import sys
import threading
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from getpass import getpass

# Fix for Windows Unicode/emoji handling in console
if sys.platform == 'win32':
    # Try to set UTF-8 mode for Windows console
    try:
        # For Python 3.7+
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass  # Silently fail if not supported
    
    # Set environment variable for UTF-8
    os.environ['PYTHONIOENCODING'] = 'utf-8'

# Import our modules
from utils import Config, setup_logging, colorize, print_trade_summary, validate_lot_size, calculate_risk_reward
from trade_manager import TradeManager, TradeStatus
from mt5 import MT5Client
from llm import LLMInterpreter, NewSignal, ModifySignal, CloseSignal, NoSignal, MultiActionSignal
from telegram import TelegramClient


class TradingBot:
    """
    Main trading bot orchestrator that coordinates all components
    """
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize the trading bot
        
        Args:
            config_path: Path to configuration file
        """
        # Load configuration
        self.config = Config(config_path)
        
        # Setup logging
        self.logger = setup_logging(self.config)
        
        # Initialize components (will be set up during startup)
        self.telegram_client: Optional[TelegramClient] = None
        self.mt5_client: Optional[MT5Client] = None
        self.llm_interpreter: Optional[LLMInterpreter] = None
        self.trade_manager: Optional[TradeManager] = None
        
        # State
        self.is_running = False
        self.is_paused = False
        self.selected_chat_id: Optional[int] = None
        
        # Conversational context
        self.recent_messages = []  # Store last 5 messages for context
        self.max_context_messages = 5
        self.last_executed_pair: Optional[str] = None
        self.last_signal_time: Optional[str] = None
        
        # Message correlation for merging signals
        self.last_signal_timestamp: Optional[datetime] = None
        self.last_signal_pair: Optional[str] = None
        self.last_signal_action: Optional[str] = None
        self.last_signal_had_sltp: bool = True
        
        self.logger.info("Trading Bot initialized")
    
    def startup(self) -> bool:
        """
        Startup sequence: connect to Telegram and MT5
        
        Returns:
            True if successful, False otherwise
        """
        print("\n" + "="*70)
        print("  TELEGRAM TRADING BOT - Startup")
        print("="*70)
        
        # Initialize trade manager
        print("\n[1/4] Initializing Trade Manager...")
        trades_file = self.config.get('app.trades_file', 'data/trades.json')
        self.trade_manager = TradeManager(storage_file=trades_file)
        
        # Load existing trades
        active_count = len(self.trade_manager.get_active_trades())
        print(f"✓ Trade Manager initialized ({active_count} active trades)")
        
        # Initialize LLM
        print("\n[2/4] Initializing LLM Interpreter...")
        if not self.config.anthropic_api_key:
            print("✗ ANTHROPIC_API_KEY not found in environment")
            return False
        
        self.llm_interpreter = LLMInterpreter(
            api_key=self.config.anthropic_api_key,
            model=self.config.get('llm.model'),
            temperature=self.config.get('llm.temperature'),
            max_tokens=self.config.get('llm.max_tokens')
        )
        print(f"✓ LLM initialized (model: {self.config.get('llm.model')})")
        
        # Connect to Telegram
        print("\n[3/4] Connecting to Telegram...")
        if not self._setup_telegram():
            return False
        
        # Connect to MT5
        print("\n[4/4] Connecting to MetaTrader 5...")
        if not self._setup_mt5():
            return False
        
        print("\n" + "="*70)
        print("  ✓ All systems connected and ready!")
        print("="*70 + "\n")
        
        return True
    
    def _setup_telegram(self) -> bool:
        """Setup Telegram connection and select group"""
        # Get credentials from config
        api_id = self.config.telegram_api_id
        api_hash = self.config.telegram_api_hash
        phone = self.config.telegram_phone
        
        # Prompt for credentials if not in environment
        if not api_id:
            api_id = input("Telegram API ID: ")
        if not api_hash:
            api_hash = input("Telegram API Hash: ")
        if not phone:
            phone = input("Phone number (with country code, e.g., +1234567890): ")
        
        # Create client
        try:
            self.telegram_client = TelegramClient(api_id, api_hash, phone)
        except Exception as e:
            print(f"✗ Failed to create Telegram client: {e}")
            return False
        
        # Connect
        if not self.telegram_client.connect():
            print("✗ Failed to connect to Telegram")
            return False
        
        print("✓ Connected to Telegram")
        
        # Select group
        if not self._select_group():
            return False
        
        return True
    
    def _select_group(self) -> bool:
        """Display groups and let user select one"""
        print("\nFetching your chats/groups...")
        dialogs = self.telegram_client.get_dialogs()
        
        if not dialogs:
            print("✗ No chats found")
            return False
        
        # Filter to show only groups and channels
        groups = [d for d in dialogs if d['type'] in ['Group', 'Supergroup', 'Channel']]
        
        if not groups:
            print("✗ No groups found")
            return False
        
        print(f"\nFound {len(groups)} groups/channels:\n")
        
        # Display groups
        for i, group in enumerate(groups, 1):
            print(f"  {i}. [{group['type']}] {group['title']}")
        
        # Get selection
        while True:
            try:
                selection = input(f"\nSelect group to monitor (1-{len(groups)}): ")
                index = int(selection) - 1
                
                if 0 <= index < len(groups):
                    selected_group = groups[index]
                    self.selected_chat_id = selected_group['id']
                    print(f"\n✓ Selected: {selected_group['title']}")
                    return True
                else:
                    print(f"Please enter a number between 1 and {len(groups)}")
            except ValueError:
                print("Please enter a valid number")
            except KeyboardInterrupt:
                print("\n\nSetup cancelled")
                return False
    
    def _setup_mt5(self) -> bool:
        """Setup MT5 connection"""
        # Get credentials
        account = self.config.mt5_account
        password = self.config.mt5_password
        server = self.config.mt5_server
        
        # Prompt for credentials if not in environment
        if not account:
            account = input("MT5 Account Number: ")
        if not password:
            password = getpass("MT5 Password: ")
        if not server:
            server = input("MT5 Server: ")
        
        # Create client
        magic_number = self.config.get('mt5.magic_number', 234567)
        self.mt5_client = MT5Client(magic_number=magic_number)
        
        # Login
        try:
            account = int(account)
        except ValueError:
            print("✗ Invalid account number")
            return False
        
        if not self.mt5_client.login(account, password, server):
            print("✗ Failed to login to MT5")
            return False
        
        # Display account info
        account_info = self.mt5_client.get_account_info()
        if account_info:
            print(f"✓ Connected to MT5")
            print(f"  Balance: {account_info['balance']} {account_info['currency']}")
            print(f"  Equity: {account_info['equity']} {account_info['currency']}")
            print(f"  Server: {account_info['server']}")
        
        return True
    
    def start_listening(self):
        """Start listening to Telegram messages"""
        if not self.telegram_client or not self.selected_chat_id:
            self.logger.error("Telegram not properly configured")
            return
        
        # Set message callback
        self.telegram_client.set_message_callback(self.process_message)
        
        # Start listening
        self.telegram_client.start_listening(self.selected_chat_id)
        
        # Start TP monitoring thread
        self.start_tp_monitor()
        
        self.is_running = True
        self.logger.info("Started listening to messages")
    
    def process_message(self, message_data: Dict[str, Any]):
        """
        Main message processing pipeline
        
        Args:
            message_data: Dictionary containing message information
        """
        if self.is_paused:
            return
        
        try:
            message_text = message_data.get('text', '')
            message_id = message_data.get('message_id')
            sender_name = message_data.get('sender_name', 'Unknown')
            
            # Display incoming message (sanitize for Windows console)
            from utils import sanitize_for_logging
            timestamp = datetime.now().strftime("%H:%M:%S")
            safe_message = sanitize_for_logging(message_text, max_length=100)
            print(f"\n[{timestamp}] New message from {sender_name}:")
            print(f"  {safe_message}")
            
            # Add to recent messages for context
            self.recent_messages.append({
                'timestamp': timestamp,
                'sender': sender_name,
                'text': message_text
            })
            if len(self.recent_messages) > self.max_context_messages:
                self.recent_messages.pop(0)  # Remove oldest
            
            # Build context from recent messages (exclude current one)
            recent_context = []
            for msg in self.recent_messages[:-1]:  # All except current
                recent_context.append(f"[{msg['timestamp']}] {msg['sender']}: {msg['text']}")
            
            # Get active trades context
            active_trades = self.trade_manager.get_context_for_llm()
            
            # Interpret message with LLM (with context)
            print("  Analyzing with LLM...")
            system_prompt = self.config.get('llm.system_prompt')
            signal = self.llm_interpreter.interpret_message(
                message_text,
                active_trades=active_trades,
                system_prompt=system_prompt,
                recent_messages=recent_context,
                last_trade_pair=self.last_executed_pair
            )
            
            if signal is None:
                print("  ⚠ Failed to interpret message")
                return
            
            # Handle different signal types
            if isinstance(signal, NewSignal):
                self._handle_new_signal(signal, message_text, message_id)
            
            elif isinstance(signal, MultiActionSignal):
                # Handle multi-action signals (e.g., "SET BE & TAKE PARTIALS")
                self._handle_multi_action_signal(signal, message_text)
            
            elif isinstance(signal, ModifySignal):
                # Sync with MT5 before modifying
                changes = self.sync_trades_with_mt5()
                if changes > 0:
                    print(f"  ℹ Synced {changes} trades with MT5")
                self._handle_modify_signal(signal, message_text)
            
            elif isinstance(signal, CloseSignal):
                # Sync with MT5 before closing
                changes = self.sync_trades_with_mt5()
                if changes > 0:
                    print(f"  ℹ Synced {changes} trades with MT5")
                self._handle_close_signal(signal, message_text)
            
            elif isinstance(signal, NoSignal):
                print(f"  ℹ Not a trading signal: {signal.reasoning}")
            
        except Exception as e:
            self.logger.error(f"Error processing message: {e}", exc_info=True)
            print(f"  ✗ Error: {e}")
    
    def _handle_new_signal(self, signal: NewSignal, original_message: str, message_id: int):
        """Handle new trading signal"""
        print(f"\n  {colorize('📊 NEW SIGNAL DETECTED', 'cyan')}")
        
        # Default to XAUUSD if pair missing or generic
        if not signal.pair or signal.pair.upper() in ['GOLD', 'XAU', '']:
            signal.pair = 'XAUUSD'
            print(f"  ℹ No specific pair - defaulting to XAUUSD (Gold)")
        
        # Check for message correlation (BUY NOW followed by BUY RANGE)
        should_modify_existing = False
        existing_trade = None
        
        if self.last_signal_timestamp:
            time_diff = (datetime.now() - self.last_signal_timestamp).total_seconds()
            
            if (time_diff < 60 and  # Within 60 seconds
                self.last_signal_pair == signal.pair and
                self.last_signal_action == signal.action and
                not self.last_signal_had_sltp):  # Last signal had no SL/TP
                
                # This is likely a completion of previous signal
                print(f"  ℹ Detected potential signal completion ({time_diff:.0f}s after previous)")
                active_trades = self.trade_manager.get_active_trades()
                
                if active_trades:
                    # Find most recent matching trade
                    for trade in reversed(active_trades):
                        if trade.pair == signal.pair and trade.action == signal.action:
                            if not trade.stop_loss or trade.stop_loss == 0:
                                should_modify_existing = True
                                existing_trade = trade
                                break
        
        if should_modify_existing and existing_trade:
            # MODIFY the existing trade instead of creating new one
            print(f"  {colorize('🔄 MODIFYING EXISTING TRADE', 'yellow')}")
            print(f"  Ticket: {existing_trade.mt5_ticket}")
            
            # Store signal entry from the range
            existing_trade.signal_entry = signal.entry_price
            existing_trade.actual_entry = existing_trade.entry_price  # Keep original
            
            # Extract and store TP levels
            if signal.tp_levels and len(signal.tp_levels) > 0:
                existing_trade.tp_levels = signal.tp_levels
                existing_trade.take_profit = signal.tp_levels[0]  # Set first TP
                print(f"  TP levels: {signal.tp_levels}")
            elif signal.take_profit:
                existing_trade.take_profit = signal.take_profit
            
            # Set SL
            existing_trade.stop_loss = signal.stop_loss or 0
            
            # Modify in MT5
            success, message = self.mt5_client.modify_order(
                ticket=existing_trade.mt5_ticket,
                stop_loss=existing_trade.stop_loss,
                take_profit=existing_trade.take_profit
            )
            
            if success:
                print(f"  {colorize('✓ Added SL/TP to existing position', 'green')}")
                print(f"  Signal entry: {existing_trade.signal_entry}")
                print(f"  Actual entry: {existing_trade.actual_entry}")
                print(f"  SL: {existing_trade.stop_loss} | TP: {existing_trade.take_profit}")
                
                # Save updated trade
                self.trade_manager.save_trades()
                
                # Track this completion
                self.last_signal_timestamp = datetime.now()
                self.last_signal_had_sltp = True
            else:
                print(f"  ✗ Failed to modify: {message}")
            
            return  # Exit early, don't create new trade
        
        print(f"  Pair: {signal.pair}")
        print(f"  Action: {colorize(signal.action, 'green' if signal.action == 'BUY' else 'red')}")
        
        # Handle entry_price = 0 (NOW/MARKET signals)
        if signal.entry_price == 0:
            # Get current market price
            symbol_info = self.mt5_client.get_symbol_info(signal.pair)
            if symbol_info:
                market_price = symbol_info['ask'] if signal.action == 'BUY' else symbol_info['bid']
                signal.entry_price = market_price
                print(f"  Entry: MARKET (current: {market_price})")
            else:
                print(f"  ✗ Failed to get current market price for {signal.pair}")
                return
        else:
            print(f"  Entry: {signal.entry_price}")
        
        print(f"  SL: {signal.stop_loss} | TP: {signal.take_profit}")
        print(f"  Execution Type: {signal.execution_type}")
        print(f"  Confidence: {signal.confidence:.0%}")
        print(f"  Reasoning: {signal.reasoning}")
        
        # Check if SL/TP are missing
        if signal.stop_loss is None or signal.take_profit is None:
            print(f"\n  {colorize('⚠ WARNING: Trade without protection!', 'yellow')}")
            if signal.stop_loss is None:
                print(f"  ⚠ No Stop Loss specified - trade will be unprotected")
            if signal.take_profit is None:
                print(f"  ⚠ No Take Profit specified")
            print(f"  ℹ Executing anyway - you can add SL/TP in follow-up message")
            print(f"  💡 Example: 'SL 4500, TP 4600'")
            
            # Ask for confirmation in terminal (optional - can remove if you want auto-execution)
            # For now, we'll just execute with warning
        
        # Use 0 for missing SL/TP (will be ignored by MT5)
        stop_loss = signal.stop_loss or 0.0
        take_profit = signal.take_profit or 0.0
        
        # Determine lot size
        lot_size = signal.lot_size or self.config.get('risk.default_lot_size', 0.1)
        
        # Validate lot size
        is_valid, error_msg = validate_lot_size(lot_size, self.config)
        if not is_valid:
            print(f"  ✗ {error_msg}")
            return
        
        # Calculate risk-reward ratio (only if we have SL and TP)
        if stop_loss > 0 and take_profit > 0:
            rr_ratio = calculate_risk_reward(
                signal.entry_price,
                stop_loss,
                take_profit,
                signal.action
            )
            min_rr = self.config.get('risk.min_risk_reward_ratio', 1.0)
            
            print(f"  Risk-Reward Ratio: {rr_ratio:.2f}")
            
            if rr_ratio < min_rr:
                print(f"  ✗ RR ratio {rr_ratio:.2f} below minimum {min_rr}")
                print(f"  💡 Tip: You can lower 'risk.min_risk_reward_ratio' in config.yaml")
                print(f"     Current minimum: {min_rr}, Signal RR: {rr_ratio:.2f}")
                return
        else:
            print(f"  ⚠ Skipping RR ratio check (no SL/TP)")
        
        # Check max open trades
        max_trades = self.config.get('risk.max_open_trades', 5)
        active_count = len(self.trade_manager.get_active_trades())
        
        if active_count >= max_trades:
            print(f"  ✗ Maximum open trades reached ({active_count}/{max_trades})")
            return
        
        # Execute based on execution type
        print(f"\n  {colorize('⚡ EXECUTING TRADE...', 'yellow')}")
        
        success = False
        ticket = None
        message = ""
        
        if signal.execution_type == "immediate":
            # Market order execution
            success, ticket, message = self.mt5_client.place_market_order(
                symbol=signal.pair,
                order_type=signal.action,
                lot_size=lot_size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                deviation=self.config.get('mt5.deviation', 5),
                comment=self.config.get('mt5.order_comment', 'TelegramBot')
            )
            
        elif signal.execution_type == "pending":
            # Pending order execution with RANGE support
            symbol_info = self.mt5_client.get_symbol_info(signal.pair)
            
            if symbol_info is None:
                print(f"  ✗ Failed to get symbol info for {signal.pair}")
                return
            
            current_price = symbol_info['bid'] if signal.action == "SELL" else symbol_info['ask']
            
            print(f"  ℹ Current market price: {current_price}")
            print(f"  ℹ Signal entry price: {signal.entry_price}")
            print(f"  ℹ Action: {signal.action}")
            
            # Try to detect if this is a RANGE signal by checking original message
            is_range = False
            range_lower = None
            range_upper = None
            
            # Look for range patterns in original message
            import re
            range_patterns = [
                r'range[:\s]+(\d+\.?\d*)\s*[-to]+\s*(\d+\.?\d*)',
                r'zone[:\s]+(\d+\.?\d*)\s*[-to]+\s*(\d+\.?\d*)',
                r'(\d+\.?\d*)\s*[-]+\s*(\d+\.?\d*)',
            ]
            
            for pattern in range_patterns:
                match = re.search(pattern, original_message.lower())
                if match:
                    val1 = float(match.group(1))
                    val2 = float(match.group(2))
                    range_lower = min(val1, val2)
                    range_upper = max(val1, val2)
                    is_range = True
                    print(f"  ℹ Detected range: {range_lower} - {range_upper}")
                    break
            
            # Determine execution strategy
            execute_now = False
            entry_price = signal.entry_price
            pending_type = None
            
            if is_range:
                # RANGE LOGIC - Per user's specifications
                print(f"  ℹ Processing as RANGE signal")
                
                # Check if current price is within range
                if range_lower <= current_price <= range_upper:
                    # Price is INSIDE range - execute at market NOW
                    execute_now = True
                    print(f"  ℹ Price INSIDE range ({range_lower}-{range_upper}) - executing at market")
                    
                elif signal.action == "SELL":
                    # SELL RANGE logic
                    if current_price > range_upper:
                        # Price ABOVE range - use UPPER limit
                        entry_price = range_upper
                        pending_type = "SELL_STOP"
                        print(f"  ℹ SELL: Price above range - SELL_STOP at {entry_price} (upper limit)")
                    else:
                        # Price BELOW range - use LOWER limit
                        entry_price = range_lower
                        pending_type = "SELL_LIMIT"
                        print(f"  ℹ SELL: Price below range - SELL_LIMIT at {entry_price} (lower limit)")
                        
                else:  # BUY
                    # BUY RANGE logic
                    if current_price < range_lower:
                        # Price BELOW range - use LOWER limit
                        entry_price = range_lower
                        pending_type = "BUY_STOP"
                        print(f"  ℹ BUY: Price below range - BUY_STOP at {entry_price} (lower limit)")
                    else:
                        # Price ABOVE range - use UPPER limit
                        entry_price = range_upper
                        pending_type = "BUY_LIMIT"
                        print(f"  ℹ BUY: Price above range - BUY_LIMIT at {entry_price} (upper limit)")
            
            else:
                # SINGLE ENTRY PRICE logic (not a range)
                print(f"  ℹ Processing as SINGLE entry point signal")
                
                # Check if price is at entry (within 10 points)
                if abs(current_price - entry_price) < (symbol_info['point'] * 10):
                    execute_now = True
                    print(f"  ℹ Price at entry level - executing at market")
                    
                elif signal.action == "BUY":
                    if current_price < entry_price:
                        # Price below entry - wait for rise
                        pending_type = "BUY_STOP"
                        print(f"  ℹ BUY: Price below entry - BUY_STOP at {entry_price}")
                    else:
                        # Price above entry - wait for drop
                        pending_type = "BUY_LIMIT"
                        print(f"  ℹ BUY: Price above entry - BUY_LIMIT at {entry_price}")
                        
                else:  # SELL
                    if current_price > entry_price:
                        # Price above entry - wait for drop
                        pending_type = "SELL_STOP"
                        print(f"  ℹ SELL: Price above entry - SELL_STOP at {entry_price}")
                    else:
                        # Price below entry - wait for rise
                        pending_type = "SELL_LIMIT"
                        print(f"  ℹ SELL: Price below entry - SELL_LIMIT at {entry_price}")
            
            # Execute based on strategy
            if execute_now:
                success, ticket, message = self.mt5_client.place_market_order(
                    symbol=signal.pair,
                    order_type=signal.action,
                    lot_size=lot_size,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    deviation=self.config.get('mt5.deviation', 5),
                    comment=self.config.get('mt5.order_comment', 'TelegramBot')
                )
            else:
                # Place pending order
                success, ticket, message = self.mt5_client.place_pending_order(
                    symbol=signal.pair,
                    order_type=pending_type,
                    lot_size=lot_size,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    comment=self.config.get('mt5.order_comment', 'TelegramBot')
                )
        
        else:
            # Conditional/time-based not supported yet
            print(f"  ⚠ {signal.execution_type} execution not supported yet")
            print(f"  Signal logged but not executed")
            return
        
        # Handle execution result
        if success:
            print(f"  {colorize('✓ TRADE EXECUTED', 'green')}")
            print(f"  Ticket: {ticket}")
            
            # Track last executed pair for context
            self.last_executed_pair = signal.pair
            self.last_signal_time = datetime.now().isoformat()
            
            # Create trade record
            trade_data = {
                'pair': signal.pair,
                'action': signal.action,
                'entry_price': signal.entry_price,
                'actual_entry': signal.entry_price,  # Will be updated with actual fill
                'signal_entry': signal.entry_price if signal.execution_type == "pending" else None,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'tp_levels': signal.tp_levels if signal.tp_levels else [],
                'partials_taken': 0,
                'partial_history': [],
                'lot_size': lot_size,
                'mt5_ticket': ticket,
                'original_message': original_message,
                'telegram_msg_id': message_id,
                'status': TradeStatus.PENDING.value if signal.execution_type == "pending" else TradeStatus.ACTIVE.value
            }
            
            trade = self.trade_manager.add_trade(trade_data)
            
            print(f"  Trade ID: {trade.trade_id[:8]}...")
            
            # Display summary
            print_trade_summary(trade_data, color=True)
            
            # Track this signal for correlation
            self.last_signal_timestamp = datetime.now()
            self.last_signal_pair = signal.pair
            self.last_signal_action = signal.action
            self.last_signal_had_sltp = (signal.stop_loss is not None and signal.take_profit is not None)
        else:
            print(f"  {colorize('✗ EXECUTION FAILED', 'red')}")
            print(f"  {message}")
    
    def _handle_multi_action_signal(self, signal: MultiActionSignal, original_message: str):
        """
        Handle multi-action signals (e.g., "SET BE & TAKE PARTIALS")
        Executes each action in sequence
        """
        print(f"\n  {colorize('📋 MULTI-ACTION SIGNAL DETECTED', 'cyan')}")
        print(f"  Actions: {len(signal.actions)}")
        print(f"  Confidence: {signal.confidence:.0%}")
        print(f"  Reasoning: {signal.reasoning}")
        
        # Sync with MT5 once before all actions
        changes = self.sync_trades_with_mt5()
        if changes > 0:
            print(f"  ℹ Synced {changes} trades with MT5")
        
        # Check if this is a "close all" signal
        close_all_keywords = [
            'no longer in this trade',
            'position closed',
            'trade closed', 
            'close all',
            'exit all'
        ]
        is_close_all = any(keyword in original_message.lower() for keyword in close_all_keywords)
        
        if is_close_all:
            print(f"\n  {colorize('🚨 CLOSE ALL DETECTED - Closing all positions and pending orders', 'yellow')}")
            
            # Get all active trades
            active_trades = self.trade_manager.get_active_trades()
            
            # Get all pending orders from MT5
            pending_orders = self.mt5_client.get_pending_orders()
            
            total_to_close = len(active_trades) + len(pending_orders)
            
            if total_to_close == 0:
                print(f"  ℹ No active trades or pending orders to close")
                return
            
            print(f"  ℹ Found {len(active_trades)} active trades and {len(pending_orders)} pending orders")
            
            # Close all active positions
            for trade in active_trades:
                print(f"\n  Closing: {trade.action} {trade.pair} (Ticket: {trade.mt5_ticket})")
                success, close_price, message = self.mt5_client.close_order(
                    ticket=trade.mt5_ticket,
                    deviation=self.config.get('mt5.deviation', 5)
                )
                if success:
                    print(f"  ✓ Closed at {close_price}")
                    self.trade_manager.close_trade(trade.trade_id, close_price or 0, 0)
                else:
                    print(f"  ⚠ {message}")
            
            # Cancel all pending orders
            for order in pending_orders:
                print(f"\n  Canceling pending: {order['type']} {order['symbol']} @ {order['entry_price']}")
                # MT5 cancels pending orders by deleting them
                success = self.mt5_client.cancel_pending_order(order['ticket'])
                if success:
                    print(f"  ✓ Cancelled ticket {order['ticket']}")
                    # Mark as closed in DB if we're tracking it
                    for trade in self.trade_manager.trades:
                        if trade.mt5_ticket == order['ticket']:
                            self.trade_manager.close_trade(trade.trade_id, 0, 0)
                            break
                else:
                    print(f"  ⚠ Failed to cancel")
            
            print(f"\n  {colorize('✓ All positions and orders closed/cancelled', 'green')}")
            return
        
        # Execute each action in sequence (normal multi-action flow)
        for i, action_dict in enumerate(signal.actions, 1):
            action_type = action_dict.get('type')
            details = action_dict.get('details', {})
            
            print(f"\n  --- Action {i}/{len(signal.actions)}: {action_type.upper()} ---")
            
            if action_type == 'modify':
                # Create ModifySignal from details
                modify_signal = ModifySignal(
                    action_type=details.get('action_type', 'modify_sl'),
                    trade_reference=details.get('trade_reference'),
                    new_stop_loss=details.get('new_stop_loss'),
                    new_take_profit=details.get('new_take_profit'),
                    confidence=signal.confidence,
                    reasoning=f"Part of multi-action: {signal.reasoning}"
                )
                self._handle_modify_signal(modify_signal, original_message)
            
            elif action_type == 'close':
                # Create CloseSignal from details
                close_signal = CloseSignal(
                    action_type=details.get('action_type', 'partial_close'),
                    trade_reference=details.get('trade_reference'),
                    close_percent=details.get('close_percent', 100.0),
                    confidence=signal.confidence,
                    reasoning=f"Part of multi-action: {signal.reasoning}"
                )
                self._handle_close_signal(close_signal, original_message)
            
            elif action_type == 'new_trade':
                # Create NewSignal from details
                new_signal = NewSignal(
                    pair=details.get('pair'),
                    action=details.get('action'),
                    entry_price=details.get('entry_price', 0),
                    stop_loss=details.get('stop_loss'),
                    take_profit=details.get('take_profit'),
                    lot_size=details.get('lot_size'),
                    execution_type=details.get('execution_type', 'immediate'),
                    confidence=signal.confidence,
                    reasoning=f"Part of multi-action: {signal.reasoning}"
                )
                self._handle_new_signal(new_signal, original_message, None)
            
            else:
                print(f"  ⚠ Unknown action type: {action_type}")
        
        print(f"\n  {colorize('✓ All actions completed', 'green')}")
    
    def _handle_modify_signal(self, signal: ModifySignal, original_message: str):
        """Handle trade modification signal"""
        print(f"\n  {colorize('🔧 MODIFY SIGNAL DETECTED', 'yellow')}")
        print(f"  Action: {signal.action_type}")
        print(f"  Trade Reference: {signal.trade_reference or 'N/A'}")
        print(f"  Confidence: {signal.confidence:.0%}")
        print(f"  Reasoning: {signal.reasoning}")
        
        # Find matching trade
        trade = self._find_trade_by_reference(signal.trade_reference)
        
        if not trade:
            print(f"  ✗ Could not identify which trade to modify")
            active_count = len(self.trade_manager.get_active_trades())
            print(f"  Active trades: {active_count}")
            if active_count > 0:
                print(f"  💡 Tip: Try checking 'status' to see active trades")
            return
        
        print(f"  Matched to: {trade.action} {trade.pair} (Ticket: {trade.mt5_ticket})")
        
        # Determine new SL/TP
        new_sl = signal.new_stop_loss if signal.new_stop_loss else trade.stop_loss
        new_tp = signal.new_take_profit if signal.new_take_profit else trade.take_profit
        
        # Handle special cases like "move to breakeven"
        if "breakeven" in original_message.lower() or " be " in original_message.lower() or original_message.lower().endswith(" be"):
            # Smart BE logic based on profitability
            symbol_info = self.mt5_client.get_symbol_info(trade.pair)
            if symbol_info:
                current_bid = symbol_info['bid']
                current_ask = symbol_info['ask']
                market_price = current_bid if trade.action == "SELL" else current_ask
                
                # Get reference prices
                signal_entry = trade.signal_entry if trade.signal_entry else trade.actual_entry
                actual_entry = trade.actual_entry if trade.actual_entry else trade.entry_price
                
                print(f"  ℹ BE Analysis:")
                print(f"    Current price: {market_price}")
                print(f"    Signal entry: {signal_entry}")
                print(f"    Actual entry: {actual_entry}")
                
                # Determine BE behavior based on profitability
                if trade.action == "BUY":
                    if market_price > actual_entry:
                        # We're in profit - use our entry
                        new_sl = actual_entry
                        print(f"  ℹ We're in profit - moving SL to our entry ({actual_entry})")
                    elif market_price > signal_entry:
                        # Provider in profit, we're in loss - use provider's entry
                        new_sl = signal_entry
                        print(f"  ℹ Provider profitable, we're not - moving SL to signal entry ({signal_entry})")
                    else:
                        # Both in loss - don't move SL
                        print(f"  ⚠ Both positions in loss - not moving SL")
                        return
                else:  # SELL
                    if market_price < actual_entry:
                        # We're in profit
                        new_sl = actual_entry
                        print(f"  ℹ We're in profit - moving SL to our entry ({actual_entry})")
                    elif market_price < signal_entry:
                        # Provider in profit, we're in loss
                        new_sl = signal_entry
                        print(f"  ℹ Provider profitable, we're not - moving SL to signal entry ({signal_entry})")
                    else:
                        # Both in loss
                        print(f"  ⚠ Both positions in loss - not moving SL")
                        return
            else:
                # Fallback to simple BE
                new_sl = trade.get_be_reference_price()
                print(f"  Moving SL to breakeven: {new_sl}")
        else:
            if new_sl != trade.stop_loss:
                print(f"  New SL: {new_sl} (was {trade.stop_loss})")
            if new_tp != trade.take_profit:
                print(f"  New TP: {new_tp} (was {trade.take_profit})")
        
        # Check if position still exists in MT5
        exists, location = self.mt5_client.check_ticket_exists(trade.mt5_ticket)
        
        if not exists:
            print(f"  ℹ Position already closed in MT5")
            print(f"  ℹ Updating trade status in database")
            self.trade_manager.close_trade(trade.trade_id, 0, 0)
            print(f"  ✓ Trade marked as closed")
            return
        
        if location == 'pending':
            print(f"  ℹ This is a pending order - modifying SL/TP")
            # For pending orders, we'd need to cancel and replace
            # For now, just notify user
            print(f"  💡 Note: Pending orders require manual modification in MT5")
            print(f"  Or wait for order to fill, then modify will work")
            return
        
        # Execute modification
        print(f"\n  {colorize('⚡ MODIFYING POSITION...', 'yellow')}")
        
        success, message = self.mt5_client.modify_order(
            ticket=trade.mt5_ticket,
            stop_loss=new_sl,
            take_profit=new_tp
        )
        
        if success:
            print(f"  {colorize('✓ POSITION MODIFIED', 'green')}")
            
            # Update trade record
            if new_sl != trade.stop_loss:
                trade.update_stop_loss(new_sl)
            if new_tp != trade.take_profit:
                trade.update_take_profit(new_tp)
            
            self.trade_manager.save_trades()
            
            print(f"  Current SL: {new_sl}")
            print(f"  Current TP: {new_tp}")
        else:
            print(f"  {colorize('✗ MODIFICATION FAILED', 'red')}")
            print(f"  {message}")
    
    def _handle_close_signal(self, signal: CloseSignal, original_message: str):
        """Handle trade close signal"""
        print(f"\n  {colorize('🚪 CLOSE SIGNAL DETECTED', 'magenta')}")
        print(f"  Action: {signal.action_type}")
        print(f"  Close %: {signal.close_percent}%")
        print(f"  Confidence: {signal.confidence:.0%}")
        
        # Find matching trade
        trade = self._find_trade_by_reference(signal.trade_reference)
        
        if not trade:
            print(f"  ✗ Could not identify which trade to close")
            active_count = len(self.trade_manager.get_active_trades())
            print(f"  Active trades: {active_count}")
            if active_count > 0:
                print(f"  💡 Tip: Try checking 'status' to see active trades")
            return
        
        print(f"  Matched to: {trade.action} {trade.pair} (Ticket: {trade.mt5_ticket})")
        
        # Check if ticket still exists in MT5
        exists, location = self.mt5_client.check_ticket_exists(trade.mt5_ticket)
        
        if not exists:
            print(f"  ℹ Position already closed in MT5")
            print(f"  ℹ Updating trade status in database")
            self.trade_manager.close_trade(trade.trade_id, 0, 0)
            print(f"  ✓ Trade marked as closed")
            return
        
        if location == 'pending':
            print(f"  ℹ This is a pending order, not an open position yet")
            print(f"  💡 To cancel pending order, use MT5 directly or wait for it to fill")
            return
        
        # For partial closes, check if we're profitable
        if signal.action_type == "partial_close" and signal.close_percent < 100:
            symbol_info = self.mt5_client.get_symbol_info(trade.pair)
            if symbol_info:
                market_price = symbol_info['bid'] if trade.action == "SELL" else symbol_info['ask']
                actual_entry = trade.actual_entry if trade.actual_entry else trade.entry_price
                
                # Check if we're profitable
                is_profitable = False
                if trade.action == "BUY":
                    is_profitable = market_price > actual_entry
                else:
                    is_profitable = market_price < actual_entry
                
                if not is_profitable:
                    print(f"  ⚠ Position not profitable yet")
                    print(f"    Current: {market_price}, Entry: {actual_entry}")
                    print(f"  ℹ Skipping partial close - waiting for profit")
                    return
                else:
                    profit_points = abs(market_price - actual_entry)
                    print(f"  ✓ Position profitable (+{profit_points:.1f} points)")
        
        # Determine volume to close
        volume = None
        if signal.close_percent and signal.close_percent < 100:
            volume = trade.lot_size * (signal.close_percent / 100.0)
            print(f"  Closing {signal.close_percent}% = {volume:.2f} lots")
        
        # Execute close
        print(f"\n  {colorize('⚡ CLOSING POSITION...', 'yellow')}")
        
        success, close_price, message = self.mt5_client.close_order(
            ticket=trade.mt5_ticket,
            volume=volume,
            deviation=self.config.get('mt5.deviation', 5)
        )
        
        if success:
            print(f"  {colorize('✓ POSITION CLOSED', 'green')}")
            if close_price:
                print(f"  Close Price: {close_price}")
            else:
                print(f"  {message}")
            
            # Update trade record
            if volume is None or signal.close_percent >= 100:
                # Full close
                # Calculate P&L if we have close price
                pnl = 0.0
                if close_price:
                    if trade.action == "BUY":
                        pnl = (close_price - trade.entry_price) * trade.lot_size * 100000  # Simplified
                    else:
                        pnl = (trade.entry_price - close_price) * trade.lot_size * 100000
                
                self.trade_manager.close_trade(trade.trade_id, close_price or 0, pnl)
                print(f"  Trade fully closed")
            else:
                # Partial close - update lot size
                remaining_lots = trade.lot_size - volume
                trade.lot_size = remaining_lots
                trade.add_modification('partial_close', {
                    'percent': signal.close_percent,
                    'volume': volume,
                    'price': close_price,
                    'remaining_lots': remaining_lots
                })
                self.trade_manager.save_trades()
                print(f"  Trade partially closed - {remaining_lots:.2f} lots remaining")
        else:
            print(f"  {colorize('✗ CLOSE FAILED', 'red')}")
            print(f"  {message}")
    
    def _find_trade_by_reference(self, reference: Optional[str]) -> Optional[Any]:
        """
        Find trade by reference string
        
        Args:
            reference: Reference to trade (pair name, description, etc.)
            
        Returns:
            Trade object or None
        """
        active_trades = self.trade_manager.get_active_trades()
        
        if not active_trades:
            return None
        
        # If no reference, return most recent trade
        if not reference:
            return active_trades[0] if active_trades else None
        
        reference = reference.upper()
        
        # Try to match by pair
        for trade in active_trades:
            if trade.pair.upper() in reference or reference in trade.pair.upper():
                return trade
        
        # If only one active trade, return it
        if len(active_trades) == 1:
            return active_trades[0]
        
        return None
    
    def shutdown(self):
        """Graceful shutdown"""
        print("\n" + "="*70)
        print("  Shutting down...")
        print("="*70)
        
        self.is_running = False
        
        # Stop listening first
        if self.telegram_client:
            try:
                self.telegram_client.stop_listening()
                print("✓ Stopped listening to messages")
            except Exception as e:
                self.logger.warning(f"Error stopping listener: {e}")
        
        # Close MT5 connection
        if self.mt5_client:
            try:
                self.mt5_client.shutdown()
                print("✓ MT5 disconnected")
            except Exception as e:
                self.logger.warning(f"Error closing MT5: {e}")
        
        # Save trades
        if self.trade_manager:
            try:
                self.trade_manager.save_trades()
                print("✓ Trades saved")
            except Exception as e:
                self.logger.warning(f"Error saving trades: {e}")
        
        # Disconnect Telegram last (this is tricky due to async)
        if self.telegram_client:
            try:
                # Give the background thread a moment to finish
                import time
                time.sleep(0.5)
                self.telegram_client.disconnect()
                print("✓ Telegram disconnected")
            except RuntimeError as e:
                # Event loop already running - this is expected
                self.logger.debug(f"Telegram disconnect skipped (loop running): {e}")
                print("✓ Telegram session closed")
            except Exception as e:
                self.logger.warning(f"Error disconnecting Telegram: {e}")
                print("⚠ Telegram disconnected with warnings")
        
        print("\nGoodbye!")
    
    def sync_trades_with_mt5(self) -> int:
        """
        Sync trade_manager database with actual MT5 positions
        Finds orphaned positions (in MT5 but not in DB) and ghost trades (in DB but not in MT5)
        
        Returns:
            Number of changes made (positions added + trades closed)
        """
        if not self.mt5_client or not self.trade_manager:
            return 0
        
        changes = 0
        
        # Get all open positions from MT5
        mt5_positions = self.mt5_client.get_open_positions()
        mt5_tickets = {pos['ticket']: pos for pos in mt5_positions}
        
        # Get bot's active trades
        active_trades = self.trade_manager.get_active_trades()
        bot_tickets = {trade.mt5_ticket: trade for trade in active_trades}
        
        # Find orphaned positions (in MT5 but not in bot DB)
        orphaned_tickets = set(mt5_tickets.keys()) - set(bot_tickets.keys())
        
        for ticket in orphaned_tickets:
            position = mt5_tickets[ticket]
            self.logger.info(f"Found orphaned position in MT5: {ticket} ({position['symbol']})")
            
            # Add to database with MANUAL flag
            trade_data = {
                'pair': position['symbol'],
                'action': position['type'],
                'entry_price': position['open_price'],
                'stop_loss': position['sl'],
                'take_profit': position['tp'],
                'lot_size': position['volume'],
                'mt5_ticket': ticket,
                'original_message': '[MANUAL TRADE - Not from Telegram]',
                'telegram_msg_id': None,
                'status': TradeStatus.ACTIVE.value
            }
            
            self.trade_manager.add_trade(trade_data)
            self.logger.info(f"Added orphaned position {ticket} to database")
            changes += 1
        
        # Find ghost trades (in DB but not in MT5)
        ghost_tickets = set(bot_tickets.keys()) - set(mt5_tickets.keys())
        
        for ticket in ghost_tickets:
            trade = bot_tickets[ticket]
            self.logger.info(f"Found ghost trade in DB: {ticket} ({trade.pair}) - not in MT5")
            
            # Mark as closed in database
            self.trade_manager.close_trade(trade.trade_id, 0, 0)
            self.logger.info(f"Marked ghost trade {ticket} as closed")
            changes += 1
        
        if changes > 0:
            self.logger.info(f"Sync complete: {changes} changes made")
        
        return changes
    
    def start_tp_monitor(self):
        """Start background thread to monitor TP levels"""
        import threading
        import time
        
        def monitor_loop():
            while self.is_running:
                try:
                    self._check_tp_levels()
                    time.sleep(10)  # Check every 10 seconds
                except Exception as e:
                    self.logger.error(f"TP monitor error: {e}")
        
        monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        monitor_thread.start()
        self.logger.info("TP monitor started")
    
    def _check_tp_levels(self):
        """Check if any TP levels have been hit"""
        active_trades = self.trade_manager.get_active_trades()
        
        for trade in active_trades:
            if not trade.tp_levels or len(trade.tp_levels) == 0:
                continue  # No multi-TP setup
            
            if trade.partials_taken >= 4:
                continue  # All partials already taken
            
            # Get current price
            symbol_info = self.mt5_client.get_symbol_info(trade.pair)
            if not symbol_info:
                continue
            
            current_price = symbol_info['bid'] if trade.action == "SELL" else symbol_info['ask']
            
            # Check next TP level
            next_tp_index = trade.partials_taken
            if next_tp_index < len(trade.tp_levels):
                next_tp = trade.tp_levels[next_tp_index]
                
                # Check if TP hit
                tp_hit = False
                if trade.action == "BUY":
                    tp_hit = current_price >= next_tp
                else:
                    tp_hit = current_price <= next_tp
                
                if tp_hit:
                    self.logger.info(f"TP{next_tp_index + 1} hit for {trade.pair} at {next_tp}")
                    self._execute_auto_partial(trade, next_tp, current_price)
    
    def _execute_auto_partial(self, trade, tp_level, current_price):
        """Execute automatic partial close at TP level"""
        percentage = trade.get_next_partial_percentage()
        
        if percentage is None:
            return
        
        print(f"\n  {colorize('🎯 TP LEVEL HIT', 'green')}")
        print(f"  Trade: {trade.action} {trade.pair}")
        print(f"  TP{trade.partials_taken + 1}: {tp_level}")
        print(f"  Closing: {percentage}%")
        
        # Calculate lots to close
        volume = trade.lot_size * (percentage / 100.0)
        
        # Execute close
        success, close_price, message = self.mt5_client.close_order(
            ticket=trade.mt5_ticket,
            volume=volume
        )
        
        if success:
            print(f"  ✓ Partial closed at {close_price}")
            
            # Update trade
            remaining_lots = trade.lot_size - volume
            trade.lot_size = remaining_lots
            trade.record_partial_close(percentage, close_price, volume)
            
            # Move SL progressively
            if trade.partials_taken == 1:
                # First partial - move to BE
                new_sl = trade.actual_entry if trade.actual_entry else trade.entry_price
                self.mt5_client.modify_order(trade.mt5_ticket, stop_loss=new_sl)
                trade.update_stop_loss(new_sl)
                print(f"  ✓ SL moved to entry ({new_sl})")
            
            elif trade.partials_taken == 2 and len(trade.tp_levels) > 0:
                # Second partial - move to TP1
                new_sl = trade.tp_levels[0]
                self.mt5_client.modify_order(trade.mt5_ticket, stop_loss=new_sl)
                trade.update_stop_loss(new_sl)
                print(f"  ✓ SL moved to TP1 ({new_sl})")
            
            self.trade_manager.save_trades()
            total_closed = sum([p['percentage'] for p in trade.partial_history])
            print(f"  Remaining: {remaining_lots:.2f} lots ({100 - total_closed:.0f}%)")
        else:
            print(f"  ✗ Partial close failed: {message}")



class REPL:
    """
    Read-Eval-Print Loop for user interaction
    """
    
    def __init__(self, bot: TradingBot):
        """
        Initialize REPL
        
        Args:
            bot: TradingBot instance
        """
        self.bot = bot
        self.prompt = bot.config.get('app.repl_prompt', 'TradingBot> ')
        self.running = False
    
    def start(self):
        """Start the REPL loop"""
        self.running = True
        
        print("\n" + "="*70)
        print("  REPL Interface Ready")
        print("  Type 'help' for available commands")
        print("="*70 + "\n")
        
        while self.running:
            try:
                command = input(self.prompt).strip()
                
                if not command:
                    continue
                
                self.execute_command(command)
                
            except KeyboardInterrupt:
                print("\n\nUse 'exit' to quit")
            except EOFError:
                break
            except Exception as e:
                print(f"Error: {e}")
        
        self.bot.shutdown()
    
    def execute_command(self, command: str):
        """Execute a REPL command"""
        parts = command.split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []
        
        if cmd == 'help':
            self.cmd_help()
        elif cmd == 'status':
            self.cmd_status()
        elif cmd == 'balance':
            self.cmd_balance()
        elif cmd == 'positions':
            self.cmd_positions()
        elif cmd == 'pending':
            self.cmd_pending()
        elif cmd == 'trades':
            self.cmd_trades()
        elif cmd == 'close':
            self.cmd_close(args)
        elif cmd == 'pause':
            self.cmd_pause()
        elif cmd == 'resume':
            self.cmd_resume()
        elif cmd == 'stats':
            self.cmd_stats()
        elif cmd == 'sync':
            self.cmd_sync()
        elif cmd == 'setlot':
            self.cmd_setlot(*args)
        elif cmd == 'lot':
            self.cmd_lot()
        elif cmd == 'minlot':
            self.cmd_minlot(*args)
        elif cmd == 'maxlot':
            self.cmd_maxlot(*args)
        elif cmd == 'exit' or cmd == 'quit':
            self.running = False
        else:
            print(f"Unknown command: {cmd}. Type 'help' for available commands.")
    
    def cmd_help(self):
        """Display help"""
        print("\nAvailable Commands:")
        print("  status      - Show active trades")
        print("  balance     - Show MT5 account balance")
        print("  positions   - Show current MT5 positions")
        print("  pending     - Show pending orders")
        print("  trades      - Show recent trade history")
        print("  close <id>  - Manually close a trade by ticket or trade_id")
        print("  stats       - Show trading statistics")
        print("")
        print("  Risk Management:")
        print("    lot         - Show current lot size settings")
        print("    setlot <size> - Set default lot size (e.g., 'setlot 0.2')")
        print("    minlot <size> - Set minimum lot size (e.g., 'minlot 0.01')")
        print("    maxlot <size> - Set maximum lot size (e.g., 'maxlot 5.0')")
        print("")
        print("  sync        - Sync trade manager with MT5 (close trades that no longer exist)")
        print("  pause       - Pause message processing")
        print("  resume      - Resume message processing")
        print("  help        - Show this help message")
        print("  exit        - Shutdown the bot\n")
    
    def cmd_status(self):
        """Show active trades"""
        trades = self.bot.trade_manager.get_active_trades()
        
        if not trades:
            print("\nNo active trades")
            return
        
        print(f"\n{colorize('Active Trades:', 'cyan')} ({len(trades)})")
        print("-" * 70)
        
        for i, trade in enumerate(trades, 1):
            action_color = 'green' if trade.action == 'BUY' else 'red'
            print(f"{i}. {colorize(trade.action, action_color)} {trade.pair}")
            print(f"   Entry: {trade.entry_price} | SL: {trade.stop_loss} | TP: {trade.take_profit}")
            print(f"   Lot: {trade.lot_size} | Ticket: {trade.mt5_ticket}")
            print(f"   Age: {int(trade.get_age_seconds() / 60)} minutes")
            print()
    
    def cmd_balance(self):
        """Show MT5 account balance"""
        account_info = self.bot.mt5_client.get_account_info()
        
        if not account_info:
            print("\nFailed to get account info")
            return
        
        print(f"\n{colorize('Account Information:', 'cyan')}")
        print(f"  Balance: {account_info['balance']} {account_info['currency']}")
        print(f"  Equity: {account_info['equity']} {account_info['currency']}")
        print(f"  Profit: {account_info['profit']} {account_info['currency']}")
        print(f"  Margin: {account_info['margin']} {account_info['currency']}")
        print(f"  Free Margin: {account_info['margin_free']} {account_info['currency']}")
        if account_info['margin'] > 0:
            print(f"  Margin Level: {account_info['margin_level']:.2f}%")
        print()
    
    def cmd_positions(self):
        """Show MT5 positions"""
        positions = self.bot.mt5_client.get_open_positions()
        
        if not positions:
            print("\nNo open positions in MT5")
            return
        
        print(f"\n{colorize('MT5 Open Positions:', 'cyan')} ({len(positions)})")
        print("-" * 70)
        
        for pos in positions:
            action_color = 'green' if pos['type'] == 'BUY' else 'red'
            profit_color = 'green' if pos['profit'] >= 0 else 'red'
            profit_str = f"{pos['profit']:.2f}"
            
            print(f"Ticket: {pos['ticket']}")
            print(f"  {colorize(pos['type'], action_color)} {pos['symbol']} - {pos['volume']} lots")
            print(f"  Open: {pos['open_price']} | Current: {pos['current_price']}")
            print(f"  SL: {pos['sl']} | TP: {pos['tp']}")
            print(f"  Profit: {colorize(profit_str, profit_color)}")
            print()
    
    def cmd_pending(self):
        """Show pending orders"""
        pending = self.bot.mt5_client.get_pending_orders()
        
        if not pending:
            print("\nNo pending orders")
            return
        
        print(f"\n{colorize('Pending Orders:', 'cyan')} ({len(pending)})")
        print("-" * 70)
        
        for order in pending:
            # Color code based on order type
            if 'BUY' in order['type']:
                type_color = 'green'
            else:
                type_color = 'red'
            
            print(f"Ticket: {order['ticket']}")
            print(f"  {colorize(order['type'], type_color)} {order['symbol']} - {order['volume']} lots")
            print(f"  Entry Price: {order['entry_price']}")
            print(f"  Current: {order['current_price']}")
            print(f"  SL: {order['sl']} | TP: {order['tp']}")
            
            # Show time pending
            from datetime import datetime
            setup_time = datetime.fromtimestamp(order['time_setup'])
            age = datetime.now() - setup_time
            hours = int(age.total_seconds() / 3600)
            minutes = int((age.total_seconds() % 3600) / 60)
            print(f"  Pending for: {hours}h {minutes}m")
            print()
    
    def cmd_trades(self):
        """Show recent trades"""
        trades = self.bot.trade_manager.get_recent_trades(10)
        
        if not trades:
            print("\nNo trades in history")
            return
        
        print(f"\n{colorize('Recent Trades:', 'cyan')} (last 10)")
        print("-" * 70)
        
        for trade in trades:
            status_color = 'green' if trade.status == 'closed' else 'yellow'
            print(f"{trade.pair} | {trade.action} | {trade.status.upper()}")
            print(f"  Entry: {trade.entry_price} | SL: {trade.stop_loss} | TP: {trade.take_profit}")
            print(f"  Created: {trade.created_at[:19]}")
            if trade.closed_at:
                print(f"  Closed: {trade.closed_at[:19]}")
            print()
    
    def cmd_close(self, args):
        """Close a trade manually"""
        if not args:
            print("Usage: close <ticket_or_trade_id>")
            return
        
        identifier = args[0]
        
        # Try to find trade
        trade = None
        
        # Try as ticket number
        try:
            ticket = int(identifier)
            trade = self.bot.trade_manager.get_trade_by_ticket(ticket)
        except ValueError:
            # Try as trade ID
            trade = self.bot.trade_manager.get_trade(identifier)
        
        if not trade:
            print(f"Trade not found: {identifier}")
            return
        
        print(f"\nClosing {trade.action} {trade.pair} (Ticket: {trade.mt5_ticket})...")
        
        success, close_price, message = self.bot.mt5_client.close_order(trade.mt5_ticket)
        
        if success:
            print(f"{colorize('✓ Position closed', 'green')} at {close_price}")
            self.bot.trade_manager.close_trade(trade.trade_id, close_price, 0.0)
        else:
            print(f"{colorize('✗ Failed to close', 'red')}: {message}")
    
    def cmd_setlot(self, *args):
        """Change default lot size"""
        if not args:
            # Show current lot size
            current_lot = self.bot.config.get('risk.default_lot_size', 0.1)
            min_lot = self.bot.config.get('risk.min_lot_size', 0.01)
            max_lot = self.bot.config.get('risk.max_lot_size', 100.0)
            print(f"\nCurrent default lot size: {current_lot}")
            print(f"Allowed range: {min_lot} - {max_lot}")
            print(f"\nUsage: setlot <size>")
            print(f"Example: setlot 0.2")
            return
        
        try:
            new_lot_size = float(args[0])
            
            # Validate lot size
            min_lot = self.bot.config.get('risk.min_lot_size', 0.01)
            max_lot = self.bot.config.get('risk.max_lot_size', 100.0)
            
            if new_lot_size < min_lot:
                print(f"✗ Lot size too small. Minimum: {min_lot}")
                return
            
            if new_lot_size > max_lot:
                print(f"✗ Lot size too large. Maximum: {max_lot}")
                return
            
            # Update config (in-memory, not saved to file)
            old_lot = self.bot.config.get('risk.default_lot_size', 0.1)
            self.bot.config.config['risk']['default_lot_size'] = new_lot_size
            
            print(f"\n{colorize('✓ Default lot size updated', 'green')}")
            print(f"  Old: {old_lot}")
            print(f"  New: {new_lot_size}")
            print(f"\n  ℹ This change is temporary (only for current session)")
            print(f"  💡 To make it permanent, edit 'risk.default_lot_size' in config.yaml")
            
        except ValueError:
            print(f"✗ Invalid lot size. Must be a number (e.g., 0.1, 0.5, 1.0)")
    
    def cmd_lot(self):
        """Show current lot size settings"""
        current_lot = self.bot.config.get('risk.default_lot_size', 0.1)
        min_lot = self.bot.config.get('risk.min_lot_size', 0.01)
        max_lot = self.bot.config.get('risk.max_lot_size', 100.0)
        
        print(f"\n{colorize('Current Lot Size Settings:', 'cyan')}")
        print(f"  Default lot size: {colorize(str(current_lot), 'green')}")
        print(f"  Minimum lot size: {min_lot}")
        print(f"  Maximum lot size: {max_lot}")
        print(f"\n  💡 Use 'setlot <size>' to change default")
        print(f"  💡 Use 'minlot <size>' to change minimum")
        print(f"  💡 Use 'maxlot <size>' to change maximum\n")
    
    def cmd_minlot(self, *args):
        """Change minimum lot size"""
        if not args:
            current = self.bot.config.get('risk.min_lot_size', 0.01)
            print(f"\nCurrent minimum lot size: {current}")
            print(f"Usage: minlot <size>")
            print(f"Example: minlot 0.01")
            return
        
        try:
            new_min = float(args[0])
            
            if new_min <= 0:
                print(f"✗ Minimum lot size must be greater than 0")
                return
            
            max_lot = self.bot.config.get('risk.max_lot_size', 100.0)
            if new_min > max_lot:
                print(f"✗ Minimum ({new_min}) cannot be greater than maximum ({max_lot})")
                return
            
            old_min = self.bot.config.get('risk.min_lot_size', 0.01)
            self.bot.config.config['risk']['min_lot_size'] = new_min
            
            print(f"\n{colorize('✓ Minimum lot size updated', 'green')}")
            print(f"  Old: {old_min}")
            print(f"  New: {new_min}")
            print(f"\n  ℹ This change is temporary (only for current session)")
            
        except ValueError:
            print(f"✗ Invalid size. Must be a number")
    
    def cmd_maxlot(self, *args):
        """Change maximum lot size"""
        if not args:
            current = self.bot.config.get('risk.max_lot_size', 100.0)
            print(f"\nCurrent maximum lot size: {current}")
            print(f"Usage: maxlot <size>")
            print(f"Example: maxlot 5.0")
            return
        
        try:
            new_max = float(args[0])
            
            if new_max <= 0:
                print(f"✗ Maximum lot size must be greater than 0")
                return
            
            min_lot = self.bot.config.get('risk.min_lot_size', 0.01)
            if new_max < min_lot:
                print(f"✗ Maximum ({new_max}) cannot be less than minimum ({min_lot})")
                return
            
            old_max = self.bot.config.get('risk.max_lot_size', 100.0)
            self.bot.config.config['risk']['max_lot_size'] = new_max
            
            print(f"\n{colorize('✓ Maximum lot size updated', 'green')}")
            print(f"  Old: {old_max}")
            print(f"  New: {new_max}")
            print(f"\n  ℹ This change is temporary (only for current session)")
            
        except ValueError:
            print(f"✗ Invalid size. Must be a number")
    
    def cmd_pause(self):
        """Pause message processing"""
        self.bot.is_paused = True
        print(f"\n{colorize('⏸ Message processing paused', 'yellow')}")
    
    def cmd_resume(self):
        """Resume message processing"""
        self.bot.is_paused = False
        print(f"\n{colorize('▶ Message processing resumed', 'green')}")
    
    def cmd_stats(self):
        """Show trading statistics"""
        stats = self.bot.trade_manager.get_statistics()
        
        print(f"\n{colorize('Trading Statistics:', 'cyan')}")
        print(f"  Total Trades: {stats['total_trades']}")
        print(f"  Active: {stats['active_trades']}")
        print(f"  Closed: {stats['closed_trades']}")
        
        if stats['closed_trades'] > 0:
            print(f"\n  Winning Trades: {stats['winning_trades']}")
            print(f"  Losing Trades: {stats['losing_trades']}")
            print(f"  Win Rate: {stats['win_rate']:.1f}%")
            
            pnl_color = 'green' if stats['total_pnl'] >= 0 else 'red'
            pnl_str = f"{stats['total_pnl']:.2f}"
            print(f"  Total P&L: {colorize(pnl_str, pnl_color)}")
        print()
    
    def cmd_sync(self):
        """Sync trade manager with MT5 - close trades that no longer exist"""
        print(f"\n{colorize('Syncing with MT5...', 'cyan')}")
        
        active_trades = self.bot.trade_manager.get_active_trades()
        if not active_trades:
            print("No active trades to sync")
            return
        
        # Get all open positions from MT5
        mt5_positions = self.bot.mt5_client.get_open_positions()
        mt5_tickets = {pos['ticket'] for pos in mt5_positions}
        
        closed_count = 0
        for trade in active_trades:
            if trade.mt5_ticket and trade.mt5_ticket not in mt5_tickets:
                # Trade exists in our system but not in MT5 - mark as closed
                print(f"  ℹ Trade {trade.pair} (Ticket: {trade.mt5_ticket}) not found in MT5")
                print(f"     Marking as closed...")
                self.bot.trade_manager.close_trade(trade.trade_id, 0, 0)
                closed_count += 1
        
        if closed_count > 0:
            print(f"\n✓ Synced {closed_count} trade(s) - marked as closed")
        else:
            print(f"\n✓ All trades in sync with MT5")
        print()


def main():
    """Main entry point"""
    bot = None
    telegram_thread = None
    
    try:
        # Create bot
        bot = TradingBot()
        
        # Startup sequence
        if not bot.startup():
            print("\nStartup failed. Exiting.")
            return
        
        # Start listening to messages in background
        bot.start_listening()
        
        # Start REPL in main thread
        repl = REPL(bot)
        
        # Run Telegram client in background thread
        telegram_thread = threading.Thread(
            target=bot.telegram_client.run_until_disconnected,
            daemon=True
        )
        telegram_thread.start()
        
        # Start REPL (blocks until exit)
        repl.start()
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\nFatal error: {e}")
        logging.error("Fatal error", exc_info=True)
    finally:
        # Ensure cleanup happens
        if bot:
            try:
                bot.shutdown()
            except Exception as e:
                print(f"Error during shutdown: {e}")
                # Force exit if shutdown fails
                import sys
                sys.exit(1)


if __name__ == "__main__":
    main()
