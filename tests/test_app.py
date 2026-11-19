"""API user flows: evaluate, export, explicit confirmation, and persisted downloads."""

import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from uuid import UUID

import openpyxl
import pytest
from fastapi.testclient import TestClient
from review_helpers import confirm_vision_records

from smartfruit.app import create_app


@pytest.fixture
def capture():
    examples = Path(__file__).resolve().parents[1] / "examples" / "vision"
    manual_keys = (
        "decay",
        "styler",
        "mold",
        "soft",
        "skin_breakdown",
        "wounds",
        "int_dryness",
        "black_tips",
        "skin_defect",
        "scars",
        "white_stain",
        "blanching",
        "yellow_color",
        "stain",
        "undersize",
    )
    return {
        "qc_header": {
            "inspection_date": "2026-11-13",
            "lot_id": "LOT_DEMO_001",
            "Level_Flag": 1,
        },
        "samples": [
            {
                "sample_id": "SAMPLE_DEMO_001",
                "pallet_id": "PALLET_DEMO_01",
                "vision_records": confirm_vision_records([
                    json.loads((examples / f"IMG_{image}.json").read_text("utf-8"))
                    for image in (6426, 6427, 6428)
                ]),
                "vision_covers_sample": True,
                "qc_fields": {**dict.fromkeys(manual_keys, 0), "sample_count": 36},
                "observations": "Inspección manual demo.",
            }
        ],
        "observations": "Conservar observaciones.",
    }


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, use_predictive=False), raise_server_exceptions=False) as c:
        yield c


def _confirmed(capture):
    result = deepcopy(capture)
    result.update(
        inspector_name="Inspector Demo",
        confirmed=True,
        final_decisions={"SAMPLE_DEMO_001": "STANDARD"},
    )
    return result


def test_index_config_and_original_demo_are_available(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    assert "SmartFruit" in index.text

    config = client.get("/api/config")
    assert config.status_code == 200
    assert config.json()["use_predictive"] is False
    assert len(config.json()["manual_defects"]) == 15
    labels = {column["label"] for column in config.json()["qc_columns"]}
    assert {"Sample", "Oleocellosis", "Skin defect", "Int. Dryness"} <= labels

    demo = client.get("/api/demo")
    assert demo.status_code == 200
    assert len(demo.json()["records"]) == 3
    assert sum(record["total_fruits"] for record in demo.json()["records"]) == 36


def test_evaluate_is_off_by_default_and_does_not_persist(client, capture, tmp_path):
    response = client.post("/api/evaluate", json=capture)
    assert response.status_code == 200
    report = response.json()
    sample = report["samples"][0]
    assert sample["final_recommendation"] == "EXTEND"
    assert sample["inspection_summary"]["oleocellosis_count"] == 3
    assert "predicted_loss_pct" not in sample["predictive"]
    assert report["inspector_confirmed"] is False
    assert list(tmp_path.iterdir()) == []


def test_export_draft_preserves_qc_layout_without_finalizing(client, capture, tmp_path):
    response = client.post("/api/export", json=capture)
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["content-type"]
    workbook = openpyxl.load_workbook(BytesIO(response.content), data_only=True)
    sheet = workbook["Report"]
    assert sheet["I15"].value.strip() == "Sample"
    assert sheet["R15"].value == "Oleocellosis"
    assert sheet["I16"].value == 36
    assert sheet["R16"].value == 3
    text = " ".join(str(cell.value) for row in sheet for cell in row if cell.value is not None)
    assert "SmartFruit" in text
    assert "BORRADOR" in text
    assert "EXTEND" in text
    assert "predicted_loss_pct" not in text
    assert list(tmp_path.iterdir()) == []


def test_finalize_persists_source_and_report_with_inspector_authority(client, capture, tmp_path):
    payload = _confirmed(capture)
    # The server must recalculate rather than trust client-provided recommendations.
    payload["final_recommendation"] = "STANDARD"
    payload["inspector_confirmed"] = True
    response = client.post("/api/finalize", json=payload)
    assert response.status_code == 200
    result = response.json()
    report_id = result["report_id"]
    assert str(UUID(report_id)) == report_id
    stored = tmp_path / report_id
    assert {path.name for path in stored.iterdir()} == {"source.json", "report.json", "report.xlsx"}
    assert json.loads((stored / "source.json").read_text("utf-8")) == payload
    assert json.loads((stored / "report.json").read_text("utf-8")) == result["report"]

    report = result["report"]
    sample = report["samples"][0]
    assert report["inspector_name"] == "Inspector Demo"
    assert report["inspector_confirmed"] is True
    assert report["confirmed_at"]
    assert report["qc_header"]["Level_Flag"] == 1
    assert report["observations"] == "Conservar observaciones."
    assert sample["final_recommendation"] == "EXTEND"
    assert sample["inspector_final_decision"] == "STANDARD"
    assert sample["inspector_confirmed"] is True

    downloaded_json = client.get(result["downloads"]["json"])
    assert downloaded_json.status_code == 200
    assert downloaded_json.json() == report
    downloaded_xlsx = client.get(result["downloads"]["xlsx"])
    assert downloaded_xlsx.status_code == 200
    assert downloaded_xlsx.content == (stored / "report.xlsx").read_bytes()
    sheet = openpyxl.load_workbook(BytesIO(downloaded_xlsx.content), data_only=True)["Report"]
    assert sheet["R16"].value == 3
    assert sheet["U2"].value == "Level Flag: 1"
    values = " ".join(str(cell.value) for row in sheet for cell in row if cell.value is not None)
    assert "CONFIRMADO" in values
    assert "Inspector Demo" in values
    assert "EXTEND" in values
    assert "STANDARD" in values
    assert "predicted_loss_pct" not in values


@pytest.mark.parametrize(
    "updates",
    [
        {"confirmed": False},
        {"confirmed": "true"},
        {"inspector_name": " "},
        {"final_decisions": {}},
        {"final_decisions": {"SAMPLE_DEMO_001": "INVALID"}},
    ],
)
def test_finalize_requires_explicit_valid_human_confirmation(client, capture, updates, tmp_path):
    payload = _confirmed(capture)
    payload.update(updates)
    response = client.post("/api/finalize", json=payload)
    assert response.status_code == 422
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "case",
    [
        "missing-header",
        "missing-date",
        "bad-date",
        "missing-lot",
        "bad-level-flag",
        "empty-samples",
        "sample-not-object",
        "missing-manual",
        "bad-manual",
        "bad-coverage",
        "wrong-denominator",
        "bad-vision",
        "bad-class",
        "observations-not-text",
    ],
)
@pytest.mark.parametrize("endpoint", ["evaluate", "export", "finalize"])
def test_invalid_capture_is_a_client_error_never_500(client, capture, case, endpoint):
    payload = _confirmed(capture)
    sample = payload["samples"][0]
    if case == "missing-header":
        payload.pop("qc_header")
    elif case == "missing-date":
        payload["qc_header"].pop("inspection_date")
    elif case == "bad-date":
        payload["qc_header"]["inspection_date"] = "2026-02-30"
    elif case == "missing-lot":
        payload["qc_header"].pop("lot_id")
    elif case == "bad-level-flag":
        payload["qc_header"]["Level_Flag"] = {"bad": "value"}
    elif case == "empty-samples":
        payload["samples"] = []
    elif case == "sample-not-object":
        payload["samples"] = [None]
    elif case == "missing-manual":
        sample["qc_fields"].pop("soft")
    elif case == "bad-manual":
        sample["qc_fields"]["mold"] = []
    elif case == "bad-coverage":
        sample["vision_covers_sample"] = False
    elif case == "wrong-denominator":
        sample["qc_fields"]["sample_count"] = 999
    elif case == "bad-vision":
        sample["vision_records"][0]["fruit_predictions"] = None
    elif case == "bad-class":
        sample["vision_records"][0]["fruit_predictions"][0]["predicted_class"] = []
    elif case == "observations-not-text":
        payload["observations"] = {}
    response = client.post(f"/api/{endpoint}", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("body", ["{broken", "null", "[]", '"text"'])
def test_malformed_json_and_non_object_bodies_are_rejected(client, body):
    response = client.post(
        "/api/evaluate", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_standard_json_numbers_are_rejected_before_persisting(client, capture, constant):
    body = json.dumps(_confirmed(capture))[:-1] + f', "extra": {constant}' + "}"
    response = client.post(
        "/api/finalize",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/api/reports/not-a-uuid/json",
        "/api/reports/00000000-0000-0000-0000-000000000000/json",
        "/api/reports/00000000-0000-0000-0000-000000000000/source.json",
        "/api/reports/%2E%2E/json",
        "/api/reports/%2E%2E%2F%2E%2E/json",
    ],
)
def test_invalid_and_traversal_downloads_are_not_found(client, path):
    assert client.get(path).status_code == 404


def test_on_without_an_artifact_continues_to_return_rule_recommendation(capture, tmp_path):
    with TestClient(create_app(tmp_path, use_predictive=True)) as on_client:
        assert on_client.get("/api/config").json()["use_predictive"] is True
        response = on_client.post("/api/evaluate", json=capture)
    assert response.status_code == 200
    sample = response.json()["samples"][0]
    assert sample["final_recommendation"] == "EXTEND"
    assert sample["predictive"]["enabled"] is True
    assert sample["predictive"]["predicted_loss_pct"] is None
