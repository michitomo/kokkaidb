"""SpeakerInfo.role を affiliation 文字列から決定論的に派生するモジュール。"""

from __future__ import annotations

from src.models import SpeakerRole

PARTY_NAMES: frozenset[str] = frozenset(
    (
        "自由民主党",
        "立憲民主党",
        "公明党",
        "国民民主党",
        "日本共産党",
        "れいわ新選組",
        "日本維新の会",
        "参政党",
        "チームみらい",
        "社会民主党",
        "教育無償化を実現する会",
        "無所属",
        "無所属の会",
    )
)

_GOV_ATTENDEE_SUFFIXES: tuple[str, ...] = (
    "局長",
    "部長",
    "審議官",
    "長官",
    "次長",
    "参事官",
    "課長",
)


def derive_role(affiliation: str) -> SpeakerRole:
    """affiliation から SpeakerRole を 1 つ決定する。マッチしなければ "その他"。

    優先順位:
        委員長/議長 > 大臣系 > 政府参考人(局長等) > 参考人 > 政党所属 > その他
    """
    if not affiliation:
        return "その他"

    if affiliation.endswith(("委員長", "議長", "副議長")) or affiliation in {
        "委員長",
        "議長",
        "副議長",
    }:
        return "委員長"

    if affiliation.endswith(("大臣", "副大臣", "政務官")):
        return "答弁者"

    # Multi-role affiliations e.g. "財務大臣 内閣府特命担当大臣（金融） ..."
    if "大臣" in affiliation or "政務官" in affiliation:
        return "答弁者"

    if affiliation.endswith(_GOV_ATTENDEE_SUFFIXES):
        return "政府参考人"

    if affiliation == "参考人" or affiliation.endswith("参考人"):
        return "参考人"

    if affiliation in PARTY_NAMES or any(party in affiliation for party in PARTY_NAMES):
        return "質疑者"

    if affiliation.endswith("会派"):
        return "質疑者"

    return "その他"
