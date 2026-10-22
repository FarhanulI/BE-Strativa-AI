"""Enable case-insensitive text for the tenancy foundation."""

from alembic import op

revision = "0004_citext"
down_revision = "0003_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS citext")