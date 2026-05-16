"""LLM 話者タグ付けの単体テスト (Step 5)

文番号インデックス方式: LLMは話者交代ポイント(splits)のみ返し、
テキスト本体はコード側で結合する。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.models import (
    RawTranscript,
    SegmentTranscript,
    SegmentUtterances,
    SpeakerInfo,
    Utterance,
    UtterancesOutput,
)
from src.speaker_tagger import (
    _build_video_url,
    _merge_overflow_into_previous,
    _split_sentences,
    tag_all_segments,
    tag_speakers,
)


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

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
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

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
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

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
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

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
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

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
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

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
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
                tag_speakers("テスト。", segment_speaker, all_speakers)


class TestBuildVideoUrl:
    def test_shugiin_url(self) -> None:
        url = _build_video_url("shugiin", "56149", 7320.2)
        assert "shugiintv.go.jp" in url
        assert "deli_id=56149" in url
        assert "time=7320.2" in url

    def test_sangiin_url(self) -> None:
        url = _build_video_url("sangiin", "7890", 180.5)
        assert "webtv.sangiin.go.jp" in url
        assert "sid=7890" in url
        assert "#180.5" in url

    def test_unknown_chamber_returns_empty(self) -> None:
        url = _build_video_url("unknown", "123", 0.0)
        assert url == ""


def _make_seg(idx: int, speaker: str, utts: list[tuple[str, str, str]]) -> SegmentUtterances:
    """テスト用ヘルパー: (role, speaker, text) のリストから SegmentUtterances を作る。"""
    return SegmentUtterances(
        segment_index=idx,
        segment_speaker=speaker,
        segment_affiliation="",
        start_seconds=float(idx * 1000),
        video_url=f"https://example.com/?t={idx * 1000}",
        utterances=[Utterance(role=r, speaker=s, text=t) for r, s, t in utts],
    )


class TestMergeOverflowIntoPrevious:
    """衆議院TV 公開 `time=` の前倒し起因の文中切れを境界補正する後処理のテスト。"""

    def test_merges_overflow_question_with_speaker_correction(self) -> None:
        """56248 型: 前 seg が文中で終わり、次 seg の先頭 utterance が
        前話者の質問続きを誤った speaker 名で tag されている。"""
        prev = _make_seg(2, "古川あおい", [
            ("質疑者", "古川あおい", "ICT等のテクノロジーを導入して、"),
        ])
        curr = _make_seg(3, "梅村聡", [
            # 古川の続き、誤 tag された先頭
            ("質疑者", "梅村聡", "生産性を向上させることが不可欠だと考えます。"),
            ("委員長", "大串正樹", "老健局長。"),
            ("政府参考人", "黒田", "お答え申し上げます..."),
            ("委員長", "大串正樹", "古川あおい君。"),
            ("質疑者", "古川あおい", "ありがとうございます..."),
            ("委員長", "大串正樹", "次に梅村聡君。"),  # ← ここで梅村が初登場
            ("質疑者", "梅村聡", "日本維新の会の梅村聡です..."),
        ])

        _merge_overflow_into_previous([prev, curr])

        # u[0..4] が prev にマージされる
        assert len(prev.utterances) == 1 + 5
        # 誤 tag されていた先頭 utterance は前 seg の speaker (古川あおい) に修正される
        moved_head = prev.utterances[1]
        assert moved_head.speaker == "古川あおい"
        assert moved_head.role == "質疑者"
        assert "生産性を向上" in moved_head.text
        # その他の utterance の speaker/role は維持される
        assert prev.utterances[2].role == "委員長"
        assert prev.utterances[3].speaker == "黒田"
        assert prev.utterances[5].speaker == "古川あおい"

        # curr は委員長指名行から始まる
        assert len(curr.utterances) == 2
        assert curr.utterances[0].role == "委員長"
        assert "次に梅村聡君" in curr.utterances[0].text
        assert curr.utterances[1].speaker == "梅村聡"

    def test_skips_when_prev_ends_with_sentence_punct(self) -> None:
        """前 seg が句点で綺麗に終わっていれば何もしない。"""
        prev = _make_seg(0, "A", [("質疑者", "A", "質問は以上です。")])
        curr = _make_seg(1, "B", [
            ("質疑者", "B", "おはようございます。"),
            ("委員長", "X", "次にB君。"),
        ])
        before_prev = len(prev.utterances)
        before_curr = len(curr.utterances)
        _merge_overflow_into_previous([prev, curr])
        assert len(prev.utterances) == before_prev
        assert len(curr.utterances) == before_curr

    def test_skips_when_no_chair_nomination_of_current_speaker(self) -> None:
        """現 seg 内に current segment_speaker を指名する委員長行が無ければ
        過剰マージを避けるため何もしない。"""
        prev = _make_seg(0, "A", [("質疑者", "A", "途中で切れる")])
        curr = _make_seg(1, "B", [
            ("質疑者", "B", "Bさんの発言"),
            ("委員長", "X", "別の人を呼ぶ"),  # B を指名していない
        ])
        before_curr = len(curr.utterances)
        _merge_overflow_into_previous([prev, curr])
        assert len(curr.utterances) == before_curr

    def test_skips_when_first_utterance_is_chair(self) -> None:
        """現 seg の先頭が委員長行なら overflow とみなさない (nominate_idx == 0)。"""
        prev = _make_seg(0, "A", [("質疑者", "A", "途中で切れる")])
        curr = _make_seg(1, "B", [
            ("委員長", "X", "次にB君。"),
            ("質疑者", "B", "Bさんの発言"),
        ])
        before_curr = len(curr.utterances)
        _merge_overflow_into_previous([prev, curr])
        assert len(curr.utterances) == before_curr

    def test_merges_answer_continuation_without_speaker_correction(self) -> None:
        """先頭 utterance が 答弁者 (== current segment_speaker ではない) のケースでは
        speaker 修正は行わず、utterances のみマージする。"""
        prev = _make_seg(0, "大森江里子", [("質疑者", "大森江里子", "質問の途中で切れる")])
        curr = _make_seg(1, "犬飼明佳", [
            ("答弁者", "松本尚", "答弁の続きです..."),
            ("委員長", "丹羽秀樹", "次に犬飼明佳君。"),
            ("質疑者", "犬飼明佳", "犬飼の発言"),
        ])
        _merge_overflow_into_previous([prev, curr])
        assert len(prev.utterances) == 2
        # 答弁者 utterance はそのまま (speaker 修正なし)
        assert prev.utterances[1].speaker == "松本尚"
        assert prev.utterances[1].role == "答弁者"
        assert len(curr.utterances) == 2

    def test_speaker_key_matches_by_family_name_prefix(self) -> None:
        """委員長指名行で苗字のみ (短縮形) のときも先頭3字で部分一致する。"""
        prev = _make_seg(0, "A", [("質疑者", "A", "途中で切れる")])
        curr = _make_seg(1, "近藤雅彦", [
            ("答弁者", "尾形", "答弁..."),
            ("委員長", "武村", "武村委員長。次に近藤雅彦君。近藤君。"),
            ("質疑者", "近藤雅彦", "近藤の発言"),
        ])
        _merge_overflow_into_previous([prev, curr])
        assert len(prev.utterances) == 2
        assert prev.utterances[1].speaker == "尾形"
        assert len(curr.utterances) == 2

    def test_empty_segments_handled_gracefully(self) -> None:
        """空の segment があっても落ちない。"""
        prev = _make_seg(0, "A", [])
        curr = _make_seg(1, "B", [("質疑者", "B", "test")])
        _merge_overflow_into_previous([prev, curr])
        # no-op

    def test_single_segment_no_crash(self) -> None:
        """segment が 1 つだけでも落ちない。"""
        seg = _make_seg(0, "A", [("質疑者", "A", "途中で切れる")])
        _merge_overflow_into_previous([seg])
        assert len(seg.utterances) == 1


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
