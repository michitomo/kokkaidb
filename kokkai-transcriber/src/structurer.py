"""LLM Q&Aペア生成・要約・トピック抽出 (DeepInfra DeepSeek V3.2)

セグメント単位で並列にQ&Aペアを生成し、抜け漏れを防止する。
LLMには utterance_indices と判断のみ返させ、full_text はコードが
utterance 全文を連結して組み立てる (docs/STRUCTURER_REWRITE.md §2.1 / Appendix A)。
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from src.api_client import get_client as _get_client
from src.api_client import with_retry
from src.models import (
    AnswerDetail,
    KeyCommitment,
    QAMetrics,
    QAPair,
    QAPairsOutput,
    QuestionDetail,
    RelatedLawTag,
    SegmentUtterances,
    SpeakerInfo,
    Topic,
    TopicsOutput,
    UtterancesOutput,
)
from src.prompts import (
    COMMITMENTS_SYSTEM_PROMPT,
    LAW_TAGGING_SYSTEM_PROMPT,
    QA_METRICS_V4_SYSTEM_PROMPT,
    QA_METRICS_V4_USER_TEMPLATE,
    QA_SEGMENT_SYSTEM_PROMPT,
    SESSION_SUMMARY_SYSTEM_PROMPT,
    TOPICS_FROM_UTTERANCES_SYSTEM_PROMPT,
    TOPICS_SYSTEM_PROMPT,
)
from src.speaker_lookup import find_by_name

# Step 6はgemma-4-31bを使用（ペア数抽出がV3.2より安定: 10/10 vs 6/10）
STRUCTURER_MODEL = "google/gemma-4-31B-it"

# 答弁本文がこの長さ未満かつ utterance_indices が空のペアは Q&A として成立していないため drop
MIN_ANSWER_LENGTH = 30

# 長文 utterance 判定 (sentence sub-number `(sN)` を併記する閾値)
# 代表質問・所信表明など共有 utterance 候補のみ対象。99% の utterance は素のテキストのみ
_LONG_UTTERANCE_CHARS = 800
_LONG_UTTERANCE_SENTENCES = 8

# プロンプトが極端に長くなったときの警告閾値 (block 分割不足の検知用)
_PROMPT_TEXT_WARN_THRESHOLD = 50000

logger = logging.getLogger(__name__)


def _split_sentences(text: str) -> list[str]:
    """テキストを文単位に分割する。句点・疑問符・感嘆符で分割。"""
    parts = re.split(r'(?<=[。？！])', text)
    result = [p.strip() for p in parts if p.strip()]
    return result if result else [text]


@dataclass
class _SegmentLayout:
    """セグメント内の utterance / sentence マッピング情報。

    LLM プロンプト構築 (`_build_utterance_map`) と full_text 組み立て
    (`_assemble_full_text_for_pair`) の両方で参照する。
    """

    per_utt_sentences: list[list[str]]  # [u_idx][local_sent_idx] -> sentence text
    utt_global_starts: list[int]  # [u_idx] -> 最初の sentence の global index
    total_sentences: int
    is_long_utt: list[bool]  # [u_idx] -> sentence sub-number を出すか


def _compute_segment_layout(seg: SegmentUtterances) -> _SegmentLayout:
    per_utt: list[list[str]] = [_split_sentences(u.text) for u in seg.utterances]
    starts: list[int] = []
    is_long: list[bool] = []
    cur = 0
    for sentences, u in zip(per_utt, seg.utterances, strict=True):
        starts.append(cur)
        cur += len(sentences)
        is_long.append(
            len(u.text) >= _LONG_UTTERANCE_CHARS
            or len(sentences) >= _LONG_UTTERANCE_SENTENCES
        )
    return _SegmentLayout(
        per_utt_sentences=per_utt,
        utt_global_starts=starts,
        total_sentences=cur,
        is_long_utt=is_long,
    )


def _build_utterance_map(seg: SegmentUtterances, layout: _SegmentLayout) -> str:
    """セグメントを `[U0]`, `[U1]`, ... の番号付きテキストに整形する。

    長文 utterance のみ sentence サブ番号 `(sN)` をグローバル通番で併記。
    LLM はこの番号を `utterance_indices` / `split_anchor_sentence_idx` に
    そのまま使う。
    """
    lines: list[str] = [
        f"セグメント発言者: {seg.segment_speaker}（{seg.segment_affiliation}）",
        "",
    ]
    for i, u in enumerate(seg.utterances):
        lines.append(f"[U{i}] [{u.role}] {u.speaker}:")
        if layout.is_long_utt[i]:
            start = layout.utt_global_starts[i]
            for j, s in enumerate(layout.per_utt_sentences[i]):
                lines.append(f"  (s{start + j}) {s}")
        else:
            lines.append(f"  {u.text}")
        lines.append("")
    return "\n".join(lines)


def _format_segments_for_prompt(segments: list[SegmentUtterances]) -> str:
    """全セグメントをLLMプロンプト用にテキスト化する。"""
    lines: list[str] = []
    for seg in segments:
        lines.append(f"\n--- セグメント {seg.segment_index}: {seg.segment_speaker}（{seg.segment_affiliation}）---")
        for u in seg.utterances:
            lines.append(f"[{u.role}] {u.speaker}: {u.text}")
    return "\n".join(lines)


def _assemble_full_text_for_pair(
    seg: SegmentUtterances,
    layout: _SegmentLayout,
    utterance_indices: list[int],
    split_anchor_sentence_idx: int | None,
    boundary_global_idx: int | None,
) -> str:
    """utterance_indices と anchor から full_text を機械的に組み立てる。

    - `split_anchor_sentence_idx` が None: 全 utterance の text を改行連結 (99% のケース)
    - anchor あり: 先頭 utterance を anchor で slice し、後続 utterance は丸ごと連結。
      `boundary_global_idx` は同じ utterance を共有する次のペアの anchor (排他的境界)。
    """
    valid_uidx = [i for i in utterance_indices if 0 <= i < len(seg.utterances)]
    if not valid_uidx:
        return ""

    if split_anchor_sentence_idx is None:
        return "\n".join(seg.utterances[i].text for i in valid_uidx)

    head_uidx = valid_uidx[0]
    sentences = layout.per_utt_sentences[head_uidx]
    g_start = layout.utt_global_starts[head_uidx]

    local_anchor = max(0, split_anchor_sentence_idx - g_start)
    if local_anchor >= len(sentences):
        # 範囲外 anchor は信頼できないので utterance 全文にフォールバック
        head_text = "".join(sentences)
    else:
        if boundary_global_idx is not None:
            local_end = max(local_anchor, boundary_global_idx - g_start)
            local_end = min(local_end, len(sentences))
        else:
            local_end = len(sentences)
        head_text = "".join(sentences[local_anchor:local_end])

    if len(valid_uidx) == 1:
        return head_text
    rest = "\n".join(seg.utterances[i].text for i in valid_uidx[1:])
    return f"{head_text}\n{rest}" if head_text else rest


def _compute_share_boundaries(
    parsed_pairs: list[dict[str, Any]], side: str
) -> list[int | None]:
    """同一 head utterance を共有するペアの anchor 順序から境界を求める。

    side: "q" or "a"。各ペアの (uidx_key, anchor_key) を見て、anchor を持つペアが
    同じ head utterance に複数あれば anchor 昇順でソートし、各ペアの境界を
    「次のペアの anchor」とする。最後のペアは None (utterance 末尾まで)。
    """
    uidx_key = f"{side}_uidx"
    anchor_key = f"{side}_anchor"

    shared: dict[int, list[tuple[int, int]]] = {}
    for i, p in enumerate(parsed_pairs):
        uidx = p[uidx_key]
        anchor = p[anchor_key]
        if not uidx or anchor is None or not isinstance(anchor, int):
            continue
        head = uidx[0]
        shared.setdefault(head, []).append((i, anchor))

    boundaries: list[int | None] = [None] * len(parsed_pairs)
    for items in shared.values():
        if len(items) <= 1:
            continue
        items.sort(key=lambda x: x[1])
        for j, (pair_idx, _) in enumerate(items):
            boundaries[pair_idx] = items[j + 1][1] if j + 1 < len(items) else None
    return boundaries


def _fuzzy_lookup(name: str, speakers_lookup: dict[str, SpeakerInfo]) -> SpeakerInfo | None:
    """完全一致 → 姓一致で speaker 情報を取得する（structurer 互換ラッパー）。"""
    return find_by_name(name, speakers_lookup, allow_single_char=True)


def _resolve_speaker_from_utterances(
    seg: SegmentUtterances,
    utterance_indices: list[int],
    speakers_lookup: dict[str, SpeakerInfo],
) -> tuple[str, str]:
    """utterance_indices から質疑者の speaker と party(=affiliation) を取得する。"""
    valid = [i for i in utterance_indices if 0 <= i < len(seg.utterances)]
    if not valid:
        return seg.segment_speaker, seg.segment_affiliation
    name = seg.utterances[valid[0]].speaker
    info = _fuzzy_lookup(name, speakers_lookup)
    if info:
        return info.name, info.affiliation
    return name, seg.segment_affiliation


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


def _resolve_answerer_from_utterances(
    seg: SegmentUtterances,
    utterance_indices: list[int],
    speakers_lookup: dict[str, SpeakerInfo],
) -> tuple[str, str]:
    """utterance_indices から答弁者の speaker と role(=affiliation) を取得する。

    議員が答弁者として選ばれた場合は、同じ utterance 範囲内で「議員でない」発言者
    （大臣・政府参考人）を探す。見つからなければ議員のまま返す（ログで警告）。
    """
    valid = [i for i in utterance_indices if 0 <= i < len(seg.utterances)]
    if not valid:
        return "", ""

    head = valid[0]
    name = seg.utterances[head].speaker
    info = _fuzzy_lookup(name, speakers_lookup)
    candidate_name = info.name if info else name
    candidate_aff = info.affiliation if info else ""

    if not _is_member_of_parliament(candidate_aff):
        return candidate_name, candidate_aff

    for ui in valid:
        alt_name = seg.utterances[ui].speaker
        alt_info = _fuzzy_lookup(alt_name, speakers_lookup)
        alt_aff = alt_info.affiliation if alt_info else ""
        if alt_name != candidate_name and not _is_member_of_parliament(alt_aff):
            logger.info(
                "Corrected answerer: %s (%s) → %s (%s)",
                candidate_name, candidate_aff,
                alt_info.name if alt_info else alt_name, alt_aff,
            )
            return (alt_info.name if alt_info else alt_name), alt_aff

    logger.warning(
        "MP '%s' (%s) resolved as answerer but no non-MP alternative found in utterance range",
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
    layout: _SegmentLayout,
    speakers_lookup: dict[str, SpeakerInfo],
) -> list[QAPair]:
    """LLM レスポンスをパースして QAPair リストを組み立てる。

    新スキーマ (utterance_indices + 任意 split_anchor_sentence_idx) を解釈し、
    full_text は `_assemble_full_text_for_pair` がコード側で組み立てる。
    """
    if not content:
        logger.warning("Empty response for segment %d", seg.segment_index)
        return []

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM JSON for segment %d: %s", seg.segment_index, e)
        return []
    raw_pairs = data.get("pairs", []) or []

    parsed_pairs: list[dict[str, Any]] = []
    for p in raw_pairs:
        q = p.get("question") or {}
        a = p.get("answer") or {}
        parsed_pairs.append({
            "topic": p.get("topic", "") or "",
            "q_uidx": [int(x) for x in (q.get("utterance_indices") or []) if isinstance(x, int)],
            "q_anchor": q.get("split_anchor_sentence_idx"),
            "q_summary": q.get("summary", "") or "",
            "q_intent": q.get("intent", "other") or "other",
            "a_uidx": [int(x) for x in (a.get("utterance_indices") or []) if isinstance(x, int)],
            "a_anchor": a.get("split_anchor_sentence_idx"),
            "a_summary": a.get("summary", "") or "",
        })

    q_boundaries = _compute_share_boundaries(parsed_pairs, "q")
    a_boundaries = _compute_share_boundaries(parsed_pairs, "a")

    n_utterances = len(seg.utterances)
    indices_total = 0
    indices_out_of_range = 0

    pairs: list[QAPair] = []
    dropped_short = 0
    dropped_empty_q = 0
    for i, p in enumerate(parsed_pairs):
        # 範囲外 utterance_indices の比率を計測 (LLM hallucination 検知)
        for side_uidx in (p["q_uidx"], p["a_uidx"]):
            for idx in side_uidx:
                indices_total += 1
                if idx < 0 or idx >= n_utterances:
                    indices_out_of_range += 1

        q_full = _assemble_full_text_for_pair(
            seg, layout, p["q_uidx"], p["q_anchor"], q_boundaries[i],
        )
        a_full = _assemble_full_text_for_pair(
            seg, layout, p["a_uidx"], p["a_anchor"], a_boundaries[i],
        )

        if len(a_full) < MIN_ANSWER_LENGTH and not p["a_uidx"]:
            dropped_short += 1
            continue
        # 質問本文が空かつ utterance_indices も空なら Q&A として成立しない (PR10, ISSUES2 §1-2)
        if not q_full and not p["q_uidx"]:
            dropped_empty_q += 1
            continue

        q_speaker, q_party = _resolve_speaker_from_utterances(seg, p["q_uidx"], speakers_lookup)
        a_speaker, a_role = _resolve_answerer_from_utterances(seg, p["a_uidx"], speakers_lookup)

        pairs.append(
            QAPair(
                id="",  # 後でマージ時に付番
                segment_index=seg.segment_index,
                topic=p["topic"],
                question=QuestionDetail(
                    speaker=q_speaker,
                    party=q_party,
                    summary=p["q_summary"],
                    full_text=q_full,
                    intent=p["q_intent"],
                ),
                answer=AnswerDetail(
                    speaker=a_speaker,
                    role=a_role,
                    summary=p["a_summary"],
                    full_text=a_full,
                ),
                video_url=seg.video_url,
            )
        )

    # 範囲外 indices 比率が 50% 超なら LLM が utterance 番号を hallucinate している
    # 可能性が高い (PR10, §2.10)
    if indices_total > 0:
        oor_ratio = indices_out_of_range / indices_total
        if oor_ratio > 0.5:
            logger.warning(
                "Segment %d: %d/%d (%.0f%%) utterance_indices out of range — "
                "LLM may have hallucinated indices",
                seg.segment_index,
                indices_out_of_range,
                indices_total,
                oor_ratio * 100,
            )

    # 受理/drop 統計サマリ (PR10, §2.10)
    logger.info(
        "Segment %d: parsed %d raw → kept %d pairs (drop_short=%d, drop_empty_q=%d, "
        "oor_idx=%d/%d)",
        seg.segment_index,
        len(parsed_pairs),
        len(pairs),
        dropped_short,
        dropped_empty_q,
        indices_out_of_range,
        indices_total,
    )
    return pairs


def _generate_qa_for_segment(
    seg: SegmentUtterances,
    session_context: str,
    speakers_lookup: dict[str, SpeakerInfo],
) -> list[QAPair]:
    """1セグメントから Q&A ペアを生成する。

    LLM には utterance_indices と判断のみ返させ、full_text はコードで組み立てる。
    QA 密度が低い場合は 1 回リトライする。
    """
    client = _get_client()

    layout = _compute_segment_layout(seg)
    prompt_text = _build_utterance_map(seg, layout)
    total_chars = sum(len(u.text) for u in seg.utterances)

    if len(prompt_text) > _PROMPT_TEXT_WARN_THRESHOLD:
        logger.warning(
            "Segment %d prompt text very large (%d chars). "
            "Block-splitting may be insufficient — investigate.",
            seg.segment_index,
            len(prompt_text),
        )

    base_user_prompt = (
        f"以下は国会質疑の1つの発言セグメントです。"
        f"この発言者の持ち時間で行われた質疑応答を**すべて**Q&Aペアとして抽出してください。\n"
        f"utterance_indices には入力の [Un] の番号を使ってください。"
        f"split_anchor_sentence_idx は通常 null。1つの utterance を複数ペアで共有する場合のみ "
        f"(sN) のグローバル番号を入れてください。\n\n"
        f"セッション情報: {session_context}\n\n"
        f"{prompt_text}"
    )

    logger.info(
        "Generating Q&A pairs for segment %d: %s (%d utterances, %d chars)",
        seg.segment_index,
        seg.segment_speaker,
        len(seg.utterances),
        total_chars,
    )

    def _qa_call(prompt: str, tokens: int, temperature: float) -> Any:
        return with_retry(lambda: client.chat.completions.create(
            model=STRUCTURER_MODEL,
            messages=[
                {"role": "system", "content": QA_SEGMENT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=tokens,
            response_format={"type": "json_object"},
        ))

    response = _qa_call(base_user_prompt, _MAX_TOKENS_CEILING, 0.1)
    if response.choices[0].finish_reason == "length":
        logger.error(
            "Q&A output still truncated for segment %d at max_tokens=%d",
            seg.segment_index,
            _MAX_TOKENS_CEILING,
        )

    pairs = _extract_pairs_from_response(
        response.choices[0].message.content, seg, layout, speakers_lookup,
    )

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

            retry_response = _qa_call(retry_prompt, _MAX_TOKENS_CEILING, 0.3)
            if retry_response.choices[0].finish_reason == "length":
                logger.warning(
                    "Q&A density-retry output truncated for segment %d at max_tokens=%d",
                    seg.segment_index,
                    _MAX_TOKENS_CEILING,
                )

            retry_pairs = _extract_pairs_from_response(
                retry_response.choices[0].message.content, seg, layout, speakers_lookup,
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
    skip_proposal_segments: bool = False,
) -> QAPairsOutput:
    """全セグメントからQ&Aペアを生成する（セグメント単位で並列処理）。

    Args:
        utterances: 話者タグ付き発言データ
        speakers: metadata.jsonのspeakers（名前→役職の解決に使用）
        max_workers: 並列数
        skip_proposal_segments: True なら、最初の質疑者 segment より前の答弁者 segment を
            Q&A 抽出から除外する（本会議代表質問の冒頭の趣旨説明スキップ用）。
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

    target_segments = (
        _drop_leading_proposal_segments(utterances.segments)
        if skip_proposal_segments
        else utterances.segments
    )

    # Q&A対象セグメントを選別し、委員長指名で質疑ブロックに分割
    qa_blocks: list[SegmentUtterances] = []
    skipped = 0
    for seg in target_segments:
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


def _drop_leading_proposal_segments(
    segments: list[SegmentUtterances],
) -> list[SegmentUtterances]:
    """最初の質疑者 segment より前の答弁者 segment を除外する（代表質問の趣旨説明スキップ用）。"""
    first_questioner_idx = next(
        (
            i
            for i, seg in enumerate(segments)
            if any(u.role == "質疑者" for u in seg.utterances)
        ),
        None,
    )
    if first_questioner_idx is None:
        return segments
    if first_questioner_idx == 0:
        return segments
    leading = segments[:first_questioner_idx]
    is_only_proposal = all(
        all(u.role == "答弁者" for u in seg.utterances) for seg in leading if seg.utterances
    )
    if not is_only_proposal:
        return segments
    return segments[first_questioner_idx:]


def _format_qa_pairs_for_prompt(qa_pairs: QAPairsOutput) -> str:
    lines = []
    for p in qa_pairs.pairs:
        role_part = f"（{p.answer.role}）" if p.answer.role else ""
        lines.append(
            f"[{p.id}] トピック: {p.topic}\n"
            f"  質問者: {p.question.speaker}（{p.question.party}）\n"
            f"  質問要旨: {p.question.summary}\n"
            f"  回答者: {p.answer.speaker}{role_part}\n"
            f"  回答要旨: {p.answer.summary}"
        )
    return "\n".join(lines)


_MAX_TOKENS_CEILING = 16384


def _call_structurer(
    system_prompt: str, user_prompt: str, *, max_tokens: int, temperature: float = 0.1
) -> dict:
    client = _get_client()

    def _do_call(tokens: int) -> Any:
        return with_retry(
            lambda: client.chat.completions.create(
                model=STRUCTURER_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=tokens,
                response_format={"type": "json_object"},
            )
        )

    response = _do_call(max_tokens)
    finish_reason = response.choices[0].finish_reason
    if finish_reason == "length":
        retry_tokens = min(max_tokens * 2, _MAX_TOKENS_CEILING)
        logger.warning(
            "Output truncated (finish_reason=length, max_tokens=%d), retrying with max_tokens=%d",
            max_tokens,
            retry_tokens,
        )
        response = _do_call(retry_tokens)
        if response.choices[0].finish_reason == "length":
            raise ValueError(
                f"Output still truncated after retry with max_tokens={retry_tokens}"
            )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from LLM")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM JSON: {e}") from e
    return data


def generate_session_summary(
    qa_pairs: QAPairsOutput,
    utterances: UtterancesOutput | None = None,
    session_meta: dict | None = None,
) -> str:
    """セッション要約（3-5文）を生成する（Step 6b-1）。

    session_meta で院名・委員会名を渡すと冒頭の種別表記が正確になる。
    使用可能なキー: chamber ("shugiin"|"sangiin"), committee, description (qa_pairs が空の場合のフォールバック)
    """
    if qa_pairs.pairs:
        body = "## Q&Aペア一覧\n" + _format_qa_pairs_for_prompt(qa_pairs)
    elif utterances is not None and utterances.segments:
        body = "## 発言セグメント\n" + _format_segments_for_prompt(utterances.segments)
    elif session_meta and session_meta.get("description"):
        body = "## セッション概要\n" + session_meta["description"]
    else:
        return ""

    meta_prefix = ""
    if session_meta:
        chamber_raw = session_meta.get("chamber", "")
        committee = session_meta.get("committee", "")
        chamber_ja = (
            "衆議院" if chamber_raw == "shugiin"
            else "参議院" if chamber_raw == "sangiin"
            else chamber_raw
        )
        parts = []
        if chamber_ja:
            parts.append(f"院: {chamber_ja}")
        if committee:
            parts.append(f"委員会: {committee}")
        if parts:
            meta_prefix = "## セッション情報\n" + "\n".join(parts) + "\n\n"

    user_prompt = "以下の国会セッションの内容から、概要を作成してください。\n\n" + meta_prefix + body
    data = _call_structurer(SESSION_SUMMARY_SYSTEM_PROMPT, user_prompt, max_tokens=4096)
    summary = data.get("session_summary", "")
    if not isinstance(summary, str):
        return ""
    return summary.strip()


def _parse_topics_data(
    data: dict,
    valid_qa_ids: set[str],
) -> tuple[list[Topic], list[str]]:
    """LLM 出力の topics データを Topic リストに変換する。"""
    topics_list: list[Topic] = []
    for t in data.get("topics", []):
        related_qa_ids = [q for q in (t.get("related_qa_ids") or []) if q in valid_qa_ids]
        related_speakers = [s for s in (t.get("related_speakers") or []) if isinstance(s, str)]
        topics_list.append(Topic(
            name=t.get("name") or "",
            description=t.get("description") or "",
            related_qa_ids=related_qa_ids,
            related_speakers=related_speakers,
        ))
    raw_key_topics = data.get("key_topics") or []
    key_topics = [n for n in raw_key_topics if isinstance(n, str) and n]
    return topics_list, key_topics


def generate_topics_and_key_topics(
    qa_pairs: QAPairsOutput,
) -> tuple[TopicsOutput, list[str]]:
    """topics + key_topics を生成する（Step 6b-2）。

    全 QA ペアを一括で LLM に渡す。
    key_topics は topics[].name のサブセットになるよう post-validate する。
    """
    if not qa_pairs.pairs:
        return TopicsOutput(topics=[]), []

    valid_qa_ids = {p.id for p in qa_pairs.pairs}
    user_prompt = "## Q&Aペア一覧\n" + _format_qa_pairs_for_prompt(qa_pairs)
    data = _call_structurer(TOPICS_SYSTEM_PROMPT, user_prompt, max_tokens=_MAX_TOKENS_CEILING)
    topics_list, raw_key_topics = _parse_topics_data(data, valid_qa_ids)

    valid_topic_names = {t.name for t in topics_list}
    key_topics: list[str] = []
    dropped: list[str] = []
    for name in raw_key_topics:
        if isinstance(name, str) and name in valid_topic_names:
            key_topics.append(name)
        else:
            dropped.append(str(name))
    if dropped:
        logger.warning(
            "generate_topics: dropped %d key_topics not found in topics[].name: %s",
            len(dropped),
            dropped,
        )

    return TopicsOutput(topics=topics_list), key_topics


def generate_topics_without_qa(
    utterances: UtterancesOutput,
) -> tuple[TopicsOutput, list[str]]:
    """utterances から直接 topics + key_topics を生成する (Step 6b-2 fallback)。

    Q&A が抽出されない floor_speech / procedural セッション (所信表明・施政方針演説等)
    でも topics を保持できるようにする。related_qa_ids は空 (QA が存在しないため)。

    Args:
        utterances: 話者タグ付き発言データ

    Returns:
        (topics, key_topics) のペア。utterances が空なら空タプル相当。
    """
    if not utterances.segments:
        return TopicsOutput(topics=[]), []

    user_prompt = (
        "## 発言セグメント (連続発言・所信表明・施政方針演説・趣旨説明等)\n"
        + _format_segments_for_prompt(utterances.segments)
    )
    data = _call_structurer(
        TOPICS_FROM_UTTERANCES_SYSTEM_PROMPT,
        user_prompt,
        max_tokens=_MAX_TOKENS_CEILING,
    )

    topics_list: list[Topic] = []
    for t in data.get("topics", []):
        related_speakers = [
            s for s in (t.get("related_speakers") or []) if isinstance(s, str)
        ]
        topics_list.append(
            Topic(
                name=t.get("name") or "",
                description=t.get("description") or "",
                related_qa_ids=[],
                related_speakers=related_speakers,
            )
        )

    valid_topic_names = {t.name for t in topics_list}
    raw_key_topics = data.get("key_topics") or []
    key_topics: list[str] = []
    dropped: list[str] = []
    for name in raw_key_topics:
        if isinstance(name, str) and name in valid_topic_names:
            key_topics.append(name)
        else:
            dropped.append(str(name))
    if dropped:
        logger.warning(
            "generate_topics_without_qa: dropped %d key_topics not in topics[].name: %s",
            len(dropped),
            dropped,
        )

    return TopicsOutput(topics=topics_list), key_topics


def generate_key_commitments(qa_pairs: QAPairsOutput) -> list[KeyCommitment]:
    """key_commitments を生成する（Step 6b-3）。"""
    if not qa_pairs.pairs:
        return []

    user_prompt = "## Q&Aペア一覧\n" + _format_qa_pairs_for_prompt(qa_pairs)
    data = _call_structurer(COMMITMENTS_SYSTEM_PROMPT, user_prompt, max_tokens=8192)

    valid_qa_ids = {p.id for p in qa_pairs.pairs}
    commitments: list[KeyCommitment] = []
    dropped = 0
    for c in data.get("key_commitments", []):
        qa_id = c.get("qa_id") or ""
        if qa_id and qa_id not in valid_qa_ids:
            dropped += 1
            continue
        commitments.append(
            KeyCommitment(
                speaker=c.get("speaker") or "",
                role=c.get("role") or "",
                text=c.get("text") or "",
                topic=c.get("topic") or "",
                qa_id=qa_id or None,
            )
        )
    if dropped:
        logger.warning(
            "generate_key_commitments: dropped %d commitments referencing unknown qa_id",
            dropped,
        )
    return commitments


def tag_related_laws(
    qa_pairs: QAPairsOutput,
    *,
    chamber: str,
    committee: str,
    date: str,
    laws_text: str,
    max_workers: int = 16,
) -> QAPairsOutput:
    """各 Q&A ペアに対し関連法案 ID を判定し、QAPair.related_law_ids に書き戻す（Step 6c）。"""
    if not qa_pairs.pairs or not laws_text:
        return qa_pairs

    chamber_ja = "衆議院" if chamber == "shugiin" else "参議院" if chamber == "sangiin" else chamber
    context = (
        f"## セッション情報\n"
        f"院: {chamber_ja}\n"
        f"委員会: {committee}\n"
        f"日付: {date}\n\n"
        f"## 法案一覧（このセッションで議論される可能性が高い順に提示）\n{laws_text}\n\n"
    )

    def tag_one(pair: QAPair) -> tuple[str, list[str]]:
        user_prompt = (
            context
            + "## 対象 Q&A ペア\n"
            + f"id: {pair.id}\n"
            + f"トピック: {pair.topic}\n"
            + f"質問: {pair.question.summary}\n"
            + f"答弁: {pair.answer.summary}"
        )
        try:
            data = _call_structurer(LAW_TAGGING_SYSTEM_PROMPT, user_prompt, max_tokens=512)
        except Exception as e:
            logger.warning("tag_related_laws failed for %s: %s", pair.id, e)
            return pair.id, []
        raw = data.get("law_ids") or []
        return pair.id, [law for law in raw if isinstance(law, str) and law]

    results: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(tag_one, p): p.id for p in qa_pairs.pairs}
        for future in as_completed(futures):
            pid, law_ids = future.result()
            results[pid] = law_ids

    for pair in qa_pairs.pairs:
        pair.related_law_ids = results.get(pair.id, [])

    tagged = sum(1 for p in qa_pairs.pairs if p.related_law_ids)
    logger.info(
        "tag_related_laws: tagged %d/%d pairs with related laws", tagged, len(qa_pairs.pairs)
    )
    return qa_pairs


def build_summary_related_laws(qa_pairs: QAPairsOutput) -> list[RelatedLawTag]:
    """qa_pairs.related_law_ids を集約して summary.related_laws を作る（幽霊タグは drop）。"""
    by_law: dict[str, list[str]] = {}
    for pair in qa_pairs.pairs:
        for law_id in pair.related_law_ids:
            by_law.setdefault(law_id, []).append(pair.id)
    return [
        RelatedLawTag(law_id=law_id, qa_ids=qa_ids)
        for law_id, qa_ids in by_law.items()
        if qa_ids
    ]


# V4評価プロンプトはDeepSeek V3.1を使用
_METRICS_MODEL = "google/gemma-4-31B-it"


def _score_one_pair(pair: QAPair) -> QAMetrics | None:
    """1ペアをV4プロンプトで評価してQAMetricsを返す。失敗時はNoneを返す。"""
    if not pair.question.full_text or not pair.answer.full_text:
        logger.warning("score_qa_pairs_metrics: skipping %s (empty text)", pair.id)
        return None

    user_msg = QA_METRICS_V4_USER_TEMPLATE.format(
        intent=pair.question.intent or "other",
        question_text=pair.question.full_text,
        answer_text=pair.answer.full_text,
    )

    client = _get_client()

    def _call() -> dict:
        response = client.chat.completions.create(
            model=_METRICS_MODEL,
            messages=[
                {"role": "system", "content": QA_METRICS_V4_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        return json.loads(raw)

    try:
        data = with_retry(_call)
        return QAMetrics.model_validate(data)
    except Exception as e:
        logger.warning("score_qa_pairs_metrics: failed for %s: %s", pair.id, e)
        return None


def score_qa_pairs_metrics(
    qa_pairs: QAPairsOutput,
    *,
    max_workers: int = 8,
) -> QAPairsOutput:
    """全Q&AペアにV4評価指標を付与して QAPairsOutput を返す（Step 6d）。

    各ペアに QAMetrics を並列で付与する。失敗したペアは metrics=None のまま保持する。
    成功した場合は score_schema_version="2.0", prompt_version="V4" を設定する。
    """
    if not qa_pairs.pairs:
        return qa_pairs

    scored: dict[str, QAMetrics | None] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_score_one_pair, p): p.id for p in qa_pairs.pairs}
        for future in as_completed(futures):
            pid = futures[future]
            try:
                scored[pid] = future.result()
            except Exception as e:
                logger.warning("score_qa_pairs_metrics: unexpected error for %s: %s", pid, e)
                scored[pid] = None

    success = 0
    for pair in qa_pairs.pairs:
        pair.metrics = scored.get(pair.id)
        if pair.metrics is not None:
            success += 1

    if success > 0:
        qa_pairs.score_schema_version = "2.0"
        qa_pairs.prompt_version = "V4"

    logger.info(
        "score_qa_pairs_metrics: scored %d/%d pairs with V4 metrics",
        success,
        len(qa_pairs.pairs),
    )
    return qa_pairs
