"""LLM 話者タグ付け (DeepInfra DeepSeek V3.2)

セグメント内の話者交代を検出し、utterances 配列を生成する。
"""

from __future__ import annotations

import json
import logging

from src.api_client import get_client as _get_client, LLM_MODEL, DEEPINFRA_BASE_URL

from src.models import (
    RawTranscript,
    SegmentTranscript,
    SegmentUtterances,
    SessionDetail,
    SpeakerInfo,
    Utterance,
    UtterancesOutput,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """あなたは国会議事録の話者タグ付けを行う専門家です。
与えられた文字起こしテキストを分析し、発言者ごとに発言を分割してください。

以下のルールに従ってください:
1. 委員長の指名発言パターン（「〇〇君」「〇〇委員」「〇〇大臣」）で話者交代を検出する
2. 答弁冒頭の定型句（「お答えいたします」「お答え申し上げます」「御指摘の」）で答弁者を検出する
3. セグメントの主発言者情報を参考にするが、委員長発言や答弁者の割り込みも正確に検出する
4. role は以下のいずれかを使用: 委員長 / 質疑者 / 答弁者 / 政府参考人 / 参考人 / その他

必ず以下の JSON 形式で出力してください:
{
  "utterances": [
    {"speaker": "発言者名", "role": "役割", "text": "発言内容"},
    ...
  ]
}
"""


def tag_speakers(
    raw_text: str,
    segment_speaker: SpeakerInfo,
    all_speakers: list[SpeakerInfo],
) -> list[Utterance]:
    """1セグメントの文字起こしテキストに話者タグを付ける。

    Args:
        raw_text: Whisper 文字起こしテキスト
        segment_speaker: このセグメントの主発言者
        all_speakers: セッション全発言者リスト

    Returns:
        Utterance のリスト

    Raises:
        openai.APIError: API 呼び出しが失敗した場合
        ValueError: LLM の出力が正しい JSON でない場合
    """
    client = _get_client()

    speaker_list = "\n".join(
        f"- {s.name}（{s.affiliation}）" for s in all_speakers
    )

    user_prompt = f"""セグメントの主発言者: {segment_speaker.name}（{segment_speaker.affiliation}）
役割: {segment_speaker.role or "質疑者"}

このセッションの発言者一覧:
{speaker_list}

以下の文字起こしを話者ごとに分割してください:

{raw_text}"""

    logger.info("Tagging speakers for segment: %s", segment_speaker.name)

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from LLM")

    data = json.loads(content)
    utterances_data = data.get("utterances", [])

    result = []
    for u in utterances_data:
        speaker = u.get("speaker", "")
        role = u.get("role", "その他")
        text = u.get("text", "")
        if not text:
            logger.warning("Skipping utterance with empty text: %s", u)
            continue
        if not speaker:
            logger.warning("Utterance missing speaker, using segment speaker: %s", segment_speaker.name)
            speaker = segment_speaker.name
        result.append(Utterance(speaker=speaker, role=role, text=text))
    return result


def _build_video_url(chamber: str, session_id: str, start_seconds: float) -> str:
    """院に応じた動画リンクURLを生成する。"""
    if chamber == "shugiin":
        return (
            f"https://www.shugiintv.go.jp/jp/index.php"
            f"?ex=VL&media_type=&deli_id={session_id}&time={start_seconds}"
        )
    elif chamber == "sangiin":
        return (
            f"https://webtv.sangiin.go.jp/webtv/detail.php"
            f"?sid={session_id}#{start_seconds}"
        )
    return ""


def tag_all_segments(
    raw_transcript: RawTranscript,
    session_detail: SessionDetail,
    max_workers: int = 16,
) -> UtterancesOutput:
    """全セグメントを並列でLLM話者タグ付けして UtterancesOutput を返す。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    speakers = session_detail.speakers

    def _resolve_speaker(seg: SegmentTranscript) -> SpeakerInfo:
        if seg.segment_index < len(speakers):
            return speakers[seg.segment_index]
        matched = next((s for s in speakers if s.name == seg.speaker_name), None)
        return matched or SpeakerInfo(
            name=seg.speaker_name,
            affiliation="",
            start_seconds=seg.start_seconds,
            start_time="",
            duration_minutes=0,
        )

    def _tag(seg: SegmentTranscript) -> SegmentUtterances:
        segment_speaker = _resolve_speaker(seg)
        utterances = tag_speakers(seg.text, segment_speaker, speakers)
        video_url = _build_video_url(
            session_detail.chamber, session_detail.session_id, seg.start_seconds
        )
        return SegmentUtterances(
            segment_index=seg.segment_index,
            segment_speaker=segment_speaker.name,
            segment_affiliation=segment_speaker.affiliation,
            start_seconds=seg.start_seconds,
            video_url=video_url,
            utterances=utterances,
        )

    results: list[SegmentUtterances] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_tag, seg): seg.segment_index for seg in raw_transcript.segments}
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda s: s.segment_index)
    return UtterancesOutput(segments=results)
