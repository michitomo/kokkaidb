# 国会議事録リアルタイムDB — Claude Code ガイド

## プロジェクト概要

衆議院TV（shugiintv.go.jp）・参議院TV（webtv.sangiin.go.jp）のアーカイブ動画から音声を抽出し、Whisper文字起こし + LLM構造化を行い、GitHub Pages上の静的サイトとして公開するシステム。公式会議録の公開タイムラグ（数週間〜数ヶ月）を解消し、質疑内容をリアルタイムにデータベース化する。

詳細な要件・設計は `ARCH.md` を参照。

---

## リポジトリ構成

```
kokkai-db/                          # このリポジトリ
├── CLAUDE.md                       # このファイル
├── ARCH.md                         # 要件定義・アーキテクチャ設計書（読取専用）
├── .github/workflows/
│   └── build-deploy.yml            # data/ push → Astro build → GitHub Pages
├── data/                           # 処理済みJSON（GitHub Actionsがgit pushする）
│   ├── shugiin/YYYY/MM/DD/{deli_id}_{委員会名}/
│   │   ├── metadata.json
│   │   ├── raw_transcript.json
│   │   ├── utterances.json
│   │   ├── qa_pairs.json
│   │   ├── summary.json
│   │   └── topics.json
│   └── sangiin/YYYY/MM/DD/{sid}_{委員会名}/
│       └── (同上)
├── kokkai-transcriber/             # データ収集・処理パイプライン（venv実行、本番はGitHub Actions）
│   ├── pyproject.toml
│   └── src/
│       ├── scrapers/
│       │   ├── base.py             # BaseScraper ABC
│       │   ├── shugiin.py          # 衆議院TV（EUC-JP、GET中心）
│       │   ├── sangiin.py          # 参議院TV（UTF-8、AJAX依存）
│       │   └── _sangiin_search.py  # 過去日付検索（Playwright、F5 ASM bypass）
│       ├── audio/
│       │   ├── extractor.py        # ffmpeg HLS/MP4 → WAVセグメント
│       │   └── sangiin_resolver.py # mediasp.jp hash → ストリームURL解決
│       ├── transcriber.py          # DeepInfra Whisper large-v3-turbo
│       ├── speaker_tagger.py       # LLM話者タグ付け（OpenRouter Gemma 4 31B-it）
│       ├── structurer.py           # LLM Q&Aペア生成（Gemini 3 Flash Preview）・要約・トピック生成（Gemma）
│       ├── publisher.py            # git commit + push
│       └── state.py                # SQLite状態管理
└── site/                           # Astroプロジェクト（静的サイト）
    ├── astro.config.mjs
    ├── package.json
    └── src/
        ├── pages/
        │   ├── index.astro
        │   ├── browse.astro
        │   ├── search.astro
        │   ├── settings.astro
        │   ├── dashboard/
        │   └── [chamber]/[year]/[month]/[day]/[slug].astro
        ├── components/
        │   ├── QAPairCard.astro
        │   ├── TimelineView.jsx    # React島
        │   ├── FilterPanel.jsx     # React島
        │   ├── DashboardCharts.jsx # React島（Recharts）
        │   ├── BYOKGate.jsx        # React島
        │   └── StreamingAnalysis.jsx
        └── lib/
            └── openrouter.js
```

---

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| データ収集 | Python 3.12+、requests、BeautifulSoup4、ffmpeg |
| 状態管理 | SQLite（両院統合、`chamber + session_id` 複合PK） |
| 文字起こし | DeepInfra Whisper large-v3-turbo（$0.0002/min） |
| LLM処理 (QA生成) | OpenRouter `google/gemini-3-flash-preview`（QA ペア生成 Step 6 のみ） |
| LLM処理 (その他) | OpenRouter `google/gemma-4-31b-it`（話者タグ・corrector・要約・topics・metrics） |
| SSG | Astro 5.x（Content Collections、partial hydration） |
| 検索 | Pagefind（静的CJK全文検索） |
| チャート | Recharts（React互換） |
| ネットワーク図 | D3 force-directed |
| BYOK LLM | OpenRouter（ブラウザから直接、sessionStorageのみ） |
| CI/CD | GitHub Actions（`data/` push トリガー） |
| ホスティング | GitHub Pages（無料、99.9% SLA） |

---

## コマンド

### データ収集パイプライン（kokkai-transcriber/）

実行環境は venv。本番は GitHub Actions 上で動く（`.github/workflows/batch.yml`、`schedule` cron で毎時起動）。

```bash
cd kokkai-transcriber

# 初回セットアップ
python -m venv .venv
source .venv/bin/activate
pip install -e .
# ffmpeg が必要（macOS: brew install ffmpeg、Linux: apt install ffmpeg）

# 参議院の過去日付検索を使う場合は browser extras + Chromium も必要
pip install -e '.[browser]' && python -m playwright install --with-deps chromium

# 特定セッションを手動処理
python -m src.pipeline --chamber shugiin --session-id 56149 --no-push

# 参議院
python -m src.pipeline --chamber sangiin --session-id 1234 --no-push

# バッチ（期間指定で並列処理）
python -m src.batch --chamber shugiin --since 2026-02-01 --workers 4 --no-push

# 状態確認
python -m src.state list

# 法案リスト（laws.json）の更新
python -m src.laws_builder --sessions 221

# テスト
python -m pytest
python -m pytest -m integration  # ネットワーク必須の統合テスト

# リント
ruff check src/ && mypy src/
```

### 静的サイト（site/）

```bash
cd site

# 依存関係インストール
npm ci

# 開発サーバー
npm run dev

# ビルド
npm run build

# Pagefindインデックス生成
npx pagefind --site dist --glob "**/*.html"

# プレビュー
npm run preview

# 型チェック
npm run check
```

---

## アーキテクチャ上の重要な決定事項

### 静的サイト完結
サーバーサイドプロセスなし。すべての動的機能はクライアントサイドJS（React島）またはビルド時生成で実現。APIエンドポイントは `site/public/api/*.json` として静的ファイルで提供。

### 両院抽象化
`BaseScraper` ABCで両院のインターフェースを統一。`detect_new_sessions(date)` / `get_session_detail(session_id)` / `get_audio_url(session_id)` の3メソッドが必須。院固有の差異（EUC-JP vs UTF-8、HLS直接 vs mediasp.jp hash）は各Scraper実装が吸収。

### 衆議院スクレイピング注意事項
- サイトはEUC-JPエンコーディング。`response.encoding = 'euc-jp'` を明示すること
- カレンダー経由のGET（`u_day=YYYYMMDD`）が安定。JavaScriptドリブンの検索フォームは使用しない
- HLS URLは `hidden input #vtag_src_base_vod` のvalue属性から取得

### 参議院スクレイピング注意事項
- 正規ホスト名は `www.webtv.sangiin.go.jp` (`webtv.sangiin.go.jp` は環境により名前解決不可)
- `detail.php?sid=XXXX` の GET は安定。発言者リストは `class="play2"` のアンカーから抽出
- **動画 URL 解決**: `public.mediasp.jp/v1/player?hash=XXX` のレスポンス本文に `video_info[0].url` として m3u8 URL が直書きされている。`audio/sangiin_resolver.py` の regex で抽出可能 (Playwright 不要)
- 実 m3u8 ホスト: `sangiin-vod.live.ipcasting.jp` (IIJ Media Service Provider 経由)
- **過去日付のセッション検出**: POST `keyword_search.php` が F5 BIG-IP ASM Bot Defense で保護されている。素の HTTP では弾かれるため Playwright + playwright-stealth + 信頼イベント (real mouse click) でフォーム送信する (`src/scrapers/_sangiin_search.py`)。`detect_new_sessions(date)` は本日 (JST) のみ GET 軽量経路、それ以外は Playwright 経路に自動分岐
- 本日分は `result_selecter.php?mode=today_reload` の GET で取れる (`absdate` は実質無視され今日分のみ返る仕様)

### Tier 0 / Tier 1 分離
- **Tier 0**: キー不要。ビルド時生成の全データを閲覧・検索・フィルタ。完全独立プロダクト
- **Tier 1**: OpenRouter APIキー入力後にLLM分析機能をアンロック。キーは `sessionStorage` のみ（タブ閉じで消去）。サーバーには絶対送信しない

### 出所明示（著作権法第48条対応）
全ページに衆議院TV / 参議院TVへのソースリンクを表示。セッションデータの `source_url` フィールドを必ず使用。

---

## データモデル

`data/{chamber}/YYYY/MM/DD/{id}_{委員会名}/` 以下の各JSONファイルの詳細スキーマは `ARCH.md` §4.4 を参照。

---

## 外部サービス・エンドポイント

| サービス | 用途 | 認証 |
|---------|------|------|
| `hlsvod.shugiintv.go.jp` | 衆議院HLS音声 | なし |
| `public.mediasp.jp/v1/player` | 参議院動画 (hash → m3u8 URL) | なし (regex で本文から抽出、Playwright 不要) |
| `sangiin-vod.live.ipcasting.jp` | 参議院 HLS 配信 (IIJ MSP) | なし |
| `www.webtv.sangiin.go.jp` (POST `keyword_search.php`) | 参議院 過去日付セッション検索 | なし (Playwright + stealth で F5 ASM bypass) |
| DeepInfra Whisper | 文字起こし (Step 3/4) | `DEEPINFRA_API_KEY` |
| OpenRouter `google/gemini-3-flash-preview` | QA ペア生成 (Step 6 generate_qa_pairs のみ) | `OPENROUTER_API_KEY` |
| OpenRouter `google/gemma-4-31b-it` | 話者タグ・corrector・要約・topics・metrics (Step 4.5/5/6) | `OPENROUTER_API_KEY` |
| OpenRouter | BYOK LLM（ブラウザのみ） | ユーザー入力キー |

環境変数は `kokkai-transcriber/.env`（gitignore済み）に配置。`DEEPINFRA_API_KEY` (Whisper) と `OPENROUTER_API_KEY` (LLM) の両方が必須。

---

---

## コーディング規約

### Python（kokkai-transcriber/）
- Python 3.12+。型アノテーション必須
- フォーマッタ: `ruff format`、リンタ: `ruff check`、型チェック: `mypy`
- 依存関係は `pyproject.toml`（`uv` 推奨）
- `BaseScraper` ABCの3メソッドシグネチャを変更しない
- エンコーディング処理は各Scraper内に閉じ込める（共通コードに漏らさない）
- ffmpegはサブプロセス呼び出し（`subprocess.run`）。エラーは `CalledProcessError` で拾う

### JavaScript/TypeScript（site/）
- Astroコンポーネントはサーバーサイドロジックを持たない（静的サイト）
- インタラクティブ部分のみReact島（`client:load` or `client:visible`）
- OpenRouterのAPIキーは `sessionStorage` のみ。`localStorage` 禁止
- `openrouter.js` の `OpenRouterClient` クラスを通じてのみAPIアクセス
- チャートはRecharts（Reactコンポーネント）、ネットワーク図はD3
- SSRモードは使用しない（`output: 'static'`）
