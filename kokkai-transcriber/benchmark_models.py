#!/usr/bin/env python3
"""LLMモデル品質ベンチマーク

既存のDeepSeek-V3.2出力をground truthとして、
GPT-OSS-120B等の代替モデルの品質を各Stepごとに評価する。

使い方:
    cd kokkai-transcriber
    uv run python benchmark_models.py
"""

from __future__ import annotations

import json
import logging
import os
import time
from difflib import SequenceMatcher
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import openai

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

MODELS_TO_TEST = [
    "openai/gpt-oss-120b",
    "google/gemma-4-31B-it",
    "deepseek-ai/DeepSeek-V3.2",
]

REFERENCE_MODEL = "deepseek-ai/DeepSeek-V3.2"

# ベンチマーク対象セッション
SESSION_DIR = Path(__file__).parent.parent / "data/shugiin/2026/04/09/56149_本会議"


def get_client() -> openai.OpenAI:
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPINFRA_API_KEY not set")
    return openai.OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)


def call_llm(client: openai.OpenAI, model: str, system: str, user: str,
             json_mode: bool = False, max_tokens: int = 8192) -> tuple[str, float]:
    """LLM呼び出し。(応答テキスト, 所要秒数)を返す。"""
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    start = time.time()
    resp = client.chat.completions.create(**kwargs)
    elapsed = time.time() - start
    content = resp.choices[0].message.content or ""
    return content.strip(), elapsed


# ---------------------------------------------------------------------------
# Step 4.5: Corrector ベンチマーク
# ---------------------------------------------------------------------------

CORRECTOR_SYSTEM = """あなたは国会議事録の校正専門家です。
Whisper音声認識が生成したテキストを修正してください。

## 修正ルール
1. 句読点の補完: 文末に「。」、疑問文に「？」を補う。読点「、」を適切に挿入する
2. 固有名詞の修正: 議員名・政党名・会派名の誤認識を修正
3. 同音異義語の修正
4. フィラー除去
5. 話者交代箇所で改行

## 禁止事項
- 意味を変えない。要約・省略・追加をしない
- 発言順序を変えない

修正後のテキストのみを返してください。"""


def bench_corrector(client: openai.OpenAI) -> None:
    """Step 4.5 Correctorの品質比較。

    未校正テキスト(whisper_segments結合) → 校正済みテキスト(corrected raw_transcript)
    のペアでground truthを作り、各モデルの出力を比較。
    """
    logger.info("=" * 60)
    logger.info("BENCHMARK: Step 4.5 Corrector")
    logger.info("=" * 60)

    rt = json.loads((SESSION_DIR / "raw_transcript.json").read_text())
    meta = json.loads((SESSION_DIR / "metadata.json").read_text())
    speakers = meta.get("speakers", [])
    speaker_list = "\n".join(f"- {s['name']}（{s.get('affiliation','')}）" for s in speakers)
    committee = meta.get("committee", "")

    # テスト対象: 中サイズのセグメント2つ（短すぎず長すぎず）
    test_segs = []
    for seg in rt["segments"]:
        ws = seg.get("whisper_segments", [])
        if ws and 2000 < len(seg["text"]) < 8000:
            # whisper_segmentsからraw textを復元
            raw_text = "".join(w["text"] for w in ws)
            test_segs.append({
                "index": seg["segment_index"],
                "speaker": seg["speaker_name"],
                "raw_text": raw_text,
                "reference": seg["text"],  # corrected version
            })
    test_segs = test_segs[:2]

    for seg_info in test_segs:
        logger.info("--- Segment %d: %s (%d chars raw) ---",
                     seg_info["index"], seg_info["speaker"], len(seg_info["raw_text"]))

        user_prompt = f"""## セッション情報
委員会: {committee}
主発言者: {seg_info['speaker']}

## 発言者リスト
{speaker_list}

## 修正対象テキスト（Whisper出力）
{seg_info['raw_text']}"""

        ref = seg_info["reference"]

        for model in MODELS_TO_TEST:
            try:
                output, elapsed = call_llm(client, model, CORRECTOR_SYSTEM, user_prompt)
                similarity = SequenceMatcher(None, ref, output).ratio()
                len_ratio = len(output) / len(ref) if ref else 0

                logger.info(
                    "  [%s] %.1fs | similarity=%.3f | len_ratio=%.2f | %d chars",
                    model.split("/")[-1], elapsed, similarity, len_ratio, len(output),
                )

                # 最初の200文字を比較表示
                logger.info("    REF: %s", ref[:150].replace("\n", "\\n"))
                logger.info("    OUT: %s", output[:150].replace("\n", "\\n"))
            except Exception as e:
                logger.error("  [%s] FAILED: %s", model, e)


# ---------------------------------------------------------------------------
# Step 5: Speaker Tagger ベンチマーク
# ---------------------------------------------------------------------------

TAGGER_SYSTEM = """あなたは国会議事録の話者タグ付けを行う専門家です。
番号付きの文リストが与えられます。話者交代ポイントを検出し、各発言の開始文番号・話者名・役割を返してください。

テキスト本体は返さないでください。開始文番号だけで十分です。

## 検出ルール
1. 委員長の指名発言パターン（「〇〇君」「〇〇委員」「〇〇大臣」）で話者交代を検出
2. 答弁冒頭の定型句（「お答えいたします」）で答弁者を検出
3. role: 委員長 / 質疑者 / 答弁者 / 政府参考人 / 参考人 / その他

## 出力形式
{
  "splits": [
    {"start": 0, "speaker": "発言者名", "role": "役割"},
    ...
  ]
}
"""


def bench_speaker_tagger(client: openai.OpenAI) -> None:
    """Step 5 Speaker Taggerの品質比較。

    corrected text → utterances.json の話者分割をground truthとし、
    各モデルのsplits出力と比較。
    """
    logger.info("=" * 60)
    logger.info("BENCHMARK: Step 5 Speaker Tagger")
    logger.info("=" * 60)

    rt = json.loads((SESSION_DIR / "raw_transcript.json").read_text())
    ut = json.loads((SESSION_DIR / "utterances.json").read_text())
    meta = json.loads((SESSION_DIR / "metadata.json").read_text())
    speakers = meta.get("speakers", [])
    speaker_list = "\n".join(f"- {s['name']}（{s.get('affiliation','')}）" for s in speakers)

    # テスト対象: 複数話者が含まれるセグメント
    import re
    test_cases = []
    for seg in rt["segments"]:
        ut_seg = next((u for u in ut["segments"] if u["segment_index"] == seg["segment_index"]), None)
        if ut_seg and len(ut_seg.get("utterances", [])) >= 3:
            # 文分割
            parts = re.split(r'(?<=[。？])|(?<=\n)', seg["text"])
            sentences = [s.strip() for s in parts if s.strip()]
            numbered = "\n".join(f"({i}){s}" for i, s in enumerate(sentences))

            # ground truth: utterancesの話者リスト
            ref_speakers = [(u["speaker"], u["role"]) for u in ut_seg["utterances"]]

            test_cases.append({
                "index": seg["segment_index"],
                "speaker_name": seg["speaker_name"],
                "numbered_text": numbered,
                "n_sentences": len(sentences),
                "ref_speakers": ref_speakers,
                "ref_n_splits": len(ref_speakers),
            })
    test_cases = test_cases[:2]

    for tc in test_cases:
        logger.info("--- Segment %d: %s (%d sentences, ref=%d splits) ---",
                     tc["index"], tc["speaker_name"], tc["n_sentences"], tc["ref_n_splits"])
        logger.info("    REF speakers: %s", [(s, r) for s, r in tc["ref_speakers"]])

        seg_speaker = next(
            (s for s in speakers if s["name"] == tc["speaker_name"]),
            {"name": tc["speaker_name"], "affiliation": ""},
        )
        user_prompt = f"""セグメントの主発言者: {seg_speaker['name']}（{seg_speaker.get('affiliation', '')}）
役割: 質疑者

このセッションの発言者一覧:
{speaker_list}

以下の番号付き文リストの話者交代ポイントを検出してください（{tc['n_sentences']}文）:

{tc['numbered_text']}"""

        for model in MODELS_TO_TEST:
            try:
                output, elapsed = call_llm(client, model, TAGGER_SYSTEM, user_prompt, json_mode=True)
                data = json.loads(output)
                splits = data.get("splits", [])
                out_speakers = [(s.get("speaker", "?"), s.get("role", "?")) for s in splits]

                # 評価: split数の一致 + 話者名の一致率
                n_match = tc["ref_n_splits"]
                speaker_names_ref = set(s for s, _ in tc["ref_speakers"])
                speaker_names_out = set(s for s, _ in out_speakers)
                name_overlap = len(speaker_names_ref & speaker_names_out) / max(len(speaker_names_ref), 1)

                logger.info(
                    "  [%s] %.1fs | splits=%d (ref=%d) | name_overlap=%.2f | speakers=%s",
                    model.split("/")[-1], elapsed,
                    len(splits), n_match, name_overlap,
                    out_speakers,
                )
            except Exception as e:
                logger.error("  [%s] FAILED: %s", model, e)


# ---------------------------------------------------------------------------
# Step 6: Structurer (Q&A) ベンチマーク
# ---------------------------------------------------------------------------

QA_SYSTEM = """あなたは国会質疑のQ&Aペアを構造化する専門家です。
与えられた番号付きutterancesリストから、質疑応答ペアをすべて抽出してください。

重要:
- 質疑者が複数テーマについて質問した場合、テーマごとに別のQ&Aペアを作成
- full_textは返さない。sentence_indices（文番号の配列）を返す
- summaryは箇条書き（各項目は「- 」始まり）

JSON形式:
{
  "pairs": [
    {
      "topic": "テーマ",
      "question": {"summary": "- 要点", "sentence_indices": [0,1], "intent": "..."},
      "answer": {"summary": "- 要点", "sentence_indices": [3,4],
                 "evasion_score": 0.3, "has_commitment": false, "commitment_text": ""}
    }
  ]
}
"""


def bench_structurer(client: openai.OpenAI) -> None:
    """Step 6 Structurerの品質比較。

    utterances → qa_pairs のQ&A抽出をground truthとし、
    各モデルの出力ペア数・トピックの一致度を比較。
    """
    logger.info("=" * 60)
    logger.info("BENCHMARK: Step 6 Structurer (Q&A)")
    logger.info("=" * 60)

    ut = json.loads((SESSION_DIR / "utterances.json").read_text())
    qa = json.loads((SESSION_DIR / "qa_pairs.json").read_text())
    meta = json.loads((SESSION_DIR / "metadata.json").read_text())
    speakers = meta.get("speakers", [])

    # テスト対象: Q&Aが多いセグメント
    # qa_pairsのspeakerからセグメントを特定
    seg_qa_count: dict[str, int] = {}
    for pair in qa["pairs"]:
        sp = pair["question"]["speaker"]
        seg_qa_count[sp] = seg_qa_count.get(sp, 0) + 1

    # 上位2セグメントを選択
    top_speakers = sorted(seg_qa_count.items(), key=lambda x: -x[1])[:2]

    import re
    for speaker_name, ref_count in top_speakers:
        ut_seg = next((s for s in ut["segments"] if s["segment_speaker"] == speaker_name), None)
        if not ut_seg:
            continue

        # utterancesを番号付き文に変換
        all_sentences: list[str] = []
        utt_list_str = ""
        for i, u in enumerate(ut_seg["utterances"]):
            sentences = re.split(r'(?<=[。？！])', u["text"])
            sentences = [s.strip() for s in sentences if s.strip()]
            for s in sentences:
                idx = len(all_sentences)
                all_sentences.append(s)
            utt_list_str += f"\n[{u['role']}] {u['speaker']}:\n"
            utt_list_str += "\n".join(f"({j}){s}" for j, s in enumerate(all_sentences[-len(sentences):], start=len(all_sentences)-len(sentences)))
            utt_list_str += "\n"

        # ground truth
        ref_topics = [p["topic"] for p in qa["pairs"] if p["question"]["speaker"] == speaker_name]

        logger.info("--- Speaker: %s (ref=%d QA pairs) ---", speaker_name, ref_count)
        logger.info("    REF topics: %s", ref_topics)

        user_prompt = f"""セグメント発言者: {speaker_name}
発言者一覧: {', '.join(s['name'] for s in speakers)}

以下の番号付き発言リストからQ&Aペアを抽出してください（{len(all_sentences)}文）:

{utt_list_str}"""

        for model in MODELS_TO_TEST:
            try:
                output, elapsed = call_llm(client, model, QA_SYSTEM, user_prompt, json_mode=True, max_tokens=16384)
                data = json.loads(output)
                pairs = data.get("pairs", [])
                out_topics = [p.get("topic", "?") for p in pairs]

                # 評価: ペア数 + トピックの類似度
                topic_similarity = 0
                if ref_topics and out_topics:
                    # 各refトピックに最も近いoutトピックとの類似度
                    sims = []
                    for rt in ref_topics:
                        best = max(SequenceMatcher(None, rt, ot).ratio() for ot in out_topics)
                        sims.append(best)
                    topic_similarity = sum(sims) / len(sims)

                logger.info(
                    "  [%s] %.1fs | pairs=%d (ref=%d) | topic_sim=%.3f",
                    model.split("/")[-1], elapsed, len(pairs), ref_count, topic_similarity,
                )
                logger.info("    OUT topics: %s", out_topics[:8])
            except Exception as e:
                logger.error("  [%s] FAILED: %s", model, e)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    client = get_client()

    logger.info("Models to test: %s", MODELS_TO_TEST)
    logger.info("Reference model: %s", REFERENCE_MODEL)
    logger.info("Session: %s", SESSION_DIR.name)

    bench_corrector(client)
    bench_speaker_tagger(client)
    bench_structurer(client)

    logger.info("=" * 60)
    logger.info("BENCHMARK COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
