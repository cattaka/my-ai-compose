## 主にチャット画面で使われる（=頻度高 or 必須寄り）API

### 必須（ほぼ常用）

- GET /api/tags
  - モデル一覧取得（モデル選択ドロップダウン用）
- POST /api/chat または POST /api/generate
  - 会話モードなら /api/chat、単発プロンプトなら /api/generate（実装側/設定でどちらかor両方） （ストリーミング時は行単位のJSONを逐次受信）

### 準必須（あると参照される）

- GET /api/version
  - 接続確認・互換判定
- GET /api/ps
  - 実行中モデル状況（UI側が表示する場合あり）

### オプション（必要な状況でのみ）

- POST /api/embeddings
  - ベクトル検索/RAGや類似度表示を有効にしている場合
- POST /api/pull
  - UIからモデルをダウンロードする操作を許可する場合
- POST /api/create
  - モデル合成/カスタム作成をUIから行う場合
- POST /api/delete
  - モデル削除操作
- GET /api/show
  - モデル詳細メタ取得

### 最低限チャットだけ成立させるなら:

- /api/tags
- /api/generate か /api/chat（どちらか一方でも可、UI設定に合わせる）
- /api/version（疎通確認用に推奨）

### 拡張したい場合に追加:

- ストリーミング：/api/chat or /api/generate のストリーム形式対応（行ごとJSON）
- Embeddings機能：/api/embeddings
- モデル管理機能：/api/pull /api/create /api/delete /api/show /api/ps

これらを実装順で優先付けすると良いです。

## /api/generate と /api/chat の設計意図比較

| 観点 | /api/generate | /api/chat |
|------|---------------|-----------|
| 入力形式 | 単一 prompt / system / template / images | messages 配列 (role付き) |
| 抽象度 | 低（自由度高い） | 高（会話用途に最適化） |
| 履歴管理 | クライアント側で連結 | サーバ側が messages を受け取り連結 |
| ストリーム行フォーマット | {"response": "..."} | {"message":{"role":"assistant","content":"..."}} |
| RAG / カスタムテンプレート | やりやすい | 可能だが柔軟性はやや低い |
| OpenAI chat 互換変換 | flatten して使う | ほぼそのままマップ |

### 選択指針
- 高度な前処理・RAG統合・プロンプト工学重視: /api/generate
- シンプルなチャットUI / OpenAIライク: /api/chat

### /api/generate と /api/chat の関係（補足解釈）

- /api/generate は「生の生成API」。system / prompt / template などをクライアントが完全制御する低レイヤ。
- /api/chat は「会話履歴(messages) → 内部プロンプト再構成 → 生成」のラッパ。実際の生成コアは /api/generate と同系処理。
- ほとんどのケースで /api/chat は messages を以下のように整形し 1 つのテキストブロックへ連結してから生成を呼ぶ（擬似例）:

  ```
  system: あなたはアシスタント...
  user: こんにちは
  assistant: こんにちは、ご用件をどうぞ。
  user: 次を要約して...
  ```

- 高度な挿入（RAG結果を system と user の間の特定位置に入れる、プロンプト圧縮、可変テンプレート最適化等）は /api/generate の方がやりやすい。
- 既存の OpenAI Chat API 互換UI/クライアントとの橋渡しを簡単にするための“利便インターフェイス”が /api/chat。

### 実装指針のヒント

| 要件 | 推奨エンドポイント |
|------|--------------------|
| 会話UI互換（OpenAI風） | /api/chat |
| プロンプト工学 / RAG細粒度制御 | /api/generate |
| 両方サポートしたい | /api/chat を内部で /api/generate に変換 |

## RAG 展開フロー概要

1. クエリ生成: ユーザー入力（必要なら履歴要約）→ 検索クエリ
2. ベクトル検索: top-k + スコア閾値 / 再ランク
3. チャンク整形: 重複除去 / 圧縮 / citation番号付与
4. プロンプト構築:
   - /api/generate: system + 「# 背景資料」ブロック + 指示 + 質問
   - /api/chat: messages 内の system / 直前 user に資料埋め込み
5. 応答後整形: 引用検証 / 不足時リトライ

### /api/generate 用テンプレート例

```
system: あなたは資料根拠付きで回答するアシスタント。資料外推測禁止。
prompt:
# 背景資料
[1] {doc1要約}
[2] {doc2要約}

# 指示
上の資料のみを根拠に簡潔回答。各主張に対応する [番号] を付与。
資料になければ「不明」。

# 質問
{question}
```

### /api/chat 用埋め込み例（最後の user）

```
<docs>
[1] {doc1要約}
[2] {doc2要約}
</docs>
質問: {question}
```

### context 利用
- 連続ターンで共通指示を保持し再トークナイズ省略
- 資料が大幅更新された場合は context を省き再構築

### トークン予算計算
- 予算 = モデル最大 - 安全マージン(例512)
- 残りを資料に割当 → 長い資料は要約/切り詰め

### 失敗対策
- 引用欠落 → 再プロンプト（例: 「引用形式 [番号] を必ず付けて再出力」）
- JSON検証失敗 → エラー理由付き再試行

## /api/chat の tools パラメータ

Ollama の /api/chat では OpenAI 風の簡易 Function Calling が可能。  
`tools` 配列で利用可能関数を宣言すると、モデルは応答内で `tool_calls` を生成する。

### tool 定義フォーマット（例）

```json
"tools": [
  {
    "name": "web_search",
    "description": "ユーザー質問に関連する最新Web情報を短く要約して返す。曖昧質問にも使う。",
    "input_schema": {
      "type": "object",
      "properties": {
        "query": { "type": "string", "description": "検索クエリ文字列" },
        "top_k": { "type": "integer", "description": "返す件数", "default": 3 }
      },
      "required": ["query"]
    }
  },
  {
    "name": "math_eval",
    "description": "数式を正確に評価。通貨/単位変換は不可。",
    "input_schema": {
      "type": "object",
      "properties": {
        "expression": { "type": "string", "description": "評価する数式" }
      },
      "required": ["expression"]
    }
  }
]
```

### チャット呼び出し例（リクエスト）

```json
{
  "model": "llama3",
  "messages": [
    { "role": "system", "content": "あなたは事実重視のアシスタント。" },
    { "role": "user", "content": "2023年の日本のGDPとその後の変化をざっくり教えて。必要なら検索して。" }
  ],
  "tools": [ /* 上記定義 */ ],
  "stream": true
}
```

### モデル応答（tool call 例・概念）

```json
{
  "message": {
    "role": "assistant",
    "content": "",
    "tool_calls": [
      {
        "id": "call_1",
        "name": "web_search",
        "arguments": { "query": "Japan GDP 2023 growth", "top_k": 3 }
      }
    ]
  },
  "done": false
}
```

### ツール実行後の再送

1. クライアントが web_search 実行→結果要約
2. tool メッセージ追加:

```json
{
  "role": "tool",
  "name": "web_search",
  "tool_call_id": "call_1",
  "content": "[1] WorldBank: ... 要約\n[2] IMF: ... 要約\n"
}
```

3. これを含む `messages` を再度 /api/chat に送信 → 最終回答生成

### ユースケース分類

| 種別 | 例 | 補足 |
|------|----|------|
| 検索/RAG | web_search, vector_retrieve | 外部知識注入 |
| 計算 | math_eval | 逐次手計算防止 |
| データ参照 | db_query | SQL生成結果は安全フィルタ |
| 外部API | weather_lookup | レート制限注意 |
| 整形/検証 | json_validate | 出力安定化 |
| セッション管理 | list_tasks | 内部状態列挙（過度な露出注意） |

### ベストプラクティス

- 説明は“いつ使うか”条件を明示（例: “最新情報が必要なときのみ”）
- 引数を最小限・型を厳格（enum, integer 範囲制限）
- 長大出力は上限（例: 4000 文字）で切る
- 無限ツールループ防止（最大呼出回数カウンタ）
- 失敗時（例外）: tool メッセージで `error: true` フィールドを返しモデルに再判断させる

### セキュリティ注意

- 書き込み系（ファイル/ネットワーク）は原則除外
- 動的に生成された名前のツールは避ける（ホワイトリスト管理）
- ログにツール実行引数を記録し監査可能に

## RAG ルーティングと展開判断

### どこで判断されるか
- Open WebUI: 単にユーザー入力送信（基本は判断しない）
- 中間層 (langchain-api):  
  1. 意図/カテゴリ判定 (キーワード, 埋め込み類似度, 分類モデル)  
  2. 利用する retriever / ベクトルストア選定  
  3. top_k / 閾値 / 再ランク有無決定  
  4. 取得チャンクの圧縮・番号付与  
  5. プロンプトへの差し込み位置決定 (/api/generate か /api/chat)

### RAG 選択アルゴリズム例（擬似）
1. embed(query) → 各コーパス top1 スコア取得  
2. max_score < 閾値 → RAGスキップ  
3. 上位Nコーパスに対して並列 top_k 検索  
4. 全チャンク結合 → 重複/低スコア削除 → 要約再圧縮  
5. citations 付与 → prompt構築

### 差し込み位置パターン
| パターン | 利点 | 注意 |
|----------|------|------|
| system直後 | 永続ルール強化 | system肥大化で希釈 |
| user内 <docs> | 実装簡単 / 目視可 | モデルがタグ無視時あり |
| toolメッセージ | 機能的分離 / function calling互換 | 実装手間 |
| prompt末尾 (# 背景資料) | 指示→資料→質問の順で自然 | 質問より後に資料を書かない |

### スキップ判定
- 雑談 (intent=chitchat) → skip
- 類似質問再発 (similarity > 0.92) → 前回資料再利用
- 低信頼 (avg score < 0.35) → “不明” テンプレ回答

### 失敗リカバリ
- 資料外推測: 「前回は資料外推測。資料内根拠番号付で再回答」を再プロンプト
- 文字数過多: 再度チャンク要約 (map→reduce)

### 推奨関数分離 (例)
- classify_intent(text) -> intent
- rank_corpora(query_vec) -> [(corpus, score)]
- retrieve(corpus_list, query, k) -> chunks
- compress(chunks) -> condensed_chunks
- build_prompt(mode, system, docs, question) -> final_prompt

## 意図 / カテゴリ判定（Intent & Category Classification）の実現方法

RAG ルーティング前段で「これはどの処理フローに回すか」を決める判定層。以下を組合せて実装。

### 1. ルールベース（最速 / 初期）
- 正規表現 / キーワード表
  - 例: "エラー", "stacktrace" → tech_support
  - 例: "売上", "予算" → finance
- 利点: 実装即可能 / 誤動作が可視
- 欠点: 網羅性・拡張性低

### 2. 埋め込み類似度（Semantic Routing）
- 各カテゴリ代表文をベクトル化し常駐
- ユーザー入力をエンコード → cosine スコア最大カテゴリ
- 閾値未満なら "general"
- 利点: メンテ容易 / 言い換えに強い
- 欠点: 微妙な境界は誤判定あり

### 3. 小型分類モデル
- scikit-learn / fastText / mini LM fine-tune
- 特徴: 埋め込み + ロジスティック回帰 / SVM
- 利点: 安定 / 高速
- 欠点: データ整備コスト

### 4. LLM Few-Shot 判定
- プロンプト: カテゴリ一覧 + 定義 + Few-shot例
- 出力: JSON { "intent": "...", "confidence": 0.x }
- 利点: 柔軟 / 新クラス追加が簡単
- 欠点: レイテンシ / コスト / ブレ

### 5. ハイブリッド推奨構成
1) ルールで確定ヒットなら即確定  
2) 埋め込みスコア > 閾値なら採用  
3) 境界ケースのみ LLM few-shot 判定  
4) 最後に安全カテゴリ fallback（"general" / "other"）

### 6. 追加メタ判定
| 判定 | 方法 | 用途 |
|------|------|------|
| 雑談(chitchat) | 埋め込み類似度 or LLM | RAGスキップ |
| 機密/拒否 | ルール + LLM安全判定 | 応答制限 |
| 計算要求 | 正規表現 + LLM | 計算ツール誘導 |
| コード質問 | トークン検出 (``` や import ) | コードモード |

### 7. 判定結果で分岐する処理例
- intent=tech_support → 技術ナレッジベース retriever
- intent=finance → 会計ドキュメント retriever
- chitchat → RAG無 / 軽量モデル
- requires_calc=True → math ツール first

### 8. 擬似フロー
