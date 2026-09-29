"""§11: every query goes through the repository module, parameterized."""

import re
from pathlib import Path

from sqlalchemy import create_engine

from fieldsight.repository import GatewayReadRepository, database_ready

SRC = Path(__file__).resolve().parents[2] / "src" / "fieldsight"
# the repository module owns queries; the LangGraph checkpointer manages its own tables by design (graph README)
ALLOWED = {"repository.py", "checkpoint.py"}
DATABASE_CALL = re.compile(r"\.execute\(|\.exec_driver_sql\(|create_engine\(|psycopg\.connect\(|Connection\.connect\(|\bsql_text\(|sqlalchemy import .*\btext\b")


def test_no_module_outside_the_repository_talks_to_the_database():
    offenders = [
        f"{path.relative_to(SRC)}:{number}: {line.strip()}"
        for path in SRC.rglob("*.py")
        if path.name not in ALLOWED
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if DATABASE_CALL.search(line)
    ]
    assert offenders == [], "move these queries into repository.py:\n" + "\n".join(offenders)


def test_readiness_probe_reports_a_reachable_and_an_unreachable_database():
    assert database_ready(GatewayReadRepository().engine) is True
    unreachable = create_engine("postgresql+psycopg://nobody:nothing@127.0.0.1:9/none", connect_args={"connect_timeout": 2})
    assert database_ready(unreachable) is False
