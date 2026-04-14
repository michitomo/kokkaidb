"""Phase 1 PoC出力からゴールデン評価データを生成する。

deli_id=56149 の実データを読み込み、speaker_tagger.py / structurer.py と
同一のプロンプトを構築して input.json / expected.json を生成する。

Usage:
    cd kokkai-transcriber
    python -m eval.generate_golden
"""

from __future__ import annotations

import json
from pathlib import Path

# --- paths ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "shugiin" / "2026" / "04" / "09" / "56149_本会議"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# --- system prompts (identical to src/speaker_tagger.py and src/structurer.py) ---

SPEAKER_TAGGING_SYSTEM_PROMPT = """あなたは国会議事録の話者タグ付けを行う専門家です。
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
}"""

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
- 0.9-1.0: 完全に回避、「答えられない」等"""

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
}"""

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

トピックは政策領域・法案・社会問題などの観点から分類してください。"""


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  wrote: {path.relative_to(PROJECT_ROOT)}")


def _format_segments_for_prompt(segments: list[dict]) -> str:
    """structurer.py の _format_segments_for_prompt と同一ロジック。"""
    lines: list[str] = []
    for seg in segments:
        lines.append(
            f"\n--- セグメント {seg['segment_index']}: "
            f"{seg['segment_speaker']}（{seg['segment_affiliation']}）---"
        )
        for u in seg["utterances"]:
            lines.append(f"[{u['role']}] {u['speaker']}: {u['text']}")
    return "\n".join(lines)


def generate_speaker_tagging(
    raw_transcript: dict,
    metadata: dict,
    utterances: dict,
    segment_indices: list[int],
) -> None:
    """speaker_tagger.py の tag_speakers() と同一プロンプトを構築。"""
    speakers = metadata["speakers"]
    speaker_list = "\n".join(
        f"- {s['name']}（{s['affiliation']}）" for s in speakers
    )

    for seg_idx in segment_indices:
        seg = raw_transcript["segments"][seg_idx]
        segment_speaker = speakers[seg_idx]

        # tag_speakers() と同一の user_prompt
        user_prompt = (
            f"セグメントの主発言者: {segment_speaker['name']}"
            f"（{segment_speaker['affiliation']}）\n"
            f"役割: {segment_speaker.get('role') or '質疑者'}\n"
            f"\nこのセッションの発言者一覧:\n"
            f"{speaker_list}\n"
            f"\n以下の文字起こしを話者ごとに分割してください:\n\n"
            f"{seg['text']}"
        )

        input_data = {
            "system_prompt": SPEAKER_TAGGING_SYSTEM_PROMPT,
            "user_prompt": user_prompt,
            "metadata": {
                "session_id": "56149",
                "segment_index": seg_idx,
                "segment_speaker": segment_speaker["name"],
                "description": (
                    f"deli_id=56149 セグメント{seg_idx}"
                    f"（{segment_speaker['name']}）の話者タグ付け"
                ),
            },
        }

        # expected: utterances.json の対応セグメントから utterances 部分のみ
        expected_seg = utterances["segments"][seg_idx]
        expected_data = {
            "utterances": expected_seg["utterances"],
        }

        case_id = f"56149_seg{seg_idx:02d}"
        _save_json(GOLDEN_DIR / f"speaker_tagging_{case_id}.input.json", input_data)
        _save_json(GOLDEN_DIR / f"speaker_tagging_{case_id}.expected.json", expected_data)


def generate_qa_pairs(utterances: dict, qa_pairs: dict) -> None:
    """structurer.py の generate_qa_pairs() と同一プロンプトを構築。"""
    segments_text = _format_segments_for_prompt(utterances["segments"])
    user_prompt = f"以下の国会質疑からQ&Aペアを生成してください:\n{segments_text}"

    input_data = {
        "system_prompt": QA_SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "metadata": {
            "session_id": "56149",
            "description": "deli_id=56149 全セグメントからのQ&Aペア生成",
        },
    }

    # expected: qa_pairs.json のペア部分
    # LLM出力は {"pairs": [...]} で、後処理で id/segment_index/video_url を付加するため
    # expected にはパイプライン最終出力をそのまま使う
    expected_data = qa_pairs

    _save_json(GOLDEN_DIR / "qa_pairs_56149.input.json", input_data)
    _save_json(GOLDEN_DIR / "qa_pairs_56149.expected.json", expected_data)


def generate_summary(
    utterances: dict,
    qa_pairs: dict,
    summary: dict,
) -> None:
    """structurer.py の generate_summary() と同一プロンプトを構築。"""
    segments_text = _format_segments_for_prompt(utterances["segments"])
    qa_text = "\n".join(
        f"[{p['id']}] {p['topic']}: {p['question']['summary']} → {p['answer']['summary']}"
        for p in qa_pairs["pairs"]
    )

    user_prompt = (
        f"以下の国会質疑の要約を生成してください。\n\n"
        f"## Q&Aペア一覧\n{qa_text}\n\n"
        f"## 全発言\n{segments_text}"
    )

    input_data = {
        "system_prompt": SUMMARY_SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "metadata": {
            "session_id": "56149",
            "description": "deli_id=56149 セッション要約生成",
        },
    }

    expected_data = summary

    _save_json(GOLDEN_DIR / "summary_56149.input.json", input_data)
    _save_json(GOLDEN_DIR / "summary_56149.expected.json", expected_data)


def generate_topics(qa_pairs: dict, topics: dict) -> None:
    """structurer.py の generate_topics() と同一プロンプトを構築。"""
    qa_text = "\n".join(
        f"[{p['id']}] トピック: {p['topic']}\n"
        f"  質問者: {p['question']['speaker']}（{p['question']['party']}）\n"
        f"  要旨: {p['question']['summary']}"
        for p in qa_pairs["pairs"]
    )

    user_prompt = f"以下のQ&Aペアからトピックを抽出・整理してください:\n\n{qa_text}"

    input_data = {
        "system_prompt": TOPICS_SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "metadata": {
            "session_id": "56149",
            "description": "deli_id=56149 トピック抽出",
        },
    }

    expected_data = topics

    _save_json(GOLDEN_DIR / "topics_56149.input.json", input_data)
    _save_json(GOLDEN_DIR / "topics_56149.expected.json", expected_data)


def main() -> None:
    print("Loading Phase 1 data...")
    raw_transcript = _load_json(DATA_DIR / "raw_transcript.json")
    metadata = _load_json(DATA_DIR / "metadata.json")
    utterances = _load_json(DATA_DIR / "utterances.json")
    qa_pairs = _load_json(DATA_DIR / "qa_pairs.json")
    summary = _load_json(DATA_DIR / "summary.json")
    topics = _load_json(DATA_DIR / "topics.json")

    print("\nGenerating golden data...")

    print("\n[speaker_tagging] segments 3, 4")
    generate_speaker_tagging(raw_transcript, metadata, utterances, [3, 4])

    print("\n[qa_pairs]")
    generate_qa_pairs(utterances, qa_pairs)

    print("\n[summary]")
    generate_summary(utterances, qa_pairs, summary)

    print("\n[topics]")
    generate_topics(qa_pairs, topics)

    print("\nDone! Golden files generated in eval/golden/")


if __name__ == "__main__":
    main()
