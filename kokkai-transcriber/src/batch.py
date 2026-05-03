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

冪等性:
    data/{chamber}/**/{session_id}_*/qa_pairs.json の存在で処理済みを判定する。
    真実のソースは常に data/ であり、それ以外に状態DBを持たない。
    SessionNotReadyError（発言者リスト未公開）で失敗したセッションは、
    単にその回のバッチでは処理されず、次回バッチでサイト側が準備できていれば自然に成功する。
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

# data/ ルート: 処理済み判定の唯一の真実のソース。
_DATA_ROOT = Path(__file__).parent.parent.parent / "data"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _has_processed_output(chamber: str, session_id: str) -> bool:
    """data/{chamber}/**/{session_id}_*/qa_pairs.json が存在すれば処理済み。"""
    chamber_dir = _DATA_ROOT / chamber
    if not chamber_dir.exists():
        return False
    matches = list(chamber_dir.glob(f"*/*/*/{session_id}_*/qa_pairs.json"))
    return len(matches) > 0


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
) -> list[tuple[str, str, str]]:
    """指定期間のセッションを探索し、未処理のものを返す。

    Returns:
        [(chamber, session_id, date_str), ...]
    """
    scraper = _get_scraper(chamber)
    dates = _date_range(since, until)
    all_sessions: list[tuple[str, str, str]] = []

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
            if _has_processed_output(chamber, sid):
                logger.debug("Already processed: %s %s", chamber, sid)
                continue
            all_sessions.append((chamber, sid, date_str))

        if session_ids:
            logger.info(
                "  %s: %d sessions found (%d new)", date_str, len(session_ids),
                sum(1 for _c, _s, dd in all_sessions if dd == date_str),
            )

        # スクレイピング先への負荷軽減
        time.sleep(0.5)

    return all_sessions


def _process_one(
    chamber: str,
    session_id: str,
) -> tuple[str, str, bool, str]:
    """1セッションを処理する（pushは常にスキップ、バッチ終了後にまとめてpush）。

    戻り値: (chamber, session_id, success, message)
    """
    try:
        scraper = _get_scraper(chamber)
        detail = scraper.get_session_detail(session_id)
        output_dir = _output_dir_for(chamber, detail.date, session_id, detail.committee)

        # バッチモードでは個別pushしない（最後にまとめてpush）
        run_pipeline(chamber, session_id, output_dir, no_push=True)

        return (chamber, session_id, True, f"{detail.date} {detail.committee}")
    except SessionNotReadyError as e:
        # サイト反映待ち。次回バッチで自然に再挑戦される。
        return (chamber, session_id, False, f"not ready: {e}")
    except Exception as e:
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
) -> None:
    """バッチ処理のメインエントリポイント。"""
    # Phase 1: 全セッション探索
    all_sessions: list[tuple[str, str, str]] = []
    for chamber in chambers:
        sessions = _discover_sessions(chamber, since, until)
        all_sessions.extend(sessions)

    logger.info("=" * 60)
    logger.info("Total sessions to process: %d", len(all_sessions))
    for chamber, sid, date_str in all_sessions:
        logger.info("  %s %s (%s)", chamber, sid, date_str)
    logger.info("=" * 60)

    if dry_run:
        if any(arg == "--json" for arg in sys.argv):
            import json
            print(json.dumps([
                {"chamber": c, "sid": s, "date": d}
                for c, s, d in all_sessions
            ]))
        else:
            logger.info("Dry run — exiting without processing")
        return

    if not all_sessions:
        logger.info("No new sessions to process")
        return

    # Phase 2: 並列処理
    succeeded = 0
    failed = 0
    not_ready = 0
    results: list[tuple[str, str, bool, str]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_one, chamber, sid): (chamber, sid, date_str)
            for chamber, sid, date_str in all_sessions
        }

        for future in as_completed(futures):
            chamber, sid, _date_str = futures[future]
            result = future.result()
            results.append(result)
            _, _, success, msg = result
            done = succeeded + failed + not_ready + 1
            if success:
                succeeded += 1
                logger.info("OK    [%d/%d] %s %s: %s", done, len(all_sessions), chamber, sid, msg)
            elif msg.startswith("not ready"):
                not_ready += 1
                logger.warning("SKIP  [%d/%d] %s %s: %s", done, len(all_sessions), chamber, sid, msg)
            else:
                failed += 1
                logger.error("ERR   [%d/%d] %s %s: %s", done, len(all_sessions), chamber, sid, msg)

    # サマリー
    logger.info("=" * 60)
    logger.info(
        "Batch complete: %d succeeded, %d not-ready (skipped), %d failed, %d total",
        succeeded, not_ready, failed, len(all_sessions),
    )
    if failed > 0:
        logger.info("Failed sessions:")
        for chamber, sid, success, msg in results:
            if not success and not msg.startswith("not ready"):
                logger.info("  %s %s: %s", chamber, sid, msg)
    if not_ready > 0:
        logger.info("Not-ready sessions (will auto-retry on next batch):")
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
        "--json",
        action="store_true",
        help="JSON形式で出力（--dry-run時のみ有効）",
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
    )


if __name__ == "__main__":
    main()
