"""Hermetic schema smoke tests — no external database.

Two lanes, both DB-independent:

* ``test_scheduling_schema_builds_on_throwaway_sqlite`` builds the scheduling
  ORM metadata on an in-memory SQLite database and introspects it. This is the
  "schema matches the models" check the assignment asks for. It is *not* an
  ``alembic upgrade head`` run: migration ``0001_core`` declares
  ``postgresql.JSONB`` columns (``sessions.case_file`` / ``transcript``) which the
  SQLite compiler cannot render, so the migrations only apply to Postgres. The
  scheduling models themselves use no JSONB, so their DDL round-trips through
  SQLite and gives a fast, dependency-free structural check.

* The migration-graph tests exercise Alembic's ``ScriptDirectory`` — pure file
  parsing, no engine — to assert the revision graph stays single-headed and fully
  connected across the ``0004`` merge (a second head or a broken ``down_revision``
  link would silently break ``alembic upgrade head`` in every environment).
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.db.models_scheduling import Base

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SCHEDULING_TABLES = {
    "technicians",
    "specialties",
    "technician_specialties",
    "service_areas",
    "availability_slots",
    "appointments",
}


def _sqlite_inspector():
    # A throwaway in-memory SQLite database — nothing persists, nothing external
    # is touched. `Base.metadata` includes the `customers` / `sessions` FK
    # stand-ins registered by tests/scheduling/conftest.py, so `appointments`'
    # foreign keys resolve during create_all.
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return inspect(engine)


def test_scheduling_schema_builds_on_throwaway_sqlite():
    inspector = _sqlite_inspector()
    tables = set(inspector.get_table_names())
    assert _SCHEDULING_TABLES <= tables


def test_availability_slot_uniqueness_and_status_column():
    """A technician can't hold two slots at the same start (double-issue guard),
    and every slot carries a ``status`` the booking claim flips open→booked."""
    inspector = _sqlite_inspector()

    uniques = inspector.get_unique_constraints("availability_slots")
    assert any(set(uc["column_names"]) == {"technician_id", "starts_at"} for uc in uniques), uniques

    columns = {c["name"] for c in inspector.get_columns("availability_slots")}
    assert {"technician_id", "starts_at", "ends_at", "status"} <= columns


def test_appointment_links_slot_technician_customer_and_session():
    """The appointment row must reference exactly the four entities the booking
    tool populates, and one slot may back at most one appointment."""
    inspector = _sqlite_inspector()

    fk_targets = {
        (tuple(fk["constrained_columns"]), fk["referred_table"])
        for fk in inspector.get_foreign_keys("appointments")
    }
    assert (("slot_id",), "availability_slots") in fk_targets
    assert (("technician_id",), "technicians") in fk_targets
    assert (("customer_id",), "customers") in fk_targets
    assert (("session_id",), "sessions") in fk_targets

    # slot_id is declared unique on the column: one appointment per slot.
    uniques = inspector.get_unique_constraints("appointments")
    unique_indexes = [ix for ix in inspector.get_indexes("appointments") if ix["unique"]]
    slot_is_unique = any(uc["column_names"] == ["slot_id"] for uc in uniques) or any(
        ix["column_names"] == ["slot_id"] for ix in unique_indexes
    )
    assert slot_is_unique, (uniques, unique_indexes)


def test_specialty_junction_binds_technician_and_specialty():
    inspector = _sqlite_inspector()
    fk_targets = {
        (tuple(fk["constrained_columns"]), fk["referred_table"])
        for fk in inspector.get_foreign_keys("technician_specialties")
    }
    assert (("technician_id",), "technicians") in fk_targets
    assert (("specialty_id",), "specialties") in fk_targets


# --- Migration graph (file parsing only, no DB) -----------------------------


def _script_directory() -> ScriptDirectory:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    # Absolute script_location so the check is independent of the process cwd.
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_migrations_have_a_single_head_and_base():
    sd = _script_directory()
    assert len(sd.get_heads()) == 1, sd.get_heads()
    assert len(sd.get_bases()) == 1, sd.get_bases()


def test_every_revision_is_reachable_from_the_single_head():
    """The head must reach the base through valid ``down_revision`` links across
    both branches of the ``0004`` merge — an orphaned revision or a dangling
    parent reference would abort a real ``alembic upgrade``."""
    sd = _script_directory()
    (head,) = sd.get_heads()
    (base,) = sd.get_bases()

    all_revisions = {r.revision for r in sd.walk_revisions()}
    # iterate_revisions(head, base) traverses both merge branches but excludes the
    # lower bound, so add the base back before comparing.
    reachable = {r.revision for r in sd.iterate_revisions(head, base)} | {base}
    assert reachable == all_revisions


def test_every_parent_link_resolves_and_exactly_one_base_exists():
    sd = _script_directory()
    all_revisions = {r.revision for r in sd.walk_revisions()}

    bases = []
    for rev in sd.walk_revisions():
        down = rev.down_revision
        if down is None:
            bases.append(rev.revision)
            continue
        parents = (down,) if isinstance(down, str) else tuple(down)
        for parent in parents:
            assert parent in all_revisions, (rev.revision, parent)
    assert len(bases) == 1  # single starting point for `alembic upgrade`
