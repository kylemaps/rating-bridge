from __future__ import annotations

from pathlib import Path

import pytest
from mcap.writer import Writer


@pytest.fixture
def synthetic_mcap(tmp_path: Path) -> Path:
    """A tiny, schemaless MCAP: two topics, one intentional >1s gap."""
    path = tmp_path / "synthetic.mcap"
    with open(path, "wb") as f:
        writer = Writer(f)
        writer.start()
        chan_a = writer.register_channel(topic="/foo", message_encoding="json", schema_id=0)
        chan_b = writer.register_channel(topic="/bar", message_encoding="json", schema_id=0)

        # /foo: five messages, 0.1s apart
        for i in range(5):
            t = i * 100_000_000  # 0.1s in ns
            writer.add_message(chan_a, log_time=t, data=b"{}", publish_time=t)

        # /bar: one message, then a 2s gap, then one more (exercises continuity)
        writer.add_message(chan_b, log_time=0, data=b"{}", publish_time=0)
        writer.add_message(chan_b, log_time=2_500_000_000, data=b"{}", publish_time=2_500_000_000)

        writer.finish()
    return path
