"""MCAP file I/O helpers — raw (schema-agnostic) message iteration + digest."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from mcap.reader import make_reader


@dataclass(frozen=True)
class RawMessage:
    topic: str
    schema_name: str
    log_time_ns: int
    payload_len: int


def file_digest(path: Path) -> tuple[str, int]:
    """Return (sha256_hex, size_bytes) for *path* using streaming reads."""
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def iter_raw_messages(path: Path) -> Iterator[RawMessage]:
    """Yield a RawMessage per MCAP message, without decoding the payload.

    This is intentionally schema-agnostic: session/continuity metrics need
    only (topic, time, size), not the decoded content, so this path never
    fails on an exotic or unsupported message encoding.
    """
    with open(path, "rb") as f:
        reader = make_reader(f)
        for schema, channel, message in reader.iter_messages():
            schema_name = schema.name if schema is not None else "(schemaless)"
            yield RawMessage(channel.topic, schema_name, message.log_time, len(message.data))


def list_channels(path: Path) -> list[tuple[str, str]]:
    """Return sorted [(topic, schema_name), ...] present in the file (summary pass)."""
    with open(path, "rb") as f:
        reader = make_reader(f)
        summary = reader.get_summary()
        if summary is None:
            # Fall back to a full scan for files without a summary section.
            seen: dict[str, str] = {}
            for rm in iter_raw_messages(path):
                seen[rm.topic] = rm.schema_name
            return sorted(seen.items())
        out = []
        for channel in summary.channels.values():
            schema = summary.schemas.get(channel.schema_id)
            out.append((channel.topic, schema.name if schema else "(schemaless)"))
        return sorted(out)
