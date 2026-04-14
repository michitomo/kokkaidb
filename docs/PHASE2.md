# Phase 2: Docker化 + サイト基盤 + Scraper抽象化 — 実装・テスト計画

> **目標**: Phase 1で確定したパイプラインをDocker化し、衆議院の自動巡回を実現する。同時にAstro静的サイトの基盤を構築し、`data/` pushからGitHub Pages自動デプロイまでのCI/CDパイプラインを完成させる。
> **所要期間**: 2-3日
> **前提**: Phase 1が完了しており、`data/shugiin/2026/04/09/56149_本会議/` 配下に6つのJSONが正常に生成されていること。

---

## Phase 1での確認事項（Phase 2開始前に把握すること）

Phase 1（deli_id=56149、2026-04-09本会議）の実装・実行から得られた知見。Phase 2での実装時に考慮すること。

### 確定した実装詳細

**shugiintv.go.jpのパーシング**（`src/scrapers/shugiin.py`に実装済み）:
- HLS URL: `vtag_src_base_vod` の value が `http://` で返るが実際は `https://`。`value.replace("http://", "https://", 1)` で正規化必須
- 非発言者リンク除外: 「はじめから再生」「先頭から再生」「全体再生」は `_NON_SPEAKER_TEXTS` セットでフィルタ済み
- 日付フォーマット: 西暦年 `(\d{4})年(\d+)月(\d+)日` を使用（令和年号ではなく西暦で返される）
- 開始時刻フォーマット: `(\d{1,2})時\s*(\d{2})分` → `HH:MM` に変換
- 委員会名: `<title>` タグから先に抽出し、本文が「本会議」なら直接使用

**並列化パターン**（Step 1リファクタ後も維持すること）:
- Whisper文字起こし（Step 4）: `ThreadPoolExecutor(max_workers=16)` + `as_completed` + `segment_index`でソート
- LLM話者タグ付け（Step 5）: 同上。9セグメント並列で約5分
- 要約・トピック生成（Step 6）: `ThreadPoolExecutor(max_workers=2)` で `generate_summary` と `generate_topics` を並列実行

**依存関係・ビルド設定**:
- ビルドバックエンド: `setuptools.build_meta`（`setuptools.backends.legacy:build` はPython 3.14で存在しない）
- `python-dotenv>=1.0` がランタイム依存に必要（`.env` 読み込みのため）
- `pyproject.toml` に `eval` オプショナル依存グループ（`pyyaml>=6.0`）あり
- テスト: `tests/conftest.py` で `load_dotenv()` を最初に呼ぶことで統合テストが `.env` を読める

**メタデータ**:
- `metadata.duration` は空文字列のまま（実際のページにトータル時間の表示がない）。許容範囲

### 実際のパイプライン実行時間（deli_id=56149、約2時間のセッション、9セグメント）

| ステップ | 時間 |
|---------|------|
| Step 3: HLS音声ダウンロード + セグメント分割 | 約4分 |
| Step 4: Whisper文字起こし（16並列） | 約2分 |
| Step 5: LLM話者タグ付け（16並列） | 約5分 |
| Step 6: Q&Aペア生成 + 要約・トピック（並列） | 約1分 |
| **合計** | **約12分** |

### 既知の問題（Phase 2以降で対応）

| 問題 | 原因 | 対応フェーズ |
|------|------|------------|
| Whisperが答弁者の固有名詞を誤認識（例: 「高市早苗」→「高池晃」） | Whisperプロンプトに発言者名としてスクレイパー検出の質問者しか渡していない。答弁者（大臣等）が含まれない | Phase 3以降でプロンプト改善 |
| Q&Aペア数が少ない（9セグメントで3ペアのみ） | `structurer.py` がセッション全体を1コンテキストとして扱い、関係性の薄いQ&Aを生成しない | Phase 3以降でプロンプト調整 |
| `metadata.duration` が空 | 実ページに総時間要素がない | 低優先度。許容範囲 |

### Step 1リファクタ時の注意点

`src/scrapers/shugiin.py` を関数からクラスへリファクタする際、以下の修正済みロジックを必ず保持すること:
- `http://` → `https://` のHLS URL正規化
- `_NON_SPEAKER_TEXTS` による非発言者フィルタ
- 西暦年日付パーシング
- `(\d{1,2})時\s*(\d{2})分` の時刻パーシング

既存のユニットテスト（`tests/test_shugiin_scraper.py`）がこれらのロジックをカバーしているので、リファクタ後も全テストがパスすることを確認すること。

---

## 成果物

Phase 2 完了時に以下が揃う:

1. `BaseScraper` ABCと`ShugiinScraper`クラス（Phase 1の関数群をクラスに再編）
2. `Dockerfile` + `docker-compose.yml`（パイプライン実行環境）
3. `state.py`（SQLite状態管理）+ `publisher.py`（git auto-push）
4. `site/` 配下にAstroプロジェクト一式（セッション一覧、個別ページ、Q&Aカード、Pagefind検索）
5. `.github/workflows/build-deploy.yml`（data/ push → Astro build → GitHub Pagesデプロイ）
6. 全ステップのテスト

---

## 全体の作業順序

```
Step 1: BaseScraper ABC + ShugiinScraperリファクタ   ← Python側、テスト既存
Step 2: SQLite状態管理 (state.py)                    ← Python側、新規
Step 3: git auto-push (publisher.py)                 ← Python側、新規
Step 4: pipelineの更新（状態管理 + auto-push統合）     ← Python側、既存改修
Step 5: Dockerfile + docker-compose.yml              ← インフラ、新規
Step 6: Astroプロジェクトセットアップ                   ← フロント側、新規
Step 7: データ読み込み + 静的APIエンドポイント生成        ← フロント側、新規
Step 8: ページ実装（一覧・詳細・Q&Aカード）             ← フロント側、新規
Step 9: Pagefind統合                                  ← フロント側、新規
Step 10: GitHub Actions CI/CD                        ← インフラ、新規
Step 11: 結合テスト（Docker → data/ push → サイトビルド → デプロイ）
```

依存関係:
- Step 1 → Step 4（Scraper ABCがpipelineに必要）
- Step 2 → Step 4（状態管理がpipelineに必要）
- Step 3 → Step 4（publisherがpipelineに必要）
- Step 6 → Step 7 → Step 8 → Step 9（Astroは順番に構築）
- Step 5 はStep 4完了後に着手
- Step 10 はStep 9完了後に着手
- Step 1-3 は並行作業可能
- Step 6-9 はStep 1-5 と並行作業可能（data/のJSONが手元にあればOK）

---

## Step 1: BaseScraper ABC + ShugiinScraperリファクタ

### 目的

Phase 1の`shugiin.py`はモジュールレベル関数で実装されている。Phase 3で参議院対応する際に同じインターフェースを使えるよう、`BaseScraper` ABCを定義し、`ShugiinScraper`クラスとして再編する。

**注意**: リファクタ時に「Phase 1での確認事項 → Step 1リファクタ時の注意点」を参照し、修正済みパーシングロジックを必ず保持すること。

### やること

#### 1-1. `src/scrapers/base.py` を新規作成

```python
from abc import ABC, abstractmethod
from src.models import SessionDetail


class BaseScraper(ABC):
    """両院共通のScraperインターフェース。

    各院のScraper実装はこの3メソッドを実装する。
    エンコーディング処理など院固有の差異は各実装に閉じ込める。
    """

    chamber: str  # "shugiin" | "sangiin"

    @abstractmethod
    def detect_new_sessions(self, date: str) -> list[str]:
        """指定日（YYYY-MM-DD）の新規セッションIDリストを返す。

        Args:
            date: 検索対象日（YYYY-MM-DD形式）

        Returns:
            セッションIDの文字列リスト（衆議院ならdeli_id、参議院ならsid）
        """
        ...

    @abstractmethod
    def get_session_detail(self, session_id: str) -> SessionDetail:
        """セッション詳細（メタデータ + 発言者リスト）を返す。

        Args:
            session_id: 院固有のセッションID

        Returns:
            SessionDetail Pydanticモデル
        """
        ...

    @abstractmethod
    def get_audio_url(self, session_id: str) -> str:
        """音声ストリームURLを返す。

        Args:
            session_id: 院固有のセッションID

        Returns:
            HLS URLまたはストリームURL文字列
        """
        ...
```

**重要**: このABCの3メソッドシグネチャは変更しない（CLAUDE.md記載の規約）。

#### 1-2. `src/scrapers/shugiin.py` をクラスベースにリファクタ

- 既存の `get_session_detail()` 関数 → `ShugiinScraper.get_session_detail()` メソッドに移行
- `detect_new_sessions(date)` を新規実装:
  - `index.php?ex=VL&u_day=YYYYMMDD` をGETリクエスト
  - レスポンスHTML内の `deli_id=` パラメータを正規表現で全抽出
  - 抽出した`deli_id`のリストを返す
- `get_audio_url(session_id)` を新規実装:
  - `get_session_detail(session_id)` を呼んで `hls_url` を返す
  - **注意**: 内部で`get_session_detail`を呼ぶと2回フェッチになるので、キャッシュまたは`hls_url`直接抽出の軽量版を実装する
- 既存のプライベート関数群（`_extract_hls_url`, `_extract_speakers` 等）はメソッドに移行するかそのまま残す（モジュール内のヘルパーとして使う分にはどちらでもOK）

```python
class ShugiinScraper(BaseScraper):
    chamber = "shugiin"

    def detect_new_sessions(self, date: str) -> list[str]:
        """カレンダーGETで指定日のdeli_idリストを返す。"""
        # date "2026-04-09" → u_day "20260409"
        u_day = date.replace("-", "")
        url = f"{BASE_URL}?{urlencode({'ex': 'VL', 'u_day': u_day})}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = "euc-jp"
        # deli_id= パラメータを全抽出
        return list(set(re.findall(r"deli_id=(\d+)", response.text)))

    def get_session_detail(self, session_id: str) -> SessionDetail:
        # Phase 1の既存実装をそのまま移行
        ...

    def get_audio_url(self, session_id: str) -> str:
        # 軽量版: 詳細ページのHTMLから hls_url のみ抽出
        ...
```

#### 1-3. `src/scrapers/__init__.py` を更新

```python
from src.scrapers.base import BaseScraper
from src.scrapers.shugiin import ShugiinScraper

__all__ = ["BaseScraper", "ShugiinScraper"]
```

### テスト

**ファイル**: `tests/test_shugiin_scraper.py`（既存テストをクラスベースに更新）

```python
# 更新が必要なテスト:
# - get_session_detail → ShugiinScraper().get_session_detail() に変更
# - detect_new_sessions の新規テスト追加（HTMLフィクスチャ使用）

def test_detect_new_sessions(mock_requests):
    """u_day GETのレスポンスからdeli_idリストを抽出する。"""
    scraper = ShugiinScraper()
    ids = scraper.detect_new_sessions("2026-04-09")
    assert "56149" in ids
    assert all(id.isdigit() for id in ids)

def test_get_audio_url(mock_requests):
    """session_idからHLS URLを取得する。"""
    scraper = ShugiinScraper()
    url = scraper.get_audio_url("56149")
    assert "hlsvod.shugiintv.go.jp" in url
```

**新規フィクスチャ**: `tests/fixtures/shugiin_calendar_20260409.html`
- `index.php?ex=VL&u_day=20260409` のレスポンスHTMLを保存

### 完了条件

- [ ] `BaseScraper` ABCが `src/scrapers/base.py` に定義されている
- [ ] `ShugiinScraper` が3メソッド全て実装している
- [ ] 既存テストがクラスベースに更新されてパスする
- [ ] `detect_new_sessions` と `get_audio_url` の新規テストがパスする
- [ ] `ruff check src/scrapers/` と `mypy src/scrapers/` がエラーなし

---

## Step 2: SQLite状態管理 (`state.py`)

### 目的

処理済みセッションを記録し、重複処理を防ぐ。両院統合で `chamber + session_id` 複合PKを使用する。

### やること

#### 2-1. `src/state.py` を新規作成

```python
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
DEFAULT_DB_PATH = Path(__file__).parent.parent / "state.db"


class StateManager:
    """処理済みセッションのSQLite状態管理。"""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
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
        """セッションのステータスを更新する。doneの場合はprocessed_atも記録。"""
        processed_at = ""
        if status == "done":
            processed_at = datetime.now(JST).isoformat()
        self.conn.execute(
            """UPDATE processed_sessions
               SET status=?, processed_at=?, error_msg=?
               WHERE chamber=? AND session_id=?""",
            (status, processed_at, error_msg, chamber, session_id),
        )
        self.conn.commit()

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

    def get_pending_sessions(self, chamber: str | None = None) -> list[dict]:
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

    def list_sessions(self, chamber: str | None = None) -> list[dict]:
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
```

### テスト

**ファイル**: `tests/test_state.py`（新規）

```python
import pytest
from pathlib import Path
from src.state import StateManager


@pytest.fixture
def state_manager(tmp_path):
    """テンポラリDBを使うStateManager。"""
    db_path = tmp_path / "test_state.db"
    manager = StateManager(db_path=db_path)
    yield manager
    manager.close()


def test_register_and_check(state_manager):
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    assert not state_manager.is_processed("shugiin", "56149")  # pendingなのでFalse


def test_update_status_done(state_manager):
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    state_manager.update_status("shugiin", "56149", "done")
    assert state_manager.is_processed("shugiin", "56149")


def test_duplicate_register_ignored(state_manager):
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")  # 重複
    sessions = state_manager.list_sessions()
    assert len(sessions) == 1


def test_pending_sessions_filter(state_manager):
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    state_manager.register_session("sangiin", "1234", "2026-04-09", "法務委員会")
    state_manager.update_status("shugiin", "56149", "done")
    pending = state_manager.get_pending_sessions()
    assert len(pending) == 1
    assert pending[0]["session_id"] == "1234"


def test_log_step(state_manager):
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    state_manager.log_step("shugiin", "56149", "scrape", True, "OK")
    # ログが書き込まれていることを確認（エラーなく完了すればOK）


def test_chamber_filter(state_manager):
    state_manager.register_session("shugiin", "56149", "2026-04-09", "本会議")
    state_manager.register_session("sangiin", "1234", "2026-04-09", "法務委員会")
    shugiin_only = state_manager.list_sessions(chamber="shugiin")
    assert len(shugiin_only) == 1
    assert shugiin_only[0]["chamber"] == "shugiin"
```

### 完了条件

- [ ] `src/state.py` に `StateManager` クラスが実装されている
- [ ] 上記テストケースがすべてパスする
- [ ] `state.db` が `.gitignore` に含まれている（未作成の場合は追加）
- [ ] `ruff check src/state.py` と `mypy src/state.py` がエラーなし

---

## Step 3: git auto-push (`publisher.py`)

### 目的

処理済みJSONを `data/` ディレクトリにコミット・プッシュし、GitHub Actions CI/CDをトリガーする。

### やること

#### 3-1. `src/publisher.py` を新規作成

```python
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
    """
    # output_dir がREPO_ROOT配下であることを確認
    relative = output_dir.resolve().relative_to(REPO_ROOT.resolve())

    _run_git("add", str(relative))

    commit_msg = f"data: {chamber} {date} {committee} ({session_id})"
    _run_git("commit", "-m", commit_msg)

    _run_git("push", "origin", "main")

    logger.info("Published: %s", commit_msg)


def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
    """gitコマンドを実行する。"""
    cmd = ["git", "-C", str(REPO_ROOT), *args]
    logger.debug("Running: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
```

**設計上の注意点:**
- `REPO_ROOT` は `kokkai-transcriber/src/publisher.py` から見て `../../`（リポジトリルート）
- Docker内で実行する場合、gitの認証情報（SSHキーまたはトークン）がコンテナ内で使える必要がある → Step 5で対応
- `git push` はリモートブランチ `main` にプッシュする

### テスト

**ファイル**: `tests/test_publisher.py`（新規）

```python
import pytest
from unittest.mock import patch, call
from pathlib import Path
from src.publisher import publish_session, REPO_ROOT


@patch("src.publisher._run_git")
def test_publish_session(mock_git, tmp_path):
    """git add, commit, push が正しい引数で呼ばれる。"""
    output_dir = REPO_ROOT / "data" / "shugiin" / "2026" / "04" / "09" / "56149_本会議"
    publish_session(
        output_dir=output_dir,
        chamber="shugiin",
        session_id="56149",
        date="2026-04-09",
        committee="本会議",
    )
    assert mock_git.call_count == 3
    # add
    add_call = mock_git.call_args_list[0]
    assert add_call[0][0] == "add"
    # commit
    commit_call = mock_git.call_args_list[1]
    assert commit_call[0][0] == "commit"
    assert "56149" in commit_call[0][2]
    # push
    push_call = mock_git.call_args_list[2]
    assert push_call[0] == ("push", "origin", "main")


@patch("src.publisher._run_git")
def test_commit_message_format(mock_git):
    """コミットメッセージに院名・日付・委員会名・IDが含まれる。"""
    output_dir = REPO_ROOT / "data" / "sangiin" / "2026" / "04" / "09" / "1234_法務委員会"
    publish_session(
        output_dir=output_dir,
        chamber="sangiin",
        session_id="1234",
        date="2026-04-09",
        committee="法務委員会",
    )
    commit_call = mock_git.call_args_list[1]
    msg = commit_call[0][2]
    assert "sangiin" in msg
    assert "2026-04-09" in msg
    assert "法務委員会" in msg
```

### 完了条件

- [ ] `src/publisher.py` に `publish_session()` が実装されている
- [ ] `_run_git` のモックテストがパスする
- [ ] `ruff check src/publisher.py` と `mypy src/publisher.py` がエラーなし

---

## Step 4: パイプラインの更新

### 目的

Phase 1のパイプラインを更新して、Step 1-3で作ったScraper ABC・状態管理・auto-pushを統合する。CLIに `--chamber` オプションを追加し、日付指定での自動巡回モードを追加する。

### やること

#### 4-1. `src/pipeline.py` を更新

既存の`pipeline.py`に以下を追加・変更する:

**変更点:**
- `ShugiinScraper` クラスのインスタンスを使うように変更（関数直接呼び出しから移行）
- `StateManager` を組み込み、処理開始時に `register_session` + `update_status("processing")`、完了時に`update_status("done")`、失敗時に`update_status("error")`
- 各ステップを `StateManager.log_step()` で記録
- `publisher.publish_session()` をパイプライン最後に呼び出す（`--no-push` フラグで無効化可能）

**CLI引数の更新:**
```
# Phase 1（既存、後方互換）
python -m src.pipeline --deli-id 56149 --output-dir data/shugiin/...

# Phase 2（新規: 自動巡回モード）
python -m src.pipeline --chamber shugiin --date 2026-04-09

# Phase 2（新規: 全未処理セッションの処理）
python -m src.pipeline --chamber shugiin --process-pending

# 共通オプション
--no-push     git pushを無効化（ローカルテスト用）
--db-path     SQLite DBのパスを指定（デフォルト: state.db）
```

**自動巡回モードの処理フロー:**
```
1. ShugiinScraper().detect_new_sessions(date) でセッションIDリストを取得
2. StateManager で未処理のものをフィルタ
3. 各セッションに対してパイプライン実行（scrape → audio → whisper → tag → structure）
4. 成功したらpublish_session() でgit push
5. StateManagerのステータスを更新
```

### テスト

**ファイル**: `tests/test_pipeline.py`（既存テストを更新）

追加するテスト:
```python
def test_pipeline_with_state_manager():
    """パイプライン実行後にStateManagerのステータスがdoneになる。"""

def test_pipeline_skips_processed():
    """処理済みセッションはスキップされる。"""

def test_pipeline_auto_discovery():
    """--date指定で新規セッションを自動検出して処理する。"""

def test_pipeline_error_records_in_state():
    """途中エラー時にStateManagerにerrorステータスが記録される。"""

def test_pipeline_no_push_flag():
    """--no-push時にpublish_sessionが呼ばれない。"""
```

### 完了条件

- [ ] `python -m src.pipeline --chamber shugiin --date 2026-04-09 --no-push` が動作する
- [ ] StateManagerと連携してステータス管理が機能する
- [ ] `--no-push` フラグでgit pushをスキップできる
- [ ] 既存の `--deli-id` オプションが引き続き動作する（後方互換）
- [ ] テストがパスする

---

## Step 5: Dockerfile + docker-compose.yml

### 目的

パイプラインをDocker化し、cron/launchd で定時実行できるようにする。

### やること

#### 5-1. `kokkai-transcriber/Dockerfile`

**注意**: `pyproject.toml` のビルドバックエンドは `setuptools.build_meta` を使用すること（Phase 1で `setuptools.backends.legacy:build` はPython 3.14で存在しないことが判明）。ローカル開発環境がPython 3.14の場合にDockerで3.12を使う際も同様。

```dockerfile
FROM python:3.12-slim

# ffmpegをインストール
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存関係インストール
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# ソースコードをコピー
COPY src/ src/

# リポジトリルートをマウントするための作業ディレクトリ
# docker-compose.yml で volumes 指定
WORKDIR /repo
```

**重要事項:**
- `ffmpeg` と `git` をコンテナ内にインストール
- `/repo` にリポジトリルートをマウントし、`publisher.py`がgit操作できるようにする
- `.env` はdocker-compose.ymlの `env_file` で注入

#### 5-2. `kokkai-transcriber/docker-compose.yml`

```yaml
services:
  transcriber:
    build:
      context: .
      dockerfile: Dockerfile
    env_file:
      - .env
    volumes:
      # リポジトリルート全体をマウント（git操作のため）
      - ..:/repo
      # state.dbを永続化
      - ./state.db:/app/state.db
    working_dir: /repo/kokkai-transcriber
    # デフォルトコマンド: 当日の衆議院セッションを処理
    command: >
      python -m src.pipeline
      --chamber shugiin
      --date today
      --db-path /app/state.db
```

#### 5-3. cron/launchd設定の手順書

Docker内にcronを入れず、ホスト側のcron/launchdから `docker compose run` を呼ぶ方式を採用する。

**cron例（Mac/Linux）:**
```bash
# crontab -e
# 毎日10:00と18:00に実行（衆議院のアーカイブは当日中に公開されるため）
0 10,18 * * * cd /path/to/kokkaidb && docker compose -f kokkai-transcriber/docker-compose.yml run --rm transcriber
```

**launchd例（Mac推奨）:**
`~/Library/LaunchAgents/com.kokkaidb.transcriber.plist` を作成する。

### テスト

```bash
# Dockerイメージのビルドが成功する
docker compose -f kokkai-transcriber/docker-compose.yml build

# コンテナ内でpythonとffmpegが使える
docker compose -f kokkai-transcriber/docker-compose.yml run --rm transcriber python --version
docker compose -f kokkai-transcriber/docker-compose.yml run --rm transcriber ffmpeg -version

# --no-push でローカルテスト（APIキー不要のdryrunは別途検討）
docker compose -f kokkai-transcriber/docker-compose.yml run --rm transcriber \
  python -m src.pipeline --chamber shugiin --deli-id 56149 --no-push
```

### 完了条件

- [ ] `docker compose build` が成功する
- [ ] コンテナ内で `python`, `ffmpeg`, `git` が利用可能
- [ ] `.env` の `DEEPINFRA_API_KEY` がコンテナ内で読める
- [ ] volumes マウントが正しく動作する（`data/`への書き込みがホスト側に反映）
- [ ] cron/launchd設定手順が文書化されている

---

## Step 6: Astroプロジェクトセットアップ

### 目的

`site/` 配下にAstro 5.xプロジェクトを作成し、基本設定を行う。

### やること

#### 6-1. Astroプロジェクト初期化

```bash
cd site
npm create astro@latest -- --template minimal --yes
```

#### 6-2. 依存関係インストール

```bash
npm install @astrojs/react react react-dom
npm install recharts                          # Phase 5で使うが先に入れてOK
npm install -D @types/react @types/react-dom
```

#### 6-3. `astro.config.mjs`

```javascript
import { defineConfig } from 'astro/config';
import react from '@astrojs/react';

export default defineConfig({
  site: 'https://<username>.github.io',
  base: '/kokkaidb',
  output: 'static',                           // SSRなし（CLAUDE.md規約）
  integrations: [react()],
});
```

**注意:**
- `output: 'static'` を必ず指定（SSR禁止、CLAUDE.md記載）
- `base` はGitHub Pagesのリポジトリ名に合わせる
- `site` はデプロイ時のベースURL

#### 6-4. ディレクトリ構造

```
site/
├── astro.config.mjs
├── package.json
├── tsconfig.json
├── src/
│   ├── layouts/
│   │   └── BaseLayout.astro       # 共通レイアウト（<html>, <head>, ナビゲーション）
│   ├── pages/
│   │   ├── index.astro            # トップ: 最新セッション一覧
│   │   ├── browse.astro           # フィルタ付き一覧（Phase 4でフィルタ実装、まずは一覧のみ）
│   │   ├── search.astro           # Pagefind検索ページ
│   │   ├── [chamber]/[year]/[month]/[day]/[slug].astro  # セッション詳細
│   │   └── settings.astro         # 設定ページ（Phase 6用プレースホルダ）
│   ├── components/
│   │   └── QAPairCard.astro       # Q&A対比カード
│   └── lib/
│       └── data.ts                # data/ JSONの読み込みユーティリティ
└── public/
    └── api/                       # ビルド時生成JSON（Step 7で作成）
```

#### 6-5. `src/layouts/BaseLayout.astro`

最低限のHTML構造:
- `<html lang="ja">`
- `<head>`: charset, viewport, title, 基本CSS（system font stack）
- `<body>`: ナビゲーション（トップ / 一覧 / 検索）、`<slot />`
- フッター: 「出所: 衆議院インターネット審議中継 / 参議院インターネット審議中継」（著作権法第48条対応、CLAUDE.md記載の出所明示要件）

**CSSについて:**
- Phase 2では最小限のCSS（system font stack + 基本レイアウト）で十分
- CSSフレームワークの導入は任意（Tailwindを使うなら `@astrojs/tailwind` を追加）
- レスポンシブ対応は最低限（viewport meta + max-width制約）

### テスト

```bash
cd site
npm run dev    # localhost:4321 でエラーなく起動
npm run build  # dist/ が生成される
```

### 完了条件

- [ ] `npm run dev` が正常に起動する
- [ ] `npm run build` が正常に完了する
- [ ] `output: 'static'` が設定されている
- [ ] BaseLayoutにナビゲーションと出所明示フッターがある
- [ ] React integrationが有効

---

## Step 7: データ読み込み + 静的APIエンドポイント生成

### 目的

`data/` 配下のJSONをAstroのビルド時に読み込み、ページ生成とAPI用JSONファイル出力に使えるようにする。

### やること

#### 7-1. `src/lib/data.ts` — データ読み込みユーティリティ

```typescript
import fs from 'node:fs';
import path from 'node:path';
import { glob } from 'glob';  // または fs.readdirSync + 再帰

// data/ ディレクトリのパス（site/ の1つ上）
const DATA_DIR = path.resolve(import.meta.dirname, '../../../data');

export interface SessionMetadata {
  chamber: string;
  session_id: string;
  date: string;
  committee: string;
  duration: string;
  source_url: string;
  speakers: SpeakerInfo[];
  // ...metadata.json の全フィールド
}

export interface SpeakerInfo {
  name: string;
  affiliation: string;
  role: string;
  start_seconds: number;
  start_time: string;
  duration_minutes: number;
}

// ...他の型定義（QAPair, Summary, Topic等 — ARCH.md 4.4に対応）

/**
 * 全セッションのメタデータを読み込む（日付降順）。
 */
export function getAllSessions(): SessionMetadata[] {
  const metadataFiles = glob.sync('**/metadata.json', { cwd: DATA_DIR });
  const sessions = metadataFiles.map(file => {
    const content = fs.readFileSync(path.join(DATA_DIR, file), 'utf-8');
    return JSON.parse(content) as SessionMetadata;
  });
  return sessions.sort((a, b) => b.date.localeCompare(a.date));
}

/**
 * 特定セッションのデータを全て読み込む。
 */
export function getSessionData(chamber: string, year: string, month: string, day: string, slug: string) {
  const dir = path.join(DATA_DIR, chamber, year, month, day, slug);
  return {
    metadata: readJson<SessionMetadata>(path.join(dir, 'metadata.json')),
    utterances: readJson(path.join(dir, 'utterances.json')),
    qaPairs: readJson(path.join(dir, 'qa_pairs.json')),
    summary: readJson(path.join(dir, 'summary.json')),
    topics: readJson(path.join(dir, 'topics.json')),
  };
}

function readJson<T = unknown>(filePath: string): T {
  return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
}
```

#### 7-2. 静的APIエンドポイント生成

Astroの `src/pages/api/` に `.json.ts` ファイルを配置して、ビルド時にJSONファイルを生成する。

**`src/pages/api/index.json.ts`** — 全セッション一覧:
```typescript
import type { APIRoute } from 'astro';
import { getAllSessions } from '../../lib/data';

export const GET: APIRoute = () => {
  const sessions = getAllSessions().map(s => ({
    chamber: s.chamber,
    session_id: s.session_id,
    date: s.date,
    committee: s.committee,
    duration: s.duration,
    speaker_count: s.speakers.length,
    source_url: s.source_url,
  }));
  return new Response(JSON.stringify(sessions), {
    headers: { 'Content-Type': 'application/json' },
  });
};
```

**`src/pages/api/speakers.json.ts`** — 発言者一覧（全セッション横断）

**`src/pages/api/topics.json.ts`** — トピック一覧（全セッション横断）

### テスト

```bash
# data/ に Phase 1 の出力JSONがある状態で
cd site
npm run build
# dist/api/index.json が生成されていることを確認
cat dist/api/index.json | python -m json.tool
```

### 完了条件

- [ ] `data.ts` が `data/` 配下の全JSONを読み込める
- [ ] `npm run build` で `dist/api/index.json` が生成される
- [ ] 生成されたJSONが正しいフォーマットである
- [ ] `data/` が空の場合でもビルドが失敗しない（空配列を返す）

---

## Step 8: ページ実装

### 目的

セッション一覧、個別セッション詳細、Q&Aカードの3つの主要ページを実装する。

### やること

#### 8-1. `src/pages/index.astro` — トップページ（最新セッション一覧）

- `getAllSessions()` で全セッション取得（日付降順）
- 最新10件を表示
- 各セッションのカード: 日付、院（衆/参ラベル）、委員会名、発言者数、リンク
- 「全件を見る」リンク → `/browse`

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import { getAllSessions } from '../lib/data';

const sessions = getAllSessions().slice(0, 10);
---
<BaseLayout title="国会議事録リアルタイムDB">
  <h1>最新の審議</h1>
  <ul>
    {sessions.map(s => (
      <li>
        <a href={`/${s.chamber}/${s.date.replace(/-/g, '/')}/${s.session_id}_${s.committee}`}>
          <span class="chamber-badge">{s.chamber === 'shugiin' ? '衆' : '参'}</span>
          <span class="date">{s.date}</span>
          <span class="committee">{s.committee}</span>
          <span class="speakers">{s.speakers.length}名</span>
        </a>
      </li>
    ))}
  </ul>
  <a href="/browse">全件を見る</a>
</BaseLayout>
```

#### 8-2. `src/pages/browse.astro` — セッション一覧

- 全セッション一覧を日付降順で表示
- Phase 2ではフィルタなし（フィルタはPhase 4）
- ページネーションは不要（データ量が少ないうちは全件表示）

#### 8-3. `src/pages/[chamber]/[year]/[month]/[day]/[slug].astro` — セッション詳細

動的ルーティングで個別セッションページを生成する。

```astro
---
import BaseLayout from '../../../../../layouts/BaseLayout.astro';
import QAPairCard from '../../../../../components/QAPairCard.astro';
import { getAllSessions, getSessionData } from '../../../../../lib/data';

export function getStaticPaths() {
  const sessions = getAllSessions();
  return sessions.map(s => {
    const [year, month, day] = s.date.split('-');
    const slug = `${s.session_id}_${s.committee}`;
    return {
      params: { chamber: s.chamber, year, month, day, slug },
    };
  });
}

const { chamber, year, month, day, slug } = Astro.params;
const data = getSessionData(chamber!, year!, month!, day!, slug!);
const { metadata, qaPairs, summary } = data;
---
<BaseLayout title={`${metadata.committee} - ${metadata.date}`}>
  <!-- 出所リンク（著作権法第48条） -->
  <p>
    出所:
    <a href={metadata.source_url} target="_blank" rel="noopener">
      {metadata.chamber === 'shugiin' ? '衆議院インターネット審議中継' : '参議院インターネット審議中継'}
    </a>
  </p>

  <!-- セッション概要 -->
  <h1>{metadata.committee}（{metadata.date}）</h1>
  <p>{summary.session_summary}</p>

  <!-- 発言者一覧 -->
  <h2>発言者</h2>
  <ul>
    {metadata.speakers.map(s => (
      <li>{s.name}（{s.affiliation}）— {s.start_time} / {s.duration_minutes}分</li>
    ))}
  </ul>

  <!-- Q&Aペア -->
  <h2>質疑応答</h2>
  {qaPairs.pairs.map(pair => (
    <QAPairCard pair={pair} />
  ))}
</BaseLayout>
```

#### 8-4. `src/components/QAPairCard.astro` — Q&A対比カード

ARCH.md 6.2の設計に基づく:
- 質問（左）と答弁（右）を並列表示（CSS Grid / Flexbox）
- 答弁の回避度インジケータ（`evasion_score` を色で表示: 緑=0〜赤=1）
- 動画リンク（`video_url`）
- トピック表示

```astro
---
// Props型はARCH.md 4.4のQAPairに対応
const { pair } = Astro.props;
const evasionColor = pair.answer.evasion_score < 0.3 ? 'green'
  : pair.answer.evasion_score < 0.7 ? 'orange' : 'red';
---
<div class="qa-card">
  <span class="topic">{pair.topic}</span>

  <div class="qa-columns">
    <div class="question">
      <h4>質問 — {pair.question.speaker}（{pair.question.party}）</h4>
      <p class="summary">{pair.question.summary}</p>
    </div>

    <div class="answer">
      <h4>答弁 — {pair.answer.speaker}（{pair.answer.role}）</h4>
      <p class="summary">{pair.answer.summary}</p>
      <span class="evasion" style={`color: ${evasionColor}`}>
        回避度: {(pair.answer.evasion_score * 100).toFixed(0)}%
      </span>
      {pair.answer.has_commitment && (
        <p class="commitment">約束: {pair.answer.commitment_text}</p>
      )}
    </div>
  </div>

  <a href={pair.video_url} target="_blank" rel="noopener">動画を見る</a>
</div>
```

### テスト

```bash
cd site
npm run dev
# ブラウザで以下を確認:
# 1. http://localhost:4321/ — セッション一覧が表示される
# 2. セッションカードをクリック → 詳細ページに遷移
# 3. 詳細ページにQ&Aカードが表示される
# 4. 出所リンクが正しく衆議院TV/参議院TVに遷移する
# 5. 動画リンクが正しいURLを持つ
# 6. evasion_scoreに応じてインジケータの色が変わる

npm run build
# dist/ にHTMLファイルが生成される
```

### 完了条件

- [ ] トップページにセッション一覧が表示される
- [ ] セッション詳細ページにQ&Aカードが表示される
- [ ] Q&Aカードに質問・答弁が並列表示される
- [ ] 出所リンクが正しく表示される（著作権法第48条対応）
- [ ] `npm run build` が成功する

---

## Step 9: Pagefind統合

### 目的

Astroビルド後のHTMLにPagefindを適用し、クライアントサイド全文検索を実現する。CJK（日本語）対応が必須。

### やること

#### 9-1. Pagefindインストール

```bash
cd site
npm install -D pagefind
```

#### 9-2. ビルドスクリプト更新

`package.json` の `scripts` に追加:

```json
{
  "scripts": {
    "build": "astro build && npx pagefind --site dist --glob '**/*.html'"
  }
}
```

もしくはbuildとpagefindを分けたい場合:
```json
{
  "scripts": {
    "build": "astro build",
    "postbuild": "npx pagefind --site dist --glob '**/*.html'"
  }
}
```

#### 9-3. `src/pages/search.astro` — 検索ページ

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
---
<BaseLayout title="検索 - 国会議事録リアルタイムDB">
  <h1>全文検索</h1>
  <div id="search"></div>

  <link href="/pagefind/pagefind-ui.css" rel="stylesheet" />
  <script>
    import { PagefindUI } from '/pagefind/pagefind-ui.js';
    new PagefindUI({
      element: '#search',
      showSubResults: true,
      translations: {
        placeholder: '審議内容を検索...',
        zero_results: '「[SEARCH_TERM]」に一致する結果はありません',
      },
    });
  </script>
</BaseLayout>
```

#### 9-4. Pagefindのdata属性でインデックス対象を制御

セッション詳細ページの主要コンテンツに `data-pagefind-body` を追加:

```astro
<div data-pagefind-body>
  <!-- Q&Aカード群やセッション概要 -->
</div>
```

ナビゲーション等のノイズを除外するため `data-pagefind-ignore` を適宜設定。

### テスト

```bash
cd site
npm run build
# dist/pagefind/ ディレクトリが生成される
npx pagefind --site dist --glob "**/*.html"
# Pagefindインデックスの統計情報が表示される

# ローカルプレビューで検索をテスト
npm run preview
# ブラウザで /search を開き:
# 1. 検索ボックスが表示される
# 2. 日本語キーワード（例: "高額療養費"）で検索結果が出る
# 3. 結果クリックでセッション詳細ページに遷移する
```

### 完了条件

- [ ] `npm run build` 後に `dist/pagefind/` が生成される
- [ ] 検索ページで日本語キーワード検索が動作する
- [ ] 検索結果からセッション詳細ページに遷移できる
- [ ] ナビゲーション等のノイズが検索結果に含まれない

---

## Step 10: GitHub Actions CI/CD

### 目的

`data/` へのpushをトリガーにAstroビルド + Pagefindインデックス生成 + GitHub Pagesデプロイを自動化する。

### やること

#### 10-1. `.github/workflows/build-deploy.yml`

```yaml
name: Build and Deploy

on:
  push:
    paths: ['data/**']
    branches: [main]

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'
          cache-dependency-path: site/package-lock.json

      - name: Install dependencies
        working-directory: site
        run: npm ci

      - name: Build Astro site
        working-directory: site
        run: npm run build

      # postbuild で pagefind が走る場合はこのステップは不要
      # ただし明示的に実行する場合:
      # - name: Build Pagefind index
      #   run: npx pagefind --site site/dist --glob "**/*.html"

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: site/dist

  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    needs: build
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

#### 10-2. GitHubリポジトリ設定

以下はGitHub UIで設定が必要（手順を文書化）:

1. **Settings → Pages → Source**: 「GitHub Actions」を選択
2. リポジトリのPagesが有効であることを確認

### テスト

```bash
# ローカルでActionsのステップを手動再現
cd site
npm ci
npm run build
ls -la dist/
ls -la dist/pagefind/

# GitHub にpush後、Actionsタブでワークフロー実行を確認
# GitHub PagesのURLでサイトが表示されることを確認
```

### 完了条件

- [ ] `.github/workflows/build-deploy.yml` が存在する
- [ ] `data/` への push で Actions が起動する
- [ ] Astro build + Pagefind indexing が成功する
- [ ] GitHub Pages にデプロイされサイトが閲覧可能
- [ ] `data/` 以外のファイル変更では Actions が起動しない

---

## Step 11: 結合テスト

### 目的

Docker → パイプライン実行 → data/ push → GitHub Actions → サイトデプロイの全フローを通しで確認する。

### やること

#### 11-1. ローカル結合テスト（pushなし）

```bash
# 1. Dockerビルド
cd kokkai-transcriber
docker compose build

# 2. 既存のdeli_id=56149 で実行（APIキー必要、pushなし）
docker compose run --rm transcriber \
  python -m src.pipeline --chamber shugiin --deli-id 56149 --no-push

# 3. data/ にJSONが生成されていることを確認
ls data/shugiin/2026/04/09/56149_本会議/

# 4. サイトビルド
cd ../site
npm run build

# 5. ローカルプレビュー
npm run preview
# ブラウザでセッション詳細ページと検索機能を確認
```

#### 11-2. End-to-End結合テスト（pushあり）

```bash
# 1. Docker実行（push込み）
docker compose run --rm transcriber \
  python -m src.pipeline --chamber shugiin --deli-id 56149

# 2. GitHubでActionsが起動したか確認
gh run list --limit 1

# 3. デプロイ完了後にGitHub PagesのURLを確認
# https://<username>.github.io/kokkaidb/
```

#### 11-3. 状態管理の確認

```bash
# SQLiteの状態を確認
docker compose run --rm transcriber python -c "
from src.state import StateManager
sm = StateManager()
for s in sm.list_sessions():
    print(s)
"
```

### チェックリスト

- [ ] `docker compose build` が成功する
- [ ] `docker compose run --rm transcriber python -m src.pipeline --chamber shugiin --deli-id 56149 --no-push` が完了する
- [ ] `data/shugiin/2026/04/09/56149_本会議/` に6つのJSONが生成される
- [ ] `state.db` にセッションが `done` ステータスで記録される
- [ ] `npm run build` が成功し `dist/` にサイトが生成される
- [ ] ローカルプレビューでトップページ、詳細ページ、検索が動作する
- [ ] Q&Aカードに出所リンクが表示される
- [ ] 同一セッションの再処理時にスキップされる（`is_processed()` が `True` を返す）
- [ ] git push 後にGitHub Actionsが起動する
- [ ] GitHub Pagesにサイトがデプロイされる

---

## ファイル一覧（Phase 2で新規作成・変更するファイル）

### 新規作成

| ファイル | Step | 内容 |
|---------|------|------|
| `kokkai-transcriber/src/scrapers/base.py` | 1 | BaseScraper ABC |
| `kokkai-transcriber/src/state.py` | 2 | SQLite状態管理 |
| `kokkai-transcriber/src/publisher.py` | 3 | git auto-push |
| `kokkai-transcriber/Dockerfile` | 5 | Dockerイメージ定義 |
| `kokkai-transcriber/docker-compose.yml` | 5 | Docker Compose設定 |
| `kokkai-transcriber/tests/test_state.py` | 2 | StateManagerテスト |
| `kokkai-transcriber/tests/test_publisher.py` | 3 | publisherテスト |
| `kokkai-transcriber/tests/fixtures/shugiin_calendar_20260409.html` | 1 | カレンダーHTMLフィクスチャ |
| `site/astro.config.mjs` | 6 | Astro設定 |
| `site/package.json` | 6 | npm設定 |
| `site/tsconfig.json` | 6 | TypeScript設定 |
| `site/src/layouts/BaseLayout.astro` | 6 | 共通レイアウト |
| `site/src/pages/index.astro` | 8 | トップページ |
| `site/src/pages/browse.astro` | 8 | 一覧ページ |
| `site/src/pages/search.astro` | 9 | 検索ページ |
| `site/src/pages/settings.astro` | 6 | 設定ページ（プレースホルダ） |
| `site/src/pages/[chamber]/[year]/[month]/[day]/[slug].astro` | 8 | セッション詳細 |
| `site/src/components/QAPairCard.astro` | 8 | Q&Aカード |
| `site/src/lib/data.ts` | 7 | データ読み込み |
| `site/src/pages/api/index.json.ts` | 7 | セッション一覧API |
| `site/src/pages/api/speakers.json.ts` | 7 | 発言者一覧API |
| `site/src/pages/api/topics.json.ts` | 7 | トピック一覧API |
| `.github/workflows/build-deploy.yml` | 10 | CI/CDワークフロー |

### 変更

| ファイル | Step | 変更内容 |
|---------|------|---------|
| `kokkai-transcriber/src/scrapers/shugiin.py` | 1 | 関数 → ShugiinScraperクラスにリファクタ |
| `kokkai-transcriber/src/scrapers/__init__.py` | 1 | エクスポート更新 |
| `kokkai-transcriber/src/pipeline.py` | 4 | StateManager + publisher統合、CLIオプション追加 |
| `kokkai-transcriber/tests/test_shugiin_scraper.py` | 1 | クラスベースに更新 + 新規テスト追加 |
| `kokkai-transcriber/tests/test_pipeline.py` | 4 | 状態管理 + auto-pushのテスト追加 |

---

## リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| Docker内でのgit認証 | push失敗 | SSH鍵マウントまたは `GH_TOKEN` 環境変数でHTTPS認証。docker-compose.yml の volumes でマウント |
| shugiintv.go.jpの日付検索レスポンス形式が想定と異なる | detect_new_sessions失敗 | 先にブラウザで `u_day=20260409` のレスポンスを保存してフィクスチャ化。実際のHTMLを見てからパーサーを書く |
| Pagefindの日本語トークナイズ | 検索精度低下 | Pagefind v1.xのCJKサポートは安定。必要に応じて `pagefind.yml` で設定調整 |
| data/ が空の場合のAstroビルド | ビルドエラー | `data.ts` で空配列フォールバック。`getStaticPaths()` が空配列を返してもAstroは問題なくビルドする |
| GitHub Pagesの base path | リンク切れ | `astro.config.mjs` の `base` を正しく設定。全リンクで相対パスを使用 |
| ShugiinScraperリファクタで既存テストが壊れる | CI失敗 | テストを先にクラスベースに書き換えてから本体を変更。red→greenの順 |
| docker-compose のvolumesパーミッション | ファイル書き込み失敗 | Dockerfile で `--chown` を使うか、UID/GIDを合わせる |
| **Phase 1確認済み** Whisper固有名詞誤認識 | metadata/utterancesの話者名が誤り | Phase 2では許容。Phase 3でWhisperプロンプトに答弁者（大臣等）の名前も渡す改善を行う |
| **Phase 1確認済み** Q&Aペア生成数が少ない | 情報量不足 | Phase 2では許容。Phase 3でstructurer.pyのプロンプトを調整し、セグメント別Q&A生成を検討する |

---

## 推奨作業順序（2-3日間）

### Day 1: Python側（Step 1-4）

1. **午前**: Step 1（BaseScraper ABC + ShugiinScraperリファクタ）— テスト先行
2. **午後前半**: Step 2（state.py）+ Step 3（publisher.py）— 並行可能
3. **午後後半**: Step 4（pipeline更新）— Step 1-3の統合

Day 1完了時の確認:
```bash
cd kokkai-transcriber
python -m pytest -m "not integration"  # 全テストパス（統合テスト除く）
python -m pytest -m integration        # 統合テスト（DEEPINFRA_API_KEY必要）
ruff check src/
mypy src/
```

**統合テストの`.env`読み込み**: `tests/conftest.py` の先頭で `from dotenv import load_dotenv; load_dotenv()` を呼ぶことで `DEEPINFRA_API_KEY` が自動読み込みされる（Phase 1で確立済み）。

### Day 2: インフラ + フロント（Step 5-9）

1. **午前**: Step 5（Docker化）+ Step 6（Astroセットアップ）— 並行可能
2. **午後前半**: Step 7（データ読み込み）+ Step 8（ページ実装）
3. **午後後半**: Step 9（Pagefind統合）

Day 2完了時の確認:
```bash
docker compose -f kokkai-transcriber/docker-compose.yml build
cd site && npm run build
npm run preview  # ブラウザで確認
```

### Day 3: CI/CD + 結合テスト（Step 10-11）

1. **午前**: Step 10（GitHub Actions）
2. **午後**: Step 11（結合テスト）
3. 問題があれば修正

Day 3完了時: GitHub Pages上でサイトが公開されていること。
