"""Sync DB with Models

Revision ID: 001
Revises:
Create Date: 2025-10-05 11:28:41.772294

"""

from enum import Enum
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


class EventCallbackStatus(Enum):
    ACTIVE = 'ACTIVE'
    DISABLED = 'DISABLED'
    COMPLETED = 'COMPLETED'
    ERROR = 'ERROR'


def upgrade() -> None:
    """Upgrade schema."""
    # For SQLite compatibility, use batch_alter_table with separate operations
    # to avoid circular dependency issues
    with op.batch_alter_table('event_callback', recreate='always') as batch_op:
        batch_op.add_column(
            sa.Column(
                'status',
                sa.Enum(EventCallbackStatus),
                nullable=False,
                server_default='ACTIVE',
            ),
        )
        batch_op.add_column(
            sa.Column(
                'updated_at', sa.DateTime, nullable=False, server_default=sa.func.now()
            ),
        )

    # Handle event_callback_result changes separately
    op.drop_index('ix_event_callback_result_event_id')
    with op.batch_alter_table('event_callback_result', recreate='always') as batch_op:
        batch_op.drop_column('event_id')
        batch_op.add_column(sa.Column('event_id', sa.String, nullable=True))
    op.create_index(
        op.f('ix_event_callback_result_event_id'),
        'event_callback_result',
        ['event_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('event_callback', recreate='always') as batch_op:
        batch_op.drop_column('status')
        batch_op.drop_column('updated_at')

    op.drop_index('ix_event_callback_result_event_id')
    with op.batch_alter_table('event_callback_result', recreate='always') as batch_op:
        batch_op.drop_column('event_id')
        batch_op.add_column(sa.Column('event_id', sa.UUID, nullable=True))
    op.create_index(
        op.f('ix_event_callback_result_event_id'),
        'event_callback_result',
        ['event_id'],
        unique=False,
    )
