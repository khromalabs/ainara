# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Guards for tests that can only run in one of the two virtualenvs.

`executor/server.py` imports `executor.venues.dydx` at module scope, which needs
the dYdX v4 signing SDK. Those packages live in the executor's own virtualenv and
deliberately not in the main one: `dydx-v4-client` requires `httpx<0.28` while the
framework's `solana` dependency requires `httpx>=0.28`, so the two cannot share an
environment. That split is the reason the executor is a separate process at all.

Without this guard the affected modules failed to IMPORT under the main venv, and
unittest reported four errors that looked like broken tests. They are not broken —
they are being run in the wrong interpreter, and the difference matters: an error
is something to fix, a skip with a reason is something to run elsewhere.

    ./executor/.venv/Scripts/python.exe -m unittest \\
        scripts.evaluation.tests.test_trading_venue_state
"""

import importlib
import unittest

# Imported by executor.venues.dydx. Checked by name rather than by attempting the
# executor import itself, so a genuine breakage inside executor/ still surfaces as
# an error instead of being quietly swallowed as "wrong environment".
_REQUIRED = ("bech32", "dydx_v4_client", "v4_proto")


def require_executor_deps():
    """Raise SkipTest when the venue signing SDKs are not importable.

    Called at module scope, before the `executor` imports. unittest's loader
    turns a SkipTest raised during module import into a reported skip rather
    than a collection error.
    """
    missing = []
    for name in _REQUIRED:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    if missing:
        raise unittest.SkipTest(
            "needs the executor virtualenv — the dYdX v4 signing SDK is not"
            f" importable here (missing: {', '.join(missing)}). These packages"
            " pin httpx<0.28 and cannot share an environment with the"
            " framework's solana dependency, so run this module with"
            " ./executor/.venv/Scripts/python.exe instead.")


# The other half of the same split. Tests that import `ainara.*` pull in the
# framework's config layer, which the executor's venv does not carry — for the
# same reason, in the other direction.
_FRAMEWORK_REQUIRED = ("jsonschema", "yaml")


def require_framework_deps():
    """Raise SkipTest when the Ainara framework's dependencies are absent.

    The mirror of require_executor_deps: called at module scope by tests that
    import `ainara.*`, so running the suite under the executor's interpreter
    reports them as skipped rather than as four import errors.
    """
    missing = []
    for name in _FRAMEWORK_REQUIRED:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    if missing:
        raise unittest.SkipTest(
            "needs the main virtualenv — the Ainara framework's dependencies"
            f" are not importable here (missing: {', '.join(missing)}). Run"
            " this module with ./venv/Scripts/python.exe instead.")
