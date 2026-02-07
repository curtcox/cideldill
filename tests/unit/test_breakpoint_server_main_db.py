"""Tests for breakpoint server __main__ DB resolution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import cideldill_server.__main__ as main


def test_resolve_db_path_defaults_to_disk(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(db=None, memory=False)

    resolved = Path(main.resolve_db_path(args))

    assert resolved.parent == tmp_path / ".cideldill" / "breakpoint_dbs"
    assert resolved.name.startswith("breakpoints-")
    assert resolved.name.endswith(".sqlite3")


def test_resolve_db_path_memory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(db=None, memory=True)

    assert main.resolve_db_path(args) == ":memory:"


def test_resolve_db_path_expands_relative(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(db="dbs/custom.sqlite3", memory=False)

    resolved = Path(main.resolve_db_path(args))

    assert resolved == tmp_path / "dbs" / "custom.sqlite3"
