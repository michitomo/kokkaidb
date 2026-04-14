"""衆議院TV (shugiintv.go.jp) スクレイパー

EUC-JP エンコーディングを明示的に処理する。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from src.models import SessionDetail, SpeakerInfo
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.shugiintv.go.jp/jp/index.php"
JST = timezone(timedelta(hours=9))

# "はじめから再生" など、発言者ではないリンクテキスト
_NON_SPEAKER_TEXTS = {"はじめから再生", "先頭から再生", "全体再生"}


class ShugiinScraper(BaseScraper):
    """衆議院TV (shugiintv.go.jp) スクレイパー。"""

    chamber = "shugiin"

    def detect_new_sessions(self, date: str) -> list[str]:
        """カレンダーGETで指定日のdeli_idリストを返す。

        Args:
            date: 検索対象日（YYYY-MM-DD形式、例: "2026-04-09"）

        Returns:
            deli_idの文字列リスト（重複なし）
        """
        u_day = date.replace("-", "")
        url = f"{BASE_URL}?{urlencode({'ex': 'VL', 'u_day': u_day})}"
        logger.info("Fetching session list for date=%s: %s", date, url)

        response = requests.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = "euc-jp"

        return list(set(re.findall(r"deli_id=(\d+)", response.text)))

    def get_session_detail(self, session_id: str) -> SessionDetail:
        """衆議院TVの詳細ページからセッション情報を取得する。

        Args:
            session_id: 衆議院TVの配信ID（例: "56149"）

        Returns:
            SessionDetail: スクレイピングした情報を格納したPydanticモデル

        Raises:
            requests.HTTPError: HTTPエラーが発生した場合
            ValueError: 必須情報が取得できなかった場合
        """
        url = f"{BASE_URL}?{urlencode({'ex': 'VL', 'deli_id': session_id})}"
        logger.info("Fetching session detail: %s", url)

        response = requests.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = "euc-jp"

        soup = BeautifulSoup(response.text, "html.parser")

        hls_url = _extract_hls_url(soup)
        if not hls_url:
            raise ValueError(f"HLS URL not found for deli_id={session_id}")

        committee, date_str, duration = _extract_session_metadata(soup, session_id)
        speakers = _extract_speakers(soup, session_id)

        return SessionDetail(
            chamber="shugiin",
            session_id=session_id,
            date=date_str,
            committee=committee,
            duration=duration,
            hls_url=hls_url,
            source_url=url,
            processed_at=datetime.now(JST).isoformat(),
            speakers=speakers,
        )

    def get_audio_url(self, session_id: str) -> str:
        """HLS URLを返す（詳細ページから軽量取得）。

        Args:
            session_id: 衆議院TVの配信ID

        Returns:
            HLS URL文字列
        """
        url = f"{BASE_URL}?{urlencode({'ex': 'VL', 'deli_id': session_id})}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = "euc-jp"

        soup = BeautifulSoup(response.text, "html.parser")
        hls_url = _extract_hls_url(soup)
        if not hls_url:
            raise ValueError(f"HLS URL not found for deli_id={session_id}")
        return hls_url


# ---------------------------------------------------------------------------
# モジュールレベルのヘルパー関数（後方互換のためトップレベルに残す）
# ---------------------------------------------------------------------------


def get_session_detail(deli_id: str) -> SessionDetail:
    """後方互換用: ShugiinScraper().get_session_detail() のエイリアス。"""
    return ShugiinScraper().get_session_detail(deli_id)


def _extract_hls_url(soup: BeautifulSoup) -> str:
    """hidden input #vtag_src_base_vod からHLS URLを取得する。"""
    tag = soup.find("input", {"id": "vtag_src_base_vod"})
    if not tag:
        logger.debug("Hidden input #vtag_src_base_vod not found in page")
        return ""
    value = tag.get("value", "")
    if not value:
        return ""
    # value が相対パス（例: "2026/2026-0409-1300-00/playlist.m3u8"）の場合に補完
    # http:// → https:// に正規化（hlsvod.shugiintv.go.jp は http で返すが HTTPS のみ受付）
    if value.startswith("http://"):
        return value.replace("http://", "https://", 1)
    if value.startswith("https://"):
        return value
    return f"https://hlsvod.shugiintv.go.jp/vod/_definst_/amlst:{value}"


def _extract_session_metadata(
    soup: BeautifulSoup, deli_id: str
) -> tuple[str, str, str]:
    """委員会名・日付・所要時間を抽出する。

    実際のページ構造:
    - タイトル: "衆議院インターネット審議中継"（委員会名・日付なし）
    - 日付: ページ内テキスト "2026年4月9日 (木)" 形式（西暦）
    - 委員会名: ページ内テキストから

    Returns:
        (committee, date_str, duration) のタプル
    """
    committee = ""
    date_str = ""
    duration = ""

    # タイトルタグから委員会名を探す（タイトルに含まれる場合）
    title_tag = soup.find("title")
    if title_tag:
        title_text = title_tag.get_text(strip=True)
        if "本会議" in title_text:
            committee = "本会議"
        else:
            title_committee_match = re.search(r"[\u4e00-\u9fff]+委員会", title_text)
            if title_committee_match:
                committee = title_committee_match.group(0)
        # 令和表記の日付（タイトルにある場合）
        reiwa_match = re.search(r"令和(\d+)年(\d+)月(\d+)日", title_text)
        if reiwa_match:
            year = 2018 + int(reiwa_match.group(1))
            date_str = f"{year:04d}-{int(reiwa_match.group(2)):02d}-{int(reiwa_match.group(3)):02d}"

    # ページ全体から西暦日付を探す（例: "2026年4月9日"）
    if not date_str:
        for tag in soup.find_all(string=re.compile(r"\d{4}年\d+月\d+日")):
            western_match = re.search(r"(\d{4})年(\d+)月(\d+)日", str(tag))
            if western_match:
                year = int(western_match.group(1))
                if 2000 <= year <= 2100:
                    m = int(western_match.group(2))
                    d = int(western_match.group(3))
                    date_str = f"{year:04d}-{m:02d}-{d:02d}"
                    break

    # 令和表記のフォールバック
    if not date_str:
        for tag in soup.find_all(string=re.compile(r"令和\d+年\d+月\d+日")):
            reiwa_match = re.search(r"令和(\d+)年(\d+)月(\d+)日", str(tag))
            if reiwa_match:
                year = 2018 + int(reiwa_match.group(1))
                rm = int(reiwa_match.group(2))
                rd = int(reiwa_match.group(3))
                date_str = f"{year:04d}-{rm:02d}-{rd:02d}"
                break

    # ページ内テキストから委員会名を探す
    if not committee:
        for tag in soup.find_all(["td", "th", "h1", "h2", "h3", "div"]):
            text = tag.get_text(strip=True)
            if "本会議" in text:
                committee = "本会議"
                break
            match = re.search(r"[\u4e00-\u9fff]+委員会", text)
            if match:
                committee = match.group(0)
                break

    # 所要時間: テーブル内 "XX時間XX分" または "XX分" のセル
    for tag in soup.find_all(string=re.compile(r"^\s*\d+時間\d+分\s*$")):
        duration = str(tag).strip()
        break

    if not committee:
        committee = "不明"
    if not date_str:
        logger.warning("Could not extract date for deli_id=%s", deli_id)
        date_str = "unknown"

    return committee, date_str, duration


def _extract_speakers(soup: BeautifulSoup, deli_id: str) -> list[SpeakerInfo]:
    """発言者リストを抽出する。

    実際のページ構造:
    <tr>
      <td></td>
      <td><a href="...&time=1310.4">森英介(衆議院議長)</a></td>
      <td>13時 02分</td>
      <td>01分</td>
    </tr>
    """
    speakers: list[SpeakerInfo] = []

    # time= パラメータを持つアンカータグを探す
    anchors = soup.find_all("a", href=re.compile(r"time=[\d.]+"))

    for anchor in anchors:
        href = anchor.get("href", "")
        time_match = re.search(r"time=([\d.]+)", href)
        if not time_match:
            continue

        start_seconds = float(time_match.group(1))
        raw_text = anchor.get_text(strip=True)

        if not raw_text:
            continue

        # "はじめから再生" 等の非発言者リンクをスキップ
        if raw_text in _NON_SPEAKER_TEXTS:
            continue

        name, affiliation = _parse_speaker_text(raw_text)
        if not name:
            continue

        # 発言者の開始時刻と所要時間はテーブルセルから取得する
        start_time, duration_minutes = _find_speaker_row_data(anchor)

        speakers.append(
            SpeakerInfo(
                name=name,
                affiliation=affiliation,
                start_seconds=start_seconds,
                start_time=start_time,
                duration_minutes=duration_minutes,
            )
        )

    logger.info("Extracted %d speakers for deli_id=%s", len(speakers), deli_id)
    return speakers


def _parse_speaker_text(text: str) -> tuple[str, str]:
    """アンカーテキストから名前と所属を分離する。

    例:
        "古川あおい(チームみらい)" -> ("古川あおい", "チームみらい")
        "伊藤孝恵(法務委員長)" -> ("伊藤孝恵", "法務委員長")
        "古川あおい" -> ("古川あおい", "")
    """
    match = re.match(r"^(.+?)\((.+)\)\s*$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text.strip(), ""


def _find_speaker_row_data(anchor_tag: object) -> tuple[str, int]:
    """アンカータグの親テーブル行から開始時刻と所要時間を取得する。

    Returns:
        (start_time, duration_minutes) のタプル
        取得できない場合は ("", 0)
    """
    parent = getattr(anchor_tag, "parent", None)
    for _ in range(5):
        if parent is None:
            break
        if getattr(parent, "name", None) == "tr":
            return _parse_table_row(parent)
        parent = getattr(parent, "parent", None)

    logger.warning(
        "Could not find parent <tr> for speaker anchor: %s",
        getattr(anchor_tag, "text", "")[:50],
    )
    return "", 0


def _parse_table_row(tr_tag: object) -> tuple[str, int]:
    """テーブル行のセルから開始時刻と所要時間を取得する。

    実際のセル構造: ['', '森英介(衆議院議長)', '13時 02分', '01分']
    """
    cells = getattr(tr_tag, "find_all", lambda *a, **k: [])("td")
    cell_texts = [c.get_text(strip=True) for c in cells]

    start_time = ""
    duration_minutes = 0

    for text in cell_texts:
        # 開始時刻: "13時 02分" または "HH:MM" 形式
        jtime_match = re.match(r"^(\d{1,2})時\s*(\d{2})分$", text)
        if jtime_match:
            h, m = int(jtime_match.group(1)), int(jtime_match.group(2))
            start_time = f"{h:02d}:{m:02d}"
            continue

        # HH:MM 形式
        if re.match(r"^\d{1,2}:\d{2}$", text):
            start_time = text
            continue

        # 所要時間: "01分" 形式
        duration_match = re.match(r"^(\d+)分$", text)
        if duration_match:
            duration_minutes = int(duration_match.group(1))

    return start_time, duration_minutes
