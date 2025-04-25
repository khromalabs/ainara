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


import time
import logging
from typing import List, Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

logger = logging.getLogger(__name__)


class DocumentEventHandler(FileSystemEventHandler):
    """Handles file system events for document indexing"""

    def __init__(
        self,
        file_extensions: List[str],
        on_created: Optional[Callable[[str], None]] = None,
        on_modified: Optional[Callable[[str], None]] = None,
        on_deleted: Optional[Callable[[str], None]] = None,
        on_moved: Optional[Callable[[str, str], None]] = None
    ):
        self.file_extensions = file_extensions
        self.on_created_callback = on_created
        self.on_modified_callback = on_modified
        self.on_deleted_callback = on_deleted
        self.on_moved_callback = on_moved
        self.last_modified_time = {}

    def on_created(self, event: FileSystemEvent):
        if event.is_directory or not self._is_valid_file(event.src_path):
            return
        # Delay slightly to ensure file is completely written
        time.sleep(1)
        if self.on_created_callback:
            self.on_created_callback(event.src_path)

    def on_modified(self, event: FileSystemEvent):
        if event.is_directory or not self._is_valid_file(event.src_path):
            return

        # Debounce modifications (files might trigger multiple modify events)
        current_time = time.time()
        if event.src_path in self.last_modified_time:
            if current_time - self.last_modified_time[event.src_path] < 5:  # 5 second debounce
                return

        self.last_modified_time[event.src_path] = current_time
        time.sleep(1)  # Give the file time to finish being written

        if self.on_modified_callback:
            self.on_modified_callback(event.src_path)

    def on_deleted(self, event: FileSystemEvent):
        if event.is_directory or not self._is_valid_file(event.src_path):
            return

        if self.on_deleted_callback:
            self.on_deleted_callback(event.src_path)

    def on_moved(self, event: FileSystemEvent):
        if event.is_directory:
            return

        src_valid = self._is_valid_file(event.src_path)
        dest_valid = self._is_valid_file(event.dest_path)

        if not (src_valid or dest_valid):
            return

        if self.on_moved_callback and src_valid and dest_valid:
            self.on_moved_callback(event.src_path, event.dest_path)
        elif self.on_deleted_callback and src_valid and not dest_valid:
            self.on_deleted_callback(event.src_path)
        elif self.on_created_callback and not src_valid and dest_valid:
            time.sleep(1)
            self.on_created_callback(event.dest_path)

    def _is_valid_file(self, path: str) -> bool:
        """Check if the file should be indexed based on extension"""
        return any(path.endswith(ext) for ext in self.file_extensions)


class FileSystemWatcher:
    """Watches file system for document changes"""

    def __init__(
        self,
        directories: List[str],
        file_extensions: List[str],
        on_file_created: Optional[Callable[[str], None]] = None,
        on_file_modified: Optional[Callable[[str], None]] = None,
        on_file_deleted: Optional[Callable[[str], None]] = None,
        on_file_moved: Optional[Callable[[str, str], None]] = None
    ):
        self.directories = directories
        self.file_extensions = file_extensions
        self.observer = Observer()
        self.event_handler = DocumentEventHandler(
            file_extensions=file_extensions,
            on_created=on_file_created,
            on_modified=on_file_modified,
            on_deleted=on_file_deleted,
            on_moved=on_file_moved
        )

        # Set up observers for each directory
        for directory in directories:
            self.observer.schedule(self.event_handler, directory, recursive=True)
            logger.info(f"Watching directory: {directory}")

    def start(self):
        """Start watching for file changes"""
        self.observer.start()
        logger.info(f"Started file system watcher for {len(self.directories)} directories")

    def stop(self):
        """Stop watching for file changes"""
        self.observer.stop()
        self.observer.join()
        logger.info("Stopped file system watcher")