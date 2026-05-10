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
    _SegmentLayout,
    _assemble_full_text_for_pair,
    _assign_follow_up_ids,
    _build_utterance_map,
    _collect_known_speaker_names,
    _compute_segment_layout,
    _compute_share_boundaries,
    _extract_pairs_from_response,
    _fix_boundary_mispairs,
    _fuzzy_lookup,
    _has_chamber_mismatch,
    _has_placeholder_header,
    _shift_video_url_time,
    _split_sentences,
    _strip_leading_questioner_label,
    _strip_leading_speaker_label,
    _strip_pure_label_lines,
    _strip_trailing_speaker_label,
    _validate_summary_person_refs,
    build_summary_related_laws,
    generate_key_commitments,
    generate_qa_pairs,
    generate_session_summary,
    generate_topics_and_key_topics,
    generate_topics_without_qa,
)


def _build_dummy_layout(
    n_utts: int,
    sentences_per_utt: int = 1,
) -> _SegmentLayout:
    """テスト用の簡易レイアウト。utt × sentences_per_utt の文を生成する。"""
    per_utt = [
        [f"u{u}_s{s}." for s in range(sentences_per_utt)]
        for u in range(n_utts)
    ]
    starts: list[int] = []
    cur = 0
    for sents in per_utt:
        starts.append(cur)
        cur += len(sents)
    return _SegmentLayout(
        per_utt_sentences=per_utt,
        utt_global_starts=starts,
        total_sentences=cur,
        is_long_utt=[False] * n_utts,
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
        layout = _build_dummy_layout(n_utts=1)
        assert _compute_share_boundaries([], "q", layout) == []

    def test_no_anchors_all_none_single_sentence_head(self) -> None:
        """head utterance が 1 sentence しか無ければ PR28 の均等分割は走らず None のまま。"""
        # head=5 だが utt 5 が 1 文しかない (n_sent < 2) ので分割不能
        layout = _build_dummy_layout(n_utts=6, sentences_per_utt=1)
        pairs = [self._pair(q_uidx=[5]), self._pair(q_uidx=[5])]
        assert _compute_share_boundaries(pairs, "q", layout) == [None, None]

    def test_single_pair_with_anchor_unshared(self) -> None:
        """anchor 付きでも他に共有相手がいなければ boundary は None。"""
        layout = _build_dummy_layout(n_utts=6)
        pairs = [self._pair(q_uidx=[5], q_anchor=3)]
        assert _compute_share_boundaries(pairs, "q", layout) == [None]

    def test_two_pairs_share_head_boundaries_in_anchor_order(self) -> None:
        """同じ head を共有する 2 ペアは anchor 昇順で次の anchor が boundary。最後は None。"""
        layout = _build_dummy_layout(n_utts=6, sentences_per_utt=200)
        pairs = [
            self._pair(q_uidx=[5], q_anchor=120),
            self._pair(q_uidx=[5], q_anchor=145),
        ]
        assert _compute_share_boundaries(pairs, "q", layout) == [145, None]

    def test_three_pairs_share_head_unsorted_input(self) -> None:
        """LLM 出力が anchor 順でなくても正しく境界を割り当てる。"""
        layout = _build_dummy_layout(n_utts=6, sentences_per_utt=300)
        pairs = [
            self._pair(q_uidx=[5], q_anchor=200),  # 後半
            self._pair(q_uidx=[5], q_anchor=100),  # 前半
            self._pair(q_uidx=[5], q_anchor=150),  # 中央
        ]
        assert _compute_share_boundaries(pairs, "q", layout) == [None, 150, 200]

    def test_q_and_a_independent(self) -> None:
        """q 側の共有は a 側に影響しない (a 側は別 utt なので推定対象外)。"""
        layout = _build_dummy_layout(n_utts=9, sentences_per_utt=50)
        pairs = [
            self._pair(q_uidx=[5], q_anchor=10, a_uidx=[7]),
            self._pair(q_uidx=[5], q_anchor=20, a_uidx=[8]),
        ]
        assert _compute_share_boundaries(pairs, "q", layout) == [20, None]
        # a 側は別 utt 7, 8 — 共有なし → None
        assert _compute_share_boundaries(pairs, "a", layout) == [None, None]

    def test_anchor_none_filled_by_pr28_inference(self) -> None:
        """PR28: anchor=None のペアは前後 explicit anchor の中点で補完される。"""
        # 1 utt × 100 sentences、g_start=0 → anchors 10, ?, 30 が範囲内
        layout = _build_dummy_layout(n_utts=1, sentences_per_utt=100)
        pairs = [
            self._pair(q_uidx=[0], q_anchor=10),
            self._pair(q_uidx=[0], q_anchor=None),
            self._pair(q_uidx=[0], q_anchor=30),
        ]
        # 補完後 anchors: [10, 20, 30] → 境界: [20, 30, None]
        assert _compute_share_boundaries(pairs, "q", layout) == [20, 30, None]

    def test_different_heads_no_sharing(self) -> None:
        """別 utterance を head にもつペア同士は共有しない。"""
        layout = _build_dummy_layout(n_utts=8, sentences_per_utt=50)
        pairs = [
            self._pair(q_uidx=[5], q_anchor=10),
            self._pair(q_uidx=[6], q_anchor=20),
        ]
        assert _compute_share_boundaries(pairs, "q", layout) == [None, None]


class TestPR28AnchorInference:
    """PR28: 同一 head utterance を共有するペアの anchor 自動推定。

    F2 56176 で 9 ペア全て q.full_text 完全重複していた事象の再発防止。
    """

    def _pair(
        self,
        q_uidx: list[int] | None = None,
        q_anchor: int | None = None,
    ) -> dict[str, object]:
        return {
            "q_uidx": q_uidx or [],
            "q_anchor": q_anchor,
            "a_uidx": [],
            "a_anchor": None,
        }

    def test_all_null_anchors_evenly_distributed(self) -> None:
        """全ペア anchor=None かつ複数共有 → 均等分割で anchor 推定。"""
        # head=0, n_sent=8, n_pairs=4 → local_anchor = 0, 2, 4, 6 (g_start=0)
        layout = _build_dummy_layout(n_utts=1, sentences_per_utt=8)
        pairs = [self._pair(q_uidx=[0]) for _ in range(4)]
        boundaries = _compute_share_boundaries(pairs, "q", layout)
        # 推定後 anchors: [0, 2, 4, 6] → 境界: [2, 4, 6, None]
        assert boundaries == [2, 4, 6, None]

    def test_inference_skipped_for_single_pair_head(self) -> None:
        """同 head を共有するペアが 1 件しか無ければ推定は走らない (boundary=None)。"""
        layout = _build_dummy_layout(n_utts=2, sentences_per_utt=8)
        pairs = [
            self._pair(q_uidx=[0]),
            self._pair(q_uidx=[1]),  # 別 head
        ]
        assert _compute_share_boundaries(pairs, "q", layout) == [None, None]

    def test_inference_skipped_when_head_has_one_sentence(self) -> None:
        """head utterance が 1 文しか無ければ分割不能 → 推定スキップ。"""
        layout = _build_dummy_layout(n_utts=1, sentences_per_utt=1)
        pairs = [self._pair(q_uidx=[0]) for _ in range(3)]
        assert _compute_share_boundaries(pairs, "q", layout) == [None, None, None]

    def test_pr28_e2e_avoids_full_text_duplication(self) -> None:
        """E2E: 56176 を再現する 4 ペア (全 anchor null、長文 1 utt 共有) で
        full_text が完全重複しないことを確認。
        """
        # 6 文 × 1 utt の質問 utt + 1 utt の答弁
        question_text = "".join(f"質問文{i}。" for i in range(6))
        seg = SegmentUtterances(
            segment_index=10,
            segment_speaker="X",
            segment_affiliation="X党",
            start_seconds=0.0,
            video_url="https://example.com/?time=0.0",
            utterances=[
                Utterance(speaker="X", role="質疑者", text=question_text),
                Utterance(speaker="A", role="答弁者", text="お答えいたします。具体的に対応してまいります。"),
            ],
        )
        response = json.dumps({
            "pairs": [
                {
                    "topic": f"トピック{i}",
                    "question": {
                        "utterance_indices": [0],
                        "split_anchor_sentence_idx": None,
                        "summary": f"- 質問{i}",
                        "intent": "information_request",
                    },
                    "answer": {
                        "utterance_indices": [1],
                        "split_anchor_sentence_idx": None,
                        "summary": f"- 回答{i}",
                    },
                }
                for i in range(4)
            ]
        })
        layout = _compute_segment_layout(seg)
        pairs = _extract_pairs_from_response(response, seg, layout, {})
        assert len(pairs) == 4
        # 4 ペアの question.full_text が全て同一になっていなければ OK
        q_texts = [p.question.full_text for p in pairs]
        assert len(set(q_texts)) > 1, (
            f"full_text duplicated across pairs: {q_texts}"
        )


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
                Utterance(speaker="質問者", role="質疑者", text="少子化対策の財源確保と経済安全保障について政府の見解をまとめて伺います。"),
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

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
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

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
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

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
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
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
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
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
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
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
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
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
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
                Utterance(speaker="テスト太郎", role="質疑者", text="質問です。高額療養費制度の見直しについて政府の見解を伺います。"),
                Utterance(speaker="テスト次郎", role="答弁者", text="お答えします。現行制度を維持しつつ次期改正の検討課題として対応してまいります。"),
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

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
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

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
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

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
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

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                result = _generate_qa_for_segment(segment, "context", {})

        assert len(result) == 1
        assert result[0].topic == "テスト"


class TestEmptyQuestionDrop:
    """PR10/§2.10: q_full_text が空かつ q_uidx が空のペアは drop される。"""

    def test_drops_pair_with_empty_question_and_no_indices(self) -> None:
        seg = SegmentUtterances(
            segment_index=0,
            segment_speaker="質問太郎",
            segment_affiliation="チームみらい",
            start_seconds=0.0,
            video_url="",
            utterances=[
                Utterance(speaker="質問太郎", role="質疑者", text="質問本文。"),
                Utterance(
                    speaker="答弁次郎",
                    role="答弁者",
                    text="お答えします。十分長い回答です。" + "x" * 50,
                ),
            ],
        )
        layout = _compute_segment_layout(seg)
        content = json.dumps(
            {
                "pairs": [
                    {
                        "topic": "ダミー",
                        "question": {
                            "summary": "Q",
                            "utterance_indices": [],
                            "split_anchor_sentence_idx": None,
                            "intent": "other",
                        },
                        "answer": {
                            "summary": "A",
                            "utterance_indices": [1],
                            "split_anchor_sentence_idx": None,
                        },
                    }
                ]
            }
        )
        result = _extract_pairs_from_response(content, seg, layout, {})
        assert result == []

    def test_keeps_pair_with_question_indices(self) -> None:
        """質問 utterance_indices が指定されていれば q_full は生成され drop されない。"""
        seg = SegmentUtterances(
            segment_index=0,
            segment_speaker="質問太郎",
            segment_affiliation="チームみらい",
            start_seconds=0.0,
            video_url="",
            utterances=[
                Utterance(speaker="質問太郎", role="質疑者", text="少子化対策の財源確保について政府の具体的見解をお聞かせください。"),
                Utterance(
                    speaker="答弁次郎",
                    role="答弁者",
                    text="十分に長い回答本文です。" + "x" * 50,
                ),
            ],
        )
        layout = _compute_segment_layout(seg)
        content = json.dumps(
            {
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
                            "utterance_indices": [1],
                            "split_anchor_sentence_idx": None,
                        },
                    }
                ]
            }
        )
        result = _extract_pairs_from_response(content, seg, layout, {})
        assert len(result) == 1
        assert result[0].question.full_text


class TestOutOfRangeIndicesWarning:
    """PR10/§2.10: 範囲外 utterance_indices の比率を計測する。"""

    def test_high_oor_ratio_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        seg = SegmentUtterances(
            segment_index=5,
            segment_speaker="質問太郎",
            segment_affiliation="チームみらい",
            start_seconds=0.0,
            video_url="",
            utterances=[
                Utterance(speaker="質問太郎", role="質疑者", text="質問本文。"),
                Utterance(
                    speaker="答弁次郎",
                    role="答弁者",
                    text="長い回答本文です。" + "y" * 50,
                ),
            ],
        )
        layout = _compute_segment_layout(seg)
        # 4 indices, 3 of which are out of range (>=2)
        content = json.dumps(
            {
                "pairs": [
                    {
                        "topic": "T",
                        "question": {
                            "summary": "Q",
                            "utterance_indices": [0, 99],
                            "split_anchor_sentence_idx": None,
                            "intent": "other",
                        },
                        "answer": {
                            "summary": "A",
                            "utterance_indices": [88, 77],
                            "split_anchor_sentence_idx": None,
                        },
                    }
                ]
            }
        )
        with caplog.at_level(logging.WARNING, logger="src.structurer"):
            _extract_pairs_from_response(content, seg, layout, {})

        warnings = [
            r for r in caplog.records if "out of range" in r.getMessage()
        ]
        assert warnings, "expected an out-of-range warning"
        assert "Segment 5" in warnings[0].getMessage()

    def test_low_oor_ratio_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        seg = SegmentUtterances(
            segment_index=2,
            segment_speaker="質問太郎",
            segment_affiliation="チームみらい",
            start_seconds=0.0,
            video_url="",
            utterances=[
                Utterance(speaker="質問太郎", role="質疑者", text="質問本文。"),
                Utterance(
                    speaker="答弁次郎",
                    role="答弁者",
                    text="長い回答本文です。" + "y" * 50,
                ),
            ],
        )
        layout = _compute_segment_layout(seg)
        # 4 indices, all in range
        content = json.dumps(
            {
                "pairs": [
                    {
                        "topic": "T",
                        "question": {
                            "summary": "Q",
                            "utterance_indices": [0],
                            "split_anchor_sentence_idx": None,
                            "intent": "other",
                        },
                        "answer": {
                            "summary": "A",
                            "utterance_indices": [1],
                            "split_anchor_sentence_idx": None,
                        },
                    }
                ]
            }
        )
        with caplog.at_level(logging.WARNING, logger="src.structurer"):
            _extract_pairs_from_response(content, seg, layout, {})

        warnings = [
            r for r in caplog.records if "out of range" in r.getMessage()
        ]
        assert not warnings


class TestGenerateTopicsWithoutQA:
    """PR10/PR11/§2.10: utterances から直接 topics + key_topics を生成する。"""

    def _make_utterances(self) -> UtterancesOutput:
        return UtterancesOutput(
            segments=[
                SegmentUtterances(
                    segment_index=0,
                    segment_speaker="高市早苗",
                    segment_affiliation="自由民主党",
                    start_seconds=0.0,
                    video_url="",
                    utterances=[
                        Utterance(
                            speaker="高市早苗",
                            role="答弁者",
                            text="経済成長と財政運営について申し上げます。",
                        ),
                    ],
                ),
            ]
        )

    def test_returns_topics_with_empty_qa_ids(self) -> None:
        utterances = self._make_utterances()
        mock_data = {
            "topics": [
                {
                    "name": "経済政策",
                    "description": "成長戦略と財政再建",
                    "related_speakers": ["高市早苗"],
                },
                {
                    "name": "外交政策",
                    "description": "同盟関係の強化",
                    "related_speakers": ["高市早苗"],
                },
            ],
            "key_topics": ["経済政策"],
        }

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = (
                _make_mock_llm_response(mock_data)
            )
            mock_factory.return_value = mock_client
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                topics, key_topics = generate_topics_without_qa(utterances)

        assert isinstance(topics, TopicsOutput)
        assert len(topics.topics) == 2
        # related_qa_ids は常に空 (QA が存在しないため)
        assert all(t.related_qa_ids == [] for t in topics.topics)
        assert key_topics == ["経済政策"]

    def test_drops_unknown_key_topic(self) -> None:
        utterances = self._make_utterances()
        mock_data = {
            "topics": [
                {
                    "name": "経済政策",
                    "description": "...",
                    "related_speakers": [],
                },
            ],
            "key_topics": ["経済政策", "存在しないトピック"],
        }

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = (
                _make_mock_llm_response(mock_data)
            )
            mock_factory.return_value = mock_client
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                topics, key_topics = generate_topics_without_qa(utterances)

        assert key_topics == ["経済政策"]

    def test_empty_utterances_returns_empty(self) -> None:
        empty = UtterancesOutput(segments=[])
        with patch("src.structurer._get_client") as mock_factory:
            topics, key_topics = generate_topics_without_qa(empty)

        assert topics.topics == []
        assert key_topics == []
        mock_factory.assert_not_called()


class TestValidateSummaryPersonRefs:
    """PR12: summary_qa_divergence 検出 — qa_pairs にない人名を抽出する。"""

    def test_known_speaker_passes(self) -> None:
        qa_pairs = _make_qa_pairs("qa_001")
        # _make_qa_pairs は question.speaker=古川あおい / answer.speaker=上野賢一郎
        summary = "上野大臣が古川議員の質問に答弁した。"
        assert _validate_summary_person_refs(summary, qa_pairs) == []

    def test_unknown_minister_detected(self) -> None:
        qa_pairs = _make_qa_pairs("qa_001")
        summary = "高市総理が答弁し、片山大臣も補足した。"
        unknown = _validate_summary_person_refs(summary, qa_pairs)
        # 「上野賢一郎」「古川あおい」とは無関係 → 高市・片山 両方 unknown
        assert "高市" in unknown
        assert "片山" in unknown

    def test_substring_match_is_known(self) -> None:
        """qa_pairs の speaker が長い実名でも、要約が surname 単独でも known 扱い。"""
        qa_pairs = _make_qa_pairs("qa_001")
        # answer.speaker = "上野賢一郎"
        summary = "上野大臣が答弁した。"
        assert _validate_summary_person_refs(summary, qa_pairs) == []

    def test_empty_qa_pairs_skips_validation(self) -> None:
        empty = QAPairsOutput(pairs=[])
        summary = "高市総理が所信を述べた。"
        assert _validate_summary_person_refs(summary, empty) == []

    def test_collect_known_speaker_names(self) -> None:
        qa_pairs = _make_qa_pairs("qa_001", "qa_002")
        known = _collect_known_speaker_names(qa_pairs)
        assert "古川あおい" in known
        assert "上野賢一郎" in known


class TestSessionSummaryRetryOnUnknownRefs:
    """PR12: 未知人名検出 → 1 回リトライ → クリーンな要約に置換。"""

    def test_retry_replaces_summary_when_first_has_unknown_ref(self) -> None:
        qa_pairs = _make_qa_pairs("qa_001")
        first_data = {"session_summary": "高市総理が答弁した。"}  # 高市 は qa_pairs に存在しない
        retry_data = {"session_summary": "上野大臣が古川議員の質問に答弁した。"}

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = [
                _make_mock_llm_response(first_data),
                _make_mock_llm_response(retry_data),
            ]
            mock_factory.return_value = mock_client
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                result = generate_session_summary(qa_pairs)

        assert result == "上野大臣が古川議員の質問に答弁した。"
        assert mock_client.chat.completions.create.call_count == 2

    def test_no_retry_when_summary_clean(self) -> None:
        qa_pairs = _make_qa_pairs("qa_001")
        clean_data = {"session_summary": "上野大臣の答弁が中心であった。"}

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(clean_data)
            mock_factory.return_value = mock_client
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                result = generate_session_summary(qa_pairs)

        assert result == "上野大臣の答弁が中心であった。"
        assert mock_client.chat.completions.create.call_count == 1

    def test_retry_kept_even_if_still_unknown(self) -> None:
        """リトライ後も未知人名が残っても、リトライ結果を採用 (warning は出る)。"""
        qa_pairs = _make_qa_pairs("qa_001")
        first_data = {"session_summary": "高市総理が答弁した。"}
        # リトライしても改善せず別の未知人名
        retry_data = {"session_summary": "片山大臣が答弁した。"}

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = [
                _make_mock_llm_response(first_data),
                _make_mock_llm_response(retry_data),
            ]
            mock_factory.return_value = mock_client
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                result = generate_session_summary(qa_pairs)

        # リトライ結果を採用
        assert result == "片山大臣が答弁した。"


class TestKeyCommitmentsSpeakerValidation:
    """PR12: (qa_id, speaker) 整合検証 + 全 drop 時のリトライ。"""

    def test_drops_commitment_with_speaker_mismatch(self) -> None:
        qa_pairs = _make_qa_pairs("qa_001")  # answer.speaker = 上野賢一郎
        mock_data = {
            "key_commitments": [
                {  # speaker matches answer.speaker (substring)
                    "speaker": "上野",
                    "role": "答弁者",
                    "text": "正しい コミット",
                    "topic": "T",
                    "qa_id": "qa_001",
                },
                {  # speaker は qa_001 の回答者と全く違う → drop
                    "speaker": "高市早苗",
                    "role": "答弁者",
                    "text": "誤帰属コミット",
                    "topic": "T",
                    "qa_id": "qa_001",
                },
            ]
        }

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_data)
            mock_factory.return_value = mock_client
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                commitments = generate_key_commitments(qa_pairs)

        assert len(commitments) == 1
        assert commitments[0].speaker == "上野"

    def test_retry_when_all_commitments_dropped(self) -> None:
        """raw が 0 でないのに整合検証で全 drop されたらリトライ。"""
        qa_pairs = _make_qa_pairs("qa_001")
        first_data = {
            "key_commitments": [
                {"speaker": "高市早苗", "role": "総理", "text": "x", "topic": "T", "qa_id": "qa_001"},
            ]
        }
        retry_data = {
            "key_commitments": [
                {"speaker": "上野賢一郎", "role": "答弁者", "text": "正しい", "topic": "T", "qa_id": "qa_001"},
            ]
        }

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = [
                _make_mock_llm_response(first_data),
                _make_mock_llm_response(retry_data),
            ]
            mock_factory.return_value = mock_client
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                commitments = generate_key_commitments(qa_pairs)

        assert len(commitments) == 1
        assert commitments[0].speaker == "上野賢一郎"
        assert mock_client.chat.completions.create.call_count == 2

    def test_no_retry_when_some_commitments_pass(self) -> None:
        """1 件でも valid commitment があればリトライしない。"""
        qa_pairs = _make_qa_pairs("qa_001")
        mock_data = {
            "key_commitments": [
                {"speaker": "上野賢一郎", "role": "答弁者", "text": "ok", "topic": "T", "qa_id": "qa_001"},
                {"speaker": "幽霊", "role": "答弁者", "text": "x", "topic": "T", "qa_id": "qa_999"},
            ]
        }

        with patch("src.structurer._get_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_mock_llm_response(mock_data)
            mock_factory.return_value = mock_client
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                commitments = generate_key_commitments(qa_pairs)

        assert len(commitments) == 1
        assert mock_client.chat.completions.create.call_count == 1


class TestAssignFollowUpIds:
    """PR13: 同一 segment 内で同一質疑者の連続ペアを follow_up_ids で連鎖。"""

    @staticmethod
    def _pair(pid: str, segment_index: int, question_speaker: str) -> "QAPair":
        from src.models import AnswerDetail, QAPair, QuestionDetail
        return QAPair(
            id=pid,
            segment_index=segment_index,
            topic="T",
            question=QuestionDetail(
                speaker=question_speaker,
                party="X",
                summary="",
                full_text="",
                intent="information_request",
            ),
            answer=AnswerDetail(speaker="A", role="答弁者", summary="", full_text="x" * 50),
            video_url="https://example.com",
        )

    def test_chains_same_speaker_in_same_segment(self) -> None:
        pairs = [
            self._pair("qa_001", 0, "古川あおい"),
            self._pair("qa_002", 0, "古川あおい"),
            self._pair("qa_003", 0, "古川あおい"),
        ]
        _assign_follow_up_ids(pairs)
        assert pairs[0].follow_up_ids == []
        assert pairs[1].follow_up_ids == ["qa_001"]
        assert pairs[2].follow_up_ids == ["qa_002"]

    def test_does_not_chain_different_segments(self) -> None:
        pairs = [
            self._pair("qa_001", 0, "古川あおい"),
            self._pair("qa_002", 1, "古川あおい"),  # 別 segment
        ]
        _assign_follow_up_ids(pairs)
        assert pairs[1].follow_up_ids == []

    def test_does_not_chain_different_speakers(self) -> None:
        pairs = [
            self._pair("qa_001", 0, "古川あおい"),
            self._pair("qa_002", 0, "別議員"),  # 別 speaker
        ]
        _assign_follow_up_ids(pairs)
        assert pairs[1].follow_up_ids == []

    def test_skips_empty_speaker(self) -> None:
        pairs = [
            self._pair("qa_001", 0, ""),
            self._pair("qa_002", 0, ""),
        ]
        _assign_follow_up_ids(pairs)
        assert pairs[0].follow_up_ids == []
        assert pairs[1].follow_up_ids == []

    def test_interleaved_speakers_chain_separately(self) -> None:
        """同一 segment 内で 2 人の質疑者が交互に発言した場合、各 speaker 内で連鎖。"""
        pairs = [
            self._pair("qa_001", 0, "Aさん"),
            self._pair("qa_002", 0, "Bさん"),
            self._pair("qa_003", 0, "Aさん"),
            self._pair("qa_004", 0, "Bさん"),
        ]
        _assign_follow_up_ids(pairs)
        assert pairs[0].follow_up_ids == []
        assert pairs[1].follow_up_ids == []
        assert pairs[2].follow_up_ids == ["qa_001"]
        assert pairs[3].follow_up_ids == ["qa_002"]

    def test_preserves_existing_follow_up_ids(self) -> None:
        """既存の follow_up_ids が空でなければ前置 (上書きしない)。"""
        pairs = [
            self._pair("qa_001", 0, "古川"),
            self._pair("qa_002", 0, "古川"),
        ]
        pairs[1].follow_up_ids = ["other_001"]
        _assign_follow_up_ids(pairs)
        assert pairs[1].follow_up_ids == ["qa_001", "other_001"]

    def test_does_not_double_add(self) -> None:
        """既存 follow_up_ids に同じ id があれば重複追加しない。"""
        pairs = [
            self._pair("qa_001", 0, "古川"),
            self._pair("qa_002", 0, "古川"),
        ]
        pairs[1].follow_up_ids = ["qa_001"]
        _assign_follow_up_ids(pairs)
        assert pairs[1].follow_up_ids == ["qa_001"]


class TestPR21SummaryHeaderValidation:
    """PR21: summary 冒頭のプレースホルダ・院取り違え検出。"""

    def test_placeholder_committee_unknown(self) -> None:
        assert _has_placeholder_header("衆議院（委員会名不明）において、…")
        assert _has_placeholder_header("委員会名不明の場で…")

    def test_placeholder_marubatsu(self) -> None:
        assert _has_placeholder_header("〇〇委員会において、…")
        assert _has_placeholder_header("○○委員会において、…")

    def test_no_placeholder_normal(self) -> None:
        assert not _has_placeholder_header("衆議院内閣委員会において、高額療養費が議論された。")

    def test_chamber_mismatch_detected(self) -> None:
        # 期待: 参議院、summary は「衆議院」のみ → 取り違え
        assert _has_chamber_mismatch("衆議院予算委員会において、…", "参議院")
        # 逆向きも検知
        assert _has_chamber_mismatch("衆議院内閣委員会では、…", "参議院")

    def test_chamber_mismatch_when_both_present_is_ok(self) -> None:
        # 「参議院」が含まれていれば、たまたま「衆議院」も含まれていてもミスマッチではない
        assert not _has_chamber_mismatch("参議院の予算委員会と衆議院の合同で…", "参議院")

    def test_chamber_mismatch_when_expected_present(self) -> None:
        assert not _has_chamber_mismatch("衆議院内閣委員会において、…", "衆議院")

    def test_chamber_mismatch_empty_expected(self) -> None:
        # expected が空文字なら検出しない (情報なし)
        assert not _has_chamber_mismatch("衆議院○○において、…", "")


class TestPR23VideoUrlShift:
    """PR23: video_url の time / hash 部分の差し替え。"""

    def test_shift_shugiin_time_param(self) -> None:
        url = "https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=56176&time=1230.0"
        result = _shift_video_url_time(url, 1500.5)
        assert "time=1500.5" in result
        assert "deli_id=56176" in result
        assert "time=1230.0" not in result

    def test_shift_sangiin_hash(self) -> None:
        url = "https://www.webtv.sangiin.go.jp/webtv/detail.php?sid=8985#100.0"
        result = _shift_video_url_time(url, 250.7)
        assert result.endswith("#250.7")
        assert "sid=8985" in result

    def test_shift_negative_clamped_to_zero(self) -> None:
        url = "https://example.com/?time=10.0"
        result = _shift_video_url_time(url, -5.0)
        assert "time=0.0" in result

    def test_shift_no_time_pattern_returns_unchanged(self) -> None:
        url = "https://example.com/no-time-param"
        assert _shift_video_url_time(url, 100.0) == url

    def test_shift_empty_url(self) -> None:
        assert _shift_video_url_time("", 100.0) == ""


class TestPR23PerPairVideoUrl:
    """PR23: _extract_pairs_from_response が pair の video_url を utterance 位置で
    補正することを確認 (segment 起点ではなく、質問 utterance 位置を反映)。
    """

    def test_per_pair_video_url_offset(self) -> None:
        # 質問が U2 (前に長い utt が 2 つ) → segment.start_seconds + offset
        seg = SegmentUtterances(
            segment_index=3,
            segment_speaker="議長",
            segment_affiliation="衆議院議長",
            start_seconds=600.0,
            video_url="https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=56176&time=600.0",
            utterances=[
                Utterance(speaker="議長", role="委員長", text="開会します。" * 20),  # ~120 chars
                Utterance(speaker="X", role="質疑者", text="質疑前置き。" * 20),  # ~120 chars
                Utterance(speaker="Y", role="質疑者", text="主たる質疑文。" * 5),
                Utterance(speaker="Z", role="答弁者", text="お答えします。回答内容です。"),
            ],
        )
        layout = _compute_segment_layout(seg)
        response = json.dumps({
            "pairs": [
                {
                    "topic": "T",
                    "question": {
                        "utterance_indices": [2],
                        "split_anchor_sentence_idx": None,
                        "summary": "- Q",
                        "intent": "information_request",
                    },
                    "answer": {
                        "utterance_indices": [3],
                        "split_anchor_sentence_idx": None,
                        "summary": "- A",
                    },
                }
            ]
        })
        pairs = _extract_pairs_from_response(response, seg, layout, {})
        assert len(pairs) == 1
        # video_url は seg.start_seconds (600.0) より大きい時刻になっているはず
        # 240 chars before utt 2, 約 240/4 = 60 秒 のオフセット → time=660.0 付近
        url = pairs[0].video_url
        assert "time=600.0" not in url  # 補正されているはず
        # 補正後 time= は 660 秒前後
        import re
        m = re.search(r"time=([\d.]+)", url)
        assert m
        new_time = float(m.group(1))
        assert 640.0 <= new_time <= 700.0, f"unexpected time: {new_time}"

    def test_pr23_1_anchor_position_adds_offset(self) -> None:
        """PR23.1: 同一 head_utt 共有のペアでも anchor 位置が異なれば URL も異なる。

        56176 のような代表質問パターンを再現: 1 質問者の長文 utterance に
        9 個の Q が含まれ、PR28 の anchor 自動推定で各 Q が別 sentence index に
        紐付く → URL も別時刻を指す。
        """
        # 1 質疑者発言が 6 文に分かれる長文 utterance
        long_q_text = "".join(f"質問文{i}。" for i in range(6))  # 6 sentences
        seg = SegmentUtterances(
            segment_index=5,
            segment_speaker="X",
            segment_affiliation="X党",
            start_seconds=600.0,
            video_url="https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=99999&time=600.0",
            utterances=[
                Utterance(speaker="X", role="質疑者", text=long_q_text),
                Utterance(speaker="A", role="答弁者", text="お答えします。具体的に対応してまいります。"),
            ],
        )
        # 4 ペアが同一 head_utt=[0] を共有、anchor は全 null (PR28 が均等推定)
        response = json.dumps({
            "pairs": [
                {
                    "topic": f"トピック{i}",
                    "question": {
                        "utterance_indices": [0],
                        "split_anchor_sentence_idx": None,
                        "summary": f"- 質問{i}",
                        "intent": "information_request",
                    },
                    "answer": {
                        "utterance_indices": [1],
                        "split_anchor_sentence_idx": None,
                        "summary": f"- 回答{i}",
                    },
                }
                for i in range(4)
            ]
        })
        layout = _compute_segment_layout(seg)
        pairs = _extract_pairs_from_response(response, seg, layout, {})
        assert len(pairs) == 4
        urls = [p.video_url for p in pairs]
        # 4 ペア全部 unique であることを期待 (anchor 0/1/3/4 → time 異なる)
        assert len(set(urls)) >= 3, f"PR23.1 should differentiate URLs by anchor position: {urls}"

    def test_per_pair_video_url_unchanged_when_first_utterance(self) -> None:
        """質問が U0 → offset=0 → seg.video_url のまま。"""
        seg = SegmentUtterances(
            segment_index=0,
            segment_speaker="X",
            segment_affiliation="X党",
            start_seconds=100.0,
            video_url="https://example.com/?time=100.0",
            utterances=[
                Utterance(speaker="X", role="質疑者", text="少子化対策の財源確保について政府の具体的な考え方を伺います。"),
                Utterance(speaker="Y", role="答弁者", text="答え。だいぶ長い回答です。こども・子育て支援金制度で対応してまいります。"),
            ],
        )
        layout = _compute_segment_layout(seg)
        response = json.dumps({
            "pairs": [
                {
                    "topic": "T",
                    "question": {
                        "utterance_indices": [0],
                        "split_anchor_sentence_idx": None,
                        "summary": "- q",
                        "intent": "information_request",
                    },
                    "answer": {
                        "utterance_indices": [1],
                        "split_anchor_sentence_idx": None,
                        "summary": "- a",
                    },
                }
            ]
        })
        pairs = _extract_pairs_from_response(response, seg, layout, {})
        assert pairs[0].video_url == seg.video_url


class TestPR39ShortQuestionDrop:
    """PR39: question.full_text が短すぎるペアを drop する。"""

    def _make_seg(self) -> SegmentUtterances:
        return SegmentUtterances(
            segment_index=0,
            segment_speaker="田中",
            segment_affiliation="立憲民主党",
            start_seconds=0.0,
            video_url="https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=99&time=0.0",
            utterances=[
                Utterance(speaker="田中", role="質疑者",
                          text="おはようございます。"),
                Utterance(speaker="大臣", role="答弁者",
                          text="お答えいたします。高額療養費制度の見直しについては次期改正で対応します。"),
                Utterance(speaker="田中", role="質疑者",
                          text="次に、少子化対策について政府の見解を伺います。具体的な財源確保の方針を教えてください。"),
                Utterance(speaker="大臣", role="答弁者",
                          text="少子化対策財源については、こども・子育て支援金制度を活用し、医療保険料に上乗せする形で確保してまいります。"),
            ],
        )

    def test_drops_short_question(self) -> None:
        seg = self._make_seg()
        layout = _compute_segment_layout(seg)
        response = json.dumps({
            "pairs": [
                {
                    "topic": "挨拶",
                    "question": {"summary": "- 挨拶", "utterance_indices": [0],
                                 "split_anchor_sentence_idx": None, "intent": "other"},
                    "answer": {"summary": "- 回答", "utterance_indices": [1],
                               "split_anchor_sentence_idx": None},
                },
                {
                    "topic": "少子化対策",
                    "question": {"summary": "- 財源方針", "utterance_indices": [2],
                                 "split_anchor_sentence_idx": None, "intent": "information_request"},
                    "answer": {"summary": "- 支援金制度", "utterance_indices": [3],
                               "split_anchor_sentence_idx": None},
                },
            ]
        })
        pairs = _extract_pairs_from_response(response, seg, layout, {})
        # U0 "おはようございます。" は 10 文字 < 30 → drop
        # U2 "次に、少子化対策について..." は 30 文字以上 → kept
        assert len(pairs) == 1
        assert "少子化" in pairs[0].question.full_text

    def test_keeps_adequate_question(self) -> None:
        seg = self._make_seg()
        layout = _compute_segment_layout(seg)
        response = json.dumps({
            "pairs": [
                {
                    "topic": "少子化",
                    "question": {"summary": "- 財源", "utterance_indices": [2],
                                 "split_anchor_sentence_idx": None, "intent": "information_request"},
                    "answer": {"summary": "- 支援金", "utterance_indices": [3],
                               "split_anchor_sentence_idx": None},
                }
            ]
        })
        pairs = _extract_pairs_from_response(response, seg, layout, {})
        assert len(pairs) == 1


class TestPR41BoundaryMispairs:
    """PR41: question.speaker が segment_speaker と不一致の場合、segment_index/video_url を補正。"""

    def _make_pair(self, seg_idx: int, q_speaker: str, video_url: str) -> "QAPair":
        from src.models import AnswerDetail, QAPair, QuestionDetail
        return QAPair(
            id="qa_001",
            segment_index=seg_idx,
            topic="テスト",
            question=QuestionDetail(
                speaker=q_speaker, party="", summary="- テスト",
                full_text="これは質問のテキストです。" * 3,
                intent="other",
            ),
            answer=AnswerDetail(
                speaker="大臣", role="答弁者", summary="- 答弁",
                full_text="お答えいたします。" * 3,
            ),
            video_url=video_url,
        )

    def test_fixes_mispaired_segment(self) -> None:
        seg0 = SegmentUtterances(
            segment_index=0, segment_speaker="古川",
            segment_affiliation="自由民主党", start_seconds=0.0,
            video_url="https://example.com/?time=0.0",
            utterances=[],
        )
        seg1 = SegmentUtterances(
            segment_index=1, segment_speaker="田中",
            segment_affiliation="立憲民主党", start_seconds=500.0,
            video_url="https://example.com/?time=500.0",
            utterances=[],
        )
        # pair は segment_index=0 (古川) だが question.speaker="田中" (segment 1 の話者)
        pair = self._make_pair(0, "田中", "https://example.com/?time=0.0")
        _fix_boundary_mispairs([pair], [seg0, seg1])
        assert pair.segment_index == 1
        assert pair.video_url == "https://example.com/?time=500.0"

    def test_no_change_when_speaker_matches(self) -> None:
        seg0 = SegmentUtterances(
            segment_index=0, segment_speaker="古川",
            segment_affiliation="自由民主党", start_seconds=0.0,
            video_url="https://example.com/?time=0.0",
            utterances=[],
        )
        pair = self._make_pair(0, "古川", "https://example.com/?time=0.0")
        _fix_boundary_mispairs([pair], [seg0])
        assert pair.segment_index == 0
        assert "time=0.0" in pair.video_url

    def test_no_change_when_speaker_not_in_any_segment(self) -> None:
        seg0 = SegmentUtterances(
            segment_index=0, segment_speaker="古川",
            segment_affiliation="自由民主党", start_seconds=0.0,
            video_url="https://example.com/?time=0.0",
            utterances=[],
        )
        pair = self._make_pair(0, "鈴木", "https://example.com/?time=0.0")
        _fix_boundary_mispairs([pair], [seg0])
        assert pair.segment_index == 0  # 対応 segment なければ変更しない


class TestPR43TrailingLabelStrip:
    """PR43: answer.full_text 末尾の次発言者ラベル除去。"""

    def test_strips_name_with_party(self) -> None:
        """「\n森本真治（立憲民主・無所属）」を除去する。"""
        text = "お答えいたします。具体的な対策を講じてまいります。\n森本真治（立憲民主・無所属）"
        result = _strip_trailing_speaker_label(text)
        assert result == "お答えいたします。具体的な対策を講じてまいります。"

    def test_strips_chair_label(self) -> None:
        """「\n藤川政人委員長」を除去する。"""
        text = "以上でございます。詳細については資料を御参照ください。\n藤川政人委員長"
        result = _strip_trailing_speaker_label(text)
        assert result == "以上でございます。詳細については資料を御参照ください。"

    def test_strips_multiple_trailing_newlines(self) -> None:
        """複数の改行 + ラベルを除去する。"""
        text = "御質問にお答えします。\n\n田中一郎"
        result = _strip_trailing_speaker_label(text)
        assert "田中一郎" not in result

    def test_no_change_for_normal_text(self) -> None:
        """末尾がラベル形式でない場合は変更しない。"""
        text = "御質問にお答えします。エネルギー政策について引き続き検討してまいります。"
        result = _strip_trailing_speaker_label(text)
        assert result == text

    def test_no_change_for_empty(self) -> None:
        assert _strip_trailing_speaker_label("") == ""

    def test_no_false_positive_for_name_mid_text(self) -> None:
        """文中の名前は除去しない（末尾のみ対象）。"""
        text = "田中一郎委員長の御指摘のとおりでございます。早急に対応いたします。"
        result = _strip_trailing_speaker_label(text)
        assert result == text

    def test_strips_kun_suffix_with_period(self) -> None:
        """PR43 enhanced: 「\n小里君。」パターンを除去する。"""
        text = "御指摘の点については早急に対応いたします。\n小里君。"
        result = _strip_trailing_speaker_label(text)
        assert result == "御指摘の点については早急に対応いたします。"

    def test_strips_kun_with_longer_name(self) -> None:
        """PR43 enhanced: 「\n牧野たかお君。」（ひらがな含む）を除去する。"""
        text = "引き続き取り組んでまいります。\n牧野たかお君。"
        result = _strip_trailing_speaker_label(text)
        assert result == "引き続き取り組んでまいります。"

    def test_strips_stacked_labels(self) -> None:
        """PR43 enhanced: 複数ラベルが積み重なった場合も最大3回適用で除去する。"""
        text = "具体的に説明いたします。\n藤川政人委員長\n森本真治君。"
        result = _strip_trailing_speaker_label(text)
        assert "委員長" not in result
        assert "森本真治" not in result

    def test_strips_inline_kun_no_newline(self) -> None:
        """PR43 v2: 改行なし+君。パターン（同一行末）を除去する。"""
        text = "引き続き取り組んでまいります。山内君。"
        result = _strip_trailing_speaker_label(text)
        assert result == "引き続き取り組んでまいります。"

    def test_strips_inline_party_no_newline(self) -> None:
        """PR43 v2: 改行なし+（党名）パターンを除去する。"""
        text = "対応してまいります。三原じゅん子（自由民主党）。"
        result = _strip_trailing_speaker_label(text)
        assert result == "対応してまいります。"

    def test_strips_inline_chair_no_newline(self) -> None:
        """PR43 v2: 改行なし+委員長パターンを除去する。"""
        text = "以上でございます。藤川政人委員長。"
        result = _strip_trailing_speaker_label(text)
        assert result == "以上でございます。"

    def test_no_false_positive_sentence_ending(self) -> None:
        """正常な文末（「ございます。」等）は除去しない。"""
        text = "取り組んでまいります。早急に対応してございます。"
        result = _strip_trailing_speaker_label(text)
        assert result == text


class TestPR43LeadingLabelStrip:
    """PR43 v2: answer.full_text 冒頭の話者ラベル除去。"""

    def test_strips_prime_minister_label(self) -> None:
        """「高市早苗内閣総理大臣。[答弁]」→「[答弁]」"""
        text = "高市早苗内閣総理大臣。御質問にお答えします。具体的な対応を検討してまいります。"
        result = _strip_leading_speaker_label(text)
        assert result == "御質問にお答えします。具体的な対応を検討してまいります。"

    def test_strips_minister_label(self) -> None:
        """「上野賢一郎厚生労働大臣。[答弁]」→「[答弁]」"""
        text = "上野賢一郎厚生労働大臣。この問題については早急に対応いたします。"
        result = _strip_leading_speaker_label(text)
        assert result == "この問題については早急に対応いたします。"

    def test_no_false_positive_question_start(self) -> None:
        """御質問文の冒頭は除去しない。"""
        text = "御質問にお答えします。エネルギー政策については引き続き検討します。"
        result = _strip_leading_speaker_label(text)
        assert result == text

    def test_no_false_positive_plain_content(self) -> None:
        """通常の答弁冒頭は除去しない。"""
        text = "今朝5時23分頃に発生した地震について申し上げます。"
        result = _strip_leading_speaker_label(text)
        assert result == text

    def test_strips_fullwidth_colon_delimiter(self) -> None:
        """「名前役職：[答弁]」形式も除去する。"""
        text = "高市早苗内閣総理大臣：まず基本的な考え方を申し上げます。"
        result = _strip_leading_speaker_label(text)
        assert result == "まず基本的な考え方を申し上げます。"

    def test_strips_sankounin_label(self) -> None:
        """PR43 v3: 参考人ラベルも除去する。"""
        text = "澤田純参考人。本日は貴重な機会をいただきありがとうございます。"
        result = _strip_leading_speaker_label(text)
        assert result == "本日は貴重な機会をいただきありがとうございます。"


class TestPR46PureLabelLines:
    """PR46: answer.full_text 内の純粋な話者ラベル行除去。"""

    def test_strips_pure_sankounin_line(self) -> None:
        """「\n砂原参考人。\n」の純粋なラベル行を除去する。"""
        text = "本日の問題についてお答えします。\n砂原参考人。\n憲法の規定については複数の解釈があります。"
        result = _strip_pure_label_lines(text)
        assert "砂原参考人。" not in result
        assert "本日の問題についてお答えします。" in result
        assert "憲法の規定については複数の解釈があります。" in result

    def test_strips_minister_label_line(self) -> None:
        """「\n高市早苗内閣総理大臣。\n」行を除去する。"""
        text = "まず最初の御質問にお答えします。\n高市早苗内閣総理大臣。\nその件については早急に対応します。"
        result = _strip_pure_label_lines(text)
        assert "高市早苗内閣総理大臣。" not in result

    def test_preserves_content_lines(self) -> None:
        """コンテンツを含む行は保持する。"""
        text = "砂原参考人によると、この問題は複雑です。\n具体的な対策を検討してまいります。"
        result = _strip_pure_label_lines(text)
        assert result == text

    def test_no_change_for_single_line(self) -> None:
        """改行のない単一行はそのまま返す。"""
        text = "御質問にお答えします。具体的な政策について説明いたします。"
        result = _strip_pure_label_lines(text)
        assert result == text

    def test_strips_multiple_embedded_labels(self) -> None:
        """複数のラベル行を除去する。"""
        text = "答弁します。\n上田参考人。\n憲法審査会の見解です。\n砂原参考人。\n補足意見を申し上げます。"
        result = _strip_pure_label_lines(text)
        assert "上田参考人。" not in result
        assert "砂原参考人。" not in result
        assert "憲法審査会の見解です。" in result
        assert "補足意見を申し上げます。" in result


class TestPR43LeadingQuestionerLabelStrip:
    """PR43 v3: question.full_text 冒頭の質疑者ラベル除去。"""

    def test_strips_name_with_party_colon(self) -> None:
        """「森本真治（立憲民主・無所属）：[質問]」→「[質問]」"""
        text = "森本真治（立憲民主・無所属）：エネルギー政策について伺います。"
        result = _strip_leading_questioner_label(text)
        assert result == "エネルギー政策について伺います。"

    def test_strips_kun_period(self) -> None:
        """「泉房穂君。[質問]」→「[質問]」"""
        text = "泉房穂君。少子化対策について質問します。"
        result = _strip_leading_questioner_label(text)
        assert result == "少子化対策について質問します。"

    def test_no_false_positive_content_start(self) -> None:
        """通常の質問開始（名前+役職なし）は除去しない。"""
        text = "少子化対策の財源確保についてお聞きします。"
        result = _strip_leading_questioner_label(text)
        assert result == text

    def test_no_false_positive_questioner_reference(self) -> None:
        """文中の名前言及（「山田大臣に伺います」等）は除去しない。"""
        text = "山田大臣に伺います。エネルギー価格の高騰についてどのようにお考えでしょうか。"
        result = _strip_leading_questioner_label(text)
        assert result == text


@pytest.mark.integration
class TestStructurerIntegration:
    def test_real_qa_generation(self, sample_utterances: UtterancesOutput) -> None:
        """実際の LLM API でQ&Aペア生成をテストする（結合テスト）。"""
        result = generate_qa_pairs(sample_utterances)
        assert isinstance(result, QAPairsOutput)
        for pair in result.pairs:
            assert pair.question.full_text
            assert pair.answer.full_text
