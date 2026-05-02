"""閣法 (CLB) + 衆法/参法 (Gian) を統合した data/laws/laws.json を生成する。

LLMの法案タグ付けプロンプトに渡す単一ソース。

使用方法:
    python -m src.laws_builder --sessions 221
    python -m src.laws_builder --sessions 217,218,219,220,221 --output-dir data/laws
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.scrapers.bill_models import BillDetail, BillType
from src.scrapers.clb import CLBScraper
from src.scrapers.gian import GianScraper

logger = logging.getLogger(__name__)

# デフォルト出力先（kokkai-transcriber/ の1つ上の data/laws/）
_DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "laws"

_TYPE_JA: dict[BillType, str] = {
    "kakuhou": "閣法",
    "shuhou": "衆法",
    "sanhou": "参法",
}

# 並び順（種別ごと）
_TYPE_ORDER: dict[BillType, int] = {
    "kakuhou": 0,
    "shuhou": 1,
    "sanhou": 2,
}

_JST = timezone(timedelta(hours=9))

_REASON_MAX_CHARS = 200


def _normalize_title(title: str) -> str:
    """dedup キー用にタイトルを正規化する。

    CLB と Gian ではタイトル中の空白（全角・半角）の入り方が揺れることが
    実運用で観測されるため、dedup のためにあらゆる空白文字を除去する。
    """
    # 全角スペース・半角スペース・改行・タブを含む全ての空白を除去
    return re.sub(r"[\s\u3000]+", "", title)


def _bill_number_sort_key(bill_number: str | None) -> tuple[int, str]:
    """法案番号を数値ソートするためのキーを返す。

    "第1号" や "1" のような文字列から数値部分を取り出す。
    """
    if not bill_number:
        return (10**9, "")
    m = re.search(r"\d+", bill_number)
    if m:
        return (int(m.group(0)), bill_number)
    return (10**9, bill_number)


def _sort_key(bill: BillDetail) -> tuple[int, int, tuple[int, str]]:
    """出力ソートキー。session desc → type (kakuhou→shuhou→sanhou) → bill_number asc。"""
    return (
        -bill.diet_session,
        _TYPE_ORDER.get(bill.type, 99),
        _bill_number_sort_key(bill.bill_number),
    )


def _compact_line(bill: BillDetail) -> str:
    """laws_compact.txt の1行分を組み立てる。"""
    type_ja = _TYPE_JA.get(bill.type, bill.type)
    parts: list[str] = [f"{bill.id}: [{type_ja}] {bill.title}"]
    if bill.submitter:
        parts.append(bill.submitter)
    if bill.reason:
        reason = bill.reason.replace("\n", " ").strip()
        if len(reason) > _REASON_MAX_CHARS:
            reason = reason[:_REASON_MAX_CHARS] + "..."
        parts.append(f"提出理由: {reason}")
    return " | ".join(parts)


def build_laws_json(sessions: list[int], output_dir: Path) -> None:
    """指定された国会回次の法案を CLB + Gian から取得して laws.json / laws_compact.txt を出力する。

    Dedup ルール: `(diet_session, normalized_title)` をキーに、CLB を優先して保持する。
    CLB は閣法のみ扱うため、Gian からの衆法・参法は基本的にそのまま追加される。

    Args:
        sessions: 対象国会回次のリスト（例: `[217, 218, 219, 220, 221]`）
        output_dir: 出力先ディレクトリ。存在しない場合は作成する。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    clb_scraper = CLBScraper()
    gian_scraper = GianScraper()

    seen_keys: set[tuple[int, str]] = set()
    collected: list[BillDetail] = []

    for session in sessions:
        logger.info("=== Session %d ===", session)

        # CLB（閣法 + 提出理由）を先に投入して優先する
        try:
            clb_bills = clb_scraper.scrape_session(session)
        except ValueError as exc:
            # ランディングに当該セッションが無い場合はスキップ
            logger.warning("CLB scrape_session(%d) skipped: %s", session, exc)
            clb_bills = []
        logger.info("CLB returned %d kakuhou bill(s) for session %d", len(clb_bills), session)

        for bill in clb_bills:
            key = (bill.diet_session, _normalize_title(bill.title))
            if key in seen_keys:
                logger.debug("Duplicate within CLB, skipping: %s", bill.title)
                continue
            seen_keys.add(key)
            collected.append(bill)

        # Gian（衆法・参法 + フォールバック閣法）
        try:
            gian_bills = gian_scraper.list_all_bills(session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gian list_all_bills(%d) failed: %s", session, exc)
            gian_bills = []
        logger.info("Gian returned %d bill(s) for session %d", len(gian_bills), session)

        for bill in gian_bills:
            key = (bill.diet_session, _normalize_title(bill.title))
            if key in seen_keys:
                logger.debug(
                    "Duplicate (already have from CLB or shugiin/sangiin): %s",
                    bill.title,
                )
                continue
            seen_keys.add(key)
            collected.append(bill)

    collected.sort(key=_sort_key)

    generated_at = datetime.now(tz=_JST).isoformat(timespec="seconds")

    laws_json_path = output_dir / "laws.json"
    laws_compact_path = output_dir / "laws_compact.txt"

    payload = {
        "generated_at": generated_at,
        "sessions_covered": sessions,
        "count": len(collected),
        "bills": [bill.model_dump(mode="json") for bill in collected],
    }
    laws_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Wrote %s (%d bills)", laws_json_path, len(collected))

    compact_lines = [_compact_line(bill) for bill in collected]
    laws_compact_path.write_text("\n".join(compact_lines) + "\n", encoding="utf-8")
    logger.info("Wrote %s (%d lines)", laws_compact_path, len(compact_lines))


def _parse_sessions(raw: str) -> list[int]:
    """ "217,218,219" のようなカンマ区切り文字列を整数リストに変換する。"""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise argparse.ArgumentTypeError("At least one session number is required")
    result: list[int] = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"Invalid session number: {p!r}") from exc
    return result


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="閣法・衆法・参法を統合した laws.json / laws_compact.txt を生成する",
    )
    parser.add_argument(
        "--sessions",
        type=_parse_sessions,
        required=True,
        help="対象国会回次（カンマ区切り、例: 217,218,219,220,221）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help=f"出力先ディレクトリ（デフォルト: {_DEFAULT_OUTPUT_DIR}）",
    )
    args = parser.parse_args()

    try:
        build_laws_json(sessions=args.sessions, output_dir=args.output_dir)
    except Exception as exc:  # noqa: BLE001
        logger.error("laws_builder failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
