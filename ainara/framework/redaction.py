# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html for details)
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

"""Mechanical secret redaction for content leaving local files.

File-analysis skills (fileread, filescanner) must never leak secrets
embedded in local files to a model — which, for remote providers, means
leaking them off the machine. This module redacts secret-shaped text
BEFORE content leaves the skill, mechanically and regardless of what
any model might "decide": redaction is a framework guard, not a skill
behavior and never a model instruction.

Behavioral contract:
  - Redaction is line-based and structure-preserving: when a pattern
    declares a ``(?P<secret>...)`` group, only that group is replaced
    (the rest of the line, e.g. ``api_key: ``, stays intact); otherwise
    the whole match is replaced.
  - Redaction may be over-eager on lines that merely look secret-shaped;
    that is the intended fail-safe direction. It never needs to be
    perfect, it needs to err on the side of redacting.
  - Built-in patterns can be disabled and user patterns added via
    config (``security.redaction.*``); an invalid user pattern is
    skipped with a warning, built-ins remain active.
"""

import logging
import re
from typing import Any, List, Pattern

from ainara.framework.config import config

logger = logging.getLogger(__name__)

REDACTED = "[REDACTED]"

# Built-in patterns. Order matters: earlier patterns win on overlapping
# spans. Most use a ``secret`` group so only the credential itself is
# replaced and the line structure survives for the model to read.
DEFAULT_SECRET_PATTERNS: List[str] = [
    # key/value assignments (YAML, JSON, Python, TOML...). The key may
    # be any identifier ENDING in a sensitive word - alphavantage_api_key,
    # VAULT_TOKEN, db.password, bot_token, wallet_address - optionally
    # quoted, so compound names are covered wherever they appear. The
    # sensitive word must be the identifier's suffix: it keeps plain
    # identifiers like 'tokens' or 'tokenizer' (token counts, code) out
    # of the blast radius.
    r"(?i)['\"]?[\w.\-]{0,64}?(?:"
    r"api[_-]?keys?|api[_-]?secrets?|api[_-]?hash|"
    r"client[_-]?secrets?|secret[_-]?keys?|secrets?|"
    r"access[_-]?keys?|access[_-]?tokens?|auth[_-]?tokens?|"
    r"refresh[_-]?tokens?|token|passphrases?|passwords?|passwd|pwd|"
    r"private[_-]?keys?|wallet[_-]?address|wallet|credentials"
    r")['\"]?\s*[:=]\s*['\"]?(?P<secret>[^\s'\"]{4,})['\"]?",
    # credentials inside connection strings / DSNs
    r"(?i)\b(postgres|postgresql|mysql|mongodb(?:\+srv)?|redis|amqp|"
    r"smtp|ftp)://(?P<secret>[^:\s/@]{1,}:[^@\s/]{1,})@",
    # credentials in URL query parameters
    r"(?i)[?&](api[_-]?key|apikey|access[_-]?token|token|secret|password|"
    r"signature)=(?P<secret>[^&\s]+)",
    # well-known provider token shapes (whole match replaced)
    r"(?:sk-ant-[A-Za-z0-9_-]{20,}|sk-proj-[A-Za-z0-9_-]{20,}|"
    r"sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|"
    r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|"
    r"glpat-[A-Za-z0-9_-]{15,}|sk_live_[A-Za-z0-9]{15,}|"
    r"sk_test_[A-Za-z0-9]{15,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})",
    # PEM private key headers
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
]


def _compiled_patterns() -> List[Pattern[str]]:
    """Build the active pattern list from config, compiled and validated."""
    if not config.get("security.redaction.enabled", True):
        return []
    raw: List[str] = []
    if config.get("security.redaction.use_builtins", True):
        raw.extend(DEFAULT_SECRET_PATTERNS)
    extra = config.get("security.redaction.extra_patterns", []) or []
    if not isinstance(extra, list):
        logger.warning(
            "security.redaction.extra_patterns must be a list of regex"
            " strings; ignoring value"
        )
        extra = []
    raw.extend(p for p in extra if isinstance(p, str) and p)

    compiled: List[Pattern[str]] = []
    for p in raw:
        try:
            compiled.append(re.compile(p))
        except re.error as e:
            logger.warning(
                "Ignoring invalid security.redaction pattern"
                f" {p!r}: {e}"
            )
    return compiled


def _apply(pattern: Pattern[str], line: str) -> str:
    """Apply one compiled pattern to a line, replacing the secret span."""

    def _sub(match: "re.Match[str]") -> str:
        secret = match.groupdict().get("secret")
        if secret is None:
            return REDACTED
        start = match.start("secret") - match.start()
        end = match.end("secret") - match.start()
        return match.group(0)[:start] + REDACTED + match.group(0)[end:]

    return pattern.sub(_sub, line)


def redact_text(text: str, patterns: Any = None) -> str:
    """Return text with secret-shaped spans replaced by [REDACTED].

    Line-based so line structure (and line counts) survive intact.
    ``patterns`` allows passing pre-compiled patterns; when omitted the
    active set is built from config.
    """
    compiled = patterns if patterns is not None else _compiled_patterns()
    if not compiled:
        return text
    return "\n".join(_apply_all(compiled, line) for line in text.splitlines())


def _apply_all(compiled: List[Pattern[str]], line: str) -> str:
    for p in compiled:
        line = _apply(p, line)
    return line
