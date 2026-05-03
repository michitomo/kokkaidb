"""共通 DeepInfra API クライアントファクトリ & 並列数設定"""

from __future__ import annotations

import logging
import os
import random
import resource
import time
from collections.abc import Callable
from typing import TypeVar

import openai

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
LLM_MODEL = "google/gemma-4-31B-it"

# ---------------------------------------------------------------------------
# ステップごとのデフォルト並列数
# DeepInfra 200 concurrent limit を前提に配分
# ---------------------------------------------------------------------------
MAX_WORKERS_AUDIO = 4        # Step 3: ffmpeg subprocess（fd重い）
MAX_WORKERS_HLS = 8          # Step 3前段: HLSセグメント並列取得（HTTP keep-alive）
MAX_WORKERS_WHISPER = 16     # Step 4: Whisper API
MAX_WORKERS_LLM = 80         # Step 4.5/5/6: LLM API（fd軽い、1req=1socket）


def ensure_fd_limit(minimum: int = 2048) -> None:
    """ファイルディスクリプタ上限を引き上げる（macOS対策）。

    macOSのデフォルトは256と低く、ffmpeg並列＋API並列で枯渇しやすい。
    パイプライン起動時に1度呼ぶ。
    """
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft < minimum:
            new_soft = min(minimum, hard)
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
            logging.getLogger(__name__).info(
                "Raised fd limit: %d → %d (hard=%d)", soft, new_soft, hard,
            )
    except (ValueError, OSError) as e:
        logging.getLogger(__name__).warning("Could not raise fd limit: %s", e)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# 429 / 5xx に対するリトライ設定
_MAX_RETRIES = 6
_BASE_DELAY = 2.0   # 秒（指数バックオフのベース）
_MAX_DELAY = 120.0  # 秒（上限）
_JITTER = 0.25      # ±25% のランダムジッター


def with_retry(fn: Callable[[], _T]) -> _T:
    """429 (rate limit) と 5xx (server error) に対してリトライする。

    指数バックオフ + ジッター戦略:
        delay = min(BASE * 2^attempt, MAX) * uniform(1-JITTER, 1+JITTER)

    429 の Retry-After ヘッダがあればその値を優先する。

    Args:
        fn: 呼び出す関数（引数なし）

    Returns:
        fn() の戻り値

    Raises:
        openai.RateLimitError: リトライ上限を超えた場合
        openai.APIStatusError: 5xx でリトライ上限を超えた場合
        その他の例外: リトライせずそのまま再 raise
    """
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except openai.RateLimitError as e:
            if attempt == _MAX_RETRIES:
                logger.error("Rate limit exceeded after %d retries", _MAX_RETRIES)
                raise
            retry_after = _parse_retry_after(e)
            delay = retry_after if retry_after else _backoff(attempt)
            logger.warning(
                "429 rate limit (attempt %d/%d), retrying in %.1fs",
                attempt + 1, _MAX_RETRIES, delay,
            )
            time.sleep(delay)
        except openai.APIStatusError as e:
            if e.status_code < 500 or attempt == _MAX_RETRIES:
                raise
            delay = _backoff(attempt)
            logger.warning(
                "HTTP %d server error (attempt %d/%d), retrying in %.1fs",
                e.status_code, attempt + 1, _MAX_RETRIES, delay,
            )
            time.sleep(delay)

    # unreachable — kept for type checker
    raise RuntimeError("with_retry: unexpected exit")  # pragma: no cover


def _backoff(attempt: int) -> float:
    """指数バックオフ + ジッターで待機秒数を返す。"""
    base = min(_BASE_DELAY * (2 ** attempt), _MAX_DELAY)
    return base * random.uniform(1 - _JITTER, 1 + _JITTER)


def _parse_retry_after(exc: openai.RateLimitError) -> float | None:
    """Retry-After ヘッダ（秒数）をパースして返す。なければ None。"""
    try:
        response = getattr(exc, "response", None)
        if response is not None:
            value = response.headers.get("retry-after") or response.headers.get("Retry-After")
            if value:
                return float(value)
    except Exception:
        pass
    return None


def get_client() -> openai.OpenAI:
    """DeepInfra APIクライアントを返す。"""
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        raise OSError("DEEPINFRA_API_KEY environment variable is not set")
    return openai.OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)
