
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import policy_synth_pipeline, provtools

HEADER = """<!--
provenance:
  _type: "https://in-toto.io/Statement/v0.1"
  subject:
    - name: "policy.md"
      digest: {}
  predicateType: "https://accord.ai/schemas/policy@v1"
  predicate:
    produced_by:
      agent_id: "AGENT-PO01"
    materials:
      - name: "ref.txt"
        digest: {}
-->
"""


@pytest.fixture
def keypair(tmp_path: Path) -> tuple[Path, Path]:
    priv = tmp_path / "keys" / "ed25519.key"
    pub = tmp_path / "keys" / "ed25519.pub"
    priv.parent.mkdir(parents=True, exist_ok=True)
    provtools.keygen_ed25519(priv, pub)
    return priv, pub


def test_pipeline_emits_attestation(tmp_path: Path, keypair: tuple[Path, Path]):
    priv, _ = keypair
    base = tmp_path

    ref = base / "ref.txt"
    ref.write_text("hello", encoding="utf-8")

    policy = base / "policy.md"
    policy.write_text(HEADER + "# Body\n", encoding="utf-8")

    attestation = base / "attestations" / "policy.dsse"

    policy_synth_pipeline.run_pipeline(
        artifact=policy.relative_to(base),
        private_key=priv.relative_to(base),
        attestation=attestation.relative_to(base),
        base_dir=base,
    )

    assert attestation.exists(), "Attestation should be generated"
    envelope = json.loads(attestation.read_text(encoding="utf-8"))
    assert envelope["payloadType"] == "application/vnd.in-toto+json"
