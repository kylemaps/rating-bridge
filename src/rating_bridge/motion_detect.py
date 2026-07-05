"""Generic ego-motion signal detection over an MCAP file.

Rating Bridge does not assume any particular robot's topic naming. It scans
the channel table for schemas/topics that plausibly carry ego-vehicle pose
(nav_msgs/Odometry, geometry_msgs/PoseStamped or
PoseWithCovarianceStamped, sensor_msgs/NavSatFix) and, as a fallback, TF
transforms whose translation actually varies over the session (a real
odom->base_link style pose stream) as opposed to a static sensor-mount
extrinsic (e.g. base_link->radar, which never moves and is not a motion
signal).

If nothing usable is found, callers get an explicit "not found" result with
the list of topics that were considered and why each was rejected — the
report must say *why* motion is not_present_in_source, not just that it is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from mcap.reader import make_reader
from mcap_ros1.decoder import DecoderFactory

# A TF frame pair whose translation range is below this is treated as a
# static sensor-mount extrinsic, not an ego-motion signal.
TF_STATIC_RANGE_M = 0.5

_POSE_SCHEMA_KEYWORDS = ("Odometry", "PoseStamped", "PoseWithCovarianceStamped", "NavSatFix")


@dataclass
class PoseSample:
    t_ns: int
    x: float  # meters (or degrees longitude, for NavSatFix samples)
    y: float  # meters (or degrees latitude, for NavSatFix samples)
    is_geodetic: bool = False


@dataclass
class MotionSignal:
    found: bool
    topic: str | None = None
    schema_name: str | None = None
    detail: str = ""
    samples: list[PoseSample] = field(default_factory=list)
    topics_considered: list[str] = field(default_factory=list)


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def find_motion_signal(path: Path) -> MotionSignal:
    with open(path, "rb") as f:
        reader = make_reader(f, decoder_factories=[DecoderFactory()])
        summary = reader.get_summary()
        if summary is None:
            return MotionSignal(found=False, detail="MCAP file has no summary section to scan.")

        channel_by_topic = {}
        for channel in summary.channels.values():
            schema = summary.schemas.get(channel.schema_id)
            channel_by_topic[channel.topic] = schema.name if schema else "(schemaless)"

        considered = sorted(channel_by_topic)

        # 1) Direct pose/odom/gps schema match.
        pose_topic = None
        for topic, schema_name in channel_by_topic.items():
            if any(k.lower() in schema_name.lower() for k in _POSE_SCHEMA_KEYWORDS):
                pose_topic = (topic, schema_name)
                break

        if pose_topic is not None:
            topic, schema_name = pose_topic
            samples: list[PoseSample] = []
            for _schema, _channel, message, ros_msg in reader.iter_decoded_messages(
                topics=[topic]
            ):
                if "NavSatFix" in schema_name:
                    samples.append(
                        PoseSample(
                            message.log_time, ros_msg.longitude, ros_msg.latitude, is_geodetic=True
                        )
                    )
                elif "PoseWithCovarianceStamped" in schema_name:
                    p = ros_msg.pose.pose.position
                    samples.append(PoseSample(message.log_time, p.x, p.y))
                elif "PoseStamped" in schema_name:
                    p = ros_msg.pose.position
                    samples.append(PoseSample(message.log_time, p.x, p.y))
                elif "Odometry" in schema_name:
                    p = ros_msg.pose.pose.position
                    samples.append(PoseSample(message.log_time, p.x, p.y))
            return MotionSignal(
                found=True,
                topic=topic,
                schema_name=schema_name,
                detail=f"Direct pose/odometry topic '{topic}' ({schema_name}).",
                samples=samples,
                topics_considered=considered,
            )

    # 2) Fallback: scan /tf for a frame pair with real displacement.
    if "/tf" in channel_by_topic:
        pair_samples: dict[tuple[str, str], list[PoseSample]] = {}
        with open(path, "rb") as f:
            reader = make_reader(f, decoder_factories=[DecoderFactory()])
            for _schema, _channel, message, ros_msg in reader.iter_decoded_messages(
                topics=["/tf"]
            ):
                for t in ros_msg.transforms:
                    key = (t.header.frame_id, t.child_frame_id)
                    tr = t.transform.translation
                    pair_samples.setdefault(key, []).append(
                        PoseSample(message.log_time, tr.x, tr.y)
                    )

        best_pair, best_range = None, 0.0
        for key, samples in pair_samples.items():
            xs = [s.x for s in samples]
            ys = [s.y for s in samples]
            rng = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
            if rng > best_range:
                best_pair, best_range = key, rng

        if best_pair is not None and best_range >= TF_STATIC_RANGE_M:
            frame_id, child_frame_id = best_pair
            topic_label = f"/tf ({frame_id} -> {child_frame_id})"
            return MotionSignal(
                found=True,
                topic=topic_label,
                schema_name="tf2_msgs/TFMessage",
                detail=(
                    f"Derived from /tf transform '{frame_id}' -> '{child_frame_id}' "
                    f"(displacement range {best_range:.2f} m over the session)."
                ),
                samples=pair_samples[best_pair],
                topics_considered=considered,
            )
        elif best_pair is not None:
            frame_id, child_frame_id = best_pair
            considered.append(
                f"/tf ({frame_id} -> {child_frame_id}) rejected: displacement range "
                f"{best_range:.3f} m < {TF_STATIC_RANGE_M} m static-extrinsic threshold "
                "(this is a fixed sensor-mount transform, not an ego-motion signal)"
            )

    return MotionSignal(
        found=False,
        detail=(
            "No nav_msgs/Odometry, geometry_msgs/Pose*Stamped, sensor_msgs/NavSatFix, or "
            "moving /tf transform found in this file."
        ),
        topics_considered=considered,
    )
