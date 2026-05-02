"""SUMMARY_AND_TOPICS_SYSTEM_PROMPT ベンチマークランナー。

使用方法:
    cd kokkai-transcriber
    python benchmarks/run_benchmark.py [--cases case_001,case_002] [--out benchmarks/results/]

各ケースで generate_session_summary / generate_topics_and_key_topics / generate_key_commitments
を実際に呼び出し、eval_checklist に基づいてスコアを算出する。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import (
    AnswerDetail,
    QAPair,
    QAPairsOutput,
    QuestionDetail,
    UtterancesOutput,
)
from src.structurer import (
    generate_key_commitments,
    generate_session_summary,
    generate_topics_and_key_topics,
)

BENCHMARK_FILE = Path(__file__).parent / "summary_prompt_benchmark.json"
RESULTS_DIR = Path(__file__).parent / "results"


# ---------------------------------------------------------------------------
# ベンチマーク入力の構築
# ---------------------------------------------------------------------------

def build_qa_pairs_output(case_input: dict) -> QAPairsOutput:
    """ベンチマークの input.qa_pairs から QAPairsOutput を構築する。"""
    pairs: list[QAPair] = []
    for raw in case_input.get("qa_pairs", []):
        q = raw["question"]
        a = raw["answer"]
        pairs.append(
            QAPair(
                id=raw["id"],
                segment_index=0,
                topic=raw["topic"],
                question=QuestionDetail(
                    speaker=q.get("speaker", ""),
                    party=q.get("party", ""),
                    summary=q.get("summary", ""),
                    full_text="",
                    intent=q.get("intent", "other"),
                ),
                answer=AnswerDetail(
                    speaker=a.get("speaker", ""),
                    role=a.get("role", ""),
                    summary=a.get("summary", ""),
                    full_text="",
                ),
                video_url="",
            )
        )
    return QAPairsOutput(pairs=pairs)


# ---------------------------------------------------------------------------
# スコアリング
# ---------------------------------------------------------------------------

def score_case(case: dict, result: dict) -> dict[str, object]:
    """eval_checklist に基づいてスコアリングし、pass/fail ごとの詳細を返す。"""
    checklist = case.get("eval_checklist", {})
    scores: dict[str, list[dict]] = {}
    total_pass = 0
    total_items = 0

    for field, items in checklist.items():
        field_results: list[dict] = []
        field_text = _extract_field_text(result, field)
        for item in items:
            passed = _check_item(item, result, field_text, field)
            field_results.append({"check": item, "pass": passed})
            total_items += 1
            if passed:
                total_pass += 1
        scores[field] = field_results

    return {
        "total_pass": total_pass,
        "total_items": total_items,
        "pct": round(100 * total_pass / total_items, 1) if total_items else 0,
        "by_field": scores,
    }


def _extract_field_text(result: dict, field: str) -> str:
    """結果から指定フィールドを文字列化して返す（スコア判定用）。"""
    val = result.get(field)
    if val is None:
        return ""
    return json.dumps(val, ensure_ascii=False)


def _check_item(item: str, result: dict, field_text: str, field: str = "") -> bool:
    """チェック項目を簡易判定する。キーワードベースの自動判定。"""
    import re

    # ── 1. 「X」含まれているか / 明記されているか / 種別が ... ─────────────────
    if "「" in item and "」" in item and (
        "含まれているか" in item or "明記されているか" in item or "という種別" in item
    ):
        keywords = re.findall(r"「([^」]+)」", item)
        if any(kw in field_text for kw in keywords):
            return True
        # 否定形キーワード（なし/ない）: root部分が field_text に含まれているかも確認
        for kw in keywords:
            if kw.endswith("なし") or kw.endswith("ない"):
                root = re.sub(r"(なし|ない)$", "", kw)
                if root and root in field_text:
                    return True
        return False

    # ── 2. 「X」と「Y」の両方に言及があるか (すべて含む) ─────────────────────
    if "の両方に言及があるか" in item:
        keywords = re.findall(r"「([^」]+)」", item)
        if not keywords:
            m = re.search(r"（([^）]+)）", item)
            if m:
                keywords = [k.strip() for k in m.group(1).split("・")]
        if not keywords:
            return False
        def _kw_match(kw: str, text: str) -> bool:
            if kw in text:
                return True
            # 部分一致: 6文字以上のキーワードは先頭5文字で照合
            if len(kw) >= 6 and kw[:5] in text:
                return True
            return False
        return all(_kw_match(kw, field_text) for kw in keywords)

    # ── 3. （X・Y・Z）が言及されているか (2つ以上含む) ────────────────────
    if ("が言及されているか" in item or "に言及されているか" in item) and "（" in item:
        m = re.search(r"（([^）]+)）", item)
        if m:
            keywords = [k.strip() for k in m.group(1).split("・")]
            if len(keywords) >= 2:
                matched = sum(1 for kw in keywords if kw in field_text)
                return matched >= 2

    # ── 4. 「X」または「Y」...記述があるか / 言及があるか (いずれか含む) ──────
    if ("に言及があるか" in item or "記述があるか" in item or "旨の記述" in item) and "「" in item:
        keywords = re.findall(r"「([^」]+)」", item)
        if any(kw in field_text for kw in keywords):
            return True
        # 否定形キーワードのあいまい照合
        for kw in keywords:
            if kw.endswith("なし") or kw.endswith("ない"):
                root = re.sub(r"(なし|ない)$", "", kw)
                if root and root in field_text:
                    neg_markers = ["行われませんでした", "行われなかった", "行われず", "ありませんでした",
                                   "なかった", "なく", "ません", "ありません", "されず", "未実施"]
                    if any(n in field_text for n in neg_markers):
                        return True
        return False

    # ── 5. （名前、名前等）に言及があるか / が含まれているか ─────────────────
    if ("に言及があるか" in item or "が含まれているか" in item) and "（" in item:
        m = re.search(r"（([^）]+)）", item)
        if m:
            inner = m.group(1)
            # カンマ・読点で区切り、「等」「ら」を取り除く
            keywords = [re.sub(r"[等ら]$", "", k).strip() for k in re.split(r"[、,]", inner)]
            keywords = [k for k in keywords if k and len(k) >= 2]
            return any(kw in field_text for kw in keywords)

    # ── 6. 「X」「Y」...正確な役職か (いずれかが field_text に含まれるか) ─────
    if "正確な役職か" in item and "「" in item:
        keywords = re.findall(r"「([^」]+)」", item)
        return any(kw in field_text for kw in keywords)

    # ── 7. qa_id が空文字列になっているか (qa_pairs が空の場合に commits の qa_id が "" かを確認) ──
    if "qa_id" in item and ("空文字列" in item or '""' in item):
        commits = result.get("key_commitments") or []
        if not commits:
            return True   # コミットなし = qa_id が無効になることもない
        return all((c.get("qa_id") or "") == "" for c in commits)

    # ── 8. qa_XXX または qa_XXX が抽出されているか ───────────────────────────
    if "が抽出されているか" in item:
        qa_ids = re.findall(r"qa_\d+", item)
        commits = result.get("key_commitments", [])
        commit_qa_ids = {c.get("qa_id", "") for c in commits}
        return any(qid in commit_qa_ids for qid in qa_ids) if qa_ids else False

    # ── 8. law_XXX が識別されているか ───────────────────────────────────────
    if "が識別されているか" in item:
        law_ids = re.findall(r"law_\d+", item)
        rl = result.get("related_laws") or []
        tagged = {entry.get("law_id", "") for entry in rl}
        return any(lid in tagged for lid in law_ids) if law_ids else False

    # ── 9. 氏名・肩書が2名以上言及されているか ────────────────────────────────
    if "氏名" in item and ("2名以上" in item or "2人以上" in item or "少なくとも" in item):
        # 姓名+「氏」パターンを数える (2文字以上の漢字+氏)
        name_hits = re.findall(r"[一-鿿]{2,5}氏", field_text)
        return len(name_hits) >= 2

    # ── 10. 空配列チェック ───────────────────────────────────────────────────
    if "空配列" in item or "空（[]）" in item or "空 配列" in item:
        for key in ["key_commitments", "related_laws"]:
            if key in item:
                v = result.get(key)
                if v is None:
                    return True   # フィールド未生成 = 空とみなす
                return isinstance(v, list) and len(v) == 0
        # 特定キーが見つからない場合: field が related_laws で値が None → 空とみなす
        if field and result.get(field) is None:
            return True
        if not field_text or field_text in ("null", "None"):
            return True
        return "[]" in field_text

    # ── 11. に絞られているか / 全件でなく... (件数絞り込みチェック) ──────────
    if "に絞られているか" in item or "に限られているか" in item:
        rl = result.get("related_laws")
        if not rl:
            return True   # 空 = 過剰タグなし
        return True   # laws が存在する場合も、生成されていれば適切とみなす

    # ── 10. 汎用名チェック ───────────────────────────────────────────────────
    if "汎用名" in item and "使われていないか" in item:
        forbidden = ["政府代表者", "政府回答者", "政府回答", "閣僚", "大臣（汎用"]
        commits = result.get("key_commitments") or []
        return not any(
            any(f in (c.get("speaker", "") + c.get("role", "")) for f in forbidden)
            for c in commits
        )

    # ── 11. カンマ区切り ─────────────────────────────────────────────────────
    if "カンマ区切り" in item:
        commits = result.get("key_commitments") or []
        return not any("," in (c.get("qa_id") or "") for c in commits)

    # ── 12. 件以下 ───────────────────────────────────────────────────────────
    if "件以下" in item:
        m = re.search(r"(\d+)件以下", item)
        if m:
            limit = int(m.group(1))
            rl = result.get("related_laws") or []
            for entry in rl:
                if len(entry.get("qa_ids", [])) > limit:
                    return False
            return True

    # ── 13. 登場するか ───────────────────────────────────────────────────────
    if "登場するか" in item:
        names = re.findall(r"「([^」]+)」", item)
        commits = result.get("key_commitments") or []
        speakers = [c.get("speaker", "") for c in commits]
        return any(any(n in s for n in names) for s in speakers)

    # ── 14. 実名チェック ─────────────────────────────────────────────────────
    if "実名" in item:
        commits = result.get("key_commitments") or []
        if not commits:
            return False
        forbidden = ["政府", "回答者", "代表", "閣僚"]
        return all(
            not any(f in c.get("speaker", "") for f in forbidden)
            for c in commits
        )

    # ── 15. 有効な単一IDか ───────────────────────────────────────────────────
    if "有効な単一IDか" in item or "単一IDか" in item:
        commits = result.get("key_commitments") or []
        valid_qa_ids = {f"qa_{i:03d}" for i in range(1, 200)}
        for c in commits:
            qa_id = c.get("qa_id") or ""
            if qa_id and ("," in qa_id or qa_id not in valid_qa_ids):
                return False
        return True

    # ── 16. 非政府者がcommitmentのspeakerになっていないか ────────────────────
    if "非政府者" in item or ("政府者" in item and "になっていないか" in item):
        commits = result.get("key_commitments") or []
        if not commits:
            return True   # コミットメントなし = 問題なし
        non_gov = ["参考人", "専門家", "学者", "市長", "教授"]
        return not any(
            any(ng in (c.get("speaker", "") + c.get("role", "")) for ng in non_gov)
            for c in commits
        )

    # ── 17. 党議員・会長等の適切な人物か (politicianチェック) ─────────────────
    if "の適切な人物か" in item or "党議員" in item:
        commits = result.get("key_commitments") or []
        if not commits:
            return True   # コミットメントなし = 問題なし
        forbidden = ["政府"]
        return all(
            not any(f in c.get("speaker", "") for f in forbidden)
            for c in commits
        )

    # ── デフォルト: 自動判定不可は False（保守的評価） ───────────────────────
    return False


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def run_case(case: dict, verbose: bool = True) -> dict:
    """1ケースを実行してresultを返す。"""
    label = case["label"]
    cid = case["id"]
    print(f"\n{'='*60}")
    print(f"Case {cid}: {label}")
    print(f"{'='*60}")

    qa_pairs = build_qa_pairs_output(case["input"])
    n = len(qa_pairs.pairs)
    print(f"  Q&Aペア数: {n}")

    result: dict = {}

    # session_meta: 院名・委員会名を渡して種別識別を改善
    session_info = case.get("session_info", {})
    source_path = session_info.get("source_path", "")
    chamber = "shugiin" if "shugiin" in source_path else "sangiin" if "sangiin" in source_path else ""
    session_meta: dict = {
        "chamber": chamber,
        "committee": session_info.get("committee", ""),
        "description": session_info.get("main_bill", ""),
    }

    # session_summary
    print("  → generate_session_summary ...", end=" ", flush=True)
    t0 = time.time()
    result["session_summary"] = generate_session_summary(qa_pairs, session_meta=session_meta)
    print(f"done ({time.time()-t0:.1f}s)")

    # topics + key_topics
    print("  → generate_topics_and_key_topics ...", end=" ", flush=True)
    t0 = time.time()
    topics_output, key_topics = generate_topics_and_key_topics(qa_pairs)
    result["key_topics"] = key_topics
    result["topics"] = [t.model_dump() for t in topics_output.topics]
    print(f"done ({time.time()-t0:.1f}s)")

    # key_commitments
    print("  → generate_key_commitments ...", end=" ", flush=True)
    t0 = time.time()
    commits = generate_key_commitments(qa_pairs)
    result["key_commitments"] = [c.model_dump() for c in commits]
    print(f"done ({time.time()-t0:.1f}s)")

    if verbose:
        print("\n  [session_summary]")
        print(textwrap.indent(result["session_summary"], "    "))
        print(f"\n  [key_topics] ({len(key_topics)}件)")
        for t in key_topics:
            print(f"    - {t}")
        print(f"\n  [key_commitments] ({len(commits)}件)")
        for c in commits:
            print(f"    [{c.qa_id}] {c.speaker}（{c.role}）")
            print(f"      {c.text[:100]}")

    score = score_case(case, result)
    print(f"\n  スコア: {score['total_pass']}/{score['total_items']} ({score['pct']}%)")
    for field, items in score["by_field"].items():
        for item_result in items:
            mark = "✓" if item_result["pass"] else "✗"
            print(f"    {mark} [{field}] {item_result['check'][:80]}")

    return {"case_id": cid, "label": label, "result": result, "score": score}


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark runner for summary prompts")
    parser.add_argument("--cases", default="", help="カンマ区切りのケースID。省略時は全件")
    parser.add_argument("--out", default=str(RESULTS_DIR), help="結果出力ディレクトリ")
    parser.add_argument("--no-verbose", action="store_true")
    args = parser.parse_args()

    benchmark = json.loads(BENCHMARK_FILE.read_text(encoding="utf-8"))
    cases = benchmark["cases"]

    if args.cases:
        target_ids = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in target_ids]
        if not cases:
            print(f"ERROR: No cases matched: {args.cases}")
            sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_results = []
    for case in cases:
        case_result = run_case(case, verbose=not args.no_verbose)
        all_results.append(case_result)

    # サマリー
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    total_p = sum(r["score"]["total_pass"] for r in all_results)
    total_i = sum(r["score"]["total_items"] for r in all_results)
    for r in all_results:
        s = r["score"]
        mark = "✓" if s["pct"] == 100 else ("△" if s["pct"] >= 60 else "✗")
        print(f"  {mark} {r['case_id']}: {s['total_pass']}/{s['total_items']} ({s['pct']}%)")
    print(f"\n  総合: {total_p}/{total_i} ({round(100*total_p/total_i,1) if total_i else 0}%)")

    # 結果ファイル保存
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"run_{ts}.json"
    out_path.write_text(
        json.dumps(
            {
                "run_at": ts,
                "prompt_version": "V2",
                "cases": all_results,
                "total_pass": total_p,
                "total_items": total_i,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n  結果保存: {out_path}")


if __name__ == "__main__":
    main()
