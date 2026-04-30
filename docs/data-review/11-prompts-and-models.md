# 11. プロンプトとモデル選定

## 11.1 モデル選定の現状

| ステップ | モデル | コスト感（DeepInfra）| 出力長 |
|---------|--------|-------------------|--------|
| Step 4 (Whisper) | `openai/whisper-large-v3-turbo` | $0.0002/分 | 数千〜数万字 |
| Step 4.5 (校正) | `deepseek-ai/DeepSeek-V3.2` | $0.27/M input, $0.40/M output | 入力と同程度 |
| Step 5 (話者タグ) | `deepseek-ai/DeepSeek-V3.2` | 同上 | 100〜500 字 (splits だけ) |
| Step 6a (Q&A) | `google/gemma-4-31B-it` | $0.10/M (cheaper) | 数千字 |
| Step 6b (要約等) | `google/gemma-4-31B-it` | 同上 | 数千字 |

`benchmark_models.py` と `benchmark2.log` で比較した結果、`structurer.py:17` のコメントには：
```
# Step 6はgemma-4-31Bを使用（ペア数抽出がV3.2より安定: 10/10 vs 6/10）
```
とある。当時の実測を信じるなら gemma の方が Step 6 の Q&A 抽出には強い。

## 11.2 観測されているモデル選定の問題

### A. Step 5 で DeepSeek を使い続ける合理性

`benchmark2.log:42-50`（Step 5 ベンチ）：
```
gpt-oss-120b: splits=3 (ref=3) | name_overlap=1.00 | speakers正確
gemma-4-31B-it: splits=3 (ref=3) | name_overlap=1.00 | speakers正確
DeepSeek-V3.2: splits=3 (ref=3) | name_overlap=1.00 | speakers正確（高階を加筆）
```

Segment 1 では 3 モデルとも正解。Segment 2 では：

```
gemma: splits=6 (ref=3) ← 過剰分割（委員長指名で都度切る）
DeepSeek: splits=3 (ref=3) ← 一致
```

**Step 5 では DeepSeek が gemma より精度が高い**ように見える。一方、

`benchmark2.log:11-19`（Step 4.5 ベンチ、健康保険法質疑）：
```
gemma: similarity=0.968 | len_ratio=0.99 ← 出力で「介護保険」を残す
DeepSeek: similarity=0.982 | len_ratio=1.01 ← 同様に「介護保険」を残す（少し改善傾向）
gpt-oss: similarity=0.957 | len_ratio=0.97
```

Step 4.5 では DeepSeek 微優位だが大差なし。コスト的には gemma の方が 30% 安い。

### 改善案

- **Step 4.5**: 短いチャンク（< 1000 字）は gemma に切り替え、長いチャンク（>= 1000 字）は
  DeepSeek を維持（コスト最適化）。
- **Step 5**: DeepSeek を維持（精度優位）。ただしプロンプトに「文脈にいない発言者を加筆しない」を
  追加して加筆癖を抑制。
- **Step 6a**: gemma 維持。
- **Step 6b**: gemma の代わりに、出力構造のシンプルさを優先するなら gpt-oss-120b を試す価値あり。

### B. Whisper のモデル選択肢が狭い

現状 `openai/whisper-large-v3-turbo` 固定。**Diarization（話者分離）**機能を持つ
モデル（pyannote、whisperX、Reverse-Whisper）は使っていない。

- セグメント分割をスクレイパーのタイムスタンプに頼っている
- セグメント内の話者交代は LLM（Step 5）に任せる

これは現実的な妥協だが、**衆議院 TV のタイムスタンプが粗い場合**（次の発言者の開始から
30 秒前に切り替わる等）に Whisper が「前の発言者の終わり」を取りこぼすリスクがある。

### 改善案
- 当面はそのまま。`no_speech_prob` が高いセグメントを警告するくらい
- 中長期で WhisperX （word-level timestamps + diarization）の検証を行う価値がある

### C. プロンプトキャッシュの活用が不十分

DeepSeek-V3.2 / gemma-4-31B はどちらも prompt caching に対応している
（`transcript_corrector.py:27` のコメントにも記載）。

#### 現状

- Step 4.5 / 5 / 6a で **system prompt が同じ** なので、これは自動キャッシュされる
- ただし **user prompt の構造**（speaker_list, session_context など）も再利用できる部分がある

#### 改善案

`speaker_tagger.py:117-125` を「定型部分」と「動的部分」に分離：

```python
# 定型部分（キャッシュされる）
prefix = f"""セッション情報:
委員会: {committee}
発言者リスト:
{speaker_list}
"""

# 動的部分（毎回違う）
suffix = f"""主発言者: {segment_speaker.name}（{segment_speaker.affiliation}）

以下の番号付き文リストの話者交代ポイントを検出してください（{n}文）:
{numbered_text}"""

# 結合して送信。キャッシュ効率が上がる
```

DeepInfra のキャッシュ仕様にも依るが、こうすると同一セッション内の Step 5 呼び出し
（segments 数 = 30〜50 回）で `speaker_list` のキャッシュヒットが効く。

### D. Step 6b の `max_tokens=8192` が小さい

5 種類の出力（session_summary, key_topics, key_commitments, topics, related_laws）を
返すには 8192 が **十分とは言えない**。topics が空になる事故（21/140）の主因の 1 つと
推察される。

#### 改善案

- 単純に `max_tokens=16384` に上げる（Gemma は対応済み）
- ただし長い session ではそれでも足りない可能性。Step 6b 分割（[02 §2.6](02-cross-cutting-issues.md#26-構造化-llm-呼び出しの-全部入り-json-が事故源)）が本筋

### E. プロンプトの「ペナルティ表現」が一部弱い

`structurer.py:40-81` の `QA_SEGMENT_SYSTEM_PROMPT`：

```
重要なルール:
- 質疑者が複数のテーマについて質問した場合、テーマごとに別のQ&Aペアを作成すること
- 1つも漏らさずに抽出すること
```

この「漏らさずに」が **過抽出** を促している。
討論セッションで Q&A が無くても LLM は何かを返そうとする。

`transcript_corrector.py:106-113` の禁止事項は明確：
```
## 禁止事項
- テキストの意味を変えない。要約・省略・追加をしない
- 発言の順序を変えない
- 存在しない発言を捏造しない
- 発言者リストに記載された名前の表記を勝手に変えない
- 「……」を出力しない。聞き取れない箇所があっても元のテキストをそのまま残すこと
```

Step 6a / 6b にも同レベルの **「禁止事項」セクション**を追加すべき：

```
## 禁止事項
- 答弁が無い質問を Q&A ペアにしない
- 同じ答弁を複数のペアに使わない
- セグメントの主発言者がいない場合、無理に Q&A を作らない
- 発言者リストにない人名を返さない（「質問者」「発言者」のような汎用ラベルも禁止）
```

### F. プロンプトに「セッション種別」のヒントが無い

[02-cross-cutting-issues.md §2.1](02-cross-cutting-issues.md#21-セッション種別が一級概念になっていない) で議論した通り、
プロンプトはセッションが質疑応答だと暗黙に仮定している。
本会議の代表質問・討論・採決などのセッションでは、この仮定が成立しない。

### 改善案

`session_kind` フィールドを `metadata.json` に持たせて、Step 6 のシステムプロンプトに
注入する：

```python
SYSTEM_PROMPT_QA = """あなたは国会質疑のQ&Aペアを構造化する専門家です。
セッション種別: {session_kind}

[session_kind == 'regular_qa' のとき]
質疑者が大臣に質問し、大臣が答弁するパターンを抽出してください。

[session_kind == 'representative_questions' のとき]
冒頭の趣旨説明（質問なし）はスキップし、代表質問者ごとの「複数質問+一括答弁」パターンを抽出してください。

[session_kind == 'floor_speech' のとき]
このセッションには Q&A 構造はありません。空の `pairs: []` を返してください。
"""
```

## 11.3 プロンプト個別の指摘

### Step 4.5 (`transcript_corrector.py:38-113`)

| 箇所 | 評価 | コメント |
|------|------|---------|
| 修正ルール 1（句読点）| ✓ | 表層編集として明確 |
| 修正ルール 2（固有名詞）| ✓ | リファレンスリストが詳細 |
| 修正ルール 3（同音異義語）| ⚠ | 文脈理解必要、効果薄（[04 §A](04-transcription.md#a-固有名詞修正が肝心なところで効かない)） |
| 修正ルール 4（フィラー除去）| ✓ | |
| 修正ルール 5（改行）| ⚠ | 「話者交代の可能性がある箇所で改行」が曖昧 |
| 政党・閣僚リファレンス | ✓ | 第 221 回固有として明確 |
| 禁止事項 | ✓ | 5 項目が明確 |
| 「プレーンテキスト」指定 | ✓ | JSON ではなくテキストを要求 |

### Step 5 (`speaker_tagger.py:28-64`)

| 箇所 | 評価 | コメント |
|------|------|---------|
| 検出ルール 1〜4 | ✓ | 役職判定の手がかりを示している |
| 委員長指名と質疑者の区別 | ✓ | サンプル付きで丁寧 |
| 出力形式 | ✓ | sentence index ベースが優秀 |
| roleの enum | ⚠ | 規約違反 31 件（[05 §A](05-speaker-tagging.md#a-役割role-の値が規約違反)） |
| 「テキストは絶対に含めない」| ✓ | 効果的 |

### Step 6a (`structurer.py:40-81`)

| 箇所 | 評価 | コメント |
|------|------|---------|
| 重要なルール | ⚠ | 「漏らさず」が過抽出を促進 |
| sentence_indices 設計 | ✓ | LLM 工学の手本 |
| evasion_score の目安 | ⚠ | 答弁空 → 1.0 の暗黙化（[06 §A](06-qa-extraction.md#a-答弁が空のペアが大量に生成される217-件)） |
| 禁止事項なし | ✗ | 追加すべき |
| セッション種別の概念なし | ✗ | 追加すべき |

### Step 6b (`structurer.py:83-124`)

| 箇所 | 評価 | コメント |
|------|------|---------|
| トピック抽出ルール | ⚠ | 「政策領域・法案・社会問題などの観点から分類」が曖昧 |
| 関連法案タグ付けルール | ⚠ | 「確信度が低いものは含めない」が過剰保守化 |
| 出力形式 | ✗ | 5 種一括が truncation の原因 |
| key_topics と topics.name の関係 | ✗ | 重複定義になっている |

## 11.4 改善案サマリー

- [ ] **[P0]** Step 6a / 6b に「禁止事項」セクションを追加
- [ ] **[P0]** `session_kind` をプロンプトに注入し挙動分岐
- [ ] **[P0]** Step 6b の `max_tokens` を 16384 に（暫定）
- [ ] **[P1]** Step 4.5 のチャンク長別モデル切り替え（短い: gemma, 長い: DeepSeek）
- [ ] **[P1]** プロンプトキャッシュを意識した structure（定型 prefix を分離）
- [ ] **[P1]** Step 6a の「漏らさず」を「Q&A 構造があるもののみ漏らさず」に修正
- [ ] **[P2]** Step 5 のプロンプトに「文脈にいない発言者を加筆しない」追加
- [ ] **[P2]** WhisperX / pyannote diarization の検証
