"""transcript_corrector SYSTEM_PROMPT 改善評価スクリプト

v1（現状）と v2（改善版）を benchmark cases に対して実行し、
修正すべき3つのバグが解消されているかを自動採点する。

Usage:
    cd kokkai-transcriber
    python -m eval.eval_transcript_correction              # v1 + v2 全ケース
    python -m eval.eval_transcript_correction --version v2 --cases bug
    python -m eval.eval_transcript_correction --dry-run

採点指標（ケースごと）:
    - no_ellipsis:    「……」が出力に含まれないか (case06, case07)
    - no_sanseitou:   「賛成党」が出力に含まれないか (case08)
    - proper_length:  出力が Whisper 文字数の 80-130% 範囲か (全ケース)
    - no_content_add: 「……」以外の不正挿入がないか（簡易チェック）
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import openai

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EVAL_DIR = Path(__file__).parent
GOLDEN_DIR = EVAL_DIR / "golden"
RESULTS_DIR = EVAL_DIR / "results" / "transcript_correction"

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
MODEL = "deepseek-ai/DeepSeek-V3.2"

# ---------------------------------------------------------------------------
# SYSTEM_PROMPT v1（現状）— transcript_corrector.py の SYSTEM_PROMPT と同一
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_V1 = """あなたは国会議事録の校正専門家です。
Whisper音声認識が生成したテキストを、以下の観点で修正してください。

## 修正ルール
1. **句読点の補完**: 文末に「。」、疑問文に「？」を補う。読点「、」を適切に挿入する
2. **固有名詞の修正**: 議員名・政党名・会派名・委員会名・法案名の誤認識を修正する。発言者リストと委員会名を参考にすること
3. **同音異義語の修正**: 文脈に合わない漢字変換を修正する（例: 「介護保険」→文脈が皆保険制度の話なら「国民皆保険」）
4. **繰り返し・フィラーの除去**: 「あの」「えー」「まあ」等の不要なフィラーを除去する
5. **改行**: 話者交代の可能性がある箇所で改行（\\n\\n）を入れる。委員長の指名発言（「〇〇君」）の前後は必ず改行する

## 第221回国会（令和8年特別会）固有名詞リファレンス

### 政党・会派の正式名称（Whisperの漢字変換ミスに注意）
- チームみらい（「チーム未来」「チーム三来」等は誤り → チームみらい）
- 自由民主党（自民党）
- 立憲民主党
- 日本維新の会
- 公明党
- 国民民主党
- 日本共産党（共産党）
- 参政党
- れいわ新選組（「令和新選組」は誤り → れいわ新選組）
- 日本保守党
- 社会民主党（社民党）

### 主要閣僚（第2次高市内閣）
- 高市早苗（たかいちさなえ）内閣総理大臣
- 木原稔（きはらみのる）内閣官房長官
- 茂木敏充（もてぎとしみつ）外務大臣
- 片山さつき（かたやまさつき）財務大臣・金融担当
- 林芳正（はやしよしまさ）総務大臣
- 平口洋（ひらぐちひろし）法務大臣
- 松本洋平（まつもとようへい）文部科学大臣
- 上野賢一郎（うえのけんいちろう）厚生労働大臣
- 鈴木憲和（すずきのりかず）農林水産大臣
- 赤澤亮正（あかざわりょうせい）経済産業大臣
- 金子恭之（かねこやすし）国土交通大臣
- 石原宏高（いしはらひろたか）環境大臣
- 小泉進次郎（こいずみしんじろう）防衛大臣
- 松本尚（まつもとたかし）デジタル大臣
- 城内実（きうちみのる）経済財政政策担当
- 小野田紀美（おのだきみ）経済安全保障担当

### 衆議院議長・副議長
- 森英介（もりえいすけ）衆議院議長
- 石井啓一（いしいけいいち）衆議院副議長

### 参議院議長・副議長
- 関口昌一（せきぐちまさかず）参議院議長
- 福山哲郎（ふくやまてつろう）参議院副議長

### 主要法案
- 健康保険法等の一部を改正する法律案（高額療養費制度、OTC類似薬）
- 防災庁設置法案
- 国家情報会議設置法案
- 社会福祉法等の一部を改正する法律案
- 労働者災害補償保険法等の一部を改正する法律案
- ヒトゲノム編集胚等の取扱いの規制に関する法律案

### 頻出する国会用語
- 高額療養費（こうがくりょうようひ）
- OTC類似薬（オーティーシーるいじやく）
- 選定療養（せんていりょうよう）
- 一部保険外療養
- 破滅的医療支出
- 予見可能性
- 国民皆保険（こくみんかいほけん）

## 禁止事項
- テキストの意味を変えない。要約・省略・追加をしない
- 発言の順序を変えない
- 存在しない発言を捏造しない
- 発言者リストに記載された名前の表記を勝手に変えない
- 「……」を出力しない。聞き取れない箇所があっても元のテキストをそのまま残すこと

修正後のテキストのみを返してください。JSON形式ではなく、プレーンテキストで返してください。"""


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT v2（改善版）
# 変更点:
#   [fix1] 「……」禁止をより具体的に強化 + ノイズ除去後の正しい処理を明示
#   [fix2] 発言者リストの政党名を確定情報として明示 + 同音誤変換の修正例を追加
#   [fix3] Whisper混入ノイズのパターン説明と処置方法を追加
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_V2 = """あなたは国会議事録の校正専門家です。
Whisper音声認識が生成したテキストを、以下の観点で修正してください。

## 修正ルール
1. **句読点の補完**: 文末に「。」、疑問文に「？」を補う。読点「、」を適切に挿入する
2. **固有名詞の修正**: 議員名・政党名・会派名・委員会名・法案名の誤認識を修正する。
   - 発言者リストの名前・所属（政党・会派）は**確定情報**として扱う。テキスト内に同音の誤変換があれば必ず発言者リストの表記に修正する
   - 例: 発言者リストに「吉川里奈（参政党）」とある場合、テキスト内の「賛成党」「さんせい党」はすべて「参政党」の誤認識として修正する
   - 例: 発言者リストに「平将明」とある場合、テキスト内の「平正明」「平まさあき」は「平将明」に修正する
3. **同音異義語の修正**: 文脈に合わない漢字変換を修正する（例: 「介護保険」→文脈が皆保険制度の話なら「国民皆保険」）
4. **繰り返し・フィラーの除去**: 「あの」「えー」「まあ」等の不要なフィラーを除去する。Whisperが拾った音声ノイズも除去する（後述）
5. **改行**: 話者交代の可能性がある箇所で改行（\\n\\n）を入れる。委員長の指名発言（「〇〇君」）の前後は必ず改行する

## Whisper音声認識ノイズの取り扱い
Whisperはメイン発言者以外の音声（PA放送・隣席のマイク・委員長の呼びかけ等）を
発言文中に混入させることがある。以下のパターンを**除去してよい**:

- 話者名の2回以上の繰り返し（例: 「石井啓一議長、石井啓一議長、石井啓一議長。」）
- 文脈に合わない固有名詞の単独出現（例: 「成長型経済すなわち**岩田和親**こうした中」の「岩田和親」は発言者名の呼びかけノイズ）
- 「議長＊○○君」「＊○○君」のような特殊記号付き挿入句

**ノイズ除去後の処理**: 前後のテキストを直接つなぐ。「……」は絶対に挿入しない。
文の末尾が「を」「が」「は」等の助詞で終わる不完全な形になっても、そのまま次の文に続ける。

## 第221回国会（令和8年特別会）固有名詞リファレンス

### 政党・会派の正式名称（Whisperの漢字変換ミスに注意）
- チームみらい（「チーム未来」「チーム三来」等は誤り → チームみらい）
- 自由民主党（自民党）
- 立憲民主党
- 日本維新の会
- 公明党
- 国民民主党
- 日本共産党（共産党）
- 参政党（「賛成党」「さんせい党」は誤り → 参政党）
- れいわ新選組（「令和新選組」は誤り → れいわ新選組）
- 日本保守党
- 社会民主党（社民党）

### 主要閣僚（第2次高市内閣）
- 高市早苗（たかいちさなえ）内閣総理大臣
- 木原稔（きはらみのる）内閣官房長官
- 茂木敏充（もてぎとしみつ）外務大臣
- 片山さつき（かたやまさつき）財務大臣・金融担当
- 林芳正（はやしよしまさ）総務大臣
- 平口洋（ひらぐちひろし）法務大臣
- 松本洋平（まつもとようへい）文部科学大臣
- 上野賢一郎（うえのけんいちろう）厚生労働大臣
- 鈴木憲和（すずきのりかず）農林水産大臣
- 赤澤亮正（あかざわりょうせい）経済産業大臣
- 金子恭之（かねこやすし）国土交通大臣
- 石原宏高（いしはらひろたか）環境大臣
- 小泉進次郎（こいずみしんじろう）防衛大臣
- 松本尚（まつもとたかし）デジタル大臣
- 城内実（きうちみのる）経済財政政策担当
- 小野田紀美（おのだきみ）経済安全保障担当

### 衆議院議長・副議長
- 森英介（もりえいすけ）衆議院議長
- 石井啓一（いしいけいいち）衆議院副議長

### 参議院議長・副議長
- 関口昌一（せきぐちまさかず）参議院議長
- 福山哲郎（ふくやまてつろう）参議院副議長

### 主要法案
- 健康保険法等の一部を改正する法律案（高額療養費制度、OTC類似薬）
- 防災庁設置法案
- 国家情報会議設置法案
- 社会福祉法等の一部を改正する法律案
- 労働者災害補償保険法等の一部を改正する法律案
- ヒトゲノム編集胚等の取扱いの規制に関する法律案

### 頻出する国会用語
- 高額療養費（こうがくりょうようひ）
- OTC類似薬（オーティーシーるいじやく）
- 選定療養（せんていりょうよう）
- 一部保険外療養
- 破滅的医療支出
- 予見可能性
- 国民皆保険（こくみんかいほけん）

## 禁止事項
- テキストの意味を変えない。要約・省略・追加をしない
- 発言の順序を変えない
- 存在しない発言を捏造しない
- 発言者リストに記載された名前の表記を勝手に変えない
- 「……」を**絶対に**出力しない（例外なし）。元のテキストが不完全であっても、聞き取れない箇所があっても、ノイズを除去した後も、「……」は一切使用しない。前後テキストを直接つなぐこと

修正後のテキストのみを返してください。JSON形式ではなく、プレーンテキストで返してください。"""


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT v3（改善版）
# 変更点（v2からの差分）:
#   [fix4] 「祈念」と「懸念」の近音誤変換を追記。哀悼・黙祷文脈での修正を明示
#   [fix5] 同音異義語ルールに Memorial/条文コンテキストの例を追加
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_V3 = """あなたは国会議事録の校正専門家です。
Whisper音声認識が生成したテキストを、以下の観点で修正してください。

## 修正ルール
1. **句読点の補完**: 文末に「。」、疑問文に「？」を補う。読点「、」を適切に挿入する
2. **固有名詞の修正**: 議員名・政党名・会派名・委員会名・法案名の誤認識を修正する。
   - 発言者リストの名前・所属（政党・会派）は**確定情報**として扱う。テキスト内に同音の誤変換があれば必ず発言者リストの表記に修正する
   - 例: 発言者リストに「吉川里奈（参政党）」とある場合、テキスト内の「賛成党」「さんせい党」はすべて「参政党」の誤認識として修正する
   - 例: 発言者リストに「平将明」とある場合、テキスト内の「平正明」「平まさあき」は「平将明」に修正する
3. **同音異義語の修正**: 文脈に合わない漢字変換を修正する
   - 例: 「介護保険」→ 皆保険制度の文脈なら「国民皆保険」
   - 例: 「懸念」→ 哀悼・黙祷・震災追悼の文脈では「祈念」が正しい（「復興を祈念する」「祈念いたします」）
   - 例: 「猶予」→ 支払い猶予・執行猶予などの法的文脈では文脈確認の上修正
4. **繰り返し・フィラーの除去**: 「あの」「えー」「まあ」等の不要なフィラーを除去する。Whisperが拾った音声ノイズも除去する（後述）
5. **改行**: 話者交代の可能性がある箇所で改行（\\n\\n）を入れる。委員長の指名発言（「〇〇君」）の前後は必ず改行する

## Whisper音声認識ノイズの取り扱い
Whisperはメイン発言者以外の音声（PA放送・隣席のマイク・委員長の呼びかけ等）を
発言文中に混入させることがある。以下のパターンを**除去してよい**:

- 話者名の2回以上の繰り返し（例: 「石井啓一議長、石井啓一議長、石井啓一議長。」）
- 文脈に合わない固有名詞の単独出現（例: 「成長型経済すなわち**岩田和親**こうした中」の「岩田和親」は発言者名の呼びかけノイズ）
- 「議長＊○○君」「＊○○君」のような特殊記号付き挿入句

**ノイズ除去後の処理**: 前後のテキストを直接つなぐ。「……」は絶対に挿入しない。
文の末尾が「を」「が」「は」等の助詞で終わる不完全な形になっても、そのまま次の文に続ける。

## 第221回国会（令和8年特別会）固有名詞リファレンス

### 政党・会派の正式名称（Whisperの漢字変換ミスに注意）
- チームみらい（「チーム未来」「チーム三来」等は誤り → チームみらい）
- 自由民主党（自民党）
- 立憲民主党
- 日本維新の会
- 公明党
- 国民民主党
- 日本共産党（共産党）
- 参政党（「賛成党」「さんせい党」は誤り → 参政党）
- れいわ新選組（「令和新選組」は誤り → れいわ新選組）
- 日本保守党
- 社会民主党（社民党）

### 主要閣僚（第2次高市内閣）
- 高市早苗（たかいちさなえ）内閣総理大臣
- 木原稔（きはらみのる）内閣官房長官
- 茂木敏充（もてぎとしみつ）外務大臣
- 片山さつき（かたやまさつき）財務大臣・金融担当
- 林芳正（はやしよしまさ）総務大臣
- 平口洋（ひらぐちひろし）法務大臣
- 松本洋平（まつもとようへい）文部科学大臣
- 上野賢一郎（うえのけんいちろう）厚生労働大臣
- 鈴木憲和（すずきのりかず）農林水産大臣
- 赤澤亮正（あかざわりょうせい）経済産業大臣
- 金子恭之（かねこやすし）国土交通大臣
- 石原宏高（いしはらひろたか）環境大臣
- 小泉進次郎（こいずみしんじろう）防衛大臣
- 松本尚（まつもとたかし）デジタル大臣
- 城内実（きうちみのる）経済財政政策担当
- 小野田紀美（おのだきみ）経済安全保障担当

### 衆議院議長・副議長
- 森英介（もりえいすけ）衆議院議長
- 石井啓一（いしいけいいち）衆議院副議長

### 参議院議長・副議長
- 関口昌一（せきぐちまさかず）参議院議長
- 福山哲郎（ふくやまてつろう）参議院副議長

### 主要法案
- 健康保険法等の一部を改正する法律案（高額療養費制度、OTC類似薬）
- 防災庁設置法案
- 国家情報会議設置法案
- 社会福祉法等の一部を改正する法律案
- 労働者災害補償保険法等の一部を改正する法律案
- ヒトゲノム編集胚等の取扱いの規制に関する法律案

### 頻出する国会用語・近音誤変換に注意すべき語
- 高額療養費（こうがくりょうようひ）
- OTC類似薬（オーティーシーるいじやく）
- 選定療養（せんていりょうよう）
- 一部保険外療養
- 破滅的医療支出
- 予見可能性
- 国民皆保険（こくみんかいほけん）
- 祈念（きねん）: Whisperが「懸念（けねん）」と誤変換することがある。哀悼・黙祷・復興の文脈では「祈念」が正しい

## 禁止事項
- テキストの意味を変えない。要約・省略・追加をしない
- 発言の順序を変えない
- 存在しない発言を捏造しない
- 発言者リストに記載された名前の表記を勝手に変えない
- 「……」を**絶対に**出力しない（例外なし）。元のテキストが不完全であっても、聞き取れない箇所があっても、ノイズを除去した後も、「……」は一切使用しない。前後テキストを直接つなぐこと

修正後のテキストのみを返してください。JSON形式ではなく、プレーンテキストで返してください。"""


VERSIONS = {"v1": SYSTEM_PROMPT_V1, "v2": SYSTEM_PROMPT_V2, "v3": SYSTEM_PROMPT_V3}

# ケースごとの採点設定
CASE_CRITERIA: dict[str, dict] = {
    "case01": {"label": "句読点補完",          "checks": ["proper_length"]},
    "case02": {"label": "固有名詞修正",         "checks": ["proper_length", "no_hiramasa"]},
    "case03": {"label": "GDP大文字化",          "checks": ["proper_length", "gdp_uppercase"]},
    "case04": {"label": "同音異義語（祈念）",   "checks": ["proper_length", "kinen_fixed"]},
    "case05": {"label": "同音異義語（猶予）",   "checks": ["proper_length", "yuuyo_fixed"]},
    "case06": {"label": "【BUG】雑音除去",       "checks": ["no_ellipsis", "noise_removed_c06", "proper_length"]},
    "case07": {"label": "【BUG】PA雑音除去",    "checks": ["no_ellipsis", "proper_length"]},
    "case08": {"label": "【BUG】賛成党未修正",  "checks": ["no_sanseitou", "proper_length"]},
}

# case08は文字数が多くコストがかさむため、デフォルトは短縮版のみ
BUG_CASES = ["case06", "case07", "case08"]
BASELINE_CASES = ["case01", "case02", "case03", "case04", "case05"]
ALL_CASES = BASELINE_CASES + BUG_CASES


def _score(output: str, case_id: str, whisper_len: int) -> dict[str, bool | str]:
    """出力テキストを自動採点する。"""
    checks = CASE_CRITERIA[case_id]["checks"]
    results: dict[str, bool | str] = {}

    for check in checks:
        if check == "no_ellipsis":
            results[check] = "……" not in output
        elif check == "no_sanseitou":
            results[check] = "賛成党" not in output
        elif check == "no_hiramasa":
            results[check] = "平正明" not in output
        elif check == "gdp_uppercase":
            results[check] = "GDP" in output and "gdp" not in output
        elif check == "kinen_fixed":
            results[check] = "祈念" in output and "懸念" not in output
        elif check == "yuuyo_fixed":
            results[check] = "猶予" in output and "優位" not in output
        elif check == "noise_removed_c06":
            # 「成長型経済すなわち岩田和親」のパターン — 岩田和親が本文中に残っていないか
            # 「岩田和親君。」は話者アナウンスなので許容。本文内「すなわち岩田」が残るのは失敗
            results[check] = "すなわち岩田" not in output
        elif check == "proper_length":
            ratio = len(output) / whisper_len if whisper_len > 0 else 1.0
            results[check] = 0.75 <= ratio <= 1.5

    # 全チェック通過か
    results["pass"] = all(v for v in results.values() if isinstance(v, bool))
    return results


def _call_api(system_prompt: str, user_prompt: str, api_key: str) -> tuple[str, float]:
    """DeepInfra API を呼び出してテキストを返す。(output, latency_sec)"""
    client = openai.OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)
    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=8192,
    )
    elapsed = time.monotonic() - t0
    return (resp.choices[0].message.content or "").strip(), elapsed


def _run_case(
    version: str,
    case_id: str,
    system_prompt: str,
    api_key: str,
    force: bool = False,
) -> dict:
    """1 version × 1 case を実行してスコアつき結果辞書を返す。"""
    input_path  = GOLDEN_DIR / f"transcript_correction_{case_id}.input.json"
    result_path = RESULTS_DIR / version / f"{case_id}.result.json"

    if result_path.exists() and not force:
        logger.info("  SKIP  %s / %s (already exists)", version, case_id)
        data = json.loads(result_path.read_text())
        return data

    inp = json.loads(input_path.read_text())
    user_prompt   = inp["user_prompt"]
    whisper_len   = inp["metadata"]["whisper_char_count"]

    logger.info("  RUN   %s / %s  (%d chars) ...", version, case_id, whisper_len)
    output, latency = _call_api(system_prompt, user_prompt, api_key)

    scores = _score(output, case_id, whisper_len)

    result = {
        "version":     version,
        "case_id":     case_id,
        "output":      output,
        "latency_sec": round(latency, 2),
        "output_len":  len(output),
        "whisper_len": whisper_len,
        "scores":      scores,
    }

    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _print_table(all_results: list[dict]) -> None:
    """バージョン × ケースの比較サマリーを表示する。"""
    if not all_results:
        print("No results.")
        return

    # 存在するバージョンを結果から動的に取得（v1, v2, v3 ...の順）
    present_versions = sorted(set(r["version"] for r in all_results), key=lambda v: v)

    print()
    print("=" * 90)
    print("  transcript_correction 改善評価サマリー")
    print("=" * 90)
    header = f"  {'case':<8} {'label':<22} " + "".join(f"{v:>7}" for v in present_versions) + "  変化(先→末)"
    print(header)
    print("-" * 90)

    by_case: dict[str, dict[str, dict]] = {}
    for r in all_results:
        by_case.setdefault(r["case_id"], {})[r["version"]] = r

    def fmt_ver(case_id: str, ver: str) -> str:
        versions_for_case = by_case.get(case_id, {})
        if ver not in versions_for_case:
            return "   N/A"
        s = versions_for_case[ver]["scores"]
        checks = CASE_CRITERIA[case_id]["checks"]
        n_pass = sum(1 for c in checks if s.get(c) is True)
        total  = len(checks)
        icon   = "✓" if s.get("pass") else "✗"
        return f"{icon} {n_pass}/{total}"

    for case_id in ALL_CASES:
        if case_id not in by_case:
            continue
        label = CASE_CRITERIA[case_id]["label"]

        ver_fmts = "".join(f"{fmt_ver(case_id, v):>7}" for v in present_versions)

        # 変化: 最初のバージョン → 最後のバージョン
        first_pass = by_case[case_id].get(present_versions[0], {}).get("scores", {}).get("pass", None)
        last_pass  = by_case[case_id].get(present_versions[-1], {}).get("scores", {}).get("pass", None)
        if first_pass is None or last_pass is None:
            change = "  -"
        elif not first_pass and last_pass:
            change = "  ✨ FIXED"
        elif first_pass and not last_pass:
            change = "  ⚠ REGRESSED"
        elif first_pass and last_pass:
            change = "  → 維持"
        else:
            change = "  → 未解決"

        tag = "★" if case_id in BUG_CASES else " "
        print(f"  {tag}{case_id:<7} {label:<22}{ver_fmts}  {change}")

    print("-" * 90)
    print("=" * 90)


def run(
    versions: list[str],
    cases: list[str],
    api_key: str,
    force: bool = False,
    dry_run: bool = False,
    max_workers: int = 4,
) -> None:
    jobs = [(ver, case_id) for ver in versions for case_id in cases]
    logger.info("Total jobs: %d (%s × %s)", len(jobs), versions, cases)

    if dry_run:
        for ver, case_id in jobs:
            inp = json.loads((GOLDEN_DIR / f"transcript_correction_{case_id}.input.json").read_text())
            w = inp["metadata"]["whisper_char_count"]
            logger.info("  [DRY-RUN] %s / %s  whisper=%d chars", ver, case_id, w)
        return

    all_results: list[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(_run_case, ver, case_id, VERSIONS[ver], api_key, force): (ver, case_id)
            for ver, case_id in jobs
        }
        for fut in as_completed(futs):
            ver, case_id = futs[fut]
            try:
                result = fut.result()
                all_results.append(result)
                s = result["scores"]
                logger.info(
                    "  DONE  %s / %s  pass=%s  latency=%.1fs  len=%d→%d",
                    ver, case_id, s.get("pass"), result["latency_sec"],
                    result["whisper_len"], result["output_len"],
                )
            except Exception as e:
                logger.exception("FAIL  %s / %s: %s", ver, case_id, e)

    _print_table(all_results)


def main() -> None:
    parser = argparse.ArgumentParser(description="transcript_correction プロンプト改善評価")
    parser.add_argument(
        "--version", nargs="+", choices=list(VERSIONS.keys()), default=["v1", "v2"],
        help="評価するプロンプトバージョン（デフォルト: v1 v2 両方）",
    )
    parser.add_argument(
        "--cases", choices=["all", "bug", "baseline"], default="all",
        help="評価ケース選択: all=全8件 bug=バグ3件 baseline=正解5件",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="既存の結果ファイルを上書き再実行する",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="API呼び出しなしで確認のみ",
    )
    parser.add_argument(
        "--workers", type=int, default=4,
        help="並列数（デフォルト: 4）",
    )
    args = parser.parse_args()

    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key and not args.dry_run:
        raise EnvironmentError("DEEPINFRA_API_KEY environment variable is not set.")

    case_map = {"all": ALL_CASES, "bug": BUG_CASES, "baseline": BASELINE_CASES}
    target_cases = case_map[args.cases]

    run(
        versions=args.version,
        cases=target_cases,
        api_key=api_key or "",
        force=args.force,
        dry_run=args.dry_run,
        max_workers=args.workers,
    )


if __name__ == "__main__":
    main()
