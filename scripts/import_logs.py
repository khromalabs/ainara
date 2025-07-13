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


import argparse
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add the project root to the Python path to allow importing from 'ainara'
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from ainara.framework.config import ConfigManager
from ainara.framework.storage.sqlite import SQLiteStorage

# --- Basic Setup ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def parse_and_import_logs(storage: SQLiteStorage, directory_path: str):
    """Parses conversation logs from a directory and imports them into the database."""
    log_dir = Path(directory_path).expanduser()
    if not log_dir.is_dir():
        logger.error(f"Directory not found: {log_dir}")
        return

    logger.info(f"Scanning for log files in: {log_dir}")
    log_files = [f for f in log_dir.iterdir() if f.is_file()]
    total_files = len(log_files)
    total_messages_imported = 0

    for i, file_path in enumerate(log_files):
        logger.info(f"Processing file {i + 1}/{total_files}: {file_path.name}")

        try:
            # Use file modification time as the base timestamp for the conversation
            base_ts = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
            time_offset = timedelta(seconds=0)

            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Split the content into user/assistant turns.
            # The regex captures the user line (starting with '>') and includes it in the split list.
            turns = re.split(r"(^>.*$)", content, flags=re.MULTILINE)

            # The first element might be empty or an initial non-user text, so we discard it if it's not a user line.
            if turns and not turns[0].strip().startswith(">"):
                turns.pop(0)

            messages_to_add = []
            # Process in pairs: user line, then assistant response
            for j in range(0, len(turns), 2):
                if j + 1 >= len(turns):
                    continue  # Skip if there's a user line without a following assistant response

                user_line = turns[j].strip()
                assistant_text = turns[j + 1].strip()

                # Basic validation
                if not user_line.startswith(">"):
                    continue
                user_content = user_line[1:].strip()
                if not user_content or not assistant_text:
                    continue

                # Prepare messages for insertion
                metadata = {
                    "source_type": "log_import",
                    "persona": "default",
                    "original_file": file_path.name,
                }
                # Add user message
                messages_to_add.append(
                    {
                        "role": "user",
                        "content": user_content,
                        "timestamp": (base_ts + time_offset).isoformat(),
                        "metadata": metadata,
                    }
                )
                time_offset += timedelta(seconds=5)  # Increment time for the next message

                # Add assistant message
                messages_to_add.append(
                    {
                        "role": "assistant",
                        "content": assistant_text,
                        "timestamp": (base_ts + time_offset).isoformat(),
                        "metadata": metadata,
                    }
                )
                time_offset += timedelta(seconds=5)

            if messages_to_add:
                storage.add_historical_messages(messages_to_add)
                logger.info(
                    f"  -> Imported {len(messages_to_add)} messages from {file_path.name}"
                )
                total_messages_imported += len(messages_to_add)

        except Exception as e:
            logger.error(f"Failed to process {file_path.name}: {e}")

    logger.info(
        f"\nImport complete. Processed {total_files} files and added {total_messages_imported} messages."
    )


def trigger_memory_rescan(storage: SQLiteStorage):
    """Resets metadata to force UserMemoriesManager to re-process all messages."""
    logger.info("Scheduling a full rescan of chat history to generate new memories...")
    try:
        with storage.conn:
            # This forces the UserMemoriesManager to start from the beginning
            storage.conn.execute(
                "DELETE FROM db_metadata WHERE key = ?",
                ("profile_last_processed_timestamp",),
            )
        # This ensures the vector store is also rebuilt
        storage.set_metadata("vector_db_needs_reset", "true")
        logger.info(
            "Successfully scheduled history rescan. New memories will be generated on the next application run."
        )
    except Exception as e:
        logger.error(f"Could not schedule history rescan: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Import conversation logs into the Ainara chat database."
    )
    parser.add_argument(
        "directory",
        type=str,
        help="The path to the directory containing the log files.",
    )
    args = parser.parse_args()

    try:
        # Use the framework's config manager to find the database
        config = ConfigManager()
        config.load_config()
        db_path = config.get(
            "memory.text_storage.storage_path",
            os.path.join(config.get("data.directory"), "chat_memory.db"),
        )
        if not db_path:
            raise ValueError("Database path not found in configuration.")

        db_path = os.path.expanduser(db_path)
        logger.info(f"Connecting to database at: {db_path}")

        # Initialize storage backend
        storage = SQLiteStorage(db_path=db_path)

        # Run the import
        parse_and_import_logs(storage, args.directory)

        # Trigger the rescan
        trigger_memory_rescan(storage)

        # Cleanly close the connection
        storage.close()

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
