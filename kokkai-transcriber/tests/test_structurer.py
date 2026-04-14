"""LLM Q&Aペア・要約・トピック生成の単体テスト (Step 6)"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.models import (
    QAPairsOutput,
    SegmentUtterances,
    SummaryOutput,
    TopicsOutput,
    Utterance,
    UtterancesOutput,
)
from src.structurer import generate_qa_pairs, generate_summary, generate_topics


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
                        "speaker": "話者A", "party": "党A",
                        "summary": "質問1", "full_text": "質問1全文", "intent": "fact_check",
                    },
                    "answer": {
                        "speaker": "答弁者A", "role": "大臣A",
                        "summary": "答弁1", "full_text": "答弁1全文",
                        "evasion_score": 0.2, "has_commitment": False, "commitment_text": "",
                    },
                },
                {
                    "topic": "トピック2",
                    "question": {
                        "speaker": "話者B", "party": "党B",
                        "summary": "質問2", "full_text": "質問2全文", "intent": "accountability",
                    },
                    "answer": {
                        "speaker": "答弁者B", "role": "大臣B",
                        "summary": "答弁2", "full_text": "答弁2全文",
                        "evasion_score": 0.7, "has_commitment": True,
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


class TestGenerateSummary:
    def test_returns_summary_output(
        self, sample_utterances: UtterancesOutput
    ) -> None:
        """SummaryOutput が返されること。"""
        from src.models import QAPair, QuestionDetail, AnswerDetail
        qa_pairs = QAPairsOutput(
            pairs=[
                QAPair(
                    id="qa_001",
                    segment_index=1,
                    topic="高額療養費",
                    question=QuestionDetail(
                        speaker="古川あおい",
                        party="チームみらい",
                        summary="高額療養費の問題",
                        full_text="全文",
                        intent="fact_check",
                    ),
                    answer=AnswerDetail(
                        speaker="上野賢一郎",
                        role="大臣",
                        summary="認識している",
                        full_text="答弁全文",
                        evasion_score=0.3,
                        has_commitment=True,
                        commitment_text="検討する",
                    ),
                    video_url="https://example.com",
                )
            ]
        )

        mock_data = {
            "session_summary": "今回の会議では健康保険法改正が議題となった。",
            "key_topics": ["高額療養費", "健康保険法改正"],
            "key_commitments": [
                {
                    "speaker": "上野賢一郎",
                    "role": "厚生労働大臣",
                    "text": "次期制度改正の検討課題として位置づけてまいりたい",
                    "topic": "高額療養費",
                    "qa_id": "qa_001",
                }
            ],
        }

        with patch("src.structurer._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_data)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = generate_summary(sample_utterances, qa_pairs)

        assert isinstance(result, SummaryOutput)

    def test_key_topics_not_empty(
        self, sample_utterances: UtterancesOutput
    ) -> None:
        """key_topics が空でないこと。"""
        from src.models import QAPairsOutput
        qa_pairs = QAPairsOutput(pairs=[])

        mock_data = {
            "session_summary": "要約テキスト",
            "key_topics": ["トピック1", "トピック2"],
            "key_commitments": [],
        }

        with patch("src.structurer._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_data)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = generate_summary(sample_utterances, qa_pairs)

        assert len(result.key_topics) > 0


class TestGenerateTopics:
    def test_returns_topics_output(self) -> None:
        """TopicsOutput が返されること。"""
        from src.models import QAPair, QAPairsOutput, QuestionDetail, AnswerDetail
        qa_pairs = QAPairsOutput(
            pairs=[
                QAPair(
                    id="qa_001",
                    segment_index=0,
                    topic="健康保険法改正",
                    question=QuestionDetail(
                        speaker="古川あおい", party="チームみらい",
                        summary="要旨", full_text="全文", intent="fact_check",
                    ),
                    answer=AnswerDetail(
                        speaker="上野", role="大臣",
                        summary="答弁", full_text="答弁全文",
                        evasion_score=0.2, has_commitment=False, commitment_text="",
                    ),
                    video_url="https://example.com",
                )
            ]
        )

        mock_data = {
            "topics": [
                {
                    "name": "医療保険制度改革",
                    "description": "高額療養費制度の見直しを含む健康保険法改正に関する質疑",
                    "related_qa_ids": ["qa_001"],
                    "related_speakers": ["古川あおい", "上野賢一郎"],
                }
            ]
        }

        with patch("src.structurer._get_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_data)
            mock_client_factory.return_value = mock_client

            with patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}):
                result = generate_topics(qa_pairs)

        assert isinstance(result, TopicsOutput)
        assert len(result.topics) > 0


@pytest.mark.integration
class TestStructurerIntegration:
    def test_real_qa_generation(self, sample_utterances: UtterancesOutput) -> None:
        """実際の LLM API でQ&Aペア生成をテストする（結合テスト）。"""
        result = generate_qa_pairs(sample_utterances)
        assert isinstance(result, QAPairsOutput)
        for pair in result.pairs:
            assert 0.0 <= pair.answer.evasion_score <= 1.0
