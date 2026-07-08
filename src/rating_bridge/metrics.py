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

    # Per-interval deceleration, then COALESCE contiguous over-threshold
    # intervals into one maneuver. A single continuous brake sampled at 10 Hz
    # produces many consecutive over-threshold intervals; reporting each as its
    # own "event" would inflate the incident count by the sample rate. One
    # physical braking maneuver must count as one event, with its peak
    # deceleration and the speed it bled off across the whole maneuver.
    hard_decel_events = []
    run: list[tuple[int, int, float, float, float]] = []  # (t1, t2, v1, v2, accel)

    def _flush_run() -> None:
        if not run:
            return
        t_start = run[0][0]
        t_end = run[-1][1]
        v_before = run[0][2]
        v_after = run[-1][3]
        peak_accel = min(r[4] for r in run)  # most negative = hardest brake
        hard_decel_events.append(
            {
                "occurred_at_utc": _ns_to_iso(t_start),
                "end_utc": _ns_to_iso(t_end),
                "log_time_ns": t_start,
                "duration_s": round((t_end - t_start) / 1e9, 3),
                "peak_deceleration_mps2": round(peak_accel, 3),
                "speed_before_mps": round(v_before, 3),
                "speed_after_mps": round(v_after, 3),
                "sample_interval_count": len(run),
            }
        )
        run.clear()

    prev_t2 = None
    for (t1, v1), (t2, v2) in zip(speeds, speeds[1:]):
        dt_s = (t2 - t1) / 1e9
        if dt_s <= 0:
            continue
        accel = (v2 - v1) / dt_s
        if accel <= -HARD_DECEL_THRESHOLD_MPS2:
            # A break in time-contiguity (a skipped/absent interval) ends the run.
            if prev_t2 is not None and run and t1 != prev_t2:
                _flush_run()
            run.append((t1, t2, v1, v2, accel))
            prev_t2 = t2
        else:
            _flush_run()
            prev_t2 = None
    _flush_run()

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


# JSON payload fields that carry an autonomy state. Values are interpreted
# case-insensitively. Anything unrecognized leaves the sample's state "unknown"
# and is reported rather than guessed.
_AUTO_STRING_VALUES = ("autonomous", "auto", "engaged", "self_driving", "self-driving")
_MANUAL_STRING_VALUES = ("manual", "disengaged", "teleop", "operator")


def _classify_json_state(obj: dict) -> tuple[str | None, bool]:
    """Map one decoded JSON payload to (state, estop).

    state is "autonomous", "manual", or None (unrecognized). estop is True if
    an emergency-stop flag is asserted in the payload.
    """
    estop = bool(
        obj.get("estop") or obj.get("e_stop") or obj.get("emergency_stop")
    )
    state: str | None = None
    for key in ("mode", "state", "status", "engagement"):
        val = obj.get(key)
        if isinstance(val, str):
            low = val.strip().lower()
            if any(low == v or low.startswith(v) for v in _AUTO_STRING_VALUES):
                state = "autonomous"
            elif any(low == v or low.startswith(v) for v in _MANUAL_STRING_VALUES):
                state = "manual"
            break
    if state is None:
        for key in ("autonomous", "engaged", "auto"):
            if isinstance(obj.get(key), bool):
                state = "autonomous" if obj[key] else "manual"
                break
    return state, estop


def _iter_topic_payloads(path: Path, topic: str):
    """Yield (log_time_ns, payload_bytes) for one topic, undecoded."""
    from mcap.reader import make_reader

    with open(path, "rb") as f:
        reader = make_reader(f)
        for _schema, channel, message in reader.iter_messages(topics=[topic]):
            yield message.log_time, message.data


def autonomy_metrics(path: Path, topics: list[str]) -> dict:
    import json as _json

    matched = sorted(t for t in topics if any(kw in t.lower() for kw in AUTONOMY_KEYWORDS))
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

    # Decode the first matched topic whose payloads parse as JSON with a
    # recognizable state field. Time in each state is integrated between
    # consecutive samples (each sample's state holds until the next).
    for topic in matched:
        samples: list[tuple[int, str, bool]] = []
        undecodable = False
        for t_ns, payload in _iter_topic_payloads(path, topic):
            try:
                obj = _json.loads(payload)
            except (ValueError, TypeError):
                undecodable = True
                break
            if not isinstance(obj, dict):
                undecodable = True
                break
            state, estop = _classify_json_state(obj)
            samples.append((t_ns, state or "unknown", estop))
        if undecodable or len(samples) < 2 or all(s[1] == "unknown" for s in samples):
            continue

        samples.sort(key=lambda s: s[0])
        auto_s = manual_s = unknown_s = 0.0
        interventions = 0  # autonomous -> manual transitions (human took over)
        disengagements = 0  # autonomous -> (manual or estop) transitions
        estop_events = 0
        prev_estop = False
        for (t1, st1, es1), (t2, _st2, _es2) in zip(samples, samples[1:]):
            dt = (t2 - t1) / 1e9
            if dt < 0:
                continue
            if st1 == "autonomous":
                auto_s += dt
            elif st1 == "manual":
                manual_s += dt
            else:
                unknown_s += dt
        for (t1, st1, es1), (t2, st2, es2) in zip(samples, samples[1:]):
            if st1 == "autonomous" and st2 == "manual":
                interventions += 1
            if st1 == "autonomous" and (st2 == "manual" or es2):
                disengagements += 1
            if es2 and not es1:
                estop_events += 1
        # trailing-sample estop rising edge relative to prior
        if samples and samples[0][2]:
            estop_events += 1

        return {
            "status": "computed",
            "source_topic": topic,
            "decoder": "json-state-v1",
            "sample_count": len(samples),
            "autonomous_time_s": round(auto_s, 3),
            "manual_time_s": round(manual_s, 3),
            "unknown_state_time_s": round(unknown_s, 3),
            "intervention_count": interventions,
            "disengagement_count": disengagements,
            "estop_event_count": estop_events,
            "topics_scanned": topics,
            "matched_topics": matched,
        }

    # A matching topic name was found, but no matched topic carried a JSON
    # payload this version can decode. Report the match honestly.
    return {
        "status": NOT_PRESENT,
        "reason": (
            "Topic name(s) suggest an autonomy-mode/e-stop signal, but no matched topic "
            "carried a JSON payload with a recognizable state field (rating-bridge decodes "
            "JSON mode/estop payloads; proprietary binary autonomy messages are flagged for "
            "manual review rather than guessed at)."
        ),
        "topics_scanned": topics,
        "matched_topics": matched,
        "autonomous_time_s": NOT_PRESENT,
        "manual_time_s": NOT_PRESENT,
        "intervention_count": NOT_PRESENT,
        "disengagement_count": NOT_PRESENT,
    }
