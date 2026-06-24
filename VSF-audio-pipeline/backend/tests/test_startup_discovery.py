from __future__ import annotations

import importlib
import sys


def _load_main(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    sys.modules.pop("app.main", None)
    sys.modules.pop("app.db.session", None)
    return importlib.import_module("app.main")


def test_trigger_startup_discovery_when_enabled(monkeypatch):
    main = _load_main(monkeypatch)
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(main.settings, "discovery_enabled", True)
    monkeypatch.setattr(
        main,
        "start_discovery_cycle",
        lambda **kwargs: calls.append(kwargs),
    )

    main._trigger_startup_discovery()

    assert calls == [
        {
            "trigger": "startup_idle",
            "completed_job_id": None,
            "completed_batch_name": None,
        }
    ]


def test_trigger_startup_discovery_skips_when_disabled(monkeypatch):
    main = _load_main(monkeypatch)
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(main.settings, "discovery_enabled", False)
    monkeypatch.setattr(
        main,
        "start_discovery_cycle",
        lambda **kwargs: calls.append(kwargs),
    )

    main._trigger_startup_discovery()

    assert calls == []
