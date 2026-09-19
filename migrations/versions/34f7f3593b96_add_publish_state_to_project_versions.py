"""add publish state to project_versions

Revision ID: 34f7f3593b96
Revises: 00e2d7607eb9
Create Date: 2026-09-19 16:12:19.914805

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '34f7f3593b96'
down_revision: Union[str, None] = '00e2d7607eb9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('project_versions', sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('project_versions', sa.Column('published_at', sa.DateTime(), nullable=True))
    op.add_column('project_versions', sa.Column('published_by', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_project_versions_published_by', 'project_versions', 'users',
        ['published_by'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_project_versions_published_by', 'project_versions', type_='foreignkey')
    op.drop_column('project_versions', 'published_by')
    op.drop_column('project_versions', 'published_at')
    op.drop_column('project_versions', 'is_published')
