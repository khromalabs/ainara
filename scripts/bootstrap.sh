#!/usr/bin/env bash
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

# Thin launcher for scripts/bootstrap.py (Linux/macOS).
# Only locates a suitable Python interpreter; all logic lives in bootstrap.py.

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        exec "$candidate" "$REPO_ROOT/scripts/bootstrap.py" "$@"
    fi
done

echo "bootstrap: no Python interpreter found (Python 3.12 required)" >&2
exit 1
