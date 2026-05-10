"""transcript_corrector の単体テスト (PR7 ループ検出 / §2.5)。"""

from __future__ import annotations

from src.transcript_corrector import _has_repetition_loop


class TestHasRepetitionLoop:
    """同一短文の3回以上反復を検出する。"""

    def test_detects_chair_nomination_loop(self) -> None:
        """「議長＊小寺君。」が3回以上連続するパターンを検出。"""
        text = "議長＊小寺君。" * 100
        assert _has_repetition_loop(text) is True

    def test_detects_youtube_filler_loop(self) -> None:
        """「ご視聴ありがとうございました。」連続を検出。"""
        text = "ご視聴ありがとうございました。" * 5
        assert _has_repetition_loop(text) is True

    def test_detects_speaker_name_loop(self) -> None:
        """「石井啓一議長、石井啓一議長、石井啓一議長」の読点区切りでも検出。"""
        text = "石井啓一議長\n石井啓一議長\n石井啓一議長\n以下省略。"
        assert _has_repetition_loop(text) is True

    def test_two_repeats_not_loop(self) -> None:
        """2回反復は通常の発言の繰り返し強調なのでループ扱いしない。"""
        text = "申し上げます。申し上げます。それは大事だ。"
        assert _has_repetition_loop(text) is False

    def test_normal_text_no_loop(self) -> None:
        """通常文で誤検出しない。"""
        text = (
            "本日はお忙しいところお集まりいただき誠にありがとうございます。"
            "それではただ今より会議を始めます。"
            "まず最初の議題に入りたいと思います。"
        )
        assert _has_repetition_loop(text) is False

    def test_long_phrase_not_a_loop(self) -> None:
        """30文字超の長文反復はループ扱いしない (本物の発言の可能性)。"""
        # 「...」内が31文字以上になるよう構築
        long_phrase = (
            "私はこの社会保障制度の問題について非常に強く深く問題意識を持っております。"
            * 3
        )
        # 31文字を超えていることを確認 (assert で固定)
        first_phrase = long_phrase.split("。")[0]
        assert len(first_phrase) > 30
        assert _has_repetition_loop(long_phrase) is False

    def test_min_repeats_two(self) -> None:
        """min_repeats=2 のときは2連続でも True を返す。"""
        text = "繰り返し。繰り返し。"
        assert _has_repetition_loop(text, min_repeats=2) is True

    def test_short_text_no_loop(self) -> None:
        """文数が min_repeats 未満なら False。"""
        assert _has_repetition_loop("短いね。", min_repeats=3) is False

    def test_empty_string_no_loop(self) -> None:
        """空文字列は False。"""
        assert _has_repetition_loop("") is False

    def test_only_whitespace_phrases_skipped(self) -> None:
        """空白だけの phrase は反復判定の対象外。"""
        text = "\n\n\n\n\n"
        assert _has_repetition_loop(text) is False

    def test_intermittent_loop_not_continuous(self) -> None:
        """非連続反復 (間に他文が挟まる) はループ扱いしない。"""
        text = "ノイズだ。本物の発言。ノイズだ。本物の発言。ノイズだ。"
        assert _has_repetition_loop(text) is False

    def test_question_mark_separator(self) -> None:
        """疑問符でも phrase 区切りとして機能する。"""
        text = "本当ですか？本当ですか？本当ですか？"
        assert _has_repetition_loop(text) is True
