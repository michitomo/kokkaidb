"""Whisperプロンプト改善のA/Bテスト評価スクリプト。

ベンチマーク JSON の各ケースに対して、指定したプロンプトバリアントで Whisper を
再実行し、圧縮率・logprob・ループ有無を比較してレポートを出力する。

セッション音声は HLS URL から必要な区間だけ取得するため、実行ごとにダウンロードが
発生する。DEEPINFRA_API_KEY 環境変数が必須。

Usage:
    cd kokkai-transcriber
    source .venv/bin/activate

    # 全ベンチマークケースを V2 プロンプトで実行（デフォルト）
    python -m eval.run_whisper_eval

    # 特定パターンのみ実行
    python -m eval.run_whisper_eval --pattern loop_prompt_base_word loop_suffix_speaker_name

    # 特定ケースのみ
    python -m eval.run_whisper_eval --case-id 56088_豊田真由子__loop_prompt_base_word

    # プロンプト確認のみ（音声DL・API呼び出しなし）
    python -m eval.run_whisper_eval --dry-run

    # 結果ディレクトリ指定
    python -m eval.run_whisper_eval --output-dir eval/results/whisper_v2
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

import openai
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

EVAL_DIR = Path(__file__).parent
BENCHMARK_FILE = EVAL_DIR / "golden" / "whisper_prompt_benchmark.json"
DEFAULT_OUTPUT_DIR = EVAL_DIR / "results" / "whisper"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
WHISPER_MODEL = "openai/whisper-large-v3-turbo"

# ループ検出の圧縮率閾値
LOOP_CR_THRESHOLD = 3.5


# ---------------------------------------------------------------------------
# プロンプトバリアント定義
# ---------------------------------------------------------------------------

def build_prompt_v1(case: dict) -> str:
    """V1（ベースライン）: ベンチマークに記録済みの実際に使われたプロンプト。"""
    return case["prompt_used"]


def build_prompt_v2(case: dict) -> str:
    """V2: 石井啓一・法律名・出席議員リスト廃止 + 委員会＋発言者：形式サフィックス。"""
    base = (
        "第221回国会、衆議院の質疑応答。"
        "高市早苗内閣総理大臣、木原稔内閣官房長官、茂木敏充外務大臣、"
        "片山さつき財務大臣、上野賢一郎厚生労働大臣、"
        "赤澤亮正経済産業大臣、小泉進次郎防衛大臣。"
        "自由民主党、立憲民主党、日本維新の会、公明党、日本共産党、"
        "国民民主党、チームみらい、参政党、れいわ新選組、日本保守党。"
        "森英介議長。"
    )
    committee = case.get("committee", "委員会")
    name = case["speaker_name"]
    affil = case.get("speaker_affiliation", "")
    return base + f"{committee}。{name}（{affil}）："


PROMPT_VARIANTS: dict[str, callable] = {
    "v1": build_prompt_v1,
    "v2": build_prompt_v2,
}


# ---------------------------------------------------------------------------
# 音声取得・抽出
# ---------------------------------------------------------------------------

def _get_hls_url(session_id: str, committee: str, date: str) -> str:
    """data/ ディレクトリから HLS URL を取得する。"""
    parts = date.split("-")
    if len(parts) != 3:
        raise ValueError(f"Invalid date format: {date}")
    year, month, day = parts
    meta_path = DATA_DIR / "shugiin" / year / month / day / f"{session_id}_{committee}" / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {meta_path}")
    with open(meta_path) as f:
        meta = json.load(f)
    url = meta.get("hls_url", "")
    if not url:
        raise ValueError(f"hls_url is empty in {meta_path}")
    return url


def _get_speaker_timing(case: dict) -> tuple[float, float]:
    """ベンチマークケースの発言者セグメント開始・終了秒数を返す。

    all_speakers リストから対象発言者の start_seconds を見つけ、
    次の発言者の start_seconds を終了点とする。
    """
    all_speakers = case.get("all_speakers", [])
    speaker_name = case["speaker_name"]

    # 発言者のインデックスを特定
    idx = next(
        (i for i, s in enumerate(all_speakers) if s["name"] == speaker_name),
        None,
    )
    if idx is None:
        raise ValueError(f"Speaker '{speaker_name}' not found in all_speakers")

    start = float(all_speakers[idx]["start_seconds"])

    # 終了点: 次の発言者の開始、または発言者の duration_minutes から推定
    if idx + 1 < len(all_speakers):
        end = float(all_speakers[idx + 1]["start_seconds"])
    else:
        duration_min = int(all_speakers[idx].get("duration_minutes", 30))
        end = start + duration_min * 60

    return start, end


def extract_speaker_segment(
    hls_url: str,
    start_seconds: float,
    end_seconds: float,
    output_path: Path,
) -> None:
    """HLS から発言者区間のみを WAV ファイルとして抽出する。

    ffmpeg の -ss/-to で求める区間だけデコードするためダウンロード量を最小化する。
    """
    duration = end_seconds - start_seconds
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "warning",
        "-ss", str(start_seconds),
        "-i", hls_url,
        "-t", str(duration),
        "-ar", "16000",
        "-ac", "1",
        "-acodec", "pcm_s16le",
        str(output_path),
    ]
    logger.info(
        "Extracting %.0f-%.0fs from HLS → %s",
        start_seconds, end_seconds, output_path.name,
    )
    subprocess.run(cmd, check=True, capture_output=True)


# ---------------------------------------------------------------------------
# Whisper 呼び出し
# ---------------------------------------------------------------------------

def run_whisper(wav_path: Path, prompt: str) -> dict:
    """Whisper API を呼び出し、全セグメントのメタデータを返す。"""
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        raise OSError("DEEPINFRA_API_KEY is not set")
    client = openai.OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)

    with open(wav_path, "rb") as f:
        f_bytes = f.read()

    start = time.monotonic()
    result = client.audio.transcriptions.create(
        model=WHISPER_MODEL,
        file=("audio.wav", io.BytesIO(f_bytes), "audio/wav"),
        language="ja",
        response_format="verbose_json",
        timestamp_granularities=["segment"],
        prompt=prompt,
    )
    elapsed = time.monotonic() - start

    segments = getattr(result, "segments", None) or []
    return {
        "text": getattr(result, "text", ""),
        "latency_seconds": round(elapsed, 2),
        "segments": [
            {
                "id": getattr(s, "id", 0),
                "start": round(getattr(s, "start", 0.0), 2),
                "end": round(getattr(s, "end", 0.0), 2),
                "text": getattr(s, "text", ""),
                "avg_logprob": round(getattr(s, "avg_logprob", 0.0), 4),
                "compression_ratio": round(getattr(s, "compression_ratio", 0.0), 2),
                "no_speech_prob": round(getattr(s, "no_speech_prob", 0.0), 4),
                "temperature": getattr(s, "temperature", 0.0),
            }
            for s in (
                [dict(s) if isinstance(s, dict) else s for s in segments]
            )
        ],
    }


# ---------------------------------------------------------------------------
# メトリクス計算
# ---------------------------------------------------------------------------

def _is_loop(text: str, cr: float) -> bool:
    """テキストがループ出力かどうかを判定する。"""
    if cr < LOOP_CR_THRESHOLD:
        return False
    # 先頭4文字が頻繁に繰り返されている場合
    if len(text) > 20:
        unit = text[:4].strip()
        if unit and text.count(unit) > len(text) / (len(unit) * 3):
            return True
    return True  # CR > threshold であればループとみなす


def compute_metrics(whisper_result: dict, target_wseg: dict) -> dict:
    """Whisper 結果から評価メトリクスを計算する。

    target_wseg は V1 で問題が発生していた whisper_segment の情報
    （start_seconds, duration_seconds）を持ち、同一時間帯のセグメントを探す。
    """
    segments = whisper_result.get("segments", [])

    # 問題発生区間（V1ではループだった時間帯）に対応するセグメントを探す
    target_start = target_wseg.get("start_seconds", 0)
    target_dur = target_wseg.get("duration_seconds", 30)
    target_end = target_start + target_dur

    overlap_segs = [
        s for s in segments
        if s["start"] < target_end and s["end"] > target_start
    ]

    # 対象区間内でのループ検出
    loops_in_target = [s for s in overlap_segs if _is_loop(s["text"], s["compression_ratio"])]

    # 全セグメントでのループ検出
    all_loops = [s for s in segments if _is_loop(s["text"], s["compression_ratio"])]

    avg_cr_target = (
        sum(s["compression_ratio"] for s in overlap_segs) / len(overlap_segs)
        if overlap_segs else 0.0
    )
    avg_lp_target = (
        sum(s["avg_logprob"] for s in overlap_segs) / len(overlap_segs)
        if overlap_segs else 0.0
    )

    return {
        "total_segments": len(segments),
        "loop_segments_in_target": len(loops_in_target),
        "loop_segments_total": len(all_loops),
        "target_loop_resolved": len(loops_in_target) == 0,
        "avg_compression_ratio_in_target": round(avg_cr_target, 2),
        "avg_logprob_in_target": round(avg_lp_target, 4),
        "overlap_segment_count": len(overlap_segs),
        "overlap_segment_texts": [s["text"][:80] for s in overlap_segs[:3]],
    }


def compute_name_metrics(whisper_result: dict, expected_corrections: dict) -> dict:
    """名前認識系ケースのメトリクスを計算する。"""
    full_text = whisper_result.get("text", "")
    results = {}
    for wrong, correct in expected_corrections.items():
        wrong_count = full_text.count(wrong)
        correct_count = full_text.count(correct)
        total = wrong_count + correct_count
        results[correct] = {
            "correct_occurrences": correct_count,
            "wrong_occurrences": wrong_count,
            "accuracy": round(correct_count / total, 2) if total > 0 else None,
        }
    return results


# ---------------------------------------------------------------------------
# メイン評価ループ
# ---------------------------------------------------------------------------

def _load_benchmark() -> dict:
    with open(BENCHMARK_FILE) as f:
        return json.load(f)


def run_case(
    case: dict,
    variants: list[str],
    output_dir: Path,
    dry_run: bool = False,
) -> dict:
    """1ケースを複数バリアントで評価し、結果 dict を返す。"""
    case_id = case["case_id"]
    session_id = case["session_id"]
    committee = case.get("committee", "")
    date = case.get("date", "")
    pattern = case["error_pattern"]

    logger.info("=== Case: %s [%s] ===", case_id, pattern)

    result = {
        "case_id": case_id,
        "error_pattern": pattern,
        "session_id": session_id,
        "committee": committee,
        "date": date,
        "speaker_name": case["speaker_name"],
        "variants": {},
    }

    # プロンプト表示
    for variant in variants:
        builder = PROMPT_VARIANTS[variant]
        prompt = builder(case)
        token_approx = round(len(prompt) / 1.5)
        result["variants"][variant] = {
            "prompt": prompt,
            "prompt_char_count": len(prompt),
            "prompt_token_approx": token_approx,
        }
        logger.info(
            "  [%s] chars=%d tokens≈%d  suffix: ...%s",
            variant, len(prompt), token_approx, prompt[-60:],
        )

    if dry_run:
        return result

    # 音声抽出
    try:
        hls_url = _get_hls_url(session_id, committee, date)
    except (FileNotFoundError, ValueError) as e:
        logger.warning("Cannot get HLS URL for %s: %s", case_id, e)
        result["error"] = str(e)
        return result

    try:
        spk_start, spk_end = _get_speaker_timing(case)
    except ValueError as e:
        logger.warning("Cannot determine timing for %s: %s", case_id, e)
        result["error"] = str(e)
        return result

    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / f"{case_id}.wav"

        try:
            extract_speaker_segment(hls_url, spk_start, spk_end, wav_path)
        except subprocess.CalledProcessError as e:
            logger.error("Audio extraction failed for %s: %s", case_id, e)
            result["error"] = f"ffmpeg failed: {e}"
            return result

        # 各バリアントで Whisper 実行
        target_wseg = case.get("whisper_output", {})
        for variant in variants:
            builder = PROMPT_VARIANTS[variant]
            prompt = builder(case)

            try:
                logger.info("  Running Whisper [%s]...", variant)
                whisper_result = run_whisper(wav_path, prompt)

                metrics: dict
                if pattern in (
                    "name_truncation",
                    "party_name_truncation",
                    "party_name_abbreviation",
                ):
                    metrics = compute_name_metrics(
                        whisper_result,
                        case.get("expected_corrections", {}),
                    )
                else:
                    metrics = compute_metrics(whisper_result, target_wseg)

                result["variants"][variant].update({
                    "whisper_text_preview": whisper_result["text"][:300],
                    "latency_seconds": whisper_result["latency_seconds"],
                    "metrics": metrics,
                })
                logger.info("  [%s] metrics: %s", variant, metrics)

            except Exception as e:  # noqa: BLE001
                logger.error("Whisper failed for %s [%s]: %s", case_id, variant, e)
                result["variants"][variant]["error"] = str(e)

    return result


def _build_summary(results: list[dict], variants: list[str]) -> dict:
    """全ケースの結果を集約してサマリーを生成する。"""
    summary: dict = {v: {"cases": 0, "loop_resolved": 0, "errors": 0} for v in variants}

    for r in results:
        if "error" in r:
            for v in variants:
                summary[v]["errors"] += 1
            continue
        for v in variants:
            vdata = r["variants"].get(v, {})
            summary[v]["cases"] += 1
            metrics = vdata.get("metrics", {})
            if isinstance(metrics, dict) and "target_loop_resolved" in metrics:
                if metrics["target_loop_resolved"]:
                    summary[v]["loop_resolved"] += 1

    # 改善率
    for v in variants:
        total = summary[v]["cases"]
        if total > 0:
            summary[v]["loop_resolve_rate"] = round(summary[v]["loop_resolved"] / total, 2)

    return summary


def run_evaluation(
    patterns: list[str] | None = None,
    case_ids: list[str] | None = None,
    variants: list[str] | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    dry_run: bool = False,
) -> None:
    benchmark = _load_benchmark()
    all_cases = benchmark["cases"]

    # フィルタリング
    if case_ids:
        all_cases = [c for c in all_cases if c["case_id"] in case_ids]
    if patterns:
        all_cases = [c for c in all_cases if c["error_pattern"] in patterns]

    active_variants = variants or ["v1", "v2"]
    # v1 以外のカスタムバリアントは定義済みのものだけ許可
    for v in active_variants:
        if v not in PROMPT_VARIANTS:
            raise ValueError(f"Unknown prompt variant: {v!r}. Available: {list(PROMPT_VARIANTS)}")

    logger.info(
        "Running %d cases × %d variants%s",
        len(all_cases),
        len(active_variants),
        " [DRY-RUN]" if dry_run else "",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for case in all_cases:
        case_result = run_case(case, active_variants, output_dir, dry_run=dry_run)
        results.append(case_result)

        # ケース単位でも保存（中断耐性）
        case_path = output_dir / f"{case['case_id']}.json"
        with open(case_path, "w") as f:
            json.dump(case_result, f, ensure_ascii=False, indent=2)

    summary = _build_summary(results, active_variants)

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "variants": active_variants,
        "total_cases": len(results),
        "dry_run": dry_run,
        "summary": summary,
        "results": results,
    }

    report_path = output_dir / "report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # テキストサマリー
    logger.info("=== Evaluation Report ===")
    for v in active_variants:
        s = summary[v]
        logger.info(
            "  [%s] cases=%d loop_resolved=%d/%d errors=%d",
            v,
            s["cases"],
            s.get("loop_resolved", 0),
            s["cases"],
            s["errors"],
        )
    logger.info("Report saved: %s", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Whisperプロンプト改善のA/Bテスト評価",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--pattern",
        nargs="+",
        dest="patterns",
        help="評価するエラーパターン（複数可）",
    )
    parser.add_argument(
        "--case-id",
        nargs="+",
        dest="case_ids",
        help="評価するケースID（複数可）",
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        default=["v1", "v2"],
        help="比較するプロンプトバリアント（default: v1 v2）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"結果出力ディレクトリ（default: {DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="プロンプト確認のみ（音声DL・API呼び出しなし）",
    )
    args = parser.parse_args()

    run_evaluation(
        patterns=args.patterns,
        case_ids=args.case_ids,
        variants=args.variants,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
