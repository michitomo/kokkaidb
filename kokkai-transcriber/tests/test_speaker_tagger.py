"""LLM 話者タグ付けの単体テスト (Step 5)

文番号インデックス方式: LLMは話者交代ポイント(splits)のみ返し、
テキスト本体はコード側で結合する。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.models import RawTranscript, SegmentTranscript, SpeakerInfo, Utterance, UtterancesOutput
from src.speaker_tagger import _build_video_url, _split_sentences, tag_speakers, tag_all_segments


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


def _make_mock_llm_response(splits_data: list[dict]) -> MagicMock:
    """LLM APIレスポンスのモック（splits形式）。"""
    content = json.dumps({"splits": splits_data}, ensure_ascii=False)
    mock_message = MagicMock()
    mock_message.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


class TestSplitSentences:
    def test_basic_split(self) -> None:
        text = "これより会議を開きます。古川あおい君。チームみらいの古川あおいです。"
        result = _split_sentences(text)
        assert result == ["これより会議を開きます。", "古川あおい君。", "チームみらいの古川あおいです。"]

    def test_question_mark(self) -> None:
        text = "どうお考えですか？お答えいたします。"
        result = _split_sentences(text)
        assert result == ["どうお考えですか？", "お答えいたします。"]

    def test_newline_split(self) -> None:
        text = "第一の質問です。\n第二の質問です。"
        result = _split_sentences(text)
        assert len(result) == 2

    def test_empty_text(self) -> None:
        assert _split_sentences("") == []
        assert _split_sentences("   ") == []


class TestTagSpeakers:
    def test_chairperson_to_questioner_to_answerer_pattern(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """委員長 → 質疑者 → 答弁者 の遷移パターン。"""
        raw_text = "古川あおい君。チームみらいの古川あおいです。お答えいたします。問題を認識しております。"
        # 4文: (0)古川あおい君。(1)チームみらいの... (2)お答えいたします。(3)問題を...

        mock_splits = [
            {"start": 0, "speaker": "藤原徹", "role": "委員長"},
            {"start": 1, "speaker": "古川あおい", "role": "質疑者"},
            {"start": 2, "speaker": "上野賢一郎", "role": "答弁者"},
        ]

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_splits)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        assert len(result) == 3
        assert result[0].speaker == "藤原徹"
        assert result[0].role == "委員長"
        assert "古川あおい君。" in result[0].text
        assert result[1].speaker == "古川あおい"
        assert result[1].role == "質疑者"
        assert "チームみらい" in result[1].text
        assert result[2].speaker == "上野賢一郎"
        assert result[2].role == "答弁者"
        assert "お答えいたします。" in result[2].text

    def test_text_assembled_from_sentences(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """テキスト本体がコード側で正しく結合されること。"""
        raw_text = "最初の文。二番目の文。三番目の文。四番目の文。"

        mock_splits = [
            {"start": 0, "speaker": "A", "role": "委員長"},
            {"start": 2, "speaker": "B", "role": "質疑者"},
        ]

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_splits)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        assert len(result) == 2
        assert result[0].text == "最初の文。二番目の文。"
        assert result[1].text == "三番目の文。四番目の文。"

    def test_single_speaker_no_split(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """話者交代なし（1人の発言）。"""
        raw_text = "チームみらいの古川あおいです。高額療養費制度について質問します。"

        mock_splits = [
            {"start": 0, "speaker": "古川あおい", "role": "質疑者"},
        ]

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_splits)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        assert len(result) == 1
        assert result[0].speaker == "古川あおい"
        assert "チームみらい" in result[0].text

    def test_empty_splits_fallback(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """LLMが空のsplitsを返した場合のフォールバック。"""
        raw_text = "テスト発言です。"

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response([])
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        assert len(result) == 1
        assert result[0].speaker == segment_speaker.name

    def test_start_not_zero_auto_corrected(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """最初のsplitのstartが0でない場合に自動補正されること。"""
        raw_text = "最初の文。二番目の文。三番目の文。"

        mock_splits = [
            {"start": 1, "speaker": "B", "role": "質疑者"},
        ]

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_splits)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        # 文0がsegment_speakerに割り当てられる
        assert len(result) == 2
        assert result[0].speaker == segment_speaker.name
        assert result[0].text == "最初の文。"

    def test_returns_utterance_objects(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """返り値が Utterance オブジェクトのリストであること。"""
        raw_text = "テスト発言。"

        mock_splits = [
            {"start": 0, "speaker": "古川あおい", "role": "質疑者"},
        ]

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_splits)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        assert all(isinstance(u, Utterance) for u in result)

    def test_api_call_uses_json_mode(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """LLM API が JSON モードで呼ばれること。"""
        raw_text = "テスト。"

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(
                [{"start": 0, "speaker": "A", "role": "質疑者"}]
            )
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                tag_speakers(raw_text, segment_speaker, all_speakers)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("response_format") == {"type": "json_object"}
        assert call_kwargs.get("temperature") == 0.1

    def test_missing_api_key_raises(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        """OPENROUTER_API_KEY が未設定の場合に EnvironmentError が送出されること。"""
        import os
        env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(EnvironmentError):
                tag_speakers("テスト。", segment_speaker, all_speakers)


class TestMalformedJsonHandling:
    """PR18: speaker_tagger の json.loads が malformed JSON / empty content で
    例外を上位伝播せず、フォールバック (全文を 1 utterance) を返すことを検証。"""

    def _make_raw_response(self, content: str | None) -> MagicMock:
        mock_message = MagicMock()
        mock_message.content = content
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    def test_malformed_json_falls_back_to_single_utterance(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        raw_text = "テスト発言です。"

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = self._make_raw_response(
                "this is not json {{{"
            )
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        assert len(result) == 1
        assert result[0].speaker == segment_speaker.name
        assert result[0].text == raw_text

    def test_empty_content_falls_back_to_single_utterance(
        self,
        segment_speaker: SpeakerInfo,
        all_speakers: list[SpeakerInfo],
    ) -> None:
        raw_text = "別のテスト。"

        with patch("src.speaker_tagger._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = self._make_raw_response(None)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                result = tag_speakers(raw_text, segment_speaker, all_speakers)

        assert len(result) == 1
        assert result[0].speaker == segment_speaker.name
        assert result[0].text == raw_text


class TestBuildVideoUrl:
    def test_shugiin_url(self) -> None:
        url = _build_video_url("shugiin", "56149", 7320.2)
        assert "shugiintv.go.jp" in url
        assert "deli_id=56149" in url
        assert "time=7320.2" in url

    def test_sangiin_url(self) -> None:
        url = _build_video_url("sangiin", "7890", 180.5)
        assert url.startswith("https://www.webtv.sangiin.go.jp/")
        assert "sid=7890" in url
        assert "#180.5" in url

    def test_unknown_chamber_returns_empty(self) -> None:
        url = _build_video_url("unknown", "123", 0.0)
        assert url == ""


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
