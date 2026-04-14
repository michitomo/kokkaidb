"""Whisper 文字起こし (DeepInfra whisper-large-v3-turbo)

OpenAI 互換クライアントを使用して DeepInfra API を呼び出す。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import openai

from src.models import RawTranscript, SegmentTranscript, SpeakerInfo, WhisperSegment

logger = logging.getLogger(__name__)

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
WHISPER_MODEL = "openai/whisper-large-v3-turbo"


def _get_client() -> openai.OpenAI:
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPINFRA_API_KEY environment variable is not set")
    return openai.OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)


def transcribe_segment(
    wav_path: Path,
    segment_index: int,
    speaker: SpeakerInfo,
    all_speakers: list[SpeakerInfo],
) -> SegmentTranscript:
    """1セグメントの WAV ファイルを文字起こしする。

    Args:
        wav_path: セグメント WAV ファイルパス
        segment_index: セグメントインデックス
        speaker: このセグメントの主発言者
        all_speakers: セッション全発言者リスト（prompt生成に使用）

    Returns:
        SegmentTranscript: 文字起こし結果

    Raises:
        openai.APIError: API 呼び出しが失敗した場合
    """
    client = _get_client()

    speaker_names = [s.name for s in all_speakers]
    prompt = f"国会質疑: {', '.join(speaker_names)}"

    logger.info(
        "Transcribing segment %d: %s (%s)",
        segment_index,
        speaker.name,
        wav_path.name,
    )

    with open(wav_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=f,
            language="ja",
            response_format="verbose_json",
            timestamp_granularities=["segment"],
            prompt=prompt,
        )

    whisper_segments = []
    raw_segments = getattr(result, "segments", None) or []
    for seg in raw_segments:
        whisper_segments.append(
            WhisperSegment(
                id=seg.get("id", 0) if isinstance(seg, dict) else getattr(seg, "id", 0),
                seek=seg.get("seek", 0) if isinstance(seg, dict) else getattr(seg, "seek", 0),
                start=seg.get("start", 0.0) if isinstance(seg, dict) else getattr(seg, "start", 0.0),
                end=seg.get("end", 0.0) if isinstance(seg, dict) else getattr(seg, "end", 0.0),
                text=seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", ""),
                tokens=seg.get("tokens", []) if isinstance(seg, dict) else list(getattr(seg, "tokens", [])),
                temperature=seg.get("temperature", 0.0) if isinstance(seg, dict) else getattr(seg, "temperature", 0.0),
                avg_logprob=seg.get("avg_logprob", 0.0) if isinstance(seg, dict) else getattr(seg, "avg_logprob", 0.0),
                compression_ratio=seg.get("compression_ratio", 0.0) if isinstance(seg, dict) else getattr(seg, "compression_ratio", 0.0),
                no_speech_prob=seg.get("no_speech_prob", 0.0) if isinstance(seg, dict) else getattr(seg, "no_speech_prob", 0.0),
            )
        )

    full_text = result.text if hasattr(result, "text") else ""

    return SegmentTranscript(
        segment_index=segment_index,
        speaker_name=speaker.name,
        start_seconds=speaker.start_seconds,
        text=full_text,
        whisper_segments=whisper_segments,
    )


def transcribe_all_segments(
    segment_paths: list[Path],
    speakers: list[SpeakerInfo],
    session_id: str,
    max_workers: int = 16,
) -> RawTranscript:
    """全セグメントを並列で文字起こしして RawTranscript を返す。

    Args:
        segment_paths: セグメント WAV ファイルのリスト
        speakers: 発言者リスト（segment_paths と同順）
        session_id: セッションID
        max_workers: 並列数（DeepInfra のレート制限に合わせて調整）

    Returns:
        RawTranscript: 全セグメントの文字起こし結果（segment_index 順にソート済み）
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _transcribe(args: tuple[int, Path, SpeakerInfo]) -> SegmentTranscript:
        i, wav_path, speaker = args
        return transcribe_segment(wav_path, i, speaker, speakers)

    tasks = list(enumerate(zip(segment_paths, speakers)))
    work = [(i, wav, spk) for i, (wav, spk) in tasks]

    results: list[SegmentTranscript] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_transcribe, item): item[0] for item in work}
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda s: s.segment_index)
    return RawTranscript(session_id=session_id, segments=results)
