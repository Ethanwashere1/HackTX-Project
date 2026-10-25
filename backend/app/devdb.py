"""Manage the embedded dev Postgres: `uv run python -m app.devdb url|stop`."""

import sys

from app.db import EMBEDDED_DB, PGDATA_DIR


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "url"
    if cmd == "url":
        from app.db import embedded_url

        print(embedded_url(EMBEDDED_DB))
    elif cmd == "stop":
        if not (PGDATA_DIR / "postmaster.pid").exists():
            print("Embedded Postgres is not running")
            return
        from pgserver import pg_ctl

        pg_ctl(["-w", "stop"], pgdata=PGDATA_DIR)
        print("Embedded Postgres stopped")
    else:
        sys.exit("usage: python -m app.devdb url|stop")


if __name__ == "__main__":
    main()
