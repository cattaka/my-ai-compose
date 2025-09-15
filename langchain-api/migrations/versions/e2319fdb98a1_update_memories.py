"""update memories

Revision ID: e2319fdb98a1
Revises: f2a19b009b45
Create Date: 2025-09-15 12:20:19.385295

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2319fdb98a1'
down_revision: Union[str, Sequence[str], None] = 'f2a19b009b45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'memories',
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index('ix_memories_deleted_at', 'memories', ['deleted_at'])


def downgrade() -> None:
    op.drop_index('ix_memories_deleted_at', table_name='memories')
    op.drop_column('memories', 'deleted_at')
