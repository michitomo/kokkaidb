"""QA_SEGMENT_SYSTEM_PROMPT ベンチマークデータ生成スクリプト

現行プロンプトの課題を網羅した7パターンのsegmentベンチマークを生成する。

生成ファイル:
    eval/golden/qa_seg_{N}_{pattern}.input.json   - LLMへの入力
    eval/golden/qa_seg_{N}_{pattern}.expected.json - 期待出力（sentence_indices形式）

Usage:
    cd kokkai-transcriber
    python -m eval.generate_qa_segment_benchmark
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# src.prompts を参照するためパスを追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.prompts import QA_SEGMENT_SYSTEM_PROMPT  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "shugiin"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。？！])", text)
    return [p.strip() for p in parts if p.strip()]


def build_sentence_map(seg: dict) -> tuple[str, list[str]]:
    """SegmentをLLMプロンプト用テキストと文リストに変換する。"""
    lines: list[str] = []
    lines.append(f"セグメント発言者: {seg['segment_speaker']}（{seg['segment_affiliation']}）")
    lines.append("")
    all_sentences: list[str] = []
    sent_idx = 0
    for u in seg["utterances"]:
        lines.append(f"[{u['role']}] {u['speaker']}:")
        for s in split_sentences(u["text"]):
            lines.append(f"  ({sent_idx}) {s}")
            all_sentences.append(s)
            sent_idx += 1
        lines.append("")
    return "\n".join(lines), all_sentences


def find_sentence_indices(full_text: str, all_sentences: list[str]) -> list[int]:
    """full_textに含まれる文のインデックスを返す。"""
    if not full_text:
        return []
    indices = []
    for i, s in enumerate(all_sentences):
        if len(s) >= 8 and s in full_text:
            indices.append(i)
    return sorted(set(indices))


def load_session(date_path: str, session_name: str) -> tuple[dict, dict]:
    base = DATA_DIR / date_path / session_name
    with open(base / "utterances.json", encoding="utf-8") as f:
        ut = json.load(f)
    with open(base / "qa_pairs.json", encoding="utf-8") as f:
        qa = json.load(f)
    return ut, qa


def pairs_for_segment(qa: dict, seg_index: int) -> list[dict]:
    return [p for p in qa["pairs"] if p["segment_index"] == seg_index]


def convert_pair_to_new_format(
    pair: dict,
    all_sentences: list[str],
) -> dict | None:
    """旧フォーマット（full_text）から新フォーマット（sentence_indices）に変換する。

    答弁full_textが空のペアはNoneを返す（フィルタリング対象）。
    """
    q_full = pair["question"].get("full_text", "")
    a_full = pair["answer"].get("full_text", "")

    # 答弁が実質的に空のペアはスキップ
    if not a_full or len(a_full.strip()) < 30:
        return None

    q_idx = find_sentence_indices(q_full, all_sentences)
    a_idx = find_sentence_indices(a_full, all_sentences)

    return {
        "topic": pair["topic"],
        "question": {
            "summary": pair["question"].get("summary", ""),
            "sentence_indices": q_idx,
            "intent": pair["question"].get("intent", "other"),
        },
        "answer": {
            "summary": pair["answer"].get("summary", ""),
            "sentence_indices": a_idx,
        },
    }


def build_user_prompt(sentence_text: str, session_context: str) -> str:
    return (
        "以下は国会質疑の1つの発言セグメントです。"
        "この発言者の持ち時間で行われた質疑応答を**すべて**Q&Aペアとして抽出してください。\n"
        "sentence_indicesには入力の(N)の番号を使ってください。\n\n"
        f"セッション情報: {session_context}\n\n"
        f"{sentence_text}"
    )


def save_case(
    case_id: str,
    system_prompt: str,
    user_prompt: str,
    metadata: dict,
    expected_pairs: list[dict],
) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    input_data = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "metadata": metadata,
    }
    expected_data = {"pairs": expected_pairs}

    input_path = GOLDEN_DIR / f"{case_id}.input.json"
    expected_path = GOLDEN_DIR / f"{case_id}.expected.json"

    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(input_data, f, ensure_ascii=False, indent=2)
    with open(expected_path, "w", encoding="utf-8") as f:
        json.dump(expected_data, f, ensure_ascii=False, indent=2)

    n_sents = user_prompt.count("(")
    print(
        f"  wrote: {input_path.name} + {expected_path.name}"
        f" | {len(expected_pairs)} expected pairs | ~{n_sents} sentences"
    )


# ---------------------------------------------------------------------------
# 各ケース生成
# ---------------------------------------------------------------------------

def gen_bench_01_simple_qa() -> None:
    """Case 1: 単純Q&A（2ペア）
    Pattern: 短いセグメント、明確な質疑者・答弁者ロール、2テーマ
    Tests: 基本的なQ&A抽出、sentence_indices形式
    Source: 56179_災害対策特別委員会 Seg 0
    """
    ut, qa = load_session("2026/04/16", "56179_災害対策特別委員会")
    seg = ut["segments"][0]
    sentence_text, all_sentences = build_sentence_map(seg)

    pairs_raw = pairs_for_segment(qa, 0)
    expected: list[dict] = []
    for p in pairs_raw:
        converted = convert_pair_to_new_format(p, all_sentences)
        if converted:
            expected.append(converted)

    session_context = "衆議院 2026-04-16 災害対策特別委員会 発言者: 関芳弘、内閣官房横山次長、小里泰弘"
    save_case(
        "qa_seg_01_simple_qa",
        QA_SEGMENT_SYSTEM_PROMPT,
        build_user_prompt(sentence_text, session_context),
        {
            "session_id": "56179",
            "segment_index": 0,
            "chamber": "shugiin",
            "committee": "災害対策特別委員会",
            "date": "2026-04-16",
            "pattern": "simple_qa",
            "description": (
                "シンプルな2テーマQ&A。明確な質疑者・答弁者ロール。"
                "基本的なsentence_indices抽出の動作確認用。"
            ),
        },
        expected,
    )


def gen_bench_02_multi_topic_committee() -> None:
    """Case 2: 複数テーマ委員会Q&A（3ペア）
    Pattern: 1人の質疑者が長い持ち時間で3つの政策テーマを順次質問
    Tests: テーマ分割の正確性（education / 人材育成 / energy）
    Source: 56089_予算委員会 Seg 3 岸信千世
    """
    ut, qa = load_session("2026/03/03", "56089_予算委員会")
    seg = ut["segments"][3]
    sentence_text, all_sentences = build_sentence_map(seg)

    pairs_raw = pairs_for_segment(qa, 3)
    expected = [
        c for p in pairs_raw
        if (c := convert_pair_to_new_format(p, all_sentences)) is not None
    ]

    all_speakers = sorted({u["speaker"] for u in seg["utterances"]})
    session_context = f"衆議院 2026-03-03 予算委員会 発言者: {', '.join(all_speakers)}"
    save_case(
        "qa_seg_02_multi_topic_committee",
        QA_SEGMENT_SYSTEM_PROMPT,
        build_user_prompt(sentence_text, session_context),
        {
            "session_id": "56089",
            "segment_index": 3,
            "chamber": "shugiin",
            "committee": "予算委員会",
            "date": "2026-03-03",
            "pattern": "multi_topic_committee",
            "description": (
                "岸信千世議員が教育制度・人材育成・エネルギー安全保障の3テーマを順次質問。"
                "1発言に複数テーマが混在するケースのテーマ分割精度を検証する。"
            ),
        },
        expected,
    )


def gen_bench_03_procedural_zero_pairs() -> None:
    """Case 3: 趣旨説明セグメント（期待ペア数=0）
    Pattern: 大臣が法案の趣旨説明をするセグメント（Q&Aではない）
    Tests: 手続き的内容からのペア抽出拒否（過剰抽出の防止）
    Source: 56098_本会議 Seg 1 片山さつき（財務大臣が4法案の趣旨説明）
    Issue: 現行モデルは4ペアを誤抽出している
    """
    ut, qa = load_session("2026/03/05", "56098_本会議")
    seg = ut["segments"][1]
    sentence_text, all_sentences = build_sentence_map(seg)

    session_context = "衆議院 2026-03-05 本会議 発言者: 森英介（議長）、片山さつき（財務大臣）"
    # 期待出力: 0ペア（趣旨説明はQ&A抽出対象外）
    save_case(
        "qa_seg_03_procedural_zero_pairs",
        QA_SEGMENT_SYSTEM_PROMPT,
        build_user_prompt(sentence_text, session_context),
        {
            "session_id": "56098",
            "segment_index": 1,
            "chamber": "shugiin",
            "committee": "本会議",
            "date": "2026-03-05",
            "pattern": "procedural_zero_pairs",
            "description": (
                "片山財務大臣が4本の法案（特例公債法、復興財源法、所得税法、関税法）の"
                "趣旨説明を行うセグメント。Q&A構造が存在しないため期待ペア数は0。"
                "現行モデルはこのセグメントから4ペアを誤抽出する問題がある。"
            ),
            "known_issue": "現行モデルが趣旨説明をQ&Aとして誤抽出",
        },
        [],  # 期待ペア: なし
    )


def gen_bench_04_bureaucrat_answerer() -> None:
    """Case 4: 政府参考人・大臣が混在する答弁（7ペア）
    Pattern: 質疑者が政府参考人（局長）と大臣の両方に交互に質問
    Tests: 答弁者が政府参考人か大臣かの区別（answerer resolution）
    Source: 56112_国土交通委員会 Seg 8 臼木秀剛
    """
    ut, qa = load_session("2026/03/10", "56112_国土交通委員会")
    seg = ut["segments"][8]
    sentence_text, all_sentences = build_sentence_map(seg)

    pairs_raw = pairs_for_segment(qa, 8)
    expected = [
        c for p in pairs_raw
        if (c := convert_pair_to_new_format(p, all_sentences)) is not None
    ]

    all_speakers = sorted({u["speaker"] for u in seg["utterances"]})
    session_context = f"衆議院 2026-03-10 国土交通委員会 発言者: {', '.join(all_speakers)}"
    save_case(
        "qa_seg_04_bureaucrat_answerer",
        QA_SEGMENT_SYSTEM_PROMPT,
        build_user_prompt(sentence_text, session_context),
        {
            "session_id": "56112",
            "segment_index": 8,
            "chamber": "shugiin",
            "committee": "国土交通委員会",
            "date": "2026-03-10",
            "pattern": "bureaucrat_answerer",
            "description": (
                "臼木秀剛議員が道路渋滞・ETC2.0・航空政策について質問。"
                "答弁者が政府参考人（道路局長・航空局長）と金子国土交通大臣で混在する。"
                "sentence_indicesから正しいanswerer（政府参考人 vs 大臣）が特定できるか検証。"
            ),
        },
        expected,
    )


def gen_bench_05_no_answer_filter() -> None:
    """Case 5: 答弁なし質問の除外（実答弁ありペアのみ期待）
    Pattern: 質疑者が「お願いにとどめさせていただく」と発言し答弁を求めない質問がある
    Tests: 答弁が実質的に存在しないペアの除外（フィルタリング）
    Source: 56116_予算委員会 Seg 1 丸川珠代（utterances 0-5のみ使用）
    Issue: 現行モデルは答弁なし qa_003「在宅避難者DX推進」を誤ってペアとして出力する
    """
    ut, qa = load_session("2026/03/11", "56116_予算委員会")
    full_seg = ut["segments"][1]

    # 最初の5発話のみ抽出（広域避難Q&A・ペット同行Q&A・答弁なし質問・消費税Q&A の範囲）
    trimmed_seg = {
        "segment_index": full_seg["segment_index"],
        "segment_speaker": full_seg["segment_speaker"],
        "segment_affiliation": full_seg["segment_affiliation"],
        "start_seconds": full_seg["start_seconds"],
        "video_url": full_seg["video_url"],
        "utterances": full_seg["utterances"][:6],  # 委員長2回 + Q3回 + A3回
    }
    sentence_text, all_sentences = build_sentence_map(trimmed_seg)

    # 期待ペア: qa_001（広域避難）・qa_002（ペット）・qa_004（消費税）のみ
    # qa_003（在宅避難者DX - 答弁なし）は除外
    pairs_raw = pairs_for_segment(qa, 1)
    INCLUDE_IDS = {"qa_001", "qa_002", "qa_004"}
    expected: list[dict] = []
    for p in pairs_raw:
        if p["id"] not in INCLUDE_IDS:
            continue
        converted = convert_pair_to_new_format(p, all_sentences)
        if converted:
            expected.append(converted)

    all_speakers = sorted({u["speaker"] for u in trimmed_seg["utterances"]})
    session_context = f"衆議院 2026-03-11 予算委員会 発言者: {', '.join(all_speakers)}"
    save_case(
        "qa_seg_05_no_answer_filter",
        QA_SEGMENT_SYSTEM_PROMPT,
        build_user_prompt(sentence_text, session_context),
        {
            "session_id": "56116",
            "segment_index": 1,
            "chamber": "shugiin",
            "committee": "予算委員会",
            "date": "2026-03-11",
            "pattern": "no_answer_filter",
            "description": (
                "丸川珠代議員が複数テーマを質問。途中で「このあとお願いにとどめさせていただきます」と"
                "言い答弁を求めずに要望を述べる部分（在宅避難者DX推進）がある。"
                "この「答弁なし」の質問はペアとして出力しないことが正解。"
            ),
            "excluded_pair": {
                "id": "qa_003",
                "topic": "在宅避難者へのニーズ把握に向けたDX推進",
                "reason": "質疑者が答弁を求めず、実際の答弁が存在しない",
            },
            "known_issue": "現行モデルが答弁なしペアをsummary付きで出力する",
        },
        expected,
    )


def gen_bench_06_plenary_qanda() -> None:
    """Case 6: 本会議Q&A（accountability/policy_proposal/fact_check混在）
    Pattern: 本会議での質疑（議員が政府に問う形式）、intents多様
    Tests: intent分類精度（accountability vs policy_proposal の区別）
    Source: 56098_本会議 Seg 5 峰島侑也（チームみらい）
    """
    ut, qa = load_session("2026/03/05", "56098_本会議")
    seg = ut["segments"][5]
    sentence_text, all_sentences = build_sentence_map(seg)

    pairs_raw = pairs_for_segment(qa, 5)
    expected = [
        c for p in pairs_raw
        if (c := convert_pair_to_new_format(p, all_sentences)) is not None
    ]

    all_speakers = sorted({u["speaker"] for u in seg["utterances"]})
    session_context = f"衆議院 2026-03-05 本会議 発言者: {', '.join(all_speakers)}"
    save_case(
        "qa_seg_06_plenary_intent_variety",
        QA_SEGMENT_SYSTEM_PROMPT,
        build_user_prompt(sentence_text, session_context),
        {
            "session_id": "56098",
            "segment_index": 5,
            "chamber": "shugiin",
            "committee": "本会議",
            "date": "2026-03-05",
            "pattern": "plenary_intent_variety",
            "description": (
                "本会議で峰島侑也議員が財政・税制を質問。"
                "intent分類: EBPMによる設備投資税制検証(policy_proposal)・"
                "ひとり親控除所得制限の合理性追及(accountability)・"
                "法人税の国際標準との比較(fact_check)。"
                "accountability intent（責任追及型）の判定精度を検証する。"
            ),
            "intent_note": (
                "qa_038 ひとり親控除の所得制限の合理性と引き上げ → accountability"
                "（政策の合理的根拠の説明責任を問う形式）"
            ),
        },
        expected,
    )


def gen_bench_07_role_label_confusion() -> None:
    """Case 7: 役割ラベル誤分類への対応
    Pattern: role='質疑者'ラベルが付いた発言が実際には大臣の政府説明、
             または役割が不明確で発言内容から質疑者/答弁者を判断する必要がある
    Tests: roleラベルに依存せず発言内容でQ&Aを判断できるか
    Source: 56089_予算委員会 Seg 18 辰巳孝太郎
             （質疑者ロールだが発言が混在、accountability + information_request 混在）
    """
    ut, qa = load_session("2026/03/03", "56089_予算委員会")
    seg = ut["segments"][18]
    sentence_text, all_sentences = build_sentence_map(seg)

    pairs_raw = pairs_for_segment(qa, 18)
    expected = [
        c for p in pairs_raw
        if (c := convert_pair_to_new_format(p, all_sentences)) is not None
    ]

    all_speakers = sorted({u["speaker"] for u in seg["utterances"]})
    session_context = f"衆議院 2026-03-03 予算委員会 発言者: {', '.join(all_speakers)}"

    # Fallback: if this seg has 0 pairs, use a better source
    if not expected:
        # 56133 Seg 7 辰巳孝太郎 (accountability + information_request)
        ut2, qa2 = load_session("2026/03/30", "56133_予算委員会")
        # find a segment with accountability pairs
        for seg2 in ut2["segments"]:
            seg2_pairs = pairs_for_segment(qa2, seg2["segment_index"])
            if any(p["question"]["intent"] == "accountability" for p in seg2_pairs) and len(seg2_pairs) >= 3:
                seg = seg2
                pairs_raw = seg2_pairs
                ut, qa = ut2, qa2
                sentence_text, all_sentences = build_sentence_map(seg)
                expected = [
                    c for p in pairs_raw
                    if (c := convert_pair_to_new_format(p, all_sentences)) is not None
                ]
                all_speakers = sorted({u["speaker"] for u in seg["utterances"]})
                session_context = f"衆議院 2026-03-30 予算委員会 発言者: {', '.join(all_speakers)}"
                break

    save_case(
        "qa_seg_07_role_label_confusion",
        QA_SEGMENT_SYSTEM_PROMPT,
        build_user_prompt(sentence_text, session_context),
        {
            "segment_index": seg["segment_index"],
            "chamber": "shugiin",
            "pattern": "role_label_confusion",
            "description": (
                "role='質疑者'ラベルが付与されているが実際の発言内容が複雑に混在するセグメント。"
                "委員長指名・質疑・答弁が入り混じる高密度なやり取りで、"
                "roleラベルに依存せず発言内容からQ&Aを正確に判断できるかを検証する。"
                "accountabilityとinformation_requestのintentが混在する。"
            ),
        },
        expected,
    )


def gen_bench_08_preamble_background_inclusion() -> None:
    """Case 8: 前置き・背景説明を含む質問のsentence_indices切り出し
    Pattern: 質疑者が挨拶・背景説明を経て複数の政策質問を行う（代表的な国会質疑パターン）
    Tests:
      - 挨拶・自己紹介・感謝文がsentence_indicesから除外されること
      - 背景説明・問題提起文がsentence_indicesに含まれること
      - summaryは実際の問いかけ内容のみを記載し背景説明を含まないこと
    Source: 56214_文部科学委員会 Seg 3 山崎正恭 (デジタル教科書法案質疑) utterances[3:6]

    sentence numbering (after trimming to utterances[3:6]):
      (0) 次に山崎正恭君。     ← 委員長指名
      (1) 山崎君。
      (2) 中道改革連合の山崎正恭です。    ← 自己紹介  → 除外
      (3) 本日も…ありがとうございます。   ← 感謝     → 除外
      (4) 貴重なお時間ですので…          ← 前置き   → 除外
      (5) ギガスクール構想により…        ← 背景説明 → 含める
      (6) 一方で…さまざまな指摘が…      ← 問題提起 → 含める
      (7) こうした状況の中…質問をさせていただきます。← 遷移文 → 含める
      (8) まず、デジタル教科書導入の…    ← 小見出し → 含める
      (9) 法案においてデジタル教科書を…  ← 質問①   → 含める
      (10) デジタル教科書の導入を通じて… ← 質問②   → 含める
      (11) これまでのギガスクール構想の成果と課題を踏まえ… ← 質問③ → 含める
      (12) 松本文部科学大臣。            ← 指名     → 除外
      (13) はい。                        ← 相槌     → 除外
      (14-16) 実質答弁                   → 含める
    """
    ut, qa = load_session("2026/04/24", "56214_文部科学委員会")
    full_seg = ut["segments"][3]  # 山崎正恭

    trimmed_seg = {
        "segment_index": full_seg["segment_index"],
        "segment_speaker": full_seg["segment_speaker"],
        "segment_affiliation": full_seg["segment_affiliation"],
        "start_seconds": full_seg.get("start_seconds", 0),
        "video_url": full_seg.get("video_url", ""),
        "utterances": full_seg["utterances"][3:6],  # 委員長指名 + 山崎Q + 松本A
    }
    sentence_text, all_sentences = build_sentence_map(trimmed_seg)

    # 期待ペア: 手動定義（背景sentence_indicesを含む）
    expected = [
        {
            "topic": "デジタル教科書導入の政策目的と学びの将来像",
            "question": {
                "summary": (
                    "- デジタル教科書の法的位置づけに係る政策目的を政府はどう定義しているか\n"
                    "- 導入を通じて子どもたちのどのような力を育てようとしているか\n"
                    "- GIGAスクール構想の成果・課題を踏まえた学びの将来像を問う"
                ),
                # (5)(6): 背景説明、(7)(8): 遷移・小見出し、(9)(10)(11): 実質質問
                "sentence_indices": [5, 6, 7, 8, 9, 10, 11],
                "intent": "information_request",
            },
            "answer": {
                "summary": (
                    "- 変わるべきものと守るべきものの両輪を大切にすることが重要\n"
                    "- 多様な子どもたちを包摂した主体的・対話的な深い学びの充実を目指す\n"
                    "- デジタル教科書で教科書内容をより分かりやすくし学びの質を高めることが目的"
                ),
                # (12)指名・(13)相槌は除外、(14)(15)(16)が実質答弁
                "sentence_indices": [14, 15, 16],
            },
        }
    ]

    session_context = "衆議院 2026-04-24 文部科学委員会 発言者: 山崎正恭（中道改革連合）、松本文部科学大臣"
    save_case(
        "qa_seg_08_preamble_background_inclusion",
        QA_SEGMENT_SYSTEM_PROMPT,
        build_user_prompt(sentence_text, session_context),
        {
            "session_id": "56214",
            "segment_index": 3,
            "utterances_slice": "3:6",
            "chamber": "shugiin",
            "committee": "文部科学委員会",
            "date": "2026-04-24",
            "pattern": "preamble_background_inclusion",
            "description": (
                "山崎正恭議員がデジタル教科書法案について質問する典型的な国会質疑パターン。"
                "挨拶（自己紹介・感謝・前置き）に続いてGIGAスクール背景説明を行い、"
                "その後に具体的な政策質問を3問連続で行う。"
                "挨拶文をsentence_indicesから除外しつつ背景説明を含めること、"
                "かつsummaryを実質的な問いかけのみに限定することが正解。"
            ),
            "design_note": {
                "exclude_from_indices": "sentences 2-4 (自己紹介・感謝・前置き)",
                "include_in_indices": "sentences 5-7 (背景説明・問題提起・遷移文)",
                "summary_scope": "sentences 9-11 の内容のみ（実質的な問いかけ）",
            },
        },
        expected,
    )


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    print("QA_SEGMENT ベンチマーク生成開始\n")
    print("=" * 60)

    print("\n[1/8] bench_01: シンプルQ&A（単純2ペア）")
    gen_bench_01_simple_qa()

    print("\n[2/8] bench_02: 複数テーマ委員会Q&A（3ペア）")
    gen_bench_02_multi_topic_committee()

    print("\n[3/8] bench_03: 趣旨説明セグメント（0ペア・過剰抽出防止）")
    gen_bench_03_procedural_zero_pairs()

    print("\n[4/8] bench_04: 政府参考人答弁（混在ケース）")
    gen_bench_04_bureaucrat_answerer()

    print("\n[5/8] bench_05: 答弁なし質問の除外")
    gen_bench_05_no_answer_filter()

    print("\n[6/8] bench_06: 本会議Q&A（intent多様性）")
    gen_bench_06_plenary_qanda()

    print("\n[7/8] bench_07: 役割ラベル混乱への対応")
    gen_bench_07_role_label_confusion()

    print("\n[8/8] bench_08: 前置き・背景説明を含む質問のsentence_indices切り出し")
    gen_bench_08_preamble_background_inclusion()

    print("\n" + "=" * 60)
    print("完了。eval/golden/ に以下のファイルが生成されました:")
    for f in sorted(GOLDEN_DIR.glob("qa_seg_*.json")):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
