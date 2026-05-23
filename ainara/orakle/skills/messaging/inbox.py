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

import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Optional

from ainara.framework.skill import Skill
from ainara.framework.storage import create_system_storage

logger = logging.getLogger(__name__)


class MessagingInbox(Skill):
    """
    Unified messaging management for reading and sending messages across platforms
    (Email, Discord, Telegram, etc.) via the Contract-Driven Virtual Router.
    """

    matcher_info = (
        "Use this skill to manage communications. It can check for new"
        " messages across all connected platforms (Email, Discord, Telegram,"
        " etc.) and send messages to specific recipients. \n\nKeywords: email,"
        " message, inbox, chat, send, reply, discord, telegram, communication,"
        " read, unread, check, notification."
    )

    def __init__(
        self,
        context: Optional[Dict[str, str]] = None,
    ):
        super().__init__()
        # Will be initialized by the capabilities manager
        self.router = None

        # Initialize storage for persistence
        self.storage = create_system_storage()

        # # Default schedule configuration
        # default_schedule = {
        #     "trigger": "cron",
        #     "minute": "*/15",  # Every 15 minutes
        #     "kwargs": {
        #         # Your skill parameters
        #     }
        # }

        self.default_schedule = {
            "trigger": "interval",
            "minutes": 10,
            "kwargs": {"action": "check"},
            "default": True
        }

    async def run(
        self,
        action: Annotated[
            str,
            "The action to perform: 'check' to read messages, 'send' to send a"
            " message",
        ],
        target: Annotated[
            Optional[str],
            "Recipient identifier (required for 'send', e.g."
            " 'mock_messaging:user1')",
        ] = None,
        limit: Annotated[
            Optional[int],
            "Maximum number of messages to retrieve (for 'check')",
        ] = 20,
        unread_only: Annotated[
            Optional[bool], "Only show unread messages (for 'check')"
        ] = True,
        content: Annotated[
            Optional[str], "Message body (required for 'send')"
        ] = None,
        include_dms: Annotated[bool, "Check Direct Messages"] = True,
        include_channels: Annotated[bool, "Check Server Channels"] = True,
    ) -> Dict[str, Any]:
        """
        Execute messaging actions.

        Examples:
            run(action='check', limit=20)
            run(action='send', target='mock_messaging:user1', content='Hello there')
        """
        if not self.router:
            return {
                "success": False,
                "error": "router not initialized",
            }
        action = action.lower().strip()

        if action == "check":
            result = await self.check_inbox(
                limit=limit,
                unread_only=unread_only,
                include_dms=include_dms,
                include_channels=include_channels,
            )
            return {"success": True, "output": result}

        elif action == "send":
            # if not target or not content:
            #     return {
            #         "success": False,
            #         "error": (
            #             "Both 'target' and 'content' are required for sending"
            #             " messages."
            #         ),
            #     }
            # result = await self.send_message(target=target, content=content)
            # return {"success": True, "output": result}

            return {
                "success": False,
                "error": (
                    f"Action {action} is disabled by now."
                ),
            }

        else:
            return {
                "success": False,
                "error": (
                    f"Unknown action: {action}. Please use 'check' or 'send'."
                ),
            }

    async def check_inbox(
        self,
        limit: int = 20,
        unread_only: bool = True,
        include_dms: bool = True,
        include_channels: bool = True,
    ) -> str:
        """Retrieves messages from DMs and/or Channels."""

        aggregated_results = {}
        current_time = datetime.now(timezone.utc).isoformat()

        # 1. Check DMs (Inbox)
        if include_dms:
            last_check_dms = self.storage.get_metadata(
                "skill:inbox:dms:last_check"
            )
            params_dms = {"limit": limit, "unread_only": unread_only}
            # Note: DMs usually don't support 'after' in the same way via the messages contract
            # but we pass it if supported by specific connectors
            if last_check_dms:
                params_dms["after"] = last_check_dms

            dms = await self.router.route_request(
                contract="messages",
                path="/messages",
                method="GET",
                params=params_dms,
            )
            if dms:
                for source, msgs in dms.items():
                    aggregated_results[f"{source} (Direct Message)"] = msgs

            self.storage.set_metadata(
                "skill:inbox:dms:last_check", current_time
            )

        # 2. Check Channels (Global Feed)
        if include_channels:
            last_check_channels = self.storage.get_metadata(
                "skill:inbox:channels:last_check"
            )
            params_channels = {"limit": limit}
            if last_check_channels:
                params_channels["after"] = last_check_channels

            channels = await self.router.route_request(
                contract="channels",
                path="/channels/messages",
                method="GET",
                params=params_channels,
            )
            if channels:
                for source, msgs in channels.items():
                    aggregated_results[f"{source} (Channels)"] = msgs

            self.storage.set_metadata(
                "skill:inbox:channels:last_check", current_time
            )

        if not aggregated_results:
            return "[]"

        # 3. Format Output
        flat_messages = []
        for source, messages in aggregated_results.items():
            if not messages:
                continue

            for msg in messages:
                # Inject source info so it's not lost
                if isinstance(msg, dict):
                    msg_copy = msg.copy()
                    msg_copy["origin_source"] = source
                    flat_messages.append(msg_copy)
                else:
                    # Fallback for non-dict messages
                    flat_messages.append(
                        {"content": str(msg), "origin_source": source}
                    )

        return json.dumps(flat_messages)

    async def send_message(self, target: str, content: str) -> str:
        """
        Sends a message to a specific target.

        Args:
            target: The recipient identifier. Can be a simple ID or prefixed with connector ID
                    (e.g., 'mock_messaging:user123').
            content: The text body of the message.
        """
        logger.info(f"InboxSkill: Sending message to {target}")

        # Determine if a specific connector is targeted
        target_connector = None
        actual_target_id = target

        if ":" in target:
            parts = target.split(":", 1)
            # Simple heuristic: if the prefix matches a known connector pattern
            target_connector = parts[0]
            actual_target_id = parts[1]

        # Dispatch to router
        results = await self.router.route_request(
            contract="messages",
            path="/messages",
            method="POST",
            params={"target_id": actual_target_id, "content": content},
            target_connector=target_connector,
        )

        if not results:
            return (
                "Failed to send message. No connector could handle target"
                f" '{target}'."
            )

        # Summarize results
        confirmations = []
        for cid, response in results.items():
            status = response.get("status", "unknown")
            confirmations.append(f"{cid}: {status}")

        return (
            f"Message dispatch complete. Results: {', '.join(confirmations)}"
        )
