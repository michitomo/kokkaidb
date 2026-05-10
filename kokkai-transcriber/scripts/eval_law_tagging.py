"""関連法案タグ精度の評価スクリプト (PR20)。

`tests/fixtures/law_tagging_benchmark.json` のケース定義 (bench_001..) と
実データ (`data/<ref>/qa_pairs.json`) の `related_law_ids` を突合し、
precision / recall / F1 を出力する。

F2/F3 検証ゲートで「法案タグ F1 ≥ 0.6」を満たすかを確認する用途。
LLM を呼ばないオフライン評価のみで動作する。

usage:
    python -m scripts.eval_law_tagging \
        --benchmark tests/fixtures/law_tagging_benchmark.json \
        --data-root ../data \
        [--threshold 0.6]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# bench_003 などの session_ref 末尾に付く「（qa_001のみ）」「（抜粋）」を除去するパターン。
_SESSION_REF_SUFFIX_RE = re.compile(r"[（(].*?[）)]\s*$")


def _strip_session_ref(ref: str) -> str:
    return _SESSION_REF_SUFFIX_RE.sub("", ref).strip()


def _resolve_data_path(data_root: Path, session_ref: str) -> Path:
    """session_ref ('data/shugiin/.../56149_本会議') を data_root 配下の絶対パスに解決する。"""
    cleaned = _strip_session_ref(session_ref)
    rel = cleaned.removeprefix("data/").lstrip("/")
    return data_root / rel


def _load_predicted_law_ids(qa_pairs_path: Path) -> set[str]:
    """qa_pairs.json から related_law_ids の集合を返す (None/空文字は除外)。"""
    if not qa_pairs_path.exists():
        logger.warning("qa_pairs.json not found: %s", qa_pairs_path)
        return set()
    data = json.loads(qa_pairs_path.read_text(encoding="utf-8"))
    predicted: set[str] = set()
    for pair in data.get("pairs", []):
        for law_id in pair.get("related_law_ids") or []:
            if isinstance(law_id, str) and law_id:
                predicted.add(law_id)
    return predicted


def _normalize_forbidden(forbidden_laws: Any) -> set[str]:
    """forbidden_laws は文字列リストか {law_id, ...} の dict リストの 2 形式があるため吸収する。"""
    out: set[str] = set()
    if not isinstance(forbidden_laws, list):
        return out
    for entry in forbidden_laws:
        if isinstance(entry, str):
            out.add(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("law_id"), str):
            out.add(entry["law_id"])
    return out


def _evaluate_case(
    case: dict[str, Any], data_root: Path
) -> dict[str, Any]:
    """1 ケース分のメトリクスを計算する。"""
    case_id = case.get("id", "?")
    session_ref = case.get("session_ref", "")
    expected = case.get("expected", {}) or {}

    required = {r["law_id"] for r in expected.get("required_laws", []) if isinstance(r, dict)}
    forbidden = _normalize_forbidden(expected.get("forbidden_laws", []))
    may_be_empty = bool(expected.get("may_be_empty"))

    qa_pairs_path = _resolve_data_path(data_root, session_ref) / "qa_pairs.json"
    predicted = _load_predicted_law_ids(qa_pairs_path)

    tp = predicted & required
    fn = required - predicted
    fp_forbidden = predicted & forbidden

    # 「forbidden が無く required もある」ケースでは「予測した law のうち required に
    # 含まれないものを FP として扱う」(strict precision)。may_be_empty の場合は
    # 何もタグしないのが正解なので任意の予測を FP 扱い。
    if may_be_empty:
        fp = predicted
    elif required:
        fp = (predicted - required) | fp_forbidden
    else:
        fp = fp_forbidden

    tp_n, fp_n, fn_n = len(tp), len(fp), len(fn)
    precision = tp_n / (tp_n + fp_n) if (tp_n + fp_n) > 0 else (1.0 if not required else 0.0)
    recall = tp_n / (tp_n + fn_n) if (tp_n + fn_n) > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "case_id": case_id,
        "session_ref": session_ref,
        "qa_pairs_exists": qa_pairs_path.exists(),
        "predicted": sorted(predicted),
        "required": sorted(required),
        "forbidden": sorted(forbidden),
        "may_be_empty": may_be_empty,
        "tp": sorted(tp),
        "fp": sorted(fp),
        "fn": sorted(fn),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _aggregate(results: list[dict[str, Any]]) -> dict[str, float]:
    """ケース横断のマイクロ平均 precision/recall/F1 を返す。"""
    tp = sum(len(r["tp"]) for r in results)
    fp = sum(len(r["fp"]) for r in results)
    fn = sum(len(r["fn"]) for r in results)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    macro_f1 = sum(r["f1"] for r in results) / len(results) if results else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "micro_precision": round(precision, 4),
        "micro_recall": round(recall, 4),
        "micro_f1": round(f1, 4),
        "macro_f1": round(macro_f1, 4),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=Path(__file__).parent.parent / "tests/fixtures/law_tagging_benchmark.json",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(__file__).parent.parent.parent / "data",
        help="data/ ディレクトリのルート (qa_pairs.json を読みに行く先)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="micro F1 ≥ threshold で exit 0、未満で exit 1",
    )
    parser.add_argument("--json", action="store_true", help="結果を JSON で標準出力")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    cases = benchmark.get("cases", [])
    if not cases:
        logger.error("benchmark contains no cases: %s", args.benchmark)
        return 2

    results = [_evaluate_case(c, args.data_root) for c in cases]
    summary = _aggregate(results)

    if args.json:
        print(json.dumps({"results": results, "summary": summary}, ensure_ascii=False, indent=2))
    else:
        print(f"# Law tagging eval ({len(results)} cases)")
        for r in results:
            mark = "OK" if r["qa_pairs_exists"] else "MISS"
            print(
                f"[{mark}] {r['case_id']:9} F1={r['f1']:.3f} "
                f"P={r['precision']:.3f} R={r['recall']:.3f} "
                f"required={r['required']} predicted={r['predicted']} "
                f"fp={r['fp']} fn={r['fn']}"
            )
        print()
        print(
            f"Summary: micro_F1={summary['micro_f1']:.3f} "
            f"micro_P={summary['micro_precision']:.3f} "
            f"micro_R={summary['micro_recall']:.3f} "
            f"macro_F1={summary['macro_f1']:.3f} "
            f"(TP={summary['tp']} FP={summary['fp']} FN={summary['fn']})"
        )

    return 0 if summary["micro_f1"] >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
