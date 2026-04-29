# 国会議事録リアルタイムDB — データ生成プロセス・データ品質レビュー

サイト閲覧時に「明らかに生成失敗している」と感じるデータが多数ある状況を受けて、
パイプライン（kokkai-transcriber/）と生成済みデータ（`data/shugiin/` 配下 140 セッション）を
網羅的に精査したレビュー。**前回の `docs/uiux-review/` の姉妹編**として、UI/UX ではなく
バックエンド側（モデル・プロンプト・スキーマ・パイプライン分割）の問題点を扱う。

## このレビューの読み方

- **章ごとに 1 ファイル**。問題ドメインごとに分けてある。
- **すぐ着手したい人**は `99-priority-roadmap.md` の P0 から見れば良い。
- **章末に「具体的な改善案」**を箇条書きで添えている。
- 失敗例は実ファイルパスと jq 集計に基づく実数で記述している（再現可能）。

## 章構成

| #  | ファイル | 概要 |
|----|---------|------|
| 1  | [01-overview.md](01-overview.md) | 全体像・主要メトリクス・致命傷 Top 5 |
| 2  | [02-cross-cutting-issues.md](02-cross-cutting-issues.md) | パイプライン全体に跨る根本的不具合 |
| 3  | [03-pipeline-architecture.md](03-pipeline-architecture.md) | 7 ステップの構造と「責務の漏れ」 |
| 4  | [04-transcription.md](04-transcription.md) | Step 4 / 4.5: Whisper 文字起こし＋校正 |
| 5  | [05-speaker-tagging.md](05-speaker-tagging.md) | Step 5: 話者交代検出（utterances.json） |
| 6  | [06-qa-extraction.md](06-qa-extraction.md) | Step 6 前半: Q&A ペア抽出（qa_pairs.json） |
| 7  | [07-summary-topics.md](07-summary-topics.md) | Step 6 後半: 要約・トピック・コミットメント |
| 8  | [08-name-normalization.md](08-name-normalization.md) | 発言者名・役職の正規化（横串） |
| 9  | [09-law-tagging.md](09-law-tagging.md) | 関連法案タグの網羅性（recall: 67% のセッションで 0 件）|
| 9b | [09b-law-tagging-accuracy.md](09b-law-tagging-accuracy.md) | 関連法案タグの精度（precision: 副タグの 1/3 が委員会所管外）|
| 10 | [10-schema-and-contracts.md](10-schema-and-contracts.md) | データ持ち方・スキーマ・モデル契約違反 |
| 11 | [11-prompts-and-models.md](11-prompts-and-models.md) | プロンプト設計とモデル選定の課題 |
| 99 | [99-priority-roadmap.md](99-priority-roadmap.md) | P0〜P3 のロードマップ |

## 全体感（Executive Summary）

### 良いところ（残したい設計）

- **JSON ファイルベースの状態管理**は、再現性・冪等性・git diff レビューの観点で優秀。
  `data/{chamber}/YYYY/MM/DD/{id}_{committee}/qa_pairs.json` の存在で「処理済み」を判定する
  シンプルさが効いている（`batch.py` で SQLite を捨てた判断は正しい）。
- **Whisper プロンプトの「直前文脈」設計**（`transcriber.py:42-67`）は理解が正しく、
  224 token 制限の中で固有名詞をスタイル模倣として埋め込めている。
- **校正ステップ（Step 4.5）の安全網**：80% 未満に縮んだチャンクと「……」を含むチャンクを
  棄却する仕組み（`transcript_corrector.py:303-318`）は LLM 暴走に対する正しい防衛。
- **Q&A 抽出での `sentence_indices` 設計**（`structurer.py:46-50`）：LLM に full_text を返させず
  index だけ返させてコード側で組み立てる方針は、トークン削減・捏造防止・整合性の三方良し。

### 致命傷（P0：本格稼働前に直すべき）

1. **140 セッション中 22（15.7%）で `qa_pairs.json` が空配列**。本会議の趣旨説明・解任決議案・
   討論など「Q&A 構造を持たない」セッションでも Step 6 を実行しており、結果として LLM が
   何も返せない／空ペアを乱発する。**そもそもこの種のセッションを Q&A 抽出に通すべきでない**
   （詳細: [03-pipeline-architecture.md](03-pipeline-architecture.md), [06-qa-extraction.md](06-qa-extraction.md)）。
2. **140 セッション中 21（15%）で `topics.json` が空**にもかかわらず `summary.json` の
   `key_topics` には値が入っている。同一 LLM 呼び出しで両方を生成する設計（`structurer.py:665`）が、
   Gemma の出力 truncation により後半（`topics`, `key_commitments`, `related_laws`）を
   落としていると推定される。`max_tokens=8192` と「全部入り JSON」の組合せが原因
   （詳細: [07-summary-topics.md](07-summary-topics.md), [11-prompts-and-models.md](11-prompts-and-models.md)）。
3. **法案タグは「付かない」だけでなく「付いているタグの 1/3〜半数が誤り」**：
   recall 観点では 140 セッション中 94（67%）で `related_laws` が空。precision 観点では
   タグが付いているセッションでも、副タグの 33%（14/42）が委員会所管外、主タグも 12.5%
   （5/40）が誤り、さらに `qa_ids: []` の幽霊タグが 7 件。原因はプロンプトに
   `committee` 名が一切渡されておらず、LLM が 75 法案リストと Q&A 要約だけで
   キーワードマッチを試みているため
   （詳細: [09-law-tagging.md](09-law-tagging.md), [09b-law-tagging-accuracy.md](09b-law-tagging-accuracy.md)）。
4. **発言者名の表記揺れが多数残っている**。`高市早苗` / `高市` / `高市内閣総理大臣` /
   `高市総理大臣` の 5 通り、`赤澤亮正` / `赤澤大臣` / `赤澤経済産業大臣` /
   `赤澤国家公安委員長`（誤）/ `赤澤防災大臣`（誤）の 5 通りなど。
   ダッシュボードの「発言者分析」が効かない直接的な原因
   （詳細: [08-name-normalization.md](08-name-normalization.md)）。
5. **5 セッションで `committee="不明"`**。スクレイパーの正規表現
   （`shugiin.py:212` の `[一-鿿]+委員会`）が、ページ内に `内閣委員会` のような
   完全な委員会名がなく `内閣委員長` しか出てこない場合に失敗する
   （詳細: [02-cross-cutting-issues.md](02-cross-cutting-issues.md)）。

### サイト全体への提言（章を跨いだ方向性）

- **「セッション種別」を一級概念にする**。本会議（趣旨説明）／本会議（代表質問）／本会議
  （討論・解任）／委員会（質疑応答）／委員会（参考人）のいずれかを `metadata.json` に持たせ、
  Step 6 の挙動を分岐させる。Q&A 抽出はそもそも全セッションでやるべき処理ではない。
- **Step 6 を 3 つに分割**する：(a) Q&A 抽出、(b) 要約・トピック、(c) 法案タグ付け。
  現在は (b)+(c) を 1 リクエストで返す全部入り JSON 設計が truncation 事故を起こしている。
  独立した責務はそれぞれ独立したプロンプト＋呼び出しに分けるのが LLM 工学の基本。
- **発言者名の正規化レイヤを Step 5 と Step 6 の間に挟む**。`metadata.json` の speakers を
  ground truth として、`utterances.json` 内の `speaker` を機械的に一意名へマッピングする。
  LLM が出力した raw 名を保存層に流さない。
- **`SpeakerInfo.role` を必ず埋める**。現在 1367 名すべて `role=""`。`affiliation` から
  「委員長／議長／大臣／政府参考人」を機械的に判定して入れるだけで、Q&A の答弁者解決精度が
  大幅に上がる。
- **`evasion_score` の生成条件を厳格化**。現在 217 ペアが「答弁テキスト 0 字 + 回避度 1.0」
  という矛盾を抱えている。**そもそも答弁が空のペアは Q&A ペアとして成立していない**ので
  生成段階で破棄するか、`status: "no_answer"` のような別フィールドで明示する。

### メトリクス・サマリー（参照用）

| メトリクス | 値 |
|-----------|---|
| 処理済み衆議院セッション | 140 |
| 総 Q&A ペア数 | 6,308 |
| Q&A 0 件のセッション | 22（15.7%）|
| `topics.json` 空のセッション | 21（15%）|
| `related_laws` 0 件のセッション | 94（67%）|
| `committee="不明"` のセッション | 5 |
| `committee="特別委員会"`（具体名欠落） | 4 |
| 答弁本文 5 字未満 + 回避度 1.0 のペア | 217 |
| 全 metadata で `SpeakerInfo.role=""` | 1367/1367（100%）|
| 評価件数 < 5 の発言者比率（UI/UX レビュー由来） | 83%（966/1160 名）|

> 上記は 2026-04-29 時点の `data/` スナップショットに対する `find ... | xargs jq` 集計。
