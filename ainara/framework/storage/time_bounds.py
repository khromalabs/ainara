# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

"""Date-window bound parsing shared by the storage backends.

Timestamps are stored as ISO-8601 strings (UTC, "+00:00" offset) in the
relational store, and as both that string and a numeric epoch mirror
("timestamp_ts") in vector-store metadata. Callers — agents, UI
surfaces — however state windows in human terms, often bare
"YYYY-MM-DD" dates.

A bare date used as the END of a window must cover the whole of that
day: as a plain string it sorts before every full timestamp of the day
and would silently exclude it (this bit Deep Recall: "what did we talk
about yesterday" matched nothing).

Both backends receive their bounds from this parser so their semantics
cannot drift:

- bare "YYYY-MM-DD" → start: 00:00:00 UTC, end: 23:59:59.999999 UTC
  (inclusive bounds on both routes)
- full ISO string   → parsed as-is ("Z" suffix supported); naive
  datetimes are interpreted as UTC
- anything else     → None (callers decide: the semantic route falls
  back to the text route, which passes the raw string to SQL unchanged)
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

BARE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def resolve_date_bound(
    value: Optional[str], is_end: bool = False
) -> Optional[datetime]:
    """Parse a date-window bound into an aware UTC datetime.

    Args:
        value: Bare "YYYY-MM-DD" date or full ISO-8601 timestamp.
        is_end: For bare dates, whether this bound is the END of the
            window (whole day covered) or its start (midnight). Full
            timestamps are unaffected by this flag.

    Returns:
        Timezone-aware datetime, or None when the value is empty or
        cannot be parsed.
    """
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    try:
        if BARE_DATE_RE.match(value):
            base = datetime.strptime(value, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            if is_end:
                # Whole of that day: last microsecond before midnight.
                return base + timedelta(days=1) - timedelta(microseconds=1)
            return base
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def resolve_epoch_bound(
    value: Optional[str], is_end: bool = False
) -> Optional[float]:
    """Parse a date-window bound into a Unix epoch float (for vector
    store metadata filters, whose range operators only work on numeric
    values)."""
    dt = resolve_date_bound(value, is_end)
    return dt.timestamp() if dt else None


def timestamp_to_epoch(value: Optional[str]) -> Optional[float]:
    """Epoch float for a stored message timestamp (full ISO expected;
    bare dates resolve to midnight UTC). None when unusable."""
    dt = resolve_date_bound(value, is_end=False)
    return dt.timestamp() if dt else None
