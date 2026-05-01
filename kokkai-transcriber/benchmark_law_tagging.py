#!/usr/bin/env python3
"""法案タグ付けプロンプトのベンチマーク

tests/fixtures/law_tagging_benchmark.json に定義されたテストケースに対して
LLM を呼び出し、related_laws の精度・再現率を測定する。

使い方:
    cd kokkai-transcriber
    source .venv/bin/activate
    python benchmark_law_tagging.py                  # 全ケース実行
    python benchmark_law_tagging.py --case bench_001 # 特定ケースのみ
    python benchmark_law_tagging.py --dry-run        # LLM呼び出しなし（構造確認のみ）

出力:
    各ケースの law_id レベル F1・qa_id レベル再現率をテーブルで表示。
    詳細な生出力は --verbose で確認可能。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import openai

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---- Paths ----
BENCH_DIR = Path(__file__).parent
FIXTURES_PATH = BENCH_DIR / "tests/fixtures/law_tagging_benchmark.json"
LAWS_PATH = BENCH_DIR.parent / "data/laws/laws_compact.txt"

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

# デフォルトモデル: structurer.py と合わせる
DEFAULT_MODEL = "google/gemma-4-31B-it"

# ---- プロンプト（structurer.py からコピー、イテレーション時はここを変更する）----
SYSTEM_PROMPT = """あなたは国会会議の分析専門家です。
セッション全体のutterancesとQ&Aペアから、要約・トピック分析・関連法案タグ付けを一括で行ってください。

以下のJSON形式で出力してください:

{
  "session_summary": "セッション全体の概要（3-5文）",
  "key_topics": ["主要トピック1", "主要トピック2", ...],
  "key_commitments": [],
  "topics": [],
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


def get_client() -> openai.OpenAI:
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPINFRA_API_KEY not set")
    return openai.OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)


def format_qa_text(qa_pairs: list[dict]) -> str:
    """structurer.py の generate_summary_and_topics と同じフォーマット。"""
    lines = []
    for p in qa_pairs:
        lines.append(
            f"[{p['id']}] トピック: {p['topic']}\n"
            f"  質問者: {p['question_speaker']}（{p['question_party']}）\n"
            f"  質問要旨: {p['question_summary']}\n"
            f"  回答要旨: {p['answer_summary']}"
        )
    return "\n".join(lines)


def call_llm(client: openai.OpenAI, model: str, qa_text: str, laws_text: str) -> tuple[str, float]:
    """LLM を呼び出して (生レスポンス, 所要秒数) を返す。"""
    user_prompt = f"以下の国会質疑のQ&Aペア一覧を分析してください。\n\n## Q&Aペア一覧\n{qa_text}"
    if laws_text:
        user_prompt += f"\n\n## 法案一覧\n{laws_text}"

    start = time.time()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )
    elapsed = time.time() - start
    return (resp.choices[0].message.content or ""), elapsed


def parse_related_laws(content: str) -> list[dict]:
    """LLM の JSON 応答から related_laws を取り出す。"""
    try:
        data = json.loads(content)
        return data.get("related_laws", [])
    except json.JSONDecodeError:
        logger.error("JSON parse error: %s", content[:200])
        return []


# ---- 評価ロジック ----

def evaluate_case(case: dict, actual_laws: list[dict]) -> dict:
    """1ケースのスコアを計算する。

    Returns:
        {
            "law_precision": float,  # 予測した law_id のうち正解の割合
            "law_recall": float,     # 必須 law_id のうち予測できた割合
            "law_f1": float,
            "required_law_hits": list[str],   # 正しく予測できた必須law_id
            "required_law_misses": list[str], # 予測できなかった必須law_id
            "forbidden_law_hits": list[str],  # 誤って予測した禁止law_id
            "qa_id_recalls": dict[str, float] # law_id -> qa_id 再現率
            "pass": bool,
        }
    """
    expected = case["expected"]
    required = {r["law_id"]: r for r in expected.get("required_laws", [])}
    forbidden = set(expected.get("forbidden_laws", []))

    actual_by_id = {a["law_id"]: a.get("qa_ids", []) for a in actual_laws}

    # law_id レベルの精度・再現率
    predicted_ids = set(actual_by_id.keys())
    required_ids = set(required.keys())

    hits = predicted_ids & required_ids
    misses = required_ids - predicted_ids
    forbidden_hits = predicted_ids & forbidden
    spurious = predicted_ids - required_ids - forbidden  # 必須でも禁止でもない予測

    law_recall = len(hits) / len(required_ids) if required_ids else (1.0 if not predicted_ids else 0.0)
    law_precision = len(hits) / len(predicted_ids) if predicted_ids else (1.0 if not required_ids else 0.0)
    law_f1 = (2 * law_precision * law_recall / (law_precision + law_recall)
               if (law_precision + law_recall) > 0 else 0.0)

    # "タグなし" ケース: required_laws=[] かつ may_be_empty=True
    if expected.get("empty_is_correct") and not required_ids:
        law_recall = 1.0 if not predicted_ids else 0.0
        law_precision = 1.0 if not predicted_ids else 0.0
        law_f1 = 1.0 if not predicted_ids else 0.0

    # qa_id レベルの再現率（各必須law_idについて）
    qa_id_recalls: dict[str, float] = {}
    for law_id, req in required.items():
        must_ids = set(req.get("must_include_qa_ids", []))
        if not must_ids:
            continue
        actual_qa_ids = set(actual_by_id.get(law_id, []))
        qa_id_recalls[law_id] = len(must_ids & actual_qa_ids) / len(must_ids)

    passed = (
        len(misses) == 0
        and len(forbidden_hits) == 0
        and all(v >= 1.0 for v in qa_id_recalls.values())
        and (not expected.get("empty_is_correct") or not predicted_ids)
    )

    return {
        "law_precision": round(law_precision, 3),
        "law_recall": round(law_recall, 3),
        "law_f1": round(law_f1, 3),
        "required_law_hits": sorted(hits),
        "required_law_misses": sorted(misses),
        "forbidden_law_hits": sorted(forbidden_hits),
        "spurious_laws": sorted(spurious),
        "qa_id_recalls": {k: round(v, 3) for k, v in qa_id_recalls.items()},
        "pass": passed,
    }


def print_summary(results: list[dict]) -> None:
    """結果テーブルを標準出力に表示。"""
    header = f"{'ID':<12} {'Label':<45} {'P':>5} {'R':>5} {'F1':>5} {'Pass':>5}"
    print()
    print(header)
    print("-" * len(header))
    passed = 0
    for r in results:
        p = r["scores"]["law_precision"]
        rec = r["scores"]["law_recall"]
        f1 = r["scores"]["law_f1"]
        ok = "OK" if r["scores"]["pass"] else "FAIL"
        if r["scores"]["pass"]:
            passed += 1
        label = r["case_label"][:45]
        print(f"{r['case_id']:<12} {label:<45} {p:>5.2f} {rec:>5.2f} {f1:>5.2f} {ok:>5}")
    print("-" * len(header))
    print(f"Passed: {passed}/{len(results)}")
    print()


def print_verbose(case: dict, actual_laws: list[dict], scores: dict) -> None:
    """ケースの詳細を表示。"""
    print(f"\n=== {case['id']}: {case['label']} ===")
    print(f"Pattern: {case['pattern']} | Expected: {case['current_status']}")
    print(f"Required laws: {[r['law_id'] for r in case['expected'].get('required_laws', [])]}")
    print(f"Actual laws:   {[a['law_id'] for a in actual_laws]}")
    if scores["required_law_misses"]:
        print(f"MISSED:        {scores['required_law_misses']}")
    if scores["forbidden_law_hits"]:
        print(f"FORBIDDEN HIT: {scores['forbidden_law_hits']}")
    if scores["spurious_laws"]:
        print(f"Spurious:      {scores['spurious_laws']}")
    if scores["qa_id_recalls"]:
        print(f"QA-id recall:  {scores['qa_id_recalls']}")
    print(f"Score: P={scores['law_precision']:.2f} R={scores['law_recall']:.2f} F1={scores['law_f1']:.2f} {'PASS' if scores['pass'] else 'FAIL'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="法案タグ付けベンチマーク")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="DeepInfra モデル名")
    parser.add_argument("--case", help="特定ケースIDのみ実行 (例: bench_001)")
    parser.add_argument("--dry-run", action="store_true", help="LLM呼び出しなし（ランダムな空結果を使用）")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細表示")
    args = parser.parse_args()

    # ベンチマークデータの読み込み
    with open(FIXTURES_PATH, encoding="utf-8") as f:
        benchmark = json.load(f)

    cases = benchmark["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            logger.error("Case not found: %s", args.case)
            return

    laws_text = LAWS_PATH.read_text(encoding="utf-8") if LAWS_PATH.exists() else ""
    if not laws_text:
        logger.warning("laws_compact.txt not found at %s", LAWS_PATH)

    client = None if args.dry_run else get_client()

    results = []
    for case in cases:
        logger.info("Running %s: %s", case["id"], case["label"])

        qa_text = format_qa_text(case["input"]["qa_pairs"])

        if args.dry_run:
            actual_laws: list[dict] = []
            elapsed = 0.0
            raw = "{}"
        else:
            raw, elapsed = call_llm(client, args.model, qa_text, laws_text)  # type: ignore[arg-type]
            actual_laws = parse_related_laws(raw)
            logger.info("  -> %d laws tagged in %.1fs", len(actual_laws), elapsed)

        scores = evaluate_case(case, actual_laws)

        if args.verbose:
            print_verbose(case, actual_laws, scores)

        results.append({
            "case_id": case["id"],
            "case_label": case["label"],
            "model": args.model,
            "elapsed_s": round(elapsed, 1),
            "actual_laws": actual_laws,
            "scores": scores,
        })

    print_summary(results)

    # JSON で詳細結果を出力
    out_path = BENCH_DIR / "benchmark_law_tagging_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info("Detailed results written to %s", out_path)


if __name__ == "__main__":
    main()
