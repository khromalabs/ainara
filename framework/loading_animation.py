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
