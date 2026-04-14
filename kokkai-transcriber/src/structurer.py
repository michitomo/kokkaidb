"""LLM Q&Aペア生成・要約・トピック抽出 (DeepInfra DeepSeek V3.2)

セグメント単位で並列にQ&Aペアを生成し、抜け漏れを防止する。
LLMにはutterance_indicesと判断のみ返させ、full_textはコードで組み立てる。
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.api_client import get_client as _get_client, LLM_MODEL, DEEPINFRA_BASE_URL

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

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

QA_SEGMENT_SYSTEM_PROMPT = """あなたは国会質疑のQ&Aペアを構造化する専門家です。
与えられた番号付きutterancesリストから、質疑応答ペアを**すべて**抽出してください。

重要なルール:
- 質疑者が複数のテーマについて質問した場合、テーマごとに別のQ&Aペアを作成すること
- 1つも漏らさずに抽出すること
- full_textは返さないこと。代わりにsentence_indices（文番号の配列）を返すこと
- sentence_indicesは、入力の(N)の番号を配列で指定。そのQ&Aの該当部分の文だけを選ぶこと
- 1つのutteranceに複数テーマが含まれる場合（例: 代表質問）、テーマごとに該当する文だけを選択すること
- summaryは箇条書き（各項目は「- 」で始める）。要点を2-4項目で簡潔に

speaker, party, roleは返さないでください（コードで元データから自動取得します）。

以下のJSON形式で出力してください:
{
  "pairs": [
    {
      "topic": "質疑テーマ（簡潔に）",
      "question": {
        "summary": "- 要点1\n- 要点2\n- 要点3",
        "sentence_indices": [0, 1, 2],
        "intent": "fact_check | policy_proposal | accountability | information_request | other"
      },
      "answer": {
        "summary": "- 要点1\n- 要点2\n- 要点3",
        "sentence_indices": [12, 13, 14],
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


def _split_sentences(text: str) -> list[str]:
    """テキストを文単位に分割する。句点・疑問符・感嘆符で分割。"""
    # Split on sentence-ending punctuation, keeping the delimiter
    parts = re.split(r'(?<=[。？！])', text)
    result = [p.strip() for p in parts if p.strip()]
    return result if result else [text]


def _build_sentence_map(seg: SegmentUtterances) -> tuple[str, list[str]]:
    """セグメント全体の文にフラットな通し番号を振り、プロンプト用テキストと文リストを返す。

    Returns:
        (prompt_text, sentences): 番号付きテキストと文のフラットリスト
    """
    lines: list[str] = []
    lines.append(f"セグメント発言者: {seg.segment_speaker}（{seg.segment_affiliation}）")
    lines.append("")

    all_sentences: list[str] = []
    sent_idx = 0
    for u in seg.utterances:
        lines.append(f"[{u.role}] {u.speaker}:")
        sentences = _split_sentences(u.text)
        for s in sentences:
            lines.append(f"  ({sent_idx}) {s}")
            all_sentences.append(s)
            sent_idx += 1
        lines.append("")

    return "\n".join(lines), all_sentences


def _format_segments_for_prompt(segments: list[SegmentUtterances]) -> str:
    """全セグメントをLLMプロンプト用にテキスト化する。"""
    lines: list[str] = []
    for seg in segments:
        lines.append(f"\n--- セグメント {seg.segment_index}: {seg.segment_speaker}（{seg.segment_affiliation}）---")
        for u in seg.utterances:
            lines.append(f"[{u.role}] {u.speaker}: {u.text}")
    return "\n".join(lines)


def _assemble_full_text_from_sentences(
    all_sentences: list[str], indices: list[int],
) -> str:
    """sentence_indicesからfull_textを機械的に組み立てる。"""
    valid = [i for i in indices if 0 <= i < len(all_sentences)]
    if not valid:
        return ""
    return "".join(all_sentences[i] for i in valid)


_SINGLE_CHAR_SURNAMES = {"林", "森", "原", "関", "堀", "岡", "辻", "塚", "柳", "萩", "菅", "泉", "馬"}


def _fuzzy_lookup(name: str, speakers_lookup: dict[str, SpeakerInfo]) -> SpeakerInfo | None:
    """名前の完全一致 → 姓一致でspeaker情報を取得する。"""
    # 完全一致
    if name in speakers_lookup:
        return speakers_lookup[name]
    # Try common surname lengths: 2-char (most common), then 1-char, then 3-char
    best_match: SpeakerInfo | None = None
    best_prefix_len = 0
    for prefix_len in (2, 1, 3):
        if prefix_len > len(name):
            continue
        # For 1-char prefix, only try if it's a known single-char surname
        if prefix_len == 1 and name[0] not in _SINGLE_CHAR_SURNAMES:
            continue
        prefix = name[:prefix_len]
        for key, info in speakers_lookup.items():
            if key.startswith(prefix) and prefix_len > best_prefix_len:
                best_match = info
                best_prefix_len = prefix_len
        if best_match is not None:
            return best_match
    return None


def _build_sentence_to_utterance_map(seg: SegmentUtterances) -> list[int]:
    """各sentenceがどのutteranceに属するかのマッピングを返す。"""
    mapping: list[int] = []
    for u_idx, u in enumerate(seg.utterances):
        n_sentences = len(_split_sentences(u.text))
        mapping.extend([u_idx] * n_sentences)
    return mapping


def _resolve_speaker_from_sentences(
    seg: SegmentUtterances,
    sentence_indices: list[int],
    sent_to_utt: list[int],
    speakers_lookup: dict[str, SpeakerInfo],
) -> tuple[str, str]:
    """sentence_indicesから質疑者のspeakerとparty(=affiliation)を取得する。"""
    valid = [i for i in sentence_indices if 0 <= i < len(sent_to_utt)]
    if valid:
        u_idx = sent_to_utt[valid[0]]
        name = seg.utterances[u_idx].speaker
        info = _fuzzy_lookup(name, speakers_lookup)
        if info:
            return info.name, info.affiliation
        return name, seg.segment_affiliation
    return seg.segment_speaker, seg.segment_affiliation


def _resolve_answerer_from_sentences(
    seg: SegmentUtterances,
    sentence_indices: list[int],
    sent_to_utt: list[int],
    speakers_lookup: dict[str, SpeakerInfo],
) -> tuple[str, str]:
    """sentence_indicesから答弁者のspeakerとrole(=affiliation)を取得する。"""
    valid = [i for i in sentence_indices if 0 <= i < len(sent_to_utt)]
    if valid:
        u_idx = sent_to_utt[valid[0]]
        name = seg.utterances[u_idx].speaker
        info = _fuzzy_lookup(name, speakers_lookup)
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

    sentence_text, all_sentences = _build_sentence_map(seg)
    user_prompt = (
        f"以下は国会質疑の1つの発言セグメントです。"
        f"この発言者の持ち時間で行われた質疑応答を**すべて**Q&Aペアとして抽出してください。\n"
        f"sentence_indicesには入力の(N)の番号を使ってください。\n\n"
        f"セッション情報: {session_context}\n\n"
        f"{sentence_text}"
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

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM JSON for segment %d: %s", seg.segment_index, e)
        return []
    raw_pairs = data.get("pairs", [])

    # sentence_indicesから full_text, speaker, party, role を機械的に組み立て
    sent_to_utt = _build_sentence_to_utterance_map(seg)
    pairs: list[QAPair] = []
    for p in raw_pairs:
        q = p.get("question", {})
        a = p.get("answer", {})

        q_indices = q.get("sentence_indices", [])
        a_indices = a.get("sentence_indices", [])
        q_full_text = _assemble_full_text_from_sentences(all_sentences, q_indices)
        a_full_text = _assemble_full_text_from_sentences(all_sentences, a_indices)

        # speaker/party/role を元データから取得
        q_speaker, q_party = _resolve_speaker_from_sentences(seg, q_indices, sent_to_utt, speakers_lookup)
        a_speaker, a_role = _resolve_answerer_from_sentences(seg, a_indices, sent_to_utt, speakers_lookup)

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

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM JSON for summary: {e}") from e

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

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM JSON for topics: {e}") from e

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
