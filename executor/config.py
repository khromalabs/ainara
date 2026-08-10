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

"""Read-only loader for the shared ainara.yaml, used by the isolated executor venv.

The executor cannot import ainara.framework.config (different venv), so it parses
the same YAML file directly. Path resolution mirrors framework/config.py: the
AINARA_CONFIG env var wins, else the platform default.
"""

import os

import yaml


def _default_config_path():
    # Mirror framework/platform_utils.get_default_config_paths (Windows/posix).
    # Windows default is %APPDATA% (Roaming), NOT Documents: Documents is what
    # OneDrive's "Known Folder Move" silently redirects into cloud sync on a
    # default Windows 11 setup, which is never acceptable for a file that can
    # hold venue signing keys. %APPDATA% is always local disk.
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(appdata, "ainara", "ainara.yaml")
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(xdg, "ainara", "ainara.yaml")


class ExecutorConfig:
    """Thin dotted-path accessor over the loaded YAML."""

    def __init__(self, path=None):
        self.path = path or os.environ.get("AINARA_CONFIG") or _default_config_path()
        if not os.path.exists(self.path):
            raise FileNotFoundError(
                f"ainara.yaml not found at {self.path}. Set AINARA_CONFIG."
            )
        with open(self.path) as f:
            self._cfg = yaml.safe_load(f) or {}

    def get(self, dotted, default=None):
        node = self._cfg
        for key in dotted.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def venue(self, name):
        """Return (network, creds_dict) for a venue, per its `network` selector."""
        network = self.get(f"apis.{name}.network", "testnet")
        creds = self.get(f"apis.{name}.{network}", {}) or {}
        return network, creds

    def jurisdiction_acknowledged(self):
        return self.get("trading.jurisdiction_acknowledged", False) is True
