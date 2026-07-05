"""Canonical JSON serialisation — deterministic bytes for hashing and signing.

Same encoding convention as veriseal's manifest spec (SPEC-manifest.md ss1):
sorted keys, no insignificant whitespace, non-ASCII left as-is, NaN/Infinity
forbidden, UTF-8 output. Rating Bridge adds a single trailing ``\n`` so the
canonical bytes double as a normal, diff-friendly text file on disk.

"Fixed float precision" (per the build spec) is achieved upstream: every
float that goes into a report is rounded to a fixed number of decimal places
before it ever reaches this function (see metrics.py / report.py). This
function itself does not silently reformat floats — it relies on its input
already being canonical-precision, so re-running the pipeline on the same
source file byte-for-byte reproduces byte-identical canonical output.
"""

from __future__ import annotations

import json


def canonical_bytes(obj: object) -> bytes:
    """Return the canonical UTF-8 byte encoding of *obj*, plus a trailing newline."""
    text = json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (text + "\n").encode("utf-8")
