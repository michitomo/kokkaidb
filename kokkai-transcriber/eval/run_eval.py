"""LLMモデル比較評価ハーネス

各モデル × 各タスク × 各テストケースで LLM を呼び出し、結果を保存する。
OpenRouter API 経由で全モデルに統一アクセス。モデル間は並列実行。

Usage:
    python -m eval.run_eval
    python -m eval.run_eval --models deepseek-v3.2 qwen-3.6-plus
    python -m eval.run_eval --tasks speaker_tagging qa_pairs
    python -m eval.run_eval --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EVAL_DIR = Path(__file__).parent
GOLDEN_DIR = EVAL_DIR / "golden"
RESULTS_DIR = EVAL_DIR / "results"
MODELS_FILE = EVAL_DIR / "models.yaml"

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT = 180.0
MAX_WORKERS = 9  # 全モデル並列


def load_config() -> dict:
    with open(MODELS_FILE) as f:
        return yaml.safe_load(f)


def load_golden_cases(task: str) -> list[dict]:
    cases = []
    for input_file in sorted(GOLDEN_DIR.glob(f"{task}_*.input.json")):
        case_id = input_file.stem.replace(".input", "")
        with open(input_file) as f:
            input_data = json.load(f)

        expected_file = GOLDEN_DIR / f"{case_id}.expected.json"
        expected = None
        if expected_file.exists():
            with open(expected_file) as f:
                expected = json.load(f)

        cases.append({
            "case_id": case_id,
            "input": input_data,
            "expected": expected,
        })
    return cases


def call_model(
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    api_key: str,
) -> dict:
    """OpenRouter REST APIを直接呼び出し。"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    start = time.monotonic()
    resp = requests.post(
        OPENROUTER_API_URL,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    elapsed = time.monotonic() - start

    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"API error: {data['error']}")

    choice = data["choices"][0]
    content = choice.get("message", {}).get("content", "")
    usage = data.get("usage", {})

    return {
        "raw_content": content,
        "parsed": _try_parse_json(content),
        "latency_seconds": round(elapsed, 2),
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


def _try_parse_json(text: str) -> dict | list | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def get_prompts_for_task(task: str, input_data: dict) -> tuple[str, str]:
    return input_data.get("system_prompt", ""), input_data.get("user_prompt", "")


def _run_single(
    model_key: str,
    model_config: dict,
    task: str,
    case: dict,
    api_key: str,
) -> str:
    """1モデル×1タスク×1ケースを実行して結果ファイルに保存。ログ文字列を返す。"""
    case_id = case["case_id"]
    model_id = model_config["id"]
    system_prompt, user_prompt = get_prompts_for_task(task, case["input"])

    model_results_dir = RESULTS_DIR / model_key / task
    model_results_dir.mkdir(parents=True, exist_ok=True)
    output_file = model_results_dir / f"{case_id}.result.json"

    if output_file.exists():
        return f"  SKIP  {model_key:20s} / {task:20s} / {case_id}"

    try:
        result = call_model(model_id, system_prompt, user_prompt, api_key)
        result["model"] = model_key
        result["model_id"] = model_id
        result["task"] = task
        result["case_id"] = case_id
        result["json_valid"] = result["parsed"] is not None
        result["cost_estimate"] = _estimate_cost(
            result["input_tokens"],
            result["output_tokens"],
            model_config["input_price_per_m"],
            model_config["output_price_per_m"],
        )

        with open(output_file, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        status = "OK" if result["json_valid"] else "FAIL(JSON)"
        return (
            f"  {status:12s} {model_key:20s} / {task:20s} / {case_id} "
            f"| {result['latency_seconds']:.1f}s | ${result['cost_estimate']:.6f}"
        )

    except requests.Timeout:
        return f"  TIMEOUT    {model_key:20s} / {task:20s} / {case_id} | {REQUEST_TIMEOUT:.0f}s"
    except Exception as e:
        return f"  ERROR      {model_key:20s} / {task:20s} / {case_id} | {e!r}"


def run_evaluation(
    models: list[str] | None = None,
    tasks: list[str] | None = None,
    dry_run: bool = False,
) -> None:
    config = load_config()
    all_models = config["models"]
    all_tasks = config["tasks"]

    target_models = models or list(all_models.keys())
    target_tasks = tasks or all_tasks

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key and not dry_run:
        raise EnvironmentError("OPENROUTER_API_KEY environment variable is not set.")

    # 全ジョブを収集
    jobs: list[tuple[str, dict, str, dict]] = []
    for task in target_tasks:
        cases = load_golden_cases(task)
        if not cases:
            logger.warning("No golden cases for task: %s", task)
            continue
        for model_key in target_models:
            if model_key not in all_models:
                continue
            for case in cases:
                jobs.append((model_key, all_models[model_key], task, case))

    logger.info("Total jobs: %d (%d models × %d tasks)", len(jobs), len(target_models), len(target_tasks))

    if dry_run:
        for model_key, _, task, case in jobs:
            s, u = get_prompts_for_task(task, case["input"])
            logger.info("  [DRY-RUN] %s / %s / %s: sys=%d user=%d", model_key, task, case["case_id"], len(s), len(u))
        return

    # 並列実行
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_run_single, mk, mc, t, c, api_key): (mk, t, c["case_id"])
            for mk, mc, t, c in jobs
        }
        for future in as_completed(futures):
            mk, t, cid = futures[future]
            try:
                msg = future.result()
                logger.info(msg)
            except Exception:
                logger.exception("Unexpected error: %s / %s / %s", mk, t, cid)


def _estimate_cost(
    input_tokens: int,
    output_tokens: int,
    input_price_per_m: float,
    output_price_per_m: float,
) -> float:
    return (input_tokens * input_price_per_m + output_tokens * output_price_per_m) / 1_000_000


def main() -> None:
    parser = argparse.ArgumentParser(description="LLMモデル比較評価ハーネス")
    parser.add_argument("--models", nargs="+", help="評価するモデルキー")
    parser.add_argument("--tasks", nargs="+", help="評価するタスク")
    parser.add_argument("--dry-run", action="store_true", help="API呼び出しなしで確認のみ")
    args = parser.parse_args()

    run_evaluation(models=args.models, tasks=args.tasks, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
