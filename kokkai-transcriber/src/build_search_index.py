"""data/ 以下の全セッションから MiniSearch 用検索インデックスを生成する。

質疑セッション: qa_pairs.json の各ペア（トピック+要約）をインデックス化 → anchor: qa-{id}
手続きセッション: utterances.json の発言セグメントをインデックス化 → anchor: utt-{id}

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

KEEP_POS = frozenset({"名詞", "動詞", "形容詞", "副詞", "形状詞", "接頭辞", "接尾辞"})


def collect_session_dirs(data_dir: Path) -> list[Path]:
    dirs: list[Path] = []
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
                        if session_dir.is_dir():
                            dirs.append(session_dir)
    return dirs


def tokenize_safe(tok, text: str, mode_c, mode_a) -> list[str]:
    """長すぎる入力をトランケートして tokenize。
    Mode C (長単位) + Mode A (短単位) の両方で分割し、重複除去して結合。
    これにより「プッシュ型」のような複合語が「プッシュ」「型」でも検索可能になる。
    """
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_INPUT_BYTES:
        text = encoded[:MAX_INPUT_BYTES].decode("utf-8", errors="replace")
    try:
        tokens: list[str] = []
        seen: set[str] = set()
        for m in tok.tokenize(text, mode_c):
            pos_major = m.part_of_speech()[0]
            if pos_major not in KEEP_POS:
                continue
            form = m.dictionary_form().strip()
            if form and form not in seen:
                seen.add(form)
                tokens.append(form)
        for m in tok.tokenize(text, mode_a):
            pos_major = m.part_of_speech()[0]
            if pos_major not in KEEP_POS:
                continue
            form = m.dictionary_form().strip()
            if form and form not in seen:
                seen.add(form)
                tokens.append(form)
        return tokens
    except Exception as exc:
        logger.warning("tokenize failed (len=%d), falling back to unigram: %s", len(encoded), exc)
        return list(text)


def build_docs_from_session(tok, mode_c, mode_a, session_dir: Path, data_dir: Path) -> list[dict]:
    rel = session_dir.relative_to(data_dir)
    parts = rel.parts
    chamber = parts[0]
    date_val = f"{parts[1]}-{parts[2]}-{parts[3]}"
    session_id = parts[4].split("_", 1)[0]
    committee = parts[4].split("_", 1)[1] if "_" in parts[4] else ""
    slug = parts[4]
    url = f"/{chamber}/{parts[1]}/{parts[2]}/{parts[3]}/{slug}"

    # 質疑セッション: qa_pairs.json を優先
    qa_path = session_dir / "qa_pairs.json"
    if qa_path.exists():
        try:
            qa_data = json.loads(qa_path.read_text(encoding="utf-8"))
            pairs = qa_data.get("pairs", [])
            if pairs:
                docs: list[dict] = []
                for pair in pairs:
                    pair_id = pair.get("id", "")
                    topic = pair.get("topic", "")
                    q = pair.get("question", {})
                    a = pair.get("answer", {})
                    q_speaker = q.get("speaker", "")
                    a_speaker = a.get("speaker", "")
                    q_summary = (q.get("summary") or "").strip()
                    a_summary = (a.get("summary") or "").strip()
                    text_for_index = f"{topic} {q_summary} {a_summary}"
                    text_for_display = (q_summary + " / " + a_summary) if (q_summary and a_summary) else (q_summary or a_summary)
                    tokens = " ".join(tokenize_safe(tok, text_for_index, mode_c, mode_a))
                    docs.append({
                        "id": f"{chamber}_{session_id}_{pair_id}",
                        "type": "qa",
                        "chamber": chamber,
                        "date": date_val,
                        "committee": committee,
                        "topic": topic,
                        "q_speaker": q_speaker,
                        "a_speaker": a_speaker,
                        "speaker": "",
                        "role": "",
                        "text": text_for_display,
                        "tokens": tokens,
                        "url": url,
                        "anchor": f"qa-{pair_id}",
                    })
                return docs
        except Exception as exc:
            logger.warning("skipping qa_pairs %s: %s", qa_path, exc)

    # 手続きセッション: utterances.json にフォールバック
    utt_path = session_dir / "utterances.json"
    if not utt_path.exists():
        return []
    try:
        data = json.loads(utt_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("skipping %s: %s", utt_path, exc)
        return []

    docs = []
    for seg_idx, seg in enumerate(data.get("segments", [])):
        for utt_idx, utt in enumerate(seg.get("utterances", [])):
            text = (utt.get("text") or "").strip()
            if not text:
                continue
            global_id = f"{chamber}_{session_id}_{seg_idx}_{utt_idx}"
            tokens = " ".join(tokenize_safe(tok, text, mode_c, mode_a))
            docs.append({
                "id": global_id,
                "type": "utt",
                "chamber": chamber,
                "date": date_val,
                "committee": committee,
                "topic": "",
                "q_speaker": "",
                "a_speaker": "",
                "speaker": utt.get("speaker", ""),
                "role": utt.get("role", ""),
                "text": text,
                "tokens": tokens,
                "url": url,
                "anchor": f"utt-{global_id}",
            })
    return docs


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Loading SudachiPy dictionary (core)...")
    tok = dictionary.Dictionary(dict="core").create()
    mode_c = tokenizer.Tokenizer.SplitMode.C
    mode_a = tokenizer.Tokenizer.SplitMode.A
    logger.info("SudachiPy ready (Mode C + Mode A)")

    session_dirs = collect_session_dirs(DATA_DIR)
    logger.info("Found %d session dirs", len(session_dirs))

    docs: list[dict] = []
    for sd in session_dirs:
        docs.extend(build_docs_from_session(tok, mode_c, mode_a, sd, DATA_DIR))

    qa_count = sum(1 for d in docs if d["type"] == "qa")
    utt_count = len(docs) - qa_count
    logger.info("Total documents: %d (Q&A: %d, 発言: %d)", len(docs), qa_count, utt_count)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    size_mb = OUTPUT_PATH.stat().st_size / 1024 / 1024
    logger.info("Written: %s (%.1f MB)", OUTPUT_PATH, size_mb)


if __name__ == "__main__":
    main()
