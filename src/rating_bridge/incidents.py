"""Draft Agent-Loss-Record-shaped incident stubs.

Maps telemetry-detected anomalies (continuity gaps, hard-deceleration
events) onto the ALR v0.1 object shape
(agent-loss-record/schema/agent-loss-record-schema.md) so they slot into the
same pipeline as agent-failure records, even though a physical-robot
telemetry gap is not an OWASP-ASI "agent threat."

Two honest compromises, called out explicitly in every stub's
``schema_notes``:

1. ALR's ``threat_class`` / ``failure_mode`` taxonomy (ss4) is scoped to AI-agent
   failure modes (goal_hijack, tool_misuse, ...). There is no category for
   "sensor blackout" or "hard brake," so these stubs use a
   ``failure_mode`` value outside the published taxonomy
   (``telemetry_gap`` / ``hard_deceleration``) pending a physical-safety
   extension to the standard.
2. ALR's ``provenance.source_type`` enum (REAL_CLAIM / INCIDENT_REPORTED /
   PUBLIC_INCIDENT / REDTEAM_SYNTHETIC) has no value for "flagged
   automatically by a deterministic analysis tool, from a real log, with no
   human review yet." These stubs use ``INCIDENT_REPORTED`` as the closest
   fit and rely on ``loss_confidence: modeled`` to signal that severity is
   a placeholder, not an assessed loss.

Every field here is explicitly a DRAFT: severity bands are placeholders,
containment/detection_lag are "unknown" unless observable from the log
itself, and nothing is asserted as a real loss.
"""

from __future__ import annotations

from datetime import UTC, datetime

ALR_SCHEMA_VERSION = "ALR-0.1"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_incidents(
    source_filename: str,
    source_sha256: str,
    gaps: list[dict],
    hard_decel_events: list[dict],
) -> list[dict]:
    incidents: list[dict] = []

    for i, gap in enumerate(gaps):
        incidents.append(
            {
                "event_id": f"ev_gap_{i:04d}",
                "alr_schema_version": ALR_SCHEMA_VERSION,
                "occurred_at": gap["start_utc"],
                "threat_class": "n/a — physical-layer telemetry anomaly, not an OWASP-ASI category",
                "atlas_technique": None,
                "failure_mode": "telemetry_gap",
                "trigger": f"no telemetry on any topic for {gap['duration_s']}s",
                "trace_ref": {
                    "source_file": source_filename,
                    "source_sha256": source_sha256,
                    "window_start_utc": gap["start_utc"],
                    "window_end_utc": gap["end_utc"],
                },
                "control_state_at_failure": ["c.monitoring:unknown — not observable from log"],
                "detection_method": "automated: rating-bridge continuity analysis",
                "time_to_detect": "n/a (detected at post-hoc analysis time, not in real time)",
                "containment": "unknown — not observable from log",
                "severity": {
                    "band": "S0",
                    "reversibility": "unknown",
                    "blast_radius": "unknown",
                    "detection_lag": "undetected-until-external (no real-time monitor observed)",
                    "data_exposure": "none",
                    "regulatory_trigger": "none",
                    "loss_confidence": "modeled",
                },
                "dependency": {"correlation_tags": ["telemetry_gap", source_filename]},
                "provenance": {
                    "source_type": "INCIDENT_REPORTED",
                    "contributor_id": "rating-bridge-auto",
                    "schema_version": ALR_SCHEMA_VERSION,
                    "redaction_tier": "T1_FINGERPRINT",
                },
                "schema_notes": (
                    "DRAFT stub — not a full ALR record. severity.band is a placeholder "
                    "pending human/actuarial review; failure_mode is outside the published "
                    "ALR v0.1 taxonomy (see incidents.py docstring)."
                ),
                "generated_utc": _now_iso(),
            }
        )

    for i, ev in enumerate(hard_decel_events):
        incidents.append(
            {
                "event_id": f"ev_decel_{i:04d}",
                "alr_schema_version": ALR_SCHEMA_VERSION,
                "occurred_at": ev["occurred_at_utc"],
                "threat_class": "n/a — physical-layer telemetry anomaly, not an OWASP-ASI category",
                "atlas_technique": None,
                "failure_mode": "hard_deceleration",
                "trigger": (
                    f"peak deceleration {ev['peak_deceleration_mps2']} m/s^2 over "
                    f"{ev['duration_s']}s (speed {ev['speed_before_mps']} -> "
                    f"{ev['speed_after_mps']} m/s, {ev['sample_interval_count']} intervals)"
                ),
                "trace_ref": {
                    "source_file": source_filename,
                    "source_sha256": source_sha256,
                    "log_time_ns": ev["log_time_ns"],
                    "window_start_utc": ev["occurred_at_utc"],
                    "window_end_utc": ev["end_utc"],
                },
                "control_state_at_failure": ["c.rollback:unknown — not observable from log alone"],
                "detection_method": "automated: rating-bridge motion analysis",
                "time_to_detect": "n/a (detected at post-hoc analysis time, not in real time)",
                "containment": "unknown — not observable from log",
                "severity": {
                    "band": "S0",
                    "reversibility": "unknown",
                    "blast_radius": "single-record",
                    "detection_lag": "undetected-until-external (no real-time monitor observed)",
                    "data_exposure": "none",
                    "regulatory_trigger": "none",
                    "loss_confidence": "modeled",
                },
                "dependency": {"correlation_tags": ["hard_deceleration", source_filename]},
                "provenance": {
                    "source_type": "INCIDENT_REPORTED",
                    "contributor_id": "rating-bridge-auto",
                    "schema_version": ALR_SCHEMA_VERSION,
                    "redaction_tier": "T1_FINGERPRINT",
                },
                "schema_notes": (
                    "DRAFT stub — not a full ALR record. severity.band is a placeholder "
                    "pending human/actuarial review; failure_mode is outside the published "
                    "ALR v0.1 taxonomy (see incidents.py docstring)."
                ),
                "generated_utc": _now_iso(),
            }
        )

    return incidents
