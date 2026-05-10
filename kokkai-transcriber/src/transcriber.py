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
# 第221回国会（令和8年特別会）対応 Whisper プロンプト  [Prompt V2]
# ---------------------------------------------------------------------------
# Whisperのpromptは「指示」ではなく「直前の文脈」として機能する（スタイル模倣）。
# 224トークン制限内に収め、かつトークンループを抑制するための設計方針:
#
# [V1→V2 変更点と根拠]
# 1. 「石井啓一副議長」削除
#    → 実データで「石井啓一議長、石井啓一議長...」25秒ループが複数確認。
#      プロンプト末尾に固定配置されていたため、本会議セッションで特に危険。
#
# 2. 全法律名（健康保険法〜労働者災害補償保険法）削除
#    → 「社会福祉法」が「福祉法、福祉法...」24秒ループを誘発（9件確認）。
#      法律名はセッション固有かつトークン消費大（~40トークン）のため除去。
#      委員会固有の法律名は将来的に動的サフィックスで追加可能。
#
# 3. 動的サフィックスを「出席議員: 全員列挙」から「{委員会}。{発言者}：」へ変更
#    → 「出席議員」リストが最多ループ誘発源（42件）。任意の出席者名が
#      音響的に不明瞭な区間でループ起点になっていた。
#    → 新形式は議事録の自然な「直前テキスト」として機能し、トークン消費も
#      ~133トークン→~15トークンに削減。全プロンプトが224制限内に確実に収まる。
#
# [維持した要素]
# - 主要閣僚7名: 小泉進次郎・片山さつき・茂木敏充は100%正確認識を確認済み
# - 主要政党名: 国民民主党（50%誤認問題あり）・日本維新の会（69%誤認）等の改善に期待
# - 森英介議長（副議長は除外）
#
# [V2.1 拡張 (PR5, §2.6)]
# 目的: whisper_misrecognition (269件) のうち参議院議長・社会民主党関連の
#       Whisper 第一通過誤認を抑制する。
#
# 変更点:
#   - 「衆議院の」→「の」: 参議院セッションでも使うため (+suffix で chamber は伝わる)
#   - 政党に「社会民主党」を追加 (元々抜けていた)
#   - 議長を「森英介議長」→「森英介衆議院議長、関口昌一参議院議長」に拡張
#     (参議院セッションで議長 context が皆無だった問題を解消)
#   - 閣僚 7名 (V2 から維持) + 第2次高市内閣の他 9名は token 予算外のため
#     transcript_corrector のフルリスト (大臣 16名) に委任
#
# Token 予算注意:
#   Whisper prompt は 224-token 制限。overflow 時は **冒頭側を truncate**。
#   現状 base 209 + 動的 suffix 18-31 = 227-240 (約 -3〜-16 tokens overflow)。
#   truncate は冒頭の "第221回国会の質疑応答。" (~10 tokens) で起こり、
#   閣僚名・政党名・議長名・動的 suffix は preserve される。
#   → 年号は corrector でカバーされるため受容できる範囲。
#
# [既知の残存問題]
# - 高市早苗: 91%で「高市」に末尾省略。音声上での省略発言か Whisper 誤認かは未確定。
# - 国民民主党: 50%で「国民民主」に末尾省略。「党」の音が弱い可能性。
# - 安倍内閣ハルシネーション: Whisper学習バイアスで稀に出現（1件確認）。
#
# 議長: 森英介(衆議院議長)、石井啓一(衆議院副議長)※プロンプト外
#       関口昌一(参議院議長)、福山哲郎(参議院副議長)※プロンプト外
# ---------------------------------------------------------------------------

_WHISPER_PROMPT_BASE = (
    "第221回国会の質疑応答。"
    "高市早苗内閣総理大臣、木原稔内閣官房長官、茂木敏充外務大臣、"
    "片山さつき財務大臣、上野賢一郎厚生労働大臣、"
    "赤澤亮正経済産業大臣、小泉進次郎防衛大臣。"
    "自由民主党、立憲民主党、日本維新の会、公明党、日本共産党、"
    "国民民主党、チームみらい、参政党、れいわ新選組、日本保守党、社会民主党。"
    "森英介衆議院議長、関口昌一参議院議長。"
)


def _build_whisper_prompt(
    speaker: SpeakerInfo,
    committee: str,
) -> str:
    """セグメント固有のWhisperプロンプトを構築する。

    「{委員会}。{発言者名}（{所属}）：」という議事録形式の自然なテキストで締める。
    Whisperはこれを「直前の発言者表記」として解釈し、次に続く音声の話者・文脈を
    正しく補正する。全体が224トークン制限に確実に収まる（~110トークン想定）。
    """
    committee_label = committee or "委員会"
    return _WHISPER_PROMPT_BASE + f"{committee_label}。{speaker.name}（{speaker.affiliation}）："


def _get_client() -> openai.OpenAI:
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        raise OSError("DEEPINFRA_API_KEY environment variable is not set")
    return openai.OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)


def transcribe_segment(
    wav_path: Path,
    segment_index: int,
    speaker: SpeakerInfo,
    committee: str,
) -> SegmentTranscript:
    """1セグメントの WAV ファイルを文字起こしする。

    Args:
        wav_path: セグメント WAV ファイルパス
        segment_index: セグメントインデックス
        speaker: このセグメントの主発言者
        committee: 委員会名（動的サフィックスに使用）

    Returns:
        SegmentTranscript: 文字起こし結果

    Raises:
        openai.APIError: API 呼び出しが失敗した場合
    """
    client = _get_client()

    prompt = _build_whisper_prompt(speaker, committee)

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
    committee: str = "",
    max_workers: int = 16,
) -> RawTranscript:
    """全セグメントを並列で文字起こしして RawTranscript を返す。

    Args:
        segment_paths: セグメント WAV ファイルのリスト
        speakers: 発言者リスト（segment_paths と同順）
        session_id: セッションID
        committee: 委員会名（Whisperプロンプトの動的サフィックスに使用）
        max_workers: 並列数（DeepInfra のレート制限に合わせて調整）

    Returns:
        RawTranscript: 全セグメントの文字起こし結果（segment_index 順にソート済み）
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _transcribe(args: tuple[int, Path, SpeakerInfo]) -> SegmentTranscript:
        i, wav_path, speaker = args
        return transcribe_segment(wav_path, i, speaker, committee)

    tasks = list(enumerate(zip(segment_paths, speakers)))
    work = [(i, wav, spk) for i, (wav, spk) in tasks]

    results: list[SegmentTranscript] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_transcribe, item): item[0] for item in work}
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda s: s.segment_index)
    return RawTranscript(session_id=session_id, segments=results)
