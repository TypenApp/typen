"""
Lexical Token Guards (Zero-Touch Rules).
Protects technical users from unwanted corrections on code identifiers,
CLI flags, URLs, emails, paths, acronyms, numbers, and mixed-case symbols.
"""

from __future__ import annotations

import re
from typing import Final

# Prefixes that indicate CLI flags, paths, mentions, hashtags, or variables
PROTECTED_PREFIXES: Final[tuple[str, ...]] = (
    "--",
    "-",
    "/",
    "\\",
    "@",
    "#",
    "$",
    "~",
    ".",
    "::",
    "->",
    "=>",
)

URL_OR_EMAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"^(https?://|www\.|[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)",
    re.IGNORECASE,
)

HEX_OR_HASH_RE: Final[re.Pattern[str]] = re.compile(r"^(0x[0-9a-fA-F]+|[0-9a-fA-F]{7,})$")

# Intentional repeated or operator punctuation that must never be normalized
INTENTIONAL_PUNCTUATION: Final[frozenset[str]] = frozenset(
    {
        "...",
        "..",
        "?!",
        "!?",
        "!!",
        "??",
        "->",
        "=>",
        "::",
        "!=",
        "==",
        "===",
        "!==",
        "<=",
        ">=",
        "<<",
        ">>",
        "//",
        "/*",
        "*/",
    }
)


def is_camel_or_pascal_case(token: str) -> bool:
    """
    Return True if token has internal uppercase transitions typical of camelCase or PascalCase
    (e.g. 'useState', ' FastAPI', 'PyInstaller', 'getElementById').
    Note: Initial double-caps typo like 'THe' is NOT camelCase; camelCase has a lowercase
    followed by an uppercase letter later in the word.
    """
    if len(token) < 3:
        return False
    has_lower = False
    for ch in token[1:]:
        if ch.islower():
            has_lower = True
        elif ch.isupper() and has_lower:
            return True
    return False


def is_initial_double_cap_typo(token: str) -> bool:
    """
    Detect accidental Shift-hold typos at the start of a word such as 'THe', 'WIll', 'THis',
    where the first 2 characters are uppercase and the remaining (>=1) characters are lowercase.
    """
    if len(token) < 3:
        return False
    return token[0].isupper() and token[1].isupper() and token[2:].islower()


def is_all_caps_acronym(token: str) -> bool:
    """
    Return True if token is ALL_CAPS (length 2..6, e.g., 'API', 'HTTP', 'JSON', 'SQL', 'NASA')
    so we do not accidentally rewrite acronyms into regular words.
    """
    alpha_only = "".join(ch for ch in token if ch.isalpha())
    if len(alpha_only) < 2:
        return False
    return alpha_only.isupper()


MENTION_PREFIXES: Final[tuple[str, ...]] = ("@", "#")


def should_skip_token(
    token: str,
    leading_prefix: str = "",
    *,
    ignore_digits: bool = True,
    ignore_acronyms: bool = True,
    ignore_symbols: bool = True,
    ignore_mentions: bool = True,
    ignore_longer_than: int = 0,
) -> bool:
    """
    Evaluate all zero-touch lexical guards.
    Returns True if the token must be preserved verbatim without spelling correction.
    The `ignore_*` switches are the user's "Ignore rules"; the structural guards
    (URLs, code symbols, camelCase, hex) are always on.
    """
    if not token:
        return True

    # 1. Single characters (except 'i' which is handled by pronoun capitalisation)
    if len(token) == 1 and token != "i":
        return True

    # 1a. Very long tokens are identifiers, hashes or pasted keys, never prose.
    if ignore_longer_than and len(token) > ignore_longer_than:
        return True

    # 2. Protected leading prefixes (CLI flags, paths, mentions, hashtags, env vars)
    if leading_prefix:
        if any(leading_prefix.endswith(p) for p in MENTION_PREFIXES):
            if ignore_mentions:
                return True
        elif any(leading_prefix.endswith(p) for p in PROTECTED_PREFIXES):
            return True

    # 2a. Trailing possessive apostrophe on a plural/sibilant noun ("dogs'", "James'",
    #     "programs'"): leave the word verbatim rather than treating the bare stem as OOV.
    if len(token) > 2 and token[-1] in ("'", "\u2019") and token[:-1].isalpha():
        return True

    # 2b. Internal hyphenated compound with alphabetic parts on both sides
    #     ("world-wide", "state-of-the-art", "non-profit", "re-evaluated"): intentional
    #     user formatting, never collapse it into a single word.
    if ignore_symbols and "-" in token.strip("-"):
        parts = token.split("-")
        if len(parts) >= 2 and all(p.isalpha() for p in parts if p):
            return True

    # 3. Any token containing digits (v2, covid19, mp4, 3d, sha256, passwords)
    if ignore_digits and any(ch.isdigit() for ch in token):
        return True

    # 4. Snake_case, paths, or embedded code symbols
    if any(sym in token for sym in ("/", "\\", "@", "$", "=", "+", "*", "<", ">", "|", "`")):
        return True
    if ignore_symbols and "_" in token:
        return True

    # 5. URLs, domains, or email addresses
    if URL_OR_EMAIL_RE.match(token):
        return True

    # 6. Internal dots (e.g. file.py, config.json, U.S.A, node.js)
    if ignore_symbols and "." in token.strip("."):
        return True

    # 7. camelCase or PascalCase identifiers (e.g. useEffect, TypeScript)
    if is_camel_or_pascal_case(token):
        return True

    # 8. Short ALL_CAPS acronyms (2..5 chars like HTML, WSGI, CORS, НАТО)
    # Note: Longer all-caps typos (e.g. RECIEVED) can be corrected if unambiguous,
    # so we only guard short acronyms <= 5 letters unless in direct typo table.
    if ignore_acronyms and is_all_caps_acronym(token) and len(token) <= 5:
        return True

    # 9. Hex strings
    if HEX_OR_HASH_RE.match(token):
        return True

    return False
