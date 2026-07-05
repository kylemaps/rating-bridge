"""End-to-end smoke test: analyze -> sign -> verify -> tamper -> verify catches it."""

from __future__ import annotations

import json
from pathlib import Path

from rating_bridge.canonical import canonical_bytes
from rating_bridge.cli import main
from rating_bridge.report import build_report


def test_build_report_shape(synthetic_mcap: Path) -> None:
    report = build_report(
        source_path=synthetic_mcap,
        source_url=None,
        source_derivation="pytest fixture",
        reproduce_command="pytest",
    )
    assert report["session"]["message_count"] == 7
    assert len(report["session"]["topics"]) == 2
    assert report["continuity"]["gap_count"] == 1
    assert report["continuity"]["longest_gap_s"] >= 2.0


def test_end_to_end_sign_verify_and_tamper(synthetic_mcap: Path, tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    key_path = tmp_path / "key.pem"

    rc = main(
        [
            "analyze",
            str(synthetic_mcap),
            "--out-dir",
            str(report_dir),
            "--sign",
            "--key",
            str(key_path),
        ]
    )
    assert rc == 0
    assert (report_dir / "exposure_report.json").exists()
    assert (report_dir / "exposure_report.sig.json").exists()

    assert main(["verify", str(report_dir)]) == 0

    # Tamper a copy: flip one field, re-hash must no longer match the signed hash.
    report_path = report_dir / "exposure_report.json"
    report_obj = json.loads(report_path.read_text(encoding="utf-8"))
    report_obj["session"]["message_count"] += 1
    report_path.write_text(json.dumps(report_obj, indent=2, sort_keys=True), encoding="utf-8")

    assert main(["verify", str(report_dir)]) == 1


def test_canonical_bytes_is_stable_under_key_order() -> None:
    a = canonical_bytes({"b": 1, "a": 2})
    b = canonical_bytes({"a": 2, "b": 1})
    assert a == b
