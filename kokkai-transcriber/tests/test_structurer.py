"""LLM Q&Aペア・要約・トピック生成の単体テスト (Step 6)"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.models import (
    QAPairsOutput,
    SegmentUtterances,
    SpeakerInfo,
    SummaryOutput,
    TopicsOutput,
    Utterance,
    UtterancesOutput,
)
from src.structurer import (
    _assemble_full_text_from_sentences,
    _build_sentence_map,
    _build_sentence_to_utterance_map,
    _fuzzy_lookup,
    _split_sentences,
    build_summary_related_laws,
    generate_key_commitments,
    generate_qa_pairs,
    generate_session_summary,
    generate_topics_and_key_topics,
)


def _make_mock_llm_response(data: dict) -> MagicMock:
    content = json.dumps(data, ensure_ascii=False)
    mock_message = MagicMock()
    mock_message.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


@pytest.fixture
def sample_utterances() -> UtterancesOutput:
    return UtterancesOutput(
        segments=[
            SegmentUtterances(
                segment_index=0,
                segment_speaker="藤原徹",
                segment_affiliation="自由民主党",
                start_seconds=0.0,
                video_url="https://www.shugiintv.go.jp/jp/index.php?ex=VL&media_type=&deli_id=56149&time=0.0",
                utterances=[
                    Utterance(speaker="藤原徹", role="委員長", text="これより会議を開きます。"),
                ],
            ),
            SegmentUtterances(
                segment_index=1,
                segment_speaker="古川あおい",
                segment_affiliation="チームみらい",
                start_seconds=7320.2,
                video_url="https://www.shugiintv.go.jp/jp/index.php?ex=VL&media_type=&deli_id=56149&time=7320.2",
                utterances=[
                    Utterance(
                        speaker="古川あおい",
                        role="質疑者",
                        text="チームみらいの古川あおいです。高額療養費制度について伺います。",
                    ),
                    Utterance(
                        speaker="上野賢一郎",
                        role="答弁者",
                        text="お答えいたします。問題を認識しております。次期制度改正の検討課題として位置づけてまいりたい。",
                    ),
                ],
            ),
        ]
    )


class TestSplitSentences:
    def test_basic_split(self) -> None:
        """句点で分割される。"""
        result = _split_sentences("これは文1。これは文2。これは文3。")
        assert len(result) == 3
        assert result[0] == "これは文1。"
        assert result[1] == "これは文2。"

    def test_empty_input(self) -> None:
        """空文字はそのまま返す。"""
        result = _split_sentences("")
        assert result == [""]

    def test_no_period(self) -> None:
        """句点なしの場合は元テキスト全体を返す。"""
        result = _split_sentences("句点のないテキスト")
        assert result == ["句点のないテキスト"]

    def test_question_mark(self) -> None:
        """疑問符でも分割される。"""
        result = _split_sentences("質問ですか？はい、そうです。")
        assert len(result) == 2

    def test_exclamation_mark(self) -> None:
        """感嘆符でも分割される。"""
        result = _split_sentences("これは重要です！確認してください。")
        assert len(result) == 2


class TestFuzzyLookup:
    @pytest.fixture
    def speakers(self) -> dict[str, SpeakerInfo]:
        return {
            "森英介": SpeakerInfo(name="森英介", affiliation="自由民主党", start_seconds=0, start_time="", duration_minutes=0),
            "森田俊和": SpeakerInfo(name="森田俊和", affiliation="立憲民主党", start_seconds=0, start_time="", duration_minutes=0),
            "林芳正": SpeakerInfo(name="林芳正", affiliation="自由民主党", start_seconds=0, start_time="", duration_minutes=0),
            "古川あおい": SpeakerInfo(name="古川あおい", affiliation="チームみらい", start_seconds=0, start_time="", duration_minutes=0),
        }

    def test_exact_match(self, speakers: dict[str, SpeakerInfo]) -> None:
        """完全一致で見つかる。"""
        result = _fuzzy_lookup("森英介", speakers)
        assert result is not None
        assert result.name == "森英介"

    def test_no_match(self, speakers: dict[str, SpeakerInfo]) -> None:
        """一致しない場合はNone。"""
        result = _fuzzy_lookup("存在しない", speakers)
        assert result is None

    def test_two_char_surname(self, speakers: dict[str, SpeakerInfo]) -> None:
        """2文字姓のマッチ。"""
        result = _fuzzy_lookup("古川", speakers)
        assert result is not None
        assert result.name == "古川あおい"

    def test_single_char_surname_disambiguation(self, speakers: dict[str, SpeakerInfo]) -> None:
        """1文字姓（森）で複数候補がある場合。"""
        # This tests the improved fuzzy_lookup behavior
        result = _fuzzy_lookup("森", speakers)
        # Should return one of the 森* speakers
        assert result is not None
        assert result.name.startswith("森")


class TestAssembleFullText:
    def test_valid_indices(self) -> None:
        sentences = ["文1。", "文2。", "文3。"]
        result = _assemble_full_text_from_sentences(sentences, [0, 2])
        assert result == "文1。文3。"

    def test_empty_indices(self) -> None:
        """空インデックスは空文字を返す。"""
        sentences = ["文1。", "文2。"]
        result = _assemble_full_text_from_sentences(sentences, [])
        assert result == ""

    def test_out_of_range_indices(self) -> None:
        """範囲外インデックスは無視される。"""
        sentences = ["文1。", "文2。"]
        result = _assemble_full_text_from_sentences(sentences, [0, 5, 10])
        assert result == "文1。"

    def test_all_out_of_range(self) -> None:
        """全て範囲外なら空文字。"""
        sentences = ["文1。"]
        result = _assemble_full_text_from_sentences(sentences, [5, 10])
        assert result == ""


class TestBuildSentenceMap:
    def test_basic_mapping(self) -> None:
        """セグメントの文に通し番号が振られる。"""
        seg = SegmentUtterances(
            segment_index=0,
            segment_speaker="テスト太郎",
            segment_affiliation="テスト党",
            start_seconds=0.0,
            video_url="",
            utterances=[
                Utterance(speaker="テスト太郎", role="質疑者", text="質問です。回答をお願いします。"),
                Utterance(speaker="テスト次郎", role="答弁者", text="お答えします。"),
            ],
        )
        prompt_text, sentences = _build_sentence_map(seg)
        assert len(sentences) == 3
        assert "(0)" in prompt_text
        assert "(1)" in prompt_text
        assert "(2)" in prompt_text

    def test_empty_utterances(self) -> None:
        """空のutterancesでもエラーにならない。"""
        seg = SegmentUtterances(
            segment_index=0,
            segment_speaker="テスト",
            segment_affiliation="",
            start_seconds=0.0,
            video_url="",
            utterances=[],
        )
        prompt_text, sentences = _build_sentence_map(seg)
        assert len(sentences) == 0


class TestBuildSentenceToUtteranceMap:
    def test_mapping(self) -> None:
        """各sentenceがどのutteranceに属するかマッピングされる。"""
        seg = SegmentUtterances(
            segment_index=0,
            segment_speaker="テスト",
            segment_affiliation="",
            start_seconds=0.0,
            video_url="",
            utterances=[
                Utterance(speaker="A", role="質疑者", text="文1。文2。"),
                Utterance(speaker="B", role="答弁者", text="文3。"),
            ],
        )
        mapping = _build_sentence_to_utterance_map(seg)
        assert mapping == [0, 0, 1]


class TestGenerateQAPairs:
    def test_returns_qa_pairs_output(
        self, sample_utterances: UtterancesOutput
    ) -> None:
        """QAPairsOutput が返されること。"""
        mock_data = {
            "pairs": [
                {
                    "topic": "高額療養費の多数回該当リセット",
                    "question": {
                        "speaker": "古川あおい",
                        "party": "チームみらい",
                        "summary": "高額療養費の問題点について質問",
                        "full_text": "チームみらいの古川あおいです。高額療養費制度について伺います。",
                        "intent": "fact_check",
                    },
                    "answer": {
                        "speaker": "上野賢一郎",
                        "role": "厚生労働大臣",
                        "summary": "問題を認識しており検討中",
                        "full_text": "お答えいたします。問題を認識しております。",
                        "evasion_score": 0.3,
                        "has_commitment": True,
                        "commitment_text": "次期制度改正の検討課題として位置づけてまいりたい",
                    },
                }
            ]
        }

        with patch("src.structurer._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_data)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = generate_qa_pairs(sample_utterances)

        assert isinstance(result, QAPairsOutput)

    def test_qa_id_sequential(self, sample_utterances: UtterancesOutput) -> None:
        """Q&Aペアの id が連番であること（qa_001, qa_002, ...）。"""
        mock_data = {
            "pairs": [
                {
                    "topic": "トピック1",
                    "question": {
                        "summary": "質問1",
                        "sentence_indices": [0],
                        "intent": "fact_check",
                    },
                    "answer": {
                        "summary": "答弁1",
                        "sentence_indices": [1],
                        "evasion_score": 0.2,
                        "has_commitment": False,
                        "commitment_text": "",
                    },
                },
                {
                    "topic": "トピック2",
                    "question": {
                        "summary": "質問2",
                        "sentence_indices": [0],
                        "intent": "accountability",
                    },
                    "answer": {
                        "summary": "答弁2",
                        "sentence_indices": [1],
                        "evasion_score": 0.7,
                        "has_commitment": True,
                        "commitment_text": "検討します",
                    },
                },
            ]
        }

        with patch("src.structurer._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_data)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = generate_qa_pairs(sample_utterances)

        assert result.pairs[0].id == "qa_001"
        assert result.pairs[1].id == "qa_002"

    def test_evasion_score_in_range(self, sample_utterances: UtterancesOutput) -> None:
        """evasion_score が 0.0-1.0 の範囲であること。"""
        mock_data = {
            "pairs": [
                {
                    "topic": "テスト",
                    "question": {
                        "speaker": "A", "party": "B",
                        "summary": "Q", "full_text": "Q全文", "intent": "other",
                    },
                    "answer": {
                        "speaker": "C", "role": "D",
                        "summary": "A", "full_text": "A全文",
                        "evasion_score": 1.5,  # 範囲外 → クランプされること
                        "has_commitment": False, "commitment_text": "",
                    },
                }
            ]
        }

        with patch("src.structurer._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_data)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = generate_qa_pairs(sample_utterances)

        for pair in result.pairs:
            assert 0.0 <= pair.answer.evasion_score <= 1.0


def _make_qa_pairs(*pair_ids: str) -> QAPairsOutput:
    from src.models import AnswerDetail, QAPair, QuestionDetail

    return QAPairsOutput(
        pairs=[
            QAPair(
                id=pid,
                segment_index=i,
                topic=f"トピック{i}",
                question=QuestionDetail(
                    speaker="古川あおい",
                    party="チームみらい",
                    summary="要旨",
                    full_text="全文",
                    intent="fact_check",
                ),
                answer=AnswerDetail(
                    speaker="上野賢一郎",
                    role="答弁者",
                    summary="答弁要旨",
                    full_text="答弁全文",
                    evasion_score=0.3,
                    has_commitment=False,
                    commitment_text="",
                ),
                video_url="https://example.com",
            )
            for i, pid in enumerate(pair_ids)
        ]
    )


class TestGenerateSessionSummary:
    def test_returns_string_from_qa_pairs(self) -> None:
        qa_pairs = _make_qa_pairs("qa_001")
        mock_data = {"session_summary": "今回の会議では高額療養費について議論された。"}

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_data)
            mock_factory.return_value = mock_client
            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = generate_session_summary(qa_pairs)

        assert result == "今回の会議では高額療養費について議論された。"

    def test_empty_qa_with_no_utterances_returns_empty(self) -> None:
        with patch("src.structurer._get_client") as mock_factory:
            result = generate_session_summary(QAPairsOutput(pairs=[]), None)

        assert result == ""
        mock_factory.assert_not_called()


class TestGenerateTopicsAndKeyTopics:
    def test_returns_topics_and_subset_key_topics(self) -> None:
        qa_pairs = _make_qa_pairs("qa_001", "qa_002")
        mock_data = {
            "topics": [
                {
                    "name": "医療保険制度改革",
                    "description": "高額療養費制度の見直し",
                    "related_qa_ids": ["qa_001"],
                    "related_speakers": ["古川あおい"],
                },
                {
                    "name": "周産期医療",
                    "description": "妊婦支援",
                    "related_qa_ids": ["qa_002"],
                    "related_speakers": ["古川あおい"],
                },
            ],
            "key_topics": ["医療保険制度改革", "存在しないトピック"],
        }

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_data)
            mock_factory.return_value = mock_client
            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                topics, key_topics = generate_topics_and_key_topics(qa_pairs)

        assert isinstance(topics, TopicsOutput)
        assert len(topics.topics) == 2
        assert key_topics == ["医療保険制度改革"]

    def test_drops_unknown_qa_id_from_related_qa_ids(self) -> None:
        qa_pairs = _make_qa_pairs("qa_001")
        mock_data = {
            "topics": [
                {
                    "name": "テーマ A",
                    "description": "...",
                    "related_qa_ids": ["qa_001", "qa_999"],
                    "related_speakers": [],
                }
            ],
            "key_topics": ["テーマ A"],
        }

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_data)
            mock_factory.return_value = mock_client
            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                topics, _ = generate_topics_and_key_topics(qa_pairs)

        assert topics.topics[0].related_qa_ids == ["qa_001"]

    def test_empty_qa_returns_empty_without_llm_call(self) -> None:
        with patch("src.structurer._get_client") as mock_factory:
            topics, key_topics = generate_topics_and_key_topics(QAPairsOutput(pairs=[]))

        assert topics.topics == []
        assert key_topics == []
        mock_factory.assert_not_called()


class TestGenerateKeyCommitments:
    def test_drops_unknown_qa_id(self) -> None:
        qa_pairs = _make_qa_pairs("qa_001")
        mock_data = {
            "key_commitments": [
                {
                    "speaker": "上野賢一郎",
                    "role": "答弁者",
                    "text": "次期改正で位置づける",
                    "topic": "高額療養費",
                    "qa_id": "qa_001",
                },
                {
                    "speaker": "誰か",
                    "role": "答弁者",
                    "text": "幽霊コミット",
                    "topic": "?",
                    "qa_id": "qa_999",
                },
            ]
        }

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_data)
            mock_factory.return_value = mock_client
            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                commitments = generate_key_commitments(qa_pairs)

        assert len(commitments) == 1
        assert commitments[0].qa_id == "qa_001"


class TestBuildSummaryRelatedLaws:
    def test_aggregates_per_pair_tags(self) -> None:
        qa_pairs = _make_qa_pairs("qa_001", "qa_002", "qa_003")
        qa_pairs.pairs[0].related_law_ids = ["law_001", "law_002"]
        qa_pairs.pairs[1].related_law_ids = ["law_001"]
        qa_pairs.pairs[2].related_law_ids = []

        result = build_summary_related_laws(qa_pairs)
        result_map = {r.law_id: sorted(r.qa_ids) for r in result}

        assert result_map == {
            "law_001": ["qa_001", "qa_002"],
            "law_002": ["qa_001"],
        }

    def test_drops_ghost_tags(self) -> None:
        qa_pairs = _make_qa_pairs("qa_001")
        qa_pairs.pairs[0].related_law_ids = []
        result = build_summary_related_laws(qa_pairs)
        assert result == []


class TestShortAnswerDrop:
    def test_drops_pair_with_empty_answer_and_no_indices(self) -> None:
        from src.structurer import _extract_pairs_from_response

        seg = SegmentUtterances(
            segment_index=0,
            segment_speaker="古川あおい",
            segment_affiliation="チームみらい",
            start_seconds=0.0,
            video_url="",
            utterances=[
                Utterance(speaker="古川あおい", role="質疑者", text="質問本文。"),
            ],
        )
        all_sentences = ["質問本文。"]
        content = json.dumps({
            "pairs": [
                {
                    "topic": "ダミー",
                    "question": {"summary": "Q", "sentence_indices": [0], "intent": "other"},
                    "answer": {
                        "summary": "A",
                        "sentence_indices": [],
                        "evasion_score": 1.0,
                        "has_commitment": False,
                        "commitment_text": "",
                    },
                }
            ]
        })

        result = _extract_pairs_from_response(content, seg, all_sentences, {})
        assert result == []


class TestGenerateQAForSegmentErrorHandling:
    """_generate_qa_for_segment のエラーハンドリングテスト。"""

    @pytest.fixture
    def segment(self) -> SegmentUtterances:
        return SegmentUtterances(
            segment_index=0,
            segment_speaker="テスト太郎",
            segment_affiliation="テスト党",
            start_seconds=0.0,
            video_url="",
            utterances=[
                Utterance(speaker="テスト太郎", role="質疑者", text="質問です。"),
                Utterance(speaker="テスト次郎", role="答弁者", text="お答えします。"),
            ],
        )

    def _make_mock_response(self, content: str) -> MagicMock:
        mock_message = MagicMock()
        mock_message.content = content
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    def test_malformed_json_returns_empty(self, segment: SegmentUtterances) -> None:
        """不正なJSONが返された場合は空リストを返す。"""
        from src.structurer import _generate_qa_for_segment

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = self._make_mock_response(
                "this is not json"
            )
            mock_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = _generate_qa_for_segment(segment, "context", {})

        assert result == []

    def test_empty_response_returns_empty(self, segment: SegmentUtterances) -> None:
        """空レスポンスの場合は空リストを返す。"""
        from src.structurer import _generate_qa_for_segment

        mock_message = MagicMock()
        mock_message.content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = _generate_qa_for_segment(segment, "context", {})

        assert result == []

    def test_missing_pairs_key_returns_empty(self, segment: SegmentUtterances) -> None:
        """'pairs' キーがない場合は空リストを返す。"""
        from src.structurer import _generate_qa_for_segment

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = self._make_mock_response(
                json.dumps({"no_pairs_key": []})
            )
            mock_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = _generate_qa_for_segment(segment, "context", {})

        assert result == []

    def test_valid_response_extracts_pairs(self, segment: SegmentUtterances) -> None:
        """正常なレスポンスからQ&Aペアを抽出する。"""
        from src.structurer import _generate_qa_for_segment

        valid_response = {
            "pairs": [
                {
                    "topic": "テスト",
                    "question": {
                        "summary": "- 質問要旨",
                        "sentence_indices": [0],
                        "intent": "fact_check",
                    },
                    "answer": {
                        "summary": "- 回答要旨",
                        "sentence_indices": [1],
                        "evasion_score": 0.2,
                        "has_commitment": False,
                    },
                }
            ]
        }

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = self._make_mock_response(
                json.dumps(valid_response, ensure_ascii=False)
            )
            mock_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = _generate_qa_for_segment(segment, "context", {})

        assert len(result) == 1
        assert result[0].topic == "テスト"


@pytest.mark.integration
class TestStructurerIntegration:
    def test_real_qa_generation(self, sample_utterances: UtterancesOutput) -> None:
        """実際の LLM API でQ&Aペア生成をテストする（結合テスト）。"""
        result = generate_qa_pairs(sample_utterances)
        assert isinstance(result, QAPairsOutput)
        for pair in result.pairs:
            assert 0.0 <= pair.answer.evasion_score <= 1.0
