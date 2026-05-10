"""Step 5↔5.5 間の metadata.speakers 逆補完 (PR6, §2.2/2.3)。

scrapers が抽出した metadata.speakers には委員長・質疑者しか含まれず、
答弁者 (大臣・副大臣・政務官) と政府参考人 (局長・審議官等) が登録されていない
ことが多い (TV ページのタイムスタンプリンク仕様の制約)。

本モジュールは speaker_tagger 出力 (UtterancesOutput) から
role∈{答弁者, 政府参考人} の発言者を抽出し、既存 metadata.speakers と
fuzzy 一致しないものを追加する。affiliation は委員長 utterance 内の
「○○大臣 ××君。」等の指名パターンから推定する (推定不可なら空文字)。

役割確定ロジック:
- 推定 affiliation が非空 → derive_role(affiliation) で role 決定
- 推定 affiliation が空 → speaker_tagger が付けた role (答弁者 or 政府参考人) を踏襲
"""

from __future__ import annotations

import logging
import re

from src.models import SpeakerInfo, UtterancesOutput
from src.scrapers._role import derive_role
from src.speaker_lookup import build_lookup, find_by_name

logger = logging.getLogger(__name__)

# 答弁者・政府参考人の役職タイトルキーワード (長い順、re alternation で誤分割回避)
_ANSWERER_TITLE_KEYWORDS: tuple[str, ...] = tuple(
    sorted(
        (
            "内閣総理大臣",
            "総理大臣",
            "国務大臣",
            "大臣政務官",
            "副大臣",
            "大臣",
            "副長官",
            "長官",
            "事務次長",
            "次長",
            "部長",
            "局長",
            "審議官",
            "参事官",
            "課長",
            "総裁",
            "理事長",
            "本部長",
        ),
        key=len,
        reverse=True,
    )
)

_TITLE_KEYWORDS_PAT = "|".join(re.escape(k) for k in _ANSWERER_TITLE_KEYWORDS)

_NAME_CHARS = r"[ぁ-ゟァ-ヿ一-鿿]"
_HONORIFIC = r"(?:君|氏|さん|議員|委員)"

# 役職タイトル + 人名 + 敬称 — non-greedy 12-char prefix で省名等を含めて拾う
_NOMINATION_PATTERN = re.compile(
    rf"(?P<title>[一-鿿]{{0,12}}?(?:{_TITLE_KEYWORDS_PAT}))"
    rf"(?P<name>{_NAME_CHARS}{{2,8}}){_HONORIFIC}"
)

_ENRICH_ROLES: frozenset[str] = frozenset(("答弁者", "政府参考人"))

# 委員長相当 (進行役) の追加キーワード — 名前末尾から affiliation 抽出時に使う
_CHAIR_LIKE_KEYWORDS: tuple[str, ...] = ("委員長", "事務総長", "副議長", "議長")


def _extract_affiliation_from_name(name: str) -> str:
    """speaker name 自体が役職タイトル混じり文字列のとき affiliation を抽出する。

    speaker_tagger が「松本大臣」「内閣府宇宙開発戦略推進事務局長」のような
    役職込みの speaker 名を返すケースに対応する。

    名前末尾が _ANSWERER_TITLE_KEYWORDS / _CHAIR_LIKE_KEYWORDS のいずれかと
    一致したら、(短い surname + suffix の場合) は suffix だけ、(役職描写型の場合)
    は name 全体を affiliation として返す。

    省/府/院/庁/院/局/部/委員会/会議 等を含む長い prefix は役職描写型と判定する。
    """
    if not name:
        return ""
    keywords = (*_ANSWERER_TITLE_KEYWORDS, *_CHAIR_LIKE_KEYWORDS)
    # 長い順にチェック (重複ある可能性があるが endswith マッチで先勝ち)
    for kw in sorted(keywords, key=len, reverse=True):
        if name.endswith(kw):
            prefix = name[: -len(kw)]
            if not prefix:
                return kw
            # prefix に役職描写キーワードがあれば name 全体を affiliation に
            if any(
                marker in prefix
                for marker in ("省", "府", "院", "庁", "局", "部", "委員会", "会議", "事務")
            ):
                return name
            return kw
    return ""


def _build_chair_nomination_map(utterances: UtterancesOutput) -> dict[str, str]:
    """委員長 utterance を全 scan して name → 推定タイトル マップを作る。

    最初に検出したタイトルを採用する (重複時は上書きしない)。
    """
    name_to_title: dict[str, str] = {}
    for seg in utterances.segments:
        for u in seg.utterances:
            if u.role != "委員長":
                continue
            for m in _NOMINATION_PATTERN.finditer(u.text):
                title = m.group("title")
                name = m.group("name")
                if not name or not title:
                    continue
                if name not in name_to_title:
                    name_to_title[name] = title
    return name_to_title


def enrich_metadata_from_utterances(
    utterances: UtterancesOutput,
    speakers: list[SpeakerInfo],
) -> list[SpeakerInfo]:
    """utterances から答弁者・政府参考人を抽出して speakers に逆補完。

    既存 speakers との fuzzy 重複チェックを行い、新規エントリのみ追加する。
    affiliation は委員長 utterance の「(役職)<名前>君。」パターンから推定する。

    Args:
        utterances: speaker_tagger の出力 (Step 5 後・Step 5.5 前)
        speakers: scrapers が抽出した既存 speakers (metadata.speakers)

    Returns:
        既存 + 補完エントリ を含む新リスト (入力 speakers は変更しない)
    """
    lookup = build_lookup(speakers)
    nomination_map = _build_chair_nomination_map(utterances)

    # name → (affiliation, fallback_role) を蓄積
    candidates: dict[str, tuple[str, str]] = {}

    for seg in utterances.segments:
        for u in seg.utterances:
            if u.role not in _ENRICH_ROLES:
                continue
            name = (u.speaker or "").strip()
            if not name:
                continue
            if find_by_name(name, lookup, allow_single_char=True) is not None:
                continue
            if name in candidates:
                continue
            # 1. 委員長指名文から推定
            affiliation = nomination_map.get(name, "")
            # 2. 推定不可なら speaker name 自体から末尾役職を抽出
            if not affiliation:
                affiliation = _extract_affiliation_from_name(name)
            candidates[name] = (affiliation, u.role)

    if not candidates:
        return list(speakers)

    enriched = list(speakers)
    for name, (affiliation, fallback_role) in candidates.items():
        if affiliation:
            role = derive_role(affiliation)
            # derive_role が想定外 ("質疑者" 等) を返した場合は fallback を優先
            if role not in _ENRICH_ROLES:
                role = fallback_role
        else:
            role = fallback_role
        enriched.append(
            SpeakerInfo(
                name=name,
                affiliation=affiliation,
                role=role,
                start_seconds=0.0,
                start_time="",
                duration_minutes=0,
            )
        )

    logger.info(
        "metadata enrichment: existing=%d, added=%d (with affiliation=%d)",
        len(speakers),
        len(candidates),
        sum(1 for _, (a, _r) in candidates.items() if a),
    )
    return enriched


__all__ = ["enrich_metadata_from_utterances"]
