#!/usr/bin/env python3
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

"""Runtime libraries we deliberately never ship in the frozen bundles.

PyInstaller collects these as transitive dependencies of compiled
extensions (sounddevice -> libportaudio -> libjack, chromadb ->
onnxruntime, ...) even though the manylinux builder only has old
copies of them. On a modern host those frozen copies precede the
host's own libstdc++ on the loader search path, shadow it, and satisfy
lookups that system libraries make for newer GLIBCXX symbols -- which
then fail at import time:

    version `GLIBCXX_3.4.32' not found (required by .../libjack.so.0)

Consumers:
  - scripts/pyinstaller/servers.spec  (filters Analysis.binaries)
  - scripts/_build.py                 (post-COLLECT verifier)
"""

SHADOWED_RUNTIME_LIBS = {
    "libstdc++.so.6",
    "libgcc_s.so.1",
    "libgomp.so.1",
}
