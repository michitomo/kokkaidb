# ECS定期実行化 TODO

batch.pyをECS Scheduled Taskとして1時間に1回実行するための作業リスト。

---

## 1. state.dbをファイルベースからgit状態判定に変更

**現状**: SQLite `state.db` で処理済みセッションを管理。コンテナが破棄されると情報が消える。

**対応**:
- batch.pyの `_discover_sessions` で、`state.is_processed()` の代わりに `data/{chamber}/.../{session_id}_*/qa_pairs.json` の存在チェックを使う
- git clone後のdata/ディレクトリから処理済みが自動復元される
- state.dbはコンテナ内の一時ファイルとして処理ログ用途のみに残す（永続化不要）

## 2. Dockerfileをself-contained化

**現状**: ホストのリポジトリをvolumeマウントしている前提。

**対応**:
- コンテナ起動時に `git clone --depth=1` でリポジトリを取得するentrypoint.shを作成
- 処理完了後に `git add data/ && git commit && git push`
- SSH鍵はAWS Secrets Managerから取得してコンテナ内に配置

```dockerfile
# entrypoint.sh の骨格
#!/bin/bash
set -euo pipefail

# SSH鍵をSecrets Managerから取得
aws secretsmanager get-secret-value --secret-id kokkaidb/deploy-key \
  --query SecretString --output text > /root/.ssh/id_ed25519
chmod 600 /root/.ssh/id_ed25519

# リポジトリをclone（data/のみshallow）
git clone --depth=1 git@github.com:michitomo/kokkaidb.git /repo
cd /repo/kokkai-transcriber

# バッチ実行
python -m src.batch --chamber shugiin --since 2026-02-01 --workers 4

# data/にpush → GitHub Actionsがサイトビルド+デプロイ
```

## 3. AWSインフラ構築

### ECRリポジトリ
- `kokkaidb-transcriber` リポジトリを作成
- GitHub Actionsまたはローカルからdocker push

### ECSタスク定義
- **CPU**: 2 vCPU（4並列処理用）
- **メモリ**: 4GB（ffmpeg + Whisper API待ち）
- **タイムアウト**: 3時間（新規セッションが多い場合）
- **環境変数**: `DEEPINFRA_API_KEY` — Secrets Manager参照

### EventBridge Scheduler
- **スケジュール**: `rate(1 hour)` または `cron(0 * * * ? *)`
- **ターゲット**: ECS RunTask
- **失敗時リトライ**: 1回（state.dbなしでも冪等なので安全）

### IAMロール
- ECSタスク実行ロール: ECR pull + CloudWatch Logs
- ECSタスクロール: Secrets Manager読み取り

### VPC/セキュリティグループ
- アウトバウンドのみ必要（衆議院TV、DeepInfra API、GitHub）
- パブリックサブネット or NATゲートウェイ

## 4. GitHub Deploy Key設定

- リポジトリにdeploy key（書き込み権限付き）を追加
- 秘密鍵をAWS Secrets Managerに `kokkaidb/deploy-key` として保存
- SSH鍵のパスフレーズなし

## 5. ログ・監視

- CloudWatch Logsにコンテナログを出力
- 失敗時のSNS通知（EventBridge → SNS）
- メトリクス: 処理セッション数、失敗数、処理時間

## 6. コスト見積もり

| 項目 | 月額概算 |
|------|---------|
| ECS Fargate (2vCPU, 4GB, 最大3h/日) | ~$15 |
| DeepInfra API (Whisper + DeepSeek) | 使用量依存 |
| ECR | ~$1 |
| Secrets Manager | ~$1 |
| NAT Gateway（使用する場合） | ~$35 |
| **合計** | **~$50 + API費用** |

NATゲートウェイを避けるならパブリックサブネット + パブリックIPで十分（インバウンドなし）。

## 7. 参議院対応（将来）

- mediasp.jp音声URL解決にPlaywrightが必要
- DockerfileにPlaywright追加（イメージサイズ増大）
- `--chamber sangiin` を追加するだけでバッチ処理は対応済み
