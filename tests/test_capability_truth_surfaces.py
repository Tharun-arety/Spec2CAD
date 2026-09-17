"""Public capability claims must remain projections of the registry."""

from pathlib import Path

from fastapi.testclient import TestClient

import api.main as main
from spec2cad.capabilities import HEALTH_CAPABILITY_IDS, capability_payload


ROOT = Path(__file__).resolve().parents[1]
client = TestClient(main.app)


def test_health_capabilities_derive_from_the_registry():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["capabilities"] == list(HEALTH_CAPABILITY_IDS)
    assert body["capability_registry"] == capability_payload()
    assert body["model_connections"]["bring_your_own_key"] is True
    assert body["model_connections"]["credentials_persisted"] is False


def test_readme_and_report_do_not_repeat_the_pre_audit_stale_claim():
    stale = "There is still no GD&T, tolerancing, assembly reasoning, or bent-sheet-metal model."
    assert stale not in (ROOT / "README.md").read_text(encoding="utf-8")
    assert stale not in (ROOT / "eval" / "run_eval.py").read_text(encoding="utf-8")
    assert stale not in (ROOT / "eval" / "report.md").read_text(encoding="utf-8")


def test_readme_names_the_capability_source_of_truth():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "spec2cad/capabilities.py" in readme
    assert "capability_registry" in readme
