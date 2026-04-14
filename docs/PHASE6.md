# Phase 6: BYOK + 高度機能 — 実装・テスト計画

> **目標**: OpenRouter APIキーによるBYOK（Bring Your Own Key）レイヤーを構築し、ブラウザ上でLLMを活用したインタラクティブ分析機能群を提供する。加えて発言者ネットワーク可視化、政党別分析、自然言語クエリ、Google Sheets連携、過去セッション遡及処理を実装する。
> **所要期間**: 継続的（機能単位で段階リリース）
> **前提**: Phase 1〜5 が完了済み。Astroサイト・ダッシュボード・フィルタ・エクスポート機能が動作していること。`data/` 配下に複数セッションのJSONが存在すること。

---

## 成果物

Phase 6 完了時に以下が揃う:

1. `/settings` ページにOpenRouterキー入力UI・モデルセレクタ
2. `site/src/lib/openrouter.js` — OpenRouterクライアント（SSEストリーミング対応）
3. `BYOKGate.jsx` — キー未入力時はTier 0表示、入力後にTier 1機能をアンロック
4. Tier 1分析コンポーネント群（答弁比較、回避度分析、フォローアップ提案、SNS生成、政策ブリーフ、自然言語クエリ）
5. `StreamingAnalysis.jsx` — SSEストリーミング表示の共通コンポーネント
6. D3発言者ネットワーク可視化（`/dashboard/speakers`）
7. 政党別分析ビュー（両院横断の名寄せ対応）
8. Google Sheets API直接連携（ワンクリックエクスポート）
9. 過去セッション遡及処理スクリプト（kokkai-transcriber側）

---

## 前提知識: アーキテクチャ上の制約

ジュニア開発者向けに、Phase 6 の実装で特に注意すべきアーキテクチャ上の制約をまとめる。

### 静的サイト完結（NF-01）
- **サーバーサイドプロセスなし**。すべてのLLM呼び出しはブラウザから直接 OpenRouter API へ送信する
- Astro は `output: 'static'` で運用。SSRモードは使用しない
- APIエンドポイントは `site/public/api/*.json` として静的ファイルで提供

### APIキーのセキュリティ（NF-05）
- APIキーは **`sessionStorage` のみ** に保持。`localStorage` は禁止
- タブを閉じたらキーは消去される。これは仕様
- キーをサーバーに送信するコードを絶対に書かない
- OpenRouter API への直接リクエスト以外にキーを含めない

### React島パターン
- インタラクティブ部分のみ React コンポーネント化し、`client:load` または `client:visible` でハイドレーション
- Astroコンポーネント（`.astro`）にサーバーサイドロジックは不要
- チャートは Recharts、ネットワーク図は D3

### 出所明示（NF-06 / 著作権法第48条）
- Tier 1 の分析結果表示にも、元データの `source_url` へのリンクを必ず含める

---

## ステップ一覧

| # | ステップ | 依存 | 難易度 |
|---|---------|------|--------|
| 1 | OpenRouterクライアント実装 | なし | ★☆☆ |
| 2 | 設定ページ（キー入力 + モデルセレクタ） | Step 1 | ★☆☆ |
| 3 | BYOKGateコンポーネント | Step 2 | ★☆☆ |
| 4 | StreamingAnalysis共通コンポーネント | Step 1 | ★★☆ |
| 5 | 答弁比較分析 | Step 3, 4 | ★★☆ |
| 6 | 回避答弁ディテクター | Step 3, 4 | ★★☆ |
| 7 | フォローアップ質問提案 | Step 3, 4 | ★★☆ |
| 8 | SNS投稿生成 | Step 3, 4 | ★☆☆ |
| 9 | 政策ブリーフ生成 | Step 3, 4 | ★★☆ |
| 10 | 自然言語クエリ | Step 3, 4 | ★★★ |
| 11 | 発言者ネットワーク（D3） | なし | ★★★ |
| 12 | 政党別分析（両院名寄せ） | なし | ★★☆ |
| 13 | Google Sheets API連携 | なし | ★★☆ |
| 14 | 過去セッション遡及処理 | なし | ★★☆ |

**並行実施可能**: Step 11〜14 は Step 1〜10 と独立して進められる。

---

## Step 1: OpenRouterクライアント実装

**ファイル:** `site/src/lib/openrouter.js`

**やること:**
- ARCH.md セクション7.3 に準拠した `OpenRouterClient` クラスを実装
- SSEストリーミング対応（`ReadableStream` の逐次読み取り）
- 非ストリーミングモードも用意（短い応答向け）
- エラーハンドリング: 401（キー無効）、429（レート制限）、500系を適切に処理
- キーの保存・読み出しは `sessionStorage` 経由のヘルパー関数として同ファイルに配置

**実装詳細:**

```javascript
// site/src/lib/openrouter.js

const STORAGE_KEY = "openrouter_api_key";
const MODEL_KEY = "openrouter_model";
const DEFAULT_MODEL = "deepseek/deepseek-v3.2";

export function getApiKey() {
  return sessionStorage.getItem(STORAGE_KEY);
}

export function setApiKey(key) {
  sessionStorage.setItem(STORAGE_KEY, key);
}

export function clearApiKey() {
  sessionStorage.removeItem(STORAGE_KEY);
}

export function getModel() {
  return sessionStorage.getItem(MODEL_KEY) || DEFAULT_MODEL;
}

export function setModel(model) {
  sessionStorage.setItem(MODEL_KEY, model);
}

export class OpenRouterClient {
  constructor(apiKey) {
    this.apiKey = apiKey;
    this.baseUrl = "https://openrouter.ai/api/v1";
  }

  // SSEストリーミング — ReadableStreamを返す
  async chatStream(messages, options = {}) {
    const response = await fetch(`${this.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
        "HTTP-Referer": window.location.origin,
        "X-Title": "国会議事録DB"
      },
      body: JSON.stringify({
        model: options.model || getModel(),
        messages,
        stream: true,
        max_tokens: options.maxTokens || 4096,
        temperature: options.temperature || 0.3
      })
    });

    if (!response.ok) {
      const errorBody = await response.text();
      throw new OpenRouterError(response.status, errorBody);
    }

    return response.body;
  }

  // 非ストリーミング — 完全なレスポンスを返す
  async chat(messages, options = {}) {
    const response = await fetch(`${this.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
        "HTTP-Referer": window.location.origin,
        "X-Title": "国会議事録DB"
      },
      body: JSON.stringify({
        model: options.model || getModel(),
        messages,
        stream: false,
        max_tokens: options.maxTokens || 4096,
        temperature: options.temperature || 0.3
      })
    });

    if (!response.ok) {
      const errorBody = await response.text();
      throw new OpenRouterError(response.status, errorBody);
    }

    const data = await response.json();
    return data.choices[0].message.content;
  }
}

export class OpenRouterError extends Error {
  constructor(status, body) {
    super(`OpenRouter API error ${status}: ${body}`);
    this.status = status;
    this.body = body;
  }

  get isUnauthorized() { return this.status === 401; }
  get isRateLimited() { return this.status === 429; }
}
```

**テスト:**
- ブラウザのDevToolsコンソールで `new OpenRouterClient("test").chat(...)` を呼び、401エラーが正しくスローされることを確認
- 有効なキーで `chatStream` を呼び、SSEチャンクが逐次到着することを確認
- `getApiKey()` / `setApiKey()` / `clearApiKey()` が `sessionStorage` を正しく操作することを確認
- タブを閉じて再度開いた時に `getApiKey()` が `null` を返すことを確認

---

## Step 2: 設定ページ（キー入力 + モデルセレクタ）

**ファイル:**
- `site/src/pages/settings.astro`
- `site/src/components/SettingsPanel.jsx`（React島）

**やること:**
- `/settings` ページにAPIキー入力フォームとモデルセレクタを配置
- キーのバリデーション（OpenRouter API `/auth/key` エンドポイントで残高確認）
- モデル一覧は静的に定義（ARCH.md セクション7.4 の推奨モデル + その他）

**SettingsPanel.jsx の実装仕様:**

```
┌─────────────────────────────────────────┐
│ 設定                                     │
├─────────────────────────────────────────┤
│                                          │
│ OpenRouter APIキー                       │
│ ┌────────────────────────┐ [検証] [削除] │
│ │ sk-or-v1-●●●●●●●●●●   │              │
│ └────────────────────────┘              │
│ ✅ キー有効 — 残高: $12.34              │
│                                          │
│ ⚠️ キーはこのタブのsessionStorageにのみ  │
│   保存されます。タブを閉じると消去されます│
│                                          │
│ 分析モデル                               │
│ ┌────────────────────────────────┐      │
│ │ DeepSeek V3.2 (コスト優先)    ▼  │      │
│ └────────────────────────────────┘      │
│                                          │
│ モデル説明:                              │
│ 安価で構造化出力が得意。SNS生成・要約向き│
└─────────────────────────────────────────┘
```

**モデル選択肢（静的定義）:**

| 表示名 | モデルID | 用途の目安 |
|--------|---------|-----------|
| DeepSeek V3.2（コスト優先） | `deepseek/deepseek-v3.2` | SNS生成、要約、自然言語クエリ |
| Claude Sonnet | `anthropic/claude-sonnet-4-20250514` | ニュアンス分析、答弁比較 |
| GPT-4o | `openai/gpt-4o` | 汎用分析 |
| Gemini 2.5 Flash | `google/gemini-2.5-flash-preview` | 高速・低コスト |

**キー検証フロー:**
1. ユーザーがキーを入力して「検証」をクリック
2. `GET https://openrouter.ai/api/v1/auth/key` を `Authorization: Bearer {key}` で呼び出し
3. 成功: 残高を表示、キーを `sessionStorage` に保存
4. 401: エラーメッセージ「APIキーが無効です」を表示

**テスト:**
- キー未入力時に「削除」ボタンが非活性であること
- 無効なキーで「検証」→ エラーメッセージが表示されること
- 有効なキーで「検証」→ 残高表示 + `sessionStorage` に保存されること
- モデル選択を変更 → `sessionStorage` に保存されること
- ブラウザ開発サーバーで `/settings` にアクセスし、レイアウトが崩れないこと

---

## Step 3: BYOKGateコンポーネント

**ファイル:** `site/src/components/BYOKGate.jsx`

**やること:**
- Tier 0 / Tier 1 の表示切り替えを行うラッパーコンポーネント
- `sessionStorage` にキーがなければ「APIキーを設定するとこの機能が使えます」のプロンプトを表示
- キーがあれば子コンポーネント（Tier 1機能）をレンダリング

**実装仕様:**

```jsx
import { useState, useEffect } from "react";
import { getApiKey } from "../lib/openrouter.js";

export default function BYOKGate({ children, featureName }) {
  const [hasKey, setHasKey] = useState(false);

  useEffect(() => {
    setHasKey(!!getApiKey());

    // settings ページでキーが保存された場合に対応
    const handleStorage = () => setHasKey(!!getApiKey());
    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, []);

  if (!hasKey) {
    return (
      <div className="byok-gate">
        <div className="byok-gate__icon">🔑</div>
        <p className="byok-gate__title">
          {featureName}にはOpenRouter APIキーが必要です
        </p>
        <p className="byok-gate__description">
          <a href="/settings">設定ページ</a>でAPIキーを入力すると、
          この機能がアンロックされます。
        </p>
        <p className="byok-gate__note">
          キーはブラウザのsessionStorageにのみ保存され、
          サーバーには送信されません。
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
```

**注意点:**
- `storage` イベントは同一タブ内では発火しない（他のタブでの変更のみ）。同一タブ内での反映には、設定ページからの遷移後のリロードまたはカスタムイベントが必要
- 解決策: `BYOKGate` 内で `focus` イベントでも `getApiKey()` を再チェックする

```jsx
useEffect(() => {
  const check = () => setHasKey(!!getApiKey());
  check();
  window.addEventListener("storage", check);
  window.addEventListener("focus", check);
  return () => {
    window.removeEventListener("storage", check);
    window.removeEventListener("focus", check);
  };
}, []);
```

**テスト:**
- `sessionStorage` にキーなし → ゲート表示（設定リンクあり）
- `sessionStorage` にキーあり → 子コンポーネントが表示
- 別タブで設定ページからキー保存 → 元タブにフォーカス戻すとアンロック
- `/settings` リンクが正しく遷移すること

---

## Step 4: StreamingAnalysis共通コンポーネント

**ファイル:** `site/src/components/StreamingAnalysis.jsx`

**やること:**
- SSEストリーミングレスポンスを逐次表示する共通コンポーネント
- Step 5〜10 の全Tier 1機能で再利用する
- 状態: `idle` → `loading` → `streaming` → `done` / `error`
- Markdownレンダリング対応（LLMの出力はMarkdownが多い）

**実装仕様:**

```jsx
import { useState, useCallback } from "react";
import { OpenRouterClient, getApiKey, OpenRouterError } from "../lib/openrouter.js";

export default function StreamingAnalysis({
  buildMessages,   // () => messages[] — プロンプトを組み立てる関数
  buttonLabel,      // 「分析開始」等
  options = {},     // model, maxTokens, temperature のオーバーライド
}) {
  const [status, setStatus] = useState("idle"); // idle | loading | streaming | done | error
  const [content, setContent] = useState("");
  const [error, setError] = useState(null);

  const run = useCallback(async () => {
    const apiKey = getApiKey();
    if (!apiKey) return;

    setStatus("loading");
    setContent("");
    setError(null);

    try {
      const client = new OpenRouterClient(apiKey);
      const stream = await client.chatStream(buildMessages(), options);
      setStatus("streaming");

      const reader = stream.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop(); // 未完了の行を保持

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6);
          if (data === "[DONE]") continue;

          try {
            const parsed = JSON.parse(data);
            const delta = parsed.choices?.[0]?.delta?.content;
            if (delta) {
              setContent(prev => prev + delta);
            }
          } catch {
            // JSONパース失敗は無視（不完全なチャンク）
          }
        }
      }

      setStatus("done");
    } catch (err) {
      setError(err instanceof OpenRouterError
        ? err.isUnauthorized ? "APIキーが無効です。設定を確認してください。"
        : err.isRateLimited ? "レート制限に達しました。しばらく待ってからお試しください。"
        : `APIエラー: ${err.message}`
        : `エラー: ${err.message}`
      );
      setStatus("error");
    }
  }, [buildMessages, options]);

  return (
    <div className="streaming-analysis">
      <button
        onClick={run}
        disabled={status === "loading" || status === "streaming"}
        className="streaming-analysis__button"
      >
        {status === "loading" ? "準備中..." :
         status === "streaming" ? "分析中..." :
         buttonLabel}
      </button>

      {error && (
        <div className="streaming-analysis__error">{error}</div>
      )}

      {content && (
        <div className="streaming-analysis__content">
          {/* Markdownレンダリング — react-markdownを使用 */}
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}
```

**依存パッケージ追加:**
```bash
cd site && npm install react-markdown
```

**テスト:**
- ボタンクリック → ローディング状態 → ストリーミング中にテキストが逐次表示されること
- ストリーミング中にボタンが非活性になること
- 完了後に再度ボタンが有効になること
- 無効なキーで実行 → エラーメッセージ表示
- ネットワーク切断時のエラーハンドリング
- Markdownの見出し・リスト・太字が正しくレンダリングされること

---

## Step 5: 答弁比較分析

**ファイル:** `site/src/components/AnswerComparison.jsx`

**機能要件:** F-25（同一大臣×同一テーマの答弁を時系列で比較分析する）

**配置場所:** セッション詳細ページのQ&Aカード内、またはダッシュボードの答弁回避度トラッカーから

**やること:**
- 選択されたQ&Aペアの答弁者+トピックで、`/api/index.json` から同一答弁者×類似トピックのQ&Aペアを検索
- 検索結果とともにLLMに分析を依頼
- ストリーミングで結果を表示

**プロンプト設計:**

```
あなたは国会答弁の比較分析の専門家です。

以下の答弁を時系列で比較し、以下の観点で分析してください:
1. 答弁内容の変化（具体性の増減、トーンの変化）
2. 矛盾する発言があればその箇所
3. 約束事項の進展状況
4. 総合評価

## 対象答弁

### {date1} {committee1}
質問者: {questioner1}
質問: {question1}
答弁: {answer1}

### {date2} {committee2}
...（同様に列挙）

日本語で回答してください。
```

**データフロー:**

```
1. ユーザーがQ&Aカードの「答弁比較」ボタンをクリック
2. /api/index.json から同一答弁者の全Q&Aペアを取得
3. トピック類似度で絞り込み（クライアントサイドのキーワードマッチ）
4. 該当Q&Aペア群をプロンプトに埋め込み
5. OpenRouter API にSSEリクエスト
6. StreamingAnalysis で逐次表示
7. 各Q&Aペアの source_url リンクを結果下部に表示
```

**UI:**

```
┌──────────────────────────────────────────┐
│ 🔍 答弁比較: 上野賢一郎 × 高額療養費     │
├──────────────────────────────────────────┤
│ 比較対象: 3件の答弁が見つかりました       │
│ ☑ 2026-04-09 本会議 (古川あおい)         │
│ ☑ 2026-04-15 厚生労働委 (佐藤太郎)       │
│ ☑ 2026-04-22 厚生労働委 (鈴木花子)       │
│                                          │
│ [比較分析を実行]                          │
│                                          │
│ ── 分析結果（ストリーミング）──            │
│ ## 答弁内容の変化                         │
│ 4月9日の本会議では「検討課題として位置... │
│ ██████████░░░░░░ 分析中...               │
│                                          │
│ 📎 出典:                                 │
│ • 衆議院TV 2026-04-09 本会議              │
│ • 衆議院TV 2026-04-15 厚生労働委員会      │
└──────────────────────────────────────────┘
```

**テスト:**
- 同一答弁者×同一トピックのQ&Aが2件以上存在する場合に比較ボタンが有効になること
- 1件しかない場合は「比較対象が見つかりません」と表示
- チェックボックスで比較対象を選択/解除できること
- 分析結果がストリーミング表示されること
- 出典リンクが衆議院TV/参議院TVの正しいURLを指していること

---

## Step 6: 回避答弁ディテクター

**ファイル:** `site/src/components/EvasionDetector.jsx`

**機能要件:** F-26（答弁の回避度を詳細分析し、理想的な答弁案を提示する）

**配置場所:** セッション詳細ページのQ&Aカード内

**やること:**
- 選択されたQ&Aペアについて、答弁が質問の核心に答えているかをLLMで詳細判定
- ビルド時の `evasion_score`（0〜1）を超える詳細分析を提供
- 理想的な答弁案も生成

**プロンプト設計:**

```
あなたは国会質疑の分析専門家です。以下のQ&Aペアを分析してください。

## 質問
質問者: {questioner}（{party}）
質問内容: {question_full_text}
質問の意図: {question_intent}

## 答弁
答弁者: {answerer}（{role}）
答弁内容: {answer_full_text}

以下の形式で分析してください:

### 1. 質問の核心
質問者が本当に聞きたかったことを1-2文で要約

### 2. 答弁の評価
- 直接回答しているか: はい/部分的/いいえ
- 回避の手法（該当する場合）: 論点すり替え/一般論への逃避/検討するで保留/管轄外への振り/数字の曖昧化
- 具体性: 高/中/低
- 回避度スコア: 0.0〜1.0（0=完全回答、1=完全回避）

### 3. 理想的な答弁案
質問の核心に正面から答えた場合の答弁案を200字以内で作成

日本語で回答してください。
```

**テスト:**
- Q&Aカードの「回避度分析」ボタンをクリック → 分析結果がストリーミング表示
- `evasion_score` が高い（≥0.7）Q&Aペアで理想答弁案が有意に異なる内容になること
- `evasion_score` が低い（≤0.2）Q&Aペアで「直接回答している」と判定されること
- 出典リンクが正しいこと

---

## Step 7: フォローアップ質問提案

**ファイル:** `site/src/components/FollowUpSuggester.jsx`

**機能要件:** F-27（答弁の弱点を突くフォローアップ質問を提案する）

**配置場所:** セッション詳細ページのQ&Aカード内

**やること:**
- 選択されたQ&Aペア（+ 同一セッション内の前後のQ&A）を分析
- 答弁の弱点・曖昧点を指摘し、それを突く質問案を3つ生成
- 各質問案に「狙い」を付記（例: 数値の具体化を迫る、期限を明確にさせる、等）

**プロンプト設計:**

```
あなたは国会質疑の戦略アドバイザーです。以下の答弁を分析し、フォローアップ質問を提案してください。

## 元の質疑
質問者: {questioner}（{party}）
質問: {question_full_text}
答弁者: {answerer}（{role}）
答弁: {answer_full_text}

{前後のQ&Aコンテキストがあれば追加}

## 指示
答弁の弱点（曖昧な表現、具体性の欠如、論点回避、数字の不在など）を特定し、
それを突くフォローアップ質問を3つ提案してください。

各質問について:
1. **質問文**: 国会の質疑として適切な表現で
2. **狙い**: この質問で何を引き出したいか
3. **想定される答弁回避パターン**: 相手がどう逃げる可能性があるか

日本語で回答してください。
```

**テスト:**
- フォローアップ質問が3つ生成されること
- 各質問に「狙い」と「想定回避パターン」が含まれること
- 元のQ&Aの出典リンクが正しいこと

---

## Step 8: SNS投稿生成

**ファイル:** `site/src/components/SNSGenerator.jsx`

**機能要件:** F-28（Q&Aペアからプラットフォーム別SNS投稿を生成する）

**配置場所:** セッション詳細ページのQ&Aカード内

**やること:**
- プラットフォーム切り替え: X（280字）/ note / ブログ
- Q&Aペアの内容を要約し、指定フォーマットで投稿文を生成
- 出典URL（衆議院TV/参議院TV）を必ず含める
- コピーボタンでクリップボードにコピー

**UI:**

```
┌──────────────────────────────────────────┐
│ 📝 SNS投稿生成                           │
├──────────────────────────────────────────┤
│ プラットフォーム: [X] [note] [ブログ]     │
│                                          │
│ [投稿文を生成]                            │
│                                          │
│ ── 生成結果 ──                            │
│ 【高額療養費の多数回該当リセット問題】     │
│ チームみらい・古川あおい議員が厚労大臣に  │
│ 質問。上野大臣は「次期制度改正の検討課題  │
│ として位置づけたい」と答弁。              │
│ 📺 動画: https://shugiintv.go.jp/...     │
│ #国会 #高額療養費                         │
│                                          │
│ [📋 コピー]                              │
└──────────────────────────────────────────┘
```

**プラットフォーム別制約:**

| プラットフォーム | 文字数 | フォーマット |
|----------------|--------|-------------|
| X | 280字以内 | 要旨 + 出典URL + ハッシュタグ |
| note | 制限なし | 見出し + 背景説明 + Q&A要旨 + 考察 + 出典 |
| ブログ | 制限なし | HTML見出し + 詳細解説 + 引用ブロック + 出典 |

**テスト:**
- Xモードで生成 → 280字以内であること
- 出典URL（`source_url`）が必ず含まれていること
- 「コピー」ボタン → クリップボードに正しくコピーされること
- 各プラットフォーム切り替えで生成結果のフォーマットが変わること

---

## Step 9: 政策ブリーフ生成

**ファイル:** `site/src/components/PolicyBrief.jsx`

**機能要件:** F-29（複数セッション横断のテーマ別政策ブリーフを生成する）

**配置場所:** `/dashboard/topics` のトピック詳細、または `/browse` のフィルタ結果から

**やること:**
- フィルタ済みの複数Q&Aペアを入力として、テーマ別の政策ブリーフを生成
- ブリーフ構成: 概要 → 各党の立場 → 政府の対応 → 時系列変化 → 今後の論点
- ソース一覧を末尾に添付

**データフロー:**

```
1. ユーザーがトピックまたはフィルタ条件を選択
2. /api/index.json から該当Q&Aペアを収集
3. Q&Aペア群をプロンプトに埋め込み（多い場合はLLMのコンテキスト長を考慮して上位20件に制限）
4. OpenRouter API にリクエスト
5. StreamingAnalysis で逐次表示
6. 全Q&Aペアの source_url リンクを末尾に表示
```

**テスト:**
- 3件以上のQ&Aペアを入力 → ブリーフが生成されること
- ブリーフに各党の立場が含まれること（データに複数政党がある場合）
- 出典リンクが正しいこと
- コンテキスト長超過時に適切にQ&Aペアが制限されること（20件まで）

---

## Step 10: 自然言語クエリ

**ファイル:** `site/src/components/NaturalLanguageQuery.jsx`

**機能要件:** F-30（データ全体に対する自然言語クエリを処理する）

**配置場所:** `/search` ページに追加タブとして、または独立セクションとして

**やること:**
- ユーザーの自然言語の質問を受け取り、`/api/index.json` のデータから回答を生成
- 2段階処理: (1) 質問からフィルタ条件を生成 → (2) フィルタ結果をコンテキストとしてLLMに回答を依頼
- これは最も複雑な機能であり、慎重に設計する

**2段階処理フロー:**

```
ステージ1: 質問解析（非ストリーミング）
  ユーザー入力: 「出産費用の無償化について各党の立場を比較して」
  ↓
  LLM呼び出し（JSON出力指定）:
  {
    "keywords": ["出産費用", "無償化"],
    "speakers": [],
    "parties": [],
    "date_range": null,
    "chamber": null
  }

ステージ2: データ検索
  /api/index.json を keywords でフィルタ
  → 該当Q&Aペア群を抽出

ステージ3: 回答生成（ストリーミング）
  該当Q&Aペア群 + 元の質問 → LLMに回答を依頼
  → StreamingAnalysis で表示
```

**ステージ1のプロンプト:**

```
あなたは国会議事録検索システムのクエリ解析エンジンです。
ユーザーの質問から検索条件をJSON形式で抽出してください。

利用可能なフィルタ:
- keywords: トピック・キーワード（配列）
- speakers: 発言者名（配列）
- parties: 政党・会派名（配列）
- date_range: { from: "YYYY-MM-DD", to: "YYYY-MM-DD" } または null
- chamber: "shugiin" | "sangiin" | null（両院）
- roles: 役割フィルタ（"質疑者" | "答弁者" など、配列）

ユーザーの質問: {user_query}

JSONのみを出力してください。説明は不要です。
```

**ステージ3のプロンプト:**

```
あなたは国会議事録データベースのアシスタントです。
以下のデータに基づいて、ユーザーの質問に回答してください。
データにない情報は推測せず、「該当するデータが見つかりませんでした」と回答してください。

## ユーザーの質問
{user_query}

## 該当データ
{フィルタ済みQ&Aペア群をJSON形式で列挙}

回答にはデータの出典（日付・委員会・発言者）を明記してください。
日本語で回答してください。
```

**UI:**

```
┌──────────────────────────────────────────┐
│ 💬 自然言語で質問                         │
├──────────────────────────────────────────┤
│ ┌──────────────────────────────────┐      │
│ │出産費用の無償化について各党の     │      │
│ │立場を比較して                    │      │
│ └──────────────────────────────────┘      │
│ [質問する]                                │
│                                          │
│ 検索条件: keywords=["出産費用","無償化"]  │
│ 該当Q&A: 8件                             │
│                                          │
│ ── 回答（ストリーミング）──               │
│ ## 各党の立場                             │
│ ### 自由民主党                            │
│ 厚生労働大臣の上野賢一郎氏は4/9の...     │
│ ██████████░░░░░░ 回答生成中...           │
│                                          │
│ 📎 参照データ:                            │
│ • 2026-04-09 本会議 — 古川あおい(質問)    │
│ • 2026-04-09 本会議 — 上野賢一郎(答弁)    │
└──────────────────────────────────────────┘
```

**エッジケース:**
- 該当データが0件 → 「お探しの内容に該当するデータが見つかりませんでした。キーワードを変えてお試しください。」
- 該当データが多すぎる（20件超）→ 日付順で最新20件に絞り、「直近20件のデータに基づいて回答しています」と注記
- ステージ1でJSON解析に失敗 → 全キーワード検索にフォールバック

**テスト:**
- 「高額療養費について」→ 関連Q&Aが抽出されること
- 「上野大臣の答弁」→ `speakers` フィルタが正しく生成されること
- 該当データ0件 → 適切なメッセージ表示
- ストリーミング表示が正常に動作すること
- 出典データが正しいこと

---

## Step 11: 発言者ネットワーク（D3）

**ファイル:** `site/src/components/SpeakerNetwork.jsx`

**機能要件:** F-21（質疑者↔答弁者の対話ネットワークを可視化する）

**配置場所:** `/dashboard/speakers`

**やること:**
- D3 force-directed graph で質疑者↔答弁者の関係を可視化
- ビルド時に `/api/speakers.json` として集計データを生成（Astroのビルドスクリプト）
- ブラウザ側は静的JSONを読み込んでD3でレンダリング

**データ形式（`/api/speakers.json` に追加するネットワークデータ）:**

```json
{
  "nodes": [
    { "id": "古川あおい", "party": "チームみらい", "role": "questioner", "count": 5 },
    { "id": "上野賢一郎", "party": "自由民主党", "role": "answerer", "count": 12 }
  ],
  "links": [
    { "source": "古川あおい", "target": "上野賢一郎", "weight": 3, "topics": ["高額療養費", "出産費用"] }
  ]
}
```

**D3実装仕様:**
- ノードサイズ: `count`（発言回数）に比例
- ノード色: `party` ごとに政党カラー（自民=青、立憲=赤、維新=緑、等）
- エッジ太さ: `weight`（Q&Aペア数）に比例
- ホバー: ノード名・所属・発言回数をツールチップ表示
- クリック: そのスピーカーのQ&Aペア一覧ページへ遷移
- ドラッグ: ノードをドラッグして配置調整可能
- フィルタ: 院（衆/参/両院）、期間、最小weight のスライダー

**政党カラーマップ（参考）:**

```javascript
const PARTY_COLORS = {
  "自由民主党": "#1e3a5f",
  "立憲民主党": "#c41e3a",
  "日本維新の会": "#2e8b57",
  "公明党": "#ff8c00",
  "国民民主党": "#1e90ff",
  "日本共産党": "#dc143c",
  "れいわ新選組": "#ff69b4",
  "チームみらい": "#9370db",
  "参政党": "#ffd700",
  "無所属": "#808080",
  // 参議院特有の会派名は名寄せ後に同じ色を適用
};
```

**テスト:**
- ネットワーク図がSVGとしてレンダリングされること
- ノードのドラッグが動作すること
- ホバーでツールチップが表示されること
- フィルタ（院・期間・最小weight）が正しく動作すること
- データが0件の場合に空のメッセージが表示されること
- ブラウザのリサイズに追従すること（レスポンシブ）

---

## Step 12: 政党別分析（両院名寄せ）

**ファイル:**
- `site/src/components/PartyAnalysis.jsx`（React島）
- `site/src/lib/party-normalization.js`（名寄せロジック）

**機能要件:** F-22（政党別の発言量・トピック分布を表示する）

**やること:**
- 両院で異なる会派名を正規化する名寄せマッピングを作成
- 政党別の発言量・トピック分布をRechartsで可視化
- ビルド時に `/api/parties.json` を生成

**名寄せマッピング（`party-normalization.js`）:**

両院で同じ政党でも会派名が異なるケースに対応する。

```javascript
// 参議院の会派名 → 正規化名
const SANGIIN_PARTY_MAP = {
  "自由民主党・無所属の会": "自由民主党",
  "立憲民主・社民": "立憲民主党",
  "公明党": "公明党",
  "日本維新の会・教育無償化を実現する会": "日本維新の会",
  "国民民主党・新緑風会": "国民民主党",
  "日本共産党": "日本共産党",
  "れいわ新選組": "れいわ新選組",
  "沖縄の風": "沖縄の風",
  "NHKから国民を守る党": "NHKから国民を守る党",
  "各派に属しない議員": "無所属",
};

// 衆議院の会派名 → 正規化名
const SHUGIIN_PARTY_MAP = {
  "自由民主党・無所属の会": "自由民主党",
  "立憲民主党・無所属": "立憲民主党",
  "日本維新の会": "日本維新の会",
  "公明党": "公明党",
  "国民民主党・無所属クラブ": "国民民主党",
  "日本共産党": "日本共産党",
  "れいわ新選組": "れいわ新選組",
  "チームみらい": "チームみらい",
  "参政党": "参政党",
  "無所属": "無所属",
};

export function normalizeParty(chamber, rawParty) {
  const map = chamber === "shugiin" ? SHUGIIN_PARTY_MAP : SANGIIN_PARTY_MAP;
  return map[rawParty] || rawParty;
}
```

**重要**: 会派名は国会の会期ごとに変わりうる。このマッピングは2026年4月時点のもの。新しい会派名が登場したらマッピングを更新する必要がある。

**可視化:**
- 棒グラフ: 政党別の発言回数（Recharts `BarChart`）
- 積み上げ棒グラフ: 政党別×トピック分布
- 院別フィルタ（衆/参/両院）

**テスト:**
- 衆議院の「自由民主党・無所属の会」と参議院の「自由民主党・無所属の会」が同じ「自由民主党」に正規化されること
- マッピングにない会派名がそのまま返されること（フォールバック）
- チャートが正しくレンダリングされること
- 院別フィルタが動作すること

---

## Step 13: Google Sheets API連携

**ファイル:** `site/src/components/SheetsExport.jsx`

**機能要件:** F-17（Google Sheets API連携によるワンクリックエクスポート）

**配置場所:** フィルタ結果ページ、Q&Aカード一覧

**やること:**
- Google Identity Services（GIS）を使ったOAuth 2.0認証（ブラウザのみ）
- フィルタ済みQ&Aペアを新規スプレッドシートに書き出し
- **注意**: Google Cloud Console でOAuth同意画面とクライアントIDの設定が必要。これはリポジトリ外の設定

**認証フロー:**

```
1. ユーザーが「Google Sheetsにエクスポート」をクリック
2. Google Identity Services のポップアップが表示される
3. ユーザーがGoogleアカウントで認証 + Sheets APIへのアクセスを許可
4. アクセストークンをメモリ内で保持（sessionStorageに保存してもよいが、有効期限1時間）
5. Sheets API v4 でスプレッドシート作成 + データ書き込み
6. 作成されたスプレッドシートのURLを表示
```

**書き出すデータ形式（1行=1 Q&Aペア）:**

| 列 | 内容 |
|----|------|
| A | 日付 |
| B | 院（衆/参） |
| C | 委員会 |
| D | トピック |
| E | 質問者 |
| F | 質問者所属 |
| G | 質問要旨 |
| H | 答弁者 |
| I | 答弁者役職 |
| J | 答弁要旨 |
| K | 回避度 |
| L | 約束事項 |
| M | 動画URL |

**依存:**
- Google Identity Services ライブラリ: `<script src="https://accounts.google.com/gsi/client"></script>` を `settings.astro` または `<head>` に追加
- Google Sheets API: `https://sheets.googleapis.com/v4/spreadsheets` へのRESTリクエスト
- Google Cloud Console でのクライアントID設定（環境変数 `PUBLIC_GOOGLE_CLIENT_ID` としてAstroに渡す）

**注意**: Phase 4のTSVエクスポート（F-16）は既に実装済みの前提。Google Sheets連携はそのTSVと同じデータを直接スプレッドシートに書き込む上位互換。

**テスト:**
- Google認証ポップアップが表示されること
- 認証後にスプレッドシートが作成されること
- 全列にデータが正しく入っていること
- 日本語テキストが文字化けしないこと
- 認証をキャンセルした場合にエラーメッセージが表示されること
- `PUBLIC_GOOGLE_CLIENT_ID` が未設定の場合にボタンが非活性 + 説明メッセージ

---

## Step 14: 過去セッション遡及処理

**ファイル:** `kokkai-transcriber/src/backfill.py`

**機能要件:** 過去セッション遡及処理（両院）

**配置場所:** kokkai-transcriber（Pythonパイプライン側）

**やること:**
- 指定した日付範囲の過去セッションをバッチ処理するスクリプト
- 既存の `pipeline.py` を内部で呼び出す
- 並列処理ではなく逐次処理（API レート制限・コスト管理のため）
- 処理済みセッションはSQLiteでスキップ

**CLI仕様:**

```bash
# 衆議院の過去1ヶ月分を遡及処理
python -m src.backfill --chamber shugiin --from 2026-03-14 --to 2026-04-14

# 参議院の特定期間
python -m src.backfill --chamber sangiin --from 2026-01-01 --to 2026-03-31

# 両院
python -m src.backfill --chamber both --from 2026-04-01 --to 2026-04-14

# ドライラン（処理対象のセッション一覧を表示するだけ）
python -m src.backfill --chamber shugiin --from 2026-03-14 --to 2026-04-14 --dry-run

# 処理間隔を指定（デフォルト60秒。APIレート制限回避）
python -m src.backfill --chamber shugiin --from 2026-03-14 --to 2026-04-14 --interval 120
```

**実装仕様:**

```python
# kokkai-transcriber/src/backfill.py

import argparse
import time
from datetime import date, timedelta

from src.scrapers.shugiin import ShugiinScraper
from src.scrapers.sangiin import SangiinScraper
from src.state import StateManager
from src.pipeline import process_session


def get_date_range(from_date: str, to_date: str) -> list[date]:
    """from_date から to_date までの日付リストを返す"""
    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def backfill(chamber: str, from_date: str, to_date: str,
             dry_run: bool = False, interval: int = 60) -> None:
    scrapers = []
    if chamber in ("shugiin", "both"):
        scrapers.append(ShugiinScraper())
    if chamber in ("sangiin", "both"):
        scrapers.append(SangiinScraper())

    state = StateManager()
    dates = get_date_range(from_date, to_date)

    for scraper in scrapers:
        for d in dates:
            date_str = d.isoformat()
            session_ids = scraper.detect_new_sessions(date_str)

            for sid in session_ids:
                if state.is_processed(scraper.chamber, sid):
                    print(f"[SKIP] {scraper.chamber}/{sid} (処理済み)")
                    continue

                if dry_run:
                    print(f"[DRY-RUN] {scraper.chamber}/{sid} ({date_str})")
                    continue

                print(f"[PROCESS] {scraper.chamber}/{sid} ({date_str})")
                try:
                    process_session(scraper.chamber, sid)
                    print(f"[DONE] {scraper.chamber}/{sid}")
                except Exception as e:
                    print(f"[ERROR] {scraper.chamber}/{sid}: {e}")
                    # エラーでも続行（他のセッションは処理する）

                time.sleep(interval)
```

**コスト見積り（遡及処理）:**
- 衆議院: 週5日 × 平均3セッション/日 × 平均2時間 = 30時間/週
- Whisper: 30h × $0.0002/min × 60min = $0.36/週
- LLM: ~$0.15/週
- 1ヶ月分の遡及: 約 $2.04（Whisper + LLM合計）

**テスト:**
- `--dry-run` で処理対象セッション一覧が表示されること
- 処理済みセッションがスキップされること（SQLiteの `status='done'` を確認）
- `--interval` で指定した秒数だけ処理間に待機すること
- エラーが発生しても他のセッションの処理が続行されること
- `--chamber both` で両院が順次処理されること

---

## 統合テスト

全ステップ完了後に実施する統合テスト:

### E2E テスト項目

| # | テスト | 手順 | 期待結果 |
|---|--------|------|----------|
| 1 | Tier 0→Tier 1 遷移 | キー未入力で各分析機能を確認 → 設定でキー入力 → 再度確認 | ゲート表示→機能アンロック |
| 2 | 答弁比較の完全フロー | Q&Aカード → 答弁比較 → 結果確認 | ストリーミング表示 + 出典リンク |
| 3 | 自然言語クエリの完全フロー | 検索ページ → 質問入力 → 回答確認 | 2段階処理 + ストリーミング回答 |
| 4 | SNS投稿 → コピー → 文字数 | X向け生成 → コピー → 文字数カウント | 280字以内 + 出典URL含む |
| 5 | 発言者ネットワーク操作 | ノードドラッグ、ホバー、フィルタ | インタラクション正常 |
| 6 | 政党名寄せ | 両院のデータで政党別集計 | 同一政党が統合 |
| 7 | Google Sheets エクスポート | 認証 → エクスポート → シート確認 | 全列にデータ、日本語正常 |
| 8 | 遡及処理 → サイト反映 | backfill実行 → git push → ビルド → サイト確認 | 過去データが表示 |
| 9 | タブ閉じ → キー消去確認 | キー入力 → タブ閉じ → 再度開く | Tier 0に戻る |
| 10 | セキュリティ確認 | DevToolsのNetwork監視 | APIキーがOpenRouter以外に送信されていないこと |

### パフォーマンステスト

| # | テスト | 基準 |
|---|--------|------|
| 1 | D3ネットワーク（100ノード） | 初回レンダリング3秒以内 |
| 2 | 自然言語クエリ（ステージ1） | JSON解析結果が5秒以内に返ること |
| 3 | 政党別チャート（1000件Q&A） | チャートレンダリング2秒以内 |
| 4 | 遡及処理（1日分3セッション） | エラーなく完了、interval遵守 |

---

## 実装の優先順位

段階的リリースを前提とした優先順位:

### 第1弾（BYOK基盤 — 最優先）
1. Step 1: OpenRouterクライアント
2. Step 2: 設定ページ
3. Step 3: BYOKGate
4. Step 4: StreamingAnalysis

### 第2弾（コア分析機能）
5. Step 5: 答弁比較
6. Step 6: 回避答弁ディテクター
7. Step 7: フォローアップ質問提案

### 第3弾（コンテンツ生成・可視化）
8. Step 8: SNS投稿生成
9. Step 11: 発言者ネットワーク
10. Step 12: 政党別分析

### 第4弾（高度機能・連携）
11. Step 9: 政策ブリーフ
12. Step 10: 自然言語クエリ
13. Step 13: Google Sheets連携
14. Step 14: 過去セッション遡及処理

各弾はそれぞれ独立してマージ・デプロイ可能。
