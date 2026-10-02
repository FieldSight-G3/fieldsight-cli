"""A photo that can't be judged is skipped and named in the report; it never stops the packet's submit."""

from pathlib import Path

from botocore.exceptions import ClientError

from fieldsight.errors import ExtractionError
from fieldsight.ingest import submit


def denied(photo, narrative):
    raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}}, "Converse")


def test_a_photo_model_the_caller_cant_use_skips_the_photo(monkeypatch):
    monkeypatch.setattr(submit, "corroborate", denied)

    verdicts, failures = submit.corroborate_photos([Path("IMG_1.jpg")], "a narrative")

    assert verdicts == []
    assert failures == [{"artifact": "IMG_1.jpg", "reason": "the photo model couldn't be called (AccessDeniedException)"}]


def test_one_failed_photo_never_costs_the_others(monkeypatch):
    def judge(photo, narrative):
        if photo.name == "bad.jpg":
            raise ExtractionError("no valid corroboration verdict for bad.jpg after one retry")
        return {"artifact": photo.name, "verdict": "inconclusive", "observation": "pliers", "reason": "no injury shown"}

    monkeypatch.setattr(submit, "corroborate", judge)

    verdicts, failures = submit.corroborate_photos([Path("bad.jpg"), Path("good.jpg")], "a narrative")

    assert [v["artifact"] for v in verdicts] == ["good.jpg"] and [f["artifact"] for f in failures] == ["bad.jpg"]
