# 05. Q&A 品質評価指標 ─ 「回避度」を置き換える 12 軸フレームワーク

[← 戻る](README.md)

> **本章のステータス**
> 旧「回避度」一指標の限界を実データ（衆議院 140 セッション・6,308 Q&A ペア）で確認し、それを置き換える **質問の質 5 軸 / 答弁の実質度 4 軸 / ペアの帰結 3 軸** からなる多軸評価体系を定義した。評価プロンプトは 4 イテレーション（V1〜V4）の試行を経て、本章末尾の **V4 プロンプト** で最終化済み（同一サンプル 15 ペアで V2/V3/V4 を比較し、AS-4 コミットメント Lv 判定の安定性・OC-1 議事録価値のキャリブレーションが V4 で改善されたことを確認）。
>
> **実装は未着手**。以下は実装合意のためのリファレンスドキュメント。

---

## 5.1 概要 ─ 新しい評価体系の全体像

```
┌─ 質問の質 (Question Quality, QQ) ─ 5 軸 ────────┐
│  QQ-1 論点明確度        Clarity                 │
│  QQ-2 一次ソース密度    Groundedness            │
│  QQ-3 新規性            Novelty   (Phase 5)     │
│  QQ-4 当事者性          Stakeholder salience    │
│  QQ-5 行動要求度        Actionability           │
└─────────────────────────────────────────────────┘
┌─ 答弁の実質度 (Answer Substantiveness, AS) ─ 4 軸┐
│  AS-1 直接回答度        Directness  ← 旧「回避度」反転 │
│  AS-2 具体情報量        Information density     │
│  AS-3 新答弁度          Beyond-precedent (Phase 5) │
│  AS-4 コミットメント強度 Commitment level (Lv0-4)│
└─────────────────────────────────────────────────┘
┌─ ペア／セッションの帰結 (Outcome, OC) ─ 3 軸 ───┐
│  OC-1 議事録価値        Record value            │
│  OC-2 追及深度          Probing depth (Phase 6) │
│  OC-3 引用可能性        Quotability             │
└─────────────────────────────────────────────────┘
```

各 Q&A ペアにこれら 12 軸（うち P0 で実装するのは 9 軸）を付与し、別途 `scoring_confidence` (`low|medium|high`) と `evaluation_note` / `issue_in_design`（ともに日本語の人間向けメモ）を併記する。**「総合スコア 1 つ」は出さない**。

### 旧スコアとの対応

| 旧 | 新 | 移行 |
|---|---|---|
| `evasion_score` (0〜1, 高いほど悪い) | `as1_directness` (0〜1, 高いほど良い) | 反転表示。値域は同じだが意味を逆方向に揃える |
| `has_commitment` (bool) | `as4_commitment.level` (0〜4) | 階層化。bool 一つでは「努める」と「○月までに公表」が同一視されていた |
| なし | QQ-1〜5（質問側評価） | 新規。質問の作り込みは答弁側と独立に評価する |
| なし | OC-1〜3（議事録価値） | 新規。「直接的≠価値が高い」「回避的≠価値が低い」を表現するための上位レイヤー |

---

## 5.2 なぜ「回避度」一指標では足りなかったか

実データを 50 ペアサンプリングして読み比べた結論:

1. **答弁側しか採点していない。** 質疑の良し悪しは質問の作り込みで半分以上決まる。直接性しか測らないと、「論点不明確で要点が散った質問に、官僚が無難に返した」ペアが低スコア（=「明確な回答」扱い）として埋もれる。
2. **「直接性」と「価値」が無関係なケースが多い。** 例えば「不適正取締りの端緒は何か」Q&A は旧 `evasion_score=0.10` だが、これは事務的な事実確認で議事録に残す価値はほぼゼロ。一方、`evasion_score=0.70` の「再審手続きの遅延理由を問う」答弁は、確かにはぐらかしているが、**そのはぐらかし自体が記録され次の追及の出発点になる**点で重要。直接性が低い＝価値が低い、ではない。
3. **「コミットメントの強度」が消えていた。** `has_commitment: bool` 一つでは「努めてまいります」（精神論）と「○月までに検討会を設置し公表する」（期限付き行動約束）が同じ「約束あり」として扱われる。後者こそ「ネクストアクションを答えざるを得ない問い」の成果物のはずだが、現行 UI では区別不能だった。
4. **「新規性／議事録価値」が完全に欠落していた。** 既存答弁の貼り付けで終わったのか、新解釈・新数字・立証責任の転換を引き出したのかが、スコアにも UI にも現れない。

> 旧「回避度」は「答弁が論点に直接触れたか」の局所判定としては概ね機能していた。だが、**質疑が国民・他議員・省庁にとって価値があったか**という上位判断には、ほとんど寄与していなかった。

---

## 5.3 設計原則

1. **正の方向で測る。** 「回避度」のような負の語ではなく「直接回答度」「具体性」「コミットメント強度」など正の語に揃える（高 = 良い）。
2. **質問と答弁は別軸で評価する。** 良い答弁が引き出せたかは、質問の作り込みと答弁者の姿勢の合成。1 つの数値に潰さない。
3. **「議事録価値」は別レイヤーに独立させる。** 個別 Q&A のスコアとは独立に、「将来引用される可能性」を測る上位指標を持つ。
4. **採点前にエビデンスを列挙させる。** LLM プロンプトでは、各スコアを決める前に該当する引用文や該当フラグを列挙させる構造（V2 で導入、V4 で確立）。「印象で甘めに付ける」ことを構造的に防ぐ。
5. **LLM 判定であることを常時明示。** 全指標バッジに「LLM 自動評価」ラベル。決定論的に算出される機械集計値（文長、数値含有数）とは別ラベルにする。
6. **党派色を出さない。** 指標セットは中立。特定政党の政策観に紐づく指標（マニフェスト連動度等）は本サイト本体ではなく **運用者向け内部ダッシュボード** に切り出す。

---

## 5.4 質問の質（QQ）

質問は **作り込みで決まる部分が大きい**。論点選定・質問設計に関わる一般的な観点を、LLM が判定可能な粒度に落とし込む。

### QQ-1 論点明確度 (Clarity) `0.0–1.0`

**定義**: 「何を確認したいのか／何を引き出したいのか」が一文で言えるか。

- 判定: LLM に質問 full_text からサブ質問のリストを抽出させ、件数に応じてスコアを下げる
  - 1 サブ質問 → 0.8〜1.0
  - 2 サブ質問 → 0.5〜0.7
  - 3 サブ質問以上 → 0.2〜0.4
  - 純粋な所信表明（疑問符なし）→ 0.0〜0.2
- 機械集計の併用: 文数・疑問符の数・接続詞の頻度を併記。

### QQ-2 具体性・一次ソース密度 (Groundedness) `0.0–1.0`

**定義**: 質問の前提が 1 次ソース（政府統計・法令・過去答弁・当事者団体データ）に立脚しているか。

- 判定: 質問 full_text 中の引用源を列挙させる（type: number / organization / law / date / past_answer / field_case / other）
  - 0 件 → 0.0〜0.2
  - 1〜2 件 → 0.2〜0.5
  - 3 件以上 → 0.5〜0.8
- 加点要素: 大きな数字を生活実感に翻訳する表現（年間総額を一人当たり月額・日額に分解する、馴染みのある単価と比較する等）を検出した場合に +0.1〜0.2。

### QQ-3 新規性 (Novelty) `0.0–1.0` ─ Phase 5

**定義**: 過去国会で同じ問いが既に立てられていないか。既出の場合は「前回答弁から状況が変わった点」「残った宿題」を起点にしているか。

- 判定: 過去会議録 RAG への類似検索で、最近接の既出 Q&A の類似度を取る。低類似度 → 高新規性。
- 完全な新規性判定は将来課題（国会会議録 API との連携が必要）。当面は **本サイト内で見える範囲の既出度** に限定し、その旨を明記する。

### QQ-4 当事者性 (Stakeholder salience) `0.0–1.0`

**定義**: 当事者の顔が浮かぶ質問か。制度・数字を語るだけでなく、その制度のもとで暮らしている人の状況が見えるか。

- 判定: LLM に当事者カテゴリを抽出させる
  - **concrete** (0.7〜1.0): 固有名詞付き（特定の人名、組織名、地名、訴訟名）。例「袴田事件の元被告」「○○市の産科診療所」「○○訴訟の原告」
  - **mid** (0.4〜0.6): 職業・状態・属性（「がん患者」「中小企業」「妊婦」「養蜂業者」）
  - **abstract** (0.1〜0.3): 「国民」「事業者」「皆様」のような最広義カテゴリ

> V2/V3 で concrete/mid 境界が不安定だったため、V4 では「**固有名詞があるか**」を明確な閾値として固めている。

### QQ-5 行動要求度 (Actionability) `0.0–1.0`

**定義**: 答弁者がネクストアクションまで答えざるを得ない設計になっているか。

- 判定軸（4 つの bool フラグ）:
  - `is_yes_no_form`: Yes/No 型の問いか（「検証し公表いただけますか」）
  - `has_deadline`: 期限が区切られているか（「○月までに」）
  - `presents_options`: 選択肢が提示されているか
  - `shifts_burden_of_proof`: 立証責任の転換を含むか（「その懸念に確からしい根拠はあるのか」）
- スコアは 4 つのフラグの合計に応じて段階的に上げる（0 件で 0.0、4 件で 1.0）。

### 質問 intent との連動

現行の `intent` フィールド（fact_check / policy_proposal / accountability / information_request / other）は維持。各 intent ごとに「期待される質の重心」が違う点を UI で明示する:

| intent | 重視軸 |
|---|---|
| fact_check | QQ-2 一次ソース／QQ-1 明確度 |
| policy_proposal | QQ-5 行動要求度／QQ-4 当事者性 |
| accountability | QQ-1 明確度／QQ-3 新規性 |
| information_request | QQ-2 一次ソース |

---

## 5.5 答弁の実質度（AS）

旧「回避度」の置き換え。直接性だけでなく、情報量・新規性・コミットメントの 4 軸で見る。

### AS-1 直接回答度 (Directness) `0.0–1.0` ← 旧「回避度」を反転

**定義**: 質問の主題に直接触れているか。

- 判定: LLM に 4 段階分類させる
  - `directly` (0.8〜1.0): 主題に直接答えている
  - `partially` (0.5〜0.7): 部分的に答えているが核心を外している
  - `tangentially` (0.2〜0.4): 関連はするが直接答えていない
  - `not_at_all` (0.0〜0.2): 完全に別話題に逃げている／答弁不在
- 既存スコアとの互換のため、概念的には `directness ≈ 1 - evasion_score`。ただし旧スコアと完全一致はせず、V4 プロンプトでの再評価が必要（実験で平均誤差 ±0.03、最大 ±0.50）。

### AS-2 具体情報量 (Information density) `0.0–1.0`

**定義**: 数値・固有名詞・期限・根拠が答弁内にどれだけ含まれているか。

- 判定: 答弁文中の具体物を type 別（number / proper_noun / deadline / evidence_citation）に列挙させ、件数連動でスコア
  - 0 件 → 0.0〜0.2
  - 1〜2 件 → 0.3〜0.5
  - 3〜4 件 → 0.5〜0.7
  - 5 件以上 → 0.7〜1.0
- 機械集計の併用: 全角数字・年月日・%・円・件・人 などの抽出件数 / 答弁文長で正規化した値も併記。

### AS-3 新答弁度 (Beyond-precedent) `0.0–1.0` ─ Phase 5

**定義**: 既存答弁の貼り付けで終わったか、新しい解釈・数字・方針を引き出したか。

- 判定: 過去会議録 RAG への類似検索で、答弁文と最近接過去答弁の類似度を取る。
- 高類似（=「定型答弁」）→ 低スコア。低類似 → 高スコア。
- 当面は本サイト内のセッション集合でのみ判定し、限界を明記。

### AS-4 コミットメント強度 (Commitment level) `0–4` 段階

**定義**: 答弁から引き出した約束がどの程度具体的か。

V4 で **判定パターンを文字列で残す** 設計に変更（`matched_pattern` フィールド）。Lv 判定の根拠を文字列で出力させることで、後からプロンプト調整時のデバッグが容易になる。

| Lv | 定義 | 該当パターン例 | trigger 例 |
|---|---|---|---|
| **0** | 約束なし。問題認識の表明や事実説明のみ。`matched_pattern: null` | 認識共有のみ | 「ご指摘のとおりであると考えております」（行動動詞なし） |
| **1** | 努力義務的（aspirational verb のみ） | "aspirational verb" | 「努めてまいります」「真摯に取り組んでまいります」「しっかり進めてまいります」 |
| **2** | 検討約束（"検討"／"議論" + 将来時制） | "kentou + future tense" | 「検討してまいります」「議論させていただきたい」 |
| **3** | 具体行動約束（**named mechanism + action verb beyond 検討**） | "concrete action verb" | 「検討会を設置いたします」「次回までに整理いたします」「公表いたします」「ガイドラインを策定いたします」 |
| **4** | 期限付き行動約束（Lv3 + 時間アンカー） | "concrete action + deadline" | 「○月までに」「今年度中に」「来年度予算で」「次期○○計画で」 |

> **V2/V3 で頻発した誤判定**: 「先生の問題意識のとおり」を Lv1 と取る、「外交的な働きかけを行っているところであります」（現在進行）を Lv1 と取る、「しっかり取り組んでまいります」を Lv3 と取る、等。V4 では **将来時制の行動動詞があるか**／**named mechanism があるか**／**期限明示があるか** の 3 段階チェックでこれらを矯正できることを実験で確認。

実装上の注意:
- 既存 `has_commitment: bool` を **置き換え**。`commitment_text` は `trigger_phrase` として維持し、Lv と pattern を併記。
- ダッシュボードの「約束事項数」は Lv 別に内訳表示する。
- Lv 3 以上のみを「フォローアップ対象」として抽出するための DB スキーマ拡張を別途検討（引き出した検討事項を横断的に追跡できる仕組み）。

---

## 5.6 ペア／セッションの帰結（OC）

個別 Q&A の Q 側・A 側スコアとは独立に、「**この質疑があとで参照される可能性が高いか**」という上位の指標を設ける。「議事録に事実・解釈・前進を残す」という質疑の核心的な役割に対応する。

### OC-1 議事録価値 (Record value) `0.0–1.0`

**定義**: この Q&A が将来、他議員・省庁・メディアに引用される可能性が高いか。

V4 で 4 つのアウトカムフラグ + 役職重みによる合成式に整理:

```
base = 0.25 × (true となったアウトカムフラグの数)
bonus = +0.15  if answerer_seniority ∈ {minister, vice_minister}
bonus = +0.10  if surfaces_government_uncertainty == true
score = clamp(base + bonus, 0, 1)
```

アウトカムフラグ:

| フラグ | 内容 |
|---|---|
| `pins_legal_interpretation` | 政府が、法案の曖昧表現（「標準的な費用」「適切な配慮」等）に対する解釈・運用方針を確定させたか |
| `fixes_official_number` | 政府が公的な数字を答弁で確定させたか |
| `goes_beyond_precedent` | 既存方針を超える答弁を引き出したか |
| `surfaces_government_uncertainty` ★ NEW V4 | 「立証責任の転換」型の問いに対して、政府が知見不足を答弁で認めたか（例: 「把握しておりません」） |

> **V4 の新フラグ `surfaces_government_uncertainty` の意義**: 「政府が確からしい根拠を持っていないことを認めた」答弁は、今後の議論で繰り返し引用される強力な議事録材料になる。実験では「再審手続き遅延」「情報保全隊」など、旧スコアでは「回避的」と切り捨てられていたが議事録価値が高い事例で正しく機能することを確認。

表示: 「議事録価値: 高（このセッションでも上位 10%）」のような **相対表現** を主にし、絶対値の数字を前面に出さない。

### OC-2 追及深度 (Probing depth) `0.0–1.0` ─ Phase 6

**定義**: follow-up 質問が連鎖し、最初の答弁から踏み込んだ回答に至ったか。

- 判定: 既存 `follow_up_ids` を活用。チェーン長と、チェーン内での AS-1（直接回答度）・AS-4（コミットメント強度）の最大値の伸び幅を計測。
- 「最初の答弁では Lv1 努力義務だったが、追及で Lv3 行動約束まで引き上げた」ようなケースに高スコア。
- 答弁パターンを想定したうえで再質問の方向を見立てる「展開予測型」の質疑設計を評価する軸。

### OC-3 引用可能性 (Quotability) `0.0–1.0`

**定義**: メディア・他議員にとって切り取りやすい一文を含んでいるか。

- 機械集計: 答弁・質問の中から、長さが適度で（30〜80 字）、固有名詞・数字を含み、語尾が断定的な文を抽出。
- LLM 判定: 「この Q&A から 1 文を引用するなら、最も力のある一文はどれか」を抽出させる。
- 表示: 抽出された候補文をハイライトし、コピーボタンを置く（10 章「将来機能」と連動）。

### Outcome 指標の使いどころ

- セッション詳細ページに「**このセッションの注目 Q&A**」セクションを置き、OC-1 上位 3 件を表示。
- ダッシュボードの「ヒートマップ」を、平均回避度ではなく **議事録価値の総和 / セッション** に置き換える。
- 「コミットメント追跡」ページは Lv3 以上のみを母集団として、約束 → 実行のフォローアップ追跡に使う。

---

## 5.7 補助フィールド（V4 で追加）

各 Q&A ペアの評価結果には、12 軸スコアの他に以下の補助フィールドを併記する:

| フィールド | 型 | 用途 |
|---|---|---|
| `scoring_confidence` | `low \| medium \| high` | LLM 自身が判定した評価の自信度。`low` は人間レビュー対象として自動抽出 |
| `evaluation_note` | str (日本語、1〜2 文) | 各ペアの総合評価メモ。UI の tooltip や methodology ページの「なぜこの評価か」表示にそのまま流用可能 |
| `would_be_referenced` | `low \| medium \| high` | OC-1 の人間可読サマリ |
| `issue_in_design` | str (日本語、1 文) または null | 質問設計上の改善点。**議員自身の質問レビュー支援機能** として運用者向け内部 UI に転用可能 |

### `issue_in_design` の活用

実験で得られた具体例:
- 「質問の核心 Yes/No が後半に埋もれた」（蜜源植物事案）
- 「『大臣のお考えを』という抽象形式のため具体約束を引き出しにくい設計」（農業セーフティネット事案）
- 「『今回の法案を超えて』と抽象的に求めたため、答弁が既存施策の再説明に逃げる余地」（中小企業支援事案）

→ 当初想定の「公開サイト向け指標」を超えて、**内部の質問改善ループ** にも使える副産物。Tier 1 BYOK ユーザー向けに、質問テキストを貼ると `issue_in_design` を返す機能として展開可能。

---

## 5.8 UI への落とし込み

### 5.8.1 Q&A カード（改善後イメージ・詳細表示）

```
─────────────────────────────────────────────────────────
🏷  topic: 高額療養費制度の見直し           [intent: policy_proposal]
─────────────────────────────────────────────────────────
❓ 質問 ─ ○○議員（××会派）
   ├ 論点明確度    ●●●●○  明確（一論点）
   ├ 一次ソース密度 ●●●●●  数値・団体データを引用
   ├ 当事者性      ●●●●○  特定の患者団体に紐づく
   └ 行動要求度    ●●●○○  Yes/No 型 + 立証責任の転換

💬 答弁 ─ ○○大臣
   ├ 直接回答度    ●●●○○  概ね直接（一部一般論）
   ├ 具体情報量    ●●○○○  数値の引用なし
   └ コミットメント Lv3 行動約束「検討会で論点整理を行う」

📌 議事録価値: 高（このセッション上位 10%）  ⓘ LLM 自動評価
🔗 引用候補: （答弁中の最も力のある一文を自動抽出）
─────────────────────────────────────────────────────────
```

### 5.8.2 Q&A カード（最小表示・デフォルト）

```
❓ 質問: ○○議員（××会派）  [policy_proposal]
   論点明確度 ●●●●○ ／ 行動要求度 ●●●○○

💬 答弁: ○○大臣
   直接回答度 ●●●○○ ／ コミットメント Lv3 行動約束

📌 議事録価値: 高    ⓘ LLM 自動評価
[ 詳細を表示 ▾ ]
```

- バッジは **5 段階の○●表示** に統一（数値の前面化を避ける）。
- ⓘ アイコンを各バッジに付与し、tooltip で定義と算出方法のリンクを表示。
- 色は青系のグラデーション 1 系統に揃える（赤・橙・緑の信号配色を撤去）。
- `scoring_confidence == low` のペアには ⚠️ マーカーを併記し、tooltip で「この評価は AI 自身が低い自信度を示しています」と表示。

### 5.8.3 ダッシュボード

| 旧表示 | 新表示 |
|---|---|
| 平均回避度 0.32 | 平均直接回答度 0.68 / 平均コミットメント Lv 1.4 |
| スタックバー（明確/含み/回避的） | スタックバー（Lv0〜Lv4 のコミットメント分布） |
| 発言者ランキング: 平均回避度 | 発言者ランキング: コミットメント Lv 平均 + 95%CI（n<10 除外） |
| ヒートマップ: 平均回避度 / 委員会 | ヒートマップ: 議事録価値総和 / 委員会 |

### 5.8.4 既存懸念事項の継承

旧版 5.4「サンプルサイズ」、5.5「コンテキスト併記」、5.6「閾値の UI 露出」、5.7「コミットメント基準」は新指標体系でも引き続き必要:

1. **しきい値**: `n < 10` 除外、`n < 30` 低彩度 + n 値併記、95%CI バー併記。
2. **コンテキスト併記**: カードに「同答弁者の AS 平均」「同法案関連の Q&A 平均」を併記。
3. **閾値のバージョニング**: 集計時に閾値・モデル ID・プロンプトバージョン (V4 など) を出力に焼き込む。
4. **委員長除外・大臣別集計**: 集計対象の絞り込みフィルタを UI に置く。

---

## 5.9 方法論ページ（必須・新設）

`/about/methodology` ページを新設し、最低限以下を載せる:

1. **指標カタログ**: QQ-1〜5 / AS-1〜4 / OC-1〜3 の各定義、5 段階の例文、評価プロンプト全文（5.13 参照）。
2. **算出パイプライン**: Whisper → 話者タグ → Q&A 抽出 → 各指標判定の流れ。各段階の精度限界。
3. **既知の限界**:
   - LLM 判定の再現性（同一答弁を別モデル・別プロンプトで再評価したときのブレ。実験では V2/V3/V4 間で AS-4 Lv が 4/15 件変動）
   - 過去会議録 RAG が本サイトのインデックス範囲に限定される（QQ-3、AS-3 の限界）
   - 1 質問 1 答弁前提の崩壊ケース（リレー答弁、ヤジ込みの議論）
4. **モデル・プロンプトのバージョニング**:
   - `metadata.json` に `score_schema_version: "2.0"` と `prompt_version: "V4"` を入れ、過去データとの混在を防ぐ
   - 旧スコアは `evasion_score_v1` として併存させ、移行期間中は両方表示
5. **訂正・問い合わせ窓口**: 名誉毀損リスク対応として、対象議員・省庁からの訂正依頼を受ける明示的な窓口を置く。

---

## 5.10 法的・倫理的観点

多軸化しても本質は変わらない。**LLM 自動評価値を「事実」として表示することのリスク**は残る。むしろ指標が増えた分、誤判定の射程も広がる。

- **すべての指標バッジに「LLM 自動評価」ラベルを常時表示**（ダッシュボード上部の常時注記、各バッジの ⓘ tooltip、カード末尾のフッター）。
- **`scoring_confidence == low` の自動フィルタリング**: 低信頼度の評価は集計対象から除外、または ⚠️ で目立たせる。
- **断定語を避ける**: 「○○大臣のコミットメント Lv 平均が低い」ではなく「本サイト収録範囲では Lv 平均が低い傾向」と表現。
- **メディア引用ガイドライン** を `/about/methodology` 内に置く（数値の引用は必ず指標バージョン・モデル ID・対象期間を併記してほしい旨）。
- **個別議員への低評価の集計表示は控える**: ダッシュボードの発言者ランキングは「上位」のみ表示し、ワーストランキングは出さない。

---

## 5.11 段階的移行計画

V4 プロンプトが確定しているため、以下の順序で実装する:

| Phase | 内容 | 既存資産との関係 |
|---|---|---|
| **P0** | UI のラベル文言・色の中立化のみ。「回避度」→「直接回答度」（反転表示）。`/about/methodology` の最低限版を公開 | 既存 `evasion_score` をそのまま使用、表示だけ反転 |
| **P1** | V4 プロンプトを `structurer.py` に組み込み、新スキーマ（QQ/AS/OC 9 軸 + 補助フィールド）でデータ再生成。`metadata.json` に `score_schema_version: "2.0"` と `prompt_version: "V4"` を記録 | 全 6,308 ペアを再評価。コスト概算 約 $5.8（DeepSeek V3.2、V4 プロンプト 3,035 tok/ペア × $0.27/$0.40 per Mtok） |
| **P2** | Q&A カード UI を新指標対応に切替。最小表示／詳細表示の 2 モード。`scoring_confidence` の ⚠️ 表示 | フロント実装。データは P1 で揃っている |
| **P3** | ダッシュボードの主指標を新スキーマに切替（コミットメント Lv 分布、議事録価値ヒートマップ等） | フロント実装 |
| **P4** | 機械集計版の AS-2 補助値・QQ-1 機械集計値を追加（LLM 判定との整合チェック） | LLM 不要、決定論的に算出可能 |
| **P5** | QQ-3 / AS-3（新規性・新答弁度）の RAG ベース判定 | 過去会議録インデックスの整備が前提 |
| **P6** | OC-2（追及深度）の follow-up チェーン分析、コミットメント追跡 DB | Phase 5（ダッシュボード）と統合 |

### 再現性測定（P1 着手前に実施）

V4 プロンプトの再現性は未測定。実装着手前に **同一ペアを N=5 回投げて分散を測る** ベンチマークを実施し、以下を確認すべき:

- AS-4 Lv の判定一貫性（多数決にすべきか、temperature を変えるべきか）
- OC-1 フラグ（特に `surfaces_government_uncertainty`）の安定性
- QQ-4 concreteness 境界の安定性

> 実験フェーズの記録: V2（日本語プロンプト）→ V3（英語プロンプト・ペルソナなし）→ V4（V3 + Lv 弁別ルール強化 + 新フラグ + 信頼度フィールド）。15 ペアでの比較で V4 が最も安定し、AS-4 Lv 誤判定は V2/V3 比で改善。詳細は `/tmp/qa_experiment/` の実験ログ参照（commit 対象外）。

---

## 5.12 オープン論点（要 TF 議論）

1. **「総合スコア」を出すか、出さないか。** ユーザビリティ的には 1 個の数字で並べたいが、それこそが「回避度問題」の再来を招く。**出さない** を推奨するが、ランキング機能とのトレードオフがある。
2. **党固有指標の扱い。** 「マニフェスト連動度」のような特定政党の政策観に紐づく指標を、運用者向けの付帯指標として出すか、本サイトとは完全に分離するか。本サイトは党派色を出さない方針なので、**運用者向けの内部ダッシュボードに切り出す** を推奨。
3. **「いまいちな質問」を可視化するか。** 質問品質レベルの低位（前提誤り／根拠不明）を露出させると名誉毀損リスクが上がる。**レベル表示は議員別ではなく Q&A 単体に閉じる** を推奨。
4. **答弁者の役職重みづけ。** OC-1 で大臣・副大臣に +0.15 のボーナスを入れているが、政府参考人の事実答弁にも価値があるケースは多い。役職重みのキャリブレーションは P1 後の実データで再調整。
5. **既存の「回避度」スコアの扱い。** 後方互換のため `evasion_score_v1` として残すか、完全置換するか。研究目的の引用が始まっている場合は前者。
6. **`issue_in_design` の公開範囲。** 公開サイトに出すか、運用者ダッシュボードのみか。質問者個人への評価とも取られかねないため、**運用者向け限定** を推奨。

---

## 5.13 評価プロンプト（V4 ─ 最終版）

DeepInfra DeepSeek V3.2 用、temperature 0、`response_format: json_object`。1 ペアあたり約 3,035 tokens（prompt 2,282 + completion 753）、概算 $0.000917 / ペア。

### システムプロンプト（V4）

````text
This task evaluates one question-and-answer pair from a Japanese Diet
(national parliament) committee. Q&A text is in Japanese; reason in English
and output JSON only.

# Context
- "Question" = a Diet member questioning the government.
- "Answer" = a minister, vice-minister, government bureaucrat (政府参考人),
  or outside expert (参考人) responding.
- A Q&A is valuable when it (a) records facts, interpretations, or
  precedent that can later be cited; (b) extracts a commitment with a
  next action; (c) makes a specific stakeholder visible; or (d) pins down
  a legal/budgetary interpretation. Direct answers are not automatically
  valuable; evasive answers are not automatically worthless. Score on
  substance, not on tone or partisanship.

# Scoring discipline
1. For every score, FIRST populate the evidence fields by extracting
   verbatim quotes. THEN choose the score consistent with what you listed.
2. If an evidence list is empty, the score MUST sit in the bottom band.
3. Do NOT round up on overall impression.
4. Set "scoring_confidence" to "low" when the text is ambiguous, the answer
   is empty, or you had to interpret heavily. This is used by the system
   to flag uncertain pairs for human review.

# Discriminating rules (read carefully — V3 was unstable on these)

## QQ-1 clarity
List sub-asks separately. ONE sub-ask = score 0.8-1.0. TWO sub-asks =
0.5-0.7. THREE+ = 0.2-0.4. A "follow-up clarification within the same
ask" (e.g. "and why?") does not count as a separate sub-ask. Pure
opinion-statements with no question mark = 0.0-0.2.

## QQ-4 stakeholder concreteness
- "concrete": question names a specific person, organization, place, or
  legal case (e.g. "袴田事件の元被告", "○○市の産科診療所", "養蜂業者○○団体").
  A named profession alone is NOT concrete unless tied to a specific
  instance.
- "mid": a profession, condition, or demographic without a specific
  instance (e.g. "がん患者", "中小企業", "妊婦", "養蜂業者").
- "abstract": "国民", "事業者", "国民全体", "皆様".

## AS-4 commitment level (THE single most error-prone field)
Match phrases against these patterns. Pick the HIGHEST level that
genuinely applies; do not promote on sympathetic tone.
- Lv0: no commitment phrase. Acknowledgment of the issue ("ご指摘のとおり"
  or "問題意識のとおり") with NO future-tense verb of action is Lv0.
- Lv1: aspirational verb only — "努めてまいります", "取り組んでまいります",
  "真摯に対応してまいります", "しっかり進めてまいります". No specific
  mechanism named.
- Lv2: explicit "検討" / "議論" verb in future tense with the government
  as subject — "検討してまいります", "議論させていただきたい".
- Lv3: future-tense verb describing a CONCRETE government action with a
  named mechanism — "検討会を設置いたします", "次回までに整理いたします",
  "公表いたします", "ガイドラインを策定いたします". Must have both a
  named action object AND an action verb beyond "検討".
- Lv4: Lv3 + an explicit time anchor — "○月までに", "今年度中に",
  "来年度予算で", "次期○○計画で".

## OC-1 record value (V3 was systematically too low)
Compute as base + bonus, then clamp to [0,1].
- base = 0.25 * (number of true outcome flags below)
- bonus = +0.15 if answerer_seniority is minister or vice_minister
- bonus = +0.10 if answer admits government uncertainty / lack of
  evidence (e.g. "把握しておりません" in response to a "立証責任転換"-style
  question — this creates a citable record even though the answer is
  evasive)
Outcome flags:
  pins_legal_interpretation, fixes_official_number, goes_beyond_precedent,
  surfaces_government_uncertainty (NEW in V4)

# Output JSON schema (use these exact keys; output JSON ONLY)

{
  "qq1_clarity": {
    "main_question_one_liner": "<=25 Japanese chars summarising the core ask",
    "sub_asks": ["each distinct sub-ask as a short Japanese phrase; [] if just one"],
    "score": 0.0-1.0
  },
  "qq2_groundedness": {
    "cited_sources": [
      {"type": "number"|"organization"|"law"|"date"|"past_answer"|"field_case"|"other",
       "excerpt": "short verbatim quote from the question"}
    ],
    "translates_big_number_to_daily_life": true|false,
    "score": 0.0-1.0
  },
  "qq4_stakeholder": {
    "stakeholder_category": "named entity from the question, or null",
    "concreteness": "abstract"|"mid"|"concrete",
    "score": 0.0-1.0
  },
  "qq5_actionability": {
    "is_yes_no_form": true|false,
    "has_deadline": true|false,
    "presents_options": true|false,
    "shifts_burden_of_proof": true|false,
    "score": 0.0-1.0
  },
  "as1_directness": {
    "addresses_main_question": "directly"|"partially"|"tangentially"|"not_at_all",
    "topic_shift_detected": true|false,
    "score": 0.0-1.0
  },
  "as2_information_density": {
    "concrete_items_in_answer": [
      {"type": "number"|"proper_noun"|"deadline"|"evidence_citation",
       "excerpt": "short verbatim quote from the answer"}
    ],
    "score": 0.0-1.0
  },
  "as4_commitment": {
    "level": 0|1|2|3|4,
    "trigger_phrase": "verbatim quote justifying the level, or null if Lv0",
    "matched_pattern": "which V4 rule pattern matched (e.g. 'aspirational verb', 'kentou + future tense', etc.), or null"
  },
  "oc1_record_value": {
    "pins_legal_interpretation": true|false,
    "fixes_official_number": true|false,
    "goes_beyond_precedent": true|false,
    "surfaces_government_uncertainty": true|false,
    "answerer_seniority": "minister"|"vice_minister"|"bureaucrat"|"reference"|"other",
    "score": 0.0-1.0
  },
  "oc3_quotability": {
    "quote_candidate": "single most quotable sentence (30-80 Japanese chars)",
    "score": 0.0-1.0
  },
  "scoring_confidence": "low"|"medium"|"high",
  "evaluation_note": "1-2 sentences in Japanese summarising the verdict",
  "would_be_referenced": "high"|"medium"|"low",
  "issue_in_design": "one sentence in Japanese on a fixable design weakness in the question, or null"
}
````

### ユーザーメッセージ形式

````text
intent: {intent}

=== QUESTION (Japanese) ===
{質問 full_text}

=== ANSWER (Japanese) ===
{答弁 full_text}
````

### 設計上の決定事項

- **言語**: システムプロンプトは英語、出力の人間向けフィールド（`evaluation_note`、`issue_in_design`、`main_question_one_liner`、`quote_candidate`）は日本語。実験で英語プロンプトはトークン削減効果が小さい（Q&A 本文の日本語が支配的）が、保守性・他モデル移植性で英語に統一。
- **ペルソナなし**: 「あなたは...の専門家です」型の前置きは入れない（ペルソナ指示は最近の研究で効果が限定的とされる）。代わりに `Context` セクションで評価対象の事実を直接記述。
- **エビデンス先列挙**: スコアを決める前に `cited_sources[]` `concrete_items_in_answer[]` などのリストを埋めさせる構造（V2 で導入、V4 で確立）。「印象でやや高め」を構造的に防ぐ。
- **`matched_pattern` の文字列化**: AS-4 Lv 判定の根拠を文字列で残すことで、誤判定検出と再調整が容易。
- **`scoring_confidence` の自己申告**: LLM 自身が低い自信度を示したペアを人間レビュー対象に自動回送できる。

---

[← 戻る](README.md) ｜ [次の章: 06-filtering-search.md →](06-filtering-search.md)
