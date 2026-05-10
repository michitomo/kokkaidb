"""参議院TV (www.webtv.sangiin.go.jp) スクレイパー

UTF-8 エンコーディング（特別な処理不要）。

`detect_new_sessions(date)` の経路:
  - 本日 (JST): `result_selecter.php?mode=today_reload&absdate=...` を GET で叩く。
                参議院TVは `mode=today_reload` の場合 absdate に関わらず本日分のみを
                返す仕様。GET 経由のため WAF を通過する。
  - 過去日付:   POST `keyword_search.php` が必要。F5 BIG-IP ASM Bot Defense で
                保護されているため、Playwright (要 stealth + 信頼イベント) で
                ブラウザ経由のフォーム送信を行う (`_sangiin_search.py` を参照)。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from src.audio.sangiin_resolver import resolve_stream_url
from src.models import SessionDetail, SpeakerInfo
from src.scrapers._committee import resolve_committee
from src.scrapers._role import derive_role
from src.scrapers._session_kind import detect_session_kind
from src.scrapers.base import BaseScraper, SessionNotReadyError

logger = logging.getLogger(__name__)

# 正規ホスト名は www.webtv.sangiin.go.jp (バレ webtv.sangiin.go.jp は環境により
# 名前解決できないことがあるため www 付きを採用)。
BASE_URL = "https://www.webtv.sangiin.go.jp/webtv"
JST = timezone(timedelta(hours=9))


class SangiinScraper(BaseScraper):
    """参議院TV (www.webtv.sangiin.go.jp) スクレイパー。"""

    chamber = "sangiin"

    def detect_new_sessions(self, date: str) -> list[str]:
        """指定日のセッションIDリストを返す。

        Args:
            date: 検索対象日（YYYY-MM-DD 形式）

        Returns:
            sid の文字列リスト（重複なし、昇順）
        """
        today_jst = datetime.now(JST).strftime("%Y-%m-%d")
        if date == today_jst:
            return self._detect_today(date)
        return self._detect_past_via_playwright(date)

    def _detect_today(self, date: str) -> list[str]:
        """本日分の高速取得 (GET、WAF 不要)。

        `result_selecter.php?mode=today_reload` は `absdate` パラメータを
        実質無視して常に「今日」分のみ返す。本メソッドは `date` が今日と
        一致する前提で呼ばれる。
        """
        url = f"{BASE_URL}/result_selecter.php?mode=today_reload&absdate={date}"
        logger.info("Fetching sangiin session list for today=%s: %s", date, url)

        session = requests.Session()
        # 先にトップページにアクセスして PHPSESSID を取得
        session.get(f"{BASE_URL}/index.php", timeout=30)
        response = session.get(url, timeout=30)
        response.raise_for_status()

        sids = sorted(set(re.findall(r"detail\.php\?sid=(\d+)", response.text)))
        logger.info("Found %d sangiin sessions for today=%s", len(sids), date)
        return sids

    def _detect_past_via_playwright(self, date: str) -> list[str]:
        """過去日付の検索 (Playwright 必須)。

        F5 BIG-IP ASM が POST keyword_search.php を遮断するため、ヘッドレス
        ブラウザで JS チャレンジを通し、検索ボタンを信頼イベントでクリック
        して結果 HTML を回収する。失敗時 (Playwright 未導入 / WAF 強化) は
        例外を投げる。`batch.py` 側で warning 扱いになる。
        """
        from src.scrapers._sangiin_search import discover_sids_for_date

        logger.info("Searching sangiin past sessions for date=%s via playwright", date)
        sids = discover_sids_for_date(date)
        logger.info("Found %d sangiin sessions for past date=%s", len(sids), date)
        return sids

    def get_session_detail(self, session_id: str) -> SessionDetail:
        """参議院TVの詳細ページからセッション情報を取得する。

        Args:
            session_id: 参議院TVのsid（例: "7890"）

        Returns:
            SessionDetail: スクレイピングした情報を格納したPydanticモデル

        Raises:
            requests.HTTPError: HTTPエラーが発生した場合
        """
        url = f"{BASE_URL}/detail.php?sid={session_id}"
        logger.info("Fetching sangiin session detail: %s", url)

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        speakers = _extract_speakers(soup, session_id)
        if not speakers:
            raise SessionNotReadyError(
                f"Speaker list not yet published for sid={session_id}. "
                "Will retry later."
            )
        for s in speakers:
            s.role = derive_role(s.affiliation)

        committee = resolve_committee(soup, speakers)
        date_str = _extract_date(soup)
        mediasp_hash = _extract_mediasp_hash(soup)
        session_kind = detect_session_kind(soup.get_text(), committee, speakers)

        return SessionDetail(
            chamber="sangiin",
            session_id=session_id,
            date=date_str,
            committee=committee,
            session_kind=session_kind,
            hls_url="",  # mediasp.jp経由で別途解決
            mediasp_hash=mediasp_hash,
            source_url=url,
            processed_at=datetime.now(JST).isoformat(),
            speakers=speakers,
        )

    def get_audio_url(self, session_id: str) -> str:
        """mediasp.jp 経由で音声ストリームURLを返す。

        Args:
            session_id: 参議院TVのsid

        Returns:
            HLS ストリーム URL 文字列
        """
        detail = self.get_session_detail(session_id)
        if not detail.mediasp_hash:
            raise ValueError(f"mediasp.jp hash not found for sid={session_id}")
        return resolve_stream_url(detail.mediasp_hash)


# ---------------------------------------------------------------------------
# モジュールレベルのヘルパー関数
# ---------------------------------------------------------------------------


def _extract_date(soup: BeautifulSoup) -> str:
    """日付を抽出する（令和/西暦の両方に対応）。"""
    # 令和表記: 令和X年Y月Z日
    for tag in soup.find_all(string=re.compile(r"令和\d+年\d+月\d+日")):
        match = re.search(r"令和(\d+)年(\d+)月(\d+)日", str(tag))
        if match:
            year = 2018 + int(match.group(1))
            m = int(match.group(2))
            d = int(match.group(3))
            return f"{year:04d}-{m:02d}-{d:02d}"

    # 西暦表記: YYYY年M月D日
    for tag in soup.find_all(string=re.compile(r"\d{4}年\d+月\d+日")):
        match = re.search(r"(\d{4})年(\d+)月(\d+)日", str(tag))
        if match:
            year = int(match.group(1))
            if 2000 <= year <= 2100:
                m = int(match.group(2))
                d = int(match.group(3))
                return f"{year:04d}-{m:02d}-{d:02d}"

    raise ValueError("Could not extract date from sangiin detail page")


def _extract_mediasp_hash(soup: BeautifulSoup) -> str:
    """mediasp.jp の hash パラメータを抽出する。"""
    script_tag = soup.find("script", src=re.compile(r"mediasp\.jp"))
    if not script_tag:
        return ""

    src = script_tag.get("src", "")
    hash_match = re.search(r"hash=([a-zA-Z0-9]+)", src)
    if hash_match:
        return hash_match.group(1)
    return ""


def _extract_speakers(soup: BeautifulSoup, session_id: str) -> list[SpeakerInfo]:
    """発言者リストを抽出する。

    参議院TV の発言者リスト:
    <a href='#1850.95' class='play2'>名前(所属)</a>

    同一人物の複数スロットは (name, affiliation) で dedup し、
    start_seconds は最小、duration_minutes は合算、start_time は若い方を残す。
    """
    seen: dict[tuple[str, str], SpeakerInfo] = {}
    seen_order: list[tuple[str, str]] = []

    anchors = soup.find_all("a", class_="play2")

    for anchor in anchors:
        href = anchor.get("href", "")
        if not href.startswith("#"):
            continue

        try:
            start_seconds = float(href[1:])
        except ValueError:
            continue

        raw_text = anchor.get_text(strip=True)
        if not raw_text:
            continue

        name, affiliation = _parse_speaker_text(raw_text)
        if not name:
            continue

        start_time, duration_minutes = _find_speaker_row_data(anchor)

        key = (name, affiliation)
        if key in seen:
            existing = seen[key]
            if start_seconds < existing.start_seconds:
                existing.start_seconds = start_seconds
                existing.start_time = start_time
            existing.duration_minutes += duration_minutes
            continue

        seen[key] = SpeakerInfo(
            name=name,
            affiliation=affiliation,
            start_seconds=start_seconds,
            start_time=start_time,
            duration_minutes=duration_minutes,
        )
        seen_order.append(key)

    speakers = [seen[k] for k in seen_order]
    logger.info("Extracted %d speakers for sid=%s", len(speakers), session_id)
    return speakers


def _parse_speaker_text(text: str) -> tuple[str, str]:
    """アンカーテキストから名前と所属を分離する。

    全角・半角カッコ両方に対応。

    例:
        "伊藤孝江(法務委員長)" -> ("伊藤孝江", "法務委員長")
        "田中太郎（自由民主党）" -> ("田中太郎", "自由民主党")
        "鈴木一郎" -> ("鈴木一郎", "")
    """
    # 半角カッコ
    match = re.match(r"^(.+?)[(\uff08](.+)[)\uff09]\s*$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text.strip(), ""


def _find_speaker_row_data(anchor_tag: object) -> tuple[str, int]:
    """アンカータグの親テーブル行から開始時刻と所要時間を取得する。"""
    parent = getattr(anchor_tag, "parent", None)
    for _ in range(5):
        if parent is None:
            break
        if getattr(parent, "name", None) == "tr":
            return _parse_table_row(parent)
        parent = getattr(parent, "parent", None)

    return "", 0


def _parse_table_row(tr_tag: object) -> tuple[str, int]:
    """テーブル行のセルから開始時刻と所要時間を取得する。"""
    cells = getattr(tr_tag, "find_all", lambda *a, **k: [])("td")
    cell_texts = [c.get_text(strip=True) for c in cells]

    start_time = ""
    duration_minutes = 0

    for text in cell_texts:
        # 開始時刻: "10時 00分" 形式
        jtime_match = re.match(r"^(\d{1,2})時\s*(\d{2})分$", text)
        if jtime_match:
            h, m = int(jtime_match.group(1)), int(jtime_match.group(2))
            start_time = f"{h:02d}:{m:02d}"
            continue

        if re.match(r"^\d{1,2}:\d{2}$", text):
            start_time = text
            continue

        # 所要時間: "03分" 形式
        duration_match = re.match(r"^(\d+)分$", text)
        if duration_match:
            duration_minutes = int(duration_match.group(1))

    return start_time, duration_minutes
