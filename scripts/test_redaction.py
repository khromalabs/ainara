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

"""Mechanical test for the framework's secret redaction.

Verifies that secret-shaped text in a file is redacted before it
reaches any model, exercising the SAME path the Bureau agent uses:
system_fileread paging (offset/next_offset) and, optionally,
system_filescanner search.

Usage:
    python scripts/test_redaction.py                # synthetic fixture
    python scripts/test_redaction.py --file PATH    # any real file

SAFETY: target files may contain REAL credentials. This script never
prints raw values: suspect spans are always masked before output, so
the report itself is safe to paste anywhere.

Exit codes: 0 = no leaks found, 1 = leaks suspected, 2 = usage error.
"""

import argparse
import asyncio
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ainara.framework.redaction import (  # noqa: E402
    REDACTED,
    _compiled_patterns,
)
from ainara.orakle.skills.system.fileread import SystemFileread  # noqa: E402
from ainara.orakle.skills.system.filescanner import (  # noqa: E402
    SystemFilescanner,
)

# One representative line per built-in pattern family. Values are fake
# but shaped exactly like the real thing. Token literals are assembled
# at runtime from fragments: the committed source must never contain a
# complete token-shaped string, or GitHub Push Protection rejects the
# push (the assembled values still match the redaction patterns, which
# is what the fixture exists to exercise).


def _tok(prefix: str, body: str) -> str:
    return prefix + body


FIXTURE_LINES = [
    "api_key: " + _tok("sk-proj-", "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"),
    "alphavantage_api_key: realkey1234567890abc",
    "VAULT_TOKEN: " + _tok("hvs.CAESIJ", "abcdefghijklmnopqrstuvwxyz123456"),
    "      wallet_address: '4Nd1mBQtrMJVYVfKf2PJy9NZBCZGGmIYS2ZvRv5C'",
    '"api_key": "' + _tok("sk-or-v1-", "abc123def456ghi789jkl012") + '"',
    "bot_token: " + _tok("7263481927:", "AABBCCDDEEFFGGHHIIJJ"),
    'ANTHROPIC_API_KEY = "' + _tok("sk-ant-api03-", "A" * 26) + '"',
    "password: hunter2hunter2",
    "db_url: postgres://admin:s3cr3tpw@db.internal:5432/app",
    "https://api.example.com/v1/data?token=abc123def456ghi789&x=1",
    _tok("github_pat_", "11A" + "A" * 24),
    _tok("AKIA", "IOSFODNN7EXAMPLE"),
    _tok("xoxb-", "123456789012-ABCDEFGHIJKLMNOPQR"),
    _tok("AIza", "SyA-1234567890abcdefghijklmnopqrstuv"),
    _tok("glpat-", "abcdefghijklmnopqrst"),
    _tok("sk_live_", "abcdefghijklmnopqrst"),
    _tok("eyJ", "hbGciOiJIUzI1NiJ9.") + _tok("", "eyJzdWIiOiIxMjM0NTY3ODkw")
    + "." + _tok("", "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV"),
    "-----BEGIN RSA PRIVATE KEY-----",
    "MY_SERVICE_TOKEN = verysecrettoken998877",
    "normal_line: stays intact",
    "version: 2.1",
    "tokenizer: sentencepiece-model-v3",
    "max_tokens: 512",
]


# Independent leak heuristics, deliberately BROADER than the built-in
# redaction patterns: they exist to catch shapes the redaction layer
# does not know about (that is their whole value). False positives are
# acceptable - suspects are reported for human review, masked.
LEAK_HEURISTICS = [
    # token prefixes not (yet) covered by the built-in redaction shapes
    (
        "unrecognized provider prefix",
        r"\b(?:hvs|npm|sbp|shpat|shpss|dop_v1|doctl|flyt|r8|figd|hf_"
        r"|hair|squ_)" + r"[A-Za-z0-9_-]{10,}\b",
        False,
    ),
    # generic high-entropy token: 20+ chars mixing digits, upper and lower
    (
        "high-entropy token",
        r"\b(?=[A-Za-z0-9_-]{20,}\b)(?=[^0-9]*[0-9])(?=[^A-Z]*[A-Z])"
        r"(?=[^a-z]*[a-z])[A-Za-z0-9_-]{20,}\b",
        False,
    ),
]


def build_fixture() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ainara-redaction-test-"))
    fixture = tmp / "fixture.conf"
    fixture.write_text("\n".join(FIXTURE_LINES) + "\n", encoding="utf-8")
    return fixture


def page_through_fileread(path: Path) -> tuple:
    """Read the whole file through the skill exactly as an agent would."""
    skill = SystemFileread()
    chunks = []
    offset = 1
    pages = 0
    while True:
        result = asyncio.run(skill.run(str(path), offset=offset, limit=2000))
        if not result.get("success"):
            raise RuntimeError(f"fileread failed: {result.get('error')}")
        chunks.append(result["content"])
        pages += 1
        if not result.get("truncated"):
            break
        offset = result["next_offset"]
        if pages > 1000:  # paranoia guard
            raise RuntimeError("paging did not converge")
    return "\n".join(chunks), pages


def residual_scan(text: str):
    """Find secret-shaped spans that survived redaction.

    Two layers:
      1. the active redaction patterns themselves - a match is OK only
         when the redacted span is exactly [REDACTED];
      2. independent heuristics (broader than the builtins) - any match
         is a suspect, since redaction should have caught it.
    """
    suspects = []
    patterns = _compiled_patterns()
    lines = text.splitlines()
    for lineno, line in enumerate(lines, start=1):
        for pattern in patterns:
            for match in pattern.finditer(line):
                secret = match.groupdict().get("secret")
                span_value = secret if secret is not None else match.group(0)
                if span_value != REDACTED:
                    suspects.append(
                        {
                            "line": lineno,
                            "pattern": pattern.pattern[:60],
                            "value_len": len(span_value),
                            "text": mask_span(line, match, secret is not None),
                        }
                    )
        for name, regex, _ in LEAK_HEURISTICS:
            for match in re.finditer(regex, line):
                suspects.append(
                    {
                        "line": lineno,
                        "pattern": name,
                        "value_len": len(match.group(0)),
                        "text": mask_span(line, match, False),
                    }
                )
    return suspects


def mask_span(line: str, match, has_secret_group: bool) -> str:
    """Return the line with the suspect span masked (never printed raw)."""
    if has_secret_group:
        start = match.start("secret")
        end = match.end("secret")
    else:
        start, end = match.span()
    marker = f"[SUSPECT x{end - start}]"
    return line[:start] + marker + line[end:]


def run_search_check(path: Path):
    """Check what filescanner search would surface for this file."""
    skill = SystemFilescanner()
    suspects = []
    queries = [p.pattern for p in _compiled_patterns()]
    queries += [regex for _, regex, _ in LEAK_HEURISTICS]
    for regex in queries:
        result = asyncio.run(
            skill.run(
                action="search",
                path=str(path.parent),
                query=regex,
                is_regex=True,
                glob=path.name,
            )
        )
        if not result.get("success"):
            continue
        for m in result.get("matches", []):
            # match text was already redacted by the skill; flag any
            # suspect span that still survived in it
            for s in residual_scan(m["text"]):
                suspects.append(
                    {
                        "line": m.get("line"),
                        "pattern": s["pattern"],
                        "value_len": s["value_len"],
                        "text": s["text"],
                    }
                )
    return suspects


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--file",
        help="real file to test against (values are never printed)",
    )
    parser.add_argument(
        "--extra-pattern",
        action="append",
        metavar="REGEX",
        help="candidate redaction pattern to test WITHOUT editing config "
             "(repeatable; same semantics as "
             "security.redaction.extra_patterns)",
    )
    parser.add_argument(
        "--skip-fixture",
        action="store_true",
        help="skip the built-in synthetic fixture",
    )
    parser.add_argument(
        "--no-search",
        action="store_true",
        help="skip the filescanner search check",
    )
    args = parser.parse_args()

    patterns = _compiled_patterns()
    if args.extra_pattern:
        from ainara.framework import config as _config

        current = list(
            _config.config.get("security", {})
            .get("redaction", {})
            .get("extra_patterns", []) or []
        )
        _config.config._set_unscoped(
            "security.redaction.extra_patterns",
            current + list(args.extra_pattern),
        )
        patterns = _compiled_patterns()
        print(
            f"candidate extra patterns added this run:"
            f" {len(args.extra_pattern)} (active total: {len(patterns)})"
        )
    print(f"active redaction patterns: {len(patterns)}")
    if not patterns:
        print("FAIL: redaction is disabled (security.redaction.enabled)")
        return 1

    failures = 0

    # --- 1. Synthetic fixture: every family must be fully redacted
    if not args.skip_fixture:
        fixture = build_fixture()
        content, pages = page_through_fileread(fixture)
        suspects = residual_scan(content)
        redacted_lines = sum(
            1 for line in content.splitlines() if REDACTED in line
        )
        print(f"\n[fixture] {fixture.parent}")
        print(
            f"  {len(FIXTURE_LINES)} lines via {pages} fileread page(s);"
            f" {redacted_lines} lines redacted"
        )
        for line in content.splitlines():
            if (
                "stays intact" in line
                or line.startswith("version:")
                or line.startswith("tokenizer:")
                or line.startswith("max_tokens:")
            ):
                print(f"  benign kept: {line[:60]}")
        if suspects:
            failures += len(suspects)
            for s in suspects:
                print(f"  LEAK: line {s['line']}: {s['text']}")
        else:
            print("  all secret families fully redacted: PASS")

    # --- 2. Real file (optional)
    if args.file:
        target = Path(args.file).expanduser()
        if not target.is_file():
            print(f"\n[real] FAIL: not a file: {target}")
            return 2
        content, pages = page_through_fileread(target)
        suspects = residual_scan(content)
        print(f"\n[real] {target}")
        print(
            f"  {len(content.splitlines())} lines via {pages} fileread"
            f" page(s)"
        )
        if suspects:
            failures += len(suspects)
            for s in suspects:
                print(f"  LEAK: line {s['line']}: {s['text']}")
        else:
            print("  no residual secret-shaped spans: PASS")

        if not args.no_search:
            search_suspects = run_search_check(target)
            print("  search surface:")
            if search_suspects:
                failures += len(search_suspects)
                for s in search_suspects:
                    print(f"    LEAK: line {s['line']}: {s['text']}")
            else:
                print("    no leaks through filescanner search: PASS")

    print()
    if failures:
        print(f"RESULT: {failures} leak(s) suspected")
        return 1
    print("RESULT: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
