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

import sys
import threading
import time
from itertools import cycle

from colorama import Fore, Style


class LoadingAnimation:
    """Simple text-based loading animation similar to npm style"""

    def __init__(self, message="Processing"):
        self.message = message
        self.done = False
        self.thread = None
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.delay = 0.08

    def animate(self):
        for frame in cycle(self.frames):
            if self.done:
                break
            sys.stdout.write(
                f"\r{Fore.LIGHTCYAN_EX}{frame} {self.message}{Style.RESET_ALL}"
            )
            sys.stdout.flush()
            time.sleep(self.delay)
        # Clear the line and reset cursor
        sys.stdout.write(
            "\r" + " " * (len(self.frames[0]) + len(self.message) + 2)
        )
        sys.stdout.write("\r")
        sys.stdout.flush()

    def start(self):
        self.done = False
        self.thread = threading.Thread(target=self.animate)
        self.thread.start()

    def stop(self):
        self.done = True
        if self.thread:
            self.thread.join()