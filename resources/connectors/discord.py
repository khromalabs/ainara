# resources/connectors/discord.py
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from ainara.framework.connectors.base import BaseConnector, capability

logger = logging.getLogger(__name__)


class DiscordConnector(BaseConnector):
    """Discord connector implementing messaging and channel capabilities."""

    API_BASE = "https://discord.com/api/v10"

    @property
    def MANIFEST(self) -> Dict[str, Any]:
        return {
            "id": "discord",
            "required_config": ["apis.messaging.discord.bot_token"],
            "description": "Discord messaging connector",
            "capabilities": ["channels", "messages"],
        }

    def initialize(self):
        """Initialize Discord connector with token and session."""
        self.token = self.config.get("apis.messaging.discord.bot_token")
        if not self.token:
            raise ValueError(
                "Discord connector requires 'bot_token' in config"
            )

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bot {self.token}",
                "User-Agent": "Ainara-Discord-Connector/1.0",
            }
        )

        # Rate limiting state
        self._rate_limit_remaining = None
        self._rate_limit_reset = None

        # Verify token by getting bot user info
        try:
            response = self._make_request("GET", "/users/@me")
            self.bot_id = response["id"]
            self.bot_username = response["username"]
            logger.info(
                f"Discord connector initialized for bot: {self.bot_username}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize Discord connector: {e}")
            raise

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make authenticated request to Discord API with rate limiting."""
        url = f"{self.API_BASE}{endpoint}"

        # Check rate limits before making request
        if (
            self._rate_limit_remaining is not None
            and self._rate_limit_remaining == 0
        ):
            reset_time = self._rate_limit_reset
            current_time = time.time()
            if current_time < reset_time:
                sleep_duration = reset_time - current_time
                logger.warning(
                    f"Rate limited, sleeping for {sleep_duration:.2f}s"
                )
                time.sleep(sleep_duration)

        response = self.session.request(method, url, **kwargs)

        # Update rate limit info
        self._rate_limit_remaining = int(
            response.headers.get("X-RateLimit-Remaining", 1)
        )
        reset_after = float(response.headers.get("X-RateLimit-Reset-After", 0))
        self._rate_limit_reset = time.time() + reset_after

        if response.status_code == 429:
            # Rate limited - Discord sends retry_after in body
            retry_after = response.json().get("retry_after", 1)
            logger.warning(
                f"Rate limited by Discord, retrying after {retry_after}s"
            )
            time.sleep(retry_after)
            return self._make_request(method, endpoint, **kwargs)

        response.raise_for_status()
        return response.json() if response.content else None

    def _get_bot_channels(self) -> List[Dict[str, Any]]:
        """Get all channels the bot has access to."""
        # Get guilds
        guilds = self._make_request("GET", "/users/@me/guilds")

        channels = []
        for guild in guilds:
            guild_id = guild["id"]
            try:
                # Get channels for each guild
                guild_channels = self._make_request(
                    "GET", f"/guilds/{guild_id}/channels"
                )
                channels.extend(guild_channels)
            except Exception as e:
                logger.warning(
                    f"Failed to get channels for guild {guild_id}: {e}"
                )

        # Get DM channels
        try:
            dm_channels = self._make_request("GET", "/users/@me/channels")
            channels.extend(dm_channels)
        except Exception as e:
            logger.warning(f"Failed to get DM channels: {e}")

        return channels

    def _parse_target(self, target: Optional[str]) -> tuple:
        """Parse target string into connector_id and actual target_id."""
        if not target:
            return None, None

        if ":" in target:
            parts = target.split(":", 1)
            return parts[0], parts[1]

        return None, target

    def _iso_to_snowflake(self, iso_timestamp: str) -> Optional[str]:
        """Convert ISO timestamp to Discord Snowflake ID."""
        if not iso_timestamp:
            return None
        try:
            # Handle Z suffix if present
            iso_timestamp = iso_timestamp.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_timestamp)
            timestamp_ms = int(dt.timestamp() * 1000)
            discord_epoch = 1420070400000
            if timestamp_ms < discord_epoch:
                return None
            return str((timestamp_ms - discord_epoch) << 22)
        except Exception:
            return None

    @capability(contract="messages", path="/messages", method="GET")
    def get_messages(
        self,
        limit: int = 0,
        unread_only: bool = True,
        source: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Get messages from Discord DMs (Inbox)."""
        logger.info(f"Discord: Getting DMs (limit={limit})")

        # Parse source if it's a Discord target
        target_connector, target_id = self._parse_target(source)

        messages = []

        if target_connector == "discord" and target_id:
            # Specific channel requested
            try:
                channel_messages = self._make_request(
                    "GET",
                    f"/channels/{target_id}/messages",
                    params={"limit": limit if limit > 0 else 50},
                )
                for msg in channel_messages:
                    messages.append(
                        {
                            "id": f"{target_id}:{msg['id']}",  # Composite ID
                            "sender": msg["author"]["username"],
                            "content": msg["content"],
                            "timestamp": msg["timestamp"],
                            "is_read": (
                                True
                            ),  # Discord doesn't have read receipts in API
                            "source": f"discord:{target_id}",
                        }
                    )
            except Exception as e:
                logger.error(
                    f"Failed to get messages for channel {target_id}: {e}"
                )
        else:
            # Get DM channels only
            try:
                dm_channels = self._make_request("GET", "/users/@me/channels")

                for channel in dm_channels:
                    channel_id = channel["id"]
                    try:
                        # Get recent messages
                        channel_messages = self._make_request(
                            "GET",
                            f"/channels/{channel_id}/messages",
                            params={
                                "limit": min(limit, 20) if limit > 0 else 5
                            },
                        )

                        for msg in channel_messages:
                            if msg["author"]["id"] == self.bot_id:
                                continue

                            messages.append(
                                {
                                    "id": f"{channel_id}:{msg['id']}",
                                    "sender": msg["author"]["username"],
                                    "content": msg["content"],
                                    "timestamp": msg["timestamp"],
                                    "is_read": True,
                                    "source": f"discord:{channel_id} (DM)",
                                }
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to get DMs for channel {channel_id}: {e}"
                        )
            except Exception as e:
                logger.error(f"Failed to get DM channels: {e}")

        # Sort by timestamp (newest first) and apply limit
        messages.sort(key=lambda x: x["timestamp"], reverse=True)
        if limit > 0:
            messages = messages[:limit]

        return messages

    @capability(contract="messages", path="/messages", method="POST")
    def send_message(
        self, target_id: str, content: str, **kwargs
    ) -> Dict[str, Any]:
        """Send a message to a Discord channel or user."""
        logger.info(f"Discord: Sending message to {target_id}")

        if not target_id or not content:
            return {
                "status": "error",
                "message": "target_id and content are required",
            }

        # Parse target
        target_connector, actual_target_id = self._parse_target(target_id)

        # If target_connector is specified and it's not discord, skip
        if target_connector and target_connector != "discord":
            return {"status": "skipped", "message": "Not a Discord target"}

        # If no connector specified, assume it's a Discord channel ID
        if not target_connector:
            actual_target_id = target_id

        try:
            # For user IDs, we need to create a DM channel first
            if not actual_target_id.isdigit():
                return {
                    "status": "error",
                    "message": "Invalid channel ID format",
                }

            # Send the message
            response = self._make_request(
                "POST",
                f"/channels/{actual_target_id}/messages",
                json={"content": content},
            )

            return {
                "status": "success",
                "message_id": response["id"],
                "channel_id": actual_target_id,
            }
        except Exception as e:
            logger.error(f"Failed to send message to {actual_target_id}: {e}")
            return {"status": "error", "message": str(e)}

    @capability(contract="channels", path="/channels/messages", method="GET")
    def get_global_channel_history(
        self, limit: int = 20, after: Optional[str] = None, **kwargs
    ) -> List[Dict[str, Any]]:
        """Get history from all accessible Guild channels."""
        logger.info(
            f"Discord: Getting global history (limit={limit}, after={after})"
        )

        messages = []
        snowflake_after = self._iso_to_snowflake(after)

        # Get guilds
        try:
            guilds = self._make_request("GET", "/users/@me/guilds")

            for guild in guilds:
                guild_id = guild["id"]
                try:
                    channels = self._make_request(
                        "GET", f"/guilds/{guild_id}/channels"
                    )

                    for channel in channels:
                        # Only text channels (0) and news (5)
                        if channel["type"] not in [0, 5]:
                            continue

                        params = {
                            "limit": 5
                        }  # Keep per-channel limit low for global fetch
                        if snowflake_after:
                            params["after"] = snowflake_after

                        try:
                            msgs = self._make_request(
                                "GET",
                                f"/channels/{channel['id']}/messages",
                                params=params,
                            )

                            for msg in msgs:
                                messages.append(
                                    {
                                        "id": f"{channel['id']}:{msg['id']}",
                                        "sender": msg["author"]["username"],
                                        "content": msg["content"],
                                        "timestamp": msg["timestamp"],
                                        "source": f"discord:{channel['name']}",
                                    }
                                )
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Failed to get global history: {e}")

        messages.sort(key=lambda x: x["timestamp"], reverse=True)
        if limit > 0:
            messages = messages[:limit]

        return messages

    @capability(contract="messages", path="/messages/{id}", method="GET")
    def get_message_details(self, id: str, **kwargs) -> Dict[str, Any]:
        """Get details of a specific message using composite ID (channel_id:message_id)."""
        logger.info(f"Discord: Getting message details for {id}")

        if ":" not in id:
            return {
                "error": "Invalid ID format. Expected channel_id:message_id"
            }

        channel_id, message_id = id.split(":", 1)

        try:
            msg = self._make_request(
                "GET", f"/channels/{channel_id}/messages/{message_id}"
            )

            return {
                "id": f"{channel_id}:{msg['id']}",
                "sender": msg["author"]["username"],
                "content": msg["content"],
                "timestamp": msg["timestamp"],
                "is_read": True,
                "source": f"discord:{channel_id}",
                "raw": msg,  # Include full Discord payload for advanced usage
            }
        except Exception as e:
            logger.error(f"Failed to get message details for {id}: {e}")
            return {"error": str(e)}

    @capability(contract="messages", path="/messages/{id}", method="PUT")
    def update_message_status(
        self, id: str, is_read: bool, **kwargs
    ) -> Dict[str, Any]:
        """
        Update message status.
        Since Discord bots auto-read, we use this to add a reaction (✅)
        to signify the system has processed the message.
        """
        logger.info(f"Discord: Updating status for {id} (is_read={is_read})")

        if ":" not in id:
            return {"status": "error", "message": "Invalid ID format"}

        channel_id, message_id = id.split(":", 1)

        if is_read:
            try:
                # Add a checkmark reaction to indicate 'read/processed'
                # URL encode the emoji if necessary, but standard unicode works directly in path usually
                # ✅ is %E2%9C%85
                self._make_request(
                    "PUT",
                    f"/channels/{channel_id}/messages/{message_id}/reactions/%E2%9C%85/@me",
                )
                return {"status": "success", "state": "marked_read"}
            except Exception as e:
                logger.error(f"Failed to update status for {id}: {e}")
                return {"status": "error", "message": str(e)}

        return {
            "status": "ignored",
            "message": "Only is_read=True is supported",
        }

    @capability(
        contract="channels", path="/channels/{id}/messages", method="GET"
    )
    def get_channel_history(
        self, id: str, limit: int = 50, after: Optional[str] = None, **kwargs
    ) -> List[Dict[str, Any]]:
        """Get channel history."""
        logger.info(
            f"Discord: Getting history for channel {id} (after={after})"
        )

        _, channel_id = self._parse_target(id)
        if not channel_id:
            return []

        try:
            messages = []
            params = {"limit": limit}

            if after:
                # Handle composite IDs (channel_id:message_id) by taking the last part
                params["after"] = (
                    after.split(":")[-1] if ":" in after else after
                )

            channel_messages = self._make_request(
                "GET", f"/channels/{channel_id}/messages", params=params
            )

            for msg in channel_messages:
                messages.append(
                    {
                        "id": f"{channel_id}:{msg['id']}",  # Composite ID
                        "sender": msg["author"]["username"],
                        "content": msg["content"],
                        "timestamp": msg["timestamp"],
                        "source": f"discord:{channel_id}",
                    }
                )

            # Sort by timestamp (newest first)
            messages.sort(key=lambda x: x["timestamp"], reverse=True)
            return messages
        except Exception as e:
            logger.error(
                f"Failed to get history for channel {channel_id}: {e}"
            )
            return []

    @capability(
        contract="channels", path="/channels/{id}/messages", method="POST"
    )
    def send_to_channel(
        self, id: str, content: str, **kwargs
    ) -> Dict[str, Any]:
        """Send a message to a specific thread or channel."""
        logger.info(f"Discord: Sending to channel {id}")

        _, channel_id = self._parse_target(id)
        if not channel_id:
            return {"status": "error", "message": "Invalid channel ID"}

        try:
            response = self._make_request(
                "POST",
                f"/channels/{channel_id}/messages",
                json={"content": content},
            )

            return {
                "status": "success",
                "message_id": response["id"],
                "channel_id": channel_id,
            }
        except Exception as e:
            logger.error(f"Failed to send to channel {channel_id}: {e}")
            return {"status": "error", "message": str(e)}
