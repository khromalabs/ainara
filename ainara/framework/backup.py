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
import os
# import shutil
import threading
import time
import traceback
import zipfile
from datetime import datetime

try:
    import py7zr
except ImportError:
    py7zr = None


logger = logging.getLogger(__name__)


class BackupManager:
    """Manages automatic backups of user data."""

    def __init__(self, config_manager):
        """
        Initializes the BackupManager.

        Args:
            config_manager: An instance of ConfigManager.
        """
        self.config = config_manager
        self.thread = None
        self.stop_event = threading.Event()
        self.last_backup_status = None  # Can be 'success', 'failure', or None
        self.last_backup_timestamp = None
        self.last_backup_error = None

    def start(self):
        """Starts the backup manager thread if backups are enabled."""
        if not self.config.get("backup.enabled"):
            logger.info("BackupManager is disabled in the configuration.")
            return

        backup_dir = self.config.get("backup.directory")
        if not backup_dir:
            logger.warning(
                "Backup directory is not set. Automatic backups will not run."
            )
            return

        if not os.path.isdir(backup_dir):
            try:
                os.makedirs(backup_dir, exist_ok=True)
                logger.info(f"Created backup directory: {backup_dir}")
            except OSError as e:
                logger.error(
                    f"Failed to create backup directory {backup_dir}: {e}"
                )
                return

        interval_hours = self.config.get("backup.interval_hours", 24)
        self.interval_seconds = interval_hours * 3600

        self.thread = threading.Thread(target=self._backup_loop, daemon=True)
        self.thread.start()
        logger.info(
            "BackupManager started. Backups will run every"
            f" {interval_hours} hours."
        )

    def stop(self):
        """Stops the backup manager thread."""
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self.thread.join()
            logger.info("BackupManager stopped.")

    def _backup_loop(self):
        """The main loop for the backup thread."""
        # Wait a short period before the first backup to allow services to start
        time.sleep(10)

        while not self.stop_event.is_set():
            self._run_backup()
            # Wait for the next interval, but check for stop_event periodically
            self.stop_event.wait(self.interval_seconds)

    def _run_backup(self):
        """Performs a single backup operation."""
        logger.info("Starting scheduled backup...")
        try:
            data_dir = self.config.get("data.directory")
            backup_dir = self.config.get("backup.directory")
            # Check backup directory for existence and write permissions
            if not os.path.isdir(backup_dir):
                raise FileNotFoundError(f"Backup directory not found: {backup_dir}")
            if not os.access(backup_dir, os.W_OK):
                raise PermissionError(f"Backup directory is not writable: {backup_dir}")

            password = self.config.get("backup.password")
            versions_to_keep = self.config.get("backup.versions_to_keep", 7)

            if not os.path.isdir(data_dir):
                raise FileNotFoundError(
                    f"Data directory not found: {data_dir}. Cannot perform"
                    " backup."
                )

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            use_7z = py7zr and password
            ext = "7z" if use_7z else "zip"
            archive_name = f"ainara_backup_{timestamp}"
            backup_filepath = os.path.join(backup_dir, f"{archive_name}.{ext}")

            def should_backup(filename: str) -> bool:
                """Filter for files to be backed up."""
                return filename.endswith(".db") and filename.count(".") == 1

            files_to_backup = []
            for root, _, files in os.walk(data_dir):
                for file in files:
                    if should_backup(file):
                        files_to_backup.append(os.path.join(root, file))

            if not files_to_backup:
                logger.info(
                    "No database files found to backup. Skipping backup cycle."
                )
                return

            logger.info(
                f"Creating backup of {len(files_to_backup)} database file(s)"
                f" from '{data_dir}' to '{backup_filepath}'"
            )

            if use_7z:
                with py7zr.SevenZipFile(
                    backup_filepath, "w", password=password
                ) as archive:
                    for file_path in files_to_backup:
                        arcname = os.path.relpath(file_path, data_dir)
                        archive.write(
                            file_path, arcname=os.path.join("data", arcname)
                        )
            else:
                if password:
                    logger.warning(
                        "py7zr is not installed. Cannot create encrypted"
                        " backup. Creating a standard zip file instead."
                    )

                with zipfile.ZipFile(
                    backup_filepath, "w", zipfile.ZIP_DEFLATED
                ) as zipf:
                    for file_path in files_to_backup:
                        arcname = os.path.relpath(file_path, data_dir)
                        zipf.write(
                            file_path, arcname=os.path.join("data", arcname)
                        )

            logger.info("Backup created successfully.")

            self._cleanup_old_backups(backup_dir, versions_to_keep)

            # Update status on success
            self.last_backup_status = "success"
            self.last_backup_timestamp = datetime.now().isoformat()
            self.last_backup_error = None

        except Exception as e:
            logger.error(f"An error occurred during backup: {e}")
            logger.error(traceback.format_exc())
            # Update status on failure
            self.last_backup_status = "failure"
            self.last_backup_timestamp = datetime.now().isoformat()
            self.last_backup_error = str(e)

    def _cleanup_old_backups(self, backup_dir, versions_to_keep):
        """Removes old backups, keeping only the specified number."""
        logger.info(
            "Cleaning up old backups, keeping the latest"
            f" {versions_to_keep} versions."
        )
        try:
            backups = sorted(
                [
                    f
                    for f in os.listdir(backup_dir)
                    if f.startswith("ainara_backup_")
                    and (f.endswith(".7z") or f.endswith(".zip"))
                ],
                key=lambda f: os.path.getmtime(os.path.join(backup_dir, f)),
            )

            if len(backups) > versions_to_keep:
                to_delete = backups[:-versions_to_keep]
                for filename in to_delete:
                    filepath = os.path.join(backup_dir, filename)
                    os.remove(filepath)
                    logger.info(f"Removed old backup: {filename}")
        except Exception as e:
            logger.error(f"An error occurred during backup cleanup: {e}")
