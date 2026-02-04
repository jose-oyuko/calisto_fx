"""
MT5 Client - MetaTrader 5 connection and trade execution
"""

import MetaTrader5 as mt5
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime
import logging


class MT5Client:
    """
    MetaTrader 5 client for executing trades and managing positions
    """
    
    def __init__(self, magic_number: int = 234567):
        """
        Initialize MT5 client
        
        Args:
            magic_number: Unique identifier for bot trades
        """
        self.magic_number = magic_number
        self.is_connected = False
        self.logger = logging.getLogger('TradingBot.MT5')
    
    def initialize(self) -> bool:
        """
        Initialize MT5 connection
        
        Returns:
            True if successful, False otherwise
        """
        if not mt5.initialize():
            self.logger.error(f"MT5 initialization failed: {mt5.last_error()}")
            return False
        
        self.is_connected = True
        self.logger.info("MT5 initialized successfully")
        return True
    
    def login(self, account: int, password: str, server: str) -> bool:
        """
        Login to MT5 account
        
        Args:
            account: MT5 account number
            password: Account password
            server: Broker server name
            
        Returns:
            True if login successful, False otherwise
        """
        if not self.is_connected:
            if not self.initialize():
                return False
        
        # Attempt login
        authorized = mt5.login(account, password=password, server=server)
        
        if not authorized:
            error = mt5.last_error()
            self.logger.error(f"MT5 login failed: {error}")
            return False
        
        # Verify connection
        account_info = mt5.account_info()
        if account_info is None:
            self.logger.error("Failed to get account info after login")
            return False
        
        self.logger.info(f"Logged in to MT5 account: {account} on {server}")
        self.logger.info(f"Account balance: {account_info.balance}, Equity: {account_info.equity}")
        
        return True
    
    def shutdown(self):
        """Shutdown MT5 connection"""
        if self.is_connected:
            mt5.shutdown()
            self.is_connected = False
            self.logger.info("MT5 connection closed")
    
    def check_connection(self) -> bool:
        """
        Check if MT5 connection is active
        
        Returns:
            True if connected, False otherwise
        """
        if not self.is_connected:
            return False
        
        # Try to get terminal info
        terminal_info = mt5.terminal_info()
        if terminal_info is None:
            self.is_connected = False
            return False
        
        return True
    
    def get_account_info(self) -> Optional[Dict[str, Any]]:
        """
        Get account information
        
        Returns:
            Dictionary with account info or None if failed
        """
        if not self.check_connection():
            self.logger.error("Not connected to MT5")
            return None
        
        account_info = mt5.account_info()
        if account_info is None:
            self.logger.error("Failed to get account info")
            return None
        
        return {
            'login': account_info.login,
            'server': account_info.server,
            'balance': account_info.balance,
            'equity': account_info.equity,
            'profit': account_info.profit,
            'margin': account_info.margin,
            'margin_free': account_info.margin_free,
            'margin_level': account_info.margin_level,
            'currency': account_info.currency,
            'leverage': account_info.leverage,
        }
    
    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get symbol information
        
        Args:
            symbol: Trading symbol (e.g., EURUSD)
            
        Returns:
            Dictionary with symbol info or None if failed
        """
        if not self.check_connection():
            return None
        
        # Select symbol (make it visible in Market Watch)
        if not mt5.symbol_select(symbol, True):
            self.logger.error(f"Failed to select symbol: {symbol}")
            return None
        
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            self.logger.error(f"Failed to get info for symbol: {symbol}")
            return None
        
        return {
            'name': symbol_info.name,
            'bid': symbol_info.bid,
            'ask': symbol_info.ask,
            'spread': symbol_info.spread,
            'digits': symbol_info.digits,
            'point': symbol_info.point,
            'trade_contract_size': symbol_info.trade_contract_size,
            'volume_min': symbol_info.volume_min,
            'volume_max': symbol_info.volume_max,
            'volume_step': symbol_info.volume_step,
        }
    
    def place_market_order(self, 
                          symbol: str, 
                          order_type: str, 
                          lot_size: float,
                          stop_loss: float = 0.0,
                          take_profit: float = 0.0,
                          deviation: int = 5,
                          comment: str = "TelegramBot") -> Tuple[bool, Optional[int], str]:
        """
        Place a market order
        
        Args:
            symbol: Trading symbol (e.g., EURUSD)
            order_type: "BUY" or "SELL"
            lot_size: Position size in lots
            stop_loss: Stop loss price (0 for no SL)
            take_profit: Take profit price (0 for no TP)
            deviation: Maximum price deviation in points
            comment: Order comment
            
        Returns:
            Tuple of (success, ticket_number, message)
        """
        if not self.check_connection():
            return False, None, "Not connected to MT5"
        
        # Get symbol info
        symbol_info = self.get_symbol_info(symbol)
        if symbol_info is None:
            return False, None, f"Failed to get symbol info for {symbol}"
        
        # Determine order type
        if order_type.upper() == "BUY":
            trade_type = mt5.ORDER_TYPE_BUY
            price = symbol_info['ask']
        elif order_type.upper() == "SELL":
            trade_type = mt5.ORDER_TYPE_SELL
            price = symbol_info['bid']
        else:
            return False, None, f"Invalid order type: {order_type}"
        
        # Normalize lot size
        lot_size = round(lot_size / symbol_info['volume_step']) * symbol_info['volume_step']
        lot_size = max(symbol_info['volume_min'], min(lot_size, symbol_info['volume_max']))
        
        # Normalize prices
        digits = symbol_info['digits']
        if stop_loss > 0:
            stop_loss = round(stop_loss, digits)
        if take_profit > 0:
            take_profit = round(take_profit, digits)
        
        # Try different filling modes in order of preference
        filling_modes = [
            mt5.ORDER_FILLING_FOK,    # Fill or Kill (most common)
            mt5.ORDER_FILLING_IOC,    # Immediate or Cancel
            mt5.ORDER_FILLING_RETURN, # Return (for exchange execution)
        ]
        
        filling_names = {
            mt5.ORDER_FILLING_FOK: "FOK",
            mt5.ORDER_FILLING_IOC: "IOC", 
            mt5.ORDER_FILLING_RETURN: "RETURN"
        }
        
        last_error_msg = ""
        
        for filling_mode in filling_modes:
            # Prepare order request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": lot_size,
                "type": trade_type,
                "price": price,
                "sl": stop_loss,
                "tp": take_profit,
                "deviation": deviation,
                "magic": self.magic_number,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }
            
            # Send order
            self.logger.info(f"Placing {order_type} order: {symbol} {lot_size} lots @ {price} (filling: {filling_names[filling_mode]})")
            result = mt5.order_send(request)
            
            if result is None:
                error = mt5.last_error()
                last_error_msg = f"Order send failed: {error}"
                self.logger.warning(f"{last_error_msg}, trying next filling mode...")
                continue
            
            # Check result
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                # Success!
                ticket = result.order
                msg = f"Order executed successfully - Ticket: {ticket}, Price: {result.price}, Filling: {filling_names[filling_mode]}"
                self.logger.info(msg)
                return True, ticket, msg
            
            elif result.retcode == 10030:  # Unsupported filling mode
                last_error_msg = f"Filling mode {filling_names[filling_mode]} not supported"
                self.logger.warning(f"{last_error_msg}, trying next...")
                continue
            
            else:
                # Other error - don't try other filling modes
                last_error_msg = f"Order failed with retcode: {result.retcode} - {result.comment}"
                self.logger.error(last_error_msg)
                return False, None, last_error_msg
        
        # All filling modes failed
        msg = f"All filling modes failed. Last error: {last_error_msg}"
        self.logger.error(msg)
        return False, None, msg
    
    def place_pending_order(self,
                           symbol: str,
                           order_type: str,
                           lot_size: float,
                           entry_price: float,
                           stop_loss: float = 0.0,
                           take_profit: float = 0.0,
                           comment: str = "TelegramBot") -> Tuple[bool, Optional[int], str]:
        """
        Place a pending order (Buy Limit, Buy Stop, Sell Limit, Sell Stop)
        
        Args:
            symbol: Trading symbol
            order_type: "BUY_LIMIT", "BUY_STOP", "SELL_LIMIT", "SELL_STOP"
            lot_size: Position size in lots
            entry_price: Price at which to enter
            stop_loss: Stop loss price
            take_profit: Take profit price
            comment: Order comment
            
        Returns:
            Tuple of (success, ticket_number, message)
        """
        if not self.check_connection():
            return False, None, "Not connected to MT5"
        
        # Get symbol info
        symbol_info = self.get_symbol_info(symbol)
        if symbol_info is None:
            return False, None, f"Failed to get symbol info for {symbol}"
        
        # Determine pending order type
        current_price = symbol_info['bid'] if order_type.startswith('SELL') else symbol_info['ask']
        
        order_type_upper = order_type.upper()
        if order_type_upper == "BUY_LIMIT":
            trade_type = mt5.ORDER_TYPE_BUY_LIMIT
        elif order_type_upper == "BUY_STOP":
            trade_type = mt5.ORDER_TYPE_BUY_STOP
        elif order_type_upper == "SELL_LIMIT":
            trade_type = mt5.ORDER_TYPE_SELL_LIMIT
        elif order_type_upper == "SELL_STOP":
            trade_type = mt5.ORDER_TYPE_SELL_STOP
        else:
            return False, None, f"Invalid pending order type: {order_type}"
        
        # Normalize lot size
        lot_size = round(lot_size / symbol_info['volume_step']) * symbol_info['volume_step']
        lot_size = max(symbol_info['volume_min'], min(lot_size, symbol_info['volume_max']))
        
        # Normalize prices
        digits = symbol_info['digits']
        entry_price = round(entry_price, digits)
        if stop_loss > 0:
            stop_loss = round(stop_loss, digits)
        if take_profit > 0:
            take_profit = round(take_profit, digits)
        
        # Prepare pending order request
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot_size,
            "type": trade_type,
            "price": entry_price,
            "sl": stop_loss,
            "tp": take_profit,
            "magic": self.magic_number,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,  # Good Till Cancelled
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        
        # Send pending order
        self.logger.info(f"Placing pending order: {order_type} {symbol} {lot_size} lots @ {entry_price}")
        result = mt5.order_send(request)
        
        if result is None:
            error = mt5.last_error()
            msg = f"Pending order send failed: {error}"
            self.logger.error(msg)
            return False, None, msg
        
        # Check result
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            msg = f"Pending order failed with retcode: {result.retcode} - {result.comment}"
            self.logger.error(msg)
            return False, None, msg
        
        # Success
        ticket = result.order
        msg = f"Pending order placed successfully - Ticket: {ticket}, Entry: {entry_price}"
        self.logger.info(msg)
        
        return True, ticket, msg
    
    def determine_pending_order_type(self, action: str, entry_price: float, symbol: str) -> Optional[str]:
        """
        Determine the correct pending order type based on current price
        
        Args:
            action: "BUY" or "SELL"
            entry_price: Desired entry price
            symbol: Trading symbol
            
        Returns:
            Pending order type string or None if should be market order
        """
        symbol_info = self.get_symbol_info(symbol)
        if symbol_info is None:
            return None
        
        current_price = symbol_info['ask'] if action == "BUY" else symbol_info['bid']
        
        if action.upper() == "BUY":
            if entry_price < current_price:
                return "BUY_LIMIT"  # Buy below current price
            elif entry_price > current_price:
                return "BUY_STOP"   # Buy above current price (breakout)
        elif action.upper() == "SELL":
            if entry_price > current_price:
                return "SELL_LIMIT"  # Sell above current price
            elif entry_price < current_price:
                return "SELL_STOP"   # Sell below current price (breakdown)
        
        return None  # Should execute at market
    
    def cancel_pending_order(self, ticket: int) -> bool:
        """
        Cancel a pending order
        
        Args:
            ticket: Order ticket number to cancel
            
        Returns:
            True if successfully cancelled, False otherwise
        """
        if not self.check_connection():
            return False
        
        # Prepare delete request
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
        }
        
        # Send cancel request
        self.logger.info(f"Cancelling pending order {ticket}")
        result = mt5.order_send(request)
        
        if result is None:
            error = mt5.last_error()
            self.logger.error(f"Failed to cancel order {ticket}: {error}")
            return False
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self.logger.error(f"Failed to cancel order {ticket}: {result.retcode} - {result.comment}")
            return False
        
        self.logger.info(f"Order {ticket} cancelled successfully")
        return True
    
    def modify_order(self, 
                    ticket: int,
                    stop_loss: Optional[float] = None,
                    take_profit: Optional[float] = None) -> Tuple[bool, str]:
        """
        Modify an open position's SL/TP
        
        Args:
            ticket: Position ticket number
            stop_loss: New stop loss price (None to keep current)
            take_profit: New take profit price (None to keep current)
            
        Returns:
            Tuple of (success, message)
        """
        if not self.check_connection():
            return False, "Not connected to MT5"
        
        # Get position info
        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            return False, f"Position {ticket} not found"
        
        position = position[0]
        symbol = position.symbol
        
        # Get symbol info for normalization
        symbol_info = self.get_symbol_info(symbol)
        if symbol_info is None:
            return False, f"Failed to get symbol info for {symbol}"
        
        # Use current values if not specified
        if stop_loss is None:
            stop_loss = position.sl
        if take_profit is None:
            take_profit = position.tp
        
        # Normalize prices
        digits = symbol_info['digits']
        stop_loss = round(stop_loss, digits) if stop_loss > 0 else 0.0
        take_profit = round(take_profit, digits) if take_profit > 0 else 0.0
        
        # Check if there are actual changes
        current_sl = round(position.sl, digits) if position.sl > 0 else 0.0
        current_tp = round(position.tp, digits) if position.tp > 0 else 0.0
        
        if stop_loss == current_sl and take_profit == current_tp:
            msg = f"No changes needed - SL and TP already at requested values"
            self.logger.info(msg)
            return True, msg
        
        # Validate stops level (minimum distance from current price)
        point = symbol_info['point']
        stops_level = symbol_info.get('stops_level', 0)
        
        if stops_level > 0 and stop_loss > 0:
            min_distance = stops_level * point
            current_bid = symbol_info['bid']
            current_ask = symbol_info['ask']
            
            if position.type == mt5.ORDER_TYPE_BUY:
                # For BUY: SL must be below current bid by at least stops_level
                min_sl = current_bid - min_distance
                if stop_loss > min_sl:
                    old_sl = stop_loss
                    stop_loss = round(min_sl, digits)
                    self.logger.warning(f"SL {old_sl} too close to market {current_bid}. Adjusted to {stop_loss} (min distance: {min_distance:.2f})")
            else:
                # For SELL: SL must be above current ask by at least stops_level
                min_sl = current_ask + min_distance
                if stop_loss < min_sl:
                    old_sl = stop_loss
                    stop_loss = round(min_sl, digits)
                    self.logger.warning(f"SL {old_sl} too close to market {current_ask}. Adjusted to {stop_loss} (min distance: {min_distance:.2f})")
        
        # Log what's changing
        changes = []
        if stop_loss != current_sl:
            changes.append(f"SL: {current_sl} → {stop_loss}")
        if take_profit != current_tp:
            changes.append(f"TP: {current_tp} → {take_profit}")
        
        self.logger.info(f"Modifying position {ticket}: {', '.join(changes)}")
        
        # Prepare modification request
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "sl": stop_loss,
            "tp": take_profit,
            "position": ticket,
        }
        
        # Send modification
        result = mt5.order_send(request)
        
        if result is None:
            error = mt5.last_error()
            msg = f"Modification failed: {error}"
            self.logger.error(msg)
            return False, msg
        
        if result.retcode == 10025:
            # "No changes" error - values are already correct
            msg = f"Position already has these values (this is OK)"
            self.logger.info(msg)
            return True, msg
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            msg = f"Modification failed with retcode: {result.retcode} - {result.comment}"
            self.logger.error(msg)
            return False, msg
        
        msg = f"Position {ticket} modified: {', '.join(changes)}"
        self.logger.info(msg)
        return True, msg
    
    def close_order(self, 
                   ticket: int,
                   volume: Optional[float] = None,
                   deviation: int = 5) -> Tuple[bool, Optional[float], str]:
        """
        Close an open position (full or partial)
        
        Args:
            ticket: Position ticket number
            volume: Volume to close (None = close all)
            deviation: Maximum price deviation
            
        Returns:
            Tuple of (success, close_price, message)
        """
        if not self.check_connection():
            return False, None, "Not connected to MT5"
        
        # Get position info
        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            # Position not found - might already be closed
            self.logger.warning(f"Position {ticket} not found in open positions")
            
            # Check if it was closed recently by looking at history
            from datetime import datetime, timedelta
            now = datetime.now()
            from_date = now - timedelta(hours=1)  # Check last hour
            
            deals = mt5.history_deals_get(from_date, now, position=ticket)
            if deals and len(deals) > 0:
                # Found in history - was closed
                last_deal = deals[-1]
                return True, last_deal.price, f"Position {ticket} was already closed at {last_deal.price}"
            
            return False, None, f"Position {ticket} not found (may have been closed manually or hit SL/TP)"
        
        position = position[0]
        symbol = position.symbol
        
        # Get symbol info
        symbol_info = self.get_symbol_info(symbol)
        if symbol_info is None:
            return False, None, f"Failed to get symbol info for {symbol}"
        
        # Determine close volume
        if volume is None:
            volume = position.volume
        else:
            volume = min(volume, position.volume)
        
        # Normalize volume
        volume = round(volume / symbol_info['volume_step']) * symbol_info['volume_step']
        
        # Determine order type (opposite of position type)
        if position.type == mt5.ORDER_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = symbol_info['bid']
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = symbol_info['ask']
        
        # Try different filling modes
        filling_modes = [
            mt5.ORDER_FILLING_FOK,
            mt5.ORDER_FILLING_IOC,
            mt5.ORDER_FILLING_RETURN,
        ]
        
        last_error_msg = ""
        
        for filling_mode in filling_modes:
            # Prepare close request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "position": ticket,
                "price": price,
                "deviation": deviation,
                "magic": self.magic_number,
                "comment": "Close by bot",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }
            
            # Send close order
            self.logger.info(f"Closing position {ticket}: {volume} lots @ {price}")
            result = mt5.order_send(request)
            
            if result is None:
                error = mt5.last_error()
                last_error_msg = f"Close failed: {error}"
                self.logger.warning(f"{last_error_msg}, trying next filling mode...")
                continue
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                close_price = result.price
                msg = f"Position {ticket} closed successfully at {close_price}"
                self.logger.info(msg)
                return True, close_price, msg
            
            elif result.retcode == 10030:  # Unsupported filling mode
                last_error_msg = f"Filling mode not supported"
                self.logger.warning(f"{last_error_msg}, trying next...")
                continue
            
            else:
                last_error_msg = f"Close failed with retcode: {result.retcode} - {result.comment}"
                self.logger.error(last_error_msg)
                return False, None, last_error_msg
        
        # All filling modes failed
        msg = f"All filling modes failed. Last error: {last_error_msg}"
        self.logger.error(msg)
        return False, None, msg
    
    def get_open_positions(self) -> List[Dict[str, Any]]:
        """
        Get all open positions
        
        Returns:
            List of position dictionaries
        """
        if not self.check_connection():
            return []
        
        positions = mt5.positions_get()
        if positions is None:
            return []
        
        result = []
        for pos in positions:
            result.append({
                'ticket': pos.ticket,
                'symbol': pos.symbol,
                'type': 'BUY' if pos.type == mt5.ORDER_TYPE_BUY else 'SELL',
                'volume': pos.volume,
                'open_price': pos.price_open,
                'current_price': pos.price_current,
                'sl': pos.sl,
                'tp': pos.tp,
                'profit': pos.profit,
                'magic': pos.magic,
                'comment': pos.comment,
            })
        
        return result
    
    def get_position_by_ticket(self, ticket: int) -> Optional[Dict[str, Any]]:
        """
        Get specific position by ticket
        
        Args:
            ticket: Position ticket number
            
        Returns:
            Position dictionary or None if not found
        """
        positions = self.get_open_positions()
        for pos in positions:
            if pos['ticket'] == ticket:
                return pos
        return None
    
    def get_pending_orders(self) -> List[Dict[str, Any]]:
        """
        Get all pending orders
        
        Returns:
            List of pending order dictionaries
        """
        if not self.check_connection():
            return []
        
        orders = mt5.orders_get()
        if orders is None:
            return []
        
        result = []
        for order in orders:
            # Determine order type name
            order_type_map = {
                mt5.ORDER_TYPE_BUY_LIMIT: "BUY_LIMIT",
                mt5.ORDER_TYPE_BUY_STOP: "BUY_STOP",
                mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
                mt5.ORDER_TYPE_SELL_STOP: "SELL_STOP",
            }
            
            order_type_name = order_type_map.get(order.type, "UNKNOWN")
            
            result.append({
                'ticket': order.ticket,
                'symbol': order.symbol,
                'type': order_type_name,
                'volume': order.volume_current,
                'entry_price': order.price_open,
                'current_price': order.price_current,
                'sl': order.sl,
                'tp': order.tp,
                'magic': order.magic,
                'comment': order.comment,
                'time_setup': order.time_setup,
            })
        
        return result
    
    def check_ticket_exists(self, ticket: int) -> Tuple[bool, str]:
        """
        Check if ticket exists in open positions or pending orders
        
        Args:
            ticket: Ticket number to check
            
        Returns:
            Tuple of (exists, location) where location is 'position', 'pending', or 'none'
        """
        if not self.check_connection():
            self.logger.warning("Not connected to MT5")
            return False, 'none'
        
        # Check open positions
        try:
            positions = mt5.positions_get(ticket=ticket)
            self.logger.debug(f"Checking ticket {ticket} in positions: {positions}")
            if positions is not None and len(positions) > 0:
                self.logger.info(f"Ticket {ticket} found in open positions")
                return True, 'position'
        except Exception as e:
            self.logger.error(f"Error checking positions for {ticket}: {e}")
        
        # Check pending orders
        try:
            orders = mt5.orders_get(ticket=ticket)
            self.logger.debug(f"Checking ticket {ticket} in orders: {orders}")
            if orders is not None and len(orders) > 0:
                self.logger.info(f"Ticket {ticket} found in pending orders")
                return True, 'pending'
        except Exception as e:
            self.logger.error(f"Error checking orders for {ticket}: {e}")
        
        self.logger.warning(f"Ticket {ticket} not found in positions or orders")
        return False, 'none'


# Example usage and testing
if __name__ == "__main__":
    # Setup basic logging
    logging.basicConfig(level=logging.INFO)
    
    print("MT5 Client Test")
    print("=" * 50)
    
    # Create client
    client = MT5Client()
    
    # Initialize
    print("\n1. Initializing MT5...")
    if client.initialize():
        print("✓ MT5 initialized")
    else:
        print("✗ MT5 initialization failed")
        exit(1)
    
    # Note: Login requires actual credentials
    # Uncomment and provide credentials to test
    """
    print("\n2. Logging in...")
    if client.login(account=12345, password="password", server="Broker-Server"):
        print("✓ Login successful")
    else:
        print("✗ Login failed")
        client.shutdown()
        exit(1)
    
    # Get account info
    print("\n3. Getting account info...")
    account_info = client.get_account_info()
    if account_info:
        print(f"✓ Balance: {account_info['balance']}")
        print(f"  Equity: {account_info['equity']}")
        print(f"  Margin: {account_info['margin']}")
    
    # Get symbol info
    print("\n4. Getting symbol info for EURUSD...")
    symbol_info = client.get_symbol_info("EURUSD")
    if symbol_info:
        print(f"✓ Bid: {symbol_info['bid']}")
        print(f"  Ask: {symbol_info['ask']}")
        print(f"  Spread: {symbol_info['spread']}")
    
    # Get open positions
    print("\n5. Getting open positions...")
    positions = client.get_open_positions()
    print(f"✓ Open positions: {len(positions)}")
    for pos in positions:
        print(f"  {pos['ticket']}: {pos['type']} {pos['symbol']} {pos['volume']} lots")
    """
    
    # Shutdown
    print("\n6. Shutting down...")
    client.shutdown()
    print("✓ MT5 connection closed")
    
    print("\n" + "=" * 50)
    print("Note: Full testing requires MT5 credentials")
    print("Uncomment the test section and provide credentials")
