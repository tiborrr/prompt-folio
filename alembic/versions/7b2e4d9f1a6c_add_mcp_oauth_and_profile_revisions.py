"""Add OAuth tables for the MCP server and profile revisions

Revision ID: 7b2e4d9f1a6c
Revises: c3f1a7d2e9b4
Create Date: 2026-11-20 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "7b2e4d9f1a6c"
down_revision: str | Sequence[str] | None = "c3f1a7d2e9b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # The app also runs create_all on startup, so a table can already exist
    if not inspector.has_table("oauthclient"):
        op.create_table(
            "oauthclient",
            sa.Column("client_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("data", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("client_id"),
        )
    if not inspector.has_table("oauthtoken"):
        op.create_table(
            "oauthtoken",
            sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("client_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("grant_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("expires_at", sa.Integer(), nullable=False),
            sa.Column("data", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("token_hash"),
        )
        op.create_index("ix_oauthtoken_kind", "oauthtoken", ["kind"])
        op.create_index("ix_oauthtoken_client_id", "oauthtoken", ["client_id"])
        op.create_index("ix_oauthtoken_grant_id", "oauthtoken", ["grant_id"])
        op.create_index("ix_oauthtoken_expires_at", "oauthtoken", ["expires_at"])
    if not inspector.has_table("profilerevision"):
        op.create_table(
            "profilerevision",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("context", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_profilerevision_created_at", "profilerevision", ["created_at"]
        )


def downgrade() -> None:
    op.drop_table("profilerevision")
    op.drop_table("oauthtoken")
    op.drop_table("oauthclient")
