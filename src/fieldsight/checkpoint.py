""" the LangGraph checkpointer: one thread per (analyst, incident, participant), so no participant's state merges with another's """

import atexit
import threading
from enum import StrEnum
from typing import Any
from uuid import UUID

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sqlalchemy.engine import URL, make_url

from fieldsight.aws import clients
from fieldsight.config import settings
from fieldsight.repository import SessionRepository
from fieldsight.schemas.review import ReviewVerdict
from fieldsight.schemas.run_records import ModelCall, RuleInvocation, ToolInvocation

# the recordability and reportability legs run concurrently, so the checkpointer needs more than one connection
POOL_MAX_SIZE = 4
POSTGRES_PORT = 5432


class Participant(StrEnum):
    """ every graph participant that keeps its own checkpointer thread (sections 5 and 10) """

    COORDINATOR = "coordinator"
    RECORDABILITY = "recordability"
    REPORTABILITY = "reportability"
    HAZARD_CONTROL = "hazard_control"
    REVIEWER = "reviewer"


def thread_id(analyst_id: UUID | str, incident_id: UUID | str, participant: Participant | str) -> str:
    """ the stable thread for one participant on one incident for one analyst, so a later turn resumes it """

    # an unknown participant is a ValueError, never a stray thread
    role = Participant(participant)
    parts = (str(analyst_id), str(incident_id))
    for part in parts:
        # ':' separates the parts; the Gateway's thread header also refuses whitespace and non-ASCII
        if not part or ":" in part or not part.isascii() or any(char.isspace() for char in part):
            raise ValueError(f"invalid thread id component: {part!r}")
    return f"{parts[0]}:{parts[1]}:{role}"


def open_thread(
    analyst_id: UUID, incident_id: UUID, participant: Participant | str, sessions: SessionRepository | None = None
) -> dict:
    """ the run config for one participant's thread, registered in sessions the first time and reused after """

    role = Participant(participant)
    thread = thread_id(analyst_id, incident_id, role)
    (sessions or SessionRepository()).get_or_create(thread, analyst_id, incident_id, role.value)
    return {"configurable": {"thread_id": thread}}


def conninfo() -> str:
    """ FIELDSIGHT_DATABASE_URL in libpq form (PostgresSaver doesn't take SQLAlchemy's '+psycopg'); no password under IAM auth """

    url = make_url(settings.database_url)
    password = None if settings.database_iam_auth else url.password
    # built explicitly: url.set(password=None) leaves the password in place
    return URL.create(
        "postgresql", username=url.username, password=password,
        host=url.host, port=url.port, database=url.database, query=url.query,
    ).render_as_string(hide_password=False)


def connection_kwargs() -> dict[str, Any]:
    """ what PostgresSaver needs on every connection; the pool calls this per new connection, so an IAM token is never stale """

    kwargs: dict[str, Any] = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}
    if settings.database_iam_auth:
        url = make_url(settings.database_url)
        kwargs["password"] = clients.rds().generate_db_auth_token(
            DBHostname=url.host, Port=url.port or POSTGRES_PORT, DBUsername=url.username, Region=settings.aws_region,
        )
        # RDS refuses IAM authentication without TLS
        kwargs["sslmode"] = "require"
    return kwargs


# any fixed 64-bit number; it only has to be the same in every process that runs setup()
SETUP_LOCK_KEY = 4804804804

_SAVER: PostgresSaver | None = None
_SAVER_LOCK = threading.Lock()


def postgres_checkpointer() -> PostgresSaver:
    """ the one checkpointer every participant shares, built once per process """

    global _SAVER
    # two threads asking at once must not build two pools or run setup() twice
    with _SAVER_LOCK:
        if _SAVER is None:
            pool = ConnectionPool(conninfo(), kwargs=connection_kwargs, min_size=1, max_size=POOL_MAX_SIZE, open=True)
            atexit.register(pool.close)
            saver = PostgresSaver(pool, serde=JsonPlusSerializer(allowed_msgpack_modules=[ReviewVerdict, ModelCall, RuleInvocation, ToolInvocation]))
            _setup(saver, pool)
            _SAVER = saver
    return _SAVER


def _setup(saver: PostgresSaver, pool: ConnectionPool) -> None:
    """ setup() reads the migration version, then inserts it: two processes doing that at once insert the same
    version and one fails, so a Postgres advisory lock makes them take turns """

    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (SETUP_LOCK_KEY,))
        try:
            saver.setup()
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (SETUP_LOCK_KEY,))