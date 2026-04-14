"""LLM Q&Aペア生成・要約・トピック抽出 (DeepInfra DeepSeek V3.2)"""

from __future__ import annotations

import json
import logging
import os

import openai

from src.models import (
    AnswerDetail,
    KeyCommitment,
    QAPair,
    QAPairsOutput,
    QuestionDetail,
    SegmentUtterances,
    SummaryOutput,
    Topic,
    TopicsOutput,
    UtterancesOutput,
)

logger = logging.getLogger(__name__)

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
LLM_MODEL = "deepseek-ai/DeepSeek-V3.2"

QA_SYSTEM_PROMPT = """あなたは国会質疑のQ&Aペアを生成する専門家です。
発言者セグメントのutterancesリストから、質疑応答ペアを抽出・構造化してください。

以下のJSON形式で出力してください:
{
  "pairs": [
    {
      "topic": "質疑テーマ（簡潔に）",
      "question": {
        "speaker": "質疑者名",
        "party": "所属政党・会派",
        "summary": "質問の要旨（1-2文）",
        "full_text": "質問の全文",
        "intent": "fact_check | policy_proposal | accountability | information_request | other"
      },
      "answer": {
        "speaker": "答弁者名",
        "role": "答弁者の役職",
        "summary": "答弁の要旨（1-2文）",
        "full_text": "答弁の全文",
        "evasion_score": 0.0から1.0（0=明確回答、1=完全回避）,
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


def _format_segments_for_prompt(segments: list[SegmentUtterances]) -> str:
    """LLMプロンプト用にセグメントをテキスト化する。"""
    lines: list[str] = []
    for seg in segments:
        lines.append(f"\n--- セグメント {seg.segment_index}: {seg.segment_speaker}（{seg.segment_affiliation}）---")
        for u in seg.utterances:
            lines.append(f"[{u.role}] {u.speaker}: {u.text}")
    return "\n".join(lines)


def generate_qa_pairs(utterances: UtterancesOutput) -> QAPairsOutput:
    """utterancesからQ&Aペアを生成する。"""
    client = _get_client()

    segments_text = _format_segments_for_prompt(utterances.segments)
    user_prompt = f"以下の国会質疑からQ&Aペアを生成してください:\n{segments_text}"

    logger.info("Generating Q&A pairs for %d segments", len(utterances.segments))

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": QA_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from LLM")

    data = json.loads(content)
    pairs_data = data.get("pairs", [])

    pairs: list[QAPair] = []
    for i, p in enumerate(pairs_data):
        qa_id = f"qa_{i + 1:03d}"
        q = p.get("question", {})
        a = p.get("answer", {})

        # セグメントインデックスはutterancesから対応付け
        seg_idx = _find_segment_index(utterances.segments, q.get("speaker", ""))

        # 対応するビデオURLを取得
        video_url = ""
        if seg_idx < len(utterances.segments):
            video_url = utterances.segments[seg_idx].video_url

        pairs.append(
            QAPair(
                id=qa_id,
                segment_index=seg_idx,
                topic=p.get("topic", ""),
                question=QuestionDetail(
                    speaker=q.get("speaker", ""),
                    party=q.get("party", ""),
                    summary=q.get("summary", ""),
                    full_text=q.get("full_text", ""),
                    intent=q.get("intent", "other"),
                ),
                answer=AnswerDetail(
                    speaker=a.get("speaker", ""),
                    role=a.get("role", ""),
                    summary=a.get("summary", ""),
                    full_text=a.get("full_text", ""),
                    evasion_score=max(0.0, min(1.0, float(a.get("evasion_score", 0.5)))),
                    has_commitment=bool(a.get("has_commitment", False)),
                    commitment_text=a.get("commitment_text", ""),
                ),
                video_url=video_url,
            )
        )

    return QAPairsOutput(pairs=pairs)


def _find_segment_index(segments: list[SegmentUtterances], speaker_name: str) -> int:
    """発言者名からセグメントインデックスを探す。見つからない場合は 0 を返す。"""
    for seg in segments:
        for u in seg.utterances:
            if u.speaker == speaker_name:
                return seg.segment_index
    return 0


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
