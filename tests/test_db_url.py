"""`normalize_asyncpg_url` — libpq→asyncpg translation (Neon dashboard strings).

Fully hermetic: pure string/URL manipulation, no engine and no DB connection.
"""

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


def test_already_asyncpg_url_is_not_double_prefixed():
    """An already-normalized DSN must pass through with the driver intact — the
    prefix swap keys off the bare ``postgresql://`` / ``postgres://`` schemes, so
    ``postgresql+asyncpg://`` must not match and become ``postgresql+asyncpg+asyncpg``."""
    url = normalize_asyncpg_url("postgresql+asyncpg://u:p@h:5432/db")
    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "h"
    assert url.port == 5432


def test_channel_binding_dropped_even_without_sslmode():
    """asyncpg rejects ``channel_binding`` regardless of whether ``sslmode`` is
    present; dropping it must not synthesize an ``ssl`` key out of nothing."""
    url = normalize_asyncpg_url("postgresql://u:p@h/db?channel_binding=require")
    assert "channel_binding" not in url.query
    assert "ssl" not in url.query
    assert url.query == {}


def test_credentials_host_port_database_survive_translation():
    url = normalize_asyncpg_url(
        "postgresql://alice:s3cr3t@primary.example.com:6543/appdb?sslmode=require"
    )
    assert url.username == "alice"
    assert url.password == "s3cr3t"
    assert url.host == "primary.example.com"
    assert url.port == 6543
    assert url.database == "appdb"
    assert url.query == {"ssl": "require"}


def test_unrelated_query_params_are_preserved_alongside_ssl_translation():
    url = normalize_asyncpg_url(
        "postgresql://u:p@h/db?sslmode=require&channel_binding=require"
        "&application_name=sears&connect_timeout=10"
    )
    assert url.query["ssl"] == "require"
    assert url.query["application_name"] == "sears"
    assert url.query["connect_timeout"] == "10"
    assert "channel_binding" not in url.query
    assert "sslmode" not in url.query


def test_sslmode_value_is_carried_through_verbatim():
    """The translation renames the key, not the value — ``disable`` must not become
    ``require`` or get normalized away."""
    url = normalize_asyncpg_url("postgresql://u:p@h/db?sslmode=disable")
    assert url.query == {"ssl": "disable"}


def test_postgres_alias_also_translates_neon_params():
    url = normalize_asyncpg_url(
        "postgres://u:p@ep-x-pooler.neon.tech/neondb?sslmode=require&channel_binding=require"
    )
    assert url.drivername == "postgresql+asyncpg"
    assert url.query == {"ssl": "require"}
