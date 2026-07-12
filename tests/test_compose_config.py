"""Deploy-config guards — parse-level only, NEVER launches a container.

Mission non-negotiable 3: `docker compose up` must always yield a working system
(fresh DB → migrate → seed → serve). These tests statically validate the compose
topology, port/volume wiring, env-var references (by NAME only — values are never read
or printed), and that the Dockerfile/entrypoint reference real migrate+seed steps.

Everything here is `yaml.safe_load` + text assertions against the repo's own files.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(name: str) -> dict:
    with open(REPO_ROOT / name) as fh:
        return yaml.safe_load(fh)


def _read_text(name: str) -> str:
    return (REPO_ROOT / name).read_text()


@pytest.fixture(scope="module")
def compose() -> dict:
    return _load_yaml("docker-compose.yml")


@pytest.fixture(scope="module")
def override() -> dict:
    # Gitignored dev-only file: absent on a fresh clone, where these checks skip
    # (never fail) — same policy as the DB-backed fixtures in tests/conftest.py.
    if not (REPO_ROOT / "docker-compose.override.yml").exists():
        pytest.skip("docker-compose.override.yml not present (gitignored, dev-only)")
    return _load_yaml("docker-compose.override.yml")


# --------------------------------------------------------------------- base compose


def test_compose_defines_expected_services(compose):
    # No frontend service: the backend serves the Tier-3 upload page itself.
    assert set(compose["services"]) == {"db", "app", "ngrok"}


def test_published_port_mappings(compose):
    services = compose["services"]
    # db published on 5433 to dodge a host Postgres on 5432; internal port stays 5432.
    assert "5433:5432" in services["db"]["ports"]
    assert "8000:8000" in services["app"]["ports"]


def test_app_waits_for_a_healthy_db(compose):
    services = compose["services"]
    assert services["app"]["depends_on"]["db"]["condition"] == "service_healthy"


def test_every_long_running_service_has_a_healthcheck(compose):
    services = compose["services"]
    for name in ("db", "app"):
        assert "healthcheck" in services[name], f"{name} is missing a healthcheck"
    # The app healthcheck must probe the same /healthz route the FastAPI app serves.
    app_check = " ".join(services["app"]["healthcheck"]["test"])
    assert "/healthz" in app_check


def test_app_database_url_targets_the_in_cluster_db_by_name(compose):
    """The single-command launch must be self-contained: both DATABASE_URL and the
    alembic-preferred DATABASE_URL_DIRECT point at the in-cluster `db` host, not the
    developer's .env (Neon / localhost). Structure-only check — no secret is read."""
    env = compose["services"]["app"]["environment"]
    assert "@db:5432/" in env["DATABASE_URL"]
    assert "@db:5432/" in env["DATABASE_URL_DIRECT"]


def test_app_loads_env_file_and_mounts_named_data_volumes(compose):
    app = compose["services"]["app"]
    env_files = app["env_file"]

    # Long syntax ({path, required: false}) keeps a literal `docker compose up`
    # working on a fresh clone that hasn't created .env yet; accept both forms.
    def _path(entry):
        return entry["path"] if isinstance(entry, dict) else entry

    assert any(_path(entry) == ".env" for entry in env_files)
    assert any(entry.get("required") is False for entry in env_files if isinstance(entry, dict)), (
        ".env must be optional so the single-command launch works without it"
    )
    mounts = app["volumes"]
    assert any(m.endswith(":/app/data/uploads") for m in mounts)
    assert any(m.endswith(":/app/data/recordings") for m in mounts)


def test_named_volumes_are_declared(compose):
    assert set(compose["volumes"]) >= {"pgdata", "uploads", "recordings"}


def test_db_service_uses_named_env_vars_not_inlined_secrets(compose):
    """POSTGRES_* are referenced via ${VAR:-default} interpolation, never hardcoded
    credentials in the committed compose file."""
    env = compose["services"]["db"]["environment"]
    for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        assert key in env
        assert env[key].startswith("${"), f"{key} should be an env reference, not a literal"


def test_no_frontend_service_or_next_public_wiring_remains(compose):
    """The web UI was removed (user directive): compose must not resurrect a frontend
    service or NEXT_PUBLIC_* wiring — the emailed Tier-3 link points at the backend's
    own GET /upload/{token} page."""
    assert "web" not in compose["services"]
    assert "NEXT_PUBLIC" not in _read_text("docker-compose.yml")


def test_ngrok_is_phone_profile_gated_and_token_scoped(compose):
    ngrok = compose["services"]["ngrok"]
    assert ngrok["profiles"] == ["phone"]
    # Secret-scoping: only the tunnel token, not the whole .env.
    assert "env_file" not in ngrok
    assert set(ngrok["environment"]) == {"NGROK_AUTHTOKEN"}


# --------------------------------------------------------------------- override


def test_override_appends_env_local_after_env_so_local_wins(override):
    """Later env_file entries win in compose; env.local must come AFTER .env so a local
    PUBLIC_HOST override actually takes effect."""
    env_file = override["services"]["app"]["env_file"]
    assert env_file == [".env", "env.local"]


def test_override_adds_cloudflared_tunnel_depending_on_healthy_app(override):
    cloudflared = override["services"]["cloudflared"]
    assert "cloudflare/cloudflared" in cloudflared["image"]
    assert cloudflared["depends_on"]["app"]["condition"] == "service_healthy"


# --------------------------------------------------------------------- env-var name wiring


def _referenced_env_names(*yaml_names: str) -> set[str]:
    """Collect ${VAR} names referenced across the compose files (names only, no values)."""
    names: set[str] = set()
    pattern = re.compile(r"\$\{([A-Z0-9_]+)")
    for name in yaml_names:
        for match in pattern.finditer(_read_text(name)):
            names.add(match.group(1))
    return names


def _example_declared_keys() -> set[str]:
    return {
        line.split("=", 1)[0].strip()
        for line in _read_text(".env.example").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }


def test_backend_developer_facing_vars_are_documented_in_example():
    """The backend-side vars wired into compose (tunnel token, public host) are documented
    by NAME in .env.example so a fresh clone knows to set them. Values never read."""
    documented = _example_declared_keys()
    for name in ("NGROK_AUTHTOKEN", "PUBLIC_HOST"):
        assert name in documented, f"{name} should be documented in .env.example"


# --------------------------------------------------------------------- Dockerfile / entrypoint


def test_dockerfile_ships_migrations_and_entrypoint():
    dockerfile = _read_text("Dockerfile")
    # Migrations must be in the image for the entrypoint's `alembic upgrade` to work.
    assert "COPY" in dockerfile and "alembic" in dockerfile
    assert "alembic.ini" in dockerfile
    assert "docker-entrypoint.sh" in dockerfile
    assert 'ENTRYPOINT ["docker-entrypoint.sh"]' in dockerfile
    # The served command is the real app.
    assert "uvicorn" in dockerfile and "app.main:app" in dockerfile


def test_dockerfile_healthcheck_probes_the_app_healthz_route():
    dockerfile = _read_text("Dockerfile")
    assert "HEALTHCHECK" in dockerfile
    assert "/healthz" in dockerfile


def test_entrypoint_exists_and_is_executable_bash():
    entrypoint = REPO_ROOT / "docker-entrypoint.sh"
    assert entrypoint.exists()
    assert entrypoint.read_text().startswith("#!")


def test_entrypoint_runs_migrate_then_seed_then_execs_the_cmd():
    """Mission non-negotiable 3 ordering: migrate → seed → exec. A regression that
    reorders (e.g. serves before migrating) would ship a broken single-command launch."""
    script = _read_text("docker-entrypoint.sh")
    migrate_at = script.find("alembic upgrade heads")
    seed_at = script.find("app.db.seed")
    exec_at = script.find('exec "$@"')
    assert migrate_at != -1, "entrypoint must run alembic migrations"
    assert seed_at != -1, "entrypoint must run the seed step"
    assert exec_at != -1, "entrypoint must exec the container CMD"
    assert migrate_at < seed_at < exec_at


def test_entrypoint_fails_fast_on_migration_error():
    """A failed migration must abort the boot (set -e + explicit exit), never serve
    against an un-migrated schema."""
    script = _read_text("docker-entrypoint.sh")
    assert "set -euo pipefail" in script
    assert "exit 1" in script
