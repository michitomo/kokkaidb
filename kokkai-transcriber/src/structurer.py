"""LLM Q&Aペア生成・要約・トピック抽出 (DeepInfra DeepSeek V3.2)

セグメント単位で並列にQ&Aペアを生成し、抜け漏れを防止する。
LLMにはutterance_indicesと判断のみ返させ、full_textはコードで組み立てる。
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import openai

from src.models import (
    AnswerDetail,
    KeyCommitment,
    QAPair,
    QAPairsOutput,
    QuestionDetail,
    SegmentUtterances,
    SpeakerInfo,
    SummaryOutput,
    Topic,
    TopicsOutput,
    UtterancesOutput,
)

logger = logging.getLogger(__name__)

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
LLM_MODEL = "deepseek-ai/DeepSeek-V3.2"

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

QA_SEGMENT_SYSTEM_PROMPT = """あなたは国会質疑のQ&Aペアを構造化する専門家です。
与えられた番号付きutterancesリストから、質疑応答ペアを**すべて**抽出してください。

重要なルール:
- 質疑者が複数のテーマについて質問した場合、テーマごとに別のQ&Aペアを作成すること
- 1つも漏らさずに抽出すること
- full_textは返さないこと。代わりにutterance_indices（番号の配列）を返すこと
- utterance_indicesは、そのQ&Aペアを構成するutterancesの番号（入力の[N]の数字）を配列で指定
- summaryは箇条書き（各項目は「- 」で始める）。要点を2-4項目で簡潔に

speaker, party, roleは返さないでください（コードで元データから自動取得します）。

以下のJSON形式で出力してください:
{
  "pairs": [
    {
      "topic": "質疑テーマ（簡潔に）",
      "question": {
        "summary": "- 要点1\n- 要点2\n- 要点3",
        "utterance_indices": [0, 1, 2],
        "intent": "fact_check | policy_proposal | accountability | information_request | other"
      },
      "answer": {
        "summary": "- 要点1\n- 要点2\n- 要点3",
        "utterance_indices": [3, 4, 5],
        "evasion_score": 0.0から1.0,
        "has_commitment": true | false,
        "commitment_text": "具体的な約束事項（has_commitmentがtrueの場合）"
      }
    }
  ]
}

evasion_scoreの目安:
- 0.0-0.2: 具体的な数値・事実で回答
- 0.3-0.5: 一般論で回答、具体性に欠ける
- 0.6-0.8: 質問をはぐらかす、別の話題にすり替える
- 0.9-1.0: 完全に回避、「答えられない」等
"""

SUMMARY_SYSTEM_PROMPT = """あなたは国会会議の要約を作成する専門家です。
セッション全体のutterancesとQ&Aペアから、以下のJSON形式で要約を生成してください:

{
  "session_summary": "セッション全体の概要（3-5文）",
  "key_topics": ["主要トピック1", "主要トピック2", ...],
  "key_commitments": [
    {
      "speaker": "発言者名",
      "role": "役職",
      "text": "約束・コミットメントの内容",
      "topic": "関連トピック",
      "qa_id": "関連するQ&AペアのID"
    }
  ]
}
"""

TOPICS_SYSTEM_PROMPT = """あなたは国会質疑のトピック分析を行う専門家です。
Q&Aペアリストからトピックを抽出し、以下のJSON形式で出力してください:

{
  "topics": [
    {
      "name": "トピック名",
      "description": "トピックの説明（1-2文）",
      "related_qa_ids": ["qa_001", "qa_002"],
      "related_speakers": ["発言者名1", "発言者名2"]
    }
  ]
}

トピックは政策領域・法案・社会問題などの観点から分類してください。
"""


def _get_client() -> openai.OpenAI:
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPINFRA_API_KEY environment variable is not set")
    return openai.OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)


def _format_numbered_utterances(seg: SegmentUtterances) -> str:
    """utterancesに番号を振ってLLMプロンプト用にテキスト化する。"""
    lines: list[str] = []
    lines.append(f"セグメント発言者: {seg.segment_speaker}（{seg.segment_affiliation}）")
    lines.append("")
    for i, u in enumerate(seg.utterances):
        lines.append(f"[{i}] [{u.role}] {u.speaker}: {u.text}")
    return "\n".join(lines)


def _format_segments_for_prompt(segments: list[SegmentUtterances]) -> str:
    """全セグメントをLLMプロンプト用にテキスト化する。"""
    lines: list[str] = []
    for seg in segments:
        lines.append(f"\n--- セグメント {seg.segment_index}: {seg.segment_speaker}（{seg.segment_affiliation}）---")
        for u in seg.utterances:
            lines.append(f"[{u.role}] {u.speaker}: {u.text}")
    return "\n".join(lines)


def _assemble_full_text(seg: SegmentUtterances, indices: list[int]) -> str:
    """utterance_indicesからfull_textを機械的に組み立てる。"""
    valid_indices = [i for i in indices if 0 <= i < len(seg.utterances)]
    if not valid_indices:
        # フォールバック: インデックスが無効な場合、セグメント全体を返す
        return "\n".join(u.text for u in seg.utterances)
    return "\n".join(seg.utterances[i].text for i in valid_indices)


def _resolve_speaker_info(
    seg: SegmentUtterances,
    indices: list[int],
    speakers_lookup: dict[str, SpeakerInfo],
) -> tuple[str, str]:
    """utterance_indicesから質疑者のspeakerとparty(=affiliation)を取得する。"""
    valid = [i for i in indices if 0 <= i < len(seg.utterances)]
    if valid:
        name = seg.utterances[valid[0]].speaker
        info = speakers_lookup.get(name)
        if info:
            return info.name, info.affiliation
        return name, seg.segment_affiliation
    return seg.segment_speaker, seg.segment_affiliation


def _resolve_answerer_info(
    seg: SegmentUtterances,
    indices: list[int],
    speakers_lookup: dict[str, SpeakerInfo],
) -> tuple[str, str]:
    """utterance_indicesから答弁者のspeakerとrole(=affiliation)を取得する。"""
    valid = [i for i in indices if 0 <= i < len(seg.utterances)]
    if valid:
        name = seg.utterances[valid[0]].speaker
        info = speakers_lookup.get(name)
        if info:
            return info.name, info.affiliation
        return name, ""
    return "", ""


def _is_qa_segment(seg: SegmentUtterances) -> bool:
    """セグメントがQ&A抽出対象かどうかを判定する。

    質疑者の発言が含まれるセグメントのみ対象。
    議長の開会宣言や大臣の趣旨説明はスキップ。
    """
    has_questioner = any(u.role == "質疑者" for u in seg.utterances)
    if has_questioner:
        return True

    # 質疑者ロールがなくても、実質的な質疑が行われているセグメントを拾う
    # （role tagging が不完全な場合のフォールバック）
    roles = {u.role for u in seg.utterances}
    if "答弁者" in roles and roles - {"答弁者", "委員長"}:
        return True

    return False


def _generate_qa_for_segment(
    seg: SegmentUtterances,
    session_context: str,
    speakers_lookup: dict[str, SpeakerInfo],
) -> list[QAPair]:
    """1セグメントからQ&Aペアを生成する。

    LLMにはutterance_indicesと判断のみ返させ、full_textはコードで組み立てる。
    """
    client = _get_client()

    numbered_text = _format_numbered_utterances(seg)
    user_prompt = (
        f"以下は国会質疑の1つの発言セグメントです。"
        f"この発言者の持ち時間で行われた質疑応答を**すべて**Q&Aペアとして抽出してください。\n"
        f"utterance_indicesには入力の[N]の番号を使ってください。\n\n"
        f"セッション情報: {session_context}\n\n"
        f"{numbered_text}"
    )

    logger.info(
        "Generating Q&A pairs for segment %d: %s (%d utterances, %d chars)",
        seg.segment_index,
        seg.segment_speaker,
        len(seg.utterances),
        sum(len(u.text) for u in seg.utterances),
    )

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": QA_SEGMENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    if not content:
        logger.warning("Empty response for segment %d", seg.segment_index)
        return []

    data = json.loads(content)
    raw_pairs = data.get("pairs", [])

    # utterance_indicesから full_text, speaker, party, role を機械的に組み立て
    pairs: list[QAPair] = []
    for p in raw_pairs:
        q = p.get("question", {})
        a = p.get("answer", {})

        q_indices = q.get("utterance_indices", [])
        a_indices = a.get("utterance_indices", [])
        q_full_text = _assemble_full_text(seg, q_indices)
        a_full_text = _assemble_full_text(seg, a_indices)

        # speaker/party/role を元データから取得（最初のutteranceから）
        q_speaker, q_party = _resolve_speaker_info(seg, q_indices, speakers_lookup)
        a_speaker, a_role = _resolve_answerer_info(seg, a_indices, speakers_lookup)

        pairs.append(
            QAPair(
                id="",  # 後でマージ時に付番
                segment_index=seg.segment_index,
                topic=p.get("topic", ""),
                question=QuestionDetail(
                    speaker=q_speaker,
                    party=q_party,
                    summary=q.get("summary", ""),
                    full_text=q_full_text,
                    intent=q.get("intent", "other"),
                ),
                answer=AnswerDetail(
                    speaker=a_speaker,
                    role=a_role,
                    summary=a.get("summary", ""),
                    full_text=a_full_text,
                    evasion_score=max(0.0, min(1.0, float(a.get("evasion_score", 0.5)))),
                    has_commitment=bool(a.get("has_commitment", False)),
                    commitment_text=a.get("commitment_text", ""),
                ),
                video_url=seg.video_url,
            )
        )

    logger.info(
        "Segment %d (%s): extracted %d Q&A pairs",
        seg.segment_index,
        seg.segment_speaker,
        len(pairs),
    )
    return pairs


def generate_qa_pairs(
    utterances: UtterancesOutput,
    speakers: list[SpeakerInfo] | None = None,
    max_workers: int = 16,
) -> QAPairsOutput:
    """全セグメントからQ&Aペアを生成する（セグメント単位で並列処理）。

    Args:
        utterances: 話者タグ付き発言データ
        speakers: metadata.jsonのspeakers（名前→役職の解決に使用）
        max_workers: 並列数
    """

    # speakers_lookup: 名前 → SpeakerInfo
    speakers_lookup: dict[str, SpeakerInfo] = {}
    if speakers:
        for s in speakers:
            speakers_lookup[s.name] = s

    # セッションコンテキスト（各LLM呼び出しに共有）
    all_speakers = set()
    for seg in utterances.segments:
        for u in seg.utterances:
            all_speakers.add(u.speaker)
    session_context = f"発言者: {', '.join(sorted(all_speakers))}"

    # Q&A対象セグメントを選別
    qa_segments = [seg for seg in utterances.segments if _is_qa_segment(seg)]
    skipped = len(utterances.segments) - len(qa_segments)
    logger.info(
        "Processing %d Q&A segments (skipped %d procedural segments)",
        len(qa_segments),
        skipped,
    )

    if not qa_segments:
        return QAPairsOutput(pairs=[])

    # セグメント単位で並列にLLM呼び出し
    segment_results: dict[int, list[QAPair]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_generate_qa_for_segment, seg, session_context, speakers_lookup): seg
            for seg in qa_segments
        }
        for future in as_completed(futures):
            seg = futures[future]
            try:
                pairs = future.result()
                segment_results[seg.segment_index] = pairs
            except Exception as e:
                logger.error(
                    "Failed to generate Q&A for segment %d (%s): %s",
                    seg.segment_index,
                    seg.segment_speaker,
                    e,
                )
                segment_results[seg.segment_index] = []

    # セグメント順にマージし、通し番号を付与
    all_pairs: list[QAPair] = []
    pair_counter = 0
    for seg in sorted(qa_segments, key=lambda s: s.segment_index):
        for pair in segment_results.get(seg.segment_index, []):
            pair_counter += 1
            pair.id = f"qa_{pair_counter:03d}"
            all_pairs.append(pair)

    logger.info("Total Q&A pairs generated: %d (from %d segments)", len(all_pairs), len(qa_segments))
    return QAPairsOutput(pairs=all_pairs)


def generate_summary(
    utterances: UtterancesOutput,
    qa_pairs: QAPairsOutput,
) -> SummaryOutput:
    """utterancesとQ&AペアからセッションサマリーのJSONを生成する。"""
    client = _get_client()

    segments_text = _format_segments_for_prompt(utterances.segments)
    qa_text = "\n".join(
        f"[{p.id}] {p.topic}: {p.question.summary} → {p.answer.summary}"
        for p in qa_pairs.pairs
    )

    user_prompt = (
        f"以下の国会質疑の要約を生成してください。\n\n"
        f"## Q&Aペア一覧\n{qa_text}\n\n"
        f"## 全発言\n{segments_text}"
    )

    logger.info("Generating session summary")

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from LLM")

    data = json.loads(content)

    commitments: list[KeyCommitment] = []
    for c in data.get("key_commitments", []):
        commitments.append(
            KeyCommitment(
                speaker=c.get("speaker", ""),
                role=c.get("role", ""),
                text=c.get("text", ""),
                topic=c.get("topic", ""),
                qa_id=c.get("qa_id", ""),
            )
        )

    return SummaryOutput(
        session_summary=data.get("session_summary", ""),
        key_topics=data.get("key_topics", []),
        key_commitments=commitments,
    )


def generate_topics(qa_pairs: QAPairsOutput) -> TopicsOutput:
    """Q&AペアからトピックリストのJSONを生成する。"""
    client = _get_client()

    qa_text = "\n".join(
        f"[{p.id}] トピック: {p.topic}\n  質問者: {p.question.speaker}（{p.question.party}）\n  要旨: {p.question.summary}"
        for p in qa_pairs.pairs
    )

    user_prompt = f"以下のQ&Aペアからトピックを抽出・整理してください:\n\n{qa_text}"

    logger.info("Generating topics")

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": TOPICS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from LLM")

    data = json.loads(content)

    topics: list[Topic] = []
    for t in data.get("topics", []):
        topics.append(
            Topic(
                name=t.get("name", ""),
                description=t.get("description", ""),
                related_qa_ids=t.get("related_qa_ids", []),
                related_speakers=t.get("related_speakers", []),
            )
        )

    return TopicsOutput(topics=topics)
