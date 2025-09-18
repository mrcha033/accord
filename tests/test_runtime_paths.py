from pathlib import Path

import pytest

from orchestrator.runtime import _rel_to_base


def test_rel_to_base_with_relative_path(tmp_path):
    base_dir = tmp_path
    dsse = base_dir / "attestations" / "x" / "y.dsse"
    dsse.parent.mkdir(parents=True)
    dsse.write_text("payload")

    assert _rel_to_base(Path("attestations/x/y.dsse"), base_dir) == "attestations/x/y.dsse"


def test_rel_to_base_with_absolute_path(tmp_path):
    base_dir = tmp_path
    dsse = base_dir / "attestations" / "y.dsse"
    dsse.parent.mkdir(parents=True)
    dsse.write_text("payload")

    assert _rel_to_base(dsse, base_dir) == "attestations/y.dsse"


@pytest.mark.usefixtures("caplog")
def test_rel_to_base_outside_base(tmp_path, tmp_path_factory, caplog):
    base_dir = tmp_path
    external_root = tmp_path_factory.mktemp("external")
    external = external_root / "z.dsse"
    external.write_text("payload")

    with caplog.at_level("WARNING"):
        result = _rel_to_base(external, base_dir)

    assert result == str(external.resolve())
    assert "not under base" in caplog.text
