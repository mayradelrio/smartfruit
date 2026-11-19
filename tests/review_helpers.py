"""Explicit QC adjudication for synthetic fixtures that exercise later workflow stages."""

from smartfruit.vision import load_vision_json


def confirm_vision_record(source):
    record = load_vision_json(source)
    for prediction in record["fruit_predictions"]:
        if prediction["predicted_class"] == "con_oleocelosis":
            prediction.update({
                "review_status": "confirmed",
                "reviewed_by": "QC fixture",
                "reviewed_at": "2026-11-18T10:00:00-05:00",
                "override_label": None,
                "override_reason": None,
            })
    return record


def confirm_vision_records(sources):
    return [confirm_vision_record(source) for source in sources]
