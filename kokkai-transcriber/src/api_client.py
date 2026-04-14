"""共通 DeepInfra API クライアントファクトリ"""

from __future__ import annotations

import os

import openai

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
LLM_MODEL = "deepseek-ai/DeepSeek-V3.2"


def get_client() -> openai.OpenAI:
    """DeepInfra APIクライアントを返す。"""
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPINFRA_API_KEY environment variable is not set")
    return openai.OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)
