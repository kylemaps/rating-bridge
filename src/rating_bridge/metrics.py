"""Deterministic metric computation over an MCAP file.

Every threshold used here is a module-level constant, documented, and echoed
back into the report's provenance block — an underwriter (or a skeptical
engineer) should never have to guess what "a gap" or "hard braking" meant
for a given report.

Nothing in this module invents a number the source data does not support.
Where a metric cannot be computed, the corresponding field is the literal
string ``"not_present_in_source"``, plus a human-readable reason.
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

from rating_bridge.mcap_io import iter_raw_messages
from rating_bridge.motion_detect import MotionSignal, find_motion_signal

NOT_PRESENT = "not_present_in_source"

# A gap in the combined (all-topics) telemetry stream longer than this is a
# reportable continuity blind spot.
GAP_THRESHOLD_S = 1.0

# Deceleration at or beyond this magnitude counts as a "hard braking" event.
# ~0.3g — a common fleet-telematics hard-braking threshold.
HARD_DECEL_THRESHOLD_MPS2 = 3.0

# Topic-name substrings that plausibly indicate an autonomy engagement /
# mode / e-stop signal. Case-insensitive.
AUTONOMY_KEYWORDS = (
    "mode",
    "engage",
    "estop",
    "e_stop",
    "e-stop",
    "autonomy",
    "manual",
    "disengag",
    "override",
    "safety_driver",
)


def _ns_to_iso(ns: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ns / 1e9, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def session_and_continuity_metrics(path: Path) -> tuple[dict, dict]:
    """Single pass over every message: session inventory + continuity gaps."""
    per_topic_count: dict[str, int] = defaultdict(int)
    per_topic_schema: dict[str, str] = {}
    per_topic_bytes: dict[str, int] = defaultdict(int)
    all_times: list[int] = []

    for rm in iter_raw_messages(path):
        per_topic_count[rm.topic] += 1
        per_topic_schema[rm.topic] = rm.schema_name
        per_topic_bytes[rm.topic] += rm.payload_len
        all_times.append(rm.log_time_ns)

    message_count = len(all_times)
    if message_count == 0:
        session = {
            "start_utc": NOT_PRESENT,
            "end_utc": NOT_PRESENT,
            "duration_s": 0.0,
            "message_count": 0,
            "topics": [],
        }
        continuity = {
            "gap_threshold_s": GAP_THRESHOLD_S,
            "gap_count": 0,
            "longest_gap_s": 0.0,
            "max_observed_interval_s": 0.0,
            "gaps": [],
        }
        return session, continuity

    all_times.sort()
    t_min, t_max = all_times[0], all_times[-1]
    duration_s = round((t_max - t_min) / 1e9, 6)

    topics = []
    for topic in sorted(per_topic_count):
        count = per_topic_count[topic]
        rate_hz = round(count / duration_s, 4) if duration_s > 0 else NOT_PRESENT
        topics.append(
            {
                "topic": topic,
                "schema": per_topic_schema[topic],
                "count": count,
                "bytes": per_topic_bytes[topic],
                "mean_rate_hz": rate_hz,
            }
        )

    session = {
        "start_utc": _ns_to_iso(t_min),
        "end_utc": _ns_to_iso(t_max),
        "duration_s": duration_s,
        "message_count": message_count,
        "topics": topics,
    }

    gaps = []
    max_interval_s = 0.0
    for prev, cur in zip(all_times, all_times[1:]):
        interval_s = (cur - prev) / 1e9
        max_interval_s = max(max_interval_s, interval_s)
        if interval_s > GAP_THRESHOLD_S:
            gaps.append(
                {
                    "start_utc": _ns_to_iso(prev),
                    "end_utc": _ns_to_iso(cur),
                    "duration_s": round(interval_s, 6),
                }
            )

    continuity = {
        "gap_threshold_s": GAP_THRESHOLD_S,
        "gap_count": len(gaps),
        "longest_gap_s": round(max((g["duration_s"] for g in gaps), default=0.0), 6),
        "max_observed_interval_s": round(max_interval_s, 6),
        "gaps": gaps,
    }
    return session, continuity


def motion_metrics(path: Path) -> tuple[dict, list[dict]]:
    """Returns (motion_dict, hard_decel_events)."""
    signal: MotionSignal = find_motion_signal(path)

    if not signal.found or len(signal.samples) < 2:
        reason = signal.detail
        if signal.found and len(signal.samples) < 2:
            reason = f"Motion topic '{signal.topic}' found but has fewer than 2 samples."
        return (
            {
                "status": NOT_PRESENT,
                "reason": reason,
                "topics_considered": signal.topics_considered,
                "distance_m": NOT_PRESENT,
                "mean_speed_mps": NOT_PRESENT,
                "max_speed_mps": NOT_PRESENT,
                "hard_decel_event_count": NOT_PRESENT,
                "hard_decel_threshold_mps2": HARD_DECEL_THRESHOLD_MPS2,
            },
            [],
        )

    samples = sorted(signal.samples, key=lambda s: s.t_ns)
    is_geodetic = samples[0].is_geodetic

    total_distance = 0.0
    speeds: list[tuple[int, float]] = []  # (t_ns of interval midpoint-ish, speed)
    for prev, cur in zip(samples, samples[1:]):
        dt_s = (cur.t_ns - prev.t_ns) / 1e9
        if dt_s <= 0:
            continue
        if is_geodetic:
            from rating_bridge.motion_detect import _haversine_m

            step_m = _haversine_m(prev.y, prev.x, cur.y, cur.x)
        else:
            step_m = math.hypot(cur.x - prev.x, cur.y - prev.y)
        total_distance += step_m
        speeds.append((cur.t_ns, step_m / dt_s))

    duration_s = (samples[-1].t_ns - samples[0].t_ns) / 1e9
    mean_speed = total_distance / duration_s if duration_s > 0 else 0.0
    max_speed = max((s for _, s in speeds), default=0.0)

    hard_decel_events = []
    for (t1, v1), (t2, v2) in zip(speeds, speeds[1:]):
        dt_s = (t2 - t1) / 1e9
        if dt_s <= 0:
            continue
        accel = (v2 - v1) / dt_s
        if accel <= -HARD_DECEL_THRESHOLD_MPS2:
            hard_decel_events.append(
                {
                    "occurred_at_utc": _ns_to_iso(t2),
                    "log_time_ns": t2,
                    "deceleration_mps2": round(accel, 3),
                    "speed_before_mps": round(v1, 3),
                    "speed_after_mps": round(v2, 3),
                }
            )

    motion = {
        "status": "computed",
        "source_topic": signal.topic,
        "source_schema": signal.schema_name,
        "detail": signal.detail,
        "sample_count": len(samples),
        "distance_m": round(total_distance, 3),
        "mean_speed_mps": round(mean_speed, 3),
        "max_speed_mps": round(max_speed, 3),
        "hard_decel_event_count": len(hard_decel_events),
        "hard_decel_threshold_mps2": HARD_DECEL_THRESHOLD_MPS2,
    }
    return motion, hard_decel_events


def autonomy_metrics(topics: list[str]) -> dict:
    matched = sorted(
        t for t in topics if any(kw in t.lower() for kw in AUTONOMY_KEYWORDS)
    )
    if not matched:
        return {
            "status": NOT_PRESENT,
            "reason": (
                "No topic name matched an autonomy-engagement pattern "
                f"({', '.join(AUTONOMY_KEYWORDS)})."
            ),
            "topics_scanned": topics,
            "matched_topics": [],
            "autonomous_time_s": NOT_PRESENT,
            "manual_time_s": NOT_PRESENT,
            "intervention_count": NOT_PRESENT,
            "disengagement_count": NOT_PRESENT,
        }
    # A matching topic name was found, but this version does not carry a
    # schema-specific decoder for arbitrary autonomy-mode message types.
    # Report the match honestly rather than guess at a decode.
    return {
        "status": NOT_PRESENT,
        "reason": (
            "Topic name(s) suggest an autonomy-mode/e-stop signal, but rating-bridge v0.1 "
            "has no schema-specific decoder for it yet — flagged for manual review rather "
            "than guessed at."
        ),
        "topics_scanned": topics,
        "matched_topics": matched,
        "autonomous_time_s": NOT_PRESENT,
        "manual_time_s": NOT_PRESENT,
        "intervention_count": NOT_PRESENT,
        "disengagement_count": NOT_PRESENT,
    }
