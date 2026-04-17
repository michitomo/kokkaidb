"""法案メタデータの共通Pydanticモデル。CLB / Gian スクレイパで共用。

衆議院・参議院の議案一覧（gian.py）と内閣法制局 recent-laws（clb.py）の
両方が同じスキーマで法案メタデータを返せるように、共通の `BillDetail` を
ここに定義する。型の揺れを避けるため、どちらのスクレイパーも本モジュールを
import すること。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

BillType = Literal["kakuhou", "shuhou", "sanhou"]


class BillDetail(BaseModel):
    """法案1件分の詳細情報（両ソース共通スキーマ）。

    Attributes:
        id: ソース横断で一意なID。
            - CLB: "clb-{detail_id}" 例: "clb-5149"
            - 衆議院議案一覧: "shugiin-{session}-{type}-{number}" 例: "shugiin-221-kakuhou-1"
            - 参議院議案一覧: "sangiin-{session}-{type}-{number}" 例: "sangiin-221-sanhou-5"
        type: 法案種別。
            - kakuhou: 内閣（政府）提出法律案
            - shuhou: 衆議院議員提出法律案
            - sanhou: 参議院議員提出法律案
        title: 法律案名。
        reason: 提出理由。議案一覧ページからは基本的に取れないため Optional。
        diet_session: 国会回次（例: 221）。
        bill_number: その国会回次内の法案番号（例: "第1号" または "1"）。
        submitter: 提出者名（主管省庁名または提出議員名）。
        submitted_at: 国会提出日（ISO 8601日付）。
        cabinet_decision_at: 閣議決定日（閣法のみ、ISO 8601日付）。
        status: 審議状況（例: "衆議院で審議中", "成立"）。
        source_url: 詳細ページのURL（経過情報ページ等）。
    """

    id: str
    type: BillType
    title: str
    reason: str | None = None
    diet_session: int
    bill_number: str | None = None
    submitter: str | None = None
    submitted_at: str | None = None
    cabinet_decision_at: str | None = None
    status: str | None = None
    source_url: str
