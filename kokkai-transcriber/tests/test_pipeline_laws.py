"""pipeline._load_laws_compact() のユニットテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import pipeline


def test_load_laws_compact_returns_file_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """laws_compact.txt が存在すればその内容をそのまま返す。"""
    laws_dir = tmp_path / "laws"
    laws_dir.mkdir()
    content = (
        "law_001: [閣法] 財政運営に必要な財源の確保を図る... | 財務省 | 提出理由: xxx\n"
        "law_002: [衆法] 政治資金規正法の一部を改正する法律案\n"
    )
    (laws_dir / "laws_compact.txt").write_text(content, encoding="utf-8")

    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)

    result = pipeline._load_laws_compact()
    assert result == content


def test_load_laws_compact_missing_file_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """laws_compact.txt が無ければ空文字列を返す。"""
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    # laws/ ディレクトリも作らない → 完全に存在しない状態
    assert pipeline._load_laws_compact() == ""


def test_load_laws_compact_counts_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """非空行をカウントしてログに出す。"""
    laws_dir = tmp_path / "laws"
    laws_dir.mkdir()
    content = "law_001: foo\nlaw_002: bar\n\nlaw_003: baz\n"
    (laws_dir / "laws_compact.txt").write_text(content, encoding="utf-8")
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)

    with caplog.at_level("INFO", logger=pipeline.logger.name):
        result = pipeline._load_laws_compact()

    assert result == content
    assert any("Loaded 3 laws for LLM tagging" in rec.message for rec in caplog.records)
