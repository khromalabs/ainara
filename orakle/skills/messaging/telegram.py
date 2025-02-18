from typing import Any, Dict

import telegram

from ainara.framework.skill import Skill
from ainara.framework.config import config


class MessagingTelegram(Skill):
    """Skill for interacting with Telegram API"""

    def __init__(self):
        super().__init__()
        self.name = "messaging.telegram"
        self.description = "Send and receive messages via Telegram"
        self.examples = [
            "Send a Telegram message to @username saying 'Hello!'",
            "Check my latest Telegram messages",
            "Reply to the last Telegram message with 'Thanks!'",
        ]

        # Initialize bot with token from config
        self.bot = None
        self.config = config
        if self.config.get("telegram_token"):
            self.bot = telegram.Bot(token=self.config["telegram_token"])

    async def send_message(self, chat_id: str, text: str) -> Dict[str, Any]:
        """Send a message to a specific chat"""
        if not self.bot:
            return {"error": "Telegram bot not configured"}

        try:
            message = await self.bot.send_message(chat_id=chat_id, text=text)
            return {
                "success": True,
                "message_id": message.message_id,
                "chat_id": chat_id,
            }
        except Exception as e:
            return {"error": str(e)}

    async def get_updates(self, limit: int = 10) -> Dict[str, Any]:
        """Get recent messages/updates"""
        if not self.bot:
            return {"error": "Telegram bot not configured"}

        try:
            updates = await self.bot.get_updates(limit=limit)
            return {
                "success": True,
                "updates": [
                    {
                        "message_id": update.message.message_id,
                        "chat_id": update.message.chat_id,
                        "text": update.message.text,
                        "date": update.message.date.isoformat(),
                    }
                    for update in updates
                    if update.message
                ],
            }
        except Exception as e:
            return {"error": str(e)}

    async def run(self, action: str, **kwargs) -> Dict[str, Any]:
        """Main entry point for the skill"""
        if action == "send_message":
            return await self.send_message(
                kwargs.get("chat_id"), kwargs.get("text", "")
            )
        elif action == "get_updates":
            return await self.get_updates(limit=int(kwargs.get("limit", 10)))
        else:
            return {"error": f"Unknown action: {action}"}
