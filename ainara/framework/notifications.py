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

import hashlib
import json
import logging
from typing import Any, Dict, List

from ainara.framework.storage.sqlite import SQLiteStorage
from ainara.framework.template_manager import TemplateManager

logger = logging.getLogger(__name__)


class NotificationManager:
    def __init__(self, llm_backend, storage: SQLiteStorage):
        self.llm = llm_backend
        self.storage = storage
        self.template_manager = TemplateManager()

    def _get_content_hash(self, content: Any) -> str:
        """Generate a unique hash for the content."""
        raw = str(content).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _is_payload_empty(self, data: Any) -> bool:
        """Heuristic to detect empty or irrelevant skill outputs."""
        if not data:
            return True

        if isinstance(data, dict):
            # 1. Check for specific "empty" patterns in common keys
            for key in ["output", "result", "results", "content"]:
                if key in data:
                    val = data[key]
                    # Check if value is empty string, empty list, or None
                    if val is None or val == "" or val == []:
                        return True

            # 2. "Success-only" responses (e.g. {"success": true}) with no other data
            # If 'success' is the only key, or if keys are only 'success' and 'status'
            keys = set(data.keys())
            if keys == {"success"} or keys == {"success", "status"}:
                return True

        return False

    def process_payload(self, payload: dict):
        """
        Entry point for Orakle scheduler.
        1. Validates payload (discards empty ones).
        2. Stores raw event in DB (Deduplication).
        3. Triggers background consolidation.
        """
        source = payload.get("source", "unknown")
        result = payload.get("result")

        # Step 1: Pre-Validation
        if self._is_payload_empty(result):
            return

        # Step 2: Storage & Deduplication
        try:
            # Atomize / Normalize
            if isinstance(result, str):
                try:
                    decoded = json.loads(result)
                    if isinstance(decoded, (list, dict)):
                        result = decoded
                except (json.JSONDecodeError, TypeError):
                    pass

            events = []
            if isinstance(result, list):
                events = result
            elif isinstance(result, dict):
                events = [result]
            else:
                # For unstructured text, we store it as one event for now
                events = [{"content": str(result)}]

            new_events_count = 0
            for event in events:
                external_id = (
                    event.get("id")
                    or event.get("uid")
                    or event.get("message_id")
                )
                content_hash = None

                if not external_id:
                    content_hash = self._get_content_hash(event)

                # --- Debug Logging Start ---
                logger.info(
                    f"Notification Debug - Source: {source} | "
                    f"ExtID: {external_id} | Hash: {content_hash}"
                )
                if not external_id:
                    # Log the exact content being hashed to detect changing timestamps/metadata
                    str_event = str(event)
                    logger.info(f"Notification Debug - Content hashed first 100 characters: {str_event[:100]}")
                    logger.info(f"Notification Debug - Content hashed last 100 characters: {str_event[-100:]}")
                # --- Debug Logging End ---

                # Check DB
                if not self.storage.is_event_processed(
                    source, external_id, content_hash
                ):
                    self.storage.add_event(
                        source, event, external_id, content_hash
                    )
                    new_events_count += 1

            if new_events_count > 0:
                logger.info(
                    f"NotificationManager: Stored {new_events_count} new"
                    f" events from {source}"
                )
                # # Step 3: Trigger Consolidation (Background)
                # thread = threading.Thread(
                #     target=self.consolidate_events,
                #     daemon=True,
                # )
                # thread.start()

        except Exception as e:
            logger.error(f"Error processing payload: {e}")

    def consolidate_events(self):
        """
        Background task:
        1. Fetch unprocessed events from DB.
        2. Summarize them using LLM.
        3. Store as Notifications.
        4. Prune raw event data.
        """
        try:
            # 1. Fetch
            raw_events = self.storage.get_unprocessed_events()
            if not raw_events:
                return

            # Group by source for better summarization
            events_by_source = {}
            for row in raw_events:
                source = row["source"]
                if source not in events_by_source:
                    events_by_source[source] = []

                # Parse the JSON data back
                if row["data"]:
                    try:
                        data = json.loads(row["data"])
                        events_by_source[source].append(data)
                    except Exception as e:
                        logger.error(f"Error processing JSON data back: {e}")
                        pass

            # 2. Summarize per source
            for source, events in events_by_source.items():
                self._generate_notification(source, events)

            # 4. Prune (Mark all fetched events as processed)
            event_ids = [row["id"] for row in raw_events]
            self.storage.mark_events_processed(event_ids)

        except Exception as e:
            logger.error(f"Error in consolidation task: {e}")

    def _generate_notification(self, source: str, new_events: List[Dict]):
        """Summarize the new events into a user-facing notification."""
        try:
            # If we have too many events, just send a summary count to save tokens
            if len(new_events) > 10:
                summary = f"{len(new_events)} new items received."
            else:
                prompt = self.template_manager.render(
                    "framework.notifications.summarize",
                    {
                        "source": source,
                        "events": json.dumps(new_events, indent=2),
                    },
                )

                temp_history = [{"role": "user", "content": prompt}]
                summary = self.llm.chat(
                    chat_history=temp_history, stream=False
                )

            if not summary or "IRRELEVANT" in summary.upper():
                return

            # 3. Store Notification
            logger.info(
                f"NotificationManager: Generated notification for {source}"
            )
            self.storage.add_notification(source, summary.strip())

        except Exception as e:
            logger.error(f"Error generating notification summary: {e}")

    def get_and_clear_notifications(self, do_clear: bool = True) -> List[dict]:
        """
        Retrieve pending notifications from DB.
        Args:
            do_clear: If True, marks them as injected so they don't show up again.
        """
        items = self.storage.get_pending_notifications()

        if items and do_clear:
            ids = [item["id"] for item in items]
            self.storage.mark_notifications_injected(ids)

        # Format for the ChatManager
        return [
            {
                "source": item["source"],
                "summary": item["content"],
                "timestamp": item["timestamp"],
            }
            for item in items
        ]

    def pending_notifications(self) -> int:
        """Check if there are pending notifications in DB."""
        # Lightweight check
        items = self.storage.get_pending_notifications()
        return len(items)
