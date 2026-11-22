"""Add public profile settings (search engines and AI agents)

Revision ID: e4a91c7d2b6f
Revises: 7b2e4d9f1a6c
Create Date: 2026-11-22 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "e4a91c7d2b6f"
down_revision: str | Sequence[str] | None = "7b2e4d9f1a6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEXT_COLUMNS = ("full_name", "headline", "profile_links", "seo_description")


def upgrade() -> None:
    # sitesettings is created by create_all on startup; a fresh database gets
    # these columns then.
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("sitesettings"):
        return
    existing = {c["name"] for c in inspector.get_columns("sitesettings")}
    for name in TEXT_COLUMNS:
        if name not in existing:
            op.add_column(
                "sitesettings",
                sa.Column(
                    name,
                    sqlmodel.sql.sqltypes.AutoString(),
                    nullable=False,
                    server_default="",
                ),
            )
    if "hide_public_contact" not in existing:
        op.add_column(
            "sitesettings",
            sa.Column(
                "hide_public_contact",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("sitesettings") as batch:
        batch.drop_column("hide_public_contact")
        for name in reversed(TEXT_COLUMNS):
            batch.drop_column(name)
