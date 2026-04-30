"""スコアリング: モデル評価結果をゴールデンデータと比較

Usage:
    python -m eval.score
    python -m eval.score --tasks speaker_tagging
    python -m eval.score --format tsv
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EVAL_DIR = Path(__file__).parent
GOLDEN_DIR = EVAL_DIR / "golden"
RESULTS_DIR = EVAL_DIR / "results"


# ---------------------------------------------------------------------------
# タスク別スコアリング関数
# ---------------------------------------------------------------------------


def score_speaker_tagging(result: dict, expected: dict) -> dict:
    """話者タグ付けのスコアリング。

    評価指標:
    - utterance_count_diff: 発言数の差分（正解との差）
    - speaker_accuracy: 話者名の一致率
    - role_accuracy: roleの一致率
    """
    parsed = result.get("parsed")
    if not parsed:
        return {"error": "JSON parse failed", "utterance_count_diff": None, "speaker_accuracy": 0.0, "role_accuracy": 0.0}

    result_utterances = parsed.get("utterances", [])
    expected_utterances = expected.get("utterances", [])

    count_diff = len(result_utterances) - len(expected_utterances)

    # 順序ベースの比較（同じインデックス同士を比較）
    min_len = min(len(result_utterances), len(expected_utterances))
    speaker_match = 0
    role_match = 0

    for i in range(min_len):
        if result_utterances[i].get("speaker") == expected_utterances[i].get("speaker"):
            speaker_match += 1
        if result_utterances[i].get("role") == expected_utterances[i].get("role"):
            role_match += 1

    total = max(len(expected_utterances), 1)

    return {
        "utterance_count_diff": count_diff,
        "speaker_accuracy": round(speaker_match / total, 3),
        "role_accuracy": round(role_match / total, 3),
    }


def score_qa_pairs(result: dict, expected: dict) -> dict:
    """Q&Aペア生成のスコアリング。

    評価指標:
    - pair_count_diff: ペア数の差
    - topic_coverage: 期待トピックとの一致率
    - answer_completeness_mae: answer_completenessの平均絶対誤差
    - record_value_mae: record_valueの平均絶対誤差
    """
    parsed = result.get("parsed")
    if not parsed:
        return {"error": "JSON parse failed", "pair_count_diff": None, "topic_coverage": 0.0}

    result_pairs = parsed.get("pairs", [])
    expected_pairs = expected.get("pairs", [])

    count_diff = len(result_pairs) - len(expected_pairs)

    # トピック名の部分一致で coverage を測定
    expected_topics = {p.get("topic", "") for p in expected_pairs}
    result_topics = {p.get("topic", "") for p in result_pairs}

    if expected_topics:
        # 部分一致: result の topic が expected の topic を含むか
        matched = 0
        for et in expected_topics:
            if any(et in rt or rt in et for rt in result_topics):
                matched += 1
        topic_coverage = round(matched / len(expected_topics), 3)
    else:
        topic_coverage = 1.0

    return {
        "pair_count_diff": count_diff,
        "topic_coverage": topic_coverage,
        "answer_completeness_mae": _compute_score_mae(result_pairs, expected_pairs, ("answer", "answer_completeness")),
        "record_value_mae": _compute_score_mae(result_pairs, expected_pairs, ("record_value",)),
        "question_sharpness_mae": _compute_score_mae(result_pairs, expected_pairs, ("question", "question_sharpness")),
    }


def _compute_score_mae(result_pairs: list, expected_pairs: list, key_path: tuple) -> float | None:
    """ペアをインデックス順で比較し、指定フィールドのMAEを計算。"""
    min_len = min(len(result_pairs), len(expected_pairs))
    if min_len == 0:
        return None

    def get_nested(d: dict, path: tuple):
        for k in path:
            if not isinstance(d, dict):
                return None
            d = d.get(k)
        return d

    total_error = 0.0
    count = 0
    for i in range(min_len):
        r_score = get_nested(result_pairs[i], key_path)
        e_score = get_nested(expected_pairs[i], key_path)
        if r_score is not None and e_score is not None:
            total_error += abs(float(r_score) - float(e_score))
            count += 1

    return round(total_error / count, 3) if count > 0 else None


def score_summary(result: dict, expected: dict) -> dict:
    """要約のスコアリング。

    評価指標:
    - key_topics_coverage: key_topicsの網羅率
    - commitment_count_diff: key_commitmentsの数の差
    - summary_length: 要約の文字数（参考値）
    """
    parsed = result.get("parsed")
    if not parsed:
        return {"error": "JSON parse failed", "key_topics_coverage": 0.0}

    result_topics = set(parsed.get("key_topics", []))
    expected_topics = set(expected.get("key_topics", []))

    if expected_topics:
        matched = sum(
            1 for et in expected_topics
            if any(et in rt or rt in et for rt in result_topics)
        )
        coverage = round(matched / len(expected_topics), 3)
    else:
        coverage = 1.0

    result_commitments = parsed.get("key_commitments", [])
    expected_commitments = expected.get("key_commitments", [])

    return {
        "key_topics_coverage": coverage,
        "commitment_count_diff": len(result_commitments) - len(expected_commitments),
        "summary_length": len(parsed.get("session_summary", "")),
    }


def score_topics(result: dict, expected: dict) -> dict:
    """トピック抽出のスコアリング。

    評価指標:
    - topic_count_diff: トピック数の差
    - name_coverage: トピック名の部分一致率
    """
    parsed = result.get("parsed")
    if not parsed:
        return {"error": "JSON parse failed", "topic_count_diff": None, "name_coverage": 0.0}

    result_topics = parsed.get("topics", [])
    expected_topics = expected.get("topics", [])

    count_diff = len(result_topics) - len(expected_topics)

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
        "topic_count_diff": count_diff,
        "name_coverage": name_coverage,
    }


SCORERS = {
    "speaker_tagging": score_speaker_tagging,
    "qa_pairs": score_qa_pairs,
    "summary": score_summary,
    "topics": score_topics,
}


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------


def collect_scores(tasks: list[str] | None = None) -> list[dict]:
    """全結果ファイルを走査してスコアを計算する。"""
    rows: list[dict] = []

    for model_dir in sorted(RESULTS_DIR.iterdir()):
        if not model_dir.is_dir():
            continue
        model_key = model_dir.name

        for task_dir in sorted(model_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            task = task_dir.name

            if tasks and task not in tasks:
                continue

            scorer = SCORERS.get(task)
            if not scorer:
                logger.warning("No scorer for task: %s", task)
                continue

            for result_file in sorted(task_dir.glob("*.result.json")):
                case_id = result_file.stem.replace(".result", "")

                with open(result_file) as f:
                    result = json.load(f)

                # 対応するゴールデン期待出力を探す
                expected_file = GOLDEN_DIR / f"{case_id}.expected.json"
                if not expected_file.exists():
                    logger.warning("No expected file for %s", case_id)
                    continue

                with open(expected_file) as f:
                    expected = json.load(f)

                scores = scorer(result, expected)

                row = {
                    "model": model_key,
                    "task": task,
                    "case_id": case_id,
                    "json_valid": result.get("json_valid", False),
                    "latency_seconds": result.get("latency_seconds"),
                    "cost_estimate": result.get("cost_estimate"),
                    "input_tokens": result.get("input_tokens"),
                    "output_tokens": result.get("output_tokens"),
                    **scores,
                }
                rows.append(row)

    return rows


def print_summary(rows: list[dict], fmt: str = "table") -> None:
    """モデル × タスク の集約サマリーを表示。"""
    if not rows:
        print("No results to display.")
        return

    if fmt == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    # モデル × タスク ごとの集約
    from collections import defaultdict

    agg: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        agg[(row["model"], row["task"])].append(row)

    if fmt == "tsv":
        header = "model\ttask\tcases\tjson_valid_rate\tavg_latency\tavg_cost\tscores"
        print(header)
        for (model, task), case_rows in sorted(agg.items()):
            n = len(case_rows)
            json_rate = sum(1 for r in case_rows if r.get("json_valid")) / n
            avg_lat = sum(r.get("latency_seconds", 0) or 0 for r in case_rows) / n
            avg_cost = sum(r.get("cost_estimate", 0) or 0 for r in case_rows) / n
            score_keys = [k for k in case_rows[0] if k not in {
                "model", "task", "case_id", "json_valid", "latency_seconds",
                "cost_estimate", "input_tokens", "output_tokens", "error",
            }]
            score_parts = []
            for k in score_keys:
                vals = [r[k] for r in case_rows if r.get(k) is not None]
                if vals and all(isinstance(v, (int, float)) for v in vals):
                    score_parts.append(f"{k}={sum(vals)/len(vals):.3f}")
            print(f"{model}\t{task}\t{n}\t{json_rate:.0%}\t{avg_lat:.1f}s\t${avg_cost:.6f}\t{'; '.join(score_parts)}")
    else:
        # table format
        print(f"\n{'Model':<20} {'Task':<20} {'N':>3} {'JSON%':>6} {'Lat':>6} {'Cost':>10} {'Scores'}")
        print("-" * 90)
        for (model, task), case_rows in sorted(agg.items()):
            n = len(case_rows)
            json_rate = sum(1 for r in case_rows if r.get("json_valid")) / n
            avg_lat = sum(r.get("latency_seconds", 0) or 0 for r in case_rows) / n
            avg_cost = sum(r.get("cost_estimate", 0) or 0 for r in case_rows) / n
            score_keys = [k for k in case_rows[0] if k not in {
                "model", "task", "case_id", "json_valid", "latency_seconds",
                "cost_estimate", "input_tokens", "output_tokens", "error",
            }]
            score_parts = []
            for k in score_keys:
                vals = [r[k] for r in case_rows if r.get(k) is not None]
                if vals and all(isinstance(v, (int, float)) for v in vals):
                    score_parts.append(f"{k}={sum(vals)/len(vals):.3f}")
            print(f"{model:<20} {task:<20} {n:>3} {json_rate:>5.0%} {avg_lat:>5.1f}s ${avg_cost:>9.6f} {'; '.join(score_parts)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM評価結果スコアリング")
    parser.add_argument("--tasks", nargs="+", help="スコアリング対象タスク")
    parser.add_argument("--format", choices=["table", "tsv", "json"], default="table")
    args = parser.parse_args()

    rows = collect_scores(tasks=args.tasks)
    print_summary(rows, fmt=args.format)


if __name__ == "__main__":
    main()
