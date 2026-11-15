import json
from pathlib import Path
import pytest
from scripts.new_client import scaffold


def test_scaffold_excludes_data_and_has_client_defaults(tmp_path):
    config = {
        "storeId": "new-client",
        "businessName": "New Client",
        "categories": ["Devices"],
    }
    target = scaffold(config, tmp_path / "new-store")
    assert (
        json.loads((target / "profiles/default.json").read_text())["businessName"]
        == "New Client"
    )
    for name in [".git", "data", ".env", ".venv", "examples", "artifacts"]:
        assert not (target / name).exists()
    assert (target / "app.py").exists() and (target / "migrations.py").exists()
    with pytest.raises(ValueError):
        scaffold(config, target)
