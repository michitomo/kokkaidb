"""TOPICS_SYSTEM_PROMPT ベンチマーク実行スクリプト

SUMMARY_AND_TOPICS_SYSTEM_PROMPT の各バリアントを7ケースに対して実行し、
qa_coverage / topic_count_diff / name_coverage を計測する。

Usage:
    cd kokkai-transcriber
    python -m eval.benchmarks.topics.run_benchmark
    python -m eval.benchmarks.topics.run_benchmark --cases P1,P2,P3
    python -m eval.benchmarks.topics.run_benchmark --prompt-file my_prompt.txt
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BENCH_DIR = Path(__file__).resolve().parent
CASES_DIR = BENCH_DIR / "cases"
RESULTS_DIR = BENCH_DIR / "results"

# デフォルトのシステムプロンプト（structurer.py の SUMMARY_AND_TOPICS_SYSTEM_PROMPT と同一）
DEFAULT_SYSTEM_PROMPT = """あなたは国会会議の分析専門家です。
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


def score_topics_result(result_topics: list, expected_topics: list) -> dict:
    """トピック評価スコアを計算する。"""
    # QA IDカバレッジ（最重要）
    expected_qa_ids: set[str] = set()
    for t in expected_topics:
        expected_qa_ids.update(t.get("related_qa_ids", []))

    result_qa_ids: set[str] = set()
    for t in result_topics:
        result_qa_ids.update(t.get("related_qa_ids", []))

    qa_coverage = (
        round(len(result_qa_ids & expected_qa_ids) / len(expected_qa_ids), 3)
        if expected_qa_ids else 1.0
    )

    # トピック数の差
    topic_count_diff = len(result_topics) - len(expected_topics)

    # トピック名の部分一致率
    expected_names = {t.get("name", "") for t in expected_topics}
    result_names = {t.get("name", "") for t in result_topics}
    if expected_names:
        matched = sum(
            1 for en in expected_names
            if any(en in rn or rn in en for rn in result_names)
        )
        name_coverage = round(matched / len(expected_names), 3)
    else:
        name_coverage = 1.0

    return {
        "qa_coverage": qa_coverage,
        "topic_count_diff": topic_count_diff,
        "name_coverage": name_coverage,
    }


def run_case(
    case_id: str,
    system_prompt: str,
    prompt_label: str,
    dry_run: bool = False,
) -> dict:
    """1ケースを実行してスコアを返す。"""
    case_dir = CASES_DIR / case_id
    input_data = json.loads((case_dir / "input.json").read_text(encoding="utf-8"))
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    meta = json.loads((case_dir / "meta.json").read_text(encoding="utf-8"))

    if dry_run:
        logger.info("[DRY RUN] %s: skipping LLM call", case_id)
        return {"case_id": case_id, "dry_run": True}

    try:
        from src.api_client import get_client as _get_client, STRUCTURER_MODEL, with_retry
    except ImportError:
        logger.error("Cannot import src.api_client. Run from kokkai-transcriber/ directory.")
        raise

    client = _get_client()
    user_prompt = input_data["user_prompt"]

    start = time.time()
    response = with_retry(lambda: client.chat.completions.create(
        model=STRUCTURER_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=8192,
        response_format={"type": "json_object"},
    ))
    latency = round(time.time() - start, 2)

    content = response.choices[0].message.content or ""
    json_valid = False
    result_topics = []
    try:
        parsed = json.loads(content)
        result_topics = parsed.get("topics", [])
        json_valid = True
    except json.JSONDecodeError:
        logger.warning("JSON parse failed for case %s", case_id)

    scores = score_topics_result(result_topics, expected.get("topics", []))

    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0

    result = {
        "case_id": case_id,
        "prompt_label": prompt_label,
        "session": meta["session"],
        "n_qa_pairs": meta["n_qa_pairs"],
        "n_topics_result": len(result_topics),
        "n_topics_expected": meta["n_topics_expected"],
        "original_coverage": meta.get("current_coverage", meta.get("original_coverage", 1.0)),
        "json_valid": json_valid,
        "latency_seconds": latency,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        **scores,
    }

    # 結果を保存
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    result_path = RESULTS_DIR / f"{case_id}_{prompt_label}_{ts}.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "%s: qa_coverage=%.1f%% topic_count=%d→%d name_cov=%.1f%% lat=%.1fs",
        case_id, scores["qa_coverage"] * 100,
        len(result_topics), meta["n_topics_expected"],
        scores["name_coverage"] * 100, latency,
    )

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="TOPICS_SYSTEM_PROMPT ベンチマーク")
    parser.add_argument("--cases", help="実行するケースのカンマ区切りリスト（例: P1,P2,D1）")
    parser.add_argument("--prompt-file", help="カスタムシステムプロンプトのファイルパス")
    parser.add_argument("--prompt-label", default="baseline", help="プロンプトの識別ラベル")
    parser.add_argument("--dry-run", action="store_true", help="LLMを呼ばずに構造確認のみ")
    args = parser.parse_args()

    # ケース選択
    cases_index = json.loads((BENCH_DIR / "cases.json").read_text(encoding="utf-8"))
    all_case_ids = [c["dir"] for c in cases_index["cases"]]

    if args.cases:
        prefixes = [p.strip() for p in args.cases.split(",")]
        selected = [cid for cid in all_case_ids if any(cid.startswith(p) for p in prefixes)]
    else:
        selected = all_case_ids

    if not selected:
        logger.error("No cases selected. Available: %s", all_case_ids)
        return

    # プロンプト
    if args.prompt_file:
        system_prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    else:
        system_prompt = DEFAULT_SYSTEM_PROMPT

    logger.info("Running %d cases with prompt_label=%s", len(selected), args.prompt_label)

    results = []
    for case_id in selected:
        result = run_case(case_id, system_prompt, args.prompt_label, dry_run=args.dry_run)
        results.append(result)

    # サマリー出力
    if not args.dry_run:
        print("\n=== Benchmark Summary ===")
        print(f"{'Case':<45} {'QA':>4} {'T_r':>4} {'T_e':>4} {'Coverage':>9} {'NameCov':>8}")
        print("-" * 80)
        for r in results:
            if r.get("dry_run"):
                continue
            print(
                f"{r['case_id']:<45} {r['n_qa_pairs']:>4} "
                f"{r['n_topics_result']:>4} {r['n_topics_expected']:>4} "
                f"{r['qa_coverage']:>8.1%} {r['name_coverage']:>7.1%}"
            )
        coverages = [r["qa_coverage"] for r in results if not r.get("dry_run")]
        if coverages:
            print(f"\nMean qa_coverage: {sum(coverages)/len(coverages):.1%}")


if __name__ == "__main__":
    main()
