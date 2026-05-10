"""src/metadata_enricher.py の単体テスト (PR6, §2.2/2.3)。"""

from __future__ import annotations

import pytest

from src.metadata_enricher import (
    _NOMINATION_PATTERN,
    _backfill_existing_speaker_roles,
    _build_chair_nomination_map,
    _build_utterance_role_map,
    _extract_affiliation_from_name,
    _extract_affiliation_from_utterance_text,
    enrich_metadata_from_utterances,
)
from src.models import (
    SegmentUtterances,
    SpeakerInfo,
    Utterance,
    UtterancesOutput,
)


def _mk_speaker(
    name: str,
    affiliation: str,
    role: str,
    start_seconds: float = 0.0,
) -> SpeakerInfo:
    return SpeakerInfo(
        name=name,
        affiliation=affiliation,
        role=role,
        start_seconds=start_seconds,
        start_time="",
        duration_minutes=0,
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
        # PR26.1: affiliation が推定できない場合は role 名を最低限の affiliation として使う
        assert added.affiliation == "答弁者"
        assert added.role == "答弁者"

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

    def test_missing_questioner_added(self) -> None:
        """PR33: metadata に未登録の質疑者も補完対象になる。"""
        existing: list[SpeakerInfo] = []
        utterances = _mk_utterances([
            ("田中太郎", "質疑者", "質問します。"),
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert len(result) == 1
        assert result[0].name == "田中太郎"
        assert result[0].role == "質疑者"

    def test_existing_questioner_not_duplicated(self) -> None:
        """PR33: 既存 metadata に登録済みの質疑者は重複追加しない。"""
        existing = [_mk_speaker("田中太郎", "立憲民主党", "質疑者", 0)]
        utterances = _mk_utterances([
            ("田中太郎", "質疑者", "質問します。"),
        ])
        result = enrich_metadata_from_utterances(utterances, existing)
        assert len(result) == 1

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


class TestPR26BackfillExistingRoles:
    """PR26: 既存 metadata.speakers の role が空文字のとき、derive_role と
    utterance 観測 role の 2 段フォールバックで補完する。
    """

    def _sp(self, name: str, affiliation: str = "", role: str = "") -> SpeakerInfo:
        return SpeakerInfo(
            name=name,
            affiliation=affiliation,
            role=role,
            start_seconds=0.0,
            start_time="",
            duration_minutes=0,
        )

    def test_derive_role_from_affiliation_when_empty(self) -> None:
        speakers = [
            self._sp("森英介", "衆議院議長"),
            self._sp("牧野たかお", "復興大臣 福島原発事故再生総括担当"),
            self._sp("西田昭二", "自由民主党"),
        ]
        updated = _backfill_existing_speaker_roles(speakers, role_map={})
        assert updated == 3
        assert speakers[0].role == "議長"  # PR29: 議長 系は独立 role
        assert speakers[1].role == "答弁者"  # 大臣
        assert speakers[2].role == "質疑者"  # 政党

    def test_pr30_sankounin_prefix_overrides_old_role(self) -> None:
        """PR30: 既存 role が「委員長」「政府参考人」「その他」でも
        affiliation が「参考人 …」始まりなら「参考人」に再分類する。
        """
        speakers = [
            self._sp("澤田純", "参考人 一般社団法人日本経済団体連合会副会長・産業競争力強化委員長", role="委員長"),
            self._sp("宮澤伸", "参考人 日本商工会議所産業政策第一部長", role="政府参考人"),
            self._sp("大橋弘", "参考人 東京大学副学長・経済学研究科教授", role="その他"),
        ]
        updated = _backfill_existing_speaker_roles(speakers, role_map={})
        assert updated == 3
        for sp in speakers:
            assert sp.role == "参考人"

    def test_pr26_1_start_seconds_filled_from_first_utterance(self) -> None:
        """PR26.1: enriched speaker の start_seconds は最初に登場した
        segment.start_seconds で埋まる。affiliation も role 名で最低限埋まる。"""
        existing: list[SpeakerInfo] = []
        # _mk_utterances は segment.start_seconds=0.0 なので別途構築
        utterances = UtterancesOutput(
            segments=[
                SegmentUtterances(
                    segment_index=0,
                    segment_speaker="質問者",
                    segment_affiliation="X党",
                    start_seconds=0.0,
                    video_url="https://example.com/v",
                    utterances=[
                        Utterance(speaker="質問者", role="質疑者", text="質問。"),
                    ],
                ),
                SegmentUtterances(
                    segment_index=1,
                    segment_speaker="質問者",
                    segment_affiliation="X党",
                    start_seconds=600.0,
                    video_url="https://example.com/v",
                    utterances=[
                        Utterance(speaker="質問者", role="質疑者", text="続けて質問。"),
                        Utterance(speaker="鈴木大輔", role="答弁者", text="お答えします。改革を進めます。"),
                    ],
                ),
            ]
        )
        result = enrich_metadata_from_utterances(utterances, existing)
        added = next(s for s in result if s.name == "鈴木大輔")
        assert added.start_seconds == 600.0  # 最初に登場した segment
        assert added.start_time == "00:10"  # 600s = 10 min
        assert added.affiliation == "答弁者"  # PR26.1 最低限の affiliation
        assert added.role == "答弁者"

    def test_pr29_existing_chairman_role_replaced_with_gicho(self) -> None:
        """PR29: 既存 metadata で role="委員長" が付いていた議長系は「議長」に
        再分類する (partial regen で derive_role 修正版を反映)。"""
        speakers = [
            self._sp("森英介", "衆議院議長", role="委員長"),
            self._sp("関口昌一", "参議院議長", role="委員長"),
        ]
        updated = _backfill_existing_speaker_roles(speakers, role_map={})
        assert updated == 2
        assert speakers[0].role == "議長"
        assert speakers[1].role == "議長"

    def test_falls_back_to_utterance_role_when_derive_returns_other(self) -> None:
        """affiliation が空または derive_role が「その他」を返す場合、
        utterance 観測 role を使う。"""
        speakers = [
            self._sp("木原稔", ""),  # affiliation 空 → derive_role はその他
        ]
        role_map = {"木原稔": "答弁者"}
        updated = _backfill_existing_speaker_roles(speakers, role_map=role_map)
        assert updated == 1
        assert speakers[0].role == "答弁者"

    def test_skips_already_populated(self) -> None:
        speakers = [
            self._sp("既存", "自由民主党", role="質疑者"),
        ]
        updated = _backfill_existing_speaker_roles(speakers, role_map={})
        assert updated == 0
        assert speakers[0].role == "質疑者"  # 触らない

    def test_replaces_その他_with_better(self) -> None:
        """role='その他' は要再計算とみなす (古い書き出しの修復)。"""
        speakers = [
            self._sp("田中", "立憲民主党", role="その他"),
        ]
        updated = _backfill_existing_speaker_roles(speakers, role_map={})
        assert updated == 1
        assert speakers[0].role == "質疑者"

    def test_falls_back_to_その他_when_no_signal(self) -> None:
        """affiliation も role_map も無ければ「その他」を入れる。"""
        speakers = [self._sp("UNKNOWN", "", role="")]
        updated = _backfill_existing_speaker_roles(speakers, role_map={})
        assert updated == 1
        assert speakers[0].role == "その他"

    def test_build_utterance_role_map(self) -> None:
        utterances = _mk_utterances([
            ("田中", "質疑者", "質問します。"),
            ("木原稔", "答弁者", "お答えいたします。"),
            ("局長X", "政府参考人", "数値を申し上げます。"),
            ("田中", "質疑者", "重ねて質問。"),  # 重複 — 最初の値を採用
        ])
        role_map = _build_utterance_role_map(utterances)
        assert role_map["田中"] == "質疑者"
        assert role_map["木原稔"] == "答弁者"
        assert role_map["局長X"] == "政府参考人"

    def test_enrich_does_not_mutate_input_speakers(self) -> None:
        """PR26 で role 補完を行うが、入力 speakers は破壊しない。"""
        original = SpeakerInfo(
            name="森英介",
            affiliation="衆議院議長",
            role="",
            start_seconds=0.0,
            start_time="",
            duration_minutes=0,
        )
        speakers = [original]
        utterances = _mk_utterances([("森英介", "議長", "開会いたします。")])
        result = enrich_metadata_from_utterances(utterances, speakers)
        assert result[0].role == "議長"  # PR29: 衆議院議長 → 議長
        assert original.role == ""  # 入力は触らない


class TestPR42ExtractAffiliationFromUtteranceText:
    """PR42: utterance テキスト先頭から役職タイトルを抽出。"""

    def test_prime_minister(self) -> None:
        assert _extract_affiliation_from_utterance_text("内閣総理大臣の高市でございます。") == "内閣総理大臣"

    def test_minister(self) -> None:
        assert _extract_affiliation_from_utterance_text("防衛大臣でございます。") == "防衛大臣"

    def test_bureau_chief_with_ministry(self) -> None:
        result = _extract_affiliation_from_utterance_text("厚生労働省社会・援護局長の山下です。")
        assert "局長" in result

    def test_no_match_for_plain_greeting(self) -> None:
        assert _extract_affiliation_from_utterance_text("おはようございます。") == ""

    def test_empty_text(self) -> None:
        assert _extract_affiliation_from_utterance_text("") == ""

    def test_enrich_uses_utterance_text_when_no_nomination(self) -> None:
        """nomination_map も name suffix も効かないが utterance テキストから役職が取れる場合。"""
        utterances = _mk_utterances([
            ("委員長", "委員長", "次に、答弁者の高市君。"),
            ("高市", "答弁者", "内閣総理大臣の高市でございます。ご質問にお答えします。"),
        ])
        result = enrich_metadata_from_utterances(utterances, [])
        answerer = next((s for s in result if s.name == "高市"), None)
        assert answerer is not None
        assert "大臣" in answerer.affiliation


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
