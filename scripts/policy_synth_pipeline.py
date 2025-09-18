"""Policy synthesis pipeline wrapper that emits provenance attestations.

This module coordinates three phases:
1. (Optional) Execute a synthesis command to build/update a policy artifact.
2. Ensure the artifact exists and contains the provenance header required by provtools.
3. Invoke `provtools.cmd_build` to generate an attestation (DSSE envelope).

The module can be reused from other orchestrators by calling `run_pipeline`.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
from pathlib import Path
from typing import Optional

from scripts import provtools


class PipelineError(RuntimeError):
    """Raised when the policy synthesis pipeline fails."""


def run_pipeline(
    *,
    artifact: Path,
    private_key: Path,
    attestation: Path,
    key_id: str = "",
    base_dir: Path | None = None,
    synth_command: Optional[list[str]] = None,
    working_directory: Path | None = None,
    public_key: Path | None = None,
) -> dict[str, str]:
    """Run the policy synthesis pipeline and emit an attestation.

    Args:
        artifact: Path to the policy Markdown artifact including provenance header.
        private_key: Path to the Ed25519 private key used for DSSE signing.
        attestation: Output path for the generated DSSE envelope.
        key_id: Optional key identifier recorded in the DSSE signatures array.
        base_dir: Base directory for resolving digests (defaults to project root).
        synth_command: Optional command (list form) to run prior to attestation.
        working_directory: Optional working directory for the synthesis command.
    """

    base_dir = (base_dir or Path(".")).resolve()
    artifact_path = artifact if artifact.is_absolute() else (base_dir / artifact).resolve()
    private_key_path = private_key if private_key.is_absolute() else (base_dir / private_key).resolve()
    attestation_path = attestation if attestation.is_absolute() else (base_dir / attestation).resolve()

    if synth_command:
        result = subprocess.run(
            synth_command,
            cwd=str((working_directory or base_dir).resolve()),
            check=False,
        )
        if result.returncode != 0:
            raise PipelineError(
                f"Synthesis command failed with exit code {result.returncode}: {' '.join(synth_command)}"
            )

    if not artifact_path.exists():
        raise PipelineError(f"Artifact not found: {artifact_path}")

    namespace = argparse.Namespace(
        file=str(artifact_path),
        priv=str(private_key_path),
        out=str(attestation_path),
        base=str(base_dir),
        keyid=key_id,
    )

    status = provtools.cmd_build(namespace)
    if status != 0:
        raise PipelineError("provtools build failed; see logs above for details")

    return {
        "artifact": str(artifact_path),
        "attestation": str(attestation_path),
        "private_key": str(private_key_path),
        "base_dir": str(base_dir),
        "public_key": str(
            _derive_public_key_path(private_key_path, public_key, base_dir)
        ),
    }


def _derive_public_key_path(
    private_key_path: Path, override: Path | None, base_dir: Path
) -> Path:
    if override is not None:
        return (
            override
            if override.is_absolute()
            else (base_dir / override).resolve()
        )

    if private_key_path.suffix:
        return private_key_path.with_suffix(".pub")
    return (private_key_path.parent / f"{private_key_path.name}.pub").resolve()


def _verify_attestation(
    *, dsse_path: Path, public_key_path: Path, base_dir: Path
) -> dict[str, object]:
    namespace = argparse.Namespace(
        dsse=str(dsse_path),
        pub=str(public_key_path),
        base=str(base_dir),
    )
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        status = provtools.cmd_verify(namespace)
    raw_output = buffer.getvalue().strip()
    payload: dict[str, object]
    if raw_output:
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError:
            payload = {"raw": raw_output}
    else:
        payload = {}
    return {"status": status, "payload": payload}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path, help="Path to the policy artifact (Markdown)")
    parser.add_argument("private_key", type=Path, help="Path to the Ed25519 private key (PEM)")
    parser.add_argument("attestation", type=Path, help="Destination path for the DSSE envelope")
    parser.add_argument("--key-id", default="", help="Key identifier stored in the DSSE signature")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(".").resolve(),
        help="Base directory for digest calculation (defaults to project root)",
    )
    parser.add_argument(
        "--synth-cmd",
        nargs=argparse.REMAINDER,
        help="Optional command (and arguments) that generates the policy artifact before attestation",
    )
    parser.add_argument(
        "--synth-cwd",
        type=Path,
        help="Working directory for the synthesis command. Defaults to base dir when omitted.",
    )
    parser.add_argument(
        "--public-key",
        type=Path,
        help="Path to the Ed25519 public key. Defaults to private key path with .pub suffix.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip verification step after attestation is generated.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        run_result = run_pipeline(
            artifact=args.artifact,
            private_key=args.private_key,
            attestation=args.attestation,
            key_id=args.key_id,
            base_dir=args.base_dir,
            synth_command=args.synth_cmd or None,
            working_directory=args.synth_cwd,
            public_key=args.public_key,
        )
        verification = None
        if not args.skip_verify:
            verification = _verify_attestation(
                dsse_path=Path(run_result["attestation"]),
                public_key_path=Path(run_result["public_key"]),
                base_dir=Path(run_result["base_dir"]),
            )
    except PipelineError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    payload = {
        "ok": True,
        "artifact": str(args.artifact),
        "attestation": str(args.attestation),
    }
    if verification is not None:
        payload["verify"] = verification["payload"]
        payload["verify_exit_code"] = verification["status"]
        payload["ok"] = verification["status"] == 0
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 1


def cli() -> int:
    """Entry-point wrapper for setuptools console scripts."""

    return main()


if __name__ == "__main__":
    raise SystemExit(cli())
