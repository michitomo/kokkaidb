"""data/ 以下の全 utterances.json から MiniSearch 用検索インデックスを生成する。

使用方法:
    python -m src.build_search_index

SudachiPy + sudachidict-core で形態素解析（Mode C: 長単位）。
出力: data/search-index/search-index.json
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

try:
    from sudachipy import dictionary, tokenizer
except ImportError:
    print("sudachipy not installed. Run: pip install sudachipy sudachidict-core", file=sys.stderr)
    sys.exit(1)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
OUTPUT_PATH = DATA_DIR / "search-index" / "search-index.json"

MAX_INPUT_BYTES = 48000

KEEP_POS = frozenset({"名詞", "動詞", "形容詞", "副詞", "形状詞", "接頭辞"})


def collect_utterance_files(data_dir: Path) -> list[Path]:
    files: list[Path] = []
    for chamber in ("shugiin", "sangiin"):
        chamber_dir = data_dir / chamber
        if not chamber_dir.exists():
            continue
        for year_dir in sorted(chamber_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            for month_dir in sorted(year_dir.iterdir()):
                if not month_dir.is_dir():
                    continue
                for day_dir in sorted(month_dir.iterdir()):
                    if not day_dir.is_dir():
                        continue
                    for session_dir in sorted(day_dir.iterdir()):
                        if not session_dir.is_dir():
                            continue
                        fp = session_dir / "utterances.json"
                        if fp.exists():
                            files.append(fp)
    return files


def tokenize_safe(tok, text: str, mode) -> list[str]:
    """長すぎる入力をトランケートして tokenize。
    SudachiPy の品詞体系: 大分類=0 が品詞名（名詞・動詞・形容詞・副詞・形状詞）。
    dictionary_form() で活用形を辞書形に正規化（「行った」→「行う」）。
    """
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_INPUT_BYTES:
        text = encoded[:MAX_INPUT_BYTES].decode("utf-8", errors="replace")
    try:
        tokens: list[str] = []
        for m in tok.tokenize(text, mode):
            pos_major = m.part_of_speech()[0]
            if pos_major not in KEEP_POS:
                continue
            form = m.dictionary_form().strip()
            if form:
                tokens.append(form)
        return tokens
    except Exception as exc:
        logger.warning("tokenize failed (len=%d), falling back to unigram: %s", len(encoded), exc)
        return list(text)


def build_docs(tok, mode, utterance_files: list[Path], data_dir: Path) -> list[dict]:
    docs: list[dict] = []
    for fp in utterance_files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("skipping %s: %s", fp, exc)
            continue

        rel = fp.relative_to(data_dir)
        parts = rel.parts
        chamber = parts[0]
        date_val = f"{parts[1]}-{parts[2]}-{parts[3]}"
        session_id = parts[4].split("_", 1)[0]
        committee = parts[4].split("_", 1)[1] if "_" in parts[4] else ""
        slug = parts[4]
        url = f"/{chamber}/{parts[1]}/{parts[2]}/{parts[3]}/{slug}"

        for seg_idx, seg in enumerate(data.get("segments", [])):
            for utt_idx, utt in enumerate(seg.get("utterances", [])):
                text = (utt.get("text") or "").strip()
                if not text:
                    continue
                global_id = f"{chamber}_{session_id}_{seg_idx}_{utt_idx}"
                tokens = " ".join(tokenize_safe(tok, text, mode))
                docs.append({
                    "id": global_id,
                    "chamber": chamber,
                    "date": date_val,
                    "committee": committee,
                    "speaker": utt.get("speaker", ""),
                    "role": utt.get("role", ""),
                    "text": text,
                    "tokens": tokens,
                    "url": url,
                    "segIdx": seg_idx,
                    "uttIdx": utt_idx,
                })

    return docs


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Loading SudachiPy dictionary (core)...")
    tok = dictionary.Dictionary(dict="core").create()
    mode = tokenizer.Tokenizer.SplitMode.C
    logger.info("SudachiPy ready")

    utterance_files = collect_utterance_files(DATA_DIR)
    logger.info("Found %d utterance files", len(utterance_files))

    docs = build_docs(tok, mode, utterance_files, DATA_DIR)
    logger.info("Total documents: %d", len(docs))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    size_mb = OUTPUT_PATH.stat().st_size / 1024 / 1024
    logger.info("Written: %s (%.1f MB; gzip ~%.0f MB)", OUTPUT_PATH, size_mb, size_mb * 0.25)


if __name__ == "__main__":
    main()
