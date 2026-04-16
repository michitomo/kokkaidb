"""HLS音声抽出とWAVセグメント分割

ffmpeg を subprocess で呼び出す。
"""

from __future__ import annotations

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.api_client import MAX_WORKERS_AUDIO
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
    max_workers: int = MAX_WORKERS_AUDIO,
) -> list[Path]:
    """発言者タイムスタンプに基づいて WAV を並列分割する。

    Args:
        full_audio: 分割元の WAV ファイルパス
        speakers: 発言者リスト（start_seconds 昇順であること）
        output_dir: 出力先ディレクトリ
        max_workers: ffmpeg 並列数（デフォルト: MAX_WORKERS_AUDIO）

    Returns:
        生成されたセグメントファイルのパスリスト（speakers と同順）

    Raises:
        subprocess.CalledProcessError: ffmpeg が失敗した場合
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    total_duration = _get_audio_duration(full_audio)

    def _split_one(i: int, speaker: SpeakerInfo) -> tuple[int, Path]:
        start = speaker.start_seconds
        end = speakers[i + 1].start_seconds if i + 1 < len(speakers) else total_duration

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
            i + 1, len(speakers), speaker.name, start, end,
        )
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return i, output_path

    results: list[tuple[int, Path]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_split_one, i, speaker): i
            for i, speaker in enumerate(speakers)
        }
        for future in as_completed(futures):
            results.append(future.result())

    # speakers と同順にソート
    results.sort(key=lambda x: x[0])
    segment_paths = [path for _, path in results]

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
