"""
Trade Manager - Handles trade state tracking and persistence
"""

import json
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass, asdict, field
from enum import Enum


class TradeStatus(Enum):
    """Trade status enumeration"""
    PENDING = "pending"
    ACTIVE = "active"
    CLOSED = "closed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TradeAction(Enum):
    """Trade action enumeration"""
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Trade:
    """
    Trade data model representing a single trading position
    """
    trade_id: str
    pair: str
    action: str  # BUY or SELL
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    
    # MT5 specific
    mt5_ticket: Optional[int] = None
    
    # Status tracking
    status: str = TradeStatus.ACTIVE.value
    
    # Metadata
    original_message: str = ""
    telegram_msg_id: Optional[int] = None
    signal_provider: Optional[str] = None
    
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    closed_at: Optional[str] = None
    
    # P&L tracking
    entry_fill_price: Optional[float] = None  # Actual fill price
    exit_price: Optional[float] = None
    profit_loss: Optional[float] = None
    
    # Modifications history
    modifications: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert trade to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Trade':
        """Create trade from dictionary"""
        # Handle modifications list
        if 'modifications' not in data:
            data['modifications'] = []
        return cls(**data)
    
    def add_modification(self, modification_type: str, details: Dict[str, Any]):
        """
        Add a modification record to trade history
        
        Args:
            modification_type: Type of modification (sl_update, tp_update, partial_close)
            details: Details of the modification
        """
        modification = {
            'type': modification_type,
            'timestamp': datetime.now().isoformat(),
            'details': details
        }
        self.modifications.append(modification)
        self.updated_at = datetime.now().isoformat()
    
    def update_stop_loss(self, new_sl: float):
        """Update stop loss and record modification"""
        old_sl = self.stop_loss
        self.stop_loss = new_sl
        self.add_modification('sl_update', {
            'old_sl': old_sl,
            'new_sl': new_sl
        })
    
    def update_take_profit(self, new_tp: float):
        """Update take profit and record modification"""
        old_tp = self.take_profit
        self.take_profit = new_tp
        self.add_modification('tp_update', {
            'old_tp': old_tp,
            'new_tp': new_tp
        })
    
    def close(self, exit_price: float, profit_loss: float):
        """Mark trade as closed"""
        self.status = TradeStatus.CLOSED.value
        self.exit_price = exit_price
        self.profit_loss = profit_loss
        self.closed_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
    
    def get_age_seconds(self) -> float:
        """Get trade age in seconds"""
        created = datetime.fromisoformat(self.created_at)
        return (datetime.now() - created).total_seconds()
    
    def __str__(self) -> str:
        """String representation of trade"""
        return (f"Trade({self.trade_id[:8]}): {self.action} {self.pair} @ {self.entry_price} "
                f"[SL: {self.stop_loss}, TP: {self.take_profit}] - {self.status}")


class TradeManager:
    """
    Manages trade state, persistence, and retrieval
    """
    
    def __init__(self, storage_file: str = "data/trades.json"):
        """
        Initialize trade manager
        
        Args:
            storage_file: Path to JSON file for persistence
        """
        self.storage_file = Path(storage_file)
        self.trades: Dict[str, Trade] = {}
        
        # Ensure data directory exists
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing trades
        self.load_trades()
    
    def generate_trade_id(self) -> str:
        """Generate unique trade ID"""
        return str(uuid.uuid4())
    
    def add_trade(self, trade_data: Dict[str, Any]) -> Trade:
        """
        Add a new trade to the manager
        
        Args:
            trade_data: Dictionary containing trade information
            
        Returns:
            Created Trade object
        """
        # Generate ID if not provided
        if 'trade_id' not in trade_data:
            trade_data['trade_id'] = self.generate_trade_id()
        
        # Create trade object
        trade = Trade.from_dict(trade_data)
        
        # Store trade
        self.trades[trade.trade_id] = trade
        
        # Persist to disk
        self.save_trades()
        
        return trade
    
    def get_trade(self, trade_id: str) -> Optional[Trade]:
        """
        Get trade by ID
        
        Args:
            trade_id: Trade identifier
            
        Returns:
            Trade object or None if not found
        """
        return self.trades.get(trade_id)
    
    def get_trade_by_ticket(self, mt5_ticket: int) -> Optional[Trade]:
        """
        Get trade by MT5 ticket number
        
        Args:
            mt5_ticket: MT5 ticket number
            
        Returns:
            Trade object or None if not found
        """
        for trade in self.trades.values():
            if trade.mt5_ticket == mt5_ticket:
                return trade
        return None
    
    def get_active_trades(self) -> List[Trade]:
        """
        Get all active trades
        
        Returns:
            List of active Trade objects
        """
        return [
            trade for trade in self.trades.values()
            if trade.status == TradeStatus.ACTIVE.value
        ]
    
    def get_trades_by_pair(self, pair: str) -> List[Trade]:
        """
        Get all active trades for a specific pair
        
        Args:
            pair: Trading pair (e.g., EURUSD)
            
        Returns:
            List of Trade objects for the pair
        """
        return [
            trade for trade in self.get_active_trades()
            if trade.pair.upper() == pair.upper()
        ]
    
    def get_trades_by_status(self, status: TradeStatus) -> List[Trade]:
        """
        Get trades by status
        
        Args:
            status: TradeStatus enum value
            
        Returns:
            List of Trade objects with specified status
        """
        return [
            trade for trade in self.trades.values()
            if trade.status == status.value
        ]
    
    def get_recent_trades(self, count: int = 10) -> List[Trade]:
        """
        Get most recent trades
        
        Args:
            count: Number of trades to return
            
        Returns:
            List of recent Trade objects, sorted by creation time
        """
        sorted_trades = sorted(
            self.trades.values(),
            key=lambda t: t.created_at,
            reverse=True
        )
        return sorted_trades[:count]
    
    def update_trade(self, trade_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update trade with new information
        
        Args:
            trade_id: Trade identifier
            updates: Dictionary of fields to update
            
        Returns:
            True if successful, False if trade not found
        """
        trade = self.get_trade(trade_id)
        if not trade:
            return False
        
        # Update fields
        for key, value in updates.items():
            if hasattr(trade, key):
                setattr(trade, key, value)
        
        # Update timestamp
        trade.updated_at = datetime.now().isoformat()
        
        # Persist changes
        self.save_trades()
        
        return True
    
    def close_trade(self, trade_id: str, exit_price: float, profit_loss: float = 0.0) -> bool:
        """
        Close a trade
        
        Args:
            trade_id: Trade identifier
            exit_price: Exit price
            profit_loss: Profit/loss amount
            
        Returns:
            True if successful, False if trade not found
        """
        trade = self.get_trade(trade_id)
        if not trade:
            return False
        
        trade.close(exit_price, profit_loss)
        self.save_trades()
        
        return True
    
    def delete_trade(self, trade_id: str) -> bool:
        """
        Delete a trade (use with caution)
        
        Args:
            trade_id: Trade identifier
            
        Returns:
            True if deleted, False if not found
        """
        if trade_id in self.trades:
            del self.trades[trade_id]
            self.save_trades()
            return True
        return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get trading statistics
        
        Returns:
            Dictionary containing statistics
        """
        all_trades = list(self.trades.values())
        active_trades = self.get_active_trades()
        closed_trades = self.get_trades_by_status(TradeStatus.CLOSED)
        
        # Calculate P&L for closed trades
        total_pnl = sum(
            trade.profit_loss for trade in closed_trades
            if trade.profit_loss is not None
        )
        
        winning_trades = [
            trade for trade in closed_trades
            if trade.profit_loss and trade.profit_loss > 0
        ]
        
        losing_trades = [
            trade for trade in closed_trades
            if trade.profit_loss and trade.profit_loss < 0
        ]
        
        return {
            'total_trades': len(all_trades),
            'active_trades': len(active_trades),
            'closed_trades': len(closed_trades),
            'total_pnl': total_pnl,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': (len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0,
        }
    
    def get_context_for_llm(self) -> List[Dict[str, Any]]:
        """
        Get trade context formatted for LLM consumption
        
        Returns:
            List of active trades in simplified format for LLM
        """
        active_trades = self.get_active_trades()
        
        context = []
        for trade in active_trades:
            context.append({
                'trade_id': trade.trade_id,
                'pair': trade.pair,
                'action': trade.action,
                'entry_price': trade.entry_price,
                'stop_loss': trade.stop_loss,
                'take_profit': trade.take_profit,
                'lot_size': trade.lot_size,
                'age_seconds': trade.get_age_seconds(),
                'original_message': trade.original_message[:100]  # First 100 chars
            })
        
        return context
    
    def save_trades(self):
        """Save all trades to JSON file"""
        trades_dict = {
            trade_id: trade.to_dict()
            for trade_id, trade in self.trades.items()
        }
        
        with open(self.storage_file, 'w') as f:
            json.dump(trades_dict, f, indent=2)
    
    def load_trades(self):
        """Load trades from JSON file"""
        if not self.storage_file.exists():
            return
        
        try:
            with open(self.storage_file, 'r') as f:
                trades_dict = json.load(f)
            
            self.trades = {
                trade_id: Trade.from_dict(trade_data)
                for trade_id, trade_data in trades_dict.items()
            }
        except Exception as e:
            print(f"Warning: Could not load trades from {self.storage_file}: {e}")
            self.trades = {}
    
    def clear_all_trades(self):
        """Clear all trades (use with caution - mainly for testing)"""
        self.trades = {}
        self.save_trades()


# Example usage and testing
if __name__ == "__main__":
    # Create trade manager
    manager = TradeManager(storage_file="data/test_trades.json")
    
    # Create a test trade
    trade_data = {
        'pair': 'EURUSD',
        'action': 'BUY',
        'entry_price': 1.0850,
        'stop_loss': 1.0800,
        'take_profit': 1.0950,
        'lot_size': 0.1,
        'original_message': 'EURUSD BUY at 1.0850, SL 1.0800, TP 1.0950',
        'telegram_msg_id': 12345
    }
    
    print("Creating test trade...")
    trade = manager.add_trade(trade_data)
    print(f"✓ Created: {trade}")
    
    # Update MT5 ticket
    print("\nUpdating MT5 ticket...")
    manager.update_trade(trade.trade_id, {'mt5_ticket': 67890})
    print(f"✓ Updated ticket to: {trade.mt5_ticket}")
    
    # Modify stop loss
    print("\nModifying stop loss...")
    trade.update_stop_loss(1.0825)
    manager.save_trades()
    print(f"✓ New SL: {trade.stop_loss}")
    
    # Get active trades
    print("\nActive trades:")
    for t in manager.get_active_trades():
        print(f"  {t}")
    
    # Get LLM context
    print("\nLLM Context:")
    context = manager.get_context_for_llm()
    print(json.dumps(context, indent=2))
    
    # Statistics
    print("\nStatistics:")
    stats = manager.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Close trade
    print("\nClosing trade...")
    manager.close_trade(trade.trade_id, exit_price=1.0920, profit_loss=70.0)
    print(f"✓ Trade closed: {trade.status}")
    
    print("\n✓ All tests passed!")
