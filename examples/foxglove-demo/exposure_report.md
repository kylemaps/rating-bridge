# Exposure & Incident Report — `demo.mcap`

Generated 2026-07-05T05:17:04Z by Rating Bridge v0.1.0

## Headline

- **Session duration:** 7.780759s  (1606 messages, 7 topics)
- **Continuity gaps (> 1.0s):** 0
- **Motion (distance / speed / hard-braking):** *not present in source* — No nav_msgs/Odometry, geometry_msgs/Pose*Stamped, sensor_msgs/NavSatFix, or moving /tf transform found in this file.
- **Autonomy engagement:** *not present in source* — No topic name matched an autonomy-engagement pattern (mode, engage, estop, e_stop, e-stop, autonomy, manual, disengag, override, safety_driver).
- **Draft incidents flagged:** 0

## Provenance

- Source file: `demo.mcap`
- SHA-256: `9a72d4151b7d042ae3fa1a4975faa02eac021c2fa937b59a158946083f3a6303`
- Size: 60,235,418 bytes
- Source URL: https://assets.foxglove.dev/demo.bag
- Derivation: mcap convert demo.bag demo.mcap (mcap-cli v0.2.0)
- Reproduce with: `python -m rating_bridge analyze data/demo.mcap --sign`

## Session

- Start (UTC): 2017-03-22T02:26:20.103843Z
- End (UTC): 2017-03-22T02:26:27.884602Z
- Duration: 7.780759 s
- Message count: 1606

| Topic | Schema | Count | Mean rate (Hz) | Bytes |
|---|---|---:|---:|---:|
| `/diagnostics` | diagnostic_msgs/DiagnosticArray | 52 | 6.6832 | 33,872 |
| `/image_color/compressed` | sensor_msgs/CompressedImage | 234 | 30.0742 | 24,733,835 |
| `/radar/points` | sensor_msgs/PointCloud2 | 156 | 20.0495 | 47,844 |
| `/radar/range` | sensor_msgs/Range | 156 | 20.0495 | 5,928 |
| `/radar/tracks` | radar_driver/RadarTracks | 156 | 20.0495 | 119,150 |
| `/tf` | tf2_msgs/TFMessage | 774 | 99.4762 | 72,756 |
| `/velodyne_points` | sensor_msgs/PointCloud2 | 78 | 10.0247 | 99,804,906 |

## Continuity

- Gap threshold: 1.0 s
- Gaps detected: 0
- Longest gap: 0.0 s
- Max observed inter-message interval (any gap, not just qualifying ones): 0.022056 s

## Motion

- Status: **not_present_in_source**
- Reason: No nav_msgs/Odometry, geometry_msgs/Pose*Stamped, sensor_msgs/NavSatFix, or moving /tf transform found in this file.
- Topics considered: /diagnostics, /image_color/compressed, /radar/points, /radar/range, /radar/tracks, /tf, /velodyne_points

## Autonomy

- Status: **not_present_in_source**
- Reason: No topic name matched an autonomy-engagement pattern (mode, engage, estop, e_stop, e-stop, autonomy, manual, disengag, override, safety_driver).
- Matched topics: (none)

## Draft incidents (Agent-Loss-Record-shaped stubs)

No threshold-triggered incidents in this window.

## What this proves / does not prove

**Proves:** Integrity and derivation: this report was computed deterministically from the exact source file bytes hashed in provenance.source_sha256, using the documented rules and thresholds above. Re-running the command in provenance.command_to_reproduce against the same file byte-for-byte reproduces this report exactly.

**Does not prove:** Veracity at capture. Nothing here proves the source log is a truthful record of physical reality, that sensors were calibrated, or that no out-of-band editing occurred before this file reached this tool. Pair with a veriseal seal made at/near capture time for that guarantee. Incident entries are DRAFT, threshold-triggered stubs — not adjudicated losses.

