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

"""Token estimation for the framework size guards (issue #37).

Every guard that converts bytes to tokens (the offload size trigger,
digestion input feasibility, the digest output bound, the budget
ledger) shares this one estimator, replacing the flat
``chars_per_token = 3`` conversion.

This is deliberately NOT a tokenizer. Guards prefer cheap, conservative
estimates over exact counts: a tokenizer dependency would cost startup
time and model downloads for precision the guards do not need — they
exist to keep payloads away from provider overflow, not to bill exact
tokens.

The conversion keeps 3 chars/token for Latin text and drops toward
~1.5 for CJK-heavy payloads via a codepoint-density sniff. That closes
the one real silent-overflow path: CJK text carries far more
information per character than a 3-chars-per-token conversion assumes,
so ~94KB of Japanese estimates ~31K tokens at the flat rate while the
provider sees ~60–90K. Interpolating linearly between the two rates
over the CJK fraction keeps mixed-language payloads monotonic; ceiling
rounding preserves a conservative bias.

TODO (#37): possible refinement — litellm.token_counter (already a
framework dependency, used by the LLM backends for chat-history
accounting) is accurate for mapped models and its fallback measures
conservative on CJK. If live testing shows this estimator's Latin
conservatism (overestimates English ~1.5x) visibly degrading the
triggers, invert the layering: token_counter primary here, this
density sniff as the failure fallback. Deliberately deferred: guards
must not change behavior across litellm versions, and the error is on
the safe side.
"""

import math

# Latin rate matches the historical flat conversion (and the
# orakle.context.chars_per_token config default); the CJK rate reflects
# the typical ~1.5–2 chars/token of CJK tokenizer output, biased low
# (more tokens) for safety.
LATIN_CHARS_PER_TOKEN = 3.0
CJK_CHARS_PER_TOKEN = 1.5

# CJK fraction at/below which the Latin rate holds and at/above which
# the CJK rate holds; between the two the rate interpolates linearly.
_CJK_FRACTION_LOW = 0.0
_CJK_FRACTION_HIGH = 0.5

# Han, kana, hangul and the CJK punctuation/fullwidth blocks that ride
# with them. Pure-ASCII text never reaches the scan (the common case:
# logs, code, JSON pay nothing).
_CJK_CODEPOINTS = frozenset(
    cp
    for lo, hi in (
        (0x2E80, 0x2EFF),  # CJK radicals supplement
        (0x3000, 0x303F),  # CJK symbols and punctuation
        (0x3040, 0x30FF),  # Hiragana + Katakana
        (0x3130, 0x318F),  # Hangul compatibility jamo
        (0x3400, 0x4DBF),  # CJK extension A
        (0x4E00, 0x9FFF),  # CJK unified ideographs
        (0xAC00, 0xD7AF),  # Hangul syllables
        (0xF900, 0xFAFF),  # CJK compatibility ideographs
        (0xFF00, 0xFF60),  # fullwidth forms
    )
    for cp in range(lo, hi + 1)
)


def cjk_fraction(text: str) -> float:
    """Fraction of characters drawn from CJK blocks (0.0 for empty)."""
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if ord(ch) in _CJK_CODEPOINTS)
    return cjk / len(text)


def effective_chars_per_token(text: str) -> float:
    """Chars-per-token rate for *this* text (not a corpus average)."""
    if not text or text.isascii():
        return LATIN_CHARS_PER_TOKEN
    fraction = cjk_fraction(text)
    if fraction <= _CJK_FRACTION_LOW:
        return LATIN_CHARS_PER_TOKEN
    if fraction >= _CJK_FRACTION_HIGH:
        return CJK_CHARS_PER_TOKEN
    span = _CJK_FRACTION_HIGH - _CJK_FRACTION_LOW
    t = (fraction - _CJK_FRACTION_LOW) / span
    return LATIN_CHARS_PER_TOKEN - (
        (LATIN_CHARS_PER_TOKEN - CJK_CHARS_PER_TOKEN) * t
    )


def estimate_tokens(text: str, chars_per_token: float = None) -> int:
    """Conservative token estimate for a text payload.

    By default the CJK-aware density sniff rates the payload itself
    (the guard behavior: mixed-language payloads get monotonic,
    conservative estimates). Pass ``chars_per_token`` explicitly to
    force a flat rate — e.g. callers deriving byte ceilings from the
    configured ``orakle.context.chars_per_token``. Ceiling rounding
    biases toward overestimation — the guards this feeds prefer false
    positives (an early, cheap rejection) over silent overflow.
    """
    if not text:
        return 0
    rate = (
        effective_chars_per_token(text)
        if chars_per_token is None
        else chars_per_token
    )
    if rate <= 0:
        rate = LATIN_CHARS_PER_TOKEN
    return math.ceil(len(text) / rate)
