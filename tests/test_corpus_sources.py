"""The corpus manifest is found in the repo, or where FIELDSIGHT_CORPUS_SOURCES names it (the Runtime image)."""

import importlib
import json

from fieldsight.ingest.corpus import sources


def test_the_repo_manifest_lists_the_letters():
    assert sources.CORPUS_SOURCES.exists() and sources.letters()


def test_an_installed_package_reads_the_manifest_the_environment_names(tmp_path, monkeypatch):
    manifest = tmp_path / "sources.json"
    manifest.write_text(json.dumps({"documents": [{"doc_type": "interpretation", "items": [
        {"label": "2021-01-08", "title": "a letter"}]}]}), encoding="utf-8")
    monkeypatch.setenv("FIELDSIGHT_CORPUS_SOURCES", str(manifest))
    try:
        assert importlib.reload(sources).letters() == {"2021-01-08": "a letter"}
    finally:
        monkeypatch.delenv("FIELDSIGHT_CORPUS_SOURCES")
        importlib.reload(sources)
