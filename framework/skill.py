# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez http://www.khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, see
# <https://www.gnu.org/licenses/>.

class Skill:
    def __init__(self):
        self.name = self.__class__.__name__
        # Define what data this skill requires from the chat manager
        self.required_data = {}

    def reload(self, config=None):
        if config:
            config.load_config()

    def run(self):
        raise NotImplementedError(
            "This method should be overridden by subclasses"
        )
