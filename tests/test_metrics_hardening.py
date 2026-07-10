"""Tests for two hardening fixes:

1. Hard-deceleration coalescing: one continuous brake sampled at N Hz counts as
   ONE maneuver, not N per-interval events.
2. Autonomy JSON decode: a mode/estop JSON topic yields computed autonomous /
   manual time and intervention counts, not not_present_in_source.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from mcap.writer import Writer

from rating_bridge.metrics import _classify_json_state, autonomy_metrics, motion_metrics

_POSE_DEF = """std_msgs/Header header
geometry_msgs/Pose pose
================================================================================
MSG: std_msgs/Header
uint32 seq
time stamp
string frame_id
================================================================================
MSG: geometry_msgs/Pose
geometry_msgs/Point position
geometry_msgs/Quaternion orientation
================================================================================
MSG: geometry_msgs/Point
float64 x
float64 y
float64 z
================================================================================
MSG: geometry_msgs/Quaternion
float64 x
float64 y
float64 z
float64 w
"""

BASE_NS = 1_782_864_000_000_000_000
STEP_NS = 100_000_000  # 10 Hz


def _pose(seq: int, t_ns: int, x: float) -> bytes:
    secs, nsecs = divmod(t_ns, 1_000_000_000)
    frame = b"map"
    return (
        struct.pack("<3I", seq, secs, nsecs)
        + struct.pack("<I", len(frame))
        + frame
        + struct.pack("<7d", x, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    )


@pytest.fixture
def braking_mcap(tmp_path: Path) -> Path:
    """A rover cruising at 4 m/s then braking to 0.4 m/s over 1 s (one maneuver),
    plus a JSON /autonomy/mode heartbeat that goes AUTONOMOUS then MANUAL once."""
    path = tmp_path / "braking.mcap"
    with open(path, "wb") as f:
        w = Writer(f)
        w.start()
        pose_schema = w.register_schema(name="geometry_msgs/PoseStamped", encoding="ros1msg", data=_POSE_DEF.encode())
        json_schema = w.register_schema(name="json_payload", encoding="jsonschema", data=b'{"type":"object"}')
        ch_pose = w.register_channel(topic="/pose", message_encoding="ros1", schema_id=pose_schema)
        ch_mode = w.register_channel(topic="/autonomy/mode", message_encoding="json", schema_id=json_schema)

        x = 0.0
        for i in range(120):  # 12 s at 10 Hz
            t = BASE_NS + i * STEP_NS
            t_s = i * 0.1
            if t_s < 8.0:
                speed = 4.0
            elif t_s < 9.0:
                speed = 4.0 - 3.6 * (t_s - 8.0)  # ~-3.6 m/s^2 for 1 s
            else:
                speed = 0.4
            x += speed * 0.1
            w.add_message(channel_id=ch_pose, log_time=t, data=_pose(i, t, round(x, 4)), publish_time=t)
            if i % 10 == 0:
                # switch to MANUAL once, at t=10s, to exercise an intervention
                mode = "MANUAL" if t_s >= 10.0 else "AUTONOMOUS"
                w.add_message(
                    channel_id=ch_mode, log_time=t,
                    data=json.dumps({"mode": mode, "estop": False}).encode(), publish_time=t,
                )
        w.finish()
    return path


def _mcap_from_speeds(path: Path, speeds: list[float]) -> Path:
    """Build a pose-only MCAP whose ego speed follows `speeds` (m/s per 0.1 s step)."""
    from mcap.writer import Writer

    with open(path, "wb") as f:
        w = Writer(f)
        w.start()
        ps = w.register_schema(name="geometry_msgs/PoseStamped", encoding="ros1msg", data=_POSE_DEF.encode())
        cp = w.register_channel(topic="/pose", message_encoding="ros1", schema_id=ps)
        x = 0.0
        for i, spd in enumerate(speeds):
            t = BASE_NS + i * STEP_NS
            x += spd * 0.1
            w.add_message(channel_id=cp, log_time=t, data=_pose(i, t, round(x, 4)), publish_time=t)
        w.finish()
    return path


def test_two_distinct_brakes_stay_separate(tmp_path: Path) -> None:
    # Two hard brakes (each -6 m/s^2) separated by steady cruising must be TWO events.
    speeds = ([4.0] * 20 + [4.0 - 0.6 * k for k in range(1, 6)] + [1.0] * 20
              + [3.0] + [3.0 - 0.6 * k for k in range(1, 5)] + [0.6] * 10)
    _, events = motion_metrics(_mcap_from_speeds(tmp_path / "two.mcap", speeds))
    assert len(events) == 2, f"distinct maneuvers merged: {len(events)}"


def test_subthreshold_jitter_makes_no_events(tmp_path: Path) -> None:
    # Sensor noise oscillating below the threshold must NOT manufacture hard-brake events.
    speeds = [3.0 + (0.05 if i % 2 else -0.05) for i in range(60)]
    _, events = motion_metrics(_mcap_from_speeds(tmp_path / "jitter.mcap", speeds))
    assert events == [], f"phantom events from jitter: {len(events)}"


def test_hard_decel_coalesces_to_one_event(braking_mcap: Path) -> None:
    motion, events = motion_metrics(braking_mcap)
    assert motion["status"] == "computed"
    assert len(events) == 1, f"expected 1 coalesced maneuver, got {len(events)}"
    ev = events[0]
    assert ev["peak_deceleration_mps2"] <= -3.0
    assert ev["speed_before_mps"] > ev["speed_after_mps"]
    assert ev["sample_interval_count"] > 1  # it really was many intervals, coalesced
    assert ev["duration_s"] > 0


def test_autonomy_json_decode(braking_mcap: Path) -> None:
    auto = autonomy_metrics(braking_mcap, ["/pose", "/autonomy/mode"])
    assert auto["status"] == "computed"
    assert auto["autonomous_time_s"] > 0
    assert auto["manual_time_s"] >= 0
    assert auto["intervention_count"] >= 1  # one AUTONOMOUS -> MANUAL transition


def test_classify_json_state() -> None:
    assert _classify_json_state({"mode": "AUTONOMOUS"}) == ("autonomous", False)
    assert _classify_json_state({"mode": "manual"}) == ("manual", False)
    assert _classify_json_state({"engaged": True})[0] == "autonomous"
    assert _classify_json_state({"estop": True})[1] is True
    assert _classify_json_state({"unrelated": 1})[0] is None


def test_autonomy_falls_back_when_no_json(tmp_path: Path) -> None:
    # A matched topic name but a non-JSON payload -> honest not_present_in_source.
    path = tmp_path / "binmode.mcap"
    with open(path, "wb") as f:
        w = Writer(f)
        w.start()
        ch = w.register_channel(topic="/vehicle/mode", message_encoding="cdr", schema_id=0)
        for i in range(5):
            t = BASE_NS + i * STEP_NS
            w.add_message(channel_id=ch, log_time=t, data=b"\x01\x02\x03\x04", publish_time=t)
        w.finish()
    auto = autonomy_metrics(path, ["/vehicle/mode"])
    assert auto["status"] == "not_present_in_source"
    assert auto["matched_topics"] == ["/vehicle/mode"]
