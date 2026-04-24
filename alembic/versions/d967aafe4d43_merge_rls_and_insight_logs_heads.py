"""merge rls and insight_logs heads

Revision ID: d967aafe4d43
Revises: b2c3d4e5f6a7, f6a7b8c9d0e1
Create Date: 2026-04-24 08:57:59.066136

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd967aafe4d43'
down_revision: Union[str, None] = ('b2c3d4e5f6a7', 'f6a7b8c9d0e1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
