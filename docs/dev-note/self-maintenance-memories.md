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

- fetch_wellknown_words_node: 初期値
  - state
    - $memory_simplicity = 0
    - $wellknown_words
      - SELECT title FROM memories WHERE memory_simplicity <= 0
    - $word_meanings = []
  - 次のノード
    - ask_word_meanings_node
- ask_word_meanings_node: 意味が必要な単語の確認
  - input
    - ユーザの入力したテキスト
    - $wellknown_words
  - output
    - $requested_words: 意味の要求が必要な単語のリスト
  - 次のノード
    ask_more_word_meanings_node
- fetch_word_meanings_node
  - 処理
    - $word_meanings
      - SELECT title, content FROM memories WHERE title IN ($requested_words) AND memory_simplicity <= $memory_simplicity
  - 次のノード
    ask_more_word_meanings_node
- ask_more_word_meanings_node: 単語の意味を付加した状態での入力
  - input
    - ユーザの入力したテキスト
    - $wellknown_words
    - $word_meanings
  - output
    - $answer: 回答
    - $requested_words: 意味の要求が必要な単語のリスト
    - require_more_memory: 回答を生成するのに十分な情報があるか？
  - 次のノード
    - if need_more_memory_node == true || $memory_simplicity >= 1000
      - $memory_simplicity += 500
      - ask_more_word_meanings_node に改めて遷移する
    - else
      - ask_updated_memories_node に遷移する
- ask_updated_memories_node
  - input
    - ユーザの入力したテキスト
    - $wellknown_words
    - $word_meanings
  - output
    - $updated_words: 追加や更新が必要な単語のリスト
      - list of (title, content)
    - $updated_memories: 追加や更新が必要な理解した知識のリスト
      - list of (title, content, list of 親となるmemories)
  - 次のノード
    - save_updated_memories_node
- save_updated_memories_node
  - 処理
    - $updated_words: memoriesテーブルに反映する
    - $updated_memories: memoriesテーブルに反映する
  - 次のノード
    - finalize_node
- finalize_node: 回答の生成
  - output
    - $answer
    - 意味の解釈に疑念が残る単語や理解した知識
