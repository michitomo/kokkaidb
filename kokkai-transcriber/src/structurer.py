"""LLM Q&Aペア生成・要約・トピック抽出 (DeepInfra DeepSeek V3.2)

セグメント単位で並列にQ&Aペアを生成し、抜け漏れを防止する。
LLMにはutterance_indicesと判断のみ返させ、full_textはコードで組み立てる。
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.api_client import get_client as _get_client, LLM_MODEL, DEEPINFRA_BASE_URL, with_retry

# Step 6はgemma-4-31Bを使用（ペア数抽出がV3.2より安定: 10/10 vs 6/10）
STRUCTURER_MODEL = "google/gemma-4-31B-it"

from src.models import (
    AnswerDetail,
    KeyCommitment,
    QAPair,
    QAPairsOutput,
    QuestionDetail,
    RelatedLawTag,
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
- roleラベル（[委員長]等）は話者タグ付けの結果であり、誤分類の場合がある。roleではなく**発言の内容**でQ&Aを判断すること
- 委員長の指名（「〇〇君。」）の直後に政策への質問・意見が続く場合、それは質疑者の発言である

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

SUMMARY_AND_TOPICS_SYSTEM_PROMPT = """あなたは国会会議の分析専門家です。
セッション全体のutterancesとQ&Aペアから、要約・トピック分析・関連法案タグ付けを一括で行ってください。

以下のJSON形式で出力してください:

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
  ],
  "topics": [
    {
      "name": "トピック名",
      "description": "トピックの説明（1-2文）",
      "related_qa_ids": ["qa_001", "qa_002"],
      "related_speakers": ["発言者名1", "発言者名2"]
    }
  ],
  "related_laws": [
    {
      "law_id": "law_001",
      "qa_ids": ["qa_001", "qa_003"]
    }
  ]
}

## トピック抽出ルール
- 政策領域・法案・社会問題などの観点から分類する

## 関連法案タグ付けルール
- 法案一覧が提供された場合、各Q&Aペアが実質的にどの法案に関連するかを判断する
- 法案名がtopicに含まれる場合だけでなく、質疑の内容・文脈から関連する法案を幅広く判断する
- 確信度が低いものは含めない（明らかに関連するもののみ）
- 法案一覧が提供されない場合、related_lawsは空配列を返す
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


# 政党名パターン: このいずれかが所属に含まれていれば議員（答弁者にはならない）
_PARTY_KEYWORDS = frozenset([
    "自由民主党", "立憲民主党", "日本維新の会", "公明党", "日本共産党",
    "国民民主党", "チームみらい", "参政党", "れいわ新選組", "日本保守党",
    "社会民主党", "中道改革連合", "無所属",
])


def _is_member_of_parliament(affiliation: str) -> bool:
    """所属から国会議員かどうかを判定する。委員長は議事進行なので議員扱いしない。"""
    if not affiliation:
        return False
    if affiliation.endswith("委員長") or affiliation.endswith("議長"):
        return False
    return any(p in affiliation for p in _PARTY_KEYWORDS)


def _resolve_answerer_from_sentences(
    seg: SegmentUtterances,
    sentence_indices: list[int],
    sent_to_utt: list[int],
    speakers_lookup: dict[str, SpeakerInfo],
) -> tuple[str, str]:
    """sentence_indicesから答弁者のspeakerとrole(=affiliation)を取得する。

    議員が答弁者として選ばれた場合は、同じsentence範囲内で「答弁者」roleを持つ
    別の発言者（大臣・政府参考人）を探す。見つからなければ議員のまま返す（ログで警告）。
    """
    valid = [i for i in sentence_indices if 0 <= i < len(sent_to_utt)]
    if not valid:
        return "", ""

    # 最初のsentenceの発言者を候補に
    u_idx = sent_to_utt[valid[0]]
    name = seg.utterances[u_idx].speaker
    info = _fuzzy_lookup(name, speakers_lookup)
    candidate_name = info.name if info else name
    candidate_aff = info.affiliation if info else ""

    # 議員でなければそのまま返す
    if not _is_member_of_parliament(candidate_aff):
        return candidate_name, candidate_aff

    # 議員が答弁者に → 同範囲内で非議員の発言者を探す
    seen_utt_indices = {sent_to_utt[i] for i in valid if 0 <= i < len(sent_to_utt)}
    for ui in sorted(seen_utt_indices):
        alt_name = seg.utterances[ui].speaker
        alt_info = _fuzzy_lookup(alt_name, speakers_lookup)
        alt_aff = alt_info.affiliation if alt_info else ""
        if alt_name != candidate_name and not _is_member_of_parliament(alt_aff):
            logger.info(
                "Corrected answerer: %s (%s) → %s (%s)",
                candidate_name, candidate_aff, alt_info.name if alt_info else alt_name, alt_aff,
            )
            return (alt_info.name if alt_info else alt_name), alt_aff

    # 見つからない場合はそのまま返すが警告
    logger.warning(
        "MP '%s' (%s) resolved as answerer but no non-MP alternative found in sentence range",
        candidate_name, candidate_aff,
    )
    return candidate_name, candidate_aff


# ---------------------------------------------------------------------------
# 案B: 委員長指名による質疑ブロック分割
# ---------------------------------------------------------------------------
# TVのタイムスタンプは質疑者単位だが、1セグメント内に複数の質疑者が
# 含まれることがある。委員長の指名発言（「次に〇〇君。」「〇〇君。」）を
# 境界として質疑ブロックに分割し、Q&A生成をブロック単位で行う。

_CHAIR_NOMINATION_RE = re.compile(
    r"^(?:次に)?(.+?)[君さ](?:ん)?[。.]?\s*$"
)


def _split_segment_into_blocks(seg: SegmentUtterances) -> list[SegmentUtterances]:
    """委員長の質疑者交代指名を境界としてセグメントを質疑ブロックに分割する。

    委員長が「次に〇〇君。」「〇〇君。」と発言している箇所を検出し、
    **その後の質疑者が直前ブロックの質疑者と異なる場合のみ**ブロックを分割する。
    同じ質疑者への続行指名（答弁後に「〇〇君。」と戻す）では分割しない。
    """
    # まず各 utterance の質疑者を特定するために、セグメント内の質疑者の変遷を追跡
    # 委員長指名の位置を検出
    candidate_splits: list[tuple[int, str]] = []  # (utterance_index_after_nomination, nominated_name)
    for i, u in enumerate(seg.utterances):
        if u.role != "委員長":
            continue
        text = u.text.strip()
        m = _CHAIR_NOMINATION_RE.match(text)
        if m and i + 1 < len(seg.utterances):
            nominated_name = m.group(1).strip()
            candidate_splits.append((i + 1, nominated_name))

    if not candidate_splits:
        return [seg]

    # 各候補分割点で、実際に質疑者が変わるかを確認
    def _find_questioner_before(idx: int) -> str:
        """idx より前の最後の質疑者名を返す。"""
        for j in range(idx - 1, -1, -1):
            if seg.utterances[j].role == "質疑者":
                return seg.utterances[j].speaker
        return ""

    def _find_questioner_after(idx: int) -> str:
        """idx 以降の最初の質疑者名を返す。"""
        for j in range(idx, len(seg.utterances)):
            if seg.utterances[j].role == "質疑者":
                return seg.utterances[j].speaker
        return ""

    split_points: list[int] = []
    for utt_idx, _nominated in candidate_splits:
        before = _find_questioner_before(utt_idx)
        after = _find_questioner_after(utt_idx)
        if before and after and before != after:
            split_points.append(utt_idx)

    if not split_points:
        return [seg]

    # 先頭が0でなければ追加（最初のブロック）
    if split_points[0] != 0:
        split_points = [0] + split_points

    split_points = sorted(set(split_points))

    if len(split_points) <= 1:
        return [seg]

    blocks: list[SegmentUtterances] = []
    for idx, start in enumerate(split_points):
        end = split_points[idx + 1] if idx + 1 < len(split_points) else len(seg.utterances)
        block_utterances = seg.utterances[start:end]
        if not block_utterances:
            continue

        questioners = [u.speaker for u in block_utterances if u.role == "質疑者"]
        block_speaker = questioners[0] if questioners else seg.segment_speaker

        blocks.append(SegmentUtterances(
            segment_index=seg.segment_index,
            segment_speaker=block_speaker,
            segment_affiliation=seg.segment_affiliation,
            start_seconds=seg.start_seconds,
            video_url=seg.video_url,
            utterances=block_utterances,
        ))

    if not blocks:
        return [seg]

    if len(blocks) > 1:
        logger.info(
            "Split segment %d (%s) into %d blocks: %s",
            seg.segment_index,
            seg.segment_speaker,
            len(blocks),
            ", ".join(b.segment_speaker for b in blocks),
        )

    return blocks


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


# QA密度チェックの閾値
_MIN_QA_DENSITY = 0.5   # 1000文字あたり最低0.5ペア
_QA_DENSITY_RETRY_HINT = (
    "\n\n【注意】前回の抽出ではQ&Aペアが{prev_count}個しか得られませんでした（{total_chars}文字のセグメント）。"
    "roleラベルに頼らず発言内容から判断し、すべてのQ&Aペアを漏れなく抽出してください。"
)


def _extract_pairs_from_response(
    content: str | None,
    seg: SegmentUtterances,
    all_sentences: list[str],
    speakers_lookup: dict[str, SpeakerInfo],
) -> list[QAPair]:
    """LLMレスポンスをパースしてQAPairリストを組み立てる。"""
    if not content:
        logger.warning("Empty response for segment %d", seg.segment_index)
        return []

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM JSON for segment %d: %s", seg.segment_index, e)
        return []
    raw_pairs = data.get("pairs", [])

    sent_to_utt = _build_sentence_to_utterance_map(seg)
    pairs: list[QAPair] = []
    for p in raw_pairs:
        q = p.get("question", {})
        a = p.get("answer", {})

        q_indices = q.get("sentence_indices", [])
        a_indices = a.get("sentence_indices", [])
        q_full_text = _assemble_full_text_from_sentences(all_sentences, q_indices)
        a_full_text = _assemble_full_text_from_sentences(all_sentences, a_indices)

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
    return pairs


def _generate_qa_for_segment(
    seg: SegmentUtterances,
    session_context: str,
    speakers_lookup: dict[str, SpeakerInfo],
) -> list[QAPair]:
    """1セグメントからQ&Aペアを生成する。

    LLMにはutterance_indicesと判断のみ返させ、full_textはコードで組み立てる。
    QA密度が低い場合は1回リトライする。
    """
    client = _get_client()

    sentence_text, all_sentences = _build_sentence_map(seg)
    total_chars = sum(len(u.text) for u in seg.utterances)

    base_user_prompt = (
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
        total_chars,
    )

    response = with_retry(lambda: client.chat.completions.create(
        model=STRUCTURER_MODEL,
        messages=[
            {"role": "system", "content": QA_SEGMENT_SYSTEM_PROMPT},
            {"role": "user", "content": base_user_prompt},
        ],
        temperature=0.1,
        max_tokens=8192,
        response_format={"type": "json_object"},
    ))

    pairs = _extract_pairs_from_response(
        response.choices[0].message.content, seg, all_sentences, speakers_lookup,
    )

    # QA密度チェック: 低密度ならリトライ（1回のみ）
    if total_chars >= 2000:
        density = len(pairs) / (total_chars / 1000)
        if density < _MIN_QA_DENSITY:
            logger.warning(
                "Low Q&A density for segment %d (%s): "
                "%d pairs / %d chars (density=%.2f < %.2f), retrying",
                seg.segment_index, seg.segment_speaker,
                len(pairs), total_chars, density, _MIN_QA_DENSITY,
            )
            retry_hint = _QA_DENSITY_RETRY_HINT.format(
                prev_count=len(pairs), total_chars=total_chars,
            )
            retry_prompt = base_user_prompt + retry_hint

            retry_response = with_retry(lambda: client.chat.completions.create(
                model=STRUCTURER_MODEL,
                messages=[
                    {"role": "system", "content": QA_SEGMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": retry_prompt},
                ],
                temperature=0.3,  # リトライ時はやや高めで多様性を出す
                max_tokens=8192,
                response_format={"type": "json_object"},
            ))

            retry_pairs = _extract_pairs_from_response(
                retry_response.choices[0].message.content, seg, all_sentences, speakers_lookup,
            )

            if len(retry_pairs) > len(pairs):
                logger.info(
                    "Retry improved segment %d: %d → %d pairs",
                    seg.segment_index, len(pairs), len(retry_pairs),
                )
                pairs = retry_pairs
            else:
                logger.info(
                    "Retry did not improve segment %d: %d → %d pairs, keeping original",
                    seg.segment_index, len(pairs), len(retry_pairs),
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

    # Q&A対象セグメントを選別し、委員長指名で質疑ブロックに分割
    qa_blocks: list[SegmentUtterances] = []
    skipped = 0
    for seg in utterances.segments:
        if not _is_qa_segment(seg):
            skipped += 1
            continue
        blocks = _split_segment_into_blocks(seg)
        for block in blocks:
            if _is_qa_segment(block):
                qa_blocks.append(block)

    logger.info(
        "Processing %d Q&A blocks (from %d segments, skipped %d procedural)",
        len(qa_blocks),
        len(utterances.segments),
        skipped,
    )

    if not qa_blocks:
        return QAPairsOutput(pairs=[])

    # ブロック単位で並列にLLM呼び出し
    block_results: list[tuple[int, int, list[QAPair]]] = []  # (seg_index, block_order, pairs)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_generate_qa_for_segment, block, session_context, speakers_lookup): (i, block)
            for i, block in enumerate(qa_blocks)
        }
        for future in as_completed(futures):
            block_order, block = futures[future]
            try:
                pairs = future.result()
                block_results.append((block.segment_index, block_order, pairs))
            except Exception as e:
                logger.error(
                    "Failed to generate Q&A for block %d (%s): %s",
                    block.segment_index,
                    block.segment_speaker,
                    e,
                )
                block_results.append((block.segment_index, block_order, []))

    # セグメント順 → ブロック順にマージし、通し番号を付与
    block_results.sort(key=lambda x: (x[0], x[1]))
    all_pairs: list[QAPair] = []
    pair_counter = 0
    for _seg_idx, _block_order, pairs in block_results:
        for pair in pairs:
            pair_counter += 1
            pair.id = f"qa_{pair_counter:03d}"
            all_pairs.append(pair)

    logger.info("Total Q&A pairs generated: %d (from %d blocks)", len(all_pairs), len(qa_blocks))
    return QAPairsOutput(pairs=all_pairs)


def generate_summary_and_topics(
    utterances: UtterancesOutput,
    qa_pairs: QAPairsOutput,
    laws_text: str = "",
) -> tuple[SummaryOutput, TopicsOutput]:
    """要約・トピック・関連法案タグを1回のLLM呼び出しで生成する。

    Args:
        utterances: 話者タグ付き発言データ
        qa_pairs: Q&Aペア
        laws_text: 法案一覧テキスト（空の場合は法案タグ付けをスキップ）

    Returns:
        (SummaryOutput, TopicsOutput) のタプル
    """
    client = _get_client()

    qa_text = "\n".join(
        f"[{p.id}] トピック: {p.topic}\n  質問者: {p.question.speaker}（{p.question.party}）\n  質問要旨: {p.question.summary}\n  回答要旨: {p.answer.summary}"
        for p in qa_pairs.pairs
    )

    user_prompt = (
        f"以下の国会質疑のQ&Aペア一覧を分析してください。\n\n"
        f"## Q&Aペア一覧\n{qa_text}"
    )
    if laws_text:
        user_prompt += f"\n\n## 法案一覧\n{laws_text}"

    logger.info("Generating summary, topics, and law tags (unified)")

    response = with_retry(lambda: client.chat.completions.create(
        model=STRUCTURER_MODEL,
        messages=[
            {"role": "system", "content": SUMMARY_AND_TOPICS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=8192,
        response_format={"type": "json_object"},
    ))

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from LLM")

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM JSON for summary+topics: {e}") from e

    # SummaryOutput
    commitments: list[KeyCommitment] = []
    for c in data.get("key_commitments", []):
        commitments.append(
            KeyCommitment(
                speaker=c.get("speaker") or "",
                role=c.get("role") or "",
                text=c.get("text") or "",
                topic=c.get("topic") or "",
                qa_id=c.get("qa_id") or "",
            )
        )

    related_laws: list[RelatedLawTag] = []
    for rl in data.get("related_laws", []):
        law_id = rl.get("law_id") or ""
        if law_id:
            related_laws.append(
                RelatedLawTag(
                    law_id=law_id,
                    qa_ids=rl.get("qa_ids") or [],
                )
            )

    summary = SummaryOutput(
        session_summary=data.get("session_summary", ""),
        key_topics=data.get("key_topics", []),
        key_commitments=commitments,
        related_laws=related_laws,
    )

    # TopicsOutput
    topics_list: list[Topic] = []
    for t in data.get("topics", []):
        topics_list.append(
            Topic(
                name=t.get("name") or "",
                description=t.get("description") or "",
                related_qa_ids=t.get("related_qa_ids") or [],
                related_speakers=t.get("related_speakers") or [],
            )
        )

    topics = TopicsOutput(topics=topics_list)

    logger.info(
        "Unified output: %d topics, %d commitments, %d law tags",
        len(topics_list),
        len(commitments),
        len(related_laws),
    )

    return summary, topics


def generate_summary(
    utterances: UtterancesOutput,
    qa_pairs: QAPairsOutput,
) -> SummaryOutput:
    """後方互換ラッパー: generate_summary_and_topicsを呼び出す。"""
    summary, _ = generate_summary_and_topics(utterances, qa_pairs)
    return summary


def generate_topics(qa_pairs: QAPairsOutput) -> TopicsOutput:
    """後方互換ラッパー: generate_summary_and_topicsを呼び出す。

    注意: この関数はutterancesなしで呼ばれるため、空のUtterancesOutputを使う。
    新規コードではgenerate_summary_and_topicsを直接使うこと。
    """
    from src.models import UtterancesOutput as UO
    dummy_utterances = UO(segments=[])
    _, topics = generate_summary_and_topics(dummy_utterances, qa_pairs)
    return topics
