# My AI Compose

LLMの実験や構築の勉強用。

## 概要

このリポジトリは、Ollama（ローカルLLMサーバー）を LangChain 経由で OpenAI API 互換のエンドポイントとして公開し、Open WebUI などのクライアントから利用できる「OpenAI APIゲートウェイ」を構築するためのものです。  
さらに、PostgreSQL と pgvector を用いた RAG（検索拡張生成）やデータ管理も視野に入れた構成となっています。

## 構成概要

- **Ollama**  
  ローカルで LLM モデルを動作させるサーバー。

- **LangChain API**  
  Ollama を OpenAI API 互換でラップし、RAGやツール連携の拡張も可能。

- **Open WebUI**  
  WebベースのチャットUI。OpenAI API互換エンドポイントに接続可能。

- **PostgreSQL / pgvector**  
  ベクトルデータベースによる検索拡張生成（RAG）やデータ管理。

## セットアップ

1. **リポジトリをクローン**
   ```sh
   git clone https://github.com/cattaka/my-ai-compose.git
   cd my-ai-compose
   ```

2. **Ollama モデルデータディレクトリ作成**
   ```sh
   mkdir ollama-data
   ```

3. **Docker Compose で起動**
   ```sh
   docker compose up --build
   ```

4. **Open WebUI にアクセス**
   - [http://localhost:3000](http://localhost:3000)

## 開発・デバッグ

- `langchain-api` サービスは Python で実装されています。
- VS Code で `.venv` 仮想環境を利用し、`uvicorn` でローカルデバッグ可能です。

## ディレクトリ構成

```
my-ai-compose/
├── docker-compose.yml
├── langchain-api/
│   ├── app.py
│   └── .venv/
├── openwebui-data/
├── ollama-data/
├── pgdata/
└── .vscode/
```

## 作業について
ollamaをローカルで動かすと重たいときは、適宜GPUを積んだサーバー機に向ける。
