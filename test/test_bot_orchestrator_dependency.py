from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException

from deps import get_bots_orchestrator


def _request_with_bots_orchestrator(service):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(bots_orchestrator=service)
        )
    )


def test_bot_orchestrator_dependency_returns_configured_service():
    service = object()

    assert get_bots_orchestrator(
        _request_with_bots_orchestrator(service)
    ) is service


def test_bot_orchestrator_dependency_returns_503_when_disabled():
    with pytest.raises(HTTPException) as exc_info:
        get_bots_orchestrator(_request_with_bots_orchestrator(None))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Bot orchestration is disabled in Spectra paper-only mode."
    )


def test_bot_orchestrator_dependency_returns_503_when_state_is_missing():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(HTTPException) as exc_info:
        get_bots_orchestrator(request)

    assert exc_info.value.status_code == 503
