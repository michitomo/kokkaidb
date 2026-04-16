"""パイプライン統合エントリポイント

使用方法:
    # 衆議院（セッションID直接指定）
    python -m src.pipeline --chamber shugiin --session-id 56149

    # 参議院
    python -m src.pipeline --chamber sangiin --session-id 7890

    # 後方互換（衆議院のみ）
    python -m src.pipeline --chamber shugiin --deli-id 56149

    # 日付指定の自動巡回
    python -m src.pipeline --chamber shugiin --date 2026-04-09

    # 未処理セッションを全て処理
    python -m src.pipeline --chamber shugiin --process-pending

    # git pushなし（ローカルテスト用）
    python -m src.pipeline --chamber shugiin --session-id 56149 --no-push
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date as date_type
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.api_client import (
    MAX_WORKERS_AUDIO,
    MAX_WORKERS_LLM,
    MAX_WORKERS_WHISPER,
    ensure_fd_limit,
)
from src.audio.extractor import download_full_audio, split_segments
from src.publisher import publish_session
from src.scrapers.base import BaseScraper
from src.scrapers.sangiin import SangiinScraper
from src.scrapers.shugiin import ShugiinScraper
from src.speaker_tagger import tag_all_segments
from src.transcript_corrector import correct_transcript
from src.state import StateManager
from src.structurer import generate_qa_pairs, generate_summary, generate_summary_and_topics, generate_topics
from src.transcriber import transcribe_all_segments

# パイプライン起動時にfd上限を引き上げ
ensure_fd_limit()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# データ出力先（kokkai-transcriber/ の1つ上の data/）
DATA_DIR = Path(__file__).parent.parent.parent / "data"

# 法案一覧（docs/laws.md）
LAWS_MD_PATH = Path(__file__).parent.parent.parent / "docs" / "laws.md"


def _load_laws_compact() -> str:
    """laws.mdからLLMプロンプト用のコンパクトな法案一覧テキストを生成する。

    見つからない場合は空文字列を返す（法案タグ付けをスキップ）。
    """
    import re

    if not LAWS_MD_PATH.exists():
        logger.info("laws.md not found at %s, skipping law tagging", LAWS_MD_PATH)
        return ""

    content = LAWS_MD_PATH.read_text(encoding="utf-8")
    lines = content.split("\n")
    compact: list[str] = []
    law_id = 0
    for line in lines:
        m = re.match(r'^## \*\*(.+?)\s*\\?\s*-\s*(.+?)\*\*$', line)
        if m:
            law_id += 1
            title = m.group(2).strip()
            compact.append(f"law_{law_id:03d}: {title}")

    if compact:
        logger.info("Loaded %d laws from laws.md for LLM tagging", len(compact))
    return "\n".join(compact)


def _output_dir_for(chamber: str, date: str, session_id: str, committee: str) -> Path:
    """セッションの出力ディレクトリパスを返す。"""
    year, month, day = date.split("-")
    return DATA_DIR / chamber / year / month / day / f"{session_id}_{committee}"


def run_pipeline(
    chamber: str,
    session_id: str,
    output_dir: Path,
    state: StateManager | None = None,
    no_push: bool = False,
) -> None:
    """1セッションのパイプラインを実行する。

    Args:
        chamber: "shugiin" | "sangiin"
        session_id: セッションID
        output_dir: JSON出力先ディレクトリ
        state: StateManagerインスタンス（Noneの場合は状態管理なし）
        no_push: Trueの場合git pushをスキップ

    Raises:
        RuntimeError: いずれかのステップが失敗した場合
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    def _log(step: str, success: bool, detail: str = "") -> None:
        if state:
            state.log_step(chamber, session_id, step, success, detail)

    # Step 2: スクレイピング
    logger.info("=== Step 2: Scraping session detail (%s %s) ===", chamber, session_id)
    try:
        scraper = _get_scraper(chamber)
        session_detail = scraper.get_session_detail(session_id)
        _log("scrape", True)
    except Exception as e:
        _log("scrape", False, str(e))
        raise RuntimeError(f"Step 2 (scraping) failed: {e}") from e

    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(
        session_detail.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved metadata.json (%d speakers)", len(session_detail.speakers))

    # Step 3: HLS音声取得・分割
    logger.info("=== Step 3: Downloading and splitting audio ===")
    try:
        # 参議院の場合、mediasp.jp hash から音声URLを解決
        if session_detail.chamber == "sangiin" and not session_detail.hls_url:
            from src.audio.sangiin_resolver import resolve_stream_url

            if not session_detail.mediasp_hash:
                raise ValueError(f"No mediasp_hash or hls_url for sangiin sid={session_id}")
            audio_url = resolve_stream_url(session_detail.mediasp_hash)
        else:
            audio_url = session_detail.hls_url

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            full_wav = tmp_path / "full_audio.wav"

            download_full_audio(audio_url, full_wav)
            segment_paths = split_segments(
                full_wav,
                session_detail.speakers,
                output_dir / "segments",
            )
        _log("audio", True)
    except Exception as e:
        _log("audio", False, str(e))
        raise RuntimeError(f"Step 3 (audio extraction) failed: {e}") from e

    logger.info("Created %d audio segments", len(segment_paths))

    # Step 4: Whisper 文字起こし
    logger.info("=== Step 4: Transcribing with Whisper ===")
    try:
        raw_transcript = transcribe_all_segments(
            segment_paths,
            session_detail.speakers,
            session_id,
            max_workers=MAX_WORKERS_WHISPER,
        )
        _log("transcribe", True)
    except Exception as e:
        _log("transcribe", False, str(e))
        raise RuntimeError(f"Step 4 (transcription) failed: {e}") from e

    # Step 4.5: LLM 文字起こし修正（句読点補完・固有名詞修正）
    logger.info("=== Step 4.5: Correcting transcript with LLM ===")
    try:
        raw_transcript = correct_transcript(raw_transcript, session_detail, max_workers=MAX_WORKERS_LLM)
        _log("correct", True)
    except Exception as e:
        _log("correct", False, str(e))
        logger.warning("Transcript correction failed (non-fatal, using original): %s", e)

    transcript_path = output_dir / "raw_transcript.json"
    transcript_path.write_text(
        raw_transcript.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "Saved raw_transcript.json (%d segments, corrected=%s)",
        len(raw_transcript.segments),
        raw_transcript.corrected,
    )

    # Step 5: LLM 話者タグ付け
    logger.info("=== Step 5: Tagging speakers with LLM ===")
    try:
        utterances_output = tag_all_segments(raw_transcript, session_detail, max_workers=MAX_WORKERS_LLM)
        _log("tag", True)
    except Exception as e:
        _log("tag", False, str(e))
        raise RuntimeError(f"Step 5 (speaker tagging) failed: {e}") from e

    utterances_path = output_dir / "utterances.json"
    utterances_path.write_text(
        utterances_output.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "Saved utterances.json (%d segments)", len(utterances_output.segments)
    )

    # Step 6: Q&Aペア生成 → 要約・トピック・法案タグ（統合LLM呼び出し）
    logger.info("=== Step 6: Generating Q&A pairs, summary, topics, and law tags ===")
    try:
        qa_pairs = generate_qa_pairs(utterances_output, speakers=session_detail.speakers, max_workers=MAX_WORKERS_LLM)
        laws_text = _load_laws_compact()
        summary, topics = generate_summary_and_topics(utterances_output, qa_pairs, laws_text=laws_text)
        _log("structure", True)
    except Exception as e:
        _log("structure", False, str(e))
        raise RuntimeError(f"Step 6 (structuring) failed: {e}") from e

    (output_dir / "qa_pairs.json").write_text(
        qa_pairs.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        summary.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "topics.json").write_text(
        topics.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "Saved qa_pairs.json (%d pairs), summary.json, topics.json (%d topics)",
        len(qa_pairs.pairs),
        len(topics.topics),
    )

    logger.info("=== Pipeline complete. Output: %s ===", output_dir)

    output_files = list(output_dir.glob("*.json"))
    for f in sorted(output_files):
        size = f.stat().st_size
        logger.info("  %s (%d bytes)", f.name, size)

    # git push
    if not no_push:
        logger.info("=== Publishing: git commit + push ===")
        try:
            publish_session(
                output_dir=output_dir,
                chamber=chamber,
                session_id=session_id,
                date=session_detail.date,
                committee=session_detail.committee,
            )
        except Exception as e:
            logger.warning("Publish failed (non-fatal): %s", e)


def _get_scraper(chamber: str) -> BaseScraper:
    """院に応じたScraperインスタンスを返す。"""
    if chamber == "shugiin":
        return ShugiinScraper()
    elif chamber == "sangiin":
        return SangiinScraper()
    else:
        raise ValueError(f"Unknown chamber: {chamber}")


def run_pipeline_for_session(
    chamber: str,
    session_id: str,
    state: StateManager,
    no_push: bool = False,
) -> None:
    """StateManagerと連携して1セッションを処理する。"""
    scraper = _get_scraper(chamber)

    # 詳細をフェッチしてoutput_dirを決定
    detail = scraper.get_session_detail(session_id)
    output_dir = _output_dir_for(chamber, detail.date, session_id, detail.committee)

    state.register_session(chamber, session_id, detail.date, detail.committee)
    state.update_status(chamber, session_id, "processing")

    try:
        run_pipeline(chamber, session_id, output_dir, state=state, no_push=no_push)
        state.update_status(chamber, session_id, "done")
    except RuntimeError as e:
        state.update_status(chamber, session_id, "error", error_msg=str(e))
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="国会TV パイプライン: スクレイピング→音声→文字起こし→構造化"
    )
    parser.add_argument(
        "--chamber",
        default="shugiin",
        choices=["shugiin", "sangiin"],
        help="院（デフォルト: shugiin）",
    )

    # セッション指定モード
    session_group = parser.add_mutually_exclusive_group()
    session_group.add_argument(
        "--session-id",
        help="セッションID（衆議院: deli_id、参議院: sid）",
    )
    session_group.add_argument(
        "--deli-id",
        help="衆議院TV の deli_id（後方互換、--session-id を推奨）",
    )
    session_group.add_argument(
        "--date",
        help="指定日の全セッションを自動巡回（YYYY-MM-DD、'today'も可）",
    )
    session_group.add_argument(
        "--process-pending",
        action="store_true",
        help="未処理セッションを全て処理",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        help="出力先ディレクトリ（--deli-id使用時のみ。省略時はdata/配下に自動生成）",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="git pushをスキップ（ローカルテスト用）",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="SQLite DBのパス（デフォルト: kokkai-transcriber/state.db）",
    )

    args = parser.parse_args()

    # StateManagerを初期化
    state_kwargs = {}
    if args.db_path:
        state_kwargs["db_path"] = args.db_path
    state = StateManager(**state_kwargs)

    try:
        if args.session_id or args.deli_id:
            # セッションID直接指定モード
            session_id = args.session_id or args.deli_id
            if args.output_dir:
                output_dir = args.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                # 出力先が明示されている場合は状態管理なしでシンプルに実行
                run_pipeline(
                    chamber=args.chamber,
                    session_id=session_id,
                    output_dir=output_dir,
                    state=state,
                    no_push=args.no_push,
                )
            else:
                run_pipeline_for_session(
                    chamber=args.chamber,
                    session_id=session_id,
                    state=state,
                    no_push=args.no_push,
                )

        elif args.date:
            # 日付指定の自動巡回モード
            target_date = (
                str(date_type.today()) if args.date == "today" else args.date
            )
            scraper = _get_scraper(args.chamber)

            session_ids = scraper.detect_new_sessions(target_date)
            logger.info("Found %d sessions for %s", len(session_ids), target_date)

            for sid in session_ids:
                if state.is_processed(args.chamber, sid):
                    logger.info("Skipping already-processed session: %s", sid)
                    continue
                try:
                    run_pipeline_for_session(
                        chamber=args.chamber,
                        session_id=sid,
                        state=state,
                        no_push=args.no_push,
                    )
                except RuntimeError as e:
                    logger.error("Session %s failed: %s", sid, e)

        elif args.process_pending:
            # 未処理セッション全処理モード
            pending = state.get_pending_sessions(chamber=args.chamber)
            logger.info("Found %d pending sessions", len(pending))
            for session in pending:
                try:
                    run_pipeline_for_session(
                        chamber=session["chamber"],
                        session_id=session["session_id"],
                        state=state,
                        no_push=args.no_push,
                    )
                except RuntimeError as e:
                    logger.error("Session %s failed: %s", session["session_id"], e)

        else:
            parser.print_help()
            sys.exit(1)

    except Exception as e:
        logger.error("Pipeline failed: %s", e)
        sys.exit(1)
    finally:
        state.close()


if __name__ == "__main__":
    main()
