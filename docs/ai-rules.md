# AI Rules / Architecture Guidelines

## 1. 目的
本リポジトリにおける LLM 利用・エージェント・メモリ維持・DB マイグレーション運用の共通ルール集。安全性 / 再現性 / 拡張性 / 低結合を重視。

---

## 2. /api/chat と tool_calls
- tool_calls は assistant から「このツールを引数付きで実行して結果を返して」と要求する構造化指示。
- クライアント（ゲートウェイ / オーケストレータ）が実行し、結果を role=tool メッセージで再投入。
- 複数ツール同時要求可。ループ上限を必ず設定。

### ワークフロー概要
1. リクエスト: messages + tools(宣言)
2. モデル応答: assistant.tool_calls
3. サーバ: ツール実行 → tool メッセージ追加
4. 追加呼び出し → 最終回答 or 追加 tool_calls

---

## 3. Tool と内部処理（オーケストレータ）判定基準

| 判定項目 | YES → Tool 公開 | NO → 内部実装 |
|----------|-----------------|---------------|
| 副作用なし (読み取り/計算) | ✅ | ❌ |
| 冪等 / 再実行低コスト | ✅ | ❌ |
| 機密リスク低 | ✅ | ❌ |
| 出力をそのままプロンプトへ戻せる | ✅ | ❌ |
| レート制御容易 | ✅ | ❌ |
| 状態変更 / トランザクション必要 | ❌ | ✅ |
| 権限・監査必須 | ❌ | ✅ |
| 高コスト / 長時間 | ❌ | ✅ |

追加視点: 「LLM が自由に呼んでも資産毀損しないか」。NO なら公開禁止。

---

## 4. オーケストレータ / LangGraph 設計

### 基本ノード例
- plan: ツール / retrieval の要否 JSON 生成
- retrieval: 複数 KB/検索システム参照
- tools: 計算・補助ツール実行
- compose: プロンプト統合
- answer: LLM 最終回答
- (memory フロー) initial → unknown_words → need_more_memory → escalate(ループ) → update_memories → answer

### 分岐
- LangGraph の add_conditional_edges を使用。ノード内で次ノードを直接呼ばない。
- state に route / flags を書き、外部関数 (state→label) で遷移決定。

### 並列 (Fan-out/Fan-in)
- plan → retrieverA / retrieverB / tools を並列
- merge ノードで統合 (docs 合体・重複除去・スコア再計算)
- 利点: レイテンシ短縮（最遅枝で決まる）

---

## 5. plan (JSON) 出力信頼性確保

優先度順対策:
1. モデル構造化出力 (function calling / with_structured_output / Pydantic)
2. ノード内パース + 1〜2回同一再試行
3. Repair プロンプト（壊れた JSON を再出力要求）
4. 失敗時フォールバック固定プラン
5. 例外 → グラフ側リトライ (回数制限)
6. ログ & メトリクス (parse_fail 回数 / repair 成功率)

---

## 6. Pydantic Plan モデル例（要点）
- 未許可 retriever / tool を弾くバリデータ
- reason は短縮（トークン節約）
- 解析失敗でもフォールバックを返す (副作用回避)

---

## 7. メモリ自己維持フロー (self-maintenance-memories)
State キー:
- user_input
- memory_simplicity (0 / 500 / 1000 段階)
- known_words / unknown_words
- requested_memories
- require_more_memory (bool)
- new_terms / new_knowledge
- answer

条件:
- require_more_memory かつ memory_simplicity < 1000 → escalate ループ
- unknown_words はトークン抽出差集合
- update_memories: unknown_words から新規候補生成（書き込みは安全ゲート内）

---

## 8. Mermaid 図記法指針
- 互換性問題がある環境では note ブロックを避ける（旧バージョン）。
- 丸括弧直後の改行や `\n(` は避ける。
- 代替: ダッシュ矢印で擬似ノートノード。
- 必要最低限の装飾 → 後から段階的強化。

---

## 9. DB / マイグレーション運用

### 接続
- ドライバ: psycopg (新世代)  
  DATABASE_URL 形式: `postgresql+psycopg://user:pass@host:port/db`
- もし `postgresql://` が来たらコード側で `+psycopg` を付与（フォールバック）

### Alembic
- migrations/env.py で `from app.db import models` を必ず import（metadata 登録）。
- モデル追加時: autogenerate → 確認 → upgrade
- 起動時自動適用 (run_migrations) は単一インスタンス前提。本番複数なら Advisory Lock or 手動適用。

### 推奨 naming_convention (将来)
```
pk_%(table_name)s
ix_%(table_name)s_%(column_0_N_name)s
uq_%(table_name)s_%(column_0_N_name)s
fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s
```

### メモリ関連テーブル
- memories: id, title, content, source_url, memory_simplicity, created_at, updated_at
- memory_relations: parent_id, child_id, relation, created_at, updated_at
- インデックス: (memory_simplicity), title(unique)

---

## 10. 書き込み操作ガード
- LLM 公開ツールは読み取り & 無副作用のみ
- 書き込みは:
  1. 計画プラン生成 (LLM)
  2. サーバ側バリデーション / コスト & 権限チェック
  3. 実行 & ログ
  4. 結果を tool メッセージ風に再投入（必要なら）

---

## 11. リトライ & フォールバック階層
| レイヤ | 対象 | 戦略 |
|--------|------|------|
| ノード内 | JSON 形式崩れ | 再プロンプト / Repair |
| グラフ | 外部 I/O 失敗 | 条件付き再試行 (回数上限) |
| アプリ | DB 接続遅延 | 待機 (wait_for_db) |
| ユーザ通知 | 不可回復 | ログ + 簡易回答 |

---

## 12. ロギング / 監査
最低限記録:
- tool_calls 発生 (tool 名, 引数要約, 時刻)
- plan parse 修復回数
- retrieval 分岐選択結果
- ループ回数 (escalate increments)

---

## 13. セキュリティ / 安全
- ツール引数サイズ上限
- SQL / ファイル書き込み / 外部 POST 系はツール公開禁止
- 不明語からの自動新規メモリ作成はキュー or 人レビュー導線（将来）

---

## 14. 並列化ポリシ
- 並列枝数を設定 (例: 同時最大 3)
- 各枝はユニークキーに結果格納 (retr_docs_a, retr_docs_b, tool_outputs)
- merge ノードで空枝許容 / 失敗枝ログ

---

## 15. 将来拡張 TODO
- retrieval スコアリング再ランク (BM25 + Embedding ハイブリッド)
- new_terms 要約自動生成 (LLM few-shot)
- memories 圧縮 (冗長化検出→要約保存)
- ユースケース別 plan スキーマ (versioning)

---

## 16. 実装簡易チェックリスト
- [ ] DATABASE_URL が +psycopg 形式
- [ ] migrations/env.py で models import
- [ ] plan ノード: フォールバック実装済
- [ ] tool_calls ループ上限設定
- [ ] 書き込み操作は直接 tool 公開されていない
- [ ] Mermaid 図は note ブロック互換確保
- [ ] unknown_words 抽出は言語拡張余地あり
- [ ] run_migrations は多重起動競合なし（開発のみ自動）

---

## 17. 簡易サンプル (Plan Repair フロー擬似)
```
LLM 出力失敗 → retry(同一プロンプト)
  → 再失敗 → repair prompt
    → 失敗 → fallback {"use_retrieval": false,...}
```

---

## 18. 命名 / スタイル
- state キー: snake_case
- ノード名: 動詞または機能 (checking_need_more_memory_node)
- ツール名: 動詞 + 対象 (search_text, fetch_document, math_eval)

---

## 19. 依存ライブラリ最小方針
優先順: 標準ライブラリ > 軽量実装 > LangGraph/LangChain > 大型外部サービス

---

## 20. 例外処理方針
- 予期可能 (JSON parse, 外部 timeout) → キャッチ & state に error 記録
- 致命的 (DB 接続不能) → ログ後再試行 / 起動失敗
- 発生頻度計測でプロンプト / 設定調整

---

以上。追加・改訂時は本ファイルを更新し、PR で合意を得ること。