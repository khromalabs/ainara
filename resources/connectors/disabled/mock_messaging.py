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
import time
import uuid
from typing import Any, Dict, List

from ainara.framework.connectors.base import BaseConnector, capability

logger = logging.getLogger(__name__)


class MockMessagingConnector(BaseConnector):
    """
    A mock connector implementing the 'messages' contract.
    Used for testing the Virtual Router architecture without external dependencies.
    """

    @property
    def MANIFEST(self) -> Dict[str, Any]:
        return {
            "id": "mock_messaging",
            "version": "1.0",
            "description": "In-memory mock for messaging contract testing",
            "capabilities": ["messages"],
            # "required_config": [],
        }

    def initialize(self):
        """
        Populate with some dummy data.
        """
        self.messages = [
            {
                "id": "msg_1",
                "source": "mock",
                "sender": "Alice",
                "content": "Hey, are we still on for the meeting?",
                "timestamp": time.time() - 3600,
                "is_read": False,
            },
            {
                "id": "msg_2",
                "source": "mock",
                "sender": "Bob",
                "content": "Project update attached.",
                "timestamp": time.time() - 7200,
                "is_read": True,
            },
            {
                "id": "msg_3",
                "source": "mock",
                "sender": "Charlie",
                "content": "Lunch?",
                "timestamp": time.time() - 1800,
                "is_read": False,
            },
        ]
        logger.info(
            "MockMessagingConnector initialized with"
            f" {len(self.messages)} messages."
        )

    @capability(contract="messages", path="/messages", method="GET")
    def get_messages(
        self,
        limit: int = 0,
        unread_only: bool = True,
        source: str = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve messages based on filters.
        """
        logger.debug(
            f"Mock get_messages called with limit={limit},"
            f" unread_only={unread_only}"
        )

        # Filter by source if specified
        if source and source != "mock":
            return []

        results = self.messages

        # Filter by read status
        if unread_only:
            results = [m for m in results if not m["is_read"]]

        # Sort by timestamp descending (newest first)
        results = sorted(results, key=lambda x: x["timestamp"], reverse=True)

        # Apply limit
        if limit > 0:
            results = results[:limit]

        return results

    @capability(contract="messages", path="/messages", method="POST")
    def send_message(
        self, target_id: str, content: str, **kwargs
    ) -> Dict[str, str]:
        """
        Simulate sending a message.
        """
        logger.info(f"Mock sending message to {target_id}: {content}")

        new_msg = {
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "source": "mock",
            "sender": "System",
            "target_id": target_id,
            "content": content,
            "timestamp": time.time(),
            "is_read": True,  # Outbound messages are read by definition
        }

        self.messages.append(new_msg)
        return {"status": "sent", "message_id": new_msg["id"]}

    @capability(contract="messages", path="/messages/{id}", method="GET")
    def get_message_details(self, id: str, **kwargs) -> Dict[str, Any]:
        """
        Get specific message details.
        """
        for msg in self.messages:
            if msg["id"] == id:
                return msg
        return {}

    @capability(contract="messages", path="/messages/{id}", method="PUT")
    def update_message_status(
        self, id: str, is_read: bool, **kwargs
    ) -> Dict[str, Any]:
        """
        Update message read status.
        """
        for msg in self.messages:
            if msg["id"] == id:
                msg["is_read"] = is_read
                logger.info(f"Updated message {id} read status to {is_read}")
                return {"status": "updated", "id": id, "is_read": is_read}

        return {"status": "not_found", "id": id}
