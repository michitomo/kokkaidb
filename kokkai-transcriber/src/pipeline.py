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

    # git pushなし（ローカルテスト用）
    python -m src.pipeline --chamber shugiin --session-id 56149 --no-push
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
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
from src.audio.extractor import detect_leading_silence, download_full_audio, split_segments
from src.normalizer import normalize_utterances
from src.publisher import publish_session
from src.scrapers.base import BaseScraper, SessionNotReadyError
from src.scrapers.sangiin import SangiinScraper
from src.scrapers.shugiin import ShugiinScraper
from src.speaker_tagger import tag_all_segments
from src.transcript_corrector import correct_transcript
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


def _load_laws_compact() -> str:
    """LLMプロンプト用のコンパクトな法案一覧テキストを読み込む。

    `data/laws/laws_compact.txt`（`src.laws_builder` で事前生成）を読んでそのまま返す。
    見つからない場合は空文字列を返す（法案タグ付けをスキップ）。
    """
    laws_path = DATA_DIR / "laws" / "laws_compact.txt"

    if not laws_path.exists():
        logger.info("laws_compact.txt not found at %s, skipping law tagging", laws_path)
        return ""

    content = laws_path.read_text(encoding="utf-8")
    line_count = sum(1 for line in content.splitlines() if line.strip())
    if line_count:
        logger.info("Loaded %d laws for LLM tagging", line_count)
    return content


def _output_dir_for(chamber: str, date: str, session_id: str, committee: str) -> Path:
    """セッションの出力ディレクトリパスを返す。"""
    year, month, day = date.split("-")
    return DATA_DIR / chamber / year / month / day / f"{session_id}_{committee}"


def run_pipeline(
    chamber: str,
    session_id: str,
    output_dir: Path,
    no_push: bool = False,
) -> None:
    """1セッションのパイプラインを実行する。

    Args:
        chamber: "shugiin" | "sangiin"
        session_id: セッションID
        output_dir: JSON出力先ディレクトリ
        no_push: Trueの場合git pushをスキップ

    Raises:
        SessionNotReadyError: 発言者リスト未公開（呼び出し側で一時エラー扱い）
        RuntimeError: いずれかのステップが失敗した場合
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 2: スクレイピング
    logger.info("=== Step 2: Scraping session detail (%s %s) ===", chamber, session_id)
    try:
        scraper = _get_scraper(chamber)
        session_detail = scraper.get_session_detail(session_id)
    except SessionNotReadyError:
        # 一時的な失敗はそのまま再raise（呼び出し側でスキップ）
        raise
    except Exception as e:
        raise RuntimeError(f"Step 2 (scraping) failed: {e}") from e

    # バリデーション: 発言者0件はここに到達しないはず（SessionNotReadyErrorで弾かれる）が
    # 念のため boundary check。
    if not session_detail.speakers:
        raise SessionNotReadyError(
            f"Speaker list unexpectedly empty for {chamber} {session_id}"
        )

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

            # HLS先頭の無音パディングを検出してタイムスタンプを補正
            # 衆議院TVの time= パラメータは映像トラック基準のため、
            # 音声トラックの先頭に無音パディングがあるとズレが生じる。
            # 最初のspeakerの start_seconds と実際の音声開始位置の差を
            # オフセットとして計算し、全speakerのタイムスタンプを補正する。
            leading_silence = detect_leading_silence(full_wav)
            if leading_silence > 10.0 and session_detail.speakers:
                first_speaker_time = session_detail.speakers[0].start_seconds
                # 音声は leading_silence 秒目から始まる。TVはfirst_speaker_timeと言っている。
                # first_speaker_time が leading_silence より十分大きければオフセットが存在。
                offset = first_speaker_time - leading_silence
                if offset > 30.0:
                    logger.info(
                        "Applying audio offset correction: %.1fs "
                        "(leading_silence=%.1fs, first_speaker=%.1fs)",
                        offset, leading_silence, first_speaker_time,
                    )
                    for speaker in session_detail.speakers:
                        speaker.start_seconds -= offset
                    # metadata.jsonも補正済みタイムスタンプで上書き
                    metadata_path.write_text(
                        session_detail.model_dump_json(indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )

            segment_paths = split_segments(
                full_wav,
                session_detail.speakers,
                output_dir / "segments",
            )
    except Exception as e:
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
    except Exception as e:
        raise RuntimeError(f"Step 4 (transcription) failed: {e}") from e

    # Step 4.5: LLM 文字起こし修正（句読点補完・固有名詞修正）
    logger.info("=== Step 4.5: Correcting transcript with LLM ===")
    try:
        raw_transcript = correct_transcript(raw_transcript, session_detail, max_workers=MAX_WORKERS_LLM)
    except Exception as e:
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

    # バリデーション: 文字起こし結果が極端に少ないセッションは異常
    total_chars = sum(len(s.text) for s in raw_transcript.segments)
    if total_chars < 100:
        raise RuntimeError(
            f"Transcript too short ({total_chars} chars). "
            f"Audio extraction or Whisper may have failed."
        )

    # Step 5: LLM 話者タグ付け
    logger.info("=== Step 5: Tagging speakers with LLM ===")
    try:
        utterances_output = tag_all_segments(raw_transcript, session_detail, max_workers=MAX_WORKERS_LLM)
    except Exception as e:
        raise RuntimeError(f"Step 5 (speaker tagging) failed: {e}") from e

    # Step 5.5: speaker / role を metadata.speakers に正規化
    logger.info("=== Step 5.5: Normalizing utterance speakers and roles ===")
    utterances_output = normalize_utterances(utterances_output, session_detail.speakers)

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
    except Exception as e:
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
    no_push: bool = False,
) -> None:
    """セッション詳細を取得して output_dir を決めた上で run_pipeline を呼ぶ。"""
    scraper = _get_scraper(chamber)
    detail = scraper.get_session_detail(session_id)
    output_dir = _output_dir_for(chamber, detail.date, session_id, detail.committee)
    run_pipeline(chamber, session_id, output_dir, no_push=no_push)


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

    args = parser.parse_args()

    try:
        if args.session_id or args.deli_id:
            session_id = args.session_id or args.deli_id
            if args.output_dir:
                output_dir = args.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                run_pipeline(
                    chamber=args.chamber,
                    session_id=session_id,
                    output_dir=output_dir,
                    no_push=args.no_push,
                )
            else:
                run_pipeline_for_session(
                    chamber=args.chamber,
                    session_id=session_id,
                    no_push=args.no_push,
                )

        elif args.date:
            target_date = (
                str(date_type.today()) if args.date == "today" else args.date
            )
            scraper = _get_scraper(args.chamber)
            session_ids = scraper.detect_new_sessions(target_date)
            logger.info("Found %d sessions for %s", len(session_ids), target_date)

            for sid in session_ids:
                try:
                    run_pipeline_for_session(
                        chamber=args.chamber,
                        session_id=sid,
                        no_push=args.no_push,
                    )
                except SessionNotReadyError as e:
                    logger.warning("Session %s not ready: %s", sid, e)
                except RuntimeError as e:
                    logger.error("Session %s failed: %s", sid, e)

        else:
            parser.print_help()
            sys.exit(1)

    except Exception as e:
        logger.error("Pipeline failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
