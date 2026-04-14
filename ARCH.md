# 国会議事録リアルタイムDB — 要件定義・アーキテクチャ設計書

> **プロジェクト名**: 国会議事録リアルタイムDB（仮）
> **ステータス**: 設計完了・Phase 1 着手可能
> **最終更新**: 2026-04-14
> **作成者**: 中原道智

---

## 1. プロジェクト概要

### 1.1 背景と課題

国立国会図書館が運営する国会会議録検索システム（kokkai.ndl.go.jp）は正式な会議録を提供しているが、反映までに数週間〜数ヶ月のタイムラグがある。委員会質疑の内容をリアルタイムに把握し、分析・活用したいニーズに対応できていない。

一方、衆議院インターネット審議中継（shugiintv.go.jp）および参議院インターネット審議中継（webtv.sangiin.go.jp）は、それぞれ審議当日中にアーカイブ動画を公開しており、発言者ごとの頭出し情報も提供している。両院の動画アーカイブから音声を抽出し、AI文字起こし・構造化することで、公式会議録の公開を待たずに質疑内容をデータベース化できる。

### 1.2 プロジェクト目標

衆議院TV・参議院TVのアーカイブ動画から自動で文字起こし・構造化・分析を行い、GitHub Pages上の静的サイトとして公開する。両院横断の検索・フィルタ・ビジュアライゼーション・LLM分析機能を備え、秘書・議員・研究者・一般市民が活用できるプラットフォームとする。

### 1.3 著作権上の整理

著作権法第40条1項により、公開して行われた政治上の演説・陳述は「同一の著作者のものを編集して利用する場合を除き、いずれの方法によるかを問わず利用することができる」と規定されている。複数議員の発言をフラットに収録するデータベースはこの範囲に含まれる。政府答弁者の発言については第40条2項の射程がやや不明確だが、国会図書館自身が全文テキストをWeb公開しており（遅延があるだけ）、速報版の提供に対する実務的リスクは極めて低い。出所明示（著作権法第48条）は必須。

---

## 2. 要件

### 2.1 機能要件

#### データ収集・処理

| ID | 要件 | 優先度 |
|----|------|--------|
| F-01 | 衆議院TVのアーカイブに新規登録されたセッションを自動検出する | Must |
| F-01b | 参議院TVのアーカイブに新規登録されたセッションを自動検出する | Must |
| F-02 | HLSストリーム（衆議院）またはmediasp.jp配信（参議院）から音声を抽出する | Must |
| F-03 | 音声をWhisper（DeepInfra）で文字起こしする | Must |
| F-04 | 各院のTV発言者タイムスタンプで音声をセグメント分割する | Must |
| F-05 | セグメント内の話者交代をLLMで検出・タグ付けする（委員長、質疑者、答弁大臣、政府参考人等） | Must |
| F-06 | 質問と答弁をペアリングし、Q&Aペアとして構造化する | Must |
| F-07 | LLMでセッション要約・トピック抽出・答弁分析を生成する | Should |
| F-08 | 処理済みセッションの状態を院ごとに管理し、重複処理を防ぐ | Must |
| F-09 | 構造化JSONをGitリポジトリにpushしてCI/CDを起動する | Must |

#### 閲覧・検索

| ID | 要件 | 優先度 |
|----|------|--------|
| F-10 | セッション一覧を日付降順で表示する | Must |
| F-11 | Pagefindによるクライアントサイド全文検索を提供する | Must |
| F-12 | 院（衆/参）、日付範囲、委員会、政党・会派、発言者名、役割、トピックで絞り込みできる | Must |
| F-13 | Q&A対比カード形式で質疑と答弁を並列表示する | Must |
| F-14 | 各発言から衆議院TVの該当タイムスタンプへの動画リンクを提供する | Must |
| F-15 | セッション内の発言をタイムラインビューで可視化する | Should |

#### エクスポート

| ID | 要件 | 優先度 |
|----|------|--------|
| F-16 | フィルタ済みQ&AペアをTSVとしてクリップボードにコピーし、Google Sheetsへのインポートを容易にする | Must |
| F-17 | Google Sheets API連携によるワンクリックエクスポートを提供する | Could |

#### ダッシュボード・ビジュアライゼーション

| ID | 要件 | 優先度 |
|----|------|--------|
| F-18 | トピック×委員会のヒートマップを表示する | Should |
| F-19 | 答弁回避度を大臣・テーマ別に集計表示する | Should |
| F-20 | 大臣の約束事項を時系列で追跡する（約束トラッカー） | Should |
| F-21 | 質疑者↔答弁者の対話ネットワークを可視化する | Could |
| F-22 | 政党別の発言量・トピック分布を表示する | Could |
| F-23 | GitHubコントリビューション風のセッションカレンダーを表示する | Could |

#### BYOK（Bring Your Own Key）インタラクティブ機能

| ID | 要件 | 優先度 |
|----|------|--------|
| F-24 | ユーザーがOpenRouter APIキーを入力すると追加のLLM分析機能がアンロックされる | Should |
| F-25 | 同一大臣×同一テーマの答弁を時系列で比較分析する | Should |
| F-26 | 答弁の回避度を詳細分析し、理想的な答弁案を提示する | Should |
| F-27 | 答弁の弱点を突くフォローアップ質問を提案する | Should |
| F-28 | Q&Aペアからプラットフォーム別SNS投稿を生成する | Could |
| F-29 | 複数セッション横断のテーマ別政策ブリーフを生成する | Could |
| F-30 | データ全体に対する自然言語クエリを処理する | Could |
| F-31 | ユーザーが分析に使うLLMモデルを選択できる | Could |

### 2.2 非機能要件

| ID | 要件 | 詳細 |
|----|------|------|
| NF-01 | 静的サイト完結 | サーバーサイドプロセスなし。GitHub Pagesでホスト。 |
| NF-02 | コスト上限 | インフラ月額$20以下（Whisper + LLM処理、ホスティング無料） |
| NF-03 | 処理遅延 | 衆議院TVアーカイブ登録後24時間以内にサイト反映 |
| NF-04 | 検索性能 | 数万発言のインデックスでも初回検索3秒以内 |
| NF-05 | BYOKセキュリティ | APIキーはsessionStorageのみ保持、サーバー送信なし |
| NF-06 | 出所明示 | 全ページに衆議院TVへのソースリンクを表示 |
| NF-07 | 可用性 | GitHub Pages SLA準拠（99.9%） |

---

## 3. データソース調査結果

### 3.1 両院比較サマリ

調査日: 2026-04-14

| 項目 | 衆議院TV (shugiintv.go.jp) | 参議院TV (webtv.sangiin.go.jp) |
|------|---------------------------|-------------------------------|
| エンコーディング | EUC-JP | UTF-8 |
| フレームワーク | jQuery + THEOplayer | jQuery + mediasp.jp |
| セッションID | `deli_id` (数値) | `sid` (数値) |
| 発言者タイムスタンプ | URLパラメータ `time=7320.2` | フラグメント `#1850.95`（`class="play2"`） |
| 動画配信 | 自前HLS (`hlsvod.shugiintv.go.jp`) | 外部SaaS (`public.mediasp.jp`、hash指定) |
| カレンダーAPI | `calendar.php?mon=YYYYMM` GET | `calendar.php` セッション依存 |
| 日付検索 | `index.php?ex=VL&u_day=YYYYMMDD` GETで完結 | `result_selecter.php` セッション状態依存 |
| 詳細ページ | `index.php?ex=VL&deli_id=XXXXX` | `detail.php?sid=XXXX` |
| 発言者リスト構造 | `<A HREF="...&time=N">名前(所属)</A>` | `<a href='#N' class='play2'>名前(所属)</a>` |

### 3.2 衆議院TVのエンドポイント

サイトはEUC-JPエンコーディング、jQuery + THEOplayer構成。

| 用途 | URL | メソッド | レスポンス |
|------|-----|---------|-----------|
| カレンダー | `calendar.php?mon=YYYYMM` | GET | 開催日リンク一覧（`u_day=YYYYMMDD`） |
| 日付別セッション一覧 | `index.php?ex=VL&u_day=YYYYMMDD` | GET | `deli_id`一覧（HTMLのJSリンク内） |
| セッション詳細 | `index.php?ex=VL&deli_id=XXXXX` | GET | 発言者リスト、HLS URL |

#### 発言者データ（セッション詳細ページ）

HTMLから以下の構造で抽出可能:

```
<A HREF="/jp/index.php?ex=VL&media_type=&deli_id=56149&time=7320.2">
  古川あおい(チームみらい)
</A>
```

取得可能フィールド:
- 発言者名: `古川あおい`
- 所属: `チームみらい`（カッコ内、役職を含む場合あり）
- 開始秒数: `7320.2`（`time=`パラメータ、小数点以下あり）
- 開始時刻: `14時42分`（テーブルセルのテキスト）
- 所要時間: `18分`（テーブルセルのテキスト）

#### HLSストリームURL

hidden input `#vtag_src_base_vod` のvalue属性から取得:

```
http://hlsvod.shugiintv.go.jp/vod/_definst_/amlst:YYYY/YYYY-MMDD-HHMM-SS/playlist.m3u8
```

実例: `2026/2026-0409-1300-00/playlist.m3u8`

### 3.3 参議院TVのエンドポイント

サイトはUTF-8エンコーディング、jQuery + mediasp.jp構成。AJAX多用でセッション状態依存が強い。

| 用途 | URL | メソッド | レスポンス |
|------|-----|---------|-----------|
| 今日のセッション | `result_selecter.php?mode=today_reload&absdate=YYYY-MM-DD` | GET | `sid`一覧 |
| カレンダー | `calendar.php` | GET (cookie必要) | 開催日リンク |
| カレンダー月移動 | `calendar.php?calendarmove=1&dt_calendarpoint=YYYY-MM` | GET | 月別カレンダー |
| 委員会一覧 | `kaigi_list.php` | GET | 委員会名リスト |
| セッション詳細 | `detail.php?sid=XXXX` | GET | 発言者リスト、動画プレイヤー |
| 検索フォーム | `form.php` | GET | 検索パラメータフォーム |

#### 発言者データ（セッション詳細ページ）

```html
<a href='#1850.95' class='play2'>伊藤孝江(法務委員長)</a>
<a href='#1897.82' class='play2'>山谷えり子(自由民主党・無所属の会)</a>
<a href='#7450.04' class='play2'>安達悠司(参政党)</a>
```

衆議院TVとほぼ同じ構造。`class="play2"`のアンカー要素からフラグメント（`#秒数`）と発言者情報を抽出。

#### 動画URL

動画は外部SaaS `public.mediasp.jp` でホスト。セッション詳細ページ内に以下のscriptタグ:

```html
<script src="https://public.mediasp.jp/v1/player?hash=d7e9tess0u5s716prbsg&forward_sec=10&playback_speed_steps=11"></script>
```

`hash`パラメータがセッション固有の動画ID。実際のストリームURL（HLS/MP4）はこのスクリプトが動的に生成するため、以下のいずれかの方法で取得が必要:
- **方法A**: Playwright/Puppeteer等のheadless browserでページをロードし、network requestsからHLS URLをインターセプト
- **方法B**: mediasp.jp APIの仕様をリバースエンジニアリング（hashからstream URLへの変換）
- **方法C**: ブラウザで手動確認し、URLパターンを特定（PoC時に実施）

### 3.4 制約事項

**共通:**
- 頭出しタイムスタンプは「質疑者の持ち時間の開始点」であり、セグメント内に複数話者（委員長、答弁者、政府参考人）が含まれる

**衆議院固有:**
- サイトはEUC-JPエンコーディング。スクレイパーは`iconv -f EUC-JP -t UTF-8`必須
- セッション検索フォームはJavaScript駆動（`FORM1`をPOST）。カレンダー経由の`u_day`パラメータGETが安定
- 委員会IDは数値（例: `1`=本会議、`131`=内閣委員会）。セレクトボックスに98種類

**参議院固有:**
- AJAX多用でセッション状態（cookie/リファラ）に依存する箇所あり。カレンダー月移動等はセッション外からのアクセスでエラーになる場合がある
- 動画は外部SaaS（mediasp.jp）ホスト。音声URL取得にheadless browserまたはAPI解析が必要
- `detail.php?sid=XXXX` のGETアクセスは安定しており、発言者リストの抽出は問題なし

---

## 4. アーキテクチャ

### 4.1 全体構成

```
┌─────────────────────────────────────────────────────────┐
│  Docker Container（Mac上でcron実行）                       │
│                                                           │
│  ┌─ ShugiinScraper ─┐  ┌─ SangiinScraper ─┐              │
│  │  shugiintv.go.jp  │  │  webtv.sangiin   │              │
│  └────────┬──────────┘  └────────┬─────────┘              │
│           └──────┬───────────────┘                         │
│                  ↓                                         │
│       Detail Parser → ffmpeg → Whisper → LLM → JSON       │
│                  (共通パイプライン)                          │
│                          ↓                                │
│                    git commit + push                      │
└────────────────────────┬────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│  GitHub Actions（on push to data/）                       │
│                                                           │
│  Astro Build → Pagefind Index → Deploy to GitHub Pages   │
└────────────────────────┬────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│  Static Site（GitHub Pages）                              │
│                                                           │
│  Tier 0: 両院横断の閲覧・検索・フィルタ・ダッシュボード     │
│  Tier 1: BYOK OpenRouter → オンデマンドLLM分析            │
└─────────────────────────────────────────────────────────┘
```

### 4.2 処理パイプライン詳細

```
1. 新規セッション検出（院別Scraper）
   衆議院: calendar.php → 開催日一覧 → index.php?ex=VL&u_day → deli_id一覧
   参議院: detail.php?sid=XXXX を巡回 or calendar_click日付から探索
   SQLiteで未処理セッションを特定

2. メタデータ抽出（院別Detail Parser）
   衆議院: index.php?ex=VL&deli_id=XXXXX → 発言者リスト + HLS URL
   参議院: detail.php?sid=XXXX → 発言者リスト（class="play2"）+ mediasp.jp hash
   発言者名、所属、開始秒、所要時間を共通フォーマットに正規化

3. 音声取得・セグメント分割（院別Audio Extractor）
   衆議院: ffmpeg -i {HLS_URL} → WAV
   参議院: mediasp.jp hashからストリームURL解決 → ffmpeg → WAV
   発言者タイムスタンプでセグメント分割 → WAVチャンク群

4〜7は両院共通パイプライン:

4. 文字起こし（DeepInfra Whisper large-v3-turbo）
   各WAVチャンク → Whisper API
   promptパラメータに答弁者候補名を含めて固有名詞精度向上
   コスト: $0.0002/min → 3時間セッション = $0.036

5. LLM話者タグ付け（DeepInfra DeepSeek V3.2等）
   セグメント内の話者交代を検出
   委員長の指名発言パターン、答弁冒頭定型句で分離
   → utterances配列（speaker, role, text）

6. LLM清書・構造化（DeepInfra DeepSeek V3.2等）
   Q&Aペア生成（質問要旨 + 答弁要旨 + 回避度 + 約束事項）
   セッション要約、トピック抽出
   → qa_pairs.json, summary.json, topics.json

7. 公開
   構造化JSONをgit push → GitHub Actions起動
   Astro build → Pagefind indexing → GitHub Pages deploy
```

### 4.3 コンポーネント構成

#### Dockerコンテナ（データ収集・処理）

```
kokkai-transcriber/
├── Dockerfile
├── docker-compose.yml
├── src/
│   ├── scrapers/
│   │   ├── base.py             # BaseScraper ABC（共通インターフェース）
│   │   ├── shugiin.py          # 衆議院TV Scraper（GET中心、EUC-JP）
│   │   └── sangiin.py          # 参議院TV Scraper（セッション管理、UTF-8）
│   ├── audio/
│   │   ├── extractor.py        # ffmpeg HLS/MP4→WAVセグメント
│   │   └── sangiin_resolver.py # mediasp.jp hash→ストリームURL解決
│   ├── transcriber.py          # Whisper API (DeepInfra)
│   ├── speaker_tagger.py       # LLM話者タグ付け
│   ├── structurer.py           # LLM清書・Q&Aペア・要約・トピック
│   ├── publisher.py            # git commit + push
│   └── state.py                # SQLite状態管理
├── data/                       # ローカル作業用（gitignore）
└── state.db                    # 処理済みセッション管理（両院統合）
```

**Scraper抽象化:**

```python
class BaseScraper(ABC):
    """両院共通のScraper インターフェース"""
    chamber: str  # "shugiin" | "sangiin"

    @abstractmethod
    def detect_new_sessions(self, date: str) -> list[str]:
        """指定日の新規セッションIDを返す"""
        ...

    @abstractmethod
    def get_session_detail(self, session_id: str) -> SessionDetail:
        """セッション詳細（発言者リスト等）を返す"""
        ...

    @abstractmethod
    def get_audio_url(self, session_id: str) -> str:
        """音声ストリームURLを返す"""
        ...

class ShugiinScraper(BaseScraper):
    chamber = "shugiin"
    # calendar.php + u_day GET → deli_id → HLS URL直接取得

class SangiinScraper(BaseScraper):
    chamber = "sangiin"
    # result_selecter.php → sid → mediasp.jp hash解決
```

#### GitHubリポジトリ

```
kokkai-db/
├── .github/workflows/
│   └── build-deploy.yml
├── data/                         # Dockerがpushする先
│   ├── shugiin/                  # 衆議院
│   │   └── YYYY/MM/DD/
│   │       └── {deli_id}_{委員会名}/
│   │           ├── metadata.json
│   │           ├── raw_transcript.json
│   │           ├── utterances.json
│   │           ├── qa_pairs.json
│   │           ├── summary.json
│   │           └── topics.json
│   └── sangiin/                  # 参議院
│       └── YYYY/MM/DD/
│           └── {sid}_{委員会名}/
│               └── (同上)
├── site/                         # Astroプロジェクト
│   ├── astro.config.mjs
│   ├── src/
│   │   ├── layouts/
│   │   ├── pages/
│   │   │   ├── index.astro
│   │   │   ├── browse.astro
│   │   │   ├── search.astro
│   │   │   ├── settings.astro
│   │   │   ├── dashboard/
│   │   │   │   ├── index.astro
│   │   │   │   ├── topics.astro
│   │   │   │   ├── speakers.astro
│   │   │   │   └── tracker.astro
│   │   │   └── [year]/[month]/[day]/
│   │   │       └── [slug].astro
│   │   ├── components/
│   │   │   ├── QAPairCard.astro
│   │   │   ├── TimelineView.jsx    # React島
│   │   │   ├── FilterPanel.jsx     # React島
│   │   │   ├── DashboardCharts.jsx # React島
│   │   │   ├── BYOKGate.jsx        # React島
│   │   │   └── StreamingAnalysis.jsx
│   │   └── lib/
│   │       └── openrouter.js
│   └── public/
│       └── api/                    # ビルド時生成
│           ├── index.json
│           ├── speakers.json
│           ├── parties.json
│           ├── topics.json
│           ├── commitments.json
│           └── stats.json
└── README.md
```

### 4.4 データモデル

#### metadata.json

```json
{
  "chamber": "shugiin",
  "session_id": "56149",
  "date": "2026-04-09",
  "committee": "本会議",
  "committee_id": 1,
  "session_number": 221,
  "duration": "1時間56分",
  "hls_url": "http://hlsvod.shugiintv.go.jp/vod/...",
  "source_url": "https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=56149",
  "processed_at": "2026-04-09T18:30:00+09:00",
  "whisper_model": "deepinfra/whisper-large-v3-turbo",
  "llm_model": "deepseek-ai/DeepSeek-V3.2",
  "speakers": [
    {
      "name": "古川あおい",
      "affiliation": "チームみらい",
      "role": "質疑者",
      "start_seconds": 7320.2,
      "start_time": "14:42",
      "duration_minutes": 18
    }
  ]
}
```

#### utterances.json

```json
{
  "segments": [
    {
      "segment_index": 8,
      "segment_speaker": "古川あおい",
      "segment_affiliation": "チームみらい",
      "start_seconds": 7320.2,
      "video_url": "https://www.shugiintv.go.jp/jp/index.php?ex=VL&media_type=&deli_id=56149&time=7320.2",
      "utterances": [
        {
          "speaker": "藤原徹",
          "role": "委員長",
          "text": "古川あおい君"
        },
        {
          "speaker": "古川あおい",
          "role": "質疑者",
          "text": "チームみらいの古川あおいです。高額療養費制度について伺います..."
        },
        {
          "speaker": "上野賢一郎",
          "role": "答弁者",
          "text": "お答えいたします。御指摘の多数回該当の取扱いについては..."
        }
      ]
    }
  ]
}
```

#### qa_pairs.json

```json
{
  "pairs": [
    {
      "id": "qa_001",
      "segment_index": 8,
      "topic": "高額療養費の多数回該当リセット",
      "question": {
        "speaker": "古川あおい",
        "party": "チームみらい",
        "summary": "がん患者が毎年1月に高額な自己負担を強いられる多数回該当リセット問題の認識と対応を問う",
        "full_text": "...",
        "intent": "fact_check"
      },
      "answer": {
        "speaker": "上野賢一郎",
        "role": "厚生労働大臣",
        "summary": "問題を認識しており、次期制度改正の検討課題として位置づけると答弁",
        "full_text": "...",
        "evasion_score": 0.3,
        "has_commitment": true,
        "commitment_text": "次期制度改正の検討課題として位置づけてまいりたい"
      },
      "follow_up_ids": ["qa_002"],
      "video_url": "https://www.shugiintv.go.jp/jp/..."
    }
  ]
}
```

#### summary.json

```json
{
  "session_summary": "2026年4月9日の本会議では、健康保険法改正案の趣旨説明と代表質問が行われた。...",
  "key_topics": ["健康保険法改正", "高額療養費", "OTC類似薬", "出産費用無償化"],
  "key_commitments": [
    {
      "speaker": "上野賢一郎",
      "role": "厚生労働大臣",
      "text": "次期制度改正の検討課題として位置づけてまいりたい",
      "topic": "高額療養費の多数回該当リセット",
      "qa_id": "qa_001"
    }
  ]
}
```

### 4.5 状態管理DB（SQLite）

```sql
CREATE TABLE processed_sessions (
    chamber      TEXT NOT NULL,    -- 'shugiin' | 'sangiin'
    session_id   TEXT NOT NULL,    -- deli_id (衆) or sid (参)
    date         TEXT NOT NULL,
    committee    TEXT NOT NULL,
    status       TEXT DEFAULT 'pending',
    audio_url    TEXT,
    speaker_count INTEGER,
    processed_at TEXT,
    error_msg    TEXT,
    PRIMARY KEY (chamber, session_id)
);

CREATE TABLE processing_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chamber      TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    step         TEXT,
    started_at   TEXT,
    finished_at  TEXT,
    success      BOOLEAN,
    detail       TEXT,
    FOREIGN KEY (chamber, session_id) REFERENCES processed_sessions(chamber, session_id)
);
```

---

## 5. 静的サイト設計

### 5.1 技術選定

| レイヤー | 選定 | 理由 |
|---------|------|------|
| SSG | Astro | Content Collections、partial hydration（React島）、Pagefind統合 |
| 検索 | Pagefind | 静的サイト専用全文検索、CJK対応、差分インデックスfetch |
| チャート | Recharts | React互換、宣言的API |
| ネットワーク図 | D3 force | カスタマイズ性 |
| UIフレームワーク | React島（Astro内） | ダッシュボード・フィルタ等のインタラクティブ部分のみ |
| ホスティング | GitHub Pages | 無料、Actions連携 |
| CI/CD | GitHub Actions | data/ pushトリガー |

### 5.2 サイトマップ

| パス | 内容 | ハイドレーション |
|------|------|-----------------|
| `/` | 最新セッション一覧（両院統合）+ ミニダッシュボード | 静的 + React島 |
| `/browse` | 多軸フィルタ付きセッション一覧（院フィルタ含む） | React島 |
| `/search` | Pagefind全文検索 | Pagefind UI |
| `/dashboard` | 両院横断ダッシュボード概要 | React島 |
| `/dashboard/topics` | トピック×委員会ヒートマップ | React島 (Recharts) |
| `/dashboard/speakers` | 発言者ネットワーク | React島 (D3) |
| `/dashboard/tracker` | 約束トラッカー | React島 |
| `/shugiin/YYYY/MM/DD/{slug}` | 衆議院セッション詳細（Q&A対比ビュー） | 静的 + React島 |
| `/sangiin/YYYY/MM/DD/{slug}` | 参議院セッション詳細（Q&A対比ビュー） | 静的 + React島 |
| `/{chamber}/YYYY/MM/DD/{slug}/timeline` | セッションタイムライン | React島 (SVG) |
| `/{chamber}/YYYY/MM/DD/{slug}/raw` | 生文字起こし | 静的 |
| `/settings` | APIキー設定、モデル選択 | React島 |
| `/api/*.json` | 静的JSON API | なし |

### 5.3 GitHub Actions

```yaml
name: Build and Deploy
on:
  push:
    paths: ['data/**']
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22 }
      - run: npm ci
        working-directory: site
      - run: npm run build    # Astro reads ../data/ at build time
        working-directory: site
      - run: npx pagefind --site site/dist --glob "**/*.html"
      - uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: site/dist
```

---

## 6. ダッシュボード・ビジュアライゼーション設計

先行事例調査（TheyWorkForYou/UK、DebateVis/IEEE、ANLP2024明治大の政党スタンス分析等）を踏まえた設計。

### 6.1 セッションタイムラインビュー

横軸=時間のバーチャート。各バーの色=話者。Q&Aペアのコネクタ線で質問と答弁を視覚的に紐付け。バークリックで発言テキスト展開+動画リンク。

### 6.2 Q&A対比カード

質問（左）と答弁（右）を並列表示。答弁の回避度をインジケータで表示。動画リンク、スプレッドシートエクスポートボタン、共有リンクを各カードに配置。

### 6.3 トピックヒートマップ

委員会×トピックのマトリクス。セル色の濃度=言及回数。LLM抽出トピックを正規化して使用。セルクリックで該当Q&Aペア一覧へ遷移。

### 6.4 答弁回避度トラッカー

大臣別・テーマ別の答弁傾向を集計。明確回答 / 検討する系 / 回避的 の3分類。時系列での変化も表示。

### 6.5 約束トラッカー

LLMが抽出した約束事項（`key_commitments`）を時系列表示。後日のセッションで進展があればリンク（自動マッチング or 手動更新）。

### 6.6 発言者ネットワーク

質疑者↔答弁者のD3 force-directed graph。ノードサイズ=発言回数、エッジ太さ=Q&Aペア数。

### 6.7 セッションカレンダー

GitHub Contributions風。日付セルの色=セッション数。クリックでその日のセッション一覧へ。

---

## 7. BYOKインタラクティブレイヤー

### 7.1 Tier構成

**Tier 0（キー不要）**: 全データ閲覧、検索、フィルタ、Q&Aカード、ダッシュボード。ビルド時にLLMで生成済みの分析結果をすべて含む。Tier 0だけで完全に独立したプロダクトとして成立する。

**Tier 1（OpenRouter APIキー入力後）**: ブラウザからOpenRouter APIへ直接リクエスト。サーバー不要。キーは`sessionStorage`に保持（タブ閉じで消去）。

### 7.2 Tier 1 機能

| カテゴリ | 機能 | 説明 |
|---------|------|------|
| 質疑インテリジェンス | 答弁比較 | 同一大臣×同一テーマの答弁を時系列比較、変化・矛盾を分析 |
| | 回避答弁ディテクター | 答弁が質問の核心に答えているかを詳細判定、理想答弁案を提示 |
| | フォローアップ質問提案 | 答弁の弱点を突く次の質問を生成。質疑準備に直結 |
| コンテンツ生成 | SNS投稿生成 | Q&Aペアからプラットフォーム別（X/note/ブログ）の投稿を生成 |
| | 政策ブリーフ生成 | テーマ横断で全Q&Aを統合したブリーフを生成 |
| | 議事録クリーンアップ | フィラー除去、口語→書き言葉変換 |
| 横断分析 | 自然言語クエリ | 「出産費用の無償化について各党の立場を比較して」等 |
| | テーマ追跡レポート | 指定テーマの時系列サマリを生成 |
| | 市民質問インターフェース | 「この議員にこれを聞いてほしい」→ 既存Q&A検索 or 質問案生成 |

### 7.3 OpenRouterクライアント実装

```javascript
class OpenRouterClient {
  constructor(apiKey) {
    this.apiKey = apiKey;
    this.baseUrl = "https://openrouter.ai/api/v1";
  }

  async chat(messages, options = {}) {
    return fetch(`${this.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
        "HTTP-Referer": window.location.origin,
        "X-Title": "国会議事録DB"
      },
      body: JSON.stringify({
        model: options.model || "deepseek/deepseek-chat-v3-0324",
        messages,
        stream: true,
        max_tokens: options.maxTokens || 4096,
        temperature: options.temperature || 0.3
      })
    }).then(r => r.body);
  }
}
```

### 7.4 推奨モデル

| 用途 | モデル | 理由 |
|------|--------|------|
| 話者タグ付け（ビルド時） | DeepSeek V3.2 | 安い、構造化出力が得意 |
| 答弁比較・分析 | Claude Sonnet / GPT-4o | ニュアンス分析に強い |
| SNS・ブリーフ生成 | DeepSeek V3.2 | コスト優先 |
| 自然言語クエリ | DeepSeek V3.2 | フィルタ→要約の2段処理 |

UIにモデルセレクタを配置し、ユーザーが選択可能にする。

---

## 8. コスト見積り

### 月間運用コスト（定常運用時）

| 項目 | 単価 | 想定量 | 月額 |
|------|------|--------|------|
| Whisper (DeepInfra) | $0.0002/min | 月160時間分 (両院合計40セッション×4h) | $1.92 |
| LLM処理 (DeepInfra) | ~$0.30/1M tokens | 月~4M tokens | $1.20 |
| GitHub Pages | 無料 | — | $0 |
| GitHub Actions | 無料枠内 | — | $0 |
| **合計** | | | **~$3.12/月** |

BYOK側のLLMコストはユーザー負担（OpenRouterの従量課金）。

---

## 9. 実装フェーズ

### Phase 1: 衆議院パイプラインPoC（2日）

目標: 1つのdeli_idで全パイプラインを手動実行し、出力JSONの構造を確定。

- [ ] `deli_id=56149`（2026-04-09本会議）の詳細ページをスクレイピング
- [ ] HLSストリームからffmpegで音声抽出
- [ ] 発言者タイムスタンプでWAVセグメント分割
- [ ] DeepInfra Whisperで文字起こし（promptに答弁者名含む）
- [ ] DeepSeek V3.2で話者タグ付け
- [ ] DeepSeek V3.2でQ&Aペア生成・要約・トピック抽出
- [ ] 全出力JSONの構造レビュー・確定

### Phase 2: Docker化 + サイト基盤 + Scraper抽象化（2-3日）

- [ ] BaseScraper ABC定義、ShugiinScraper実装
- [ ] Dockerfile + docker-compose.yml
- [ ] cron/launchd設定（1日2回実行）
- [ ] SQLite状態管理（chamber + session_id複合キー）
- [ ] git auto-push
- [ ] Astroプロジェクトセットアップ（`/shugiin/`, `/sangiin/` ルーティング）
- [ ] 基本ページ（セッション一覧、個別セッション、Q&Aカード）
- [ ] Pagefind統合
- [ ] GitHub Actions CI/CD

### Phase 3: 参議院対応（1-2日）

- [ ] 参議院TV動画URL解決方法の確定（mediasp.jp解析 or Playwright）
- [ ] SangiinScraper実装（detail.php?sid パース、発言者タイムスタンプ抽出）
- [ ] 参議院音声取得パイプラインの結合テスト
- [ ] 両院統合での表示・検索確認

### Phase 4: フィルタ + エクスポート（1日）

- [ ] クライアントサイド多軸フィルタリング（院フィルタ含む）
- [ ] Google Sheets TSVエクスポート
- [ ] 動画タイムスタンプリンク完備（両院）

### Phase 5: ダッシュボード（2-3日）

- [ ] セッションタイムラインビュー
- [ ] トピックヒートマップ（両院横断）
- [ ] 答弁回避度トラッカー
- [ ] 約束トラッカー
- [ ] セッションカレンダー

### Phase 6: BYOK + 高度機能（継続的）

- [ ] OpenRouterキー入力UI + sessionStorage管理
- [ ] 答弁比較（SSEストリーミング）
- [ ] フォローアップ質問提案
- [ ] SNS投稿生成
- [ ] 発言者ネットワーク
- [ ] 政党別分析（両院横断で同一政党・会派の名寄せ）
- [ ] 自然言語クエリ
- [ ] Google Sheets API直接連携
- [ ] 過去セッション遡及処理（両院）
