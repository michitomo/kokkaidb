"""HLS音声抽出・WAVセグメント分割の単体テスト (Step 3)"""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from src.audio.extractor import (
    _get_audio_duration,
    download_full_audio,
    split_segments,
)
from src.models import SpeakerInfo


def _make_dummy_wav(path: Path, duration_seconds: float = 5.0) -> Path:
    """テスト用のダミー WAV ファイルを生成する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 16000
    num_frames = int(sample_rate * duration_seconds)
    with wave.open(str(path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * num_frames)
    return path


@pytest.fixture
def dummy_wav(tmp_path: Path) -> Path:
    return _make_dummy_wav(tmp_path / "test_audio.wav", duration_seconds=10.0)


@pytest.fixture
def sample_speakers() -> list[SpeakerInfo]:
    return [
        SpeakerInfo(
            name="藤原徹",
            affiliation="自由民主党",
            start_seconds=0.0,
            start_time="13:00",
            duration_minutes=2,
        ),
        SpeakerInfo(
            name="古川あおい",
            affiliation="チームみらい",
            start_seconds=3.0,
            start_time="13:02",
            duration_minutes=3,
        ),
        SpeakerInfo(
            name="山田花子",
            affiliation="立憲民主党",
            start_seconds=7.0,
            start_time="13:05",
            duration_minutes=3,
        ),
    ]


class TestDownloadFullAudio:
    def test_ffmpeg_command_args(self, tmp_path: Path) -> None:
        """ffmpegコマンドが正しい引数で構築されること。"""
        output_path = tmp_path / "audio.wav"
        hls_url = "http://hlsvod.shugiintv.go.jp/vod/test.m3u8"

        with patch("src.audio.extractor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            download_full_audio(hls_url, output_path)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]

        assert cmd[0] == "ffmpeg"
        assert "-i" in cmd
        assert hls_url in cmd
        assert "-acodec" in cmd
        assert "pcm_s16le" in cmd
        assert "-ar" in cmd
        assert "16000" in cmd
        assert "-ac" in cmd
        assert "1" in cmd
        assert str(output_path) in cmd

    def test_returns_output_path(self, tmp_path: Path) -> None:
        """戻り値が output_path と一致すること。"""
        output_path = tmp_path / "audio.wav"
        hls_url = "http://example.com/test.m3u8"

        with patch("src.audio.extractor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = download_full_audio(hls_url, output_path)

        assert result == output_path

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """出力先の親ディレクトリが作成されること。"""
        output_path = tmp_path / "nested" / "deep" / "audio.wav"
        hls_url = "http://example.com/test.m3u8"

        with patch("src.audio.extractor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            download_full_audio(hls_url, output_path)

        assert output_path.parent.exists()

    def test_ffmpeg_error_raises(self, tmp_path: Path) -> None:
        """ffmpeg が失敗した場合に CalledProcessError が送出されること。"""
        output_path = tmp_path / "audio.wav"
        hls_url = "http://example.com/bad.m3u8"

        with patch("src.audio.extractor.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")
            with pytest.raises(subprocess.CalledProcessError):
                download_full_audio(hls_url, output_path)


class TestSplitSegments:
    def test_correct_number_of_segments(
        self, dummy_wav: Path, sample_speakers: list[SpeakerInfo], tmp_path: Path
    ) -> None:
        """発言者数と同じ数のセグメントが生成されること。"""
        output_dir = tmp_path / "segments"

        with patch("src.audio.extractor.subprocess.run") as mock_run, \
             patch("src.audio.extractor._get_audio_duration", return_value=10.0):
            mock_run.return_value = MagicMock(returncode=0)
            # ダミーファイルを作成してからsplit
            for i, s in enumerate(sample_speakers):
                safe_name = s.name.replace("/", "_").replace(" ", "_")
                (tmp_path / "segments").mkdir(parents=True, exist_ok=True)
                (tmp_path / "segments" / f"{i:03d}_{safe_name}.wav").touch()

            result = split_segments(dummy_wav, sample_speakers, output_dir)

        assert len(result) == len(sample_speakers)

    def test_ffmpeg_ss_to_args(
        self, dummy_wav: Path, sample_speakers: list[SpeakerInfo], tmp_path: Path
    ) -> None:
        """ffmpeg に正しい -ss / -to 引数が渡されること。"""
        output_dir = tmp_path / "segments"

        with patch("src.audio.extractor.subprocess.run") as mock_run, \
             patch("src.audio.extractor._get_audio_duration", return_value=10.0):
            mock_run.return_value = MagicMock(returncode=0)
            split_segments(dummy_wav, sample_speakers, output_dir)

        # 3つのセグメントに対して3回 ffmpeg が呼ばれること
        assert mock_run.call_count == len(sample_speakers)

        # 並列実行のため順序は不定 → 全呼び出しからコマンドを収集して検証
        all_cmds = [call[0][0] for call in mock_run.call_args_list]

        # -ss 0.0 / -to 3.0 のコマンドが存在すること（最初のセグメント）
        first_seg = [c for c in all_cmds if "0.0" in c and "3.0" in c]
        assert len(first_seg) == 1
        assert "-ss" in first_seg[0]
        assert "-to" in first_seg[0]
        assert "-c" in first_seg[0]
        assert "copy" in first_seg[0]

        # -to 10.0 のコマンドが存在すること（最後のセグメント）
        last_seg = [c for c in all_cmds if "10.0" in c]
        assert len(last_seg) == 1
        assert "-to" in last_seg[0]

    def test_segment_filename_format(
        self, dummy_wav: Path, sample_speakers: list[SpeakerInfo], tmp_path: Path
    ) -> None:
        """セグメントファイル名が {index:03d}_{speaker_name}.wav 形式であること。"""
        output_dir = tmp_path / "segments"

        with patch("src.audio.extractor.subprocess.run") as mock_run, \
             patch("src.audio.extractor._get_audio_duration", return_value=10.0):
            mock_run.return_value = MagicMock(returncode=0)
            result = split_segments(dummy_wav, sample_speakers, output_dir)

        assert result[0].name == "000_藤原徹.wav"
        assert result[1].name == "001_古川あおい.wav"
        assert result[2].name == "002_山田花子.wav"

    def test_last_segment_uses_total_duration(
        self, dummy_wav: Path, tmp_path: Path
    ) -> None:
        """最後のセグメントの終了時刻が全体の長さであること。"""
        speakers = [
            SpeakerInfo(
                name="話者A",
                affiliation="党A",
                start_seconds=0.0,
                start_time="10:00",
                duration_minutes=5,
            ),
            SpeakerInfo(
                name="話者B",
                affiliation="党B",
                start_seconds=5.0,
                start_time="10:05",
                duration_minutes=5,
            ),
        ]
        output_dir = tmp_path / "segments"
        total_duration = 15.0

        with patch("src.audio.extractor.subprocess.run") as mock_run, \
             patch("src.audio.extractor._get_audio_duration", return_value=total_duration):
            mock_run.return_value = MagicMock(returncode=0)
            split_segments(dummy_wav, speakers, output_dir)

        last_cmd = mock_run.call_args_list[-1][0][0]
        to_idx = last_cmd.index("-to")
        assert float(last_cmd[to_idx + 1]) == total_duration


@pytest.mark.integration
class TestAudioExtractorIntegration:
    def test_real_hls_download(self, tmp_path: Path) -> None:
        """実際のHLSストリームからダウンロードをテストする（結合テスト、要ffmpeg）。"""
        hls_url = "http://hlsvod.shugiintv.go.jp/vod/_definst_/amlst:2026/2026-0409-1300-00/playlist.m3u8"
        output_path = tmp_path / "audio.wav"
        result = download_full_audio(hls_url, output_path)
        assert result.exists()
        assert result.stat().st_size > 0
