# Phase 1: 衆議院パイプラインPoC — 実装・テスト計画

> **目標**: `deli_id=56149`（2026-04-09 本会議）を対象に全パイプラインを手動実行し、出力JSONの構造を確定する。
> **所要期間**: 2日
> **前提**: `DEEPINFRA_API_KEY` が環境変数またはdotenvで利用可能であること。ffmpegがインストール済みであること。

---

## 成果物

Phase 1 完了時に以下が揃う:

1. `kokkai-transcriber/` 配下に動作するPythonスクリプト群
2. `data/shugiin/2026/04/09/56149_本会議/` 配下に6つのJSON（metadata, raw_transcript, utterances, qa_pairs, summary, topics）
3. 各JSONスキーマが `ARCH.md` セクション4.4のデータモデルと一致することの確認
4. 各ステップの単体テスト

---

## ステップ

### Step 1: プロジェクト骨格のセットアップ

**やること:**

```
kokkai-transcriber/
├── pyproject.toml          # uv/pip用。依存: requests, beautifulsoup4, openai (DeepInfra互換), pydantic
├── .env.example            # DEEPINFRA_API_KEY=
├── .gitignore              # data/, state.db, .env, __pycache__, *.wav
└── src/
    ├── __init__.py
    ├── models.py           # Pydantic: SpeakerInfo, SessionDetail, Utterance, QAPair, etc.
    ├── scrapers/
    │   ├── __init__.py
    │   └── shugiin.py
    ├── audio/
    │   ├── __init__.py
    │   └── extractor.py
    ├── transcriber.py
    ├── speaker_tagger.py
    ├── structurer.py
    └── pipeline.py         # ステップ1-6を順に実行するCLIエントリポイント
```

**決定事項:**
- Phase 1 では `BaseScraper` ABC は作らない（Phase 2 で抽出）。`shugiin.py` に直接実装する
- Phase 1 では SQLite 状態管理も作らない（Phase 2 スコープ）
- Phase 1 では `publisher.py`（git push）も作らない。手動でJSONを確認する
- Pydanticモデルでデータ構造を厳密に定義し、JSONシリアライズに使う
- DeepInfra APIは OpenAI互換エンドポイント（`openai` Pythonライブラリで接続可能）

**テスト:**
- `pyproject.toml` が有効で `uv sync` / `pip install -e .` が成功すること

---

### Step 2: 衆議院TV詳細ページのスクレイピング

**やること:**
- `shugiin.py` に `get_session_detail(deli_id: str) -> SessionDetail` を実装
- URL: `https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=56149`
- レスポンスのエンコーディングを `euc-jp` に明示設定
- BeautifulSoup4でHTMLをパースし、以下を抽出:
  - 発言者リスト: `<A HREF="...&time=N">名前(所属)</A>` パターン
  - HLS URL: `hidden input #vtag_src_base_vod` のvalue属性
  - 委員会名: ページタイトルまたはヘッダから
  - 日付: URLパラメータまたはページ内テキストから

**抽出する発言者フィールド:**

| フィールド | 抽出元 | 例 |
|-----------|--------|-----|
| `name` | アンカーテキストのカッコ前 | `古川あおい` |
| `affiliation` | カッコ内テキスト | `チームみらい` |
| `start_seconds` | `time=` パラメータ（float） | `7320.2` |
| `start_time` | テーブルセルのテキスト | `14:42` |
| `duration_minutes` | テーブルセルのテキスト（`XX分`） | `18` |

**出力:** `SessionDetail` Pydanticモデル → `metadata.json` として保存

**テスト:**
- 保存済みHTMLフィクスチャ（`tests/fixtures/shugiin_56149.html`）を使った単体テスト
  - 発言者リストが正しい数・順序で抽出されること
  - HLS URLが正しいフォーマットであること
  - EUC-JP→UTF-8変換後に日本語文字列が正しいこと
  - カッコ内に役職が含まれるケース（例: `伊藤孝恵(法務委員長)`）のパース
- 実際のshugiintv.go.jpへの結合テスト（手動実行、CIでは無効化）

---

### Step 3: HLS音声抽出 + セグメント分割

**やること:**
- `audio/extractor.py` に以下の2関数を実装:
  - `download_full_audio(hls_url: str, output_path: Path) -> Path`
    - `ffmpeg -i {hls_url} -vn -acodec pcm_s16le -ar 16000 -ac 1 {output_path}`
    - 16kHz mono WAV（Whisper最適）
  - `split_segments(full_audio: Path, speakers: list[SpeakerInfo], output_dir: Path) -> list[Path]`
    - 発言者タイムスタンプに基づきWAVを分割
    - 各セグメントのファイル名: `{segment_index:03d}_{speaker_name}.wav`
    - 最後のセグメントの終了時刻 = 全体の終了時刻

**注意事項:**
- ffmpegは `subprocess.run()` で呼び出す。`CalledProcessError` を捕捉
- HLSダウンロードはセッション全体で1回（2〜4GB程度の一時ファイル）。完了後にセグメント分割
- セグメント分割は ffmpeg の `-ss` / `-to` オプションで実行（再エンコードなし: `-c copy` は非推奨、WAVなのでオーバーヘッドは小さい）

**テスト:**
- 短いダミーWAVファイルを生成し、`split_segments` が正しい区間で分割すること
- ffmpegコマンドの引数が正しく構築されることを `subprocess.run` のモックでテスト
- 結合テスト: 実際のHLS URLからダウンロード + 分割（手動実行、要ffmpeg）

---

### Step 4: Whisper文字起こし

**やること:**
- `transcriber.py` に `transcribe_segment(wav_path: Path, speaker_names: list[str]) -> RawTranscript` を実装
- DeepInfra Whisper large-v3-turbo を OpenAI互換APIで呼び出す:
  ```python
  client = openai.OpenAI(
      api_key=os.environ["DEEPINFRA_API_KEY"],
      base_url="https://api.deepinfra.com/v1/openai",
  )
  result = client.audio.transcriptions.create(
      model="openai/whisper-large-v3-turbo",
      file=open(wav_path, "rb"),
      language="ja",
      response_format="verbose_json",
      timestamp_granularities=["segment"],
      prompt=f"国会質疑: {', '.join(speaker_names)}",
  )
  ```
- `prompt` パラメータに答弁者候補名を含めて固有名詞の文字起こし精度を向上させる
- `response_format="verbose_json"` でセグメントレベルのタイムスタンプを取得

**出力:** `raw_transcript.json`（Whisper APIの生レスポンスを各セグメント分結合）

**テスト:**
- DeepInfra APIレスポンスのモックを使った単体テスト（JSON構造の検証）
- 結合テスト: 1セグメントのWAVを実際にWhisperに投げて結果確認（手動実行、要APIキー）

---

### Step 5: LLM話者タグ付け

**やること:**
- `speaker_tagger.py` に `tag_speakers(raw_text: str, segment_speaker: SpeakerInfo, all_speakers: list[SpeakerInfo]) -> list[Utterance]` を実装
- DeepInfra DeepSeek V3.2をOpenAI互換APIで呼び出す:
  ```python
  client = openai.OpenAI(
      api_key=os.environ["DEEPINFRA_API_KEY"],
      base_url="https://api.deepinfra.com/v1/openai",
  )
  response = client.chat.completions.create(
      model="deepseek-ai/DeepSeek-V3.2",
      messages=[system_prompt, user_prompt],
      temperature=0.1,
      response_format={"type": "json_object"},
  )
  ```
- システムプロンプトで以下を指示:
  - セグメントの主発言者情報（名前、所属）を提供
  - 委員長の指名発言パターン（「〇〇君」「〇〇委員」）で話者交代を検出
  - 答弁冒頭の定型句（「お答えいたします」「お答え申し上げます」）で答弁者を検出
  - 出力は `{"utterances": [{"speaker": "...", "role": "...", "text": "..."}]}` のJSON
- `role` は: `委員長`, `質疑者`, `答弁者`, `政府参考人`, `参考人`, `その他`

**出力:** `utterances.json`

**テスト:**
- 典型的なパターンの文字起こしテキストフィクスチャを使った単体テスト:
  - 委員長 → 質疑者 → 委員長 → 答弁者 の遷移パターン
  - 政府参考人の答弁パターン
  - 話者交代なし（質疑者の持ち時間全体が1人の発言）
- LLM APIレスポンスのモックでJSON構造を検証

---

### Step 6: LLM Q&Aペア生成・要約・トピック抽出

**やること:**
- `structurer.py` に以下の3関数を実装:
  - `generate_qa_pairs(utterances: list[SegmentUtterances]) -> QAPairsOutput`
  - `generate_summary(utterances: list[SegmentUtterances], qa_pairs: QAPairsOutput) -> SummaryOutput`
  - `generate_topics(qa_pairs: QAPairsOutput) -> TopicsOutput`
- 各関数ともDeepInfra DeepSeek V3.2をJSON modeで呼び出す
- Q&Aペア生成のプロンプトには以下を含む:
  - 質問要旨と答弁要旨の要約
  - `evasion_score`: 0.0（明確回答）〜1.0（完全回避）
  - `has_commitment` / `commitment_text`: 答弁者が具体的な行動を約束したか
  - `intent`: 質問の意図分類（`fact_check`, `policy_proposal`, `accountability`, `information_request` 等）
- セッション要約は全utterancesとQ&Aペアの両方を入力として使う

**出力:** `qa_pairs.json`, `summary.json`, `topics.json`

**テスト:**
- utterancesフィクスチャを使った単体テスト（LLMモック）
  - Q&Aペアのid採番が連番であること
  - evasion_scoreが0.0-1.0の範囲であること
  - summary内のkey_topicsが空でないこと
- Pydanticバリデーションで `ARCH.md` のスキーマとの一致を保証

---

### Step 7: パイプライン統合 + JSON出力

**やること:**
- `pipeline.py` にCLIエントリポイントを実装:
  ```
  python -m src.pipeline --deli-id 56149 --output-dir data/shugiin/2026/04/09/56149_本会議
  ```
- Step 2→3→4→5→6 を順に実行
- 各ステップの出力を次のステップに渡す
- 最終出力: `output-dir/` 配下に6ファイル
- 各ステップでログ出力（`logging` モジュール、INFO/WARNING/ERROR）
- 途中で失敗した場合、どのステップで失敗したかを明示してエラー終了

**テスト:**
- 全ステップのモックを使ったパイプライン統合テスト
  - 各ステップが正しい順序で呼ばれること
  - 出力ディレクトリに6ファイルが生成されること
  - 各JSONファイルがPydanticモデルでバリデーション可能であること

---

### Step 8: 手動実行 + JSON構造レビュー

**やること:**
- 実際に `deli_id=56149` で全パイプラインを実行
- 出力されたJSONを `ARCH.md` セクション4.4のデータモデルと照合
- 以下を確認:
  - [ ] `metadata.json` — 全フィールドが埋まっているか。speakersの数・順序がページと一致するか
  - [ ] `raw_transcript.json` — 文字起こしが日本語として読めるか。固有名詞の精度
  - [ ] `utterances.json` — 話者タグが正しいか。委員長の指名発言が分離されているか
  - [ ] `qa_pairs.json` — Q&Aペアが妥当か。evasion_scoreの感覚値が合っているか
  - [ ] `summary.json` — 要約が的確か。key_topicsが網羅的か。key_commitmentsの抽出精度
  - [ ] `topics.json` — トピックの粒度が適切か
- 問題があればプロンプトを調整して再実行
- **この結果をもとに `ARCH.md` のデータモデルを必要に応じて修正する**（フィールド追加・型変更等）

---

## テスト構成

```
kokkai-transcriber/
├── tests/
│   ├── conftest.py              # 共通フィクスチャ（SpeakerInfo等）
│   ├── fixtures/
│   │   ├── shugiin_56149.html   # 保存済みHTMLフィクスチャ（EUC-JP）
│   │   ├── whisper_response.json
│   │   └── sample_utterances.json
│   ├── test_shugiin_scraper.py  # Step 2
│   ├── test_audio_extractor.py  # Step 3
│   ├── test_transcriber.py      # Step 4
│   ├── test_speaker_tagger.py   # Step 5
│   ├── test_structurer.py       # Step 6
│   └── test_pipeline.py         # Step 7
```

**テスト方針:**
- 外部依存（shugiintv.go.jp、DeepInfra API、ffmpeg）はデフォルトでモック
- `pytest.mark.integration` マーカーで結合テストを分離。`pytest -m integration` で実行
- フィクスチャHTMLは実際のページを保存したもの（Phase 1初日に取得）
- Pydanticモデルのバリデーションを各テストのアサーションに活用

```bash
# 単体テスト（外部依存なし）
cd kokkai-transcriber && python -m pytest -m "not integration"

# 結合テスト（APIキー + ffmpeg + ネットワーク必要）
cd kokkai-transcriber && python -m pytest -m integration
```

---

## 依存関係

```toml
# pyproject.toml [project.dependencies]
requests = ">=2.31"
beautifulsoup4 = ">=4.12"
openai = ">=1.30"         # DeepInfra OpenAI互換クライアント
pydantic = ">=2.7"

# [project.optional-dependencies]
# dev =
pytest = ">=8.0"
ruff = ">=0.4"
mypy = ">=1.10"
```

**システム依存:**
- Python 3.12+
- ffmpeg 6.x+（HLSダウンロード + WAVセグメント分割）

---

## リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| shugiintv.go.jpのHTML構造が変わっている | スクレイピング失敗 | フィクスチャHTMLを先に取得して構造を確認。実際のHTMLとARCH.mdの記述が一致しない場合はARCH.mdを修正 |
| HLSストリームのダウンロードが遅い/失敗する | 音声取得不可 | ffmpegのタイムアウト設定。リトライ1回。失敗時は手動ダウンロードも選択肢 |
| Whisperの固有名詞認識精度が低い | utterancesの質低下 | promptパラメータに候補者名を明示。後段のLLM話者タグ付けで補正 |
| LLMの話者タグ付け精度が不十分 | Q&Aペアの質低下 | プロンプトの反復改善。委員長指名パターンのルールベース前処理を追加 |
| DeepInfra APIのレート制限 | 処理遅延 | セグメント間にsleep挿入。Phase 1は1セッションなので問題は小さい |
| 本会議の発言構造が委員会と異なる | パーサーの仮定が壊れる | deli_id=56149は本会議。代表質問形式のため、委員長→質疑者→答弁の単純パターンが多い。Phase 2以降で委員会形式に対応 |
