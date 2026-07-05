"""Build the exposure_report.json dict and render exposure_report.md."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import rating_bridge
from rating_bridge.incidents import build_incidents
from rating_bridge.mcap_io import file_digest
from rating_bridge.metrics import (
    GAP_THRESHOLD_S,
    HARD_DECEL_THRESHOLD_MPS2,
    autonomy_metrics,
    motion_metrics,
    session_and_continuity_metrics,
)

SCHEMA_VERSION = "rating-bridge-exposure-report-v1"


def build_report(
    source_path: Path,
    source_url: str | None,
    source_derivation: str | None,
    reproduce_command: str,
) -> dict:
    sha256_hex, size_bytes = file_digest(source_path)
    session, continuity = session_and_continuity_metrics(source_path)
    motion, hard_decel_events = motion_metrics(source_path)
    topics = [t["topic"] for t in session["topics"]]
    autonomy = autonomy_metrics(topics)
    incidents = build_incidents(source_path.name, sha256_hex, continuity["gaps"], hard_decel_events)

    report = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": rating_bridge.__version__,
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provenance": {
            "source_filename": source_path.name,
            "source_sha256": sha256_hex,
            "source_size_bytes": size_bytes,
            "source_url": source_url or "not_present_in_source",
            "source_derivation": source_derivation or "not_present_in_source",
            "command_to_reproduce": reproduce_command,
            "gap_threshold_s": GAP_THRESHOLD_S,
            "hard_decel_threshold_mps2": HARD_DECEL_THRESHOLD_MPS2,
        },
        "session": session,
        "continuity": continuity,
        "motion": motion,
        "autonomy": autonomy,
        "incidents": incidents,
        "notes": {
            "proves": (
                "Integrity and derivation: this report was computed deterministically from "
                "the exact source file bytes hashed in provenance.source_sha256, using the "
                "documented rules and thresholds above. Re-running the command in "
                "provenance.command_to_reproduce against the same file byte-for-byte "
                "reproduces this report exactly."
            ),
            "does_not_prove": (
                "Veracity at capture. Nothing here proves the source log is a truthful "
                "record of physical reality, that sensors were calibrated, or that no "
                "out-of-band editing occurred before this file reached this tool. Pair with "
                "a veriseal seal made at/near capture time for that guarantee. Incident "
                "entries are DRAFT, threshold-triggered stubs — not adjudicated losses."
            ),
        },
    }
    return report


def _fmt(value, suffix: str = "") -> str:
    if value == "not_present_in_source":
        return "*not present in source*"
    return f"{value}{suffix}"


def render_markdown(report: dict) -> str:
    p = report["provenance"]
    s = report["session"]
    c = report["continuity"]
    m = report["motion"]
    a = report["autonomy"]
    incidents = report["incidents"]

    lines: list[str] = []
    ap = lines.append

    ap(f"# Exposure & Incident Report — `{p['source_filename']}`")
    ap("")
    ap(f"Generated {report['generated_utc']} by Rating Bridge v{report['tool_version']}")
    ap("")
    ap("## Headline")
    ap("")
    ap(f"- **Session duration:** {_fmt(s['duration_s'], 's')}  ({s['message_count']} messages, "
       f"{len(s['topics'])} topics)")
    ap(f"- **Continuity gaps (> {c['gap_threshold_s']}s):** {c['gap_count']}"
       + (f", longest {c['longest_gap_s']}s" if c["gap_count"] else ""))
    if m["status"] == "computed":
        ap(f"- **Distance traveled:** {m['distance_m']} m  "
           f"(mean {m['mean_speed_mps']} m/s, max {m['max_speed_mps']} m/s)")
        ap(f"- **Hard-deceleration events (>= {m['hard_decel_threshold_mps2']} m/s^2):** "
           f"{m['hard_decel_event_count']}")
    else:
        ap("- **Motion (distance / speed / hard-braking):** *not present in source* — "
           f"{m['reason']}")
    if a["status"] == "computed":
        ap(f"- **Autonomous time:** {a['autonomous_time_s']}s / "
           f"**Manual time:** {a['manual_time_s']}s / "
           f"**Interventions:** {a['intervention_count']}")
    else:
        ap("- **Autonomy engagement:** *not present in source* — " + a["reason"])
    ap(f"- **Draft incidents flagged:** {len(incidents)}")
    ap("")

    ap("## Provenance")
    ap("")
    ap(f"- Source file: `{p['source_filename']}`")
    ap(f"- SHA-256: `{p['source_sha256']}`")
    ap(f"- Size: {p['source_size_bytes']:,} bytes")
    ap(f"- Source URL: {p['source_url']}")
    ap(f"- Derivation: {p['source_derivation']}")
    ap(f"- Reproduce with: `{p['command_to_reproduce']}`")
    ap("")

    ap("## Session")
    ap("")
    ap(f"- Start (UTC): {s['start_utc']}")
    ap(f"- End (UTC): {s['end_utc']}")
    ap(f"- Duration: {s['duration_s']} s")
    ap(f"- Message count: {s['message_count']}")
    ap("")
    ap("| Topic | Schema | Count | Mean rate (Hz) | Bytes |")
    ap("|---|---|---:|---:|---:|")
    for t in s["topics"]:
        row = f"| `{t['topic']}` | {t['schema']} | {t['count']} | {t['mean_rate_hz']} "
        ap(row + f"| {t['bytes']:,} |")
    ap("")

    ap("## Continuity")
    ap("")
    ap(f"- Gap threshold: {c['gap_threshold_s']} s")
    ap(f"- Gaps detected: {c['gap_count']}")
    ap(f"- Longest gap: {c['longest_gap_s']} s")
    ap(f"- Max observed inter-message interval (any gap, not just qualifying ones): "
       f"{c['max_observed_interval_s']} s")
    if c["gaps"]:
        ap("")
        ap("| Start (UTC) | End (UTC) | Duration (s) |")
        ap("|---|---|---:|")
        for g in c["gaps"]:
            ap(f"| {g['start_utc']} | {g['end_utc']} | {g['duration_s']} |")
    ap("")

    ap("## Motion")
    ap("")
    if m["status"] == "computed":
        ap(f"- Source signal: `{m['source_topic']}` ({m['source_schema']})")
        ap(f"- Detail: {m['detail']}")
        ap(f"- Samples: {m['sample_count']}")
        ap(f"- Distance traveled: {m['distance_m']} m")
        ap(f"- Mean speed: {m['mean_speed_mps']} m/s")
        ap(f"- Max speed: {m['max_speed_mps']} m/s")
        ap(f"- Hard-deceleration threshold: {m['hard_decel_threshold_mps2']} m/s^2")
        ap(f"- Hard-deceleration events: {m['hard_decel_event_count']}")
    else:
        ap("- Status: **not_present_in_source**")
        ap(f"- Reason: {m['reason']}")
        ap(f"- Topics considered: {', '.join(m['topics_considered']) or '(none)'}")
    ap("")

    ap("## Autonomy")
    ap("")
    if a["status"] == "computed":
        ap(f"- Autonomous time: {a['autonomous_time_s']} s")
        ap(f"- Manual time: {a['manual_time_s']} s")
        ap(f"- Interventions: {a['intervention_count']}")
        ap(f"- Disengagements: {a['disengagement_count']}")
    else:
        ap("- Status: **not_present_in_source**")
        ap(f"- Reason: {a['reason']}")
        ap(f"- Matched topics: {', '.join(a['matched_topics']) or '(none)'}")
    ap("")

    ap("## Draft incidents (Agent-Loss-Record-shaped stubs)")
    ap("")
    if not incidents:
        ap("No threshold-triggered incidents in this window.")
    else:
        for inc in incidents:
            ap(f"### `{inc['event_id']}` — {inc['failure_mode']}")
            ap("")
            ap(f"- Occurred at: {inc['occurred_at']}")
            ap(f"- Trigger: {inc['trigger']}")
            ap(f"- Detection method: {inc['detection_method']}")
            ap(f"- Severity band: {inc['severity']['band']} "
               f"(loss_confidence: {inc['severity']['loss_confidence']})")
            ap(f"- {inc['schema_notes']}")
            ap("")
    ap("")

    ap("## What this proves / does not prove")
    ap("")
    ap(f"**Proves:** {report['notes']['proves']}")
    ap("")
    ap(f"**Does not prove:** {report['notes']['does_not_prove']}")
    ap("")

    return "\n".join(lines) + "\n"
