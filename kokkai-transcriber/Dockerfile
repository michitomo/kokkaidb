FROM python:3.12-slim

# ffmpegとgitとSSHクライアントをインストール
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git openssh-client && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /root/.ssh && \
    ssh-keyscan github.com >> /root/.ssh/known_hosts 2>/dev/null

WORKDIR /app

# 依存関係インストール
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# ソースコードをコピー
COPY src/ src/

# リポジトリルートをマウントするための作業ディレクトリ
# docker-compose.yml で volumes 指定
WORKDIR /repo/kokkai-transcriber
