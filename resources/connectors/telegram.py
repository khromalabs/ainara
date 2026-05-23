# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

import logging
from typing import Any, Dict, List, Optional

try:
    from telethon import TelegramClient
    from telethon.tl.types import User, Chat, Channel
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

from ainara.framework.connectors.base import BaseConnector, capability

logger = logging.getLogger(__name__)


class TelegramConnector(BaseConnector):
    """
    A connector for Telegram using MTProto (Telethon).
    Acts as a Userbot (representing the user), allowing access to
    private history and sending messages as the user.
    """

    # TODO Disabled by now
    hiddenConnector = True

    @property
    def MANIFEST(self) -> Dict[str, Any]:
        return {
            "id": "telegram",
            "version": "1.0",
            "description": "Telegram MTProto Connector (Userbot)",
            "capabilities": ["messages", "channels"],
            "required_config": [
                "apis.messaging.telegram.api_id",
                "apis.messaging.telegram.api_hash",
                "apis.messaging.telegram.session_path"
            ],
        }

    def initialize(self):
        """
        Initialize the connector configuration.
        Actual connection is deferred until the first capability call.
        """
        if not TELETHON_AVAILABLE:
            logger.error("Telethon is not installed. Telegram connector disabled.")
            return

        self.api_id = self.config.get("apis.messaging.telegram.api_id")
        self.api_hash = self.config.get("apis.messaging.telegram.api_hash")
        self.session_path = self.config.get("apis.messaging.telegram.session_path")

        # Client is initialized lazily
        self.client: Optional['TelegramClient'] = None

    async def _ensure_client(self) -> 'TelegramClient':
        """
        Lazy initialization and connection of the Telegram Client.
        Assumes the session file is already authenticated via external wizard.
        """
        if not TELETHON_AVAILABLE:
            raise ImportError("Telethon library is missing.")

        if self.client is None:
            logger.info(f"Initializing Telegram Client with session: {self.session_path}")
            self.client = TelegramClient(
                self.session_path,
                self.api_id,
                self.api_hash
            )

        if not self.client.is_connected():
            await self.client.connect()

        if not await self.client.is_user_authorized():
            # We do not handle interactive login here.
            # It must be done via the setup wizard.
            await self.client.disconnect()
            raise PermissionError(
                "Telegram session is not authorized. Please authenticate via the setup wizard."
            )

        return self.client

    def _format_message(self, message, chat_id=None) -> Dict[str, Any]:
        """Helper to format a Telethon message object to the contract format."""
        if not message:
            return {}

        # Determine sender name
        sender_name = "Unknown"
        if message.sender:
            if isinstance(message.sender, User):
                sender_name = f"{message.sender.first_name or ''} {message.sender.last_name or ''}".strip()
                if not sender_name:
                    sender_name = message.sender.username or "Unknown User"
            elif isinstance(message.sender, (Chat, Channel)):
                sender_name = message.sender.title

        # Determine Chat ID if not provided
        if not chat_id:
            chat_id = message.chat_id

        # Create a composite ID (chat_id:msg_id) to uniquely identify messages globally
        # This is necessary because message IDs are only unique within a chat in Telegram
        composite_id = f"{chat_id}:{message.id}"

        return {
            "id": composite_id,
            "source": "telegram",
            "sender": sender_name,
            "sender_id": str(message.sender_id) if message.sender_id else None,
            "target_id": str(chat_id),
            "content": message.text or "[Media/System Message]",
            "timestamp": message.date.timestamp(),
            "is_read": not message.media_unread,  # Approximation, or check dialog status
            "metadata": {
                "is_group": message.is_group,
                "is_channel": message.is_channel,
                "is_private": message.is_private,
            }
        }

    # -------------------------------------------------------------------------
    # Capability: Messages
    # -------------------------------------------------------------------------

    @capability(contract="messages", path="/messages", method="GET")
    async def get_messages(
        self,
        limit: int = 0,
        unread_only: bool = True,
        source: str = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent messages.
        In Telegram context, this fetches the latest message from active dialogs (Inbox view).
        """
        if source and source != "telegram":
            return []

        client = await self._ensure_client()
        results = []

        # If limit is 0, default to a reasonable number for an inbox check
        fetch_limit = limit if limit > 0 else 20

        # Iterate over dialogs (conversations)
        async for dialog in client.iter_dialogs(limit=fetch_limit):
            if unread_only and dialog.unread_count == 0:
                continue

            # The dialog.message is the last message in the chat
            msg_data = self._format_message(dialog.message, chat_id=dialog.id)

            # Enrich with unread count info
            msg_data["unread_count"] = dialog.unread_count
            msg_data["is_read"] = dialog.unread_count == 0

            results.append(msg_data)

        return results

    @capability(contract="messages", path="/messages", method="POST")
    async def send_message(
        self, target_id: str, content: str, **kwargs
    ) -> Dict[str, str]:
        """
        Send a message to a user or chat.
        target_id can be a numeric ID (as string) or a username (e.g. @username).
        """
        client = await self._ensure_client()

        # Resolve target
        try:
            # Try converting to int if it looks like an ID
            entity = int(target_id)
        except ValueError:
            # Otherwise treat as username/string
            entity = target_id

        sent_msg = await client.send_message(entity, content)

        composite_id = f"{sent_msg.chat_id}:{sent_msg.id}"
        return {"status": "sent", "message_id": composite_id}

    @capability(contract="messages", path="/messages/{id}", method="GET")
    async def get_message_details(self, id: str, **kwargs) -> Dict[str, Any]:
        """
        Get details of a specific message.
        Expects ID format: 'chat_id:message_id'
        """
        client = await self._ensure_client()

        try:
            chat_id_str, msg_id_str = id.split(":")
            chat_id = int(chat_id_str)
            msg_id = int(msg_id_str)
        except ValueError:
            logger.error(f"Invalid Telegram message ID format: {id}. Expected 'chat_id:msg_id'")
            return {}

        message = await client.get_messages(chat_id, ids=msg_id)
        if not message:
            return {}

        return self._format_message(message, chat_id=chat_id)

    @capability(contract="messages", path="/messages/{id}", method="PUT")
    async def update_message_status(
        self, id: str, is_read: bool, **kwargs
    ) -> Dict[str, Any]:
        """
        Update message status. Currently only supports marking as read.
        Expects ID format: 'chat_id:message_id'
        """
        if not is_read:
            # Telegram doesn't support "marking as unread" via API easily for single messages
            return {"status": "ignored", "reason": "cannot_mark_unread"}

        client = await self._ensure_client()

        try:
            chat_id_str, msg_id_str = id.split(":")
            chat_id = int(chat_id_str)
            msg_id = int(msg_id_str)
        except ValueError:
            return {"status": "error", "message": "Invalid ID format"}

        # Send read acknowledgment up to this message
        await client.send_read_acknowledge(chat_id, max_id=msg_id)

        return {"status": "updated", "id": id, "is_read": True}

    # -------------------------------------------------------------------------
    # Capability: Channels (History)
    # -------------------------------------------------------------------------

    @capability(contract="channels", path="/channels/{id}/messages", method="GET")
    async def get_channel_history(
        self, id: str, limit: int = 50, **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Get history of a specific chat/channel.
        """
        client = await self._ensure_client()

        try:
            entity = int(id)
        except ValueError:
            entity = id

        results = []
        async for message in client.iter_messages(entity, limit=limit):
            results.append(self._format_message(message, chat_id=entity))

        return results

    @capability(contract="channels", path="/channels/{id}/messages", method="POST")
    async def send_to_channel(
        self, id: str, content: str, **kwargs
    ) -> Dict[str, Any]:
        """
        Send a message to a specific channel/chat (Alias for send_message).
        """
        # Re-use the logic from send_message
        return await self.send_message(target_id=id, content=content)
