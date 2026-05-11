"""パイプラインテスト"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.models import (
    AnswerDetail,
    KeyCommitment,
    QAPair,
    QAPairsOutput,
    QuestionDetail,
    RawTranscript,
    SegmentTranscript,
    SegmentUtterances,
    SessionDetail,
    SpeakerInfo,
    SummaryOutput,
    Topic,
    TopicsOutput,
    Utterance,
    UtterancesOutput,
    WhisperSegment,
)
from src.pipeline import _get_scraper, run_pipeline
from src.scrapers.sangiin import SangiinScraper
from src.scrapers.shugiin import ShugiinScraper


@pytest.fixture
def mock_session_detail() -> SessionDetail:
    return SessionDetail(
        chamber="shugiin",
        session_id="56149",
        date="2026-04-09",
        committee="本会議",
        committee_id=1,
        hls_url="http://hlsvod.shugiintv.go.jp/vod/_definst_/amlst:2026/2026-0409-1300-00/playlist.m3u8",
        source_url="https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=56149",
        speakers=[
            SpeakerInfo(
                name="古川あおい",
                affiliation="チームみらい",
                role="質疑者",
                start_seconds=7320.2,
                start_time="14:42",
                duration_minutes=18,
            ),
        ],
    )


@pytest.fixture
def mock_raw_transcript() -> RawTranscript:
    long_text = "チームみらいの古川あおいです。" * 8  # >100 chars to pass pipeline validation
    return RawTranscript(
        session_id="56149",
        segments=[
            SegmentTranscript(
                segment_index=0,
                speaker_name="古川あおい",
                start_seconds=7320.2,
                text=long_text,
                whisper_segments=[
                    WhisperSegment(
                        id=0, seek=0, start=7320.2, end=7380.0,
                        text=long_text,
                    )
                ],
            )
        ],
    )


@pytest.fixture
def mock_utterances_output() -> UtterancesOutput:
    return UtterancesOutput(
        segments=[
            SegmentUtterances(
                segment_index=0,
                segment_speaker="古川あおい",
                segment_affiliation="チームみらい",
                start_seconds=7320.2,
                video_url="https://www.shugiintv.go.jp/jp/index.php?ex=VL&media_type=&deli_id=56149&time=7320.2",
                utterances=[
                    Utterance(speaker="古川あおい", role="質疑者", text="チームみらいの古川あおいです。"),
                ],
            )
        ]
    )


@pytest.fixture
def mock_qa_pairs() -> QAPairsOutput:
    return QAPairsOutput(
        pairs=[
            QAPair(
                id="qa_001",
                segment_index=0,
                topic="高額療養費",
                question=QuestionDetail(
                    speaker="古川あおい",
                    party="チームみらい",
                    summary="高額療養費の問題",
                    full_text="全文",
                    intent="fact_check",
                ),
                answer=AnswerDetail(
                    speaker="上野賢一郎",
                    role="大臣",
                    summary="答弁要旨",
                    full_text="答弁全文",
                    evasion_score=0.3,
                    has_commitment=True,
                    commitment_text="検討します",
                ),
                video_url="https://example.com",
            )
        ]
    )


@pytest.fixture
def mock_summary() -> SummaryOutput:
    return SummaryOutput(
        session_summary="本会議の要約",
        key_topics=["高額療養費", "健康保険法改正"],
        key_commitments=[
            KeyCommitment(
                speaker="上野賢一郎",
                role="大臣",
                text="検討します",
                topic="高額療養費",
                qa_id="qa_001",
            )
        ],
    )


@pytest.fixture
def mock_topics() -> TopicsOutput:
    return TopicsOutput(
        topics=[
            Topic(
                name="医療保険制度改革",
                description="高額療養費制度の見直し",
                related_qa_ids=["qa_001"],
                related_speakers=["古川あおい"],
            )
        ]
    )


def _pipeline_patches(
    mock_session_detail: SessionDetail,
    mock_raw_transcript: RawTranscript,
    mock_utterances_output: UtterancesOutput,
    mock_qa_pairs: QAPairsOutput,
    mock_summary: SummaryOutput,
    mock_topics: TopicsOutput,
    tmp_path: Path,
):
    """run_pipeline()をフルモックするコンテキストマネージャのヘルパー。"""
    return (
        patch("src.pipeline.ShugiinScraper.get_session_detail", return_value=mock_session_detail),
        patch("src.pipeline.download_full_audio"),
        patch("src.pipeline.detect_leading_silence", return_value=0.0),
        patch("src.pipeline.split_segments", return_value=[tmp_path / "seg_000.wav"]),
        patch("src.pipeline.transcribe_all_segments", return_value=mock_raw_transcript),
        patch("src.pipeline.correct_transcript", return_value=mock_raw_transcript),
        patch("src.pipeline.tag_all_segments", return_value=mock_utterances_output),
        patch("src.pipeline._run_step6", return_value=(mock_qa_pairs, mock_summary, mock_topics)),
        patch("src.pipeline._load_laws_compact", return_value=""),
        patch("src.pipeline.publish_session"),
    )


class TestRunPipeline:
    def test_all_six_json_files_generated(
        self,
        tmp_path: Path,
        mock_session_detail: SessionDetail,
        mock_raw_transcript: RawTranscript,
        mock_utterances_output: UtterancesOutput,
        mock_qa_pairs: QAPairsOutput,
        mock_summary: SummaryOutput,
        mock_topics: TopicsOutput,
    ) -> None:
        """出力ディレクトリに6ファイルが生成されること。"""
        output_dir = tmp_path / "output"

        with (
            patch("src.pipeline.ShugiinScraper.get_session_detail", return_value=mock_session_detail),
            patch("src.pipeline.download_full_audio"),
            patch("src.pipeline.detect_leading_silence", return_value=0.0),
            patch("src.pipeline.split_segments", return_value=[tmp_path / "seg_000.wav"]),
            patch("src.pipeline.transcribe_all_segments", return_value=mock_raw_transcript),
            patch("src.pipeline.correct_transcript", return_value=mock_raw_transcript),
            patch("src.pipeline.tag_all_segments", return_value=mock_utterances_output),
            patch("src.pipeline._run_step6", return_value=(mock_qa_pairs, mock_summary, mock_topics)),
            patch("src.pipeline._load_laws_compact", return_value=""),
            patch("src.pipeline.publish_session"),
        ):
            run_pipeline("shugiin", "56149", output_dir, no_push=True)

        json_files = sorted(output_dir.glob("*.json"))
        file_names = {f.name for f in json_files}
        assert file_names == {
            "metadata.json",
            "raw_transcript.json",
            "utterances.json",
            "qa_pairs.json",
            "summary.json",
            "topics.json",
        }

    def test_each_json_validates_with_pydantic(
        self,
        tmp_path: Path,
        mock_session_detail: SessionDetail,
        mock_raw_transcript: RawTranscript,
        mock_utterances_output: UtterancesOutput,
        mock_qa_pairs: QAPairsOutput,
        mock_summary: SummaryOutput,
        mock_topics: TopicsOutput,
    ) -> None:
        """各JSONファイルがPydanticモデルでバリデーション可能であること。"""
        output_dir = tmp_path / "output"

        with (
            patch("src.pipeline.ShugiinScraper.get_session_detail", return_value=mock_session_detail),
            patch("src.pipeline.download_full_audio"),
            patch("src.pipeline.detect_leading_silence", return_value=0.0),
            patch("src.pipeline.split_segments", return_value=[tmp_path / "seg_000.wav"]),
            patch("src.pipeline.transcribe_all_segments", return_value=mock_raw_transcript),
            patch("src.pipeline.correct_transcript", return_value=mock_raw_transcript),
            patch("src.pipeline.tag_all_segments", return_value=mock_utterances_output),
            patch("src.pipeline._run_step6", return_value=(mock_qa_pairs, mock_summary, mock_topics)),
            patch("src.pipeline._load_laws_compact", return_value=""),
            patch("src.pipeline.publish_session"),
        ):
            run_pipeline("shugiin", "56149", output_dir, no_push=True)

        # 各JSONをPydanticモデルでバリデーション
        SessionDetail.model_validate_json(
            (output_dir / "metadata.json").read_text(encoding="utf-8")
        )
        RawTranscript.model_validate_json(
            (output_dir / "raw_transcript.json").read_text(encoding="utf-8")
        )
        UtterancesOutput.model_validate_json(
            (output_dir / "utterances.json").read_text(encoding="utf-8")
        )
        QAPairsOutput.model_validate_json(
            (output_dir / "qa_pairs.json").read_text(encoding="utf-8")
        )
        SummaryOutput.model_validate_json(
            (output_dir / "summary.json").read_text(encoding="utf-8")
        )
        TopicsOutput.model_validate_json(
            (output_dir / "topics.json").read_text(encoding="utf-8")
        )

    def test_scraping_failure_raises_runtime_error(self, tmp_path: Path) -> None:
        """Step 2 でのエラーが RuntimeError として送出されること。"""
        output_dir = tmp_path / "output"

        with patch(
            "src.pipeline.ShugiinScraper.get_session_detail",
            side_effect=Exception("Network error"),
        ):
            with pytest.raises(RuntimeError, match="Step 2"):
                run_pipeline("shugiin", "56149", output_dir, no_push=True)

    def test_transcription_failure_raises_runtime_error(
        self,
        tmp_path: Path,
        mock_session_detail: SessionDetail,
    ) -> None:
        """Step 4 でのエラーが RuntimeError として送出されること。"""
        output_dir = tmp_path / "output"

        with (
            patch("src.pipeline.ShugiinScraper.get_session_detail", return_value=mock_session_detail),
            patch("src.pipeline.download_full_audio"),
            patch("src.pipeline.detect_leading_silence", return_value=0.0),
            patch("src.pipeline.split_segments", return_value=[tmp_path / "seg_000.wav"]),
            patch("src.pipeline.transcribe_all_segments", side_effect=Exception("API error")),
        ):
            with pytest.raises(RuntimeError, match="Step 4"):
                run_pipeline("shugiin", "56149", output_dir, no_push=True)

    def test_output_directory_created(
        self,
        tmp_path: Path,
        mock_session_detail: SessionDetail,
        mock_raw_transcript: RawTranscript,
        mock_utterances_output: UtterancesOutput,
        mock_qa_pairs: QAPairsOutput,
        mock_summary: SummaryOutput,
        mock_topics: TopicsOutput,
    ) -> None:
        """出力ディレクトリが自動作成されること。"""
        output_dir = tmp_path / "nested" / "deep" / "output"
        assert not output_dir.exists()

        with (
            patch("src.pipeline.ShugiinScraper.get_session_detail", return_value=mock_session_detail),
            patch("src.pipeline.download_full_audio"),
            patch("src.pipeline.detect_leading_silence", return_value=0.0),
            patch("src.pipeline.split_segments", return_value=[tmp_path / "seg_000.wav"]),
            patch("src.pipeline.transcribe_all_segments", return_value=mock_raw_transcript),
            patch("src.pipeline.correct_transcript", return_value=mock_raw_transcript),
            patch("src.pipeline.tag_all_segments", return_value=mock_utterances_output),
            patch("src.pipeline._run_step6", return_value=(mock_qa_pairs, mock_summary, mock_topics)),
            patch("src.pipeline._load_laws_compact", return_value=""),
            patch("src.pipeline.publish_session"),
        ):
            run_pipeline("shugiin", "56149", output_dir, no_push=True)

        assert output_dir.exists()

    def test_no_push_skips_publish(
        self,
        tmp_path: Path,
        mock_session_detail: SessionDetail,
        mock_raw_transcript: RawTranscript,
        mock_utterances_output: UtterancesOutput,
        mock_qa_pairs: QAPairsOutput,
        mock_summary: SummaryOutput,
        mock_topics: TopicsOutput,
    ) -> None:
        """--no-push の場合に publish_session が呼ばれないこと。"""
        output_dir = tmp_path / "output"

        with (
            patch("src.pipeline.ShugiinScraper.get_session_detail", return_value=mock_session_detail),
            patch("src.pipeline.download_full_audio"),
            patch("src.pipeline.detect_leading_silence", return_value=0.0),
            patch("src.pipeline.split_segments", return_value=[tmp_path / "seg_000.wav"]),
            patch("src.pipeline.transcribe_all_segments", return_value=mock_raw_transcript),
            patch("src.pipeline.correct_transcript", return_value=mock_raw_transcript),
            patch("src.pipeline.tag_all_segments", return_value=mock_utterances_output),
            patch("src.pipeline._run_step6", return_value=(mock_qa_pairs, mock_summary, mock_topics)),
            patch("src.pipeline._load_laws_compact", return_value=""),
            patch("src.pipeline.publish_session") as mock_publish,
        ):
            run_pipeline("shugiin", "56149", output_dir, no_push=True)
            mock_publish.assert_not_called()


class TestGetScraper:
    def test_shugiin_scraper(self) -> None:
        scraper = _get_scraper("shugiin")
        assert isinstance(scraper, ShugiinScraper)

    def test_sangiin_scraper(self) -> None:
        scraper = _get_scraper("sangiin")
        assert isinstance(scraper, SangiinScraper)

    def test_unknown_chamber_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown chamber"):
            _get_scraper("unknown")


class TestSangiinPipeline:
    """参議院パイプラインのテスト。"""

    @pytest.fixture
    def sangiin_session_detail(self) -> SessionDetail:
        return SessionDetail(
            chamber="sangiin",
            session_id="7890",
            date="2026-04-10",
            committee="法務委員会",
            hls_url="",
            mediasp_hash="abc123def456",
            source_url="https://webtv.sangiin.go.jp/webtv/detail.php?sid=7890",
            speakers=[
                SpeakerInfo(
                    name="伊藤孝江",
                    affiliation="法務委員長",
                    role="委員長",
                    start_seconds=0.0,
                    start_time="10:00",
                    duration_minutes=3,
                ),
                SpeakerInfo(
                    name="田中太郎",
                    affiliation="自由民主党",
                    role="質疑者",
                    start_seconds=180.5,
                    start_time="10:03",
                    duration_minutes=25,
                ),
            ],
        )

    def test_sangiin_pipeline_generates_six_json_files(
        self,
        tmp_path: Path,
        sangiin_session_detail: SessionDetail,
        mock_raw_transcript: RawTranscript,
        mock_utterances_output: UtterancesOutput,
        mock_qa_pairs: QAPairsOutput,
        mock_summary: SummaryOutput,
        mock_topics: TopicsOutput,
    ) -> None:
        """参議院パイプラインが6ファイルを出力すること。"""
        output_dir = tmp_path / "output"

        with (
            patch("src.pipeline.SangiinScraper.get_session_detail", return_value=sangiin_session_detail),
            patch("src.audio.sangiin_resolver.resolve_stream_url", return_value="https://vod.mediasp.jp/test/playlist.m3u8"),
            patch("src.pipeline.download_full_audio"),
            patch("src.pipeline.detect_leading_silence", return_value=0.0),
            patch("src.pipeline.split_segments", return_value=[tmp_path / "seg_000.wav"]),
            patch("src.pipeline.transcribe_all_segments", return_value=mock_raw_transcript),
            patch("src.pipeline.correct_transcript", return_value=mock_raw_transcript),
            patch("src.pipeline.tag_all_segments", return_value=mock_utterances_output),
            patch("src.pipeline._run_step6", return_value=(mock_qa_pairs, mock_summary, mock_topics)),
            patch("src.pipeline._load_laws_compact", return_value=""),
            patch("src.pipeline.publish_session"),
        ):
            run_pipeline("sangiin", "7890", output_dir, no_push=True)

        json_files = sorted(output_dir.glob("*.json"))
        file_names = {f.name for f in json_files}
        assert file_names == {
            "metadata.json",
            "raw_transcript.json",
            "utterances.json",
            "qa_pairs.json",
            "summary.json",
            "topics.json",
        }

    def test_sangiin_metadata_has_correct_chamber(
        self,
        tmp_path: Path,
        sangiin_session_detail: SessionDetail,
        mock_raw_transcript: RawTranscript,
        mock_utterances_output: UtterancesOutput,
        mock_qa_pairs: QAPairsOutput,
        mock_summary: SummaryOutput,
        mock_topics: TopicsOutput,
    ) -> None:
        """参議院のmetadata.jsonにchamber='sangiin'が記録されること。"""
        output_dir = tmp_path / "output"

        with (
            patch("src.pipeline.SangiinScraper.get_session_detail", return_value=sangiin_session_detail),
            patch("src.audio.sangiin_resolver.resolve_stream_url", return_value="https://vod.mediasp.jp/test/playlist.m3u8"),
            patch("src.pipeline.download_full_audio"),
            patch("src.pipeline.detect_leading_silence", return_value=0.0),
            patch("src.pipeline.split_segments", return_value=[tmp_path / "seg_000.wav"]),
            patch("src.pipeline.transcribe_all_segments", return_value=mock_raw_transcript),
            patch("src.pipeline.correct_transcript", return_value=mock_raw_transcript),
            patch("src.pipeline.tag_all_segments", return_value=mock_utterances_output),
            patch("src.pipeline._run_step6", return_value=(mock_qa_pairs, mock_summary, mock_topics)),
            patch("src.pipeline._load_laws_compact", return_value=""),
            patch("src.pipeline.publish_session"),
        ):
            run_pipeline("sangiin", "7890", output_dir, no_push=True)

        import json

        metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["chamber"] == "sangiin"
        assert metadata["mediasp_hash"] == "abc123def456"
        assert metadata["hls_url"] == ""

    def test_sangiin_no_mediasp_hash_raises(self, tmp_path: Path) -> None:
        """mediasp_hashもhls_urlもない参議院セッションがエラーになること。"""
        detail = SessionDetail(
            chamber="sangiin",
            session_id="9999",
            date="2026-04-10",
            committee="不明",
            hls_url="",
            mediasp_hash="",
            source_url="https://webtv.sangiin.go.jp/webtv/detail.php?sid=9999",
            speakers=[
                SpeakerInfo(
                    name="テスト委員長",
                    affiliation="委員長",
                    role="委員長",
                    start_seconds=0.0,
                    start_time="10:00",
                    duration_minutes=5,
                )
            ],
        )
        output_dir = tmp_path / "output"

        with patch("src.pipeline.SangiinScraper.get_session_detail", return_value=detail):
            with pytest.raises(RuntimeError, match="Step 3"):
                run_pipeline("sangiin", "9999", output_dir, no_push=True)
