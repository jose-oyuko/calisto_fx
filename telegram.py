"""
Telegram Client - Handles Telegram connection and message listening
"""

import logging
import asyncio
from typing import Optional, List, Callable, Dict, Any
from telethon import TelegramClient as TelethonClient, events
from telethon.tl.types import User, Chat, Channel


class TelegramListener:
    """
    Telegram client for listening to group messages
    """
    
    def __init__(self, api_id: int, api_hash: str, phone: str, 
                 session_name: str = "trading_bot_session"):
        """
        Initialize Telegram listener
        
        Args:
            api_id: Telegram API ID
            api_hash: Telegram API hash
            phone: Phone number for authentication
            session_name: Session file name
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.session_name = session_name
        
        self.client: Optional[TelethonClient] = None
        self.is_connected = False
        self.is_listening = False
        self.selected_chat_id: Optional[int] = None
        self.message_callback: Optional[Callable] = None
        
        self.logger = logging.getLogger('TradingBot.Telegram')
    
    async def connect(self) -> bool:
        """
        Connect and authenticate to Telegram
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.client = TelethonClient(self.session_name, self.api_id, self.api_hash)
            
            self.logger.info("Connecting to Telegram...")
            await self.client.connect()
            
            # Check if already authorized
            if not await self.client.is_user_authorized():
                self.logger.info("Not authorized, sending code request...")
                await self.client.send_code_request(self.phone)
                
                # Prompt for code (in real implementation, this should be handled by main.py)
                print(f"\nPlease enter the code sent to {self.phone}:")
                code = input("Code: ")
                
                try:
                    await self.client.sign_in(self.phone, code)
                except Exception as e:
                    # If two-factor auth is enabled
                    if "password" in str(e).lower():
                        password = input("2FA Password: ")
                        await self.client.sign_in(password=password)
                    else:
                        raise e
            
            # Get user info
            me = await self.client.get_me()
            self.is_connected = True
            self.logger.info(f"Connected as: {me.first_name} (@{me.username})")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to connect to Telegram: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from Telegram"""
        if self.client:
            await self.client.disconnect()
            self.is_connected = False
            self.is_listening = False
            self.logger.info("Disconnected from Telegram")
    
    async def get_dialogs(self) -> List[Dict[str, Any]]:
        """
        Get list of all chats/groups
        
        Returns:
            List of dialog dictionaries with id, title, and type
        """
        if not self.is_connected:
            self.logger.error("Not connected to Telegram")
            return []
        
        try:
            dialogs = []
            async for dialog in self.client.iter_dialogs():
                entity = dialog.entity
                
                # Determine chat type
                if isinstance(entity, User):
                    chat_type = "User"
                elif isinstance(entity, Chat):
                    chat_type = "Group"
                elif isinstance(entity, Channel):
                    chat_type = "Channel" if entity.broadcast else "Supergroup"
                else:
                    chat_type = "Unknown"
                
                dialogs.append({
                    'id': dialog.id,
                    'title': dialog.title or dialog.name,
                    'type': chat_type,
                    'entity': entity
                })
            
            return dialogs
            
        except Exception as e:
            self.logger.error(f"Failed to get dialogs: {e}")
            return []
    
    def set_message_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """
        Set callback function for new messages
        
        Args:
            callback: Function to call with message data
        """
        self.message_callback = callback
    
    async def start_listening(self, chat_id: int) -> bool:
        """
        Start listening to messages from a specific chat
        
        Args:
            chat_id: Chat/group ID to listen to
            
        Returns:
            True if started successfully
        """
        if not self.is_connected:
            self.logger.error("Not connected to Telegram")
            return False
        
        if self.is_listening:
            self.logger.warning("Already listening to messages")
            return True
        
        self.selected_chat_id = chat_id
        
        # Register event handler for new messages
        @self.client.on(events.NewMessage(chats=chat_id))
        async def message_handler(event):
            """Handle incoming messages"""
            if not self.is_listening:
                return
            
            try:
                # Extract message data
                message_data = {
                    'message_id': event.id,
                    'text': event.message.message,
                    'date': event.message.date,
                    'sender_id': event.sender_id,
                    'chat_id': event.chat_id,
                    'is_reply': event.message.reply_to is not None,
                }
                
                # Get sender info if available
                try:
                    sender = await event.get_sender()
                    if sender:
                        message_data['sender_name'] = getattr(sender, 'first_name', 'Unknown')
                        message_data['sender_username'] = getattr(sender, 'username', None)
                except:
                    pass
                
                self.logger.info(f"New message: {message_data['text'][:50]}...")
                
                # Call callback if set
                if self.message_callback:
                    # Run callback in a way that doesn't block the event loop
                    asyncio.create_task(self._async_callback_wrapper(message_data))
                
            except Exception as e:
                self.logger.error(f"Error handling message: {e}")
        
        self.is_listening = True
        self.logger.info(f"Started listening to chat ID: {chat_id}")
        
        return True
    
    async def _async_callback_wrapper(self, message_data: Dict[str, Any]):
        """
        Wrapper to handle callback execution
        
        Args:
            message_data: Message data dictionary
        """
        try:
            # If callback is a coroutine
            if asyncio.iscoroutinefunction(self.message_callback):
                await self.message_callback(message_data)
            else:
                # Run synchronous callback in executor to avoid blocking
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.message_callback, message_data)
        except Exception as e:
            self.logger.error(f"Error in message callback: {e}")
    
    def stop_listening(self):
        """Stop listening to messages"""
        self.is_listening = False
        self.logger.info("Stopped listening to messages")
    
    def resume_listening(self):
        """Resume listening to messages"""
        if self.selected_chat_id:
            self.is_listening = True
            self.logger.info("Resumed listening to messages")
    
    async def send_message(self, chat_id: int, text: str) -> bool:
        """
        Send a message to a chat
        
        Args:
            chat_id: Chat ID to send to
            text: Message text
            
        Returns:
            True if successful
        """
        if not self.is_connected:
            self.logger.error("Not connected to Telegram")
            return False
        
        try:
            await self.client.send_message(chat_id, text)
            self.logger.info(f"Message sent to chat {chat_id}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send message: {e}")
            return False
    
    async def run_until_disconnected(self):
        """Keep the client running until disconnected"""
        if self.client and self.is_connected:
            await self.client.run_until_disconnected()


# Synchronous wrapper functions for easier integration
class TelegramClient:
    """
    Synchronous wrapper around TelegramListener for easier use
    """
    
    def __init__(self, api_id: int, api_hash: str, phone: str):
        """
        Initialize Telegram client
        
        Args:
            api_id: Telegram API ID
            api_hash: Telegram API hash
            phone: Phone number
        """
        # Convert to integers/strings if needed
        self.api_id = int(api_id) if not isinstance(api_id, int) else api_id
        self.api_hash = str(api_hash)
        self.phone = str(phone)
        
        self.listener = TelegramListener(self.api_id, self.api_hash, self.phone)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.logger = logging.getLogger('TradingBot.TelegramClient')
    
    def _ensure_loop(self):
        """Ensure event loop exists"""
        if self.loop is None or self.loop.is_closed():
            try:
                self.loop = asyncio.get_event_loop()
            except RuntimeError:
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
    
    def _run_async(self, coro):
        """Run async function synchronously"""
        self._ensure_loop()
        return self.loop.run_until_complete(coro)
    
    def connect(self) -> bool:
        """Connect to Telegram"""
        return self._run_async(self.listener.connect())
    
    def disconnect(self):
        """Disconnect from Telegram"""
        self._run_async(self.listener.disconnect())
    
    def get_dialogs(self) -> List[Dict[str, Any]]:
        """Get list of chats/groups"""
        return self._run_async(self.listener.get_dialogs())
    
    def set_message_callback(self, callback: Callable):
        """Set message callback function"""
        self.listener.set_message_callback(callback)
    
    def start_listening(self, chat_id: int) -> bool:
        """Start listening to messages"""
        return self._run_async(self.listener.start_listening(chat_id))
    
    def stop_listening(self):
        """Stop listening to messages"""
        self.listener.stop_listening()
    
    def resume_listening(self):
        """Resume listening to messages"""
        self.listener.resume_listening()
    
    def run_until_disconnected(self):
        """Keep client running"""
        self._run_async(self.listener.run_until_disconnected())


# Example usage and testing
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load environment variables
    load_dotenv()
    
    api_id = os.getenv('TELEGRAM_API_ID')
    api_hash = os.getenv('TELEGRAM_API_HASH')
    phone = os.getenv('TELEGRAM_PHONE')
    
    if not all([api_id, api_hash, phone]):
        print("Error: Telegram credentials not found in .env file")
        print("Please set TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_PHONE")
        exit(1)
    
    print("Telegram Client Test")
    print("=" * 70)
    print(f"the api hash is {api_hash} and api id is {api_id} and the phone is {phone}")
    # Create client
    client = TelegramClient(api_id, api_hash, phone)
    
    # Connect
    print("\n1. Connecting to Telegram...")
    if client.connect():
        print("✓ Connected successfully")
    else:
        print("✗ Connection failed")
        exit(1)
    
    # Get dialogs
    print("\n2. Fetching chats/groups...")
    dialogs = client.get_dialogs()
    print(f"✓ Found {len(dialogs)} chats")
    
    # Display some dialogs
    print("\nFirst 10 chats:")
    for i, dialog in enumerate(dialogs[:10], 1):
        print(f"  {i}. [{dialog['type']}] {dialog['title']} (ID: {dialog['id']})")
    
    # Disconnect
    print("\n3. Disconnecting...")
    client.disconnect()
    print("✓ Disconnected")
    
    print("\n" + "=" * 70)
    print("Test completed successfully!")
