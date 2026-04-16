"""LLM 話者タグ付け (DeepInfra DeepSeek V3.2)

セグメント内の話者交代を検出し、utterances 配列を生成する。
LLMには話者交代ポイント（文番号）と話者名・役割のみ返させ、
テキスト本体はコード側で元の文を結合する（出力トークン大幅削減）。
"""

from __future__ import annotations

import json
import logging
import re

from src.api_client import get_client as _get_client, LLM_MODEL, DEEPINFRA_BASE_URL, with_retry

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
番号付きの文リストが与えられます。話者交代ポイントを検出し、各発言の開始文番号・話者名・役割を返してください。

テキスト本体は返さないでください。開始文番号だけで十分です。

## 検出ルール
1. 委員長の指名発言パターン（「〇〇君」「〇〇委員」「〇〇大臣」）で話者交代を検出する
2. 答弁冒頭の定型句（「お答えいたします」「お答え申し上げます」「御指摘の」）で答弁者を検出する
3. セグメントの主発言者情報を参考にするが、委員長発言や答弁者の割り込みも正確に検出する
4. role は以下のいずれかを使用: 委員長 / 質疑者 / 答弁者 / 政府参考人 / 参考人 / その他

## 出力形式
必ず以下の JSON 形式で出力してください:
{
  "splits": [
    {"start": 0, "speaker": "発言者名", "role": "役割"},
    {"start": 5, "speaker": "別の発言者", "role": "役割"},
    ...
  ]
}

- start: その発言者の発言が始まる文番号（0始まり）
- splits は start の昇順で並べること
- 最初の split の start は必ず 0 であること
- テキストは絶対に含めないこと
"""


def _split_sentences(text: str) -> list[str]:
    """テキストを文単位に分割する。

    句点「。」、疑問符「？」、改行で分割。
    空文字列は除外する。
    """
    # 句点・疑問符の後、または改行で分割
    parts = re.split(r'(?<=[。？])|(?<=\n)', text)
    return [s.strip() for s in parts if s.strip()]


def _number_sentences(sentences: list[str]) -> str:
    """文リストを番号付きテキストに変換する。"""
    return "\n".join(f"({i}){s}" for i, s in enumerate(sentences))


def tag_speakers(
    raw_text: str,
    segment_speaker: SpeakerInfo,
    all_speakers: list[SpeakerInfo],
) -> list[Utterance]:
    """1セグメントの文字起こしテキストに話者タグを付ける。

    入力テキストを文単位で番号付けし、LLMには話者交代ポイントのみ返させる。
    テキスト本体はコード側で結合する。

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

    sentences = _split_sentences(raw_text)
    if not sentences:
        return [Utterance(speaker=segment_speaker.name, role="質疑者", text=raw_text)]

    numbered_text = _number_sentences(sentences)

    speaker_list = "\n".join(
        f"- {s.name}（{s.affiliation}）" for s in all_speakers
    )

    user_prompt = f"""セグメントの主発言者: {segment_speaker.name}（{segment_speaker.affiliation}）
役割: {segment_speaker.role or "質疑者"}

このセッションの発言者一覧:
{speaker_list}

以下の番号付き文リストの話者交代ポイントを検出してください（{len(sentences)}文）:

{numbered_text}"""

    logger.info("Tagging speakers for segment: %s", segment_speaker.name)

    response = with_retry(lambda: client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    ))

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from LLM")

    data = json.loads(content)
    splits = data.get("splits", [])

    if not splits:
        # フォールバック: 分割なし → 全文を主発言者の発言とする
        logger.warning("No splits returned, using entire text as single utterance")
        return [Utterance(
            speaker=segment_speaker.name,
            role=segment_speaker.role or "質疑者",
            text=raw_text,
        )]

    # start で昇順ソート
    splits.sort(key=lambda s: s.get("start", 0))

    # 最初の split が 0 でなければ補正
    if splits[0].get("start", 0) != 0:
        splits.insert(0, {
            "start": 0,
            "speaker": segment_speaker.name,
            "role": segment_speaker.role or "質疑者",
        })

    # splits → Utterance リストに変換
    result = []
    for i, split in enumerate(splits):
        start_idx = split.get("start", 0)
        end_idx = splits[i + 1].get("start", len(sentences)) if i + 1 < len(splits) else len(sentences)

        # 範囲チェック
        start_idx = max(0, min(start_idx, len(sentences)))
        end_idx = max(start_idx, min(end_idx, len(sentences)))

        if start_idx >= end_idx:
            continue

        text = "".join(sentences[start_idx:end_idx])
        speaker = split.get("speaker", "")
        role = split.get("role", "その他")

        if not speaker:
            logger.warning("Split missing speaker, using segment speaker: %s", segment_speaker.name)
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
