"""src/metadata_enricher.py の単体テスト (PR6, §2.2/2.3)。"""

from __future__ import annotations

import pytest

from src.metadata_enricher import (
    _NOMINATION_PATTERN,
    _build_chair_nomination_map,
    _extract_affiliation_from_name,
    enrich_metadata_from_utterances,
)
from src.models import (
    SegmentUtterances,
    SpeakerInfo,
    Utterance,
    UtterancesOutput,
)


def _mk_utterances(
    rows: list[tuple[str, str, str]],
) -> UtterancesOutput:
    """rows = [(speaker, role, text), ...] を 1 segment 内の utterances にまとめる。"""
    utts = [Utterance(speaker=sp, role=r, text=t) for sp, r, t in rows]
    return UtterancesOutput(
        segments=[
            SegmentUtterances(
                segment_index=0,
                segment_speaker="坂本哲志",
                segment_affiliation="予算委員長",
                start_seconds=0.0,
                video_url="https://example.com/v",
                utterances=utts,
            )
        ]
    )


class TestNominationPattern:
    """_NOMINATION_PATTERN: 委員長指名文からの (役職, 名前) 抽出。"""

    def test_minister_nomination(self) -> None:
        m = _NOMINATION_PATTERN.search("次に厚生労働大臣木原稔君、答弁を求めます。")
        assert m is not None
        assert m.group("title") == "厚生労働大臣"
        assert m.group("name") == "木原稔"

    def test_vice_minister_nomination(self) -> None:
        m = _NOMINATION_PATTERN.search("外務副大臣岩田和親君。")
        assert m is not None
        # 副大臣 が 大臣 より先に試される (長い順)
        assert m.group("title") == "外務副大臣"
        assert m.group("name") == "岩田和親"

    def test_seimukan_nomination(self) -> None:
        m = _NOMINATION_PATTERN.search("文部科学大臣政務官山田太郎君。")
        assert m is not None
        assert m.group("title") == "文部科学大臣政務官"

    def test_bureau_chief_nomination(self) -> None:
        m = _NOMINATION_PATTERN.search("厚生労働省医政局長田中花子君、答弁。")
        assert m is not None
        assert m.group("title") == "厚生労働省医政局長"
        assert m.group("name") == "田中花子"

    def test_shingikan_nomination(self) -> None:
        m = _NOMINATION_PATTERN.search("内閣府審議官小山一郎君。")
        assert m is not None
        assert m.group("title") == "内閣府審議官"

    def test_no_match_for_member(self) -> None:
        # 役職タイトルがない通常の指名文は match しない
        m = _NOMINATION_PATTERN.search("中村はやと君。")
        assert m is None

    def test_no_match_for_committee_chair(self) -> None:
        # 委員長/議長 は ANSWERER タイトルに含まれないため match しない
        m = _NOMINATION_PATTERN.search("委員長坂本哲志君。")
        assert m is None


class TestExtractAffiliationFromName:
    """speaker_tagger が役職込みの speaker 名 (e.g. '松本大臣') を返すケース。"""

    def test_minister_suffix_short_name(self) -> None:
        # surname + 大臣 → 末尾 keyword だけ返す
        assert _extract_affiliation_from_name("松本大臣") == "大臣"

    def test_kokumu_minister_suffix(self) -> None:
        assert _extract_affiliation_from_name("小野田国務大臣") == "国務大臣"

    def test_seimukan_suffix(self) -> None:
        assert _extract_affiliation_from_name("田中大臣政務官") == "大臣政務官"

    def test_role_descriptive_full_name(self) -> None:
        # prefix に 省/府/局/委員会 等を含む → name 全体を affiliation に
        assert (
            _extract_affiliation_from_name("内閣府宇宙開発戦略推進事務局長")
            == "内閣府宇宙開発戦略推進事務局長"
        )
        assert (
            _extract_affiliation_from_name("公正取引委員会委員長")
            == "公正取引委員会委員長"
        )
        assert (
            _extract_affiliation_from_name("経済産業省官房審議官")
            == "経済産業省官房審議官"
        )

    def test_no_keyword_match(self) -> None:
        # 純粋な人名 (役職を含まない) は空文字
        assert _extract_affiliation_from_name("木原稔") == ""
        assert _extract_affiliation_from_name("中村はやと") == ""
        assert _extract_affiliation_from_name("") == ""

    def test_short_kanjichain_with_just_keyword(self) -> None:
        # name が完全に keyword のみ
        assert _extract_affiliation_from_name("大臣政務官") == "大臣政務官"
        assert _extract_affiliation_from_name("局長") == "局長"


class TestBuildChairNominationMap:
    def test_collects_only_from_chair_utterances(self) -> None:
        utterances = _mk_utterances([
            ("坂本哲志", "委員長", "次に厚生労働大臣木原稔君、答弁を求めます。"),
            ("木原稔", "答弁者", "お答えいたします。"),
            ("中村はやと", "質疑者", "総務大臣田中太郎君に質問します。"),  # 質疑者 なので無視
        ])
        m = _build_chair_nomination_map(utterances)
        assert m == {"木原稔": "厚生労働大臣"}

    def test_first_occurrence_wins(self) -> None:
        utterances = _mk_utterances([
            ("坂本哲志", "委員長", "厚生労働大臣木原稔君。"),
            ("坂本哲志", "委員長", "国土交通大臣木原稔君。"),
        ])
        m = _build_chair_nomination_map(utterances)
        assert m == {"木原稔": "厚生労働大臣"}

    def test_multiple_names_in_one_text(self) -> None:
        utterances = _mk_utterances([
            ("坂本哲志", "委員長",
             "厚生労働大臣木原稔君。続いて文部科学副大臣山田花子君。"),
        ])
        m = _build_chair_nomination_map(utterances)
        assert m == {
            "木原稔": "厚生労働大臣",
            "山田花子": "文部科学副大臣",
        }


class TestEnrichMetadataFromUtterances:
    def test_appends_unknown_answerer(self) -> None:
        existing = [
            SpeakerInfo(
                name="中村はやと",
                affiliation="自由民主党",
                role="質疑者",
                start_seconds=0.0,
                start_time="10:00",
                duration_minutes=10,
            ),
        ]
        utterances = _mk_utterances([
            ("中村はやと", "委員長", "厚生労働大臣木原稔君、答弁を。"),
            ("木原稔", "答弁者", "お答えいたします。"),
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert len(result) == 2
        added = result[1]
        assert added.name == "木原稔"
        assert added.affiliation == "厚生労働大臣"
        assert added.role == "答弁者"
        assert added.start_seconds == 0.0
        assert added.duration_minutes == 0

    def test_skips_already_registered_speaker(self) -> None:
        existing = [
            SpeakerInfo(
                name="木原稔",
                affiliation="自由民主党",
                role="質疑者",
                start_seconds=100.0,
                start_time="10:00",
                duration_minutes=10,
            ),
        ]
        utterances = _mk_utterances([
            ("中村", "委員長", "厚生労働大臣木原稔君。"),
            ("木原稔", "答弁者", "お答えいたします。"),
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert len(result) == 1
        # 既存エントリは変更されていない
        assert result[0].affiliation == "自由民主党"

    def test_fuzzy_match_skips_2char_prefix(self) -> None:
        existing = [
            SpeakerInfo(
                name="木原稔",
                affiliation="自由民主党",
                role="質疑者",
                start_seconds=0.0,
                start_time="",
                duration_minutes=0,
            ),
        ]
        # speaker_tagger が短く "木原" と返した場合、fuzzy match で既存とみなしてスキップ
        utterances = _mk_utterances([
            ("中村", "委員長", "厚生労働大臣木原稔君。"),
            ("木原", "答弁者", "お答えいたします。"),
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert len(result) == 1

    def test_no_affiliation_inferred_falls_back_to_role(self) -> None:
        existing: list[SpeakerInfo] = []
        utterances = _mk_utterances([
            # 委員長指名文がない、name から役職抽出も不可 → affiliation 推定不可
            ("田中太郎", "答弁者", "お答えいたします。改革を進めます。"),
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert len(result) == 1
        added = result[0]
        assert added.name == "田中太郎"
        assert added.affiliation == ""
        assert added.role == "答弁者"  # fallback: speaker_tagger の role

    def test_affiliation_extracted_from_name_suffix(self) -> None:
        """speaker_tagger が役職込みの名前 (松本大臣) を返したケース。"""
        existing: list[SpeakerInfo] = []
        utterances = _mk_utterances([
            ("松本大臣", "答弁者", "お答えいたします。"),
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert len(result) == 1
        added = result[0]
        assert added.name == "松本大臣"
        assert added.affiliation == "大臣"
        assert added.role == "答弁者"

    def test_affiliation_full_for_role_descriptive_name(self) -> None:
        """speaker_tagger が役職描写型 name (内閣府...局長) を返すケース。"""
        existing: list[SpeakerInfo] = []
        utterances = _mk_utterances([
            ("内閣府宇宙開発戦略推進事務局長", "政府参考人", "御答弁します。"),
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert len(result) == 1
        added = result[0]
        assert added.affiliation == "内閣府宇宙開発戦略推進事務局長"
        assert added.role == "政府参考人"

    def test_chair_nomination_takes_precedence_over_name_suffix(self) -> None:
        """委員長指名文があれば name 末尾より優先。"""
        existing: list[SpeakerInfo] = []
        utterances = _mk_utterances([
            ("中村", "委員長", "厚生労働大臣木原稔大臣君、答弁を。"),
            ("木原稔大臣", "答弁者", "お答えいたします。"),
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert len(result) == 1
        # 委員長指名文の "厚生労働大臣" が、name 末尾の "大臣" より優先される
        assert result[0].affiliation == "厚生労働大臣"

    def test_political_party_role_skipped(self) -> None:
        existing: list[SpeakerInfo] = []
        utterances = _mk_utterances([
            ("田中太郎", "質疑者", "質問します。"),  # 質疑者 は対象外
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert result == existing

    def test_government_attendee_role_kept(self) -> None:
        existing: list[SpeakerInfo] = []
        utterances = _mk_utterances([
            ("中村", "委員長", "厚生労働省医政局長田中花子君、答弁を。"),
            ("田中花子", "政府参考人", "お答えいたします。"),
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert len(result) == 1
        assert result[0].name == "田中花子"
        assert result[0].affiliation == "厚生労働省医政局長"
        assert result[0].role == "政府参考人"

    def test_role_fallback_when_derive_returns_unrelated_role(self) -> None:
        """affiliation から derive_role が返した role が想定外なら、speaker_tagger の role を採用。"""
        existing: list[SpeakerInfo] = []
        utterances = _mk_utterances([
            # affiliation "委員長" → derive_role → 委員長 (但し ANSWERER 役職には不適)
            # ただし NOMINATION_PATTERN は 委員長 を含まないため、 affiliation は ""
            # にしか推定されない。fallback role が使われる。
            ("田中花子", "答弁者", "お答えします。"),
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert result[0].role == "答弁者"

    def test_duplicate_answerer_added_once(self) -> None:
        existing: list[SpeakerInfo] = []
        utterances = _mk_utterances([
            ("中村", "委員長", "厚生労働大臣木原稔君。"),
            ("木原稔", "答弁者", "お答えいたします。"),
            ("中村", "委員長", "再度、厚生労働大臣木原稔君。"),
            ("木原稔", "答弁者", "再度のお答えです。"),
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert len(result) == 1
        assert result[0].name == "木原稔"

    def test_does_not_mutate_input(self) -> None:
        existing = [
            SpeakerInfo(
                name="中村",
                affiliation="自由民主党",
                role="質疑者",
                start_seconds=0.0,
                start_time="10:00",
                duration_minutes=10,
            ),
        ]
        utterances = _mk_utterances([
            ("中村", "委員長", "厚生労働大臣木原稔君。"),
            ("木原稔", "答弁者", "お答えいたします。"),
        ])
        before_len = len(existing)
        result = enrich_metadata_from_utterances(utterances, existing)
        assert len(existing) == before_len
        assert result is not existing

    def test_no_candidates_returns_copy(self) -> None:
        existing = [
            SpeakerInfo(
                name="中村",
                affiliation="自由民主党",
                role="質疑者",
                start_seconds=0.0,
                start_time="",
                duration_minutes=0,
            ),
        ]
        utterances = _mk_utterances([("中村", "質疑者", "質問します。")])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert result == existing
        assert result is not existing


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
