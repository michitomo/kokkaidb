# Phase 3: 参議院対応 — 実装・テスト計画

> **目標**: 参議院TV（webtv.sangiin.go.jp）のスクレイピング・音声取得パイプラインを実装し、衆議院と同一の共通パイプライン（Whisper→話者タグ→構造化）で処理できるようにする。
> **所要期間**: 1-2日
> **前提**:
> - Phase 1（衆議院パイプラインPoC）が完了し、`pipeline.py` が衆議院セッションを正常処理できること
> - Phase 2（Docker化 + サイト基盤 + Scraper抽象化）が完了し、`BaseScraper` ABC / `SangiinScraper` スタブ / SQLite状態管理 / Astroサイト基盤が存在すること
> - `DEEPINFRA_API_KEY` が利用可能であること
> - ffmpeg がインストール済みであること

---

## 成果物

Phase 3 完了時に以下が揃う:

1. `kokkai-transcriber/src/scrapers/sangiin.py` — `SangiinScraper` 実装（`BaseScraper` ABC 準拠）
2. `kokkai-transcriber/src/audio/sangiin_resolver.py` — mediasp.jp hash → ストリームURL 解決
3. `data/sangiin/YYYY/MM/DD/{sid}_{委員会名}/` 配下に6つのJSON（metadata, raw_transcript, utterances, qa_pairs, summary, topics）
4. 参議院セッションの単体テスト・結合テスト
5. `pipeline.py` が `--chamber sangiin --session-id XXXX` で参議院を処理できること
6. Astroサイトで両院のセッションが統合表示されること

---

## 背景知識: 衆議院との差異

実装前に以下の差異を理解しておくこと。これを正しく処理するのが Phase 3 の核心。

| 項目 | 衆議院TV | 参議院TV |
|------|---------|---------|
| サイトURL | `shugiintv.go.jp` | `webtv.sangiin.go.jp` |
| エンコーディング | EUC-JP（`response.encoding = 'euc-jp'` 必須） | UTF-8（特別な処理不要） |
| セッションID | `deli_id`（数値） | `sid`（数値） |
| 詳細ページ | `index.php?ex=VL&deli_id=XXXXX` | `detail.php?sid=XXXX` |
| 発言者リンク | `<A HREF="...&time=N">名前(所属)</A>` | `<a href='#N' class='play2'>名前(所属)</a>` |
| タイムスタンプ | URLパラメータ `time=7320.2` | フラグメント `#1850.95` |
| 動画配信 | 自前HLS（`hlsvod.shugiintv.go.jp`、URLがHTMLに直書き） | 外部SaaS `mediasp.jp`（hashパラメータ、動的生成） |
| セッション検出 | `calendar.php?mon=YYYYMM` → `u_day` GET | `result_selecter.php?mode=today_reload&absdate=YYYY-MM-DD` GET |
| カレンダー月移動 | GETで完結 | cookie/セッション依存あり |
| ビデオリンクURL | `shugiintv.go.jp/...&time=N` | `webtv.sangiin.go.jp/detail.php?sid=XXXX#N` |

---

## ステップ

### Step 1: 参議院TV詳細ページの調査・HTMLフィクスチャ取得

**やること:**
- ブラウザで `https://webtv.sangiin.go.jp/webtv/detail.php?sid=XXXX` にアクセスし、実際のHTML構造を確認する
  - テスト用に適切な `sid` を1つ選ぶ（開催日が近い委員会セッションが望ましい）
- ページソースを保存し、`tests/fixtures/sangiin_{sid}.html` として配置
- 以下を確認・記録:
  - [ ] `class="play2"` アンカータグの実際のHTML構造
  - [ ] フラグメント `#秒数` の形式（整数か小数か）
  - [ ] 発言者テキストの形式（名前とカッコの間にスペースがあるか等）
  - [ ] mediasp.jp の `<script>` タグの場所と `hash` パラメータの形式
  - [ ] 委員会名・日付がページのどこに記載されているか
  - [ ] カレンダー `result_selecter.php?mode=today_reload&absdate=YYYY-MM-DD` のレスポンス形式

**出力:** テスト用HTMLフィクスチャファイル + 発見事項のメモ（コード内コメントで十分）

**注意:**
- ARCH.md セクション3.3 の記述が実際のHTMLと異なる場合がある。**実際のHTMLを信頼する**。差異があれば ARCH.md にコメントを残す
- `detail.php?sid=XXXX` のGETアクセスは安定しているとARCH.mdに記載あり

---

### Step 2: SangiinScraper — セッション詳細ページのスクレイピング

**やること:**
- `kokkai-transcriber/src/scrapers/sangiin.py` に `SangiinScraper` クラスを実装する
- Phase 2 で定義済みの `BaseScraper` ABC を継承し、以下の3メソッドを実装:

#### 2a: `get_session_detail(session_id: str) -> SessionDetail`

- URL: `https://webtv.sangiin.go.jp/webtv/detail.php?sid={session_id}`
- エンコーディング: UTF-8（Pythonデフォルトで OK、明示設定不要）
- BeautifulSoup4 でHTMLをパースし、以下を抽出:
  - **発言者リスト**: `class="play2"` のアンカー要素
    ```python
    anchors = soup.find_all("a", class_="play2")
    ```
  - **タイムスタンプ**: `href` 属性のフラグメント部分（`#1850.95` → `1850.95`）
    ```python
    href = anchor.get("href", "")
    if href.startswith("#"):
        start_seconds = float(href[1:])
    ```
  - **発言者名・所属**: アンカーテキストを `_parse_speaker_text()` でパース（衆議院と同じロジック）
  - **mediasp.jp hash**: `<script src="...public.mediasp.jp/v1/player?hash=...">` タグから抽出
    ```python
    script_tag = soup.find("script", src=re.compile(r"mediasp\.jp"))
    hash_match = re.search(r"hash=([a-zA-Z0-9]+)", script_tag["src"])
    ```
  - **委員会名**: ページ内の適切な要素から（Step 1 の調査結果に基づく）
  - **日付**: ページ内テキストから `令和X年Y月Z日` or `YYYY年M月D日` パターンで抽出

**出力フィールド（SessionDetail）:**

| フィールド | 値 |
|-----------|-----|
| `chamber` | `"sangiin"` |
| `session_id` | sid値（文字列） |
| `date` | `YYYY-MM-DD` |
| `committee` | 委員会名 |
| `hls_url` | **空文字列**（この時点では未解決。Step 3 で別途解決） |
| `source_url` | `https://webtv.sangiin.go.jp/webtv/detail.php?sid={sid}` |
| `speakers` | `SpeakerInfo` のリスト |

**重要**: `hls_url` は `get_session_detail` では空で返す。音声URLの解決は `sangiin_resolver.py` の責務とする（mediasp.jp の解決が複雑なため分離）。

**`_parse_speaker_text()` の共通化について:**
- 衆議院スクレイパーの `_parse_speaker_text()` と同一ロジックが使える。Phase 2 で `BaseScraper` に移動済みならそれを使う。未移動なら `sangiin.py` 内にコピーして実装し、後で共通化する（共通化はこのステップの範囲外）。

#### 2b: `detect_new_sessions(date: str) -> list[str]`

- URL: `https://webtv.sangiin.go.jp/webtv/result_selecter.php?mode=today_reload&absdate={date}`
  - `date` は `YYYY-MM-DD` 形式
- レスポンスからセッションID（`sid`）のリストを抽出する
- レスポンス形式は Step 1 の調査で確定する（HTML断片 or JSON）
- 抽出パターン例: `detail.php?sid=` を含むリンクから sid を取得

**注意:**
- `result_selecter.php` はAJAXレスポンスの可能性がある。HTMLフラグメントかJSONかを Step 1 で確認する
- cookie/セッション依存の可能性がある。依存する場合は `requests.Session()` を使い、先に `webtv.sangiin.go.jp` にアクセスしてcookieを取得する

#### 2c: `get_audio_url(session_id: str) -> str`

- 内部で `sangiin_resolver.py` の `resolve_stream_url()` を呼ぶ（Step 3 で実装）
- このメソッド自体は薄いラッパー

**テスト:**
- `tests/fixtures/sangiin_{sid}.html` を使った単体テスト（`tests/test_sangiin_scraper.py`）
  - 発言者リストが正しい数・順序で抽出されること
  - タイムスタンプが float で正しくパースされること
  - 名前・所属の分離が正しいこと（`伊藤孝江(法務委員長)` → name=`伊藤孝江`, affiliation=`法務委員長`）
  - mediasp.jp hash が正しく抽出されること
  - UTF-8 なので日本語文字列はそのまま正しく読めること
- `detect_new_sessions` のレスポンスフィクスチャを使ったテスト
- 実際の sangiin サイトへの結合テスト（`pytest.mark.integration`）

---

### Step 3: mediasp.jp 音声URL解決

**やること:**
- `kokkai-transcriber/src/audio/sangiin_resolver.py` に `resolve_stream_url(mediasp_hash: str) -> str` を実装
- これは Phase 3 で**最も不確実性が高い**ステップ。以下の3つの方法を順に試す

#### 方法A: mediasp.jp API リバースエンジニアリング（推奨、まずこれを試す）

1. ブラウザの DevTools Network タブで参議院TVの動画ページを開く
2. mediasp.jp へのリクエストを観察し、HLS/MP4 の実URLパターンを特定する
3. 典型的なパターン:
   ```
   https://public.mediasp.jp/v1/player?hash={hash}
   → JavaScript内で実際のストリームURLを構築
   → https://vod.mediasp.jp/.../{hash}/playlist.m3u8 のようなパターン
   ```
4. パターンが特定できたら、Pythonで直接URLを組み立てる

**実装例（パターンが判明した場合）:**
```python
def resolve_stream_url(mediasp_hash: str) -> str:
    """mediasp.jp の hash から HLS ストリーム URL を解決する。"""
    # Step 1: player.js を取得してストリームURLパターンを抽出
    player_url = f"https://public.mediasp.jp/v1/player?hash={mediasp_hash}"
    response = requests.get(player_url, timeout=30)
    
    # player.js 内から実際のストリームURLを正規表現で抽出
    # （具体的なパターンは調査結果に依存）
    match = re.search(r'"(https?://[^"]+\.m3u8[^"]*)"', response.text)
    if match:
        return match.group(1)
    
    raise ValueError(f"Could not resolve stream URL for hash={mediasp_hash}")
```

#### 方法B: Playwright によるヘッドレスブラウザ（方法Aが失敗した場合）

1. `playwright` を依存関係に追加（`pyproject.toml`）
2. ヘッドレスブラウザでページをロードし、ネットワークリクエストをインターセプトする

```python
from playwright.sync_api import sync_playwright

def resolve_stream_url_playwright(sid: str) -> str:
    """Playwright でネットワークリクエストから HLS URL を取得する。"""
    stream_url = None
    
    def handle_response(response):
        nonlocal stream_url
        if ".m3u8" in response.url or ".mp4" in response.url:
            stream_url = response.url
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("response", handle_response)
        page.goto(f"https://webtv.sangiin.go.jp/webtv/detail.php?sid={sid}")
        page.wait_for_timeout(5000)  # mediasp.js ロード待ち
        browser.close()
    
    if not stream_url:
        raise ValueError(f"Could not intercept stream URL for sid={sid}")
    return stream_url
```

**Playwright 使用時の追加手順:**
- `pyproject.toml` に `playwright` を追加
- `Dockerfile` に `playwright install --with-deps chromium` を追加
- CI/テストでは `playwright install chromium` を事前実行

#### 方法C: 手動URL確認 + 設定ファイル（最終手段）

- ブラウザ DevTools で手動確認した URL パターンをハードコードまたは設定ファイルで管理
- Phase 3 のPoCとしては許容するが、自動化には向かない

**判断基準:**
1. まず方法Aを試す（30分程度の調査）
2. 方法Aで安定したパターンが見つからなければ方法Bに切り替え
3. 方法Bも困難なら方法Cで Phase 3 を先に進め、自動化は後日

**テスト:**
- 方法A の場合: mediasp.jp レスポンスのモックフィクスチャを使った単体テスト
- 方法B の場合: Playwright のモックは複雑なため、結合テスト（`pytest.mark.integration`）のみ
- いずれの場合も: 返り値が有効な URL（`http` or `https` 始まり、`.m3u8` or `.mp4` 含む）であることをアサート

---

### Step 4: パイプラインの両院対応

**やること:**
- `pipeline.py` を修正し、`--chamber` 引数に応じて衆議院/参議院のスクレイパーを切り替えるようにする

#### 4a: `pipeline.py` の修正

現在の `pipeline.py` は衆議院専用（`shugiin.py` の `get_session_detail` を直接インポート）。以下のように変更:

```python
# 変更前
from src.scrapers.shugiin import get_session_detail

# 変更後
from src.scrapers.base import BaseScraper
from src.scrapers.shugiin import ShugiinScraper
from src.scrapers.sangiin import SangiinScraper

def _get_scraper(chamber: str) -> BaseScraper:
    if chamber == "shugiin":
        return ShugiinScraper()
    elif chamber == "sangiin":
        return SangiinScraper()
    else:
        raise ValueError(f"Unknown chamber: {chamber}")
```

CLI引数の変更:
```
# 変更前
python -m src.pipeline --deli-id 56149 --output-dir data/shugiin/...

# 変更後
python -m src.pipeline --chamber shugiin --session-id 56149
python -m src.pipeline --chamber sangiin --session-id XXXX
```

- `--output-dir` は自動生成する: `data/{chamber}/YYYY/MM/DD/{session_id}_{committee}/`
- `--deli-id` は `--session-id` にリネーム（両院共通の概念）

#### 4b: `speaker_tagger.py` の video_url 修正

現在 `tag_all_segments` 内で衆議院TVのURL形式がハードコードされている:
```python
# 現在のコード（kokkai-transcriber/src/speaker_tagger.py:147-149）
video_url = (
    f"https://www.shugiintv.go.jp/jp/index.php"
    f"?ex=VL&media_type=&deli_id={deli_id}&time={seg.start_seconds}"
)
```

これを院に応じて切り替える:
```python
def _build_video_url(chamber: str, session_id: str, start_seconds: float) -> str:
    if chamber == "shugiin":
        return (
            f"https://www.shugiintv.go.jp/jp/index.php"
            f"?ex=VL&media_type=&deli_id={session_id}&time={start_seconds}"
        )
    elif chamber == "sangiin":
        return (
            f"https://webtv.sangiin.go.jp/webtv/detail.php"
            f"?sid={session_id}#{start_seconds}"
        )
    return ""
```

`tag_all_segments` の引数に `chamber` を追加するか、`session_detail.chamber` を参照する。

#### 4c: 音声取得フローの分岐

参議院の場合、音声取得フローが異なる:
1. `get_session_detail` で mediasp.jp hash を取得（`hls_url` は空）
2. `sangiin_resolver.resolve_stream_url(hash)` でストリームURL を解決
3. 解決後のURLを `download_full_audio` に渡す（ffmpeg 処理は共通）

`pipeline.py` 内で以下の分岐を追加:

```python
if session_detail.chamber == "sangiin" and not session_detail.hls_url:
    from src.audio.sangiin_resolver import resolve_stream_url
    # mediasp_hash は SessionDetail に追加フィールドとして格納するか、
    # SangiinScraper.get_audio_url(session_id) で取得
    audio_url = scraper.get_audio_url(session_id)
else:
    audio_url = session_detail.hls_url

download_full_audio(audio_url, full_wav)
```

#### 4d: models.py への追加フィールド（必要な場合）

`SessionDetail` に参議院固有のフィールドが必要かを検討:
- `mediasp_hash: str = ""` — mediasp.jp の hash 値（参議院のみ）

これは Step 1 の調査結果に依存する。`get_audio_url()` メソッドで完結できるなら追加不要。

**テスト:**
- `pipeline.py` の `--chamber sangiin` ルートの単体テスト（全外部依存モック）
- `_build_video_url` の両院パターンのテスト
- 引数パースのテスト（`--chamber` + `--session-id`）

---

### Step 5: 参議院セッションの結合テスト

**やること:**
- Step 1 で選んだ `sid` を使って、実際に全パイプラインを実行する

```bash
# 実行コマンド
docker compose run --rm transcriber python -m src.pipeline \
  --chamber sangiin --session-id {sid}
```

- 出力された JSON を検証:
  - [ ] `metadata.json` — `chamber` が `"sangiin"`、`source_url` が参議院TVのURL、speakers の数がページと一致
  - [ ] `raw_transcript.json` — 日本語として読める文字起こし
  - [ ] `utterances.json` — 話者タグが正しい、`video_url` が参議院TVのフォーマット（`detail.php?sid=XXXX#N`）
  - [ ] `qa_pairs.json` — Q&Aペアが妥当、video_url が正しい
  - [ ] `summary.json` — 要約が的確
  - [ ] `topics.json` — トピックの粒度が適切

- 衆議院の既存パイプラインが壊れていないことも確認:
  ```bash
  docker compose run --rm transcriber python -m src.pipeline \
    --chamber shugiin --session-id 56149
  ```

**テスト:**
- 参議院 + 衆議院の両方の結合テスト（`pytest.mark.integration`）
- SQLite状態管理が `(chamber='sangiin', session_id='{sid}')` で正しく記録されること

---

### Step 6: Astroサイトの両院統合表示確認

**やること:**
- `data/sangiin/` に出力された JSON が Astro のビルドで正しく読み込まれることを確認
- 以下のページが正常に動作すること:
  - [ ] `/` — トップページに衆議院・参議院両方のセッションが表示される
  - [ ] `/browse` — 院フィルタで「参議院」を選択した場合に参議院のみ表示される
  - [ ] `/sangiin/YYYY/MM/DD/{slug}` — 参議院セッション詳細ページが表示される
  - [ ] `/search` — 参議院セッション内の発言が Pagefind で検索可能
  - [ ] Q&Aカードの動画リンクが参議院TV（`webtv.sangiin.go.jp`）を指していること
  - [ ] 出所明示: 各ページに参議院TVへのソースリンクが表示されていること

```bash
cd site
npm run build
npx pagefind --site dist --glob "**/*.html"
npm run preview
# ブラウザで確認
```

**注意:**
- Phase 2 で Astro サイトが `data/{chamber}/` のディレクトリ構造を正しくハンドルしていれば、大きな変更は不要のはず
- `[chamber]/[year]/[month]/[day]/[slug].astro` の動的ルートが `sangiin` を受け付けることを確認

---

## テスト構成

```
kokkai-transcriber/
├── tests/
│   ├── fixtures/
│   │   ├── sangiin_{sid}.html           # 参議院詳細ページのHTMLフィクスチャ
│   │   ├── sangiin_calendar.html        # カレンダー/セッション一覧のフィクスチャ
│   │   └── mediasp_player.js            # mediasp.jp player スクリプトのフィクスチャ
│   ├── test_sangiin_scraper.py          # Step 2
│   ├── test_sangiin_resolver.py         # Step 3
│   └── test_pipeline.py                 # Step 4（既存テストに参議院ケースを追加）
```

**テスト方針:**
- 外部依存（webtv.sangiin.go.jp、mediasp.jp、DeepInfra API、ffmpeg）はデフォルトでモック
- `pytest.mark.integration` で結合テストを分離
- フィクスチャ HTML は実際のページを保存（Step 1 で取得）
- Pydantic バリデーションでスキーマの正しさを保証

```bash
# 単体テストのみ
cd kokkai-transcriber && python -m pytest tests/test_sangiin_scraper.py tests/test_sangiin_resolver.py -m "not integration"

# 結合テスト（ネットワーク + API キー必要）
cd kokkai-transcriber && python -m pytest -m integration

# 全テスト（衆議院 + 参議院）
cd kokkai-transcriber && python -m pytest

# リント・型チェック
cd kokkai-transcriber && ruff check src/ && mypy src/
```

---

## ファイル変更一覧

### 新規作成

| ファイル | 内容 |
|---------|------|
| `src/scrapers/sangiin.py` | `SangiinScraper` クラス（`BaseScraper` 継承） |
| `src/audio/sangiin_resolver.py` | mediasp.jp hash → ストリームURL解決 |
| `tests/fixtures/sangiin_{sid}.html` | 参議院詳細ページHTMLフィクスチャ |
| `tests/fixtures/sangiin_calendar.html` | セッション一覧フィクスチャ |
| `tests/fixtures/mediasp_player.js` | mediasp.jp スクリプトフィクスチャ |
| `tests/test_sangiin_scraper.py` | SangiinScraper 単体テスト |
| `tests/test_sangiin_resolver.py` | sangiin_resolver 単体テスト |

### 変更

| ファイル | 変更内容 |
|---------|---------|
| `src/pipeline.py` | `--chamber` 引数追加、院による分岐、`--deli-id` → `--session-id` リネーム |
| `src/speaker_tagger.py` | `_build_video_url()` 追加、`tag_all_segments` の video_url 生成を院別に |
| `src/models.py` | `SessionDetail` に `mediasp_hash: str = ""` 追加（必要な場合のみ） |
| `pyproject.toml` | `playwright` 依存追加（方法B選択時のみ） |
| `Dockerfile` | Playwright + Chromium インストール追加（方法B選択時のみ） |
| `tests/test_pipeline.py` | 参議院パイプラインのテストケース追加 |

---

## リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| mediasp.jp のストリームURL解決が困難 | 音声取得不可 | 3段階の方法（API解析→Playwright→手動）で段階的に対応。最悪は手動URLで PoC を先行 |
| mediasp.jp がアクセス制限をかけている | URLは解決できても音声DL失敗 | User-Agent設定、リファラ設定で対応。ffmpegの`-headers`オプション |
| `detail.php?sid=XXXX` のHTML構造がARCH.mdの記述と異なる | スクレイピングロジック再設計 | Step 1 で実HTMLを先に確認。フィクスチャベースで開発 |
| `result_selecter.php` がcookie/セッション依存 | セッション検出失敗 | `requests.Session()` でcookie管理。難しければ `detail.php?sid=N` の連番巡回にフォールバック |
| Playwright導入によるDockerイメージ肥大化 | ビルド時間・ディスク増 | 方法Aが成功すればPlaywright不要。方法B選択時はmulti-stage buildで軽量化 |
| 参議院TV と衆議院TV で発言者テキストの書式が微妙に異なる | パースエラー | 全角/半角カッコ、スペースの有無等を正規表現で吸収。フィクスチャに複数パターンを含める |
| 既存の衆議院パイプラインが `pipeline.py` 変更でリグレッション | 衆議院処理が壊れる | Step 5 で衆議院の回帰テストも実施。既存テストが通ることを確認 |

---

## 判断が必要なポイント（実装者メモ）

Phase 3 の実装中に以下の判断が必要になる。判断に迷ったら先に進めず、レビューを依頼すること。

1. **mediasp.jp 解決方法の選択**: 方法A/B/Cのどれにするか。30分調査して方法Aが無理なら方法Bに移行。方法Bも1時間以内に動かなければ方法Cで先に進む
2. **`_parse_speaker_text()` の共通化**: Phase 2 で既に `BaseScraper` に移動済みかどうかで対応が変わる。移動済みなら使う、未移動ならコピーで先に進む
3. **`SessionDetail` への `mediasp_hash` 追加**: `get_audio_url()` で完結するなら不要。resolver の呼び出しに hash が必要で、かつ `get_session_detail` の時点で取得できるなら追加する
4. **Playwright の Docker 対応**: 方法B を選択した場合のみ。Dockerfile の変更が大きいので、方法B確定後に着手する
