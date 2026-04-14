"""HLS音声抽出とWAVセグメント分割

ffmpeg を subprocess で呼び出す。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.models import SpeakerInfo

logger = logging.getLogger(__name__)


def download_full_audio(hls_url: str, output_path: Path) -> Path:
    """HLSストリームをWAVファイルとしてダウンロードする。

    Args:
        hls_url: HLS プレイリスト URL
        output_path: 出力先 WAV ファイルパス

    Returns:
        出力ファイルパス

    Raises:
        subprocess.CalledProcessError: ffmpeg が失敗した場合
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",  # 上書き許可
        "-i", hls_url,
        "-vn",                  # 映像なし
        "-acodec", "pcm_s16le", # 16bit PCM
        "-ar", "16000",         # 16kHz (Whisper 最適)
        "-ac", "1",             # モノラル
        str(output_path),
    ]

    logger.info("Downloading audio: %s -> %s", hls_url, output_path)
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    logger.info("Audio downloaded: %s", output_path)
    return output_path


def split_segments(
    full_audio: Path,
    speakers: list[SpeakerInfo],
    output_dir: Path,
) -> list[Path]:
    """発言者タイムスタンプに基づいて WAV を分割する。

    Args:
        full_audio: 分割元の WAV ファイルパス
        speakers: 発言者リスト（start_seconds 昇順であること）
        output_dir: 出力先ディレクトリ

    Returns:
        生成されたセグメントファイルのパスリスト（speakers と同順）

    Raises:
        subprocess.CalledProcessError: ffmpeg が失敗した場合
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    total_duration = _get_audio_duration(full_audio)
    segment_paths: list[Path] = []

    for i, speaker in enumerate(speakers):
        start = speaker.start_seconds

        # 次の発言者の開始秒か、最後なら全体の終了時刻
        if i + 1 < len(speakers):
            end = speakers[i + 1].start_seconds
        else:
            end = total_duration

        # ファイル名に使えない文字を置換
        safe_name = speaker.name.replace("/", "_").replace(" ", "_")
        output_path = output_dir / f"{i:03d}_{safe_name}.wav"

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(full_audio),
            "-ss", str(start),
            "-to", str(end),
            "-c", "copy",
            str(output_path),
        ]

        logger.info(
            "Splitting segment %d/%d: %s (%.1fs - %.1fs)",
            i + 1,
            len(speakers),
            speaker.name,
            start,
            end,
        )
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        segment_paths.append(output_path)

    logger.info("Split %d segments into %s", len(segment_paths), output_dir)
    return segment_paths


def _get_audio_duration(wav_path: Path) -> float:
    """ffprobe で WAV ファイルの長さ（秒）を取得する。"""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(wav_path),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return float(result.stdout.strip())
