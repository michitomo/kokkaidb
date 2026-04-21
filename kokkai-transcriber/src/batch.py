"""バッチ処理: 指定期間のセッションを並列でパイプライン実行する

使用方法:
    # 2026年2月以降の衆議院セッションを8並列で処理
    python -m src.batch --chamber shugiin --since 2026-02-01 --workers 8

    # 参議院も（mediasp解決が動く前提）
    python -m src.batch --chamber sangiin --since 2026-02-01 --workers 8

    # 両院
    python -m src.batch --since 2026-02-01 --workers 8

    # ドライラン（実際の処理はせず対象セッションを表示）
    python -m src.batch --since 2026-02-01 --dry-run

    # git push なし
    python -m src.batch --since 2026-02-01 --workers 4 --no-push
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.pipeline import _get_scraper, _output_dir_for, run_pipeline
from src.publisher import _get_default_branch, _run_git
from src.scrapers.base import SessionNotReadyError
from src.state import StateManager

MAX_RETRIES = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _date_range(since: date, until: date) -> list[date]:
    """since〜until（inclusive）の平日リストを返す。国会は土日開催がほぼない。"""
    dates: list[date] = []
    current = since
    while current <= until:
        if current.weekday() < 5:  # 月〜金
            dates.append(current)
        current += timedelta(days=1)
    return dates


def _discover_sessions(
    chamber: str,
    since: date,
    until: date,
    state: StateManager,
) -> list[tuple[str, str, str]]:
    """指定期間のセッションを探索し、未処理のものを返す。

    期間外の pending_retry セッションも一緒に返す（前回失敗分の自動再試行）。

    Returns:
        [(chamber, session_id, date_str), ...]
    """
    scraper = _get_scraper(chamber)
    dates = _date_range(since, until)
    all_sessions: list[tuple[str, str, str]] = []
    seen_ids: set[str] = set()

    logger.info(
        "Discovering %s sessions from %s to %s (%d weekdays)",
        chamber, since, until, len(dates),
    )

    for d in dates:
        date_str = d.isoformat()
        try:
            session_ids = scraper.detect_new_sessions(date_str)
        except Exception as e:
            logger.warning("Failed to fetch %s sessions for %s: %s", chamber, date_str, e)
            continue

        for sid in session_ids:
            if state.is_processed(chamber, sid):
                logger.debug("Already processed: %s %s", chamber, sid)
                continue
            all_sessions.append((chamber, sid, date_str))
            seen_ids.add(sid)

        if session_ids:
            logger.info("  %s: %d sessions found (%d new)", date_str, len(session_ids),
                        sum(1 for c, s, _ in all_sessions if _ == date_str))

        # スクレイピング先への負荷軽減
        time.sleep(0.5)

    # 期間外の pending_retry も拾う（サイト反映遅延などで前回失敗したもの）
    retry_sessions = state.get_retry_sessions(chamber=chamber, max_retries=MAX_RETRIES)
    added = 0
    for row in retry_sessions:
        sid = row["session_id"]
        if sid in seen_ids:
            continue
        all_sessions.append((chamber, sid, row["date"]))
        seen_ids.add(sid)
        added += 1
    if added > 0:
        logger.info("Also retrying %d pending_retry sessions from previous runs", added)

    return all_sessions


def _process_one(
    chamber: str,
    session_id: str,
    state: StateManager,
) -> tuple[str, str, bool, str]:
    """1セッションを処理する（pushは常にスキップ、バッチ終了後にまとめてpush）。

    戻り値: (chamber, session_id, success, message)
    """
    try:
        scraper = _get_scraper(chamber)
        detail = scraper.get_session_detail(session_id)
        output_dir = _output_dir_for(chamber, detail.date, session_id, detail.committee)

        state.register_session(chamber, session_id, detail.date, detail.committee)
        state.update_status(chamber, session_id, "processing")

        # バッチモードでは個別pushしない（最後にまとめてpush）
        run_pipeline(chamber, session_id, output_dir, state=state, no_push=True)
        state.update_status(chamber, session_id, "done")

        return (chamber, session_id, True, f"{detail.date} {detail.committee}")
    except SessionNotReadyError as e:
        # 一時的な失敗 → pending_retry に。次回バッチが自動で拾う。
        retry = 0
        try:
            # dateとcommittee不明なので仮登録
            state.register_session(chamber, session_id, "unknown", "unknown")
            retry = state.get_retry_count(chamber, session_id) + 1
            if retry > MAX_RETRIES:
                state.update_status(chamber, session_id, "error",
                                    error_msg=f"Exceeded max retries ({MAX_RETRIES}): {e}")
                return (chamber, session_id, False, f"max retries exceeded: {e}")
            state.update_status(chamber, session_id, "pending_retry", error_msg=str(e))
        except Exception:
            pass
        return (chamber, session_id, False, f"not ready (retry {retry}/{MAX_RETRIES}): {e}")
    except Exception as e:
        try:
            state.update_status(chamber, session_id, "error", error_msg=str(e))
        except Exception:
            pass
        return (chamber, session_id, False, str(e))


def _batch_push(since: date, until: date) -> None:
    """処理済みデータをまとめて git commit + push する。"""
    import subprocess

    _run_git("add", "data/")

    # 差分がなければスキップ（exit code 0 = no changes, 1 = has changes）
    try:
        _run_git("diff", "--cached", "--quiet", "--exit-code")
        logger.info("No changes to push")
        return
    except subprocess.CalledProcessError:
        pass  # 差分あり → commit + push

    date_range = f"{since}〜{until}"
    _run_git("commit", "-m", f"data: batch {date_range}")

    branch = _get_default_branch()
    _run_git("push", "origin", branch)
    logger.info("Pushed to origin/%s", branch)


def run_batch(
    chambers: list[str],
    since: date,
    until: date,
    max_workers: int = 4,
    no_push: bool = False,
    dry_run: bool = False,
    db_path: Path | None = None,
) -> None:
    """バッチ処理のメインエントリポイント。"""
    state_kwargs = {}
    if db_path:
        state_kwargs["db_path"] = db_path
    state = StateManager(**state_kwargs)

    # Phase 1: 全セッション探索
    all_sessions: list[tuple[str, str, str]] = []
    for chamber in chambers:
        sessions = _discover_sessions(chamber, since, until, state)
        all_sessions.extend(sessions)

    logger.info("=" * 60)
    logger.info("Total sessions to process: %d", len(all_sessions))
    for chamber, sid, date_str in all_sessions:
        logger.info("  %s %s (%s)", chamber, sid, date_str)
    logger.info("=" * 60)

    if dry_run:
        logger.info("Dry run — exiting without processing")
        state.close()
        return

    if not all_sessions:
        logger.info("No new sessions to process")
        state.close()
        return

    # Phase 2: 並列処理
    succeeded = 0
    failed = 0
    retried = 0  # pending_retry に回ったセッション数
    results: list[tuple[str, str, bool, str]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _process_one, chamber, sid, state,
            ): (chamber, sid, date_str)
            for chamber, sid, date_str in all_sessions
        }

        for future in as_completed(futures):
            chamber, sid, date_str = futures[future]
            result = future.result()
            results.append(result)
            _, _, success, msg = result
            if success:
                succeeded += 1
                logger.info("OK  [%d/%d] %s %s: %s", succeeded + failed + retried, len(all_sessions), chamber, sid, msg)
            elif msg.startswith("not ready"):
                retried += 1
                logger.warning("RETRY [%d/%d] %s %s: %s", succeeded + failed + retried, len(all_sessions), chamber, sid, msg)
            else:
                failed += 1
                logger.error("ERR [%d/%d] %s %s: %s", succeeded + failed + retried, len(all_sessions), chamber, sid, msg)

    # サマリー
    logger.info("=" * 60)
    logger.info("Batch complete: %d succeeded, %d retry-later, %d failed, %d total",
                succeeded, retried, failed, len(all_sessions))
    if failed > 0:
        logger.info("Failed sessions (permanent):")
        for chamber, sid, success, msg in results:
            if not success and not msg.startswith("not ready"):
                logger.info("  %s %s: %s", chamber, sid, msg)
    if retried > 0:
        logger.info("Pending-retry sessions (will retry on next batch):")
        for chamber, sid, success, msg in results:
            if not success and msg.startswith("not ready"):
                logger.info("  %s %s: %s", chamber, sid, msg)
    logger.info("=" * 60)

    # Phase 3: まとめて git push
    if not no_push and succeeded > 0:
        logger.info("Pushing %d sessions to origin...", succeeded)
        try:
            _batch_push(since, until)
        except Exception as e:
            logger.error("Git push failed: %s", e)

    state.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="国会TV バッチ処理: 期間指定の全セッションを並列で処理"
    )
    parser.add_argument(
        "--chamber",
        choices=["shugiin", "sangiin"],
        action="append",
        help="対象の院（複数指定可、省略時は衆議院のみ）",
    )
    parser.add_argument(
        "--since",
        required=True,
        help="開始日（YYYY-MM-DD）",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="終了日（YYYY-MM-DD、デフォルト: 今日）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="並列数（デフォルト: 8）",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="git push をスキップ",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="対象セッション一覧を表示するのみ（処理は行わない）",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="SQLite DB パス（デフォルト: kokkai-transcriber/state.db）",
    )

    args = parser.parse_args()

    chambers = args.chamber or ["shugiin"]
    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until) if args.until else date.today()

    if since > until:
        print(f"Error: --since ({since}) is after --until ({until})", file=sys.stderr)
        sys.exit(1)

    run_batch(
        chambers=chambers,
        since=since,
        until=until,
        max_workers=args.workers,
        no_push=args.no_push,
        dry_run=args.dry_run,
        db_path=args.db_path,
    )


if __name__ == "__main__":
    main()
