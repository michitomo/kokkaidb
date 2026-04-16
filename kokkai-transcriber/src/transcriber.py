"""Whisper 文字起こし (DeepInfra whisper-large-v3-turbo)

OpenAI 互換クライアントを使用して DeepInfra API を呼び出す。
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path

import openai

from src.api_client import with_retry
from src.models import RawTranscript, SegmentTranscript, SpeakerInfo, WhisperSegment

logger = logging.getLogger(__name__)

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
WHISPER_MODEL = "openai/whisper-large-v3-turbo"

# ---------------------------------------------------------------------------
# 第221回国会（令和8年特別会）対応 Whisper プロンプト
# ---------------------------------------------------------------------------
# Whisperのpromptは「指示」ではなく「直前の文脈」として機能する（スタイル模倣）。
# 224トークン制限があるため、固有名詞を自然な文中に埋め込む形式で記述する。
# セグメントごとに動的部分（発言者名）を末尾に配置し、影響力を最大化する。
#
# 政党・会派名:
#   衆: 自由民主党、立憲民主党、日本維新の会、公明党、日本共産党、チームみらい、日本保守党
#   参: 国民民主党、参政党、れいわ新選組、社会民主党、沖縄の風
#
# 主要閣僚: 高市早苗(総理)、木原稔(官房長官)、茂木敏充(外務)、片山さつき(財務)、
#   林芳正(総務)、平口洋(法務)、松本洋平(文科)、上野賢一郎(厚労)、鈴木憲和(農水)、
#   赤澤亮正(経産)、金子恭之(国交)、石原宏高(環境)、小泉進次郎(防衛)、松本尚(デジタル)
#
# 議長: 森英介(衆議院議長)、石井啓一(衆議院副議長)、
#       関口昌一(参議院議長)、福山哲郎(参議院副議長)
# ---------------------------------------------------------------------------

_WHISPER_PROMPT_BASE = (
    "第221回国会、衆議院本会議・委員会における質疑応答。"
    "高市早苗内閣総理大臣、木原稔内閣官房長官、茂木敏充外務大臣、"
    "片山さつき財務大臣、上野賢一郎厚生労働大臣、赤澤亮正経済産業大臣、"
    "小泉進次郎防衛大臣。"
    "自由民主党、立憲民主党、日本維新の会、公明党、日本共産党、"
    "国民民主党、チームみらい、参政党、れいわ新選組、日本保守党。"
    "健康保険法、高額療養費制度、OTC類似薬、防災庁設置法、"
    "国家情報会議設置法、社会福祉法、労働者災害補償保険法。"
    "森英介議長、石井啓一副議長。"
)


def _build_whisper_prompt(
    speaker: SpeakerInfo,
    all_speakers: list[SpeakerInfo],
) -> str:
    """セグメント固有のWhisperプロンプトを構築する。

    末尾に当該セグメントの発言者名・セッション発言者名を配置し、
    Whisperの224トークン制限内で最大限の効果を得る。
    （制限を超えた場合、末尾224トークンのみが使用される）
    """
    speaker_names = ", ".join(s.name for s in all_speakers)
    segment_suffix = f"発言者: {speaker.name}（{speaker.affiliation}）。出席議員: {speaker_names}。"
    return _WHISPER_PROMPT_BASE + segment_suffix


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

    prompt = _build_whisper_prompt(speaker, all_speakers)

    logger.info(
        "Transcribing segment %d: %s (%s)",
        segment_index,
        speaker.name,
        wav_path.name,
    )

    with open(wav_path, "rb") as f:
        f_bytes = f.read()

    def _call() -> object:
        return client.audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=("audio.wav", io.BytesIO(f_bytes), "audio/wav"),
            language="ja",
            response_format="verbose_json",
            timestamp_granularities=["segment"],
            prompt=prompt,
        )

    result = with_retry(_call)

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
