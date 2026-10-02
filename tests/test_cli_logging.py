"""The CLI's logs go to a file, so the terminal shows only the command's result."""

import subprocess
import sys

SCRIPT = """
import logging, sys
from pathlib import Path
from fieldsight.logging_context import configure_logging
configure_logging(path=Path(sys.argv[1]))
logging.getLogger("botocore.credentials").info("Found credentials in shared credentials file")
print("the result")
"""


def test_logs_land_in_the_file_and_only_the_result_on_screen(tmp_path):
    log = tmp_path / "nested" / "cli.log"

    done = subprocess.run([sys.executable, "-c", SCRIPT, str(log)], capture_output=True, text=True, check=True)

    assert done.stdout.strip() == "the result" and done.stderr == ""
    assert "Found credentials" in log.read_text(encoding="utf-8")
