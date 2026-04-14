"""LLM 話者タグ付けの単体テスト (Step 5)"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.models import RawTranscript, SegmentTranscript, SpeakerInfo, Utterance, UtterancesOutput
from src.speaker_tagger import tag_speakers, tag_all_segments


@pytest.fixture
def segment_speaker() -> SpeakerInfo:
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
            role="委員長",
            start_seconds=0.0,
            start_time="13:00",
            duration_minutes=5,
        ),
        SpeakerInfo(
            name="古川あおい",
            affiliation="チームみらい",
            role="質疑者",
            start_seconds=7320.2,
            start_time="14:42",
            duration_minutes=18,
        ),
    ]


def _make_mock_llm_response(utterances_data: list[dict]) -> MagicMock:
    """LLM APIレスポンスのモックを作成する。"""
    content = json.dumps({"utterances": utterances_data}, ensure_ascii=False)
    mock_message = MagicMock()
    mock_message.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


class TestTagSpeakers:
    def test_chairperson_to_questioner_to_answerer_pattern(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """委員長 → 質疑者 → 委員長 → 答弁者 の遷移パターン。"""
        raw_text = "古川あおい君。チームみらいの古川あおいです。お答えいたします。問題を認識しております。"

        mock_utterances = [
            {"speaker": "藤原徹", "role": "委員長", "text": "古川あおい君。"},
            {"speaker": "古川あおい", "role": "質疑者", "text": "チームみらいの古川あおいです。"},
            {"speaker": "上野賢一郎", "role": "答弁者", "text": "お答えいたします。問題を認識しております。"},
        ]

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_utterances)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        assert len(result) == 3
        assert result[0].role == "委員長"
        assert result[1].role == "質疑者"
        assert result[2].role == "答弁者"

    def test_government_witness_pattern(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """政府参考人の答弁パターン。"""
        raw_text = "政府参考人として説明いたします。詳細については..."

        mock_utterances = [
            {"speaker": "田中参考人", "role": "政府参考人", "text": "政府参考人として説明いたします。詳細については..."},
        ]

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_utterances)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        assert len(result) == 1
        assert result[0].role == "政府参考人"

    def test_no_speaker_change(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """話者交代なし（質疑者の持ち時間全体が1人の発言）。"""
        raw_text = "チームみらいの古川あおいです。高額療養費制度について質問します。..."

        mock_utterances = [
            {"speaker": "古川あおい", "role": "質疑者", "text": "チームみらいの古川あおいです。高額療養費制度について質問します。..."},
        ]

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_utterances)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        assert len(result) == 1
        assert result[0].speaker == "古川あおい"
        assert result[0].role == "質疑者"

    def test_returns_utterance_objects(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """返り値が Utterance オブジェクトのリストであること。"""
        raw_text = "テスト発言"

        mock_utterances = [
            {"speaker": "古川あおい", "role": "質疑者", "text": "テスト発言"},
        ]

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_utterances)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        assert all(isinstance(u, Utterance) for u in result)

    def test_json_structure_validated(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """LLM レスポンスの JSON 構造が検証されること（必須フィールドの存在）。"""
        raw_text = "テスト"
        valid_utterances = [
            {"speaker": "話者A", "role": "質疑者", "text": "テキスト"},
        ]

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(valid_utterances)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        for u in result:
            assert hasattr(u, "speaker")
            assert hasattr(u, "role")
            assert hasattr(u, "text")

    def test_api_call_uses_json_mode(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """LLM API が JSON モードで呼ばれること。"""
        raw_text = "テスト"

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(
                [{"speaker": "A", "role": "質疑者", "text": "テスト"}]
            )
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                tag_speakers(raw_text, segment_speaker, all_speakers)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("response_format") == {"type": "json_object"}
        assert call_kwargs.get("temperature") == 0.1

    def test_missing_api_key_raises(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """DEEPINFRA_API_KEY が未設定の場合に EnvironmentError が送出されること。"""
        import os
        env = {k: v for k, v in os.environ.items() if k != "DEEPINFRA_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(EnvironmentError):
                tag_speakers("テスト", segment_speaker, all_speakers)


@pytest.mark.integration
class TestSpeakerTaggerIntegration:
    def test_real_api_call(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """実際の LLM API を呼び出すテスト（結合テスト、要 API キー）。"""
        raw_text = "チームみらいの古川あおいです。高額療養費制度について伺います。"
        result = tag_speakers(raw_text, segment_speaker, all_speakers)
        assert isinstance(result, list)
        assert len(result) > 0
        for u in result:
            assert isinstance(u, Utterance)
            assert u.role in ["委員長", "質疑者", "答弁者", "政府参考人", "参考人", "その他"]
