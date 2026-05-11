# 品質監査・結果集約フォーマット

## 目的

全156セッションの品質監査をサブエージェント並列で実施し、結果を**機械集約可能**かつ**人間可読**な形で記録する。

主目的は再生成パイプライン (`STRUCTURER_REWRITE.md` で計画中の刷新を含む) に反映すべき「**横断的問題**」を浮かび上がらせること。単発バグではなく、**同種問題が複数セッションで再発しているパターン**を発見することがゴール。

## 監査担当モデル

サンプルテスト (3セッション × Sonnet/Haiku) の結果、内容に踏み込んだ問題 (誤帰属・欠落・事実誤認・Whisperハルシネーションの定量化等) は **Sonnet が圧倒的に強い**。本格監査は **Sonnet** を使用。

機械チェック (schema validation、null count、重複検出、表記ゆれ集計) は別途スクリプトで全件処理する想定 (本フォーマットの対象外)。

## サブエージェント実行モデル

- **1セッション = 1エージェント** (1セッションをまとめて読むため)
- 並列度は3〜6 (アカウントの並列上限と相談)
- 各エージェントは下記の **出力フォーマット** に厳密に従う
- 全エージェント終了後、JSON ブロックを集約して横断分析

## 分類定義

### Issue カテゴリ (closed taxonomy)

集約時にクロス集計するため、必ずいずれか1つに分類する。複数該当する場合は最も主要なものを選び、`secondary_categories` に副次分類を列挙する。

| カテゴリ | 説明 | 例 |
|---|---|---|
| `whisper_hallucination_loop` | Whisperの繰り返しループ・ハルシネーション | 「議長＊小寺君。」が6904回繰り返し |
| `whisper_misrecognition` | Whisperによる人名・地名・固有名詞の誤認識 | 八潮市→八代市、山本大地→山本大臣、内閣府→政党 |
| `speaker_misattribution` | 話者誤帰属 (質問者/答弁者の誤り) | qa_069 質問者が `川裕一郎` だが実は `中村はやと` |
| `content_missing` | コンテンツ欠落 (segment 全体が qa_pairs から消える等) | 片山さつき財政演説3,588字が qa_pairs に1件もない |
| `role_label_error` | `role` フィールドの誤分類 | 議長を「委員長」、事務総長を「質疑者」 |
| `schema_empty_field` | 必須フィールドの空/null | `answer.role=""` (98.6%)、`metrics=null` (24.6%) |
| `schema_inconsistency` | スキーマ一貫性の問題 (null↔空文字、表記ゆれ等) | duration=""、committee_id=null の混在 |
| `metadata_missing_speaker` | metadata.speakers に答弁者・参考人が未登録 | 30名以上の答弁者が speakers リスト外 |
| `summary_qa_divergence` | summary/topics と qa_pairs の内容乖離 | summary が qa_pairs にない事実を言及 |
| `timestamp_inconsistency` | 時刻の不整合 | start_seconds と start_time が約7分ズレ、video_url の time が他話者の値 |
| `duplicate` | 重複 (同一話者複数登録、同一テキスト等) | 山下貴司が午前/午後で2エントリ |
| `fact_error` | 事実誤認 (LLM補正による情報改変) | OSC略語の創作、`財政投融資` → `財政投入` |
| `transcript_truncation` | full_text 途切れ (**既知問題、対象外**) | (記録不要) |
| `other` | 上記に該当しないその他 | UI 表示への影響等 |

### Severity (重要度)

| 値 | 基準 |
|---|---|
| `high` | データ利用者が誤った情報を信じる/重要情報を取得できない。再生成計画に必ず反映すべき |
| `medium` | データ品質が損なわれるが、利用者は気付ける/補正できる |
| `low` | スキーマ整合性、表記ゆれ、軽微な欠損 |

### Confidence (確信度)

監査担当が誤検知する可能性の自己評価。

| 値 | 基準 |
|---|---|
| `high` | 直接的な証拠あり (テキスト引用、JSON値) で誤検知の可能性低い |
| `medium` | 状況証拠あり、文脈解釈が必要 |
| `low` | 直感ベース、要二次確認 |

### Systemic signal (横断性)

横断分析時に最重要のフラグ。

| 値 | 基準 |
|---|---|
| `likely_systemic` | パイプラインの構造的欠陥が原因。同種問題が他セッションでも発生している可能性が高い |
| `session_specific` | 当該セッション固有の事象 (特殊な音声、稀な議事進行等) |
| `unknown` | 単一セッションからは判断不能 |

## 出力フォーマット (サブエージェント側)

### Section 1: JSON ブロック (機械集約用)

監査結果を**最初に**この JSON ブロックで出力する。1セッション = 1 オブジェクト。

```json
{
  "session_id": "shugiin/2026/02/18/56074_本会議",
  "chamber": "shugiin",
  "date": "2026-02-18",
  "deli_id": "56074",
  "committee": "本会議",
  "auditor_model": "claude-sonnet-4-6",
  "audit_at": "2026-05-10T14:30:00Z",
  "overall_quality": "medium",
  "issue_count": {"high": 4, "medium": 4, "low": 4, "total": 12},
  "findings": [
    {
      "id": "F001",
      "category": "speaker_misattribution",
      "secondary_categories": ["role_label_error"],
      "severity": "high",
      "confidence": "high",
      "systemic_signal": "likely_systemic",
      "title": "qa_069 の質問者が誤帰属 (川裕一郎 → 実際は中村はやと)",
      "location": {
        "file": "qa_pairs.json",
        "json_path": "$.pairs[68].question.speaker",
        "segment_index": 9,
        "qa_id": "qa_069"
      },
      "evidence": "qa_pairs.json では speaker=川裕一郎 だが、raw_transcript segment 9 で委員長が「中村君。」と呼び、その後の発言内容 (高市総理批判、「主婦一名では高市早苗さんの名前を書いている」) は中村はやとの政治的立場と一致。",
      "estimated_cause": "speaker_tagger が segment 9 の audio clip ラベル (川裕一郎) をそのまま付与し、後半の話者交代 (川 → 中村) を検出できなかった。委員長の指名「中村君」を Whisper が「長妻君」と誤認識したことも一因。",
      "downstream_impact": ["topics.json", "summary.json"]
    }
  ],
  "blindspots": [
    "raw_transcript の segment 全体を逐字精査していない (サンプリングのみ)",
    "外部の議員名簿との照合は未実施"
  ]
}
```

#### フィールド仕様

**トップレベル:**
- `session_id` (string, required): `{chamber}/YYYY/MM/DD/{deli_id}_{委員会名}` 形式。集約キー
- `chamber`, `date`, `deli_id`, `committee` (string, required): メタデータ抜粋
- `auditor_model` (string, required): モデル ID (`claude-sonnet-4-6` 等)
- `audit_at` (ISO8601, required): 監査実施タイムスタンプ
- `overall_quality` ("high"|"medium"|"low", required): セッション全体の主観評価
- `issue_count` (object, required): 重要度別集計。`total` は和に一致すること
- `findings` (array, required): 発見問題のリスト
- `blindspots` (array of string, optional): 自己評価による見落とし観点

**finding オブジェクト:**
- `id` (string, required): セッション内連番 (F001, F002, ...)
- `category` (enum, required): 上記カテゴリ表より1つ
- `secondary_categories` (array, optional): 副次分類
- `severity` (enum, required): high/medium/low
- `confidence` (enum, required): high/medium/low
- `systemic_signal` (enum, required): likely_systemic/session_specific/unknown
- `title` (string, required): 1行要約 (60字以内)
- `location` (object, required):
  - `file`: 主たる証拠ファイル (`qa_pairs.json` 等)
  - `json_path`: JSONPath (`$.pairs[3].answer.speaker` 等)
  - `segment_index` (optional): 関連 segment_index
  - `qa_id` (optional): 関連 qa_id
- `evidence` (string, required): 直接引用または具体的な参照。後で再現できる粒度
- `estimated_cause` (string, required): パイプラインのどの段階が原因か
- `downstream_impact` (array, optional): 影響波及するファイル

### Section 2: Narrative Summary (人間可読)

JSON ブロックの**後に**通常の Markdown でナラティブを記述する。集約時には Section 1 のみ使うが、レビュー時の参照用。

```markdown
## 総合評価

セッションの全体品質、印象、特筆事項を 3-5文で記述。

## 注目すべき発見 (Top 3)

1. **{title}** — 重要な理由を1-2文
2. ...
3. ...

## 見落とし可能性のある観点

- {blindspot 1}
- {blindspot 2}
```

## サブエージェント用プロンプトテンプレート

```
あなたは国会議事録データベース (kokkaidb) の品質監査担当です。

## 背景
衆議院TV/参議院TVのアーカイブ動画 → Whisper文字起こし → LLM構造化したデータが
`data/{chamber}/YYYY/MM/DD/{id}_{委員会名}/` 以下に保存されている。
各ディレクトリのJSON:
- metadata.json / raw_transcript.json / utterances.json
- qa_pairs.json / summary.json / topics.json

## 既知の問題 (調査対象外)
qa_pairs.json の full_text 途切れ問題は対応済み。**それ以外**の品質問題を探してほしい。
カテゴリ `transcript_truncation` には記録しないこと。

## 調査対象
{SESSION_PATH}

## 調査の観点
- Whisperハルシネーション・誤認識
- 話者誤帰属、role誤分類
- コンテンツ欠落 (segment全体が qa_pairs から消える等)
- summary/topics と qa_pairs の内容乖離
- スキーマ一貫性 (空フィールド、null/空文字混在、表記ゆれ)
- メタデータ正確性 (日付、委員会、speakers の網羅性)
- 時刻整合性 (start_seconds vs start_time、video_url の time)
- 事実誤認 (LLM補正による情報改変)
- その他データ利用者にとって支障となる問題

## 出力フォーマット

**docs/QUALITY_AUDIT_FORMAT.md** に従う。具体的には:

### Section 1: JSON ブロック (最初に出力)
```json
{
  "session_id": "...",
  "chamber": "...",
  "date": "...",
  "deli_id": "...",
  "committee": "...",
  "auditor_model": "claude-sonnet-4-6",
  "audit_at": "{現在時刻 ISO8601}",
  "overall_quality": "high|medium|low",
  "issue_count": {"high": N, "medium": N, "low": N, "total": N},
  "findings": [
    {
      "id": "F001",
      "category": "<closed taxonomy のいずれか>",
      "secondary_categories": [],
      "severity": "high|medium|low",
      "confidence": "high|medium|low",
      "systemic_signal": "likely_systemic|session_specific|unknown",
      "title": "...",
      "location": {"file": "...", "json_path": "...", "segment_index": N, "qa_id": "..."},
      "evidence": "...",
      "estimated_cause": "...",
      "downstream_impact": []
    }
  ],
  "blindspots": []
}
```

カテゴリは下記から1つ:
whisper_hallucination_loop / whisper_misrecognition / speaker_misattribution /
content_missing / role_label_error / schema_empty_field / schema_inconsistency /
metadata_missing_speaker / summary_qa_divergence / timestamp_inconsistency /
duplicate / fact_error / other

### Section 2: Narrative Summary (Markdown)
- 総合評価 (3-5文)
- 注目すべき発見 Top 3
- 見落とし可能性

時間をかけてファイルを丁寧に読み、相互参照して矛盾を探すこと。
JSON は valid であること (集約時に jq で処理する)。
```

## 集約方法

### ファイル配置

各サブエージェントの JSON 出力を `docs/audit-results/{session_id with slashes -> dashes}.json` に保存。

```
docs/audit-results/
├── shugiin-2026-02-18-56074-本会議.json
├── shugiin-2026-04-24-56211-内閣委員会.json
└── ...
```

### 横断集計 (jq)

```bash
# カテゴリ × 重要度のクロス集計
jq -s '
  [.[].findings[]] |
  group_by(.category) |
  map({
    category: .[0].category,
    high: map(select(.severity=="high")) | length,
    medium: map(select(.severity=="medium")) | length,
    low: map(select(.severity=="low")) | length,
    total: length,
    systemic_share: (map(select(.systemic_signal=="likely_systemic")) | length)
  }) |
  sort_by(-.total)
' docs/audit-results/*.json

# likely_systemic で頻発しているもの = 再生成パイプラインで優先修正すべき
jq -s '
  [.[].findings[]] |
  map(select(.systemic_signal=="likely_systemic")) |
  group_by(.category) |
  map({category: .[0].category, count: length, examples: [.[0:3][] | .title]}) |
  sort_by(-.count)
' docs/audit-results/*.json

# セッション別の品質スコア (high問題が多いほど低品質)
jq -s '
  map({
    session: .session_id,
    quality: .overall_quality,
    high: .issue_count.high,
    total: .issue_count.total
  }) | sort_by(-.high)
' docs/audit-results/*.json
```

### 再生成計画への反映

1. `likely_systemic` で **5セッション以上** に出現するカテゴリ → パイプライン側の修正必須
2. `severity=high` が **特定モデル/特定ScraperPath** に集中 → 該当箇所のリファクタ対象
3. カテゴリ別に代表事例を抽出 → 再生成後の検証テストケースに転用

## 運用上の注意

- **JSON の妥当性**: サブエージェントが壊れた JSON を出すと集約がコケる。プロンプトで「JSON は valid であること」を明示し、集約スクリプト側でも `jq -e .` で検証する
- **重複検出**: 同じ問題を複数の finding に分割しないよう、エージェントに「最も顕著な現れに統合する」と指示
- **既知問題の除外**: `transcript_truncation` は対象外であることをプロンプトで2回明記する (見落としやすい)
- **コスト**: Sonnet で1セッション平均 ~120k tokens × 156セッション = ~19M tokens。並列度に応じて wall-clock を調整

## 関連ドキュメント

- `docs/STRUCTURER_REWRITE.md` — 既に判明している `transcript_truncation` 問題の刷新計画
- `docs/ISSUES.md` — 既知の課題ログ
- `CLAUDE.md` — プロジェクト全体ガイド
