"""add chat attachments

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-20 11:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    msg_type = sa.Enum("text", "image", "voice", "file", name="messagetype")
    msg_type.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "messages",
        sa.Column("type", msg_type, nullable=False, server_default="text"),
    )
    op.add_column("messages", sa.Column("attachment_path", sa.String(length=300), nullable=True))
    op.add_column("messages", sa.Column("attachment_name", sa.String(length=200), nullable=True))
    op.add_column("messages", sa.Column("attachment_mime", sa.String(length=100), nullable=True))
    op.add_column("messages", sa.Column("attachment_size", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("duration_sec", sa.Integer(), nullable=True))
    op.alter_column("messages", "text", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE messages SET text = '' WHERE text IS NULL")
    op.alter_column("messages", "text", existing_type=sa.Text(), nullable=False)
    op.drop_column("messages", "duration_sec")
    op.drop_column("messages", "attachment_size")
    op.drop_column("messages", "attachment_mime")
    op.drop_column("messages", "attachment_name")
    op.drop_column("messages", "attachment_path")
    op.drop_column("messages", "type")
    sa.Enum("text", "image", "voice", "file", name="messagetype").drop(
        op.get_bind(), checkfirst=True
    )
