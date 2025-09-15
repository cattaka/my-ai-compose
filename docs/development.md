# 開発メモ: DB マイグレーション (Alembic + SQLAlchemy + psycopg)

## 前提
- ドライバ: `psycopg` (v3) を使用  
- 接続 URL 形式: `postgresql+psycopg://USER:PASS@HOST:PORT/DB`  
- モデルは `app/db/models/` に配置し `app/db/models/__init__.py` で import 集約  
- Alembic: `migrations/env.py` で `from app.db import models` を import して metadata 登録

---

## 初期セットアップ（最初の 1 回）

```bash
cd langchain-api
pip install -r requirements.txt
alembic init migrations           # 既にある場合は不要
# env.py を編集し:
#   from app.db.session import Base, DATABASE_URL
#   config.set_main_option("sqlalchemy.url", DATABASE_URL)
#   from app.db import models
alembic revision --autogenerate -m "init"
alembic upgrade head
```

---

## モデル変更フロー

```bash
# 1. app/db/models/*.py を修正（列追加など）
# 2. 生成
alembic revision --autogenerate -m "add <feature>"
# 3. 内容確認（不要/危険な操作が無いか）
alembic upgrade head
```

差分が検出されない場合:
- import 漏れ (models/__init__.py を確認)
- 既存 DEFAULT / server_default 変更は手書きが必要

---

## 代表コマンド

| 操作 | コマンド |
|------|----------|
| 最新適用 | `alembic upgrade head` |
| 1つ戻す | `alembic downgrade -1` |
| ベースへ戻す | `alembic downgrade base` |
| 履歴表示 | `alembic history --verbose` |
| 現在バージョン確認 | `alembic current` |
| 差分チェックのみ | `alembic revision --autogenerate -m test --splice` (生成後不要なら削除) |

---

## Docker 内での利用

Compose 設定例（環境変数）:
```yaml
environment:
  - DATABASE_URL=postgresql+psycopg://raguser:ragpass@postgres:5432/ragdb
```

起動時に自動適用したい場合:
- `app/startup` 内で `run_migrations()` を呼ぶ
- 複数レプリカを想定する本番ではロック（advisory lock）や CI/CD で手動適用を推奨

---

## run_migrations ユーティリティ（例）

```python
from alembic import command
from alembic.config import Config
from pathlib import Path

def run_migrations():
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(cfg, "head")
```

FastAPI 起動フック:
```python
@app.on_event("startup")
def on_startup():
    wait_for_db()
    run_migrations()
```

簡易 DB 待機:
```python
def wait_for_db():
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    for _ in range(15):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError:
            time.sleep(2)
    raise RuntimeError("DB not ready")
```

---

## psycopg2 を避ける理由
- `psycopg[binary]` はビルド不要
- URL が `postgresql://` だと自動で `psycopg2` を試すため `postgresql+psycopg://` を強制
- セッション初期化で受け取った URL に `+psycopg` を付けるフォールバック実装済み

---

## よくあるエラーと対処

| 症状 | 原因 | 対処 |
|------|------|------|
| revision 生成でテーブルが無視 | モデル未 import | `app/db/models/__init__.py` と `env.py` の import |
| psycopg2 ModuleNotFoundError | URL スキーム誤り | `postgresql+psycopg://` に変更 |
| updated_at が更新されない | onupdate のみ / DB トリガ無し | SQLAlchemy 経由で UPDATE される経路確認 |

---

## 命名規約 (任意導入)
`session.py`:
```python
NAMING_CONVENTION = {
  "pk": "pk_%(table_name)s",
  "ix": "ix_%(table_name)s_%(column_0_N_name)s",
  "uq": "uq_%(table_name)s_%(column_0_N_name)s",
  "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
}
```

---

## Rollback 指針
- 重要な破壊的変更は 1 リビジョン = 1 意図
- 破壊操作（列削除, 型変更）は事前に nullable 追加→移行→削除の2段階に分ける

---

## チェックリスト
- [ ] DATABASE_URL が +psycopg
- [ ] models/__init__.py に全モデル import
- [ ] env.py で models import
- [ ] autogenerate 差分を毎回レビュー
- [ ] 本番は自動 upgrade の多重実行を防止

---

## Self-Maintenance Memories フロー開発メモ (更新)

最新フローは self-maintenance-memories.md / *.mermaid を参照。

### 実行例 (LangGraph)

```python
from sqlalchemy.ext.asyncio import AsyncSession
from app.graph.self_maintenance_memories_graph import get_memory_graph

async def run_flow(session: AsyncSession, text: str):
    graph = get_memory_graph()
    init_state = {
        "user_text": text,
        "memory_simplicity": 0,
        "max_memory_simplicity": 1000,
    }
    result = await graph.ainvoke(
        init_state,
        config={"configurable": {"session": session}}  # session 注入
    )
    return {
        "answer": result.get("answer"),
        "updated_words": result.get("updated_words"),
        "updated_memories": result.get("updated_memories"),
    }
```