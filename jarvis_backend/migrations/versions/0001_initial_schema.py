"""Initial schema for JARVIS memory database.

Creates the conversations, conversations_fts (FTS5), sessions, notes,
and mail_sessions tables that MemoryManager expects.
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- conversations ---
    op.create_table(
        "conversations",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, nullable=True),
        sa.Column("role", sa.String, nullable=True),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("timestamp", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("metadata", sa.Text, nullable=True),
    )

    # --- conversations_fts (FTS5) ---
    op.execute("""
        CREATE VIRTUAL TABLE conversations_fts USING fts5(
            content, role, session_id
        )
        """)

    # --- sessions ---
    op.create_table(
        "sessions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_active", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("metadata", sa.Text, nullable=True),
    )

    # --- notes ---
    op.create_table(
        "notes",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, nullable=True),
        sa.Column("title", sa.String, nullable=True),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("tags", sa.Text, nullable=True),
    )

    # --- mail_sessions ---
    op.create_table(
        "mail_sessions",
        sa.Column("token", sa.String, primary_key=True),
        sa.Column("email_address", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mail_sessions")
    op.drop_table("notes")
    op.drop_table("sessions")
    op.execute("DROP TABLE conversations_fts")
    op.drop_table("conversations")
