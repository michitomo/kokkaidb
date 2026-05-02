#!/usr/bin/env python3
"""speaker_tagger SYSTEM_PROMPT ベンチマーク評価スクリプト

Usage:
    # キャッシュされたbaseline結果で評価
    uv run python benchmarks/eval_speaker_tagger.py --no-call

    # 現在のSYSTEM_PROMPTでLLM評価
    uv run python benchmarks/eval_speaker_tagger.py

    # 改善プロンプトファイルで評価
    uv run python benchmarks/eval_speaker_tagger.py --prompt-file benchmarks/prompt_v2.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import SpeakerInfo


def splits_to_sentence_labels(
    splits: list[dict], n_sentences: int
) -> list[tuple[str, str]]:
    """splits配列 → 文ごとの (speaker, role) リストに変換"""
    if not splits:
        return [("", "")] * n_sentences

    sorted_splits = sorted(splits, key=lambda s: s.get("start", 0))
    labels: list[tuple[str, str]] = []

    for i, split in enumerate(sorted_splits):
        start = max(0, split.get("start", 0))
        end = (
            sorted_splits[i + 1].get("start", n_sentences)
            if i + 1 < len(sorted_splits)
            else n_sentences
        )
        end = min(end, n_sentences)
        speaker = split.get("speaker", "")
        role = split.get("role", "")
        for _ in range(start, end):
            labels.append((speaker, role))

    # 末尾が足りない場合は最後のラベルで埋める
    while len(labels) < n_sentences:
        labels.append(labels[-1] if labels else ("", ""))

    return labels[:n_sentences]


def count_sentences(numbered_text: str) -> int:
    """numbered_text の文数を数える"""
    return sum(1 for line in numbered_text.split("\n") if line.strip())


def score_test_case(
    pred_splits: list[dict],
    expected_splits: list[dict],
    n_sentences: int,
) -> dict:
    """1テストケースのスコアを計算して返す"""
    pred_labels = splits_to_sentence_labels(pred_splits, n_sentences)
    exp_labels = splits_to_sentence_labels(expected_splits, n_sentences)

    speaker_correct = sum(1 for p, e in zip(pred_labels, exp_labels) if p[0] == e[0])
    role_correct = sum(1 for p, e in zip(pred_labels, exp_labels) if p[1] == e[1])
    full_correct = sum(
        1 for p, e in zip(pred_labels, exp_labels) if p[0] == e[0] and p[1] == e[1]
    )

    return {
        "n_sentences": n_sentences,
        "speaker_accuracy": speaker_correct / n_sentences if n_sentences > 0 else 0.0,
        "role_accuracy": role_correct / n_sentences if n_sentences > 0 else 0.0,
        "full_accuracy": full_correct / n_sentences if n_sentences > 0 else 0.0,
        "speaker_correct": speaker_correct,
        "role_correct": role_correct,
        "full_correct": full_correct,
    }


def run_llm_evaluation(test_cases: list[dict], system_prompt: str) -> list[dict]:
    """LLMを呼び出して各テストケースを評価"""
    from src.api_client import LLM_MODEL, get_client, with_retry

    client = get_client()
    results = []

    for tc in test_cases:
        tc_id = tc["id"]
        inp = tc["input"]
        numbered_text = inp["numbered_text"]
        sp_data = inp["segment_speaker"]
        all_sp_data = inp["all_speakers"]

        segment_speaker = SpeakerInfo(
            name=sp_data["name"],
            affiliation=sp_data.get("affiliation", ""),
            role=sp_data.get("role") or "",
            start_seconds=sp_data.get("start_seconds", 0),
            start_time=sp_data.get("start_time", ""),
            duration_minutes=sp_data.get("duration_minutes", 0),
        )

        all_speakers = [
            SpeakerInfo(
                name=s["name"],
                affiliation=s.get("affiliation", ""),
                role=s.get("role") or "",
                start_seconds=s.get("start_seconds", 0),
                start_time=s.get("start_time", ""),
                duration_minutes=s.get("duration_minutes", 0),
            )
            for s in all_sp_data
        ]

        speaker_list = "\n".join(f"- {s.name}（{s.affiliation}）" for s in all_speakers)
        n_sentences = count_sentences(numbered_text)

        user_prompt = (
            f"セグメントの主発言者: {segment_speaker.name}（{segment_speaker.affiliation}）\n"
            f"役割: {segment_speaker.role or '質疑者'}\n\n"
            f"このセッションの発言者一覧:\n{speaker_list}\n\n"
            f"以下の番号付き文リストの話者交代ポイントを検出してください（{n_sentences}文）:\n\n"
            f"{numbered_text}"
        )

        print(f"  {tc_id}...", end="", flush=True)
        try:
            response = with_retry(
                lambda: client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
            )
            content = response.choices[0].message.content or ""
            data = json.loads(content)
            pred_splits = data.get("splits", [])
            print(" OK")
        except Exception as e:
            print(f" ERROR: {e}")
            pred_splits = []

        score = score_test_case(pred_splits, tc["expected_splits"], n_sentences)
        results.append(
            {
                "id": tc_id,
                "categories": tc["categories"],
                "difficulty": tc["difficulty"],
                "description": tc.get("description", ""),
                "pred_splits": pred_splits,
                "expected_splits": tc["expected_splits"],
                "score": score,
            }
        )

    return results


def run_cached_evaluation(test_cases: list[dict]) -> list[dict]:
    """benchmark JSONに記録済みの current_llm_output を使用して評価"""
    results = []
    for tc in test_cases:
        numbered_text = tc["input"]["numbered_text"]
        n_sentences = count_sentences(numbered_text)

        cur = tc.get("current_llm_output") or {}
        pred_splits = cur.get("splits", [])

        score = score_test_case(pred_splits, tc["expected_splits"], n_sentences)
        results.append(
            {
                "id": tc["id"],
                "categories": tc["categories"],
                "difficulty": tc["difficulty"],
                "description": tc.get("description", ""),
                "pred_splits": pred_splits,
                "expected_splits": tc["expected_splits"],
                "score": score,
            }
        )

    return results


def print_report(results: list[dict], label: str = "") -> None:
    """評価レポートを出力"""
    bar = "=" * 70
    print(f"\n{bar}")
    if label:
        print(f"評価レポート: {label}")
    print(f"{bar}\n")

    total_n = total_spk = total_role = total_full = 0
    category_stats: dict[str, dict] = {}

    for r in results:
        s = r["score"]
        n = s["n_sentences"]
        total_n += n
        total_spk += s["speaker_correct"]
        total_role += s["role_correct"]
        total_full += s["full_correct"]

        sa = s["speaker_accuracy"] * 100
        ra = s["role_accuracy"] * 100
        fa = s["full_accuracy"] * 100
        cats = ", ".join(r["categories"]) or "正常系"
        print(
            f"{r['id']} ({r['difficulty']:6s})  "
            f"spk={sa:5.1f}%  role={ra:5.1f}%  full={fa:5.1f}%  [{cats}]"
        )

        for cat in r["categories"] or ["正常系"]:
            if cat not in category_stats:
                category_stats[cat] = {"n": 0, "full": 0}
            category_stats[cat]["n"] += n
            category_stats[cat]["full"] += s["full_correct"]

    if total_n > 0:
        print(f"\n{'─'*70}")
        print(
            f"{'総合':8s}        "
            f"spk={total_spk/total_n*100:5.1f}%  "
            f"role={total_role/total_n*100:5.1f}%  "
            f"full={total_full/total_n*100:5.1f}%  ({total_n}文)"
        )
        print("\nカテゴリ別 full accuracy:")
        for cat, st in sorted(category_stats.items()):
            acc = st["full"] / st["n"] * 100 if st["n"] > 0 else 0
            print(f"  {cat}: {acc:5.1f}%  ({st['n']}文)")

    print(f"\n{bar}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="speaker_tagger ベンチマーク評価")
    parser.add_argument("--prompt-file", help="SYSTEM_PROMPTが書かれたテキストファイル")
    parser.add_argument(
        "--no-call", action="store_true", help="キャッシュされたcurrent_llm_outputを使用"
    )
    parser.add_argument("--label", default="", help="レポートのラベル")
    args = parser.parse_args()

    bench_path = Path(__file__).parent / "speaker_tagger_benchmark.json"
    data = json.loads(bench_path.read_text(encoding="utf-8"))
    test_cases = data["test_cases"]

    if args.no_call:
        print("キャッシュされた結果を使用して評価...")
        results = run_cached_evaluation(test_cases)
        label = args.label or "baseline (cached)"
    else:
        if args.prompt_file:
            system_prompt = Path(args.prompt_file).read_text(encoding="utf-8")
            label = args.label or Path(args.prompt_file).stem
            print(f"プロンプトファイル使用: {args.prompt_file}")
        else:
            from src.speaker_tagger import SYSTEM_PROMPT

            system_prompt = SYSTEM_PROMPT
            label = args.label or "current_prompt (v1)"
            print("現在のSYSTEM_PROMPTを使用")

        print(f"LLM評価中 ({len(test_cases)}テストケース)...")
        results = run_llm_evaluation(test_cases, system_prompt)

    print_report(results, label)


if __name__ == "__main__":
    main()
