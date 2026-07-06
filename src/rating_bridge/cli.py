"""Rating Bridge CLI: analyze / sign / verify.

    python -m rating_bridge analyze data\\demo.mcap [--sign] [--out-dir report]
    python -m rating_bridge sign [--report-dir report] [--key keys\\rating_bridge_signing_key.pem]
    python -m rating_bridge verify report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import rating_bridge
from rating_bridge.canonical import canonical_bytes
from rating_bridge.report import build_report, render_markdown
from rating_bridge.signing import (
    generate_key,
    load_private_pem,
    public_pem,
    save_private_pem,
)
from rating_bridge.signing import sign as ed25519_sign
from rating_bridge.signing import verify as ed25519_verify

DEFAULT_KEY_PATH = Path("keys") / "rating_bridge_signing_key.pem"

_ANSI = {"green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m", "cyan": "\033[36m", "dim": "\033[2m"}
_RESET = "\033[0m"


def _color_enabled() -> bool:
    if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb":
        return False
    return sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"{_ANSI[code]}{text}{_RESET}" if _color_enabled() else text


def _truncate(hex_id: str) -> str:
    return f"{hex_id[:16]}..."


def _print_header(title: str) -> None:
    bar = "-" * len(title)
    print(f"\n{title}\n{bar}")


def _do_analyze(args: argparse.Namespace) -> int:
    source_path = Path(args.mcap_file)
    if not source_path.exists():
        print(_c(f"ERROR: source file not found: {source_path}", "red"), file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    reproduce_command = f"python -m rating_bridge analyze {source_path.as_posix()}" + (
        " --sign" if args.sign else ""
    )

    report = build_report(
        source_path=source_path,
        source_url=args.source_url,
        source_derivation=args.source_derivation,
        reproduce_command=reproduce_command,
    )

    report_json_path = out_dir / "exposure_report.json"
    report_md_path = out_dir / "exposure_report.md"

    # exposure_report.json is written pretty-printed for human readability;
    # `sign` recomputes the *canonical* encoding independently at sign time,
    # so pretty-printing here has no bearing on what gets hashed/signed.
    report_json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report_md_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")

    source_size = f"{report['provenance']['source_size_bytes']:,}"

    _print_header("Analyze complete")
    print(f"Source:        {_c(str(source_path), 'cyan')}  "
          f"({_c(source_size, 'cyan')} bytes)")
    print(f"Messages:      {_c(str(report['session']['message_count']), 'cyan')}  "
          f"across {_c(str(len(report['session']['topics'])), 'cyan')} topics")
    print(f"Duration:      {_c(str(report['session']['duration_s']), 'cyan')} s")
    print(f"Continuity:    {_c(str(report['continuity']['gap_count']), 'cyan')} gap(s) "
          f"> {report['continuity']['gap_threshold_s']}s")
    print(f"Motion:        {_c(report['motion']['status'], 'cyan')}")
    print(f"Autonomy:      {_c(report['autonomy']['status'], 'cyan')}")
    print(f"Incidents:     {_c(str(len(report['incidents'])), 'cyan')} draft stub(s)")
    print(f"JSON report:   {report_json_path}")
    print(f"Markdown:      {report_md_path}")

    if args.sign:
        return _sign(out_dir, Path(args.key) if args.key else DEFAULT_KEY_PATH)
    return 0


def _sign(out_dir: Path, key_path: Path) -> int:
    report_json_path = out_dir / "exposure_report.json"
    sig_path = out_dir / "exposure_report.sig.json"

    if not report_json_path.exists():
        print(_c(f"ERROR: {report_json_path} not found. Run `analyze` first.", "red"), file=sys.stderr)
        return 2

    if key_path.exists():
        key = load_private_pem(key_path)
    else:
        key = generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        save_private_pem(key, key_path)
        print(_c(
            f"WARNING: generated new signing key -> {key_path}\n"
            "         This is a local demo key, not an HSM-backed production key. "
            "Keep it safe and secret.",
            "yellow",
        ))

    report_obj = json.loads(report_json_path.read_bytes())
    canon = canonical_bytes(report_obj)
    report_sha256 = hashlib.sha256(canon).hexdigest()
    signature = ed25519_sign(key, bytes.fromhex(report_sha256))

    sig_doc = {
        "report_sha256": report_sha256,
        "signature": signature.hex(),
        "public_key": public_pem(key),
        "signed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool_version": rating_bridge.__version__,
    }
    sig_path.write_text(
        json.dumps(sig_doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    _print_header("Sign complete")
    print(f"Report SHA-256: {_c(_truncate(report_sha256), 'cyan')}")
    print(f"Signature:      {sig_path}")
    print(f"Signing key:    {key_path}")
    return 0


def _do_sign(args: argparse.Namespace) -> int:
    return _sign(Path(args.report_dir), Path(args.key) if args.key else DEFAULT_KEY_PATH)


def _do_verify(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir)
    report_json_path = report_dir / "exposure_report.json"
    sig_path = report_dir / "exposure_report.sig.json"

    if not report_json_path.exists() or not sig_path.exists():
        print(
            _c(f"ERROR: expected both {report_json_path} and {sig_path} to exist.", "red"),
            file=sys.stderr,
        )
        return 2

    try:
        report_obj = json.loads(report_json_path.read_bytes())
    except json.JSONDecodeError as exc:
        print(_c("TAMPERED: exposure_report.json is not valid JSON", "red"))
        print(f"  {exc}")
        return 1

    try:
        sig_doc = json.loads(sig_path.read_bytes())
    except json.JSONDecodeError as exc:
        print(_c(f"ERROR: exposure_report.sig.json is not valid JSON: {exc}", "red"), file=sys.stderr)
        return 2

    recomputed_sha256 = hashlib.sha256(canonical_bytes(report_obj)).hexdigest()
    hash_ok = recomputed_sha256 == sig_doc.get("report_sha256")

    sig_ok = False
    if hash_ok:
        try:
            sig_ok = ed25519_verify(
                sig_doc["public_key"],
                bytes.fromhex(sig_doc["report_sha256"]),
                bytes.fromhex(sig_doc["signature"]),
            )
        except Exception:
            sig_ok = False

    if hash_ok and sig_ok:
        print(_c(f"INTACT: signature valid, report SHA-256 {_truncate(recomputed_sha256)}", "green"))
        return 0

    if not hash_ok:
        print(_c("TAMPERED: report hash does not match the signed hash", "red"))
        print(f"  expected    {_truncate(sig_doc.get('report_sha256', '?'))}")
        print(f"  recomputed  {_truncate(recomputed_sha256)}")
    else:
        print(_c("TAMPERED: signature invalid for the recomputed hash", "red"))
        print("  report content changed after signing, or signature/key do not match")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rating_bridge",
        description="MCAP -> signed, re-runnable Exposure & Incident Report.",
    )
    parser.add_argument(
        "--version", action="version", version=f"rating-bridge {rating_bridge.__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="Analyze an MCAP file and write a report.")
    p_analyze.add_argument("mcap_file", help="Path to the .mcap file to analyze.")
    p_analyze.add_argument("--out-dir", default="report", help="Output directory (default: report).")
    p_analyze.add_argument("--sign", action="store_true", help="Sign the report after writing it.")
    p_analyze.add_argument("--key", default=None, help="Ed25519 private key PEM (used with --sign).")
    p_analyze.add_argument("--source-url", default=None, help="Public source URL (for provenance).")
    p_analyze.add_argument(
        "--source-derivation", default=None, help="How the source .mcap was produced (for provenance)."
    )
    p_analyze.set_defaults(func=_do_analyze)

    p_sign = sub.add_parser("sign", help="Sign an existing exposure_report.json.")
    p_sign.add_argument("--report-dir", default="report", help="Directory with exposure_report.json.")
    p_sign.add_argument("--key", default=None, help="Path to Ed25519 private key PEM.")
    p_sign.set_defaults(func=_do_sign)

    p_verify = sub.add_parser("verify", help="Verify a report dir. Exit 0=INTACT, 1=TAMPERED, 2=usage error.")
    p_verify.add_argument("report_dir", help="Directory with exposure_report.json + exposure_report.sig.json.")
    p_verify.set_defaults(func=_do_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
