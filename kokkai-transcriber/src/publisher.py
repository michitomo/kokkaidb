"""git auto-push: 処理済みJSONをgit commit + pushしてCI/CDをトリガーする"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# リポジトリルート（kokkai-transcriber/ の1つ上）
REPO_ROOT = Path(__file__).parent.parent.parent


def publish_session(
    output_dir: Path,
    chamber: str,
    session_id: str,
    date: str,
    committee: str,
) -> None:
    """処理済みJSONをgit commit + pushする。

    Args:
        output_dir: JSONファイルが格納されたディレクトリ
            例: data/shugiin/2026/04/09/56149_本会議/
        chamber: "shugiin" | "sangiin"
        session_id: セッションID
        date: セッション日付（YYYY-MM-DD）
        committee: 委員会名

    Raises:
        subprocess.CalledProcessError: gitコマンドが失敗した場合
        ValueError: output_dirがREPO_ROOT配下にない場合
    """
    # output_dir がREPO_ROOT配下であることを確認
    relative = output_dir.resolve().relative_to(REPO_ROOT.resolve())

    _run_git("add", str(relative))

    commit_msg = f"data: {chamber} {date} {committee} ({session_id})"
    _run_git("commit", "-m", commit_msg)

    _run_git("push", "origin", "main")

    logger.info("Published: %s", commit_msg)


def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
    """gitコマンドをREPO_ROOTで実行する。"""
    cmd = ["git", "-C", str(REPO_ROOT), *args]
    logger.debug("Running: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
