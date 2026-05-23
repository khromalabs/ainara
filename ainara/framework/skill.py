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


class Skill:
    def __init__(self):
        self.name = self.__class__.__name__
        self.connector_manager = None  # Added: Reference to ConnectorManager
        # Define what data this skill requires from the chat manager
        self.required_data = {}
        # Default schedule configuration.
        # Examples:
        # {'trigger': 'interval', 'minutes': 15}
        # {'trigger': 'cron', 'hour': 8, 'minute': 0, 'misfire_grace_time': 3600}
        #
        # Note on misfire_grace_time:
        # - If omitted, defaults to scheduler strict mode (usually 1s).
        # - Set to None to allow the job to run no matter how late it is (e.g. after sleep).
        # - Set to an integer (seconds) to define a specific grace window.
        self.default_schedule = None

    # def reload(self, config=None):
    #     if config:
    #         config.load_config()

    def run(self):
        raise NotImplementedError(
            "This method should be overridden by subclasses"
        )
