"""
LLM Interpreter - Uses Anthropic Claude to interpret trading signals from messages
"""

import json
import logging
from typing import Optional, Dict, Any, List, Union
from anthropic import Anthropic
from pydantic import BaseModel, Field


# ============================================================================
# Pydantic Models for LLM Output Schemas
# ============================================================================

class NewSignal(BaseModel):
    """Schema for a new trading signal"""
    signal_type: str = Field(default="new_signal", description="Type of signal")
    pair: str = Field(..., description="Trading pair (e.g., EURUSD)")
    action: str = Field(..., description="BUY or SELL")
    entry_price: float = Field(..., description="Entry price")
    stop_loss: float = Field(..., description="Stop loss price")
    take_profit: float = Field(..., description="Take profit price")
    lot_size: Optional[float] = Field(None, description="Position size in lots")
    execution_type: str = Field(default="immediate", description="immediate, pending, or conditional")
    confidence: float = Field(..., description="Confidence score 0-1")
    reasoning: str = Field(..., description="Explanation of interpretation")


class ModifySignal(BaseModel):
    """Schema for modifying an existing trade"""
    signal_type: str = Field(default="modify", description="Type of signal")
    action_type: str = Field(..., description="modify_sl, modify_tp, or modify_both")
    trade_reference: Optional[str] = Field(None, description="Reference to which trade (pair name or description)")
    new_stop_loss: Optional[float] = Field(None, description="New stop loss price")
    new_take_profit: Optional[float] = Field(None, description="New take profit price")
    confidence: float = Field(..., description="Confidence score 0-1")
    reasoning: str = Field(..., description="Explanation of interpretation")


class CloseSignal(BaseModel):
    """Schema for closing a trade"""
    signal_type: str = Field(default="close", description="Type of signal")
    action_type: str = Field(default="close", description="close or partial_close")
    trade_reference: Optional[str] = Field(None, description="Reference to which trade")
    close_percent: Optional[float] = Field(100.0, description="Percentage to close (100 = full close)")
    confidence: float = Field(..., description="Confidence score 0-1")
    reasoning: str = Field(..., description="Explanation of interpretation")


class NoSignal(BaseModel):
    """Schema for non-trading messages"""
    signal_type: str = Field(default="none", description="Type of signal")
    confidence: float = Field(..., description="Confidence score 0-1")
    reasoning: str = Field(..., description="Explanation why this is not a signal")


# Union type for all possible signal types
SignalResponse = Union[NewSignal, ModifySignal, CloseSignal, NoSignal]


class LLMInterpreter:
    """
    Interprets trading signals from Telegram messages using Anthropic Claude
    """
    
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514", 
                 temperature: float = 0.1, max_tokens: int = 2000):
        """
        Initialize LLM interpreter
        
        Args:
            api_key: Anthropic API key
            model: Model name to use
            temperature: Temperature for generation (lower = more consistent)
            max_tokens: Maximum tokens to generate
        """
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.logger = logging.getLogger('TradingBot.LLM')
    
    def _create_tools(self) -> List[Dict[str, Any]]:
        """
        Create tool definitions for structured output
        
        Returns:
            List of tool definitions
        """
        return [
            {
                "name": "report_new_signal",
                "description": "Report a new trading signal found in the message",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pair": {
                            "type": "string",
                            "description": "Trading pair (e.g., EURUSD, GBPUSD, XAUUSD)"
                        },
                        "action": {
                            "type": "string",
                            "enum": ["BUY", "SELL"],
                            "description": "Trading direction"
                        },
                        "entry_price": {
                            "type": "number",
                            "description": "Entry price for the trade"
                        },
                        "stop_loss": {
                            "type": "number",
                            "description": "Stop loss price"
                        },
                        "take_profit": {
                            "type": "number",
                            "description": "Take profit price"
                        },
                        "lot_size": {
                            "type": "number",
                            "description": "Position size in lots (if specified)"
                        },
                        "execution_type": {
                            "type": "string",
                            "enum": ["immediate", "pending", "conditional"],
                            "description": "When to execute the trade"
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score between 0 and 1"
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Explanation of the interpretation"
                        }
                    },
                    "required": ["pair", "action", "entry_price", "stop_loss", "take_profit", "confidence", "reasoning"]
                }
            },
            {
                "name": "report_modify_signal",
                "description": "Report an instruction to modify an existing trade",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action_type": {
                            "type": "string",
                            "enum": ["modify_sl", "modify_tp", "modify_both"],
                            "description": "What to modify"
                        },
                        "trade_reference": {
                            "type": "string",
                            "description": "Reference to which trade (e.g., 'EURUSD', 'EUR trade', 'the gold position')"
                        },
                        "new_stop_loss": {
                            "type": "number",
                            "description": "New stop loss price (if modifying SL)"
                        },
                        "new_take_profit": {
                            "type": "number",
                            "description": "New take profit price (if modifying TP)"
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score between 0 and 1"
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Explanation of the interpretation"
                        }
                    },
                    "required": ["action_type", "confidence", "reasoning"]
                }
            },
            {
                "name": "report_close_signal",
                "description": "Report an instruction to close an existing trade",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action_type": {
                            "type": "string",
                            "enum": ["close", "partial_close"],
                            "description": "Full or partial close"
                        },
                        "trade_reference": {
                            "type": "string",
                            "description": "Reference to which trade"
                        },
                        "close_percent": {
                            "type": "number",
                            "description": "Percentage to close (100 for full close)"
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score between 0 and 1"
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Explanation of the interpretation"
                        }
                    },
                    "required": ["action_type", "confidence", "reasoning"]
                }
            },
            {
                "name": "report_no_signal",
                "description": "Report that the message does not contain a trading signal",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score between 0 and 1"
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Explanation why this is not a signal"
                        }
                    },
                    "required": ["confidence", "reasoning"]
                }
            }
        ]
    
    def _build_context_message(self, active_trades: List[Dict[str, Any]]) -> str:
        """
        Build context message about active trades
        
        Args:
            active_trades: List of active trade dictionaries
            
        Returns:
            Formatted context string
        """
        if not active_trades:
            return "No active trades."
        
        context = "Active trades:\n"
        for i, trade in enumerate(active_trades, 1):
            context += (f"{i}. {trade['action']} {trade['pair']} @ {trade['entry_price']} "
                       f"(SL: {trade['stop_loss']}, TP: {trade['take_profit']}, "
                       f"Lot: {trade['lot_size']})\n")
        
        return context
    
    def interpret_message(self, 
                         message: str, 
                         active_trades: Optional[List[Dict[str, Any]]] = None,
                         system_prompt: Optional[str] = None) -> Optional[SignalResponse]:
        """
        Interpret a telegram message to extract trading signal
        
        Args:
            message: Message text to interpret
            active_trades: List of active trades for context
            system_prompt: Custom system prompt (uses default if None)
            
        Returns:
            SignalResponse object or None if interpretation failed
        """
        if active_trades is None:
            active_trades = []
        
        # Build context about active trades
        context = self._build_context_message(active_trades)
        
        # Default system prompt if not provided
        if system_prompt is None:
            system_prompt = """You are an expert trading signal interpreter. Your job is to analyze messages from a Telegram trading group and determine if they contain valid trading signals.

A valid NEW trading signal must include:
- Currency pair (e.g., EURUSD, GBPUSD, XAUUSD)
- Direction (BUY/SELL or LONG/SHORT)
- Entry price or range
- Stop Loss (SL)
- Take Profit (TP)

A MODIFY signal includes instructions like:
- "Move SL to breakeven"
- "Close 50% at current price"
- "Adjust TP to X.XXXX"

A CLOSE signal includes instructions like:
- "Close all positions"
- "Exit the EUR trade"
- "Take profit now"

Use the provided tools to report your findings. Always provide your confidence level and reasoning."""
        
        # Prepare messages
        messages = [
            {
                "role": "user",
                "content": f"{context}\n\nNew message to analyze:\n{message}\n\nAnalyze this message and use the appropriate tool to report your findings."
            }
        ]
        
        try:
            # Call Claude with tools
            self.logger.info(f"Interpreting message: {message[:100]}...")
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system_prompt,
                tools=self._create_tools(),
                messages=messages
            )
            
            # Extract tool use from response
            tool_use = None
            for block in response.content:
                if block.type == "tool_use":
                    tool_use = block
                    break
            
            if tool_use is None:
                self.logger.warning("No tool use found in response")
                return None
            
            # Parse tool response into appropriate schema
            tool_name = tool_use.name
            tool_input = tool_use.input
            
            if tool_name == "report_new_signal":
                result = NewSignal(**tool_input)
                self.logger.info(f"Detected NEW signal: {result.pair} {result.action}")
                
            elif tool_name == "report_modify_signal":
                result = ModifySignal(**tool_input, signal_type="modify")
                self.logger.info(f"Detected MODIFY signal: {result.action_type}")
                
            elif tool_name == "report_close_signal":
                result = CloseSignal(**tool_input, signal_type="close")
                self.logger.info(f"Detected CLOSE signal: {result.action_type}")
                
            elif tool_name == "report_no_signal":
                result = NoSignal(**tool_input, signal_type="none")
                self.logger.info("No trading signal detected")
            
            else:
                self.logger.warning(f"Unknown tool: {tool_name}")
                return None
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error interpreting message: {e}")
            return None


# Example usage and testing
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Load environment variables
    load_dotenv()
    api_key = os.getenv('ANTHROPIC_API_KEY')
    
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not found in environment")
        print("Please create a .env file with your API key")
        exit(1)
    
    print("LLM Interpreter Test")
    print("=" * 70)
    
    # Create interpreter
    interpreter = LLMInterpreter(api_key=api_key)
    
    # Test messages
    test_messages = [
        {
            "message": "EURUSD BUY at 1.0850, SL 1.0800, TP 1.0950",
            "active_trades": []
        },
        {
            "message": "Gold looking bullish today, expecting a move higher",
            "active_trades": []
        },
        {
            "message": "Move SL to breakeven on the EUR trade",
            "active_trades": [
                {
                    "pair": "EURUSD",
                    "action": "BUY",
                    "entry_price": 1.0850,
                    "stop_loss": 1.0800,
                    "take_profit": 1.0950,
                    "lot_size": 0.1
                }
            ]
        },
        {
            "message": "Close 50% of EURUSD position",
            "active_trades": [
                {
                    "pair": "EURUSD",
                    "action": "BUY",
                    "entry_price": 1.0850,
                    "stop_loss": 1.0825,
                    "take_profit": 1.0950,
                    "lot_size": 0.1
                }
            ]
        }
    ]
    
    # Test each message
    for i, test in enumerate(test_messages, 1):
        print(f"\nTest {i}:")
        print(f"Message: {test['message']}")
        print(f"Active trades: {len(test['active_trades'])}")
        
        result = interpreter.interpret_message(
            test['message'],
            test['active_trades']
        )
        
        if result:
            print(f"\nResult:")
            print(f"  Type: {result.signal_type}")
            print(f"  Confidence: {result.confidence}")
            print(f"  Reasoning: {result.reasoning}")
            
            if isinstance(result, NewSignal):
                print(f"  Pair: {result.pair}")
                print(f"  Action: {result.action}")
                print(f"  Entry: {result.entry_price}")
                print(f"  SL: {result.stop_loss}")
                print(f"  TP: {result.take_profit}")
            
            elif isinstance(result, ModifySignal):
                print(f"  Action: {result.action_type}")
                if result.new_stop_loss:
                    print(f"  New SL: {result.new_stop_loss}")
                if result.new_take_profit:
                    print(f"  New TP: {result.new_take_profit}")
            
            elif isinstance(result, CloseSignal):
                print(f"  Close %: {result.close_percent}")
        else:
            print("  Failed to interpret message")
        
        print("-" * 70)
    
    print("\n✓ Tests completed")
