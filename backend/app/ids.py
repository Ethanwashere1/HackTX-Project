"""Opaque prefixed IDs, e.g. usr_01jb3k9x2c7q4m8z5r6t2v.

The part after the prefix starts with a millisecond timestamp, so IDs sort by creation time
(used for `?after=msg_…` paging), followed by random characters.
"""

import secrets
import time

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32, lowercase


def _b32(n: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[n & 31])
        n >>= 5
    return "".join(reversed(out))


def new_id(prefix: str) -> str:
    ts = _b32(int(time.time() * 1000), 10)
    rand = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    return f"{prefix}_{ts}{rand}"


def id_factory(prefix: str):
    return lambda: new_id(prefix)
