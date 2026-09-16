"""Static and generated UI capability data must match the Python registry."""

import json
from pathlib import Path

from scripts.freeze_demo import SCENARIOS
from spec2cad.capabilities import capability_payload


ROOT = Path(__file__).resolve().parents[1]


def test_static_replay_registry_is_an_exact_projection():
    payload = json.loads(
        (ROOT / "web/public/replay/capabilities.json").read_text(encoding="utf-8")
    )
    assert payload == capability_payload()


def test_every_showcase_capability_id_resolves_to_an_available_record():
    records = {item["id"]: item for item in capability_payload()["capabilities"]}
    for scenario in SCENARIOS:
        assert scenario["capability_ids"]
        for capability_id in scenario["capability_ids"]:
            assert records[capability_id]["implementation_maturity"] != "unavailable"


def test_published_catalog_keeps_labels_as_registry_ids():
    catalog = json.loads(
        (ROOT / "web/public/replay/catalog.json").read_text(encoding="utf-8")
    )
    expected = {item["id"]: item["capability_ids"] for item in SCENARIOS}
    assert {
        item["id"]: item["capability_ids"] for item in catalog["scenarios"]
    } == expected
