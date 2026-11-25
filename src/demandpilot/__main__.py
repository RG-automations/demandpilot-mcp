"""Entry point: `python -m demandpilot --db <path>`.

Starts the MCP server over stdio. Never auto-generates the database and
never writes anything but protocol data to stdout (logs go to stderr).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from demandpilot.server import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=str, required=True, help="Path to the demo SQLite database.")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.is_file():
        print(
            f"Database not found at {db_path}. Generate one first with "
            "`python -m demandpilot.data_gen --db <path>`.",
            file=sys.stderr,
        )
        return 1

    run(db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
