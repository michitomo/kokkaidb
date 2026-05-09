# Structurer 完全刷新計画 — utterance ベーススキーマへの移行

> **作成日**: 2026-05-10
> **ステータス**: 計画段階（実装前）
> **対象**: `kokkai-transcriber/src/structurer.py` および `src/prompts.py:QA_SEGMENT_SYSTEM_PROMPT`
> **影響範囲**: `qa_pairs.json` の `question.full_text` / `answer.full_text` の組み立てロジックと、それに依存する下流処理（summary, topics, key_commitments, law_tagging, metrics）

---

## ⚠️ 実装前提：全生成済みセッションの削除

**この計画を実装する前に、`data/shugiin/` および `data/sangiin/` 配下の生成済みセッションを全削除し、ゼロから再生成する**。

理由:
- スキーマ変更により旧データとの互換性が無くなる
- 既存データには既知の品質問題が複数存在しており（後述）、部分的なマイグレーションでは品質が揃わない
- 全データ再生成のコストは許容範囲（138セッション × DeepInfra 料金）

実行手順:
```bash
# バックアップ（必要なら）
cp -r data/ data.backup-2026-05-10/

# 全削除
rm -rf data/shugiin data/sangiin data/search-index
rm -f site/public/api/search-index.json

# 状態DBもリセット
rm kokkai-transcriber/state.db  # 必要に応じて

# 新パイプラインで再生成
cd kokkai-transcriber
python -m src.batch --chamber shugiin --since 2026-02-01 --workers 4
python -m src.batch --chamber sangiin --since 2026-02-01 --workers 4
```

---

## 1. 問題の背景

### 1.1 観測された症状

ユーザーから「Q&Aペアの答弁が途中で切れている」との指摘。具体例:

セッション `data/shugiin/2026/04/24/56209_厚生労働委員会` の qa_022（浜地雅一質問・田中雇用環境均等局長答弁）:

**正規の議事録での全文**:
> お答えいたします。年収の壁・支援強化パッケージの、先生御言及のありました対応策の一つとして実施をしておりましたキャリアアップ助成金です。社会保険適用時処遇改善コースということで実施をしておりましたが、その執行状況、令和六年度の支給額三十一・八億円となってございます。…（中略）…**この社会保険適用時処遇改善コースにつきましては令和三年度末で終了ということにいたしまして、壁を意識せず働いていただける環境づくりを一層支援するという観点から、令和七年七月にこれを拡充いたしまして、労働者一人当たり最大七十五万円を助成ということで制度を改善をしております。できる限り多くの企業にこの助成金を活用いただけますように、周知広報に一層取り組んでまいりたいと考えております**

**現状の `answer.full_text`**:
> 社会保険適用時処遇改善コースということで実施をしておりましたが、その執行状況、令和6年度の支給額31.8億円となってございます。…（中略）…この助成金につきましては、より多くの企業にご活用いただきたいというふうに考えております。

→ **冒頭の「お答えいたします。年収の壁支援強化パッケージの…キャリアアップ助成金です。」と、末尾の「令和3年度末で終了…令和7年7月に拡充…75万円を助成…周知広報に一層取り組んでまいりたい」が完全に欠落**している。

なお `utterances.json` には完全な発言が保存されている（Whisper・話者タグ付けは正常）。問題は `structurer.py` の Q&A ペア組み立て段階で発生している。

### 1.2 全データでの定量分析

衆議院138セッション・5,770ペアでの集計:

| 指標 | 数値 |
|--|--|
| 答弁の同一utterance内で末尾切れ | **21.1%**（1,220ペア） |
| 質問の同一utterance内で末尾切れ | **52.5%**（3,104ペア） |
| utteranceが1ペアにのみ属する | 38.1%（7,848件 / 20,580件） |
| utteranceが複数ペアに属する | **1.0%**（208件） — 代表質問・所信表明 |
| utteranceがどのペアにも属さない | 60.9%（≒委員長指名・点呼など手続き発言） |
| `_INPUT_CHAR_LIMIT=20000` で切り捨てられる長セグメント | 33セグメント |

### 1.3 根本原因

現状の設計:

1. `structurer.py` は LLM に **sentence_indices**（utterance内の文番号配列）を返させ、コードでその文を連結して `full_text` を組み立てる。
2. `prompts.py:QA_SEGMENT_SYSTEM_PROMPT` で **「挨拶・自己紹介・感謝は除外し、背景説明・問題提起は含める」** と明示指示している。
3. 入力プロンプトでは135個の文に逐一 `(N)` 番号を付与しており、長セグメントでは20000文字制限に引っかかる。

これにより:

- **設計通りの挙動**: 挨拶・前置きが `full_text` から除外される（プロンプトが指示している通り）
- **設計通りでないバグ**: LLM が「実質的内容」と「結論」の判別を誤り、本筋の答弁を途中で打ち切る（21〜52%）
- **副次的バグ**: 20000文字制限に達した長セグメントは末尾の発言が完全に LLM から見えなくなる

### 1.4 ユーザー要件の変化

> 基本的にはあいさつや前置きを含め、全ての発言がペアに登録されていて欲しいです。ただし、生成される要約にはそれを含んでほしくないです。

つまり:
- `full_text` には**挨拶・前置きを含む全発言**を入れたい
- `summary` は**実質的内容のみ**（現状通り）

これは、現状のプロンプト設計思想（「full_text からも挨拶を除外する」）とは逆向きの要件。設計レベルの方針転換が必要。

---

## 2. 採用する解決策：utterance ベーススキーマへの全面移行

### 2.1 設計原則

1. **utterance を質疑応答の最小単位とする**。utterance はもともと話者タグ付け済みで、1人の話者が連続して話した塊なので、Q&Aペアの自然な単位として整合する。
2. **`full_text` は LLM が組み立てない**。コードが `seg.utterances[i].text` を連結するだけ。LLM の判断ミスで途中欠落が原理的に起きない構造にする。
3. **`summary` は LLM が独立生成**（現状通り、プロンプトで「挨拶・背景不要」と指示済み）。
4. **複数ペアが共有する utterance（代表質問・所信表明、全体の1%）には sentence-level anchor で境界を明示**させる。

### 2.2 新スキーマ

LLM の Q&A 抽出レスポンス形式:

```json
{
  "pairs": [
    {
      "topic": "年収の壁支援強化パッケージの執行状況と評価",
      "question": {
        "utterance_indices": [12],
        "split_anchor_sentence_idx": null,
        "summary": "- 年収の壁支援強化パッケージの執行状況の確認\n- 106万の壁対策の評価",
        "intent": "information_request"
      },
      "answer": {
        "utterance_indices": [14],
        "split_anchor_sentence_idx": null,
        "summary": "- キャリアアップ助成金（社会保険適用時処遇改善コース）の支給額は令和6年度31.8億円\n- 令和7年7月に拡充し、労働者1人当たり最大75万円を助成\n- 周知広報に一層取り組む方針"
      }
    }
  ]
}
```

フィールド説明:

| フィールド | 必須 | 内容 |
|--|--|--|
| `utterance_indices` | ✓ | このペアの Q または A を構成する utterance 番号の配列。通常1個、まれに連続する複数。 |
| `split_anchor_sentence_idx` | △ | 同じ utterance を**他のペアと共有する**場合のみ設定。このペアが utterance 内のどの文から始まるかをグローバル sentence index で指定。99%のペアでは `null`。 |
| `summary` | ✓ | 「- 」箇条書き2〜4項目。挨拶・背景は不要（現状プロンプトと同じ方針）。 |
| `intent` | ✓ (Q側のみ) | fact_check / policy_proposal / accountability / information_request / other |

### 2.3 LLM への入力プロンプト形式

現状はセグメント内の全文に通し番号を振っていたが、新方式では**utterance単位で番号付け**し、長文 utterance のみ内部に sentence サブ番号を併記:

```
セグメント発言者: 浜地雅一（中道改革連合・無所属）

[U10] [質疑者] 浜地雅一:
  なぜ周知が必要かというと、この年収の壁支援強化パッケージが...
  ...御答弁をいただきたいと思います。

[U11] [委員長] 大串正樹:
  田中雇用環境均等局長。

[U12] [政府参考人] 田中雇用環境均等局長:
  お答えいたします。年収の壁支援強化パッケージの先ほど言及のありました...
  ...周知広報に一層取り組んでまいりたいと考えております。

[U13] [質疑者] 浜地雅一:
  ありがとうございます。私も手元にデータがあるんですけど...
```

代表質問・所信表明のような長文 utterance のみ:

```
[U5] [答弁者] 高市早苗:
  (s120) 内閣総理大臣高市早苗君。
  (s121) 先般の総選挙の結果を受け、首班指名をいただき...
  (s122) 重要な政策転換を何としてもやり抜いていけ...
  ...
  (s230) 量子、航空、宇宙、コンテンツ、創薬などの17の戦略分野については...
```

このとき LLM は `[{utterance_indices: [5], split_anchor_sentence_idx: 120}, {utterance_indices: [5], split_anchor_sentence_idx: 145}, ...]` のように同じ utterance を複数ペアで共有しつつ、各ペアの開始位置を anchor で示す。

### 2.4 コード側の `full_text` 組み立てロジック

```python
def assemble_full_text(seg, pair_group):
    """1つの utterance を共有する複数ペアの full_text を構築。
    pair_group: 同じ utterance を共有するペア群（ソート済み by anchor）
    """
    if len(pair_group) == 1:
        # 単独ペア: utterance全文をそのまま使う
        pair = pair_group[0]
        utts = [seg.utterances[i] for i in pair.utterance_indices]
        return "\n".join(u.text for u in utts)
    else:
        # 複数ペア共有: anchor で境界分割
        u_idx = pair_group[0].utterance_indices[0]  # 共有utterance
        utt = seg.utterances[u_idx]
        sentences = split_sentences(utt.text)
        # 各ペアの開始 sentence_idx を取得（anchor が None なら utterance 先頭=0）
        anchors = [p.split_anchor_sentence_idx for p in pair_group]
        # 連続スライス割り当て
        boundaries = sorted(set(anchors + [len(sentences)]))
        for i, pair in enumerate(sorted(pair_group, key=lambda p: p.split_anchor_sentence_idx or 0)):
            start = pair.split_anchor_sentence_idx or 0
            end = boundaries[boundaries.index(start) + 1]
            pair.full_text = "".join(sentences[start:end])
```

これにより:

- 単独ペア（99%）: 挨拶・前置き含む utterance 全文が `full_text` に入る
- 共有ペア（1%）: 各ペアは utterance 内の連続スライスを担当し、全 sentence は必ずどこかのペアに属する（穴ができない）

### 2.5 旧 `sentence_indices` 方式の廃止

現状の `_split_sentences`, `_build_sentence_map`, `_assemble_full_text_from_sentences`, `_build_sentence_to_utterance_map` は新方式では不要（または大幅縮小）。

ただし `_split_segment_into_blocks`（委員長指名による質疑ブロック分割）は引き継ぎ、新方式でも使用する。

---

## 3. 副次的に解決される既存課題

`docs/data-review/` および品質監査（§7参照）で判明した問題のうち、本刷新で同時に解消されるもの:

| 既存課題 | 解消理由 |
|--|--|
| 06-qa-extraction §A: 答弁が空のペア（217件） | utterance_indices が空の答弁ペアは出力時に弾く構造に。プロンプトでも明示。 |
| 06-qa-extraction §B: 質問が極端に短い（44件） | utterance ベースなら「趣旨説明定型句」の独立 utterance はペア化されず、自然に除外される。 |
| `_INPUT_CHAR_LIMIT = 20000` 制限（33セグメント） | utterance 単位の番号付けで入力トークンが大幅減少。20000制限を撤廃するか引き上げ可能。 |
| 過去計画ドキュメント（ISSUES.md §1-1, §1-2）の `sentence_indices` が空配列問題 | 新スキーマには `sentence_indices` 自体が無い。 |
| **answer.role が全件空文字列**（全セッション・181+件確認） | 新プロンプトで `answer.role` 生成を明示的に指示。utterance の role フィールドをコードで引き継ぐことで LLM 依存を除去できる。 |
| **本会議で議長が「委員長」と誤ラベル**（56074・56075の両本会議） | speaker_tagger プロンプトに本会議固有の役職語彙（議長/副議長/事務総長）を明示。セッション種別（本会議 vs 委員会）を入力コンテキストに加える。 |
| **本会議施政方針演説の question.full_text が「氏名呼称のみ」**（56075の qa_025–032） | 本会議施政方針演説モードを検出し、演説型セッションには質疑者/答弁者の概念を適用しない special-casing をプロンプトレベルで実装する。 |
| **summary.key_commitments が存在しない qa_id を参照**（56074・56075） | utterance ベースで qa_pair が確実に生成されるようになることで、summary 生成時の qa_id 参照先が実在する。さらに qa_id 参照整合性チェックを publisher に追加。 |
| **unmatched フラグの偽陽性**（56209で27件確認） | utterance ベーススキーマでは answer.utterance_indices で明示的に参照するため、テキスト比較による誤フラグがなくなる。 |

---

## 4. 影響範囲と移行計画

### 4.1 コード変更箇所

| ファイル | 変更内容 |
|--|--|
| `src/prompts.py:QA_SEGMENT_SYSTEM_PROMPT` | 全面書き換え（utterance_indices + split_anchor 形式の指示） |
| `src/structurer.py` | `_extract_pairs_from_response`, `_generate_qa_for_segment`, `_build_sentence_map` 周辺の全面書き換え。`_split_segment_into_blocks`, `_resolve_speaker_*`, `_resolve_answerer_*` は引き継ぎ。 |
| `src/models.py` | `QuestionDetail` / `AnswerDetail` のスキーマ確認・調整（`full_text` フィールドは残すが LLM 出力には含まれない） |
| `src/pipeline.py` | 影響なし想定 |
| `_INPUT_CHAR_LIMIT` | 撤廃または60000程度に引き上げ |

### 4.2 下流処理の影響

以下は `qa_pairs.json` を入力として動作するため、`full_text` の内容変化に対する影響を確認:

- `generate_session_summary` — `full_text` 短縮 → 完全になることでサマリー品質は向上するはず
- `generate_topics_and_key_topics` — トピック抽出は `summary` ベースなので影響軽微
- `generate_key_commitments` — `summary` ベースなので影響軽微
- `tag_related_laws` — `summary` ベースなので影響軽微
- `score_qa_pairs_metrics` — `full_text` を直接見るため、評価指標は変動する。V4 メトリクスのキャリブレーションを再確認する必要あり。

### 4.3 サイト側の影響

`site/` 配下のコンポーネントは `full_text` をそのまま表示しているだけなので、機能影響は無い。ただし表示テキストが長くなる可能性があるため、レイアウト確認は必要:

- `QAPairCard.astro` — full_text 折り畳み表示の高さ調整が必要かも
- `[chamber]/[year]/[month]/[day]/[slug].astro` — 全文表示は問題なし
- `search.astro` — Pagefind 再インデックス必要（自動化済み）

### 4.4 検証手順

実装後、以下を順に確認:

1. **単体テスト**: `tests/` 配下に新スキーマのパース・assemble ロジックのユニットテストを追加
2. **dry-run で 1 セッション再生成**: `2026/04/24/56209_厚生労働委員会` で qa_022 が完全な答弁を含むか目視確認
3. **代表質問セッションで dry-run**: `2026/02/20/56075_本会議` で高市答弁が複数ペアにきれいに分割され、かつ冒頭の「内閣総理大臣高市早苗君。先般の総選挙…」が qa_002 に含まれるか確認
4. **全 QA ペア数の比較**: 旧データと比較してペア数が極端に増減していないか
5. **サマリー品質の目視確認**: 数セッションで `summary` が挨拶を含んでいないか、内容が要約として妥当か

### 4.5 実装順序

1. プロンプト草案 (`QA_SEGMENT_SYSTEM_PROMPT_V2`) を作成
2. `structurer.py` 新版を書く（旧版は一時的に併存させても良い）
3. ユニットテスト追加
4. 手元の単一セッションで dry-run、目視確認
5. 5〜10セッションで dry-run、QA ペア数とサマリー品質の比較
6. **全生成済みセッション削除**（このドキュメント冒頭の手順）
7. 全データ再生成
8. サイトビルド・Pagefind 再インデックス
9. 旧コード（`_split_sentences` 等）削除

---

## 5. 設計判断のログ

### Q: なぜ post-processing で既存データを修正する案を採用しなかったか

post-processing 案（`docs/data-review/06-qa-extraction.md` 等で言及されていた既存方針の延長）の最大の利点は「LLM 再呼び出し不要で既存データを救える」ことだった。しかし**全データ再生成を別の品質改善目的で行う予定があり、その利点が消滅する**。

再生成前提なら、LLM への入力トークン削減・20000文字制限の自然解消・LLM 失敗モード低減・コード単純化など、すべての観点で utterance ベーススキーマが優位。

### Q: なぜ LLM に utterance_indices だけ返させず anchor も持たせるか

99% のペアで anchor は不要（`null`）。ただし代表質問・所信表明（1%、208件観測）は1人の答弁者が長大な utterance で複数のテーマを連続で話すケースがあり、これを単純に utterance 単位で扱うと「同じ full_text を持つ複数ペア」が生まれてしまう（過去にコミット `8f122f6` で発生した既知問題、`docs/ISSUES.md §1-1` 参照）。

anchor 方式で LLM に「このペアは utterance のどこから始まるか」を sentence 番号で明示させ、コードが境界を計算することで、共有 utterance も穴なく分割される。

### Q: なぜ summary プロンプトは変更しないか

現状の `prompts.py` で `summary` は「実質的な問いかけ内容のみ（挨拶・背景不要）」と指示済みで、これはユーザー要件と一致している。`full_text` の方針だけが要件と逆向きだったので、`full_text` の組み立てだけを変える。

### Q: 既存の `_resolve_answerer_from_sentences`（議員→大臣補正）は引き継ぐか

引き継ぐ。これは「議員が答弁者として誤解決された場合に、同範囲の非議員に置き換える」という防御で、新方式でも同様のロジックが必要。`sentence_indices` を使っていたインターフェースを `utterance_indices` に置き換えるのみ。

---

## 6. 未解決の論点

実装着手時に再検討する事項:

- [ ] サブ番号付き utterance（`(s120)` 形式）を LLM が安定してパース・参照できるか、実プロンプトで検証が必要
- [ ] 単一答弁が複数 utterance に分かれるケース（chair が割り込んで答弁者が再開、など）を `utterance_indices: [12, 14]` のように扱う場合、間の utterance（chair の発言）を明示的に skip する指示をプロンプトに含めるか
- [ ] 旧 `sentence_indices` 形式のテストコード・スナップショットの扱い（破棄するか新規書き起こし）
- [ ] `score_qa_pairs_metrics` (V4) が `full_text` を直接読むため、`full_text` が長くなることでスコア分布が変動する可能性。閾値再キャリブレーションの要否
- [ ] **本会議・施政方針演説の special-casing**: `session_type` フィールド（本会議 / 委員会 / 参考人質疑 等）を `metadata.json` に追加し、structurer がそれを参照してプロンプトを切り替える設計にするか
- [ ] **metadata.speakers への答弁者自動追加**: structurer が生成した qa_pairs から answer.speaker を逆引きして metadata.speakers を補完するポストプロセスを publisher に実装すべきか
- [ ] **Whisper ループ検出フィルタ**: 同一トークンが N 回以上連続するセグメントを自動検出・スキップする前処理を audio/extractor.py または transcriber.py に追加するか
- [ ] **答弁者名の正規化**: structurer が出力する answer.speaker の表記揺れ（「城内」vs「城内大臣」vs「城内実」）を、既知の閣僚名簿との照合で正規化するポストプロセスを追加するか。または speaker_tagger プロンプトで「役職名を除いた氏名のみ」を返すよう統一指示するか

---

## 7. 品質監査結果 — 2026-05-09

`docs/QUALITY_AUDIT_FORMAT.md` のフォーマットに従い、6セッションをサンプル監査した結果を記録する。横断的問題（likely_systemic）を優先的に整理し、再生成パイプラインへの反映項目を特定する。

### 7.1 監査対象セッション

| session_id | 全体品質 | high件数 | 総件数 |
|--|--|--|--|
| `shugiin/2026/02/18/56074_本会議` | medium | 4 | 15 |
| `shugiin/2026/02/20/56075_本会議` | **low** | 4 | 13 |
| `shugiin/2026/02/20/56083_不明` | **low** | 5 | 14 |
| `shugiin/2026/04/24/56209_厚生労働委員会` | medium | 5 | 13 |
| `shugiin/2026/04/24/56211_内閣委員会` | medium | 5 | 16 |
| `sangiin/2026/04/20/8966_こども特別委員会` | **low** | 7 | 16 |

### 7.2 横断的問題（likely_systemic）— 再生成計画への反映必須

#### P-01: `answer.role` が全件空文字列
**確認セッション**: 56209（60件中60件）、56211（69件中68件）、sangiin 8966（53件中53件）  
**規模推定**: 全138セッション × 平均40ペア ≈ **5,500件以上**が空文字列の可能性  
**症状**: ダッシュボードの「大臣答弁/政府参考人答弁」フィルタ、役職バッジ表示、約束トラッカーの役職付与がすべて機能しない  
**根本原因**: structurer のプロンプトが `answer.role` の生成を指示していないか、LLM が一貫して省略している  
**対策**: 新プロンプトで `answer.role` を `utterance.role` から機械的に引き継ぐか、明示的に「答弁者の役職を役割コード（大臣 / 副大臣 / 政府参考人 / 委員長 / etc.）として必ず記入すること」と指示する

#### P-02: 全政府答弁者が `metadata.speakers` に未登録
**確認セッション**: 56209（15名以上不在）、56211（8名以上不在）、sangiin 8966（16名全員不在）、56074（小寺博夫不在）  
**規模推定**: 全セッションに影響。各セッションの答弁側出席者（大臣・副大臣・政府参考人）が一切 speakers に入っていない  
**症状**: 話者フィルタで答弁者が検索不能、発言者ネットワークグラフに政府側が現れない、BYOK 分析での答弁者 lookup 失敗  
**根本原因**: ShugiinScraper / SangiinScraper が衆参TV の発言者リストから質疑者のみを取得し、政府側出席者を収集していない  
**対策**: structurer が生成した qa_pairs の answer.speaker を逆引きして metadata.speakers を補完するポストプロセスを publisher に追加する（§6 参照）

#### P-03: `metrics` が null のペアが散在
**確認セッション**: 56209（8件 / 60件 = 13.3%）、56211（17件 / 69件 = 24.6%）、sangiin 8966（9件 / 53件 = 17.0%）  
**規模推定**: 全セッションで平均15〜25%のペアがnull  
**症状**: ダッシュボードの「質問の鋭さ」「答弁の直接性」チャートで該当ペアが除外またはNaN扱い  
**根本原因**: `score_qa_pairs_metrics` のバッチ処理で API タイムアウト・コンテキスト超過が発生した際にフォールバックとして null が書き込まれている  
**対策**: publisher に「metrics=null のペアを再スコアリングして再試行するリカバリロジック」を実装する。または再生成後にまとめて metrics を別バッチで補完するスクリプトを用意する

#### P-04: Whisper ハルシネーションループ（セッション冒頭・放送終了後）
**確認セッション**:
- 56075_本会議: 委員長名連続読み上げで **48,754文字** のループ（「小寺博君」6,916回）
- 56211_内閣委員会: 開会宣言で **485文字** のループ（「山下貴司（内閣委員会。」繰り返し）
- 56211_内閣委員会: 放送終了後に「ご視聴ありがとうございました。」が 2 セグメントに幻覚生成

**症状**: ループが発生した utterance は実質 garbage になり、対応 qa_pairs の question/answer.full_text が汚染される。放送終了後幻覚では実際の質疑発言が 2 名（高山聡史・中村はやと）のセグメントで消失  
**根本原因**: Whisper large-v3-turbo の繰り返しパターン脆弱性。短い同音パターン高密度音声（委員長名連続読み上げ）と放送終了後の無音・エンドカード音声が特に危険  
**対策**:
1. `transcriber.py` に **ループ検出フィルタ** を実装：同一トークン/フレーズが N 回（例: 5回）以上連続した whisper_segment を検出し、警告ログを出して該当セグメントをスキップまたはフラグ付けする
2. HLS 収録範囲の末尾を放送終了前に切り詰める（放送後の無音区間を ffmpeg で除去）

#### P-05: 本会議における役職ラベル誤り（議長→委員長）
**確認セッション**: 56074_本会議（森英介のrole='委員長'）、56075_本会議（森英介のrole='委員長' 全セグメント）  
**症状**: 本会議の議長が「委員長」として表示・分類される。本会議の委員会フィルタが誤動作する  
**根本原因**: speaker_tagger のプロンプトが本会議と委員会の役職語彙を区別していない。「セッションの主宰者 = 委員長」というデフォルト分類が本会議でも適用されている  
**対策**: speaker_tagger に **セッション種別コンテキスト**（`session_type: "本会議" | "委員会"`）を入力として渡し、本会議では「議長・副議長・事務総長」、委員会では「委員長・理事・政府参考人」の語彙を使い分けるよう指示する

#### P-06: 本会議施政方針演説での q&a 構造の誤適用
**確認セッション**: 56075_本会議（qa_025–032 の question.full_text が全て「城内実君。はい。」9文字）  
**症状**: 施政方針演説（質問者なし・複数大臣が連続演説）に通常の「質疑者/答弁者」フォームを適用しようとするため、question が演説者の呼称のみになる  
**根本原因**: structurer プロンプトが「本会議施政方針演説」という特殊モードを持たない  
**対策**: session_type が「施政方針演説」または「代表質問」と判定される場合、structurer を「演説者リスト」モードに切り替え、各演説者の発言を qa_pair ではなく `statement` 型エントリとして格納する。または question.full_text に「（施政方針演説・質問なし）」を設定する規約を明確にする

#### P-07: `summary.key_commitments` の qa_id 参照ずれ
**確認セッション**: 56074_本会議（森英介・石井啓一の就任挨拶が qa_001/qa_002 に誤参照）、56075_本会議（片山さつきのコミットメントが高市の qa_002 に誤参照）  
**症状**: 約束トラッカーから対応 qa_pair へのディープリンクが別人・別発言に飛ぶ  
**根本原因**: summary 生成時に対象 qa_pair が存在しない（content_missing と連動）か、LLM が最も近い qa_id を推測で割り当てる  
**対策**: `publisher.py` に qa_id 参照整合性チェックを追加。`key_commitments[n].qa_id` が `qa_pairs[*].id` に存在しない場合は警告ログを出力し `qa_id=null` に補正する

#### P-08: 答弁者名の表記ゆれ（同一人物が複数の名前で登録）
**確認セッション**: 56209（上野厚生労働大臣 / 上野厚労大臣 / 上野）、56211（城内 / 城内大臣）、sangiin 8966（斉藤 / 斎藤 / 斉藤支援局長 / 斎藤支援局長）  
**症状**: 答弁者別の集計・フィルタが分断する。同一官僚が 2〜3 の別エントリとして表示される  
**根本原因**: structurer LLM が Whisper テキスト内の「役職名付き呼称」と「氏名のみ」を文脈によって別々に採用する。正規化ステップが存在しない  
**対策**: structurer プロンプトで「answer.speaker は役職名を除いた**氏名のみ**を記入（例: 上野賢一郎、城内実）」と明示。または publisher に閣僚名簿との照合による名前正規化ステップを追加する

#### P-09: `metadata.duration` が空文字列
**確認セッション**: 56074、56083、56209、56075（全 shugiin 監査セッション）  
**症状**: セッションカードの収録時間表示が空欄、時間長でのソート・フィルタが機能しない  
**根本原因**: HLS extractor または scraper が duration の計算・書き込みをスキップしている  
**対策**: pipeline.py で最終 segment の `end_seconds` からセッション総時間を計算して `metadata.duration` に書き込む 1 行を追加する

### 7.3 セッション固有の重大問題（再生成後も注意が必要なケース）

#### 委員会名「不明」スクレイパー失敗（56083）
- `metadata.committee="不明"`, `committee_id=null`, `session_number=null` — スクレイパーが委員会名フィールドを抽出できなかった
- 衆議院TVの HTML 変更またはセレクタ不一致が原因の可能性。再生成前に ShugiinScraper の委員会名抽出ロジックを確認・修正すること
- 判明した実態: 衆議院憲法審査会（HLS URL の日時パターン `2026-0220-1010-18` から推定）

#### LLM モデル混在（sangiin 8966）
- `metadata.llm_model="google/gemma-4-31B-it"` — 仕様の DeepSeek V3.2 ではなく Gemma が使われている
- この 1 セッションで観測された品質劣化（answer.role 全件空、key_topics 5件欠落、qa_033 話者誤帰属）の主因である可能性が高い
- 再生成時に `DEEPINFRA_API_KEY` と `structurer.py` のモデル設定を確認し、全セッションで DeepSeek V3.2 が一貫して使われていることを検証すること

#### Whisper 数値誤認識（sangiin 8966）
- 令和6年 出生数「77万759人」→ 実際は約72万人（MHLW 暫定値との乖離約5万人）
- `qa_045.question.full_text` および utterances.json の両方に存在しており、qa_044 の回答切断（answer.full_text が「68人」で終わる）と連動している
- 数値の正確性が重要なセッション（統計・予算）では、Whisper 修正後テキストを LLM に再確認させるステップが必要

#### `start_time` と `start_seconds` の大幅乖離（56083）
- 平沢勝栄: `start_seconds=2562.3`, `start_time="12:23"` → HLS URL 基準の実際の時刻は約 10:52 で**約90分の乖離**
- `start_time` の計算基準が誤っており、タイムラインビューで発言時刻の大幅なずれが生じる
- 再生成時に `start_time` をセッション開始時刻（HLS URL から取得）+ `start_seconds` で正確に算出していることを確認する

### 7.4 監査の限界・ブラインドスポット

- 6セッションのサンプル（全生成済みセッションの約4%）。インデックス完全な定量集計は `jq` スクリプトによる全件横断集計で補完すること（`docs/QUALITY_AUDIT_FORMAT.md §集約方法` 参照）
- `raw_transcript.json` が 1MB を超えるセッションはファイル全件精査が困難であり、Whisper 誤認識の全数把握はできていない
- 実在閣僚名簿・議員名簿との照合が未実施のため、話者誤帰属・誤認識の一部は確信度 medium 止まり
- 監査結果の JSON ファイルは `docs/audit-results/` に格納予定（現時点ではディレクトリ未作成）
