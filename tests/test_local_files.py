"""Regresión de bloqueos breves al publicar resultados en Windows/OneDrive."""

import json
from pathlib import Path

import pytest

from smartfruit import local_files


def test_atomic_json_retries_reader_lock_and_keeps_old_target_until_success(tmp_path, monkeypatch):
    destination = tmp_path / "progress.json"
    destination.write_text('{"completed": 0}', encoding="utf-8")
    replace = Path.replace
    attempts = []
    waits = []

    def transient_lock(path, target):
        attempts.append(path)
        if len(attempts) <= 2:
            assert json.loads(destination.read_text("utf-8")) == {"completed": 0}
            raise PermissionError("WinError 5: el lector mantiene abierto el destino")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", transient_lock)
    monkeypatch.setattr(local_files.time, "sleep", waits.append)
    local_files.write_json_atomic(destination, {"completed": 12})
    assert len(attempts) == 3
    assert waits == [0.02, 0.04]
    assert json.loads(destination.read_text("utf-8")) == {"completed": 12}
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_json_retries_temporary_write_lock_too(tmp_path, monkeypatch):
    write_text = Path.write_text
    attempts = []

    def transient_write_lock(path, *args, **kwargs):
        attempts.append(path)
        if len(attempts) < 3:
            raise PermissionError("Sincronización en curso")
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", transient_write_lock)
    monkeypatch.setattr(local_files.time, "sleep", lambda delay: None)
    destination = tmp_path / "result.json"
    local_files.write_json_atomic(destination, {"records": []})
    assert len(attempts) == 3
    assert json.loads(destination.read_text("utf-8")) == {"records": []}


def test_permanent_lock_stops_after_bounded_retries_without_corrupting_target(tmp_path, monkeypatch):
    destination = tmp_path / "response.json"
    destination.write_text('{"records": []}', encoding="utf-8")
    attempts = []

    def locked(path, target):
        attempts.append(path)
        raise PermissionError("Destino bloqueado")

    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr(local_files.time, "sleep", lambda delay: None)
    with pytest.raises(PermissionError, match="bloqueado"):
        local_files.write_json_atomic(destination, {"records": [1]})
    assert len(attempts) == 10
    assert json.loads(destination.read_text("utf-8")) == {"records": []}
    assert list(tmp_path.glob("*.tmp")) == []
