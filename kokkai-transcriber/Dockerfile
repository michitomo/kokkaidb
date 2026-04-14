FROM python:3.12-slim

# ffmpegとgitをインストール
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存関係インストール
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# ソースコードをコピー
COPY src/ src/

# リポジトリルートをマウントするための作業ディレクトリ
# docker-compose.yml で volumes 指定
WORKDIR /repo
