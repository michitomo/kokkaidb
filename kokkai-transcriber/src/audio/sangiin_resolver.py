"""mediasp.jp hash → ストリームURL解決

参議院TVの動画は mediasp.jp 外部SaaSでホストされている。
player ページの JavaScript/HTML から実際の HLS ストリーム URL を抽出する。

方法A（API解析）を優先し、失敗時は方法B（Playwright）にフォールバック可能な設計。
"""

from __future__ import annotations

import logging
import re

import requests

logger = logging.getLogger(__name__)

MEDIASP_PLAYER_URL = "https://public.mediasp.jp/v1/player"


def resolve_stream_url(mediasp_hash: str) -> str:
    """mediasp.jp の hash から HLS ストリーム URL を解決する。

    Args:
        mediasp_hash: mediasp.jp の player hash パラメータ

    Returns:
        HLS ストリーム URL 文字列

    Raises:
        ValueError: ストリームURLが解決できなかった場合
    """
    if not mediasp_hash:
        raise ValueError("mediasp_hash is empty")

    url = _resolve_via_api(mediasp_hash)
    if url:
        return url

    raise ValueError(
        f"Could not resolve stream URL for hash={mediasp_hash}. "
        "API resolution failed. Consider using Playwright fallback."
    )


def _resolve_via_api(mediasp_hash: str) -> str:
    """方法A: player ページから HLS URL を正規表現で抽出する。"""
    player_url = f"{MEDIASP_PLAYER_URL}?hash={mediasp_hash}"
    logger.info("Resolving mediasp.jp stream URL: %s", player_url)

    try:
        response = requests.get(
            player_url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; kokkai-transcriber/0.1)",
                "Referer": "https://webtv.sangiin.go.jp/",
            },
        )
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to fetch mediasp.jp player page: %s", e)
        return ""

    text = response.text

    # パターン1: 直接の m3u8 URL
    m3u8_match = re.search(r'"(https?://[^"]+\.m3u8[^"]*)"', text)
    if m3u8_match:
        url = m3u8_match.group(1)
        logger.info("Resolved m3u8 URL: %s", url)
        return url

    # パターン2: mp4 URL（m3u8 が見つからない場合のフォールバック）
    mp4_match = re.search(r'"(https?://[^"]+\.mp4[^"]*)"', text)
    if mp4_match:
        url = mp4_match.group(1)
        logger.info("Resolved mp4 URL: %s", url)
        return url

    # パターン3: vod.mediasp.jp のパス構築
    # 一部のレスポンスでは相対パスやhash直接組み立てが必要
    vod_match = re.search(r'"(https?://vod[^"]+)"', text)
    if vod_match:
        url = vod_match.group(1)
        logger.info("Resolved vod URL: %s", url)
        return url

    logger.warning("No stream URL found in mediasp.jp response for hash=%s", mediasp_hash)
    return ""
