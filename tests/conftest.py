import psycopg
import pytest

from fieldsight.config import settings


@pytest.fixture(autouse=True)
def clean_db():
    """Truncate all core tables before every test so each test starts
    from a known-empty state. Assumes a local dev Postgres via
    docker compose — never point this at a shared/prod database."""
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE incidents, run_records, review_queue, sessions CASCADE;"
            )
        conn.commit()
    yield