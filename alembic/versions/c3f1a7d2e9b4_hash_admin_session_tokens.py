"""Hash admin session tokens

Revision ID: c3f1a7d2e9b4
Revises: 95069374a6e7
Create Date: 2026-11-11 21:00:00.000000

Admin sessions used the admin password itself as token. Tokens are now random
and stored as SHA-256 hashes, so the old rows (which hold the plaintext
password) are deleted; the admin logs in once more after this deploy.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f1a7d2e9b4"
down_revision: Union[str, Sequence[str], None] = "95069374a6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if sa.inspect(op.get_bind()).has_table("adminsession"):
        op.execute("DELETE FROM adminsession")


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to restore: the deleted sessions only force a new login
