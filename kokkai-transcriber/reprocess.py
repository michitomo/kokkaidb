#!/usr/bin/env python3
"""一括再処理スクリプト

1. state.db の status='error' セッション → フルパイプライン再実行（セッション並列）
2. state.db の status='done' セッション → Step 4.5 以降をStep別バッチ処理

DeepInfra 200 concurrent limit を活用して高速に処理する。

使い方:
    cd kokkai-transcriber
    uv run python reprocess.py                    # デフォルト
    uv run python reprocess.py --workers 100      # LLM並列数
    uv run python reprocess.py --errors-only      # errorのみ再処理
    uv run python reprocess.py --rerun-only       # doneのStep4.5以降のみ
    uv run python reprocess.py --session-parallel 4  # フルパイプライン並列数
"""

from __future__ import annotations

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.api_client import MAX_WORKERS_LLM, ensure_fd_limit
from src.state import StateManager
from src.models import RawTranscript, SessionDetail, SummaryOutput
from src.transcript_corrector import (
    CorrectionChunk,
    _chunk_segment,
    correct_chunk,
)
from src.normalizer import normalize_utterances
from src.speaker_tagger import tag_all_segments
from src.structurer import (
    build_summary_related_laws,
    generate_key_commitments,
    generate_qa_pairs,
    generate_session_summary,
    generate_topics_and_key_topics,
    tag_related_laws,
)
from src.committee_to_ministry import filter_laws_for_committee
from src.pipeline import run_pipeline_for_session, DATA_DIR, _load_laws_compact

_FLOOR_LIKE_KINDS = frozenset(("floor_speech", "procedural"))

ensure_fd_limit()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _session_dir(chamber: str, date: str, session_id: str, committee: str) -> Path:
    year, month, day = date.split("-")
    return DATA_DIR / chamber / year / month / day / f"{session_id}_{committee}"


@dataclass
class SessionInfo:
    chamber: str
    session_id: str
    date: str
    committee: str

    @property
    def dir(self) -> Path:
        return _session_dir(self.chamber, self.date, self.session_id, self.committee)


# ---------------------------------------------------------------------------
# Phase 2: Step別バッチ処理（done セッションの再処理）
# ---------------------------------------------------------------------------

def rerun_step45_batch(
    sessions: list[SessionInfo],
    state: StateManager,
    max_workers: int,
) -> None:
    """全セッションのStep 4.5をチャンク単位でバッチ並列処理する。"""
    logger.info("--- Step 4.5: Collecting chunks from %d sessions ---", len(sessions))

    # 全セッションからチャンクを収集
    @dataclass
    class ChunkTask:
        session: SessionInfo
        chunk: CorrectionChunk
        speaker_name: str
        speaker_affiliation: str
        all_speakers_str: str
        committee: str

    tasks: list[ChunkTask] = []
    session_data: dict[str, tuple[RawTranscript, SessionDetail]] = {}

    for s in sessions:
        transcript_path = s.dir / "raw_transcript.json"
        metadata_path = s.dir / "metadata.json"
        if not transcript_path.exists() or not metadata_path.exists():
            logger.warning("Missing files for %s, skipping", s.session_id)
            continue

        rt = RawTranscript.model_validate_json(transcript_path.read_text(encoding="utf-8"))
        sd = SessionDetail.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        session_data[s.session_id] = (rt, sd)

        for seg in rt.segments:
            speaker = sd.speakers[seg.segment_index] if seg.segment_index < len(sd.speakers) else None
            sp_name = speaker.name if speaker else seg.speaker_name
            sp_aff = speaker.affiliation if speaker else ""
            chunks = _chunk_segment(seg)
            for chunk in chunks:
                tasks.append(ChunkTask(
                    session=s,
                    chunk=chunk,
                    speaker_name=sp_name,
                    speaker_affiliation=sp_aff,
                    all_speakers_str="\n".join(
                        f"- {sp.name}（{sp.affiliation}）" for sp in sd.speakers
                    ),
                    committee=sd.committee,
                ))

    logger.info("Step 4.5: %d chunks from %d sessions, workers=%d", len(tasks), len(sessions), max_workers)

    # 全チャンクを並列で修正
    from src.models import SpeakerInfo

    corrected: dict[tuple[str, int, int], str] = {}  # (session_id, seg_idx, chunk_idx) → text
    failed_sessions: set[str] = set()

    def _correct_task(task: ChunkTask) -> tuple[str, int, int, str]:
        speaker = SpeakerInfo(
            name=task.speaker_name,
            affiliation=task.speaker_affiliation,
            start_seconds=0, start_time="", duration_minutes=0,
        )
        sd = session_data[task.session.session_id][1]
        result = correct_chunk(task.chunk.text, speaker, sd.speakers, task.committee)
        return task.session.session_id, task.chunk.segment_index, task.chunk.chunk_index, result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_correct_task, t): t for t in tasks}
        done_count = 0
        for future in as_completed(futures):
            try:
                sid, seg_idx, chunk_idx, text = future.result()
                # 安全チェック
                task = futures[future]
                original_len = len(task.chunk.text)
                ratio = len(text) / original_len if original_len > 0 else 1.0
                if ratio < 0.8:
                    text = task.chunk.text
                corrected[(sid, seg_idx, chunk_idx)] = text
            except Exception as e:
                task = futures[future]
                logger.error("Chunk failed [%s seg=%d chunk=%d]: %s",
                             task.session.session_id, task.chunk.segment_index, task.chunk.chunk_index, e)
                corrected[(task.session.session_id, task.chunk.segment_index, task.chunk.chunk_index)] = task.chunk.text
                failed_sessions.add(task.session.session_id)
            done_count += 1
            if done_count % 50 == 0 or done_count == len(tasks):
                logger.info("Step 4.5: %d/%d chunks done", done_count, len(tasks))

    # セッションごとに再結合して保存
    from datetime import datetime, timedelta, timezone
    from src.models import SegmentTranscript
    JST = timezone(timedelta(hours=9))

    for s in sessions:
        if s.session_id not in session_data:
            continue
        rt, sd = session_data[s.session_id]
        new_segments = []
        for seg in rt.segments:
            chunks = _chunk_segment(seg)
            parts = [corrected.get((s.session_id, seg.segment_index, c.chunk_index), c.text) for c in chunks]
            new_segments.append(SegmentTranscript(
                segment_index=seg.segment_index,
                speaker_name=seg.speaker_name,
                start_seconds=seg.start_seconds,
                text="\n".join(parts),
                whisper_segments=seg.whisper_segments,
            ))
        new_rt = RawTranscript(
            session_id=rt.session_id,
            corrected=True,
            corrected_at=datetime.now(JST).isoformat(),
            segments=new_segments,
        )
        (s.dir / "raw_transcript.json").write_text(
            new_rt.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8",
        )
        session_data[s.session_id] = (new_rt, sd)

    logger.info("Step 4.5 complete. %d sessions updated, %d had errors", len(sessions), len(failed_sessions))


def _run_step5_one(
    s: SessionInfo,
    state: StateManager,
    max_workers: int,
) -> tuple[SessionInfo, bool, str]:
    """1セッションのStep 5を実行する。"""
    transcript_path = s.dir / "raw_transcript.json"
    metadata_path = s.dir / "metadata.json"
    if not transcript_path.exists() or not metadata_path.exists():
        return s, False, "missing files"
    try:
        rt = RawTranscript.model_validate_json(transcript_path.read_text(encoding="utf-8"))
        sd = SessionDetail.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        utterances_output = tag_all_segments(rt, sd, max_workers=max_workers)
        utterances_output = normalize_utterances(utterances_output, sd.speakers)
        (s.dir / "utterances.json").write_text(
            utterances_output.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8",
        )
        return s, True, f"{len(utterances_output.segments)} segments"
    except Exception as e:
        state.update_status(s.chamber, s.session_id, "error", f"Rerun Step 5 failed: {e}")
        return s, False, str(e)


def rerun_step5_batch(
    sessions: list[SessionInfo],
    state: StateManager,
    max_workers: int,
    session_parallel: int = 6,
) -> list[SessionInfo]:
    """全セッションのStep 5をセッション間並列で処理する。失敗セッションを除いたリストを返す。"""
    logger.info(
        "--- Step 5: Tagging speakers for %d sessions, workers=%d, session_parallel=%d ---",
        len(sessions), max_workers, session_parallel,
    )

    per_session_workers = max(1, max_workers // session_parallel)
    succeeded: list[SessionInfo] = []
    failed: list[SessionInfo] = []

    with ThreadPoolExecutor(max_workers=session_parallel) as executor:
        futures = {
            executor.submit(_run_step5_one, s, state, per_session_workers): s
            for s in sessions
        }
        for i, future in enumerate(as_completed(futures), 1):
            s, success, detail = future.result()
            if success:
                succeeded.append(s)
                logger.info("[%d/%d] [%s] Step 5 done: %s", i, len(sessions), s.session_id, detail)
            else:
                failed.append(s)
                logger.error("[%d/%d] [%s] Step 5 failed: %s", i, len(sessions), s.session_id, detail[:100])

    logger.info("Step 5 complete: %d ok, %d failed", len(succeeded), len(failed))
    return succeeded


def _run_step6_one(
    s: SessionInfo,
    state: StateManager,
    max_workers: int,
) -> tuple[str, bool, str]:
    """1セッションのStep 6を実行する。(session_id, success, detail)を返す。"""
    from src.models import UtterancesOutput as UO

    utterances_path = s.dir / "utterances.json"
    metadata_path = s.dir / "metadata.json"
    if not utterances_path.exists() or not metadata_path.exists():
        return s.session_id, False, "missing files"
    try:
        utterances_output = UO.model_validate_json(utterances_path.read_text(encoding="utf-8"))
        sd = SessionDetail.model_validate_json(metadata_path.read_text(encoding="utf-8"))

        sk = sd.session_kind
        if sk in _FLOOR_LIKE_KINDS:
            from src.models import QAPairsOutput
            qa_pairs = QAPairsOutput(pairs=[])
        else:
            qa_pairs = generate_qa_pairs(
                utterances_output,
                speakers=sd.speakers,
                max_workers=max_workers,
                skip_proposal_segments=(sk == "representative_questions"),
            )

        session_summary = generate_session_summary(qa_pairs, utterances_output)
        topics, key_topics = generate_topics_and_key_topics(qa_pairs)
        commitments = generate_key_commitments(qa_pairs)

        if qa_pairs.pairs:
            laws_text = filter_laws_for_committee(_load_laws_compact(), sd.committee)
            if laws_text:
                qa_pairs = tag_related_laws(
                    qa_pairs,
                    chamber=sd.chamber,
                    committee=sd.committee,
                    date=sd.date,
                    laws_text=laws_text,
                    max_workers=max_workers,
                )

        summary = SummaryOutput(
            session_summary=session_summary,
            key_topics=key_topics,
            key_commitments=commitments,
            related_laws=build_summary_related_laws(qa_pairs),
        )

        (s.dir / "qa_pairs.json").write_text(
            qa_pairs.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8",
        )
        (s.dir / "summary.json").write_text(
            summary.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8",
        )
        (s.dir / "topics.json").write_text(
            topics.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8",
        )
        state.update_status(s.chamber, s.session_id, "done")
        return s.session_id, True, f"{len(qa_pairs.pairs)} pairs, {len(topics.topics)} topics"
    except Exception as e:
        state.update_status(s.chamber, s.session_id, "error", f"Rerun Step 6 failed: {e}")
        return s.session_id, False, str(e)


def rerun_step6_batch(
    sessions: list[SessionInfo],
    state: StateManager,
    max_workers: int,
    session_parallel: int = 6,
) -> None:
    """全セッションのStep 6をセッション間並列で処理する。

    各セッション内のセグメントも並列(max_workers)で処理するが、
    セッション自体もsession_parallel本同時に走らせることで
    API並列枠をフル活用する。
    """
    logger.info(
        "--- Step 6: Structuring %d sessions, workers=%d, session_parallel=%d ---",
        len(sessions), max_workers, session_parallel,
    )

    # セッション内並列数を調整（全体でmax_workersを超えないように）
    per_session_workers = max(1, max_workers // session_parallel)

    ok, fail = 0, 0
    with ThreadPoolExecutor(max_workers=session_parallel) as executor:
        futures = {
            executor.submit(_run_step6_one, s, state, per_session_workers): s
            for s in sessions
        }
        for i, future in enumerate(as_completed(futures), 1):
            sid, success, detail = future.result()
            if success:
                ok += 1
                logger.info("[%d/%d] [%s] Step 6 done: %s", i, len(sessions), sid, detail)
            else:
                fail += 1
                logger.error("[%d/%d] [%s] Step 6 failed: %s", i, len(sessions), sid, detail[:100])

    logger.info("Step 6 complete: %d ok, %d failed", ok, fail)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="一括再処理スクリプト")
    parser.add_argument(
        "--workers", type=int, default=MAX_WORKERS_LLM,
        help=f"LLM並列数（デフォルト: {MAX_WORKERS_LLM}）",
    )
    parser.add_argument(
        "--session-parallel", type=int, default=2,
        help="Phase 1 フルパイプライン並列数（デフォルト: 2）",
    )
    parser.add_argument(
        "--errors-only", action="store_true",
        help="status=error のセッションのみ再処理（フルパイプライン）",
    )
    parser.add_argument(
        "--rerun-only", action="store_true",
        help="status=done のセッションのみ Step 4.5 以降を再実行",
    )
    parser.add_argument(
        "--no-push", action="store_true", default=True,
        help="git pushをスキップ（デフォルト: True）",
    )
    parser.add_argument(
        "--step6-only", action="store_true",
        help="status=done のセッションの Step 6 のみ再実行",
    )
    args = parser.parse_args()

    state = StateManager()

    # Phase 1: error セッションのフルパイプライン再実行（セッション並列）
    if not args.rerun_only:
        rows = state.conn.execute(
            "SELECT chamber, session_id, date, committee, error_msg "
            "FROM processed_sessions WHERE status='error' "
            "ORDER BY date, session_id"
        ).fetchall()
        error_sessions = [dict(r) for r in rows]

        logger.info("=" * 60)
        logger.info("Phase 1: Retrying %d error sessions (full pipeline, %d parallel)",
                     len(error_sessions), args.session_parallel)
        logger.info("=" * 60)

        ok, fail = 0, 0

        def _run_one(s: dict) -> tuple[str, bool, str]:
            try:
                run_pipeline_for_session(
                    chamber=s["chamber"],
                    session_id=s["session_id"],
                    state=state,
                    no_push=args.no_push,
                )
                return s["session_id"], True, ""
            except RuntimeError as e:
                return s["session_id"], False, str(e)

        with ThreadPoolExecutor(max_workers=args.session_parallel) as executor:
            futures = {executor.submit(_run_one, s): s for s in error_sessions}
            for i, future in enumerate(as_completed(futures), 1):
                sid, success, err = future.result()
                s = futures[future]
                if success:
                    ok += 1
                    logger.info("[%d/%d] OK %s %s", i, len(error_sessions), s["chamber"], sid)
                else:
                    fail += 1
                    logger.error("[%d/%d] ERR %s %s: %s", i, len(error_sessions), s["chamber"], sid, err[:100])

        logger.info("Phase 1 complete: %d ok, %d failed", ok, fail)

    # Phase 2: done セッションの Step 4.5 以降をStep別バッチ処理
    if not args.errors_only:
        rows = state.conn.execute(
            "SELECT chamber, session_id, date, committee "
            "FROM processed_sessions WHERE status='done' "
            "ORDER BY date, session_id"
        ).fetchall()
        sessions = [SessionInfo(**dict(r)) for r in rows]

        logger.info("=" * 60)
        logger.info("Phase 2: Step-batched rerun for %d done sessions (workers=%d)",
                     len(sessions), args.workers)
        logger.info("=" * 60)

        if args.step6_only:
            # Step 6 のみ再実行
            rerun_step6_batch(sessions, state, max_workers=args.workers)
        else:
            # Step 4.5: 全チャンクをバッチ並列
            rerun_step45_batch(sessions, state, max_workers=args.workers)

            # Step 5: セッション間並列
            succeeded = rerun_step5_batch(sessions, state, max_workers=args.workers)

            # Step 6: セッション間並列
            rerun_step6_batch(succeeded, state, max_workers=args.workers)

    logger.info("=" * 60)
    logger.info("All done.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
