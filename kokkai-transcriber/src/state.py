"""SQLite状態管理: 処理済みセッションの追跡"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
DEFAULT_DB_PATH = Path(__file__).parent.parent / "state.db"


class StateManager:
    """処理済みセッションのSQLite状態管理。"""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """テーブルが存在しなければ作成する。"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS processed_sessions (
                chamber      TEXT NOT NULL,
                session_id   TEXT NOT NULL,
                date         TEXT NOT NULL,
                committee    TEXT NOT NULL,
                status       TEXT DEFAULT 'pending',
                audio_url    TEXT,
                speaker_count INTEGER,
                processed_at TEXT,
                error_msg    TEXT,
                retry_count  INTEGER DEFAULT 0,
                PRIMARY KEY (chamber, session_id)
            );

            CREATE TABLE IF NOT EXISTS processing_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                chamber      TEXT NOT NULL,
                session_id   TEXT NOT NULL,
                step         TEXT,
                started_at   TEXT,
                finished_at  TEXT,
                success      BOOLEAN,
                detail       TEXT,
                FOREIGN KEY (chamber, session_id)
                    REFERENCES processed_sessions(chamber, session_id)
            );
        """)
        # retry_count カラムの後付けマイグレーション
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(processed_sessions)").fetchall()}
        if "retry_count" not in cols:
            self.conn.execute("ALTER TABLE processed_sessions ADD COLUMN retry_count INTEGER DEFAULT 0")
        self.conn.commit()

    def is_processed(self, chamber: str, session_id: str) -> bool:
        """セッションが処理済み（status='done'）か判定する。"""
        row = self.conn.execute(
            "SELECT status FROM processed_sessions WHERE chamber=? AND session_id=?",
            (chamber, session_id),
        ).fetchone()
        return row is not None and row["status"] == "done"

    def register_session(
        self,
        chamber: str,
        session_id: str,
        date: str,
        committee: str,
    ) -> None:
        """新規セッションをpendingとして登録する。既に存在する場合はスキップ。"""
        self.conn.execute(
            """INSERT OR IGNORE INTO processed_sessions
               (chamber, session_id, date, committee, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (chamber, session_id, date, committee),
        )
        self.conn.commit()

    def update_status(
        self,
        chamber: str,
        session_id: str,
        status: str,
        error_msg: str = "",
    ) -> None:
        """セッションのステータスを更新する。doneの場合はprocessed_atも記録。

        status='pending_retry' の場合は retry_count をインクリメント。
        """
        processed_at = ""
        if status == "done":
            processed_at = datetime.now(JST).isoformat()

        if status == "pending_retry":
            self.conn.execute(
                """UPDATE processed_sessions
                   SET status=?, error_msg=?, retry_count=COALESCE(retry_count, 0) + 1
                   WHERE chamber=? AND session_id=?""",
                (status, error_msg, chamber, session_id),
            )
        else:
            self.conn.execute(
                """UPDATE processed_sessions
                   SET status=?, processed_at=?, error_msg=?
                   WHERE chamber=? AND session_id=?""",
                (status, processed_at, error_msg, chamber, session_id),
            )
        self.conn.commit()

    def get_retry_count(self, chamber: str, session_id: str) -> int:
        """セッションのリトライ回数を返す。"""
        row = self.conn.execute(
            "SELECT retry_count FROM processed_sessions WHERE chamber=? AND session_id=?",
            (chamber, session_id),
        ).fetchone()
        return (row["retry_count"] or 0) if row else 0

    def get_retry_sessions(self, chamber: str | None = None, max_retries: int = 5) -> list[dict]:  # type: ignore[type-arg]
        """pending_retry 状態かつリトライ上限未満のセッションを返す。"""
        if chamber:
            rows = self.conn.execute(
                """SELECT * FROM processed_sessions
                   WHERE status='pending_retry' AND chamber=?
                     AND COALESCE(retry_count, 0) < ?""",
                (chamber, max_retries),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM processed_sessions
                   WHERE status='pending_retry' AND COALESCE(retry_count, 0) < ?""",
                (max_retries,),
            ).fetchall()
        return [dict(r) for r in rows]

    def log_step(
        self,
        chamber: str,
        session_id: str,
        step: str,
        success: bool,
        detail: str = "",
    ) -> None:
        """処理ステップのログを記録する。"""
        now = datetime.now(JST).isoformat()
        self.conn.execute(
            """INSERT INTO processing_log
               (chamber, session_id, step, started_at, finished_at, success, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (chamber, session_id, step, now, now, success, detail),
        )
        self.conn.commit()

    def get_pending_sessions(self, chamber: str | None = None) -> list[dict]:  # type: ignore[type-arg]
        """未処理セッションの一覧を返す。chamberがNoneなら全院。"""
        if chamber:
            rows = self.conn.execute(
                "SELECT * FROM processed_sessions WHERE status='pending' AND chamber=?",
                (chamber,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM processed_sessions WHERE status='pending'"
            ).fetchall()
        return [dict(r) for r in rows]

    def list_sessions(self, chamber: str | None = None) -> list[dict]:  # type: ignore[type-arg]
        """全セッション一覧を返す（CLIの状態確認用）。"""
        if chamber:
            rows = self.conn.execute(
                "SELECT * FROM processed_sessions WHERE chamber=? ORDER BY date DESC",
                (chamber,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM processed_sessions ORDER BY date DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self.conn.close()
