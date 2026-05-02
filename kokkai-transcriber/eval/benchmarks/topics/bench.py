"""TOPICS_SYSTEM_PROMPT ベンチマーク実行（スタンドアロン版）

python3 bench.py --label baseline
python3 bench.py --label v2 --prompt-file prompts/v2.txt
python3 bench.py --label baseline --cases D1,D2,D3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import openai

BENCH_DIR = Path(__file__).resolve().parent
CASES_DIR = BENCH_DIR / "cases"
RESULTS_DIR = BENCH_DIR / "results"
PROMPTS_DIR = BENCH_DIR / "prompts"

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
MODEL = "google/gemma-4-31B-it"

# ベースラインプロンプト（structurer.py の SUMMARY_AND_TOPICS_SYSTEM_PROMPT と同一）
BASELINE_PROMPT = """あなたは国会会議の分析専門家です。
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


def score(result_topics: list, expected_topics: list) -> dict:
    exp_ids: set[str] = set()
    for t in expected_topics:
        exp_ids.update(t.get("related_qa_ids", []))

    res_ids: set[str] = set()
    for t in result_topics:
        res_ids.update(t.get("related_qa_ids", []))

    qa_cov = round(len(res_ids & exp_ids) / len(exp_ids), 3) if exp_ids else 1.0
    count_diff = len(result_topics) - len(expected_topics)

    exp_names = {t.get("name", "") for t in expected_topics}
    res_names = {t.get("name", "") for t in result_topics}
    if exp_names:
        matched = sum(1 for en in exp_names if any(en in rn or rn in en for rn in res_names))
        name_cov = round(matched / len(exp_names), 3)
    else:
        name_cov = 1.0

    return {"qa_coverage": qa_cov, "topic_count_diff": count_diff, "name_coverage": name_cov}


def run_one(case_dir: Path, system_prompt: str, label: str) -> dict:
    inp = json.loads((case_dir / "input.json").read_text())
    exp = json.loads((case_dir / "expected.json").read_text())
    meta = json.loads((case_dir / "meta.json").read_text())

    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        raise OSError("DEEPINFRA_API_KEY not set")
    client = openai.OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)

    t0 = time.time()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": inp["user_prompt"]},
        ],
        temperature=0.1,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )
    latency = round(time.time() - t0, 1)

    content = resp.choices[0].message.content or ""
    json_valid = False
    result_topics = []
    try:
        parsed = json.loads(content)
        result_topics = parsed.get("topics", [])
        json_valid = True
    except json.JSONDecodeError:
        pass

    scores = score(result_topics, exp.get("topics", []))
    usage = resp.usage
    row = {
        "case_id": case_dir.name,
        "label": label,
        "session": meta["session"],
        "n_qa": meta["n_qa_pairs"],
        "n_topics_result": len(result_topics),
        "n_topics_expected": meta["n_topics_expected"],
        "original_coverage": meta.get("current_coverage", meta.get("original_coverage", 1.0)),
        "json_valid": json_valid,
        "latency_s": latency,
        "in_tok": usage.prompt_tokens if usage else 0,
        "out_tok": usage.completion_tokens if usage else 0,
        **scores,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = int(time.time())
    (RESULTS_DIR / f"{case_dir.name}__{label}__{ts}.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2)
    )
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--prompt-file", default=None)
    ap.add_argument("--cases", default=None, help="カンマ区切り prefix (例: P1,D1)")
    args = ap.parse_args()

    if args.prompt_file:
        system_prompt = Path(args.prompt_file).read_text()
    else:
        system_prompt = BASELINE_PROMPT

    cases_index = json.loads((BENCH_DIR / "cases.json").read_text())
    all_dirs = [CASES_DIR / c["dir"] for c in cases_index["cases"]]

    if args.cases:
        prefixes = [p.strip() for p in args.cases.split(",")]
        all_dirs = [d for d in all_dirs if any(d.name.startswith(p) for p in prefixes)]

    print(f"Running {len(all_dirs)} cases with label={args.label}")
    results = []
    for case_dir in all_dirs:
        print(f"  {case_dir.name} ...", end="", flush=True)
        try:
            row = run_one(case_dir, system_prompt, args.label)
            results.append(row)
            cov_before = row["original_coverage"]
            print(f" qa_cov={row['qa_coverage']:.0%} (was {cov_before:.0%}) "
                  f"topics={row['n_topics_result']}/{row['n_topics_expected']} "
                  f"{row['latency_s']}s")
        except Exception as e:
            print(f" ERROR: {e}")

    if results:
        print(f"\n{'Case':<46} {'QA':>4} {'T_r':>4} {'T_e':>4} "
              f"{'Before':>7} {'After':>7} {'Names':>7}")
        print("-" * 86)
        for r in results:
            print(f"{r['case_id']:<46} {r['n_qa']:>4} "
                  f"{r['n_topics_result']:>4} {r['n_topics_expected']:>4} "
                  f"{r['original_coverage']:>6.0%} {r['qa_coverage']:>6.0%} "
                  f"{r['name_coverage']:>6.0%}")
        coverages = [r["qa_coverage"] for r in results]
        print(f"\nMean qa_coverage: {sum(coverages)/len(coverages):.1%}")


if __name__ == "__main__":
    main()
