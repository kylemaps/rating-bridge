"""Rating Bridge — MCAP -> signed, re-runnable exposure & incident report.

The middle of the pipeline: veriseal seals raw MCAP telemetry; Rating Bridge
reads a (sealed or unsealed) MCAP log and produces a deterministic, signed
"Exposure & Incident Report" that an insurance underwriter can rate against,
with incident stubs shaped to the Agent Loss Record (ALR) schema.
"""

from __future__ import annotations

__version__ = "0.1.0"
