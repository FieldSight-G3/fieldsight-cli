import os

from dotenv import load_dotenv

# config.py reads the environment on import, so every setting must exist before fieldsight is imported.
# Real values from .env win; anything missing or empty gets the same placeholder CI uses.
load_dotenv()
TEST_ENVIRONMENT = {
    "FIELDSIGHT_ENVIRONMENT": "test",
    "FIELDSIGHT_AWS_REGION": "us-east-1",
    "FIELDSIGHT_BEDROCK_MODEL_ID": "test-placeholder",
    "FIELDSIGHT_BEDROCK_FAST_MODEL_ID": "test-placeholder",
    "FIELDSIGHT_BEDROCK_JUDGE_MODEL_ID": "test-placeholder",
    "FIELDSIGHT_BEDROCK_EMBEDDING_MODEL_ID": "test-placeholder",
    "FIELDSIGHT_BEDROCK_KB_ID": "test-placeholder",
    "FIELDSIGHT_BEDROCK_KB_DATA_SOURCE_ID": "test-placeholder",
    "FIELDSIGHT_BEDROCK_GUARDRAIL_ID": "test-placeholder",
    "FIELDSIGHT_BEDROCK_GUARDRAIL_VERSION": "1",
    "FIELDSIGHT_PACKET_BUCKET": "test-placeholder",
    "FIELDSIGHT_DATABASE_URL": "postgresql://fieldsight:fieldsight_dev@localhost:5432/fieldsight",
    "FIELDSIGHT_RETRIEVAL_SCORE_THRESHOLD": "0.5",
    "FIELDSIGHT_RETRIEVAL_MAX_CHUNKS": "8",
    "FIELDSIGHT_CONFIDENCE_FLOOR": "0.7",
    "FIELDSIGHT_GATEWAY_API_KEY": "test-placeholder",
    "FIELDSIGHT_ALLOW_DEV_IDENTITY": "true",
}
for key, value in TEST_ENVIRONMENT.items():
    if not os.environ.get(key):
        os.environ[key] = value

import psycopg
import pytest
from langchain_core.documents import Document

from fieldsight.config import settings


@pytest.fixture(autouse=True)
def clean_db():
    """Truncate all core tables before every test so each test starts
    from a known-empty state. Assumes a local dev Postgres via
    docker compose — never point this at a shared/prod database."""
    psycopg_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://",1)
    with psycopg.connect(psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE incidents, run_records, review_queue, sessions CASCADE;"
            )
        conn.commit()
    yield


class ScriptedModel:
    """ stands in for Bedrock: replays one reply per model call """

    def __init__(self, replies):
        self.replies = list(replies)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return self.replies.pop(0)


@pytest.fixture
def script(monkeypatch):
    """ replace Bedrock with scripted replies for the specialists; every corpus search returns chunk CFR-1904-a """

    from fieldsight.aws import clients
    from fieldsight.graph import specialists
    from fieldsight.tools import tools

    hit = Document(page_content="text of 1904.39", metadata={"score": 0.82, "source_metadata": {
        "chunk_id": "CFR-1904-a", "doc_id": "CFR-1904", "title": "29 CFR Part 1904", "doc_type": "regulation",
        "section_path": "1904.39", "page": 1}})
    monkeypatch.setattr(tools, "search", lambda query, doc_type=None, section_path=None: [hit])

    def use(replies):
        model = ScriptedModel(replies)
        monkeypatch.setattr(clients, "chat_model", lambda: model)
        # drop the cached specialists so they're rebuilt on the scripted model
        monkeypatch.setattr(specialists, "_SPECIALISTS", None)

    return use
