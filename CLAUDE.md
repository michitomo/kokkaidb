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
├── data/                           # 処理済みJSON（Dockerがgit pushする）
│   ├── shugiin/YYYY/MM/DD/{deli_id}_{委員会名}/
│   │   ├── metadata.json
│   │   ├── raw_transcript.json
│   │   ├── utterances.json
│   │   ├── qa_pairs.json
│   │   ├── summary.json
│   │   └── topics.json
│   └── sangiin/YYYY/MM/DD/{sid}_{委員会名}/
│       └── (同上)
├── kokkai-transcriber/             # Dockerコンテナ（データ収集・処理パイプライン）
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── pyproject.toml
│   └── src/
│       ├── scrapers/
│       │   ├── base.py             # BaseScraper ABC
│       │   ├── shugiin.py          # 衆議院TV（EUC-JP、GET中心）
│       │   └── sangiin.py          # 参議院TV（UTF-8、AJAX依存）
│       ├── audio/
│       │   ├── extractor.py        # ffmpeg HLS/MP4 → WAVセグメント
│       │   └── sangiin_resolver.py # mediasp.jp hash → ストリームURL解決
│       ├── transcriber.py          # DeepInfra Whisper large-v3-turbo
│       ├── speaker_tagger.py       # LLM話者タグ付け（DeepSeek V3.2）
│       ├── structurer.py           # LLM Q&Aペア・要約・トピック生成
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
| LLM処理 | DeepInfra DeepSeek V3.2（話者タグ・構造化・要約） |
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

```bash
# Docker起動
docker compose up -d

# 特定セッションを手動処理（Phase 1 PoC用）
docker compose run --rm transcriber python -m src.pipeline --chamber shugiin --session-id 56149

# 参議院
docker compose run --rm transcriber python -m src.pipeline --chamber sangiin --session-id 1234

# 状態確認
docker compose run --rm transcriber python -m src.state list

# テスト
cd kokkai-transcriber && python -m pytest

# リント
cd kokkai-transcriber && ruff check src/ && mypy src/
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
- `detail.php?sid=XXXX` のGETは安定。発言者リストは `class="play2"` のアンカーから抽出
- 動画はmediasp.jp外部SaaSホスト。音声URL取得にはPlaywright（headless browser）またはAPIリバースエンジニアリングが必要（Phase 3で確定）
- AJAX依存箇所（カレンダー月移動等）はsession/cookie管理が必要

### Tier 0 / Tier 1 分離
- **Tier 0**: キー不要。ビルド時生成の全データを閲覧・検索・フィルタ。完全独立プロダクト
- **Tier 1**: OpenRouter APIキー入力後にLLM分析機能をアンロック。キーは `sessionStorage` のみ（タブ閉じで消去）。サーバーには絶対送信しない

### 出所明示（著作権法第48条対応）
全ページに衆議院TV / 参議院TVへのソースリンクを表示。セッションデータの `source_url` フィールドを必ず使用。

---

## データモデル

### `data/{chamber}/YYYY/MM/DD/{id}_{委員会名}/` の各ファイル

**metadata.json** — セッション基本情報（chamber, session_id, date, committee, hls_url, source_url, speakers配列）

**utterances.json** — 発言者セグメント + 話者タグ済み発言配列（speaker, role, text）

**qa_pairs.json** — Q&Aペア（id, topic, question/answer各フィールド、evasion_score, has_commitment, video_url）

**summary.json** — セッション要約、key_topics配列、key_commitments配列

**topics.json** — トピック一覧（Pagefind・フィルタ用）

### SQLiteスキーマ（`kokkai-transcriber/state.db`）

```sql
CREATE TABLE processed_sessions (
    chamber      TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    date         TEXT NOT NULL,
    committee    TEXT NOT NULL,
    status       TEXT DEFAULT 'pending',  -- pending/processing/done/error
    audio_url    TEXT,
    speaker_count INTEGER,
    processed_at TEXT,
    error_msg    TEXT,
    PRIMARY KEY (chamber, session_id)
);
```

---

## 外部サービス・エンドポイント

| サービス | 用途 | 認証 |
|---------|------|------|
| `hlsvod.shugiintv.go.jp` | 衆議院HLS音声 | なし |
| `public.mediasp.jp` | 参議院動画（hash指定） | なし（Playwright使用） |
| DeepInfra Whisper | 文字起こし | `DEEPINFRA_API_KEY` |
| DeepInfra DeepSeek V3.2 | 話者タグ・構造化 | `DEEPINFRA_API_KEY` |
| OpenRouter | BYOK LLM（ブラウザのみ） | ユーザー入力キー |

環境変数は `kokkai-transcriber/.env`（gitignore済み）に配置。`DEEPINFRA_API_KEY` のみ必須。

---

## 実装フェーズ

現在のステータスは `ARCH.md` セクション9を正として扱う。

| フェーズ | 内容 | ステータス |
|---------|------|-----------|
| Phase 1 | 衆議院パイプラインPoC（deli_id=56149） | 未着手 |
| Phase 2 | Docker化 + Astroサイト基盤 + ShugiinScraper | 未着手 |
| Phase 3 | 参議院対応（mediasp.jp解決含む） | 未着手 |
| Phase 4 | フィルタ + TSVエクスポート | 未着手 |
| Phase 5 | ダッシュボード（ヒートマップ・約束トラッカー等） | 未着手 |
| Phase 6 | BYOK + OpenRouter連携 + 高度機能 | 未着手 |

**Phase 1の最初のタスク**: `deli_id=56149`（2026-04-09本会議）を使って全パイプラインを手動実行し、出力JSONの構造を確定する。

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
