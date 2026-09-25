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
