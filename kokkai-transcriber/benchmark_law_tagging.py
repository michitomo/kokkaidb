#!/usr/bin/env python3
"""法案タグ付けプロンプトのベンチマーク

tests/fixtures/law_tagging_benchmark.json に定義されたテストケースに対して
LLM を呼び出し、related_laws の精度・再現率を測定する。

使い方:
    cd kokkai-transcriber
    source .venv/bin/activate
    python benchmark_law_tagging.py                  # 全ケース実行
    python benchmark_law_tagging.py --case bench_001 # 特定ケースのみ
    python benchmark_law_tagging.py --dry-run        # LLM呼び出しなし（構造確認のみ）

出力:
    各ケースの law_id レベル F1・qa_id レベル再現率をテーブルで表示。
    詳細な生出力は --verbose で確認可能。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
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

# ---- Paths ----
BENCH_DIR = Path(__file__).parent
FIXTURES_PATH = BENCH_DIR / "tests/fixtures/law_tagging_benchmark.json"
LAWS_PATH = BENCH_DIR.parent / "data/laws/laws_compact.txt"
LAWS_JSON_PATH = BENCH_DIR.parent / "data/laws/laws.json"

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

# デフォルトモデル: structurer.py と合わせる
DEFAULT_MODEL = "google/gemma-4-31B-it"


def build_id_normalization_map() -> dict[str, str]:
    """laws_compact.txt の実ID（clb-XXXX / shugiin-XXX 等）を合成 law_XXX IDにマップする。

    ベンチマーク fixture は「law_001 = 1行目、law_002 = 2行目 ...」という規約を採用。
    モデルは laws_compact.txt を見て clb-XXXX 等を出力するため、評価時に law_XXX へ変換する。
    戻り値: {"clb-5149": "law_001", "clb-5151": "law_002", ...}
    """
    if not LAWS_PATH.exists():
        return {}
    compact_lines = [
        line for line in LAWS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    mapping: dict[str, str] = {}
    for i, line in enumerate(compact_lines):
        actual_id = line.split(":")[0].strip()  # "clb-5149"
        if actual_id:
            mapping[actual_id] = f"law_{i + 1:03d}"
    return mapping

# ---- プロンプトバージョン管理 ----
# イテレーション時は SYSTEM_PROMPT を差し替える。
# 各バージョンを定数として残し、最後に SYSTEM_PROMPT に代入する。

# V0: オリジナル（ベースライン）
PROMPT_V0 = """あなたは国会会議の分析専門家です。
セッション全体のutterancesとQ&Aペアから、要約・トピック分析・関連法案タグ付けを一括で行ってください。

以下のJSON形式で出力してください:

{
  "session_summary": "セッション全体の概要（3-5文）",
  "key_topics": ["主要トピック1", "主要トピック2", ...],
  "key_commitments": [],
  "topics": [],
  "related_laws": [
    {
      "law_id": "law_001",
      "qa_ids": ["qa_001", "qa_003"]
    }
  ]
}

## トピック抽出ルール
- 政策領域・法案・社会問題などの観点から分類する

## 関連法案タグ付けルール
- 法案一覧が提供された場合、各Q&Aペアが実質的にどの法案に関連するかを判断する
- 法案名がtopicに含まれる場合だけでなく、質疑の内容・文脈から関連する法案を幅広く判断する
- 確信度が低いものは含めない（明らかに関連するもののみ）
- 法案一覧が提供されない場合、related_lawsは空配列を返す
"""

# V1: ID形式の明示 + 判断基準の整理（→ 依然 clb-XXXX を生成。モデルの訓練データ由来のIDが優先されている）
PROMPT_V1 = """あなたは国会会議の分析専門家です。
セッション全体のutterancesとQ&Aペアから、要約・トピック分析・関連法案タグ付けを一括で行ってください。

以下のJSON形式で出力してください:

{
  "session_summary": "セッション全体の概要（3-5文）",
  "key_topics": ["主要トピック1", "主要トピック2", ...],
  "key_commitments": [],
  "topics": [],
  "related_laws": [
    {
      "law_id": "law_025",
      "qa_ids": ["qa_001", "qa_003"]
    }
  ]
}

## トピック抽出ルール
- 政策領域・法案・社会問題などの観点から分類する

## 関連法案タグ付けルール

**【必須】law_id は「## 法案一覧」に記載された識別子（law_001, law_025 等）を使うこと。**
clb-XXXX・shugiin-XXX などの独自識別子は使用しない。法案一覧にない法案もタグ付けしない。

法案一覧が提供されない場合、related_laws は空配列を返す。

タグ付けの判断基準（優先順）:

1. **直接言及（必ずタグ付け）**
   QAペアのトピック名または質問・回答の要旨に、法案名またはその主要部分が含まれる場合は
   必ず対応する law_id をタグ付けする。
   例: topic に「健康保険法等の一部を改正する法律案」が含まれる → law_025 を付与

2. **文脈推論（確信度が中程度以上の場合）**
   トピック名に法案名が含まれなくても、質疑の内容・政策領域から
   「この質疑は当該法案の審議として行われている」と判断できる場合はタグ付けする。
   委員会審議中の法案についての具体的な条文内容・施行規則・運用方針に関する質疑が該当する。

3. **タグ付けしない場合**
   - 特定法案の審議ではない一般的な政策議論（予算委員会の一般質疑等）
   - 「関連するかもしれない」程度の間接的なつながり
   - 法案一覧に存在しない法案

qa_ids の記載ルール:
- そのQ&Aペアが実質的にその法案を直接議論している場合に qa_id を記載する
- セッション全体に関連するが特定のQ&Aに紐付けられない場合は qa_ids=[] でよい
"""

# V2: 3箇所への ID指示配置 + ユーザープロンプト側でも注記
# 戦略: (1)システムプロンプト冒頭, (2)JSON例示内コメント, (3)ユーザープロンプトの法案リスト直前
PROMPT_V2 = """【重要ルール】related_laws の law_id は、必ずユーザープロンプトの「## 法案一覧」に記載された \
「law_XXX」識別子を使うこと。clb-XXXX・shugiin-XXX などは絶対に使用しない。

あなたは国会会議の分析専門家です。
セッション全体のQ&Aペアから、要約・トピック分析・関連法案タグ付けを行ってください。

以下のJSON形式で出力してください:

{
  "session_summary": "セッション全体の概要（3-5文）",
  "key_topics": ["主要トピック1", "主要トピック2", ...],
  "key_commitments": [],
  "topics": [],
  "related_laws": [
    {
      "law_id": "law_025",
      "qa_ids": ["qa_001", "qa_003"]
    }
  ]
}

※ law_id は必ず「## 法案一覧」の各行先頭の「law_XXX」を使うこと。それ以外の識別子は使わない。

## タグ付けルール

法案一覧が提供されない場合、related_laws は空配列を返す。

タグ付けの判断基準:
1. **直接言及（必ずタグ付け）**: QAのトピック名または要旨に法案名が含まれる場合は必ずタグ付けする。
2. **文脈推論**: 「この質疑は当該法案の審議として行われている」と判断できる場合はタグ付けする。
3. **タグ付けしない**: 特定法案の審議でない一般質疑、または法案一覧にない法案は含めない。

qa_ids には、そのQ&Aペアが実質的にその法案を議論している場合に qa_id を記載する。
"""

# V3: 「審議中かどうか」の判断軸を明確化 + 一般質疑での偽陽性抑制
PROMPT_V3 = """あなたは国会会議の分析専門家です。
セッション全体のQ&Aペアから、要約・トピック分析・関連法案タグ付けを行ってください。

以下のJSON形式で出力してください:

{
  "session_summary": "セッション全体の概要（3-5文）",
  "key_topics": ["主要トピック1", "主要トピック2", ...],
  "key_commitments": [],
  "topics": [],
  "related_laws": [
    {
      "law_id": "（法案IDをそのまま使用。例: clb-5199）",
      "qa_ids": ["qa_001", "qa_003"]
    }
  ]
}

## 関連法案タグ付けルール

**判断基準**: 「この法案がこのセッションで**直接審議されているか**」を判断する。
法案の政策分野と質疑の話題が一致するだけでは不十分。**その法案の条文・施行・運用・効果が具体的に議論されている**必要がある。

### タグ付けする（確信度：高）
- QAのトピック名または質問・回答の要旨に、法案名またはその主要部分が**明示的に含まれる**
- 委員会審議で、法案の特定の条文内容（「第X条の規定により…」等）、施行時期、運用方針、対象範囲について質疑が行われている

### タグ付けしない（確信度：低）
- **予算委員会・特別委員会の一般質疑**など、特定法案の審議を目的としないセッションで、たまたま法案の政策領域に触れた場合
- 「この政策にはこんな法案もある」という間接的な関連性のみ（法案が議題の中心でない）
- 「〇〇を強化する方針」「〇〇を検討している」という政策方針の言及（特定の法案条文を審議していない）

### qa_idsの記載
- その法案の条文・内容を実質的に議論しているQAペアのqa_idをすべて記載する
- 法案に関連するQAペアを漏れなく記載し、セッション全体が1法案を審議している場合は関連QAのqa_idをすべて列挙する

### 重要
- 法案一覧が提供されない場合、related_laws は空配列を返す
- 法案一覧にない法案はタグ付けしない
"""

# V4: session_context を活用した判断基準の明確化
PROMPT_V4 = """あなたは国会会議の分析専門家です。
セッション全体のQ&Aペアから、要約・トピック分析・関連法案タグ付けを行ってください。

以下のJSON形式で出力してください:

{
  "session_summary": "セッション全体の概要（3-5文）",
  "key_topics": ["主要トピック1", "主要トピック2", ...],
  "key_commitments": [],
  "topics": [],
  "related_laws": [
    {
      "law_id": "（法案IDをそのまま使用。例: clb-5199）",
      "qa_ids": ["qa_001", "qa_003"]
    }
  ]
}

## 関連法案タグ付けルール

### 入力の「セッション情報」を最初に確認する
- **本会議（趣旨説明・代表質問）**: 趣旨説明された法案を特定し、その法案に関連する全QAをタグ付けする
- **委員会（審議中の法案あり）**: セッション情報に記載された審議中法案について、関連QAをタグ付けする
- **予算委員会・一般質疑（法案審議なし）**: セッション情報に「一般質疑」「特定法案の審議ではない」と記載されている場合は、**法案名が質問・回答に明示的に言及されている場合のみ**タグ付けし、話題が関連するだけでは付けない

### タグ付けの判断基準
1. **直接言及（必ずタグ付け）**: QAのトピック名に法案名が含まれる → 必ずタグ付け
2. **委員会審議（タグ付け）**: セッション情報で審議中と明示された法案に関連する質疑 → タグ付け
3. **一般質疑（厳格制限）**: セッション情報が「一般質疑」「法案審議なし」の場合、**QAのトピック名に法案名が含まれる場合のみ**タグ付けする。質問・回答内の言及（政策方針・将来計画・検討事項）はタグ付けの根拠にならない

### qa_idsの記載
- タグ付けした法案に直接関連するQAのqa_idをすべて記載する
- セッション全体が1法案の審議であれば、全QAのqa_idを漏れなく記載する

### 重要
- 法案一覧が提供されない場合、related_laws は空配列を返す
- 法案一覧にないIDはタグ付けしない
"""

# ---- 現在テスト中のプロンプト ----
SYSTEM_PROMPT = PROMPT_V4


def get_client() -> openai.OpenAI:
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPINFRA_API_KEY not set")
    return openai.OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)


def format_qa_text(qa_pairs: list[dict]) -> str:
    """structurer.py の generate_summary_and_topics と同じフォーマット。"""
    lines = []
    for p in qa_pairs:
        lines.append(
            f"[{p['id']}] トピック: {p['topic']}\n"
            f"  質問者: {p['question_speaker']}（{p['question_party']}）\n"
            f"  質問要旨: {p['question_summary']}\n"
            f"  回答要旨: {p['answer_summary']}"
        )
    return "\n".join(lines)


def call_llm(
    client: openai.OpenAI,
    model: str,
    qa_text: str,
    laws_text: str,
    session_context: str = "",
) -> tuple[str, float]:
    """LLM を呼び出して (生レスポンス, 所要秒数) を返す。"""
    parts = ["以下の国会質疑のQ&Aペア一覧を分析してください。"]
    if session_context:
        parts.append(f"\n## セッション情報\n{session_context}")
    parts.append(f"\n## Q&Aペア一覧\n{qa_text}")
    user_prompt = "\n".join(parts)
    if laws_text:
        user_prompt += f"\n\n## 法案一覧\n{laws_text}"

    start = time.time()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )
    elapsed = time.time() - start
    return (resp.choices[0].message.content or ""), elapsed


def parse_related_laws(content: str, id_map: dict[str, str]) -> list[dict]:
    """LLM の JSON 応答から related_laws を取り出し、law_id を正規化する。

    モデルは実際の clb-XXXX / shugiin-XXX 等の ID を出力する傾向があるため、
    laws.json と laws_compact.txt の対応表で law_XXX 形式に変換する。
    """
    try:
        data = json.loads(content)
        raw = data.get("related_laws", [])
    except json.JSONDecodeError:
        logger.error("JSON parse error: %s", content[:200])
        return []

    normalized = []
    for entry in raw:
        raw_id = entry.get("law_id", "")
        # already law_XXX format → keep as is
        if raw_id.startswith("law_"):
            normalized.append(entry)
        elif raw_id in id_map:
            normalized.append({**entry, "law_id": id_map[raw_id]})
            logger.debug("Normalized law_id: %s → %s", raw_id, id_map[raw_id])
        else:
            # Unknown ID: keep with a warning (won't match expected)
            logger.debug("Unknown law_id format (not in map): %s", raw_id)
            normalized.append(entry)
    return normalized


# ---- 評価ロジック ----

def evaluate_case(case: dict, actual_laws: list[dict]) -> dict:
    """1ケースのスコアを計算する。

    Returns:
        {
            "law_precision": float,  # 予測した law_id のうち正解の割合
            "law_recall": float,     # 必須 law_id のうち予測できた割合
            "law_f1": float,
            "required_law_hits": list[str],   # 正しく予測できた必須law_id
            "required_law_misses": list[str], # 予測できなかった必須law_id
            "forbidden_law_hits": list[str],  # 誤って予測した禁止law_id
            "qa_id_recalls": dict[str, float] # law_id -> qa_id 再現率
            "pass": bool,
        }
    """
    expected = case["expected"]
    required = {r["law_id"]: r for r in expected.get("required_laws", [])}
    forbidden = set(expected.get("forbidden_laws", []))

    actual_by_id = {a["law_id"]: a.get("qa_ids", []) for a in actual_laws}

    # law_id レベルの精度・再現率
    predicted_ids = set(actual_by_id.keys())
    required_ids = set(required.keys())

    hits = predicted_ids & required_ids
    misses = required_ids - predicted_ids
    forbidden_hits = predicted_ids & forbidden
    spurious = predicted_ids - required_ids - forbidden  # 必須でも禁止でもない予測

    law_recall = len(hits) / len(required_ids) if required_ids else (1.0 if not predicted_ids else 0.0)
    law_precision = len(hits) / len(predicted_ids) if predicted_ids else (1.0 if not required_ids else 0.0)
    law_f1 = (2 * law_precision * law_recall / (law_precision + law_recall)
               if (law_precision + law_recall) > 0 else 0.0)

    # "タグなし" ケース: required_laws=[] かつ may_be_empty=True
    if expected.get("empty_is_correct") and not required_ids:
        law_recall = 1.0 if not predicted_ids else 0.0
        law_precision = 1.0 if not predicted_ids else 0.0
        law_f1 = 1.0 if not predicted_ids else 0.0

    # qa_id レベルの再現率（各必須law_idについて）
    qa_id_recalls: dict[str, float] = {}
    for law_id, req in required.items():
        must_ids = set(req.get("must_include_qa_ids", []))
        if not must_ids:
            continue
        actual_qa_ids = set(actual_by_id.get(law_id, []))
        qa_id_recalls[law_id] = len(must_ids & actual_qa_ids) / len(must_ids)

    passed = (
        len(misses) == 0
        and len(forbidden_hits) == 0
        and all(v >= 1.0 for v in qa_id_recalls.values())
        and (not expected.get("empty_is_correct") or not predicted_ids)
    )

    return {
        "law_precision": round(law_precision, 3),
        "law_recall": round(law_recall, 3),
        "law_f1": round(law_f1, 3),
        "required_law_hits": sorted(hits),
        "required_law_misses": sorted(misses),
        "forbidden_law_hits": sorted(forbidden_hits),
        "spurious_laws": sorted(spurious),
        "qa_id_recalls": {k: round(v, 3) for k, v in qa_id_recalls.items()},
        "pass": passed,
    }


def print_summary(results: list[dict]) -> None:
    """結果テーブルを標準出力に表示。"""
    header = f"{'ID':<12} {'Label':<45} {'P':>5} {'R':>5} {'F1':>5} {'Pass':>5}"
    print()
    print(header)
    print("-" * len(header))
    passed = 0
    for r in results:
        p = r["scores"]["law_precision"]
        rec = r["scores"]["law_recall"]
        f1 = r["scores"]["law_f1"]
        ok = "OK" if r["scores"]["pass"] else "FAIL"
        if r["scores"]["pass"]:
            passed += 1
        label = r["case_label"][:45]
        print(f"{r['case_id']:<12} {label:<45} {p:>5.2f} {rec:>5.2f} {f1:>5.2f} {ok:>5}")
    print("-" * len(header))
    print(f"Passed: {passed}/{len(results)}")
    print()


def print_verbose(case: dict, actual_laws: list[dict], scores: dict) -> None:
    """ケースの詳細を表示。"""
    print(f"\n=== {case['id']}: {case['label']} ===")
    print(f"Pattern: {case['pattern']} | Expected: {case['current_status']}")
    print(f"Required laws: {[r['law_id'] for r in case['expected'].get('required_laws', [])]}")
    print(f"Actual laws:   {[a['law_id'] for a in actual_laws]}")
    if scores["required_law_misses"]:
        print(f"MISSED:        {scores['required_law_misses']}")
    if scores["forbidden_law_hits"]:
        print(f"FORBIDDEN HIT: {scores['forbidden_law_hits']}")
    if scores["spurious_laws"]:
        print(f"Spurious:      {scores['spurious_laws']}")
    if scores["qa_id_recalls"]:
        print(f"QA-id recall:  {scores['qa_id_recalls']}")
    print(f"Score: P={scores['law_precision']:.2f} R={scores['law_recall']:.2f} F1={scores['law_f1']:.2f} {'PASS' if scores['pass'] else 'FAIL'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="法案タグ付けベンチマーク")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="DeepInfra モデル名")
    parser.add_argument("--case", help="特定ケースIDのみ実行 (例: bench_001)")
    parser.add_argument("--dry-run", action="store_true", help="LLM呼び出しなし（ランダムな空結果を使用）")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細表示")
    parser.add_argument("--save-as", help="結果を保存するファイル名サフィックス (例: v1 → _v1.json)")
    args = parser.parse_args()

    # ベンチマークデータの読み込み
    with open(FIXTURES_PATH, encoding="utf-8") as f:
        benchmark = json.load(f)

    cases = benchmark["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            logger.error("Case not found: %s", args.case)
            return

    laws_text = LAWS_PATH.read_text(encoding="utf-8") if LAWS_PATH.exists() else ""
    if not laws_text:
        logger.warning("laws_compact.txt not found at %s", LAWS_PATH)

    id_map = build_id_normalization_map()
    logger.info("ID normalization map: %d entries", len(id_map))

    client = None if args.dry_run else get_client()

    results = []
    for case in cases:
        logger.info("Running %s: %s", case["id"], case["label"])

        qa_text = format_qa_text(case["input"]["qa_pairs"])

        session_context = case["input"].get("session_context", "")

        if args.dry_run:
            actual_laws: list[dict] = []
            elapsed = 0.0
            raw = "{}"
        else:
            raw, elapsed = call_llm(client, args.model, qa_text, laws_text, session_context)  # type: ignore[arg-type]
            actual_laws = parse_related_laws(raw, id_map)
            logger.info("  -> %d laws tagged in %.1fs", len(actual_laws), elapsed)

        scores = evaluate_case(case, actual_laws)

        if args.verbose:
            print_verbose(case, actual_laws, scores)

        results.append({
            "case_id": case["id"],
            "case_label": case["label"],
            "model": args.model,
            "elapsed_s": round(elapsed, 1),
            "actual_laws": actual_laws,
            "scores": scores,
        })

    print_summary(results)

    # JSON で詳細結果を出力
    suffix = f"_{args.save_as}" if args.save_as else ""
    out_path = BENCH_DIR / f"benchmark_law_tagging_results{suffix}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info("Detailed results written to %s", out_path)


if __name__ == "__main__":
    main()
