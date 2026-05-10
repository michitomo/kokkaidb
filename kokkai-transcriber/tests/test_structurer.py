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
    _assemble_full_text_for_pair,
    _build_utterance_map,
    _compute_segment_layout,
    _compute_share_boundaries,
    _extract_pairs_from_response,
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


class TestBuildUtteranceMap:
    def test_basic_numbering(self) -> None:
        """各 utterance が [Un] 番号でラベル付けされる。"""
        seg = SegmentUtterances(
            segment_index=0,
            segment_speaker="テスト太郎",
            segment_affiliation="テスト党",
            start_seconds=0.0,
            video_url="",
            utterances=[
                Utterance(speaker="テスト太郎", role="質疑者", text="質問です。回答お願いします。"),
                Utterance(speaker="テスト次郎", role="答弁者", text="お答えします。"),
            ],
        )
        layout = _compute_segment_layout(seg)
        prompt_text = _build_utterance_map(seg, layout)
        assert "[U0]" in prompt_text
        assert "[U1]" in prompt_text
        assert "テスト太郎" in prompt_text
        # 短い utterance は (sN) サブ番号を出さない
        assert "(s0)" not in prompt_text

    def test_long_utterance_includes_sentence_subnumbers(self) -> None:
        """長文 utterance は (sN) サブ番号で分割される。"""
        long_text = "".join(f"これは{i}番目の文です。" for i in range(15))
        seg = SegmentUtterances(
            segment_index=0,
            segment_speaker="高市早苗",
            segment_affiliation="自由民主党",
            start_seconds=0.0,
            video_url="",
            utterances=[
                Utterance(speaker="高市早苗", role="答弁者", text=long_text),
            ],
        )
        layout = _compute_segment_layout(seg)
        prompt_text = _build_utterance_map(seg, layout)
        assert "[U0]" in prompt_text
        assert "(s0)" in prompt_text
        assert "(s14)" in prompt_text

    def test_empty_utterances(self) -> None:
        """空 utterances でもエラーにならない。"""
        seg = SegmentUtterances(
            segment_index=0,
            segment_speaker="テスト",
            segment_affiliation="",
            start_seconds=0.0,
            video_url="",
            utterances=[],
        )
        layout = _compute_segment_layout(seg)
        prompt_text = _build_utterance_map(seg, layout)
        assert layout.total_sentences == 0
        assert "テスト" in prompt_text


class TestAssembleFullTextForPair:
    def _make_seg(self) -> SegmentUtterances:
        return SegmentUtterances(
            segment_index=0,
            segment_speaker="A",
            segment_affiliation="X党",
            start_seconds=0.0,
            video_url="",
            utterances=[
                Utterance(speaker="A", role="質疑者", text="質問1。質問2。"),
                Utterance(speaker="B", role="答弁者", text="お答えいたします。要点を述べます。"),
            ],
        )

    def test_single_utterance_no_anchor(self) -> None:
        """anchor なし: utterance 全文が連結される。"""
        seg = self._make_seg()
        layout = _compute_segment_layout(seg)
        result = _assemble_full_text_for_pair(seg, layout, [1], None, None)
        assert result == "お答えいたします。要点を述べます。"

    def test_multiple_utterances_no_anchor(self) -> None:
        """複数 utterance: 改行で連結される。"""
        seg = self._make_seg()
        layout = _compute_segment_layout(seg)
        result = _assemble_full_text_for_pair(seg, layout, [0, 1], None, None)
        assert "質問1。質問2。" in result
        assert "お答えいたします。要点を述べます。" in result

    def test_empty_indices(self) -> None:
        """空 indices は空文字。"""
        seg = self._make_seg()
        layout = _compute_segment_layout(seg)
        assert _assemble_full_text_for_pair(seg, layout, [], None, None) == ""

    def test_out_of_range_ignored(self) -> None:
        """範囲外 index は無視される。"""
        seg = self._make_seg()
        layout = _compute_segment_layout(seg)
        result = _assemble_full_text_for_pair(seg, layout, [99], None, None)
        assert result == ""

    def _make_long_seg(self) -> SegmentUtterances:
        """1 つの長文 utterance (10 文) を持つセグメント。anchor 検証用。"""
        long_text = "".join(f"これは{i}番目の文です。" for i in range(10))
        return SegmentUtterances(
            segment_index=0,
            segment_speaker="高市",
            segment_affiliation="自由民主党",
            start_seconds=0.0,
            video_url="",
            utterances=[Utterance(speaker="高市", role="答弁者", text=long_text)],
        )

    def test_anchor_with_no_boundary_slices_to_end(self) -> None:
        """anchor あり・boundary なし: anchor から utterance 末尾まで。"""
        seg = self._make_long_seg()
        layout = _compute_segment_layout(seg)
        # anchor=3 → 3,4,5,6,7,8,9 の 7 文
        result = _assemble_full_text_for_pair(seg, layout, [0], 3, None)
        assert "これは2番目の文です。" not in result
        assert "これは3番目の文です。" in result
        assert "これは9番目の文です。" in result

    def test_anchor_with_boundary_slices_range(self) -> None:
        """anchor + boundary: [anchor, boundary) のスライスのみ。"""
        seg = self._make_long_seg()
        layout = _compute_segment_layout(seg)
        # anchor=2, boundary=5 → 2,3,4 の 3 文
        result = _assemble_full_text_for_pair(seg, layout, [0], 2, 5)
        assert "これは1番目の文です。" not in result
        assert "これは2番目の文です。" in result
        assert "これは4番目の文です。" in result
        assert "これは5番目の文です。" not in result

    def test_anchor_at_zero_returns_full(self) -> None:
        """anchor=0, boundary なし: 全文と等価。"""
        seg = self._make_long_seg()
        layout = _compute_segment_layout(seg)
        result = _assemble_full_text_for_pair(seg, layout, [0], 0, None)
        assert "これは0番目の文です。" in result
        assert "これは9番目の文です。" in result

    def test_anchor_out_of_range_falls_back_to_full(self) -> None:
        """anchor が utterance の sentence 数を超えた場合は utterance 全文にフォールバック。"""
        seg = self._make_long_seg()
        layout = _compute_segment_layout(seg)
        result = _assemble_full_text_for_pair(seg, layout, [0], 999, None)
        assert "これは0番目の文です。" in result
        assert "これは9番目の文です。" in result

    def test_anchor_plus_trailing_utterances(self) -> None:
        """anchor 付き head + 後続 utterance: head は slice、後続は丸ごと連結。"""
        long_text = "".join(f"head文{i}。" for i in range(8))
        seg = SegmentUtterances(
            segment_index=0,
            segment_speaker="A",
            segment_affiliation="X党",
            start_seconds=0.0,
            video_url="",
            utterances=[
                Utterance(speaker="A", role="答弁者", text=long_text),
                Utterance(speaker="B", role="答弁者", text="後続発言。"),
            ],
        )
        layout = _compute_segment_layout(seg)
        result = _assemble_full_text_for_pair(seg, layout, [0, 1], 5, None)
        assert "head文4。" not in result
        assert "head文5。" in result
        assert "head文7。" in result
        assert "後続発言。" in result


class TestComputeShareBoundaries:
    """`_compute_share_boundaries` の境界計算ロジック。"""

    def _pair(
        self,
        q_uidx: list[int] | None = None,
        q_anchor: int | None = None,
        a_uidx: list[int] | None = None,
        a_anchor: int | None = None,
    ) -> dict[str, object]:
        return {
            "q_uidx": q_uidx or [],
            "q_anchor": q_anchor,
            "a_uidx": a_uidx or [],
            "a_anchor": a_anchor,
        }

    def test_empty_pairs(self) -> None:
        assert _compute_share_boundaries([], "q") == []

    def test_no_anchors_all_none(self) -> None:
        """anchor なしのペアは boundary も None。"""
        pairs = [self._pair(q_uidx=[5]), self._pair(q_uidx=[5])]
        assert _compute_share_boundaries(pairs, "q") == [None, None]

    def test_single_pair_with_anchor_unshared(self) -> None:
        """anchor 付きでも他に共有相手がいなければ boundary は None。"""
        pairs = [self._pair(q_uidx=[5], q_anchor=3)]
        assert _compute_share_boundaries(pairs, "q") == [None]

    def test_two_pairs_share_head_boundaries_in_anchor_order(self) -> None:
        """同じ head を共有する 2 ペアは anchor 昇順で次の anchor が boundary。最後は None。"""
        pairs = [
            self._pair(q_uidx=[5], q_anchor=120),
            self._pair(q_uidx=[5], q_anchor=145),
        ]
        # ソート後: pair0 (anchor=120) → boundary=145 / pair1 (anchor=145) → boundary=None
        assert _compute_share_boundaries(pairs, "q") == [145, None]

    def test_three_pairs_share_head_unsorted_input(self) -> None:
        """LLM 出力が anchor 順でなくても正しく境界を割り当てる。"""
        pairs = [
            self._pair(q_uidx=[5], q_anchor=200),  # 後半
            self._pair(q_uidx=[5], q_anchor=100),  # 前半
            self._pair(q_uidx=[5], q_anchor=150),  # 中央
        ]
        # anchor 昇順: 100→150, 150→200, 200→None
        # 元の index に戻す: pair0(200)→None, pair1(100)→150, pair2(150)→200
        assert _compute_share_boundaries(pairs, "q") == [None, 150, 200]

    def test_q_and_a_independent(self) -> None:
        """q 側の共有は a 側に影響しない。"""
        pairs = [
            self._pair(q_uidx=[5], q_anchor=10, a_uidx=[7]),
            self._pair(q_uidx=[5], q_anchor=20, a_uidx=[8]),
        ]
        assert _compute_share_boundaries(pairs, "q") == [20, None]
        assert _compute_share_boundaries(pairs, "a") == [None, None]

    def test_anchor_none_excluded_from_share_group(self) -> None:
        """anchor=None のペアは共有グループに含めない (boundary 計算対象外)。"""
        pairs = [
            self._pair(q_uidx=[5], q_anchor=10),
            self._pair(q_uidx=[5], q_anchor=None),  # 共有グループに入らない
            self._pair(q_uidx=[5], q_anchor=30),
        ]
        # 共有グループは pair0(10), pair2(30) のみ
        assert _compute_share_boundaries(pairs, "q") == [30, None, None]

    def test_different_heads_no_sharing(self) -> None:
        """別 utterance を head にもつペア同士は共有しない。"""
        pairs = [
            self._pair(q_uidx=[5], q_anchor=10),
            self._pair(q_uidx=[6], q_anchor=20),
        ]
        assert _compute_share_boundaries(pairs, "q") == [None, None]


class TestSharedUtteranceEnd2End:
    """`_extract_pairs_from_response` を経由した共有 utterance のシナリオ。

    代表質問・所信表明など 1 utterance に複数 Q または A が連なるケースを再現。
    """

    def _make_long_seg(self) -> SegmentUtterances:
        # 質疑者 (短文) + 答弁者 (長文 12 文) の 2 utterance
        answer_text = "".join(f"answer文{i}。" for i in range(12))
        return SegmentUtterances(
            segment_index=0,
            segment_speaker="質問者",
            segment_affiliation="X党",
            start_seconds=0.0,
            video_url="https://example.com/",
            utterances=[
                Utterance(speaker="質問者", role="質疑者", text="まとめて伺います。"),
                Utterance(speaker="高市早苗", role="答弁者", text=answer_text),
            ],
        )

    def test_two_answers_share_one_utterance_via_anchors(self) -> None:
        """2 ペアが同じ答弁 utterance を anchor で分割共有する。"""
        seg = self._make_long_seg()
        layout = _compute_segment_layout(seg)
        # answer utterance は seg.utterances[1] で sentences は global index 1..12
        # (質問者 utterance の 1 文 "まとめて伺います。" が s0)
        # → anchor を s1 (answer の先頭) と s5 (answer の途中) に置く
        response = json.dumps({
            "pairs": [
                {
                    "topic": "前半トピック",
                    "question": {
                        "utterance_indices": [0],
                        "split_anchor_sentence_idx": None,
                        "summary": "- 前半",
                        "intent": "information_request",
                    },
                    "answer": {
                        "utterance_indices": [1],
                        "split_anchor_sentence_idx": 1,
                        "summary": "- 前半回答",
                    },
                },
                {
                    "topic": "後半トピック",
                    "question": {
                        "utterance_indices": [0],
                        "split_anchor_sentence_idx": None,
                        "summary": "- 後半",
                        "intent": "information_request",
                    },
                    "answer": {
                        "utterance_indices": [1],
                        "split_anchor_sentence_idx": 5,
                        "summary": "- 後半回答",
                    },
                },
            ]
        }, ensure_ascii=False)

        pairs = _extract_pairs_from_response(response, seg, layout, {})
        assert len(pairs) == 2

        a0 = pairs[0].answer.full_text
        a1 = pairs[1].answer.full_text
        # ペア0 は anchor=1 → boundary=5: answer 文 0..3 (global 1..4)
        assert "answer文0。" in a0
        assert "answer文3。" in a0
        assert "answer文4。" not in a0
        # ペア1 は anchor=5 → boundary=None: answer 文 4..11 (global 5..12)
        assert "answer文0。" not in a1
        assert "answer文4。" in a1
        assert "answer文11。" in a1

        # 全文をどちらかが拾い切ること (穴ができない)
        combined = a0 + a1
        for i in range(12):
            assert f"answer文{i}。" in combined


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
                        "utterance_indices": [0],
                        "split_anchor_sentence_idx": None,
                        "intent": "fact_check",
                    },
                    "answer": {
                        "summary": "答弁1",
                        "utterance_indices": [1],
                        "split_anchor_sentence_idx": None,
                    },
                },
                {
                    "topic": "トピック2",
                    "question": {
                        "summary": "質問2",
                        "utterance_indices": [0],
                        "split_anchor_sentence_idx": None,
                        "intent": "accountability",
                    },
                    "answer": {
                        "summary": "答弁2",
                        "utterance_indices": [1],
                        "split_anchor_sentence_idx": None,
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

    def test_full_text_assembled_from_utterances(
        self, sample_utterances: UtterancesOutput,
    ) -> None:
        """full_text が utterance.text 全文から組み立てられること。"""
        mock_data = {
            "pairs": [
                {
                    "topic": "高額療養費",
                    "question": {
                        "summary": "- 質問要旨",
                        "utterance_indices": [0],
                        "split_anchor_sentence_idx": None,
                        "intent": "fact_check",
                    },
                    "answer": {
                        "summary": "- 答弁要旨",
                        "utterance_indices": [1],
                        "split_anchor_sentence_idx": None,
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

        assert len(result.pairs) == 1
        # sample_utterances の segment_index=1 の質疑者 utterance (uidx=0 within block)
        # が question.full_text に丸ごと反映されることを確認
        assert "チームみらい" in result.pairs[0].question.full_text
        assert "高額療養費" in result.pairs[0].question.full_text
        # answer も同様に utterance 全文が入る (挨拶含む)
        assert "お答えいたします" in result.pairs[0].answer.full_text
        assert "次期制度改正" in result.pairs[0].answer.full_text


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
        from src.structurer import _compute_segment_layout, _extract_pairs_from_response

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
        layout = _compute_segment_layout(seg)
        content = json.dumps({
            "pairs": [
                {
                    "topic": "ダミー",
                    "question": {
                        "summary": "Q",
                        "utterance_indices": [0],
                        "split_anchor_sentence_idx": None,
                        "intent": "other",
                    },
                    "answer": {
                        "summary": "A",
                        "utterance_indices": [],
                        "split_anchor_sentence_idx": None,
                    },
                }
            ]
        })

        result = _extract_pairs_from_response(content, seg, layout, {})
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
                        "utterance_indices": [0],
                        "split_anchor_sentence_idx": None,
                        "intent": "fact_check",
                    },
                    "answer": {
                        "summary": "- 回答要旨",
                        "utterance_indices": [1],
                        "split_anchor_sentence_idx": None,
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
            assert pair.question.full_text
            assert pair.answer.full_text
