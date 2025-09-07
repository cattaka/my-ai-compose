## self-maintenance-memories

## テーブル

- memories
  - id: int
  - title: string
    - 単語の場合はシンプルにその単語が入る。文章の場合はサマライズしたものを入れる。
  - content: string
    - 単語の場合は意味を簡潔にして入れる。文章の場合はそのまま文を入れる。
  - source_url: string
    - 外部から取り込まれたものについてはurlを入れる。
  - memory_simplicity: int
    - その記憶の簡潔の数値。初期設計では0, 500, 1000のみを使用する
      - 0: 単語。LLMによって登録された単語。
      - 500: 理解した知識。LLMによって導出されたデータ。自由に更新できる。
      - 1000: 生データ。外部から取り込まれたデータ、出典が更新されない限り更新しない。
  - updated_at: datetime
  - created_at: datetime
- memory_relations: memories間の関係。
  - parent_memory_id: int foreign key
  - parent_memory_id: int foreign key
  - updated_at: datetime
  - created_at: datetime

## LangGraph

- initial_node: 初期値
  - state
    - $memory_simplicity = 0
    - $wellknown_words
      - SELECT title FROM memories WHERE memory_simplicity <= 0
    - $unknown_words = []
  - 次のノード
    - checking_unknown_words_node
- checking_unknown_words_node: 意味が必要な単語の確認
  - input
    - ユーザの入力したテキスト
    - $wellknown_words
  - output
    - $unknown_words: 意味の要求が必要な単語のリスト
  - 次のノード
    checking_need_more_memory_node
- checking_need_more_memory_node: 単語の意味を付加した状態での入力
  - 前処理
    - $requested_memories
      - SELECT title, content FROM memories WHERE memory_simplicity <= $memory_simplicity
  - input
    - ユーザの入力したテキスト
    - $wellknown_words
    - $requested_memories
  - output
    - $unknown_words: 意味の要求が必要な単語のリスト
    - require_more_memory: 回答を生成するのに十分な情報があるか？
  - 次のノード
    - if need_more_memory_node == true || $memory_simplicity >= 1000
      - $memory_simplicity += 500
      - checking_need_more_memory_node に改めて遷移する
    - else
      - answer_node に遷移する
- update_memories
  - input
    - ユーザの入力したテキスト
    - $wellknown_words
    - $requested_memories
  - output
    - 追加や更新が必要な単語のリスト
      - list of (title, content)
    - 追加や更新が必要な理解した知識のリスト
      - list of (title, content, list of 親となるmemories)
  - 次のノード
    - answer_node
- answer_node: 回答の生成
  - input
    - ユーザの入力したテキスト
    - $wellknown_words
    - $requested_memories
  - output
    - LLMが生成する
    - 意味の解釈に疑念が残る単語や理解した知識
