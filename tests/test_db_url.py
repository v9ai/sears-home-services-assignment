"""`normalize_asyncpg_url` — libpq→asyncpg translation (Neon dashboard strings)."""

from app.db.base import normalize_asyncpg_url


def test_neon_style_url_translates_sslmode_and_drops_channel_binding():
    url = normalize_asyncpg_url(
        "postgresql://user:pw@ep-x-pooler.us-east-1.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )
    assert url.drivername == "postgresql+asyncpg"
    assert url.query == {"ssl": "require"}


def test_plain_local_url_is_untouched_except_driver():
    url = normalize_asyncpg_url("postgresql://postgres:postgres@db:5432/sears")
    assert url.drivername == "postgresql+asyncpg"
    assert url.query == {}
    assert url.host == "db"


def test_existing_ssl_param_wins_over_sslmode():
    url = normalize_asyncpg_url("postgresql://u:p@h/db?sslmode=require&ssl=prefer")
    assert url.query == {"ssl": "prefer"}


def test_postgres_scheme_alias():
    assert normalize_asyncpg_url("postgres://u:p@h/db").drivername == "postgresql+asyncpg"
