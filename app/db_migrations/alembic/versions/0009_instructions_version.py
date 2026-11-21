"""Add the nullable instructions_version label to ai_requests (spec 4.1, D-36)."""

import sqlalchemy as sa
from alembic import op

revision = "0009_instructions_version"
down_revision = "0008_ai_platform"
branch_labels = None
depends_on = None

INSTRUCTIONS_VERSION_RULE = (
    "instructions_version IS NULL OR (char_length(instructions_version) BETWEEN 1 AND 64 "
    "AND instructions_version ~ '^[A-Za-z0-9._:-]+$')"
)


def upgrade() -> None:
    op.add_column("ai_requests", sa.Column("instructions_version", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_ai_requests_instructions_version"), "ai_requests", INSTRUCTIONS_VERSION_RULE
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_ai_requests_instructions_version"), "ai_requests", type_="check")
    op.drop_column("ai_requests", "instructions_version")
