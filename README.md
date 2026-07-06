# Rating Bridge

For underwriters and brokers who need to price autonomous-systems risk from telemetry they can actually trust.

Rating Bridge turns a robotics MCAP log into a **signed, re-runnable Exposure & Incident Report** that an insurance underwriter can rate against. It is the middle of a three-part pipeline: [veriseal](https://github.com/kylemaps/veriseal) seals the raw telemetry cryptographically at/near capture; Rating Bridge derives deterministic exposure metrics (session, continuity, motion, autonomy) and threshold-triggered draft incident stubs shaped to the **[Agent Loss Record](https://github.com/kylemaps/agent-loss-record) (ALR) v0.1** schema; the ALR corpus is where those records become comparable, priceable data points. Every number in the report traces back to the exact source-file bytes (SHA-256 in the provenance block), every threshold is documented in the report itself, and re-running the printed command on the same file reproduces the report byte-for-byte.

> Status: early v0.1, solo project. Analyze/sign/verify work end-to-end, but the report format will change. Adversarial feedback welcome: [open an issue](https://github.com/kylemaps/rating-bridge/issues).

![CI](https://github.com/kylemaps/rating-bridge/actions/workflows/ci.yml/badge.svg)

---

## Quickstart (Windows)

```bat
git clone https://github.com/kylemaps/rating-bridge.git
cd rating-bridge
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .

REM Get the public sample data (see Dataset below)
curl -L -o data\demo.bag https://assets.foxglove.dev/demo.bag
REM Convert ROS1 bag -> MCAP with the official mcap CLI
REM (download: https://github.com/foxglove/mcap/releases -> mcap-windows-amd64.exe)
mcap convert data\demo.bag data\demo.mcap

REM Analyze + sign in one step
.venv\Scripts\python.exe -m rating_bridge analyze data\demo.mcap --sign ^
    --source-url https://assets.foxglove.dev/demo.bag ^
    --source-derivation "mcap convert demo.bag demo.mcap (mcap-cli v0.2.0)"
```
```
Analyze complete
----------------
Source:        data\demo.mcap  (60,235,418 bytes)
Messages:      1606  across 7 topics
Duration:      7.780759 s
Continuity:    0 gap(s) > 1.0s
Motion:        not_present_in_source
Autonomy:      not_present_in_source
Incidents:     0 draft stub(s)
JSON report:   report\exposure_report.json
Markdown:      report\exposure_report.md

Sign complete
-------------
Report SHA-256: 153268d5e339a0f9...
Signature:      report\exposure_report.sig.json
Signing key:    keys\rating_bridge_signing_key.pem
```
```bat
REM Verify the signed report (exit 0 = INTACT, 1 = TAMPERED)
.venv\Scripts\python.exe -m rating_bridge verify report
```
```
INTACT: signature valid, report SHA-256 153268d5e339a0f9...
```

**See a real signed report without running anything:** [`examples/foxglove-demo/`](examples/foxglove-demo/)
is a checked-in output from this exact quickstart. `exposure_report.md` is the human-readable
version; `exposure_report.sig.json` is the signature you can verify against it.

Outputs land in `report\`:

| File | What it is |
|---|---|
| `exposure_report.json` | The full machine-readable report (pretty-printed) |
| `exposure_report.md` | Ledger-style human-readable version for a non-engineer |
| `exposure_report.sig.json` | `{report_sha256, signature, public_key, signed_at, tool_version}`: Ed25519 over the SHA-256 of the canonical JSON encoding |

---

## Dataset

The demo uses Foxglove's public sample ROS 1 bag:

- **URL:** <https://assets.foxglove.dev/demo.bag> (Foxglove public assets bucket; ~70 MB)
- **Content:** ~7.8 s urban driving snippet (2017-03-22), 1,606 messages over 7 topics: compressed camera images, Velodyne lidar, radar points/range/tracks, TF, diagnostics.
- **Conversion:** ROS 1 `.bag` to `.mcap` via the official [`mcap` CLI](https://github.com/foxglove/mcap/releases) (`mcap convert`). The conversion command is recorded in the report's provenance block.
- The `data\` directory is gitignored; the report's `source_sha256` pins the exact bytes analyzed.

---

## How it works

Analyze reads the MCAP file once and computes six things, each independently documented in the report:

- **Session**: start/end (UTC), duration, message count, per-topic inventory with counts, mean rates, byte volumes.
- **Continuity**: telemetry gaps over 1 s across the combined stream (count, longest, every gap listed). Blind spots are what an underwriter can't rate around.
- **Motion**: if a pose/odometry/GPS-like signal exists, distance, mean/max speed, and hard-deceleration events (3 m/s² or more, about 0.3 g, documented in the report). The detector accepts a *moving* `/tf` transform but rejects static sensor-mount extrinsics.
- **Autonomy**: autonomous vs manual time and intervention counts, if a mode/engagement/e-stop topic exists; otherwise the fields are emitted as `not_present_in_source` with the reason.
- **Incidents**: every detected gap or hard-decel event as a DRAFT Agent-Loss-Record-shaped stub (`loss_confidence: modeled`, severity band placeholder, deviations from the ALR taxonomy called out inline).
- **Provenance**: source SHA-256/size/URL/derivation, tool version, thresholds, and the exact command to reproduce the report.

Metrics the source cannot support are emitted as the literal `"not_present_in_source"` with a stated reason: never fabricated.

Signing canonicalizes the JSON (sorted keys, compact separators, UTF-8, `\n` line ending, floats pre-rounded at metric computation time), hashes with SHA-256, and signs the digest with Ed25519: the same primitives and JSON conventions as veriseal's manifest spec, so the two tools verify the same way.

---

## Architecture

```
raw robotics telemetry (.bag / .mcap)
        |
        v
  veriseal            seal the raw bytes near capture (upstream, separate tool)
        |
        v
  rating_bridge analyze
        |-- session & continuity metrics
        |-- motion metrics (if pose/odometry/GPS present)
        |-- autonomy metrics (if mode/engagement topic present)
        `-- draft incident stubs (ALR-shaped, loss_confidence: modeled)
        |
        v
  exposure_report.json / .md      canonical JSON, SHA-256 hashed
        |
        v
  rating_bridge sign               Ed25519 signature over the hash
        |
        v
  rating_bridge verify              anyone can recompute the hash and
                                     check the signature independently
```

---

## What it does NOT prove

- **Integrity and derivation, not veracity.** The signature proves this report derives deterministically from the hashed source bytes. It proves nothing about whether the log truthfully recorded reality: sensors can be miscalibrated, logs can be edited *before* they reach this tool. Pair with a veriseal seal made at/near capture for the upstream half.
- **The demo signing key is a local PEM file**, generated on first use. It is not an HSM and is not tied to any identity. A verifier who doesn't independently pin the public key learns only that *someone* signed it.
- **Draft incidents are threshold triggers, not adjudicated losses.** A hard brake at 3 m/s² may be good defensive driving. Severity bands are placeholders (`S0`, `modeled`) pending human review.
- **Motion from planar pose deltas** (or TF translation) ignores Z, orientation, and covariance; GPS-derived speed inherits GPS noise. Speeds are step-differenced, not filtered.
- **Autonomy detection is name-based** in v0.1: it flags plausible topics but does not decode proprietary mode messages; it says so in the report rather than guessing.
- The demo dataset (7.8 s of driving with no pose/odometry topic) exercises the `not_present_in_source` paths for motion-from-odometry and autonomy. That is the honest behavior being demonstrated.

---

## Status / Roadmap

v0.1, solo-maintained. Built: analyze, sign, and verify, end-to-end, against a real public dataset, with a checked-in signed example. Not stable yet: the report schema itself, which will change as more datasets exercise the motion and autonomy paths.

Rating Bridge is one of a family of standalone tools (veriseal, agent-loss-record, trace-bridge, coverholder-passport); each stands on its own.

---

## License

Apache-2.0 © Kyle Mapue
