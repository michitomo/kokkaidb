"""data/ 配下の各セッション JSON のスキーマ整合性を検証する。

`docs/STRUCTURER_REWRITE.md` §2.12 のスキーマ規約に基づいて:

1. 各 JSON が Pydantic モデルで parse できるか (型・必須フィールド)
2. null / 空文字の混在検出 (例: ある committee_id が `null`、別が空文字)
3. metadata.speakers の name と utterances/qa_pairs.speaker の整合性

使い方:

    python -m scripts.validate_data_schema                # data/ 全件
    python -m scripts.validate_data_schema --data-dir /tmp/regen-test
    python -m scripts.validate_data_schema --strict-empty # 必須 str に "" を許容しない
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

# kokkai-transcriber/scripts/foo.py から実行されるので、
# parent (kokkai-transcriber) を sys.path に乗せる。
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import (  # noqa: E402
    QAPairsOutput,
    RawTranscript,
    SessionDetail,
    SummaryOutput,
    TopicsOutput,
    UtterancesOutput,
)

EXPECTED_FILES: dict[str, type[BaseModel]] = {
    "metadata.json": SessionDetail,
    "raw_transcript.json": RawTranscript,
    "utterances.json": UtterancesOutput,
    "qa_pairs.json": QAPairsOutput,
    "summary.json": SummaryOutput,
    "topics.json": TopicsOutput,
}


def iter_session_dirs(data_dir: Path) -> Iterable[Path]:
    """`data/{chamber}/YYYY/MM/DD/{id}_{name}/` を yield する。"""
    for chamber_dir in sorted(data_dir.iterdir()):
        if not chamber_dir.is_dir() or chamber_dir.name in {"laws", "search-index"}:
            continue
        for year in sorted(chamber_dir.glob("*")):
            for month in sorted(year.glob("*")):
                for day in sorted(month.glob("*")):
                    for session in sorted(day.glob("*")):
                        if session.is_dir() and (session / "metadata.json").exists():
                            yield session


def load_session(session_dir: Path) -> tuple[list[str], dict[str, Any]]:
    """セッションディレクトリを読み込み、(エラー一覧, パース済みオブジェクト辞書) を返す。"""
    errors: list[str] = []
    parsed: dict[str, Any] = {}
    for filename, model in EXPECTED_FILES.items():
        path = session_dir / filename
        if not path.exists():
            errors.append(f"missing: {filename}")
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{filename}: invalid JSON ({exc})")
            continue
        try:
            parsed[filename] = model.model_validate(raw)
        except ValidationError as exc:
            err_count = len(exc.errors())
            first = exc.errors()[0]
            loc = ".".join(str(x) for x in first["loc"])
            errors.append(f"{filename}: pydantic validation failed ({err_count} errors; first: {loc} — {first['msg']})")
    return errors, parsed


def check_speaker_consistency(parsed: dict[str, Any]) -> list[str]:
    """metadata.speakers と utterances/qa_pairs の speaker 名の整合性を確認する。

    metadata に存在しない speaker が utterances.unmatched=False で現れる、
    あるいは qa_pairs の question.speaker / answer.speaker が metadata に
    現れない場合を警告する。
    """
    warnings: list[str] = []
    metadata: SessionDetail | None = parsed.get("metadata.json")
    utterances: UtterancesOutput | None = parsed.get("utterances.json")
    qa_pairs: QAPairsOutput | None = parsed.get("qa_pairs.json")
    if metadata is None:
        return warnings

    known_names = {sp.name for sp in metadata.speakers}

    if utterances is not None:
        unknown_in_utterances: set[str] = set()
        for seg in utterances.segments:
            for utt in seg.utterances:
                if not utt.unmatched and utt.speaker and utt.speaker not in known_names:
                    unknown_in_utterances.add(utt.speaker)
        if unknown_in_utterances:
            warnings.append(
                "utterances has speakers not in metadata.speakers (and unmatched=False): "
                + ", ".join(sorted(unknown_in_utterances))
            )

    if qa_pairs is not None:
        unknown_in_qa: set[str] = set()
        for pair in qa_pairs.pairs:
            for name in (pair.question.speaker, pair.answer.speaker):
                if name and name not in known_names:
                    unknown_in_qa.add(name)
        if unknown_in_qa:
            warnings.append(
                "qa_pairs has speakers not in metadata.speakers: "
                + ", ".join(sorted(unknown_in_qa))
            )
    return warnings


def check_null_empty_consistency(parsed: dict[str, Any], strict_empty: bool) -> list[str]:
    """null / 空文字 の使い分けが規約と整合するかを確認する。

    現状は警告レベルのライト・ヒューリスティックで、データ全体の傾向を集計するために
    使う想定 (個別違反でハードに失敗させない)。
    """
    warnings: list[str] = []
    metadata: SessionDetail | None = parsed.get("metadata.json")
    if metadata is None:
        return warnings
    # 例: duration が空文字なら未取得を疑う (規約上は None を推奨だが、現コードは "" を吐く)
    if strict_empty and metadata.duration == "":
        warnings.append("metadata.duration is empty string (use None for missing)")
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        default=str(ROOT.parent / "data"),
        help="検証対象の data ディレクトリ (既定: リポジトリ直下の data/)",
    )
    parser.add_argument("--strict-empty", action="store_true")
    parser.add_argument("--max-failures", type=int, default=0, help="0 = 全件表示")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        print(f"data dir not found: {data_dir}", file=sys.stderr)
        return 2

    total = 0
    failed = 0
    error_categories: Counter[str] = Counter()
    warning_categories: Counter[str] = Counter()
    failures: list[tuple[Path, list[str]]] = []
    warnings_per_session: dict[Path, list[str]] = defaultdict(list)

    for session_dir in iter_session_dirs(data_dir):
        total += 1
        errors, parsed = load_session(session_dir)
        warnings = check_speaker_consistency(parsed) + check_null_empty_consistency(parsed, args.strict_empty)
        if errors:
            failed += 1
            failures.append((session_dir, errors))
            for e in errors:
                error_categories[e.split(":", 1)[0]] += 1
        if warnings:
            warnings_per_session[session_dir].extend(warnings)
            for w in warnings:
                warning_categories[w.split(":", 1)[0]] += 1

    print(f"Validated {total} sessions in {data_dir}")
    print(f"  failed: {failed}")
    print(f"  with warnings: {len(warnings_per_session)}")

    if error_categories:
        print("\nError categories:")
        for cat, n in error_categories.most_common():
            print(f"  {n:4d}  {cat}")
    if warning_categories:
        print("\nWarning categories:")
        for cat, n in warning_categories.most_common():
            print(f"  {n:4d}  {cat}")

    if failures:
        print("\nFailures:")
        shown = failures if args.max_failures == 0 else failures[: args.max_failures]
        for session_dir, errors in shown:
            rel = session_dir.relative_to(data_dir)
            print(f"  {rel}")
            for e in errors:
                print(f"    - {e}")
        if args.max_failures and len(failures) > args.max_failures:
            print(f"  ... ({len(failures) - args.max_failures} more)")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
