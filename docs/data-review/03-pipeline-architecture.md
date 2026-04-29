# 03. パイプライン設計（責務の漏れと過密）

## 3.1 現在のステップ責務マップ

```
[Step 1-2] スクレイピング
    ↓ metadata.json (speakers, hls_url)
[Step 3] ffmpeg HLS → WAV → silence-detect → セグメント分割
    ↓ tmpdir/segments/*.wav
[Step 4] Whisper × N並列
    ↓ in-memory RawTranscript
[Step 4.5] DeepSeek 句読点・固有名詞修正（チャンク並列）
    ↓ raw_transcript.json
[Step 5] DeepSeek 話者交代検出
    ↓ utterances.json
[Step 6a] Gemma Q&A ペア生成（セグメント並列）
    ↓ qa_pairs.json
[Step 6b] Gemma 要約・トピック・コミットメント・関連法案（一括）
    ↓ summary.json + topics.json
```

良いところと悪いところを段階ごとに整理する。

## 3.2 責務が「漏れている」箇所

### A. 「セッション種別の判定」がどのステップにも無い

[02-cross-cutting-issues.md §2.1](02-cross-cutting-issues.md#21-セッション種別が一級概念になっていない) の通り、
本会議でも委員会でも全く同じパイプラインが走る。
`metadata.json` を読み解けば「趣旨説明」「討論」「採決」「質疑」のいずれかは推定できるはずだが、
そのロジックがどこにも無い。**Step 2.5（仮称: セッション種別タグ付け）を新設すべき**。

### B. 「発言者名の正規化」がどのステップにも無い

[08-name-normalization.md](08-name-normalization.md) で詳述。`metadata.json` の `speakers[].name`
が ground truth として確定しているのに、Step 4.5 / 5 / 6 はそれぞれ独自に LLM に名前を
出力させている。結果として `高市早苗` / `高市内閣総理大臣` / `高市総理大臣` が並走する。
**Step 5.5（仮称: 名前正規化）を speaker_tagger と structurer の間に挟むべき**。

### C. 「セッション間整合性のバリデーション」がどのステップにも無い

- 同じ大臣がセッションをまたぐと別の役職表記になる
- `key_topics` と `topics.name` が同じ session 内でも違う語彙
- `related_qa_ids` で参照される qa_id が実在しないケースが起きうる（54 トピックで空配列）

これらを検出する **Step 7（仮称: 整合性チェック）** を入れるべき。検出しても自動修正は難しいので、
バッチ実行後にレポートを出して人間にレビューを促す程度で良い。

### D. 「単一セグメント内に複数質疑者が居るパターン」の検出が不完全

`structurer.py:_split_segment_into_blocks`（299-396）が委員長指名を境界にブロック分割するが、
正規表現 `_CHAIR_NOMINATION_RE = r"^(?:次に)?(.+?)[君さ](?:ん)?[。.]?\s*$"` は短い指名
（「〇〇君。」）しか拾わない。実際の本会議では：

- 「議長:」のような呼びかけ
- 「速記をやめてください」の議事整理
- 「これにて質疑を終局いたします」の議事進行

など、議事進行発言は色々ある。これらを「質疑者ブロックの境界」として正しく扱えていない。
詳細は [05-speaker-tagging.md](05-speaker-tagging.md)。

## 3.3 責務が「過密」になっている箇所

### A. Step 6b（structurer の summary+topics 統合）

[02-cross-cutting-issues.md §2.6](02-cross-cutting-issues.md#26-構造化-llm-呼び出しの-全部入り-json-が事故源) の通り、
1 つの LLM 呼び出しに 5 種の出力を要求している。出力 JSON 設計の一般則として：

> **「並列に存在する複数の構造体」を 1 リクエストで返させると、後段が落ちる**。
> 入力が共通でも、出力ごとに呼び出しを分けるのが安全。

これは Gemma に限らず GPT/Claude/Gemini いずれでも観測される現象。
DeepSeek-V3.2 でもベンチマーク（`benchmark2.log`）で同様の歪みが見える。

### B. Step 4.5（校正）の「同音異義語修正」が広すぎる

`transcript_corrector.py:42-113` の SYSTEM_PROMPT は校正タスクとして 5 種類を要求：

1. 句読点の補完
2. 固有名詞の修正
3. **同音異義語の修正**（例: 「介護保険」→「国民皆保険」）
4. フィラー除去
5. 改行整形

このうち 3. が **意味理解を要するタスク**で、他の 4 種は表層的な編集タスク。
1 つのプロンプトに混ぜると LLM の出力スタイルが乱れやすい。

実際 `benchmark2.log:11` を見ると：

```
[gpt-oss-120b] OUT: ...日本は国民の皆様のご理解のもと、介護保険制度によって...
[gemma-4-31B-it] OUT: ...日本は国民の皆様のご理解のもと、介護保険制度によって...
[DeepSeek-V3.2] OUT: ...日本は、国民の皆様のご理解のもと、介護保険制度によって...
```

3 モデルとも **「介護保険制度」を残してしまった**。プロンプトの例で `介護保険 → 国民皆保険` を
明示しているのに、それでも修正できない。これは「文脈を読んで意味を変える」タスクの難しさ。

実装的には、Step 4.5 を 2 段階にするのが筋：

- **Step 4.5a**: 句読点・改行・フィラー除去（決定論的・言語表層編集）
- **Step 4.5b**: 固有名詞・同音異義語修正（意味理解、より強いモデル）

### C. Step 6a（Q&A 抽出）の「リトライ密度判定」がノイズを生む

`structurer.py:531-571` の QA 密度チェック：

```python
if total_chars >= 2000:
    density = len(pairs) / (total_chars / 1000)
    if density < 0.5:
        retry  # temperature 0.3 で再試行
```

セッションが長い演説（討論、所信表明）の場合 **「Q&A 密度が低い」のは正しい**のに、
本パイプラインは「ペアが少ない＝LLM 失敗」と判定して再試行する。
結果として LLM は無理にペアを増やそうとして空答弁ペアを乱発する。

これは [02-cross-cutting-issues.md §2.4](02-cross-cutting-issues.md#24-答弁が無いものを-qa-ペアにしてしまう失敗の連鎖) の根本原因の一部。

## 3.4 「冪等でない」副作用

### Step 4.5 のチャンク棄却が確率的

`transcript_corrector.py:303-318`：

```python
if "……" in corrected_text:
    corrected_text = chunk_obj.text  # 棄却
ratio = corrected_len / original_len if original_len > 0 else 1.0
if ratio < 0.8:
    corrected_text = chunk_obj.text  # 棄却
```

棄却が起きると `corrected=true` のフラグが立ちつつも、内部に未補正のテキストが
混在する状態になる。これは **観測しづらい部分的失敗**で、再実行しないと直らない。

### Step 6a のリトライが temperature 違いで非決定的

`structurer.py:552`:

```python
temperature=0.3,  # リトライ時はやや高めで多様性を出す
```

リトライ結果は確率的なので、同じセッションをもう一度処理しても出力が変わる可能性がある。
`data/` を「真実のソース」として運用する以上、決定性は重要。

## 3.5 並列度の考え方

| ステップ | 並列度 | 内容 | 適切か |
|---------|-------|------|--------|
| Step 3 | 4 (`MAX_WORKERS_AUDIO`) | ffmpeg subprocess | OK（fd 重い）|
| Step 4 | 16 (`MAX_WORKERS_WHISPER`) | Whisper API | OK |
| Step 4.5 | 80 (`MAX_WORKERS_LLM`) | DeepSeek チャンク | やや多い（rate limit リスク） |
| Step 5 | 80 | DeepSeek セグメント | 同上 |
| Step 6a | 80 | Gemma セグメント | 同上 |

`with_retry`（`api_client.py:55-99`）が 429 に対して 6 回までリトライするので
レート制限自体は捌けるが、80 並列はセッション 1 件に対して過剰。
1 セッションあたり 30〜50 セグメントしかないので、20 並列でも所要時間は変わらない。
むしろ並列度を下げて DeepInfra のレート制限ヘッダを尊重する方が安定する。

## 3.6 「処理失敗の境界」の不明確さ

`pipeline.py:107-119` の Step 2 失敗ハンドリング：

```python
except SessionNotReadyError:
    raise
except Exception as e:
    raise RuntimeError(f"Step 2 (scraping) failed: {e}") from e
```

Step 4.5 だけは `non-fatal` で進める：

```python
except Exception as e:
    logger.warning("Transcript correction failed (non-fatal, using original): %s", e)
```

Step 4.5 を non-fatal にしているのは妥当（校正失敗 → 未校正テキストで進める）。
ただし `corrected=False` のままで `qa_pairs.json` まで出力されるので、
**サイト側からはどのセッションが校正失敗したか分からない**。`metadata.json` か
`raw_transcript.json` に `correction_status: "succeeded"|"partial"|"failed"`
のような明示フィールドがあると、サイト側で警告表示できる。

## 改善案サマリー

- [ ] **[P0]** Step 2.5（セッション種別タグ付け）を新設
- [ ] **[P0]** Step 6b を 3 個の LLM 呼び出しに分割
- [ ] **[P1]** Step 5.5（発言者名正規化）を新設
- [ ] **[P1]** Step 4.5 を 2 段階（表層編集 / 意味補正）に
- [ ] **[P1]** Step 6a の密度リトライをセッション種別に応じて無効化
- [ ] **[P2]** Step 7（整合性チェック）を新設、CI でレポート
- [ ] **[P2]** 校正・LLM 呼び出しの `status` を `metadata.json` に明示
- [ ] **[P2]** LLM 並列度を 80 → 20 に下げて安定性向上
