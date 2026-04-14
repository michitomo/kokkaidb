"""StateManagerの単体テスト"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.state import StateManager


@pytest.fixture
def state_manager(tmp_path: Path) -> StateManager:
    """テンポラリDBを使うStateManager。"""
    db_path = tmp_path / "test_state.db"
    manager = StateManager(db_path=db_path)
    yield manager  # type: ignore[misc]
    manager.close()


def test_register_and_check(state_manager: StateManager) -> None:
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    assert not state_manager.is_processed("shugiin", "56149")  # pendingなのでFalse


def test_update_status_done(state_manager: StateManager) -> None:
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    state_manager.update_status("shugiin", "56149", "done")
    assert state_manager.is_processed("shugiin", "56149")


def test_update_status_error(state_manager: StateManager) -> None:
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    state_manager.update_status("shugiin", "56149", "error", error_msg="Step 3 failed")
    assert not state_manager.is_processed("shugiin", "56149")
    sessions = state_manager.list_sessions()
    assert sessions[0]["status"] == "error"
    assert sessions[0]["error_msg"] == "Step 3 failed"


def test_duplicate_register_ignored(state_manager: StateManager) -> None:
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")  # 重複
    sessions = state_manager.list_sessions()
    assert len(sessions) == 1


def test_pending_sessions_filter(state_manager: StateManager) -> None:
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    state_manager.register_session("sangiin", "1234", "2026-04-09", "法務委員会")
    state_manager.update_status("shugiin", "56149", "done")
    pending = state_manager.get_pending_sessions()
    assert len(pending) == 1
    assert pending[0]["session_id"] == "1234"


def test_log_step(state_manager: StateManager) -> None:
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    state_manager.log_step("shugiin", "56149", "scrape", True, "OK")
    # ログが書き込まれていることを確認（エラーなく完了すればOK）


def test_chamber_filter(state_manager: StateManager) -> None:
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    state_manager.register_session("sangiin", "1234", "2026-04-09", "法務委員会")
    shugiin_only = state_manager.list_sessions(chamber="shugiin")
    assert len(shugiin_only) == 1
    assert shugiin_only[0]["chamber"] == "shugiin"


def test_unknown_session_not_processed(state_manager: StateManager) -> None:
    assert not state_manager.is_processed("shugiin", "99999")


def test_get_pending_sessions_by_chamber(state_manager: StateManager) -> None:
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    state_manager.register_session("sangiin", "1234", "2026-04-09", "法務委員会")
    shugiin_pending = state_manager.get_pending_sessions(chamber="shugiin")
    assert len(shugiin_pending) == 1
    assert shugiin_pending[0]["chamber"] == "shugiin"
