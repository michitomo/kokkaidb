"""publisher.pyの単体テスト"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.publisher import REPO_ROOT, publish_session


@patch("src.publisher._run_git")
def test_publish_session(mock_git: object) -> None:
    """git add, commit, push が正しい引数で呼ばれる。"""
    output_dir = REPO_ROOT / "data" / "shugiin" / "2026" / "04" / "09" / "56149_本会議"
    publish_session(
        output_dir=output_dir,
        chamber="shugiin",
        session_id="56149",
        date="2026-04-09",
        committee="本会議",
    )
    assert mock_git.call_count == 3  # type: ignore[attr-defined]
    # add
    add_call = mock_git.call_args_list[0]  # type: ignore[attr-defined]
    assert add_call[0][0] == "add"
    # commit
    commit_call = mock_git.call_args_list[1]  # type: ignore[attr-defined]
    assert commit_call[0][0] == "commit"
    assert "56149" in commit_call[0][2]
    # push
    push_call = mock_git.call_args_list[2]  # type: ignore[attr-defined]
    assert push_call[0] == ("push", "origin", "main")


@patch("src.publisher._run_git")
def test_commit_message_format(mock_git: object) -> None:
    """コミットメッセージに院名・日付・委員会名・IDが含まれる。"""
    output_dir = REPO_ROOT / "data" / "sangiin" / "2026" / "04" / "09" / "1234_法務委員会"
    publish_session(
        output_dir=output_dir,
        chamber="sangiin",
        session_id="1234",
        date="2026-04-09",
        committee="法務委員会",
    )
    commit_call = mock_git.call_args_list[1]  # type: ignore[attr-defined]
    msg = commit_call[0][2]
    assert "sangiin" in msg
    assert "2026-04-09" in msg
    assert "法務委員会" in msg


@patch("src.publisher._run_git")
def test_publish_adds_relative_path(mock_git: object) -> None:
    """git addに渡すパスがREPO_ROOT相対であること。"""
    output_dir = REPO_ROOT / "data" / "shugiin" / "2026" / "04" / "09" / "56149_本会議"
    publish_session(
        output_dir=output_dir,
        chamber="shugiin",
        session_id="56149",
        date="2026-04-09",
        committee="本会議",
    )
    add_call = mock_git.call_args_list[0]  # type: ignore[attr-defined]
    added_path = add_call[0][1]
    # パスがREPO_ROOTからの相対パスであること（絶対パスでないこと）
    assert not added_path.startswith("/") or "data/shugiin" in added_path


def test_publish_outside_repo_raises() -> None:
    """REPO_ROOT外のディレクトリを指定するとValueErrorが発生する。"""
    with patch("src.publisher._run_git"):
        with pytest.raises(ValueError):
            publish_session(
                output_dir=Path("/tmp/outside_repo"),
                chamber="shugiin",
                session_id="56149",
                date="2026-04-09",
                committee="本会議",
            )
