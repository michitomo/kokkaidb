"""参議院TVの過去日付検索 (Playwright 経由)

POST `keyword_search.php` は F5 BIG-IP ASM Bot Defense で保護されており、
素の HTTP クライアント (urllib / requests / curl_cffi) はサーバ側で
"Request Rejected" を返される。WAF を通すには:

1. ブラウザで JS チャレンジを実行して TS Cookie を有効化する
2. 検索ボタンを **信頼イベント (isTrusted=true)** で発火させる

の両方が必要。Playwright + playwright-stealth + 実マウスクリックでこの
要件を満たし、検索結果 HTML をネットワークインターセプトで回収する。

ヘッドレス検知も `playwright-stealth` の各種パッチで回避済み。

依存: `pip install -e .[browser]` && `playwright install chromium`
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_INDEX_URL = "https://www.webtv.sangiin.go.jp/webtv/index.php"
_SID_PATTERN = re.compile(r"detail\.php\?sid=(\d+)")
_REJECTED_MARKER = "Request Rejected"


def discover_sids_for_date(date: str, *, timeout_ms: int = 30_000) -> list[str]:
    """指定日の sid をすべて返す (Playwright 必須)。

    Args:
        date: YYYY-MM-DD
        timeout_ms: ページ操作・応答待ちの個別タイムアウト

    Returns:
        sid 文字列の昇順リスト。該当なしなら []。

    Raises:
        RuntimeError: playwright / playwright-stealth が未インストールの場合、
                       または WAF 遮断で空応答しか得られなかった場合。
    """
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
    except ImportError as e:
        raise RuntimeError(
            "playwright and playwright-stealth are required for past-date "
            "Sangiin session discovery. Install with: "
            "pip install -e '.[browser]' && playwright install --with-deps chromium"
        ) from e

    y, mo, d = date.split("-")
    # 形式バリデーション (失敗時は ValueError)
    int(y)
    int(mo)
    int(d)

    captured: list[str] = []

    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                # F5 ASM のヘッドレス検知を緩めるための定番フラグ。
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            ctx = browser.new_context(
                viewport={"width": 1366, "height": 768},
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
            )
            page = ctx.new_page()

            def _on_response(resp: object) -> None:
                req = getattr(resp, "request", None)
                url = getattr(resp, "url", "")
                method = getattr(req, "method", "") if req else ""
                if "keyword_search.php" not in url or method != "POST":
                    return
                try:
                    captured.append(resp.text())  # type: ignore[attr-defined]
                except Exception:
                    pass

            page.on("response", _on_response)

            page.goto(_INDEX_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            # init_search() の AJAX が #sel_s_year を挿入するのを待つ。
            page.wait_for_function(
                "() => !!document.getElementById('sel_s_year')",
                timeout=timeout_ms,
            )
            page.wait_for_timeout(1500)

            # 詳細検索パネルを開く (信頼イベントで)
            page.click("#detail-search")
            page.wait_for_timeout(700)

            # 日選択 option を再構築 (本来は date_future_check が onChange で
            # 動的に再生成するが、Playwright での option 操作と相性が悪いため
            # 全月共通で 1〜31 日を入れて目的の値を選ぶ)。
            page.evaluate(
                "() => {"
                "  const j = window.jQuery;"
                "  j('#sel_s_day').empty(); j('#sel_e_day').empty();"
                "  for (let i=1;i<=31;i++) {"
                "    j('#sel_s_day').append('<option value=\"'+i+'\">'+i+'</option>');"
                "    j('#sel_e_day').append('<option value=\"'+i+'\">'+i+'</option>');"
                "  }"
                "}"
            )
            page.select_option("#sel_s_year", y)
            page.select_option("#sel_e_year", y)
            page.select_option("#sel_s_month", str(int(mo)))
            page.select_option("#sel_e_month", str(int(mo)))
            page.select_option("#sel_s_day", str(int(d)))
            page.select_option("#sel_e_day", str(int(d)))

            # 信頼イベントで検索ボタンをクリック → keyword_search.php POST 発火。
            with page.expect_response(
                lambda r: ("keyword_search.php" in r.url
                           and r.request.method == "POST"),
                timeout=timeout_ms,
            ) as resp_info:
                page.click("input[name='btn_search']")
            resp_info.value  # 応答取得まで block

            # ページネーションが続く場合に備えて短く待機。
            page.wait_for_timeout(1500)
        finally:
            browser.close()

    return _parse_search_responses(captured, date)


def _parse_search_responses(html_responses: list[str], date: str) -> list[str]:
    """keyword_search.php の応答 HTML 群から sid を抽出する。

    WAF が遮断した場合は応答ボディが
    `<html><head><title>Request Rejected</title>...` の数百バイトしかない。
    これを検知したら例外。
    """
    if not html_responses:
        raise RuntimeError(f"No keyword_search.php response captured for date={date}")

    sids: set[str] = set()
    rejected = 0
    for html in html_responses:
        if _REJECTED_MARKER in html[:500]:
            rejected += 1
            continue
        for sid in _SID_PATTERN.findall(html):
            sids.add(sid)

    if rejected and not sids:
        raise RuntimeError(
            f"All keyword_search.php responses were WAF-rejected for date={date} "
            f"({rejected}/{len(html_responses)}). Headless detection may have updated; "
            "review playwright-stealth or browser fingerprint."
        )
    return sorted(sids)
