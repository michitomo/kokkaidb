#!/usr/bin/env python3
"""コミットメント検出プロンプト ベンチマーク

commitments_benchmark.json の24ケースに対し、複数のプロンプトバリアントを実行して
精度（Precision / Recall / F1）を比較する。

使い方:
    cd kokkai-transcriber
    source .venv/bin/activate
    python benchmark_commitments.py            # 全バリアントを実行
    python benchmark_commitments.py --variant v1 v2   # 特定バリアントのみ
    python benchmark_commitments.py --dry-run  # LLM呼び出しなし・現状スコアのみ表示
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import openai

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
MODEL = "google/gemma-4-31B-it"

BENCHMARK_PATH = Path(__file__).parent.parent / "kokkai-transcriber/tests/fixtures/commitments_benchmark.json"
# benchmarkはこのスクリプトと同じリポジトリ内にある
BENCHMARK_PATH_ALT = Path(__file__).parent / "tests/fixtures/commitments_benchmark.json"


# ---------------------------------------------------------------------------
# プロンプトバリアント定義
# ---------------------------------------------------------------------------

# V1: 現行プロンプト（定義なし）
PROMPT_V1 = """\
あなたは国会質疑のコミットメント（約束）を判定する専門家です。

以下の国会質疑の答弁テキストを分析し、答弁者がコミットメントを行っているかどうかを判定してください。

以下のJSON形式で出力してください:
{
  "has_commitment": true | false,
  "commitment_text": "具体的な約束事項（has_commitmentがtrueの場合）",
  "reasoning": "判定理由（1-2文）"
}

has_commitment の目安:
- true: 答弁者が具体的な約束・コミットメントをした
- false: 具体的な約束がなかった
"""

# V2: コミットメント定義を追加
PROMPT_V2 = """\
あなたは国会質疑のコミットメント（約束）を判定する専門家です。

以下の国会質疑の答弁テキストを分析し、答弁者がコミットメントを行っているかどうかを判定してください。

## has_commitment の判定基準（厳密に適用すること）

**True（コミットメントあり）**とするのは、答弁者が以下のいずれかを明言した場合のみ:
1. 法案提出・閣議決定等の政府公式行動（「〇〇法案を提出する」「閣議決定する」等）
2. 具体的な数値目標（金額・比率・件数等を伴うもの）
3. 具体的な期限（「今国会」「今年中」「令和〇年度」「〇月までに」等）
4. 制度創設・廃止・改正の確約（「〇〇制度を新設する」「〇〇を廃止する」等）
5. 答弁者自身が直接実行する具体的アクション

**False（コミットメントなし）**とする典型パターン:
- 「〜に取り組む」「〜を推進する」「〜に努める」等の一般的努力表明
- 「〜を検討する」「〜を協議する」等の未確定プロセス表明
- 「〜したい」「〜するつもり」「〜してまいりたい」等の意向・希望
- 議事進行の結果（委員長指名・採決・選任等）
- 現状説明・既存施策の継続（新規性のないもの）
- 回避的な答弁（質問をはぐらかしている場合）

以下のJSON形式で出力してください:
{
  "has_commitment": true | false,
  "commitment_text": "コミットメントの内容（has_commitmentがtrueの場合のみ。具体的な行動・数値・期限を含めること）",
  "reasoning": "判定理由（1-2文）"
}
"""

# V3: V2 + few-shot examples（TP2件・FP2件）
PROMPT_V3 = """\
あなたは国会質疑のコミットメント（約束）を判定する専門家です。

以下の国会質疑の答弁テキストを分析し、答弁者がコミットメントを行っているかどうかを判定してください。

## has_commitment の判定基準（厳密に適用すること）

**True（コミットメントあり）**とするのは、答弁者が以下のいずれかを明言した場合のみ:
1. 法案提出・閣議決定等の政府公式行動（「〇〇法案を提出する」「閣議決定する」等）
2. 具体的な数値目標（金額・比率・件数等を伴うもの）
3. 具体的な期限（「今国会」「今年中」「令和〇年度」「〇月までに」等）
4. 制度創設・廃止・改正の確約（「〇〇制度を新設する」「〇〇を廃止する」等）
5. 答弁者自身が直接実行する具体的アクション

**False（コミットメントなし）**とする典型パターン:
- 「〜に取り組む」「〜を推進する」「〜に努める」等の一般的努力表明
- 「〜を検討する」「〜を協議する」等の未確定プロセス表明
- 「〜したい」「〜するつもり」「〜してまいりたい」等の意向・希望形
- 議事進行の結果（委員長指名・採決・選任等）
- 現状説明・既存施策の継続（新規性のないもの）
- 回避的な答弁（質問をはぐらかしている場合）

## 判定例

**例1（True）**
答弁: 「令和7年度からの5年間の農業構造転換集中対策期間において別枠予算を確保し、農地の大区画化や農業の構造転換への集中投資を実施し、生産性の抜本的な向上に努めてまいります。」
→ has_commitment: true（期間5年＋別枠予算確保＋集中投資実施という具体的アクション）

**例2（True）**
答弁: 「令和7年度は224億円の内示を行っており、令和7年度ではそれを100%使い切る形となっております。」
→ has_commitment: true（具体的な金額224億円＋100%執行という数値目標）

**例3（False）**
答弁: 「日米同盟の抑止力、対処力を一層強化してまいります。同時に、幅広い分野での日米協力を拡大してまいります。また、普天間飛行場の一日も早い全面返還を目指して辺野古移設を進めるなど取り組んでいきます。」
→ has_commitment: false（「強化してまいります」「拡大してまいります」「取り組んでいきます」はすべて方針表明。具体的な数値・期限・法案なし）

**例4（False）**
答弁: 「ご異議なしと認めます。よって、同意のとおり決まりました。議長は各常任委員長を指名いたします。」
→ has_commitment: false（議事進行上の手続き。政策コミットメントではない）

以下のJSON形式で出力してください:
{
  "has_commitment": true | false,
  "commitment_text": "コミットメントの内容（has_commitmentがtrueの場合のみ。具体的な行動・数値・期限を含めること）",
  "reasoning": "判定理由（1-2文）"
}
"""

# V4: V3 + evasion整合性チェック + 「方向で検討」「するつもり」の明示的排除
PROMPT_V4 = """\
あなたは国会質疑のコミットメント（約束）を判定する専門家です。

以下の国会質疑の答弁テキストを分析し、答弁者がコミットメントを行っているかどうかを判定してください。

## has_commitment の判定基準（厳密に適用すること）

**True（コミットメントあり）**とするのは、答弁者が以下のいずれかを明言した場合のみ:
1. 法案提出・閣議決定等の政府公式行動（「〇〇法案を提出する」「閣議決定する」等）
2. 具体的な数値目標（金額・比率・件数等を伴うもの）
3. 具体的な期限（「今国会」「今年中」「令和〇年度」「〇月までに」等）
4. 制度創設・廃止・改正の確約（「〇〇制度を新設する」「〇〇を廃止する」等）
5. 答弁者自身が直接実行する具体的アクション

**False（コミットメントなし）**とする典型パターン（疑わしい場合はFalseとすること）:
- 「〜に取り組む」「〜を推進する」「〜に努める」「〜に尽力する」等の一般的努力表明
- 「〜を検討する」「〜を協議する」「〜の方向で検討」等の未確定プロセス表明
- 「〜したい」「〜するつもり」「〜してまいりたい」「〜と考えております」等の意向・希望形
- 「〜に万全を期す」「〜に全力を尽くす」等の曖昧なコミット表現
- 議事進行の結果（委員長指名・採決・選任等）
- 現状説明・既存施策の継続（新規性のないもの）
- 質問の核心を避けた回答（仮定の質問に答えない等）

**条件付きコミットメント**: 「〇〇が得られれば〜する」等の条件付きは、条件と成果物が明確な場合のみTrueとし、commitment_textに条件を明示すること。

## 判定例

**例1（True）**
答弁: 「令和7年度からの5年間の農業構造転換集中対策期間において別枠予算を確保し、農地の大区画化や農業の構造転換への集中投資を実施し、生産性の抜本的な向上に努めてまいります。」
→ has_commitment: true / commitment_text: 「令和7年度からの5年間、別枠予算を確保し農業構造転換への集中投資を実施する」

**例2（True）**
答弁: 「令和7年度は224億円の内示を行っており、令和7年度ではそれを100%使い切る形となっております。」
→ has_commitment: true / commitment_text: 「令和7年度に224億円を100%執行する」

**例3（False）**
答弁: 「日米同盟の抑止力、対処力を一層強化してまいります。同時に、幅広い分野での日米協力を拡大してまいります。また、普天間飛行場の一日も早い全面返還を目指して辺野古移設を進めるなど取り組んでいきます。」
→ has_commitment: false（「強化してまいります」等はすべて方針表明。具体的な数値・期限・法案なし）

**例4（False）**
答弁: 「引き続き、重要な技術の流出防止に向けまして、不断に取組の見直しや検討を行い、関係省庁と連携いたしまして、必要な取組を強化してまいりたいと考えております。」
→ has_commitment: false（「強化してまいりたい」は意向形。「検討」「見直し」は未確定プロセス。具体的な制度変更・期限なし）

**例5（True: 条件付き）**
答弁: 「野党の皆様の協力を得られれば、夏前には国民会議で中間取りまとめを行い、必要な法案の早期提出を目指します。」
→ has_commitment: true / commitment_text: 「野党の協力が得られれば夏前に中間取りまとめを行い法案を提出する（条件付き）」

以下のJSON形式で出力してください:
{
  "has_commitment": true | false,
  "commitment_text": "コミットメントの内容（has_commitmentがtrueの場合のみ。具体的な行動・数値・期限を含めること。Falseの場合は空文字列）",
  "reasoning": "判定理由（1-2文）"
}
"""

# V5: V3 + 主節述語テスト + 条件付きコミットメント明示
PROMPT_V5 = """\
あなたは国会質疑のコミットメント（約束）を判定する専門家です。

以下の国会質疑の答弁テキストを分析し、答弁者がコミットメントを行っているかどうかを判定してください。

## has_commitment の判定基準（厳密に適用すること）

**True（コミットメントあり）**とするのは、答弁者が以下のいずれかを明言した場合のみ:
1. 法案提出・閣議決定等の政府公式行動（「〇〇法案を提出する」「閣議決定する」等）
2. 具体的な数値目標（金額・比率・件数等を伴うもの）
3. 具体的な期限（「今国会」「今年中」「令和〇年度」「〇月までに」等）
4. 制度創設・廃止・改正の確約（「〇〇制度を新設する」「〇〇を廃止する」等）
5. 答弁者自身が直接実行する具体的アクション
6. **条件付きコミットメント**: 条件（A）・期限または成果物（B）がともに具体的に明示されている「AがあればBする」形式（commitment_textに条件を括弧書きで付記すること）

**False（コミットメントなし）**とする典型パターン:
- 「〜に取り組む」「〜を推進する」「〜に努める」等の一般的努力表明
- 「〜を検討する」「〜を協議する」等の未確定プロセス表明
- 「〜したい」「〜するつもり」「〜してまいりたい」等の意向・希望形
- 議事進行の結果（委員長指名・採決・選任等）
- 現状説明・既存施策の継続（新規性のないもの）
- 回避的な答弁（質問をはぐらかしている場合）
- **「〜するところです」「〜しているところ」「〜実施するところであります」**等の「するところ」表現は現在の対応状況の報告であり、将来の政策コミットメントではない

## 主節述語テスト（最重要ルール）

文中に具体的な日時・数値・行動が含まれていても、**文末の主節述語**（主たる結論）が意向・希望形（〜したい/〜まいりたい/〜つもり）の場合はFalseとすること。
従属節・背景説明の具体的要素に引きずられないこと。

## 判定例

**例1（True）**
答弁: 「令和7年度からの5年間の農業構造転換集中対策期間において別枠予算を確保し、農地の大区画化や農業の構造転換への集中投資を実施し、生産性の抜本的な向上に努めてまいります。」
→ has_commitment: true（「別枠予算を確保し、集中投資を実施」という具体的アクション＋5年という期間。主節は確定形）

**例2（True）**
答弁: 「令和7年度は224億円の内示を行っており、令和7年度ではそれを100%使い切る形となっております。」
→ has_commitment: true（具体的な金額224億円＋100%執行という数値目標）

**例3（True: 条件付き）**
答弁: 「国民会議に参加する野党の皆様の協力を得られれば、夏前には国民会議で中間取りまとめを行い、必要な法案の早期提出を目指します。」
→ has_commitment: true / commitment_text: 「野党の協力が得られれば夏前に中間取りまとめを行い法案を提出する（条件付き）」
（条件が明確、期限が具体的、成果物が明確→条件付きコミットメントとして扱う）

**例4（False）**
答弁: 「日米同盟の抑止力、対処力を一層強化してまいります。普天間飛行場の一日も早い全面返還を目指して辺野古移設を進めるなど取り組んでいきます。」
→ has_commitment: false（「強化してまいります」「取り組んでいきます」はすべて方針表明。具体的な数値・期限・法案なし）

**例5（False: 従属節に具体的要素あり・主節は希望形）**
答弁: 「早ければ今日にもリヤドから経由により東京までの輸送を実施するところであります。希望される方々が全員出国できるように、第二便等も含めて、準備に万全を期してまいりたいと考えております。」
→ has_commitment: false
（「実施するところ」=現在進行中の対応状況の報告。主節「準備に万全を期してまいりたい」は希望形。文中に具体的な今日・輸送という言及があっても、主節述語が意向形のためFalse）

**例6（False）**
答弁: 「ご異議なしと認めます。議長は各常任委員長を指名いたします。」
→ has_commitment: false（議事進行上の手続き。政策コミットメントではない）

以下のJSON形式で出力してください:
{
  "has_commitment": true | false,
  "commitment_text": "コミットメントの内容（has_commitmentがtrueの場合のみ。具体的な行動・数値・期限を含めること。Falseの場合は空文字列）",
  "reasoning": "判定理由（1-2文）"
}
"""

# V6: V5 + 主節述語を明示的に抽出させる構造化推論
PROMPT_V6 = """\
あなたは国会質疑のコミットメント（約束）を判定する専門家です。

以下の国会質疑の答弁テキストを分析し、答弁者がコミットメントを行っているかどうかを判定してください。

## has_commitment の判定基準（厳密に適用すること）

**True（コミットメントあり）**とするのは、答弁者が以下のいずれかを明言した場合のみ:
1. 法案提出・閣議決定等の政府公式行動（「〇〇法案を提出する」「閣議決定する」等）
2. 具体的な数値目標（金額・比率・件数等を伴うもの）
3. 具体的な期限（「今国会」「今年中」「令和〇年度」「〇月までに」等）
4. 制度創設・廃止・改正の確約（「〇〇制度を新設する」「〇〇を廃止する」等）
5. 答弁者自身が直接実行する具体的アクション
6. **条件付きコミットメント**: 条件・期限・成果物がともに具体的な「AがあればBする」形式

**False（コミットメントなし）**とする典型パターン:
- 「〜に取り組む」「〜を推進する」「〜に努める」等の一般的努力表明
- 「〜を検討する」「〜の方向で検討」等の未確定プロセス表明
- 「〜したい」「〜するつもり」「〜してまいりたい」等の意向・希望形
- 「〜するところ」「〜しているところ」等の現状対応報告
- 議事進行の結果（委員長指名・採決等）
- 回避的な答弁、現状説明・既存施策の継続

## 判定手順

まず以下を確認してから判定してください:
1. 答弁の**文末主節述語**を特定する（例:「〜します（確定）」「〜まいりたい（希望）」「〜検討する（プロセス）」）
2. 文中に具体的な数値・期限・制度変更・法案提出が含まれるか確認する
3. それらは**答弁者自身が将来実行する**内容か（現状報告・民間組織の話ではないか）確認する

以下のJSON形式で出力してください（main_clause_verbを必ず埋めること）:
{
  "main_clause_verb": "文末主節述語の抜き出しと形式判定（例: 「〜してまいります（確定形）」「〜まいりたい（希望形）」「〜検討中（プロセス形）」）",
  "has_commitment": true | false,
  "commitment_text": "コミットメントの内容（has_commitmentがtrueの場合のみ。Falseの場合は空文字列）",
  "reasoning": "判定理由（1-2文）"
}
"""

# V7: 判定フロー（デシジョンツリー）形式
PROMPT_V7 = """\
あなたは国会質疑のコミットメント（約束）を判定する専門家です。

以下の国会質疑の答弁テキストを、次の**判定フロー**に従って分析してください。

## 判定フロー（順番に確認する）

**ステップ1: 政策コミットメント対象か？**
- 議事進行の手続き（委員長指名・採決・選任等）→ **False**

**ステップ2: 具体的要素の有無**
以下のいずれかが答弁に含まれるか？
- 具体的な数値（金額・比率・件数等）
- 具体的な期限（「今国会」「今年中」「令和〇年度」「〇月まで」等）
- 制度創設・廃止・改正・法案提出の明言
- 条件付きだが条件・期限・成果物がすべて具体的な約束
→ 一つも含まれない場合は **False**

**ステップ3: 答弁者が将来実行するか？**
上記の要素が「答弁者自身の将来の行動」として述べられているか確認する。

以下の動詞形式で判断:
| 動詞パターン | 判定 |
|---|---|
| 「〜します」「〜することとしています」「〜を提出します」等（確定形） | → **True方向** |
| 「〜するところです」「〜しているところ」「〜実施するところ」（現状報告形） | → **False（現状説明）** |
| 「〜したい」「〜まいりたい」「〜するつもり」「〜したいと考えています」（意向形） | → **False（意向表明）** |
| 「〜の方向で検討」「〜を検討する」（未確定形） | → **False（プロセス）** |
| 「A があれば B する（B に具体的期限と成果物あり）」（条件付き確定形） | → **True（条件付き）** |

**ステップ4: 答弁者の立場**
政府・国会議員による政策コミットメントか？民間組織（農協、企業等）の担当者の内部手続きではないか？
→ 民間組織の内部手続き → **False**

## 判定例

**例1（True）**：「令和7年度からの5年間の農業構造転換集中対策期間において別枠予算を確保し、集中投資を実施します」
→ 具体期間5年＋別枠予算確保＋確定形「実施します」→ True

**例2（True: 条件付き）**：「野党の協力を得られれば、夏前には法案を提出します」
→ 条件(野党協力)＋具体期限(夏前)＋法案提出→ True（条件付き）

**例3（False）**：「希望される方々が全員出国できるように、輸送を実施するところであります。準備に万全を期してまいりたい」
→ 「するところ」=現状対応報告、「まいりたい」=意向形→ False

**例4（False）**：「強化してまいります。取り組んでいきます。辺野古移設を進めるなど取り組んでいきます」
→ 具体数値・期限なし、すべて方針表明→ False

以下のJSON形式で出力してください:
{
  "step_results": "ステップ1〜4の確認結果を1文ずつ（判定フローの追跡）",
  "has_commitment": true | false,
  "commitment_text": "コミットメントの内容（has_commitmentがtrueの場合のみ。Falseは空文字列）",
  "reasoning": "最終判定理由（1文）"
}
"""

PROMPT_VARIANTS: dict[str, str] = {
    "v1": PROMPT_V1,
    "v2": PROMPT_V2,
    "v3": PROMPT_V3,
    "v4": PROMPT_V4,
    "v5": PROMPT_V5,
    "v6": PROMPT_V6,
    "v7": PROMPT_V7,
}


# ---------------------------------------------------------------------------
# データ構造
# ---------------------------------------------------------------------------

@dataclass
class BenchCase:
    id: str
    category: str
    label: str
    topic: str
    question_summary: str
    answer_text: str
    ground_truth_has_commitment: bool
    ground_truth_commitment_text: str
    current_has_commitment: bool
    is_borderline: bool = False


@dataclass
class CaseResult:
    case_id: str
    category: str
    ground_truth: bool
    predicted: bool
    commitment_text: str
    reasoning: str
    correct: bool
    elapsed: float


@dataclass
class VariantScore:
    variant: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def tp(self) -> int:
        return sum(1 for r in self.results if r.ground_truth and r.predicted)

    @property
    def fp(self) -> int:
        return sum(1 for r in self.results if not r.ground_truth and r.predicted)

    @property
    def fn(self) -> int:
        return sum(1 for r in self.results if r.ground_truth and not r.predicted)

    @property
    def tn(self) -> int:
        return sum(1 for r in self.results if not r.ground_truth and not r.predicted)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def accuracy(self) -> float:
        correct = sum(1 for r in self.results if r.correct)
        return correct / len(self.results) if self.results else 0.0

    def category_breakdown(self) -> dict[str, dict]:
        cats: dict[str, list[CaseResult]] = {}
        for r in self.results:
            cats.setdefault(r.category, []).append(r)
        out = {}
        for cat, rs in sorted(cats.items()):
            correct = sum(1 for r in rs if r.correct)
            out[cat] = {"correct": correct, "total": len(rs), "pct": correct / len(rs) * 100}
        return out


# ---------------------------------------------------------------------------
# ベンチマーク読み込み
# ---------------------------------------------------------------------------

def load_benchmark() -> list[BenchCase]:
    path = BENCHMARK_PATH if BENCHMARK_PATH.exists() else BENCHMARK_PATH_ALT
    if not path.exists():
        raise FileNotFoundError(f"Benchmark not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for c in raw["cases"]:
        gt = c["ground_truth"]
        # borderlineのground_truthはpreferredフィールドで上書き
        gt_has = gt.get("preferred", gt["has_commitment"]) if c["category"] == "borderline" else gt["has_commitment"]
        cases.append(BenchCase(
            id=c["id"],
            category=c["category"],
            label=c["label"],
            topic=c["input"]["topic"],
            question_summary=c["input"]["question_summary"],
            answer_text=c["input"]["answer_text"],
            ground_truth_has_commitment=gt_has,
            ground_truth_commitment_text=gt.get("commitment_text", ""),
            current_has_commitment=c["current_output"]["has_commitment"],
            is_borderline=(c["category"] == "borderline"),
        ))
    return cases


# ---------------------------------------------------------------------------
# LLM 呼び出し
# ---------------------------------------------------------------------------

def call_llm(client: openai.OpenAI, system_prompt: str, case: BenchCase) -> tuple[bool, str, str, float]:
    """LLMを呼び出してhas_commitment, commitment_text, reasoning, elapsed を返す。"""
    user_msg = (
        f"トピック: {case.topic}\n\n"
        f"質問の要旨:\n{case.question_summary}\n\n"
        f"答弁テキスト:\n{case.answer_text}"
    )

    start = time.time()
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.0,
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        elapsed = time.time() - start
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
        has_commitment = bool(data.get("has_commitment", False))
        commitment_text = data.get("commitment_text", "") or ""
        reasoning = data.get("reasoning", "") or ""
        return has_commitment, commitment_text, reasoning, elapsed
    except Exception as e:
        elapsed = time.time() - start
        logger.error("LLM error for %s: %s", case.id, e)
        return False, "", f"ERROR: {e}", elapsed


# ---------------------------------------------------------------------------
# 現行スコア（LLMなし・current_output から計算）
# ---------------------------------------------------------------------------

def compute_current_score(cases: list[BenchCase]) -> VariantScore:
    score = VariantScore(variant="current (from benchmark data)")
    for c in cases:
        gt = c.ground_truth_has_commitment
        pred = c.current_has_commitment
        score.results.append(CaseResult(
            case_id=c.id,
            category=c.category,
            ground_truth=gt,
            predicted=pred,
            commitment_text="",
            reasoning="(from benchmark data)",
            correct=(gt == pred),
            elapsed=0.0,
        ))
    return score


# ---------------------------------------------------------------------------
# 出力フォーマット
# ---------------------------------------------------------------------------

def print_score(score: VariantScore, cases: list[BenchCase], verbose: bool = False) -> None:
    print(f"\n{'='*60}")
    print(f"  Variant: {score.variant}")
    print(f"{'='*60}")
    print(f"  Accuracy : {score.accuracy*100:.1f}%  ({sum(r.correct for r in score.results)}/{len(score.results)})")
    print(f"  Precision: {score.precision*100:.1f}%")
    print(f"  Recall   : {score.recall*100:.1f}%")
    print(f"  F1       : {score.f1*100:.1f}%")
    print(f"  TP={score.tp}  FP={score.fp}  FN={score.fn}  TN={score.tn}")
    print()
    print("  カテゴリ別:")
    for cat, info in score.category_breakdown().items():
        bar = "✓" * info["correct"] + "✗" * (info["total"] - info["correct"])
        print(f"    {cat:<16} {info['correct']}/{info['total']}  {info['pct']:5.1f}%  [{bar}]")

    if verbose:
        print()
        print("  ケース別詳細:")
        case_map = {c.id: c for c in cases}
        for r in score.results:
            c = case_map[r.case_id]
            mark = "✓" if r.correct else "✗"
            pred_str = "T" if r.predicted else "F"
            gt_str = "T" if r.ground_truth else "F"
            print(f"    {mark} {r.case_id:<22} GT={gt_str} Pred={pred_str}  {c.label[:35]}")
            if not r.correct and r.reasoning and "(from benchmark" not in r.reasoning:
                print(f"      → {r.reasoning[:80]}")
            if not r.correct and r.predicted and r.commitment_text:
                print(f"      CT: {r.commitment_text[:70]}")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Commitments prompt benchmark")
    parser.add_argument("--variant", nargs="*", default=list(PROMPT_VARIANTS.keys()),
                        choices=list(PROMPT_VARIANTS.keys()),
                        help="実行するバリアント (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="LLM呼び出しなし。benchmark dataのcurrent_outputスコアのみ表示")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="ケース別詳細を表示")
    args = parser.parse_args()

    cases = load_benchmark()
    logger.info("Loaded %d benchmark cases", len(cases))

    # 常に現行スコアを表示
    current_score = compute_current_score(cases)
    print_score(current_score, cases, verbose=args.verbose)

    if args.dry_run:
        return

    # API クライアント
    import os
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        logger.error("DEEPINFRA_API_KEY not set")
        sys.exit(1)
    client = openai.OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)

    # 各バリアントを実行
    all_scores: list[VariantScore] = [current_score]

    for variant_name in args.variant:
        system_prompt = PROMPT_VARIANTS[variant_name]
        score = VariantScore(variant=variant_name)
        logger.info("Running variant %s (%d cases)...", variant_name, len(cases))

        for i, case in enumerate(cases):
            has_commitment, commitment_text, reasoning, elapsed = call_llm(client, system_prompt, case)
            gt = case.ground_truth_has_commitment
            score.results.append(CaseResult(
                case_id=case.id,
                category=case.category,
                ground_truth=gt,
                predicted=has_commitment,
                commitment_text=commitment_text,
                reasoning=reasoning,
                correct=(gt == has_commitment),
                elapsed=elapsed,
            ))
            mark = "✓" if (gt == has_commitment) else "✗"
            logger.info(
                "  [%s %d/%d] %s GT=%s Pred=%s  %.1fs  %s",
                variant_name, i + 1, len(cases), mark,
                "T" if gt else "F", "T" if has_commitment else "F",
                elapsed, case.id,
            )

        all_scores.append(score)
        print_score(score, cases, verbose=args.verbose)

    # サマリー比較
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    print(f"  {'Variant':<30} {'Acc':>6} {'Prec':>6} {'Rec':>6} {'F1':>6}")
    print(f"  {'-'*56}")
    for s in all_scores:
        print(
            f"  {s.variant:<30} {s.accuracy*100:5.1f}%"
            f" {s.precision*100:5.1f}% {s.recall*100:5.1f}% {s.f1*100:5.1f}%"
        )


if __name__ == "__main__":
    main()
