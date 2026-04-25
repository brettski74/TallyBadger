from pathlib import Path

from psycopg import connect

from tallybadger.core.config import get_settings


def apply_sql_migrations(database_url: str, sql_dir: Path | None = None) -> list[str]:
    migrations_dir = sql_dir or Path(__file__).resolve().parents[2] / "sql"
    migration_files = sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql"))
    if not migration_files:
        return []

    applied: list[str] = []
    with connect(database_url, autocommit=False) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                for migration_file in migration_files:
                    cur.execute(migration_file.read_text(encoding="utf-8"))
                    applied.append(migration_file.name)
    return applied


def main() -> None:
    settings = get_settings()
    applied = apply_sql_migrations(settings.database_url)
    for migration in applied:
        print(f"applied {migration}")


if __name__ == "__main__":
    main()
