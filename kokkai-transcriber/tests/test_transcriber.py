"""Whisper 文字起こしの単体テスト (Step 4)"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models import RawTranscript, SegmentTranscript, SpeakerInfo
from src.transcriber import transcribe_segment, transcribe_all_segments

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def whisper_response_data() -> dict:
    return json.loads((FIXTURES_DIR / "whisper_response.json").read_text(encoding="utf-8"))


@pytest.fixture
def sample_speaker() -> SpeakerInfo:
    return SpeakerInfo(
        name="古川あおい",
        affiliation="チームみらい",
        role="質疑者",
        start_seconds=7320.2,
        start_time="14:42",
        duration_minutes=18,
    )


@pytest.fixture
def all_speakers() -> list[SpeakerInfo]:
    return [
        SpeakerInfo(
            name="藤原徹",
            affiliation="自由民主党",
            start_seconds=0.0,
            start_time="13:00",
            duration_minutes=5,
        ),
        SpeakerInfo(
            name="古川あおい",
            affiliation="チームみらい",
            start_seconds=7320.2,
            start_time="14:42",
            duration_minutes=18,
        ),
    ]


def _make_mock_transcription(data: dict) -> MagicMock:
    """Whisper API レスポンスのモックを作成する。"""
    mock = MagicMock()
    mock.text = data["text"]
    mock.segments = data["segments"]
    return mock


class TestTranscribeSegment:
    def test_returns_segment_transcript(
        self,
        tmp_path: Path,
        sample_speaker: SpeakerInfo,
        whisper_response_data: dict,
    ) -> None:
        """SegmentTranscript が返されること。"""
        wav_path = tmp_path / "test.wav"
        wav_path.touch()

        mock_result = _make_mock_transcription(whisper_response_data)

        with patch("src.transcriber._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.audio.transcriptions.create.return_value = mock_result
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = transcribe_segment(wav_path, 1, sample_speaker, "内閣委員会")

        assert isinstance(result, SegmentTranscript)
        assert result.segment_index == 1
        assert result.speaker_name == "古川あおい"
        assert result.start_seconds == 7320.2

    def test_text_from_whisper_response(
        self,
        tmp_path: Path,
        sample_speaker: SpeakerInfo,
        whisper_response_data: dict,
    ) -> None:
        """文字起こしテキストが Whisper レスポンスのテキストと一致すること。"""
        wav_path = tmp_path / "test.wav"
        wav_path.touch()

        mock_result = _make_mock_transcription(whisper_response_data)

        with patch("src.transcriber._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.audio.transcriptions.create.return_value = mock_result
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = transcribe_segment(wav_path, 1, sample_speaker, "内閣委員会")

        assert result.text == whisper_response_data["text"]

    def test_whisper_segments_parsed(
        self,
        tmp_path: Path,
        sample_speaker: SpeakerInfo,
        whisper_response_data: dict,
    ) -> None:
        """Whisper セグメントが正しくパースされること。"""
        wav_path = tmp_path / "test.wav"
        wav_path.touch()

        mock_result = _make_mock_transcription(whisper_response_data)

        with patch("src.transcriber._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.audio.transcriptions.create.return_value = mock_result
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = transcribe_segment(wav_path, 1, sample_speaker, "内閣委員会")

        assert len(result.whisper_segments) == len(whisper_response_data["segments"])
        assert result.whisper_segments[0].text == whisper_response_data["segments"][0]["text"]

    def test_api_call_parameters(
        self,
        tmp_path: Path,
        sample_speaker: SpeakerInfo,
        whisper_response_data: dict,
    ) -> None:
        """API 呼び出しパラメータが正しいこと（言語、モデル、response_format、prompt内容）。"""
        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(b"")

        mock_result = _make_mock_transcription(whisper_response_data)

        with patch("src.transcriber._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.audio.transcriptions.create.return_value = mock_result
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                transcribe_segment(wav_path, 1, sample_speaker, "内閣委員会")

        call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
        assert call_kwargs["model"] == "openai/whisper-large-v3-turbo"
        assert call_kwargs["language"] == "ja"
        assert call_kwargs["response_format"] == "verbose_json"
        assert "prompt" in call_kwargs
        # prompt に発言者名・委員会名が含まれること（V2サフィックス形式）
        assert "古川あおい" in call_kwargs["prompt"]
        assert "内閣委員会" in call_kwargs["prompt"]
        # ループを誘発した出席議員リストが含まれないこと
        assert "出席議員" not in call_kwargs["prompt"]
        # 削除された石井啓一副議長が含まれないこと
        assert "石井啓一" not in call_kwargs["prompt"]

    def test_missing_api_key_raises(
        self,
        tmp_path: Path,
        sample_speaker: SpeakerInfo,
    ) -> None:
        """DEEPINFRA_API_KEY が未設定の場合に EnvironmentError が送出されること。"""
        wav_path = tmp_path / "test.wav"
        wav_path.touch()

        import os
        env = {k: v for k, v in os.environ.items() if k != "DEEPINFRA_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(OSError):
                transcribe_segment(wav_path, 1, sample_speaker, "内閣委員会")


class TestTranscribeAllSegments:
    def test_returns_raw_transcript(
        self,
        tmp_path: Path,
        all_speakers: list[SpeakerInfo],
        whisper_response_data: dict,
    ) -> None:
        """RawTranscript が返されること。"""
        wav_paths = [tmp_path / f"seg_{i:03d}.wav" for i in range(len(all_speakers))]
        for p in wav_paths:
            p.touch()

        mock_result = _make_mock_transcription(whisper_response_data)

        with patch("src.transcriber._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.audio.transcriptions.create.return_value = mock_result
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = transcribe_all_segments(wav_paths, all_speakers, "56149", committee="内閣委員会")

        assert isinstance(result, RawTranscript)
        assert result.session_id == "56149"
        assert len(result.segments) == len(all_speakers)


@pytest.mark.integration
class TestTranscriberIntegration:
    def test_real_api_call(self, tmp_path: Path) -> None:
        """実際の Whisper API を呼び出すテスト（結合テスト、要 API キー）。"""
        import wave
        wav_path = tmp_path / "test.wav"
        with wave.open(str(wav_path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 16000)  # 1秒の無音

        speaker = SpeakerInfo(
            name="テスト話者",
            affiliation="テスト党",
            start_seconds=0.0,
            start_time="00:00",
            duration_minutes=1,
        )

        result = transcribe_segment(wav_path, 0, speaker, [speaker])
        assert isinstance(result, SegmentTranscript)
