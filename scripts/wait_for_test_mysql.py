"""Wait until both disposable MySQL services accept host-side SQL connections."""

import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


URLS = (
    "mysql+pymysql://root@127.0.0.1:3308/opcua_collector_test",
    "mysql+pymysql://root@127.0.0.1:3309/recipecontrol_test",
)


def main() -> None:
    deadline = time.monotonic() + 90
    pending = set(URLS)
    while pending and time.monotonic() < deadline:
        for url in tuple(pending):
            engine = create_engine(
                url,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 3, "read_timeout": 3, "write_timeout": 3},
            )
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                pending.remove(url)
            except SQLAlchemyError:
                pass
            finally:
                engine.dispose()
        if pending:
            time.sleep(1)
    if pending:
        ports = ", ".join(url.rsplit(":", 1)[-1].split("/", 1)[0] for url in pending)
        raise SystemExit(f"Disposable MySQL services did not become ready on ports: {ports}")
    print("Disposable MySQL services accept host-side SQL connections.")


if __name__ == "__main__":
    main()
