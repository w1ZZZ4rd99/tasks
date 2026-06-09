"""Unit tests for the audit log."""

import json
from datetime import datetime

from src.domain import AuditLog, AuditSeverity


def clock():
    return datetime(2026, 6, 9, 12, 0, 0)


def test_log_appends_in_memory():
    log = AuditLog(now=clock)
    event = log.log(AuditSeverity.INFO, "test.action", "hello", account="A1")
    assert len(log) == 1
    assert event.metadata == {"account": "A1"}
    assert event.timestamp == clock()


def test_filter_by_min_severity():
    log = AuditLog(now=clock)
    log.log(AuditSeverity.INFO, "a", "i")
    log.log(AuditSeverity.WARNING, "b", "w")
    log.log(AuditSeverity.CRITICAL, "c", "c")
    warn_plus = log.filter(min_severity=AuditSeverity.WARNING)
    assert len(warn_plus) == 2
    assert all(e.severity.value >= AuditSeverity.WARNING.value for e in warn_plus)


def test_filter_by_action_and_predicate():
    log = AuditLog(now=clock)
    log.log(AuditSeverity.INFO, "tx.completed", "ok", amount=10)
    log.log(AuditSeverity.INFO, "tx.failed", "no", amount=99)
    assert len(log.filter(action="tx.completed")) == 1
    assert len(log.filter(predicate=lambda e: e.metadata.get("amount") == 99)) == 1


def test_file_persistence_one_json_line_per_event(tmp_path):
    path = tmp_path / "audit.log"
    log = AuditLog(file_path=str(path), now=clock)
    log.log(AuditSeverity.INFO, "a", "first", n=1)
    log.log(AuditSeverity.WARNING, "b", "second", n=2)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["action"] == "a"
    assert first["severity"] == "INFO"
    assert first["metadata"]["n"] == 1


def test_export(tmp_path):
    log = AuditLog(now=clock)
    log.log(AuditSeverity.INFO, "a", "x")
    out = tmp_path / "export.log"
    log.export(str(out))
    assert len(out.read_text(encoding="utf-8").strip().splitlines()) == 1
