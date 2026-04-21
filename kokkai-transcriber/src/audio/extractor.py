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
            "-af", (
                "silenceremove="
                "start_periods=0:"         # 先頭無音は残す（発言開始を保持）
                "stop_periods=-1:"         # 途中・末尾の無音を全て対象
                "stop_duration=2.0:"       # 2秒以上続く無音を除去
                "stop_threshold=-45dB"     # -45dB以下を無音と判定
            ),
            "-ar", "16000",
            "-ac", "1",
            "-acodec", "pcm_s16le",
            str(output_path),
        ]

        logger.info(
            "Splitting segment %d/%d: %s (%.1fs - %.1fs)",
            i + 1, len(speakers), speaker.name, start, end,
        )
        subprocess.run(cmd, check=True, capture_output=True, text=True)

        original_size = (end - start) * 16000 * 2  # 概算bytes (16kHz, 16bit)
        actual_size = output_path.stat().st_size
        reduction_pct = (1 - actual_size / original_size) * 100 if original_size > 0 else 0
        logger.info(
            "Segment %d silence-removed: %.1fMB (%.0f%% reduction)",
            i, actual_size / 1024 / 1024, reduction_pct,
        )

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


def detect_leading_silence(wav_path: Path, threshold_db: float = -60.0) -> float:
    """WAVファイルの先頭無音の長さ（秒）を検出する。

    ffmpegのsilencedetectフィルタを使い、先頭から最初に音声が始まるまでの
    無音区間の長さを返す。無音がなければ0.0を返す。

    Args:
        wav_path: 対象WAVファイル
        threshold_db: 無音と判定する閾値（dB）。デフォルト-60dB。

    Returns:
        先頭無音の長さ（秒）
    """
    cmd = [
        "ffmpeg",
        "-i", str(wav_path),
        "-af", f"silencedetect=noise={threshold_db}dB:d=1.0",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # silencedetect は stderr に出力する
    # "silence_end: 470.123 | silence_duration: 470.123" の形式
    import re
    for line in result.stderr.split("\n"):
        m = re.search(r"silence_end:\s*([\d.]+)", line)
        if m:
            silence_end = float(m.group(1))
            logger.info("Detected leading silence: %.1fs", silence_end)
            return silence_end

    logger.info("No leading silence detected")
    return 0.0
