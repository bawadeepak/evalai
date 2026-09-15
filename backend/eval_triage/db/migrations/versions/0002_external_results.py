"""external results imported from Inspect and Promptfoo

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-16 08:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import eval_triage.db.types

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXTERNAL_TABLES = ("external_imports", "external_results")


def upgrade() -> None:
    op.create_table('external_imports',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('plugin', sa.String(length=40), nullable=False),
    sa.Column('plugin_version', sa.String(length=40), nullable=False),
    sa.Column('source_version', sa.String(length=80), nullable=True),
    sa.Column('source_identity', sa.JSON(), nullable=False),
    sa.Column('artifact_hash', sa.String(length=64), nullable=False),
    sa.Column('filename', sa.String(length=300), nullable=True),
    sa.Column('summary', sa.JSON(), nullable=False),
    sa.Column('warnings', sa.JSON(), nullable=False),
    sa.Column('is_demo', sa.Boolean(), nullable=False),
    sa.Column('created_at', eval_triage.db.types.UTCDateTime(length=32), nullable=False),
    sa.ForeignKeyConstraint(['artifact_hash'], ['artifacts.content_hash'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('external_imports', schema=None) as batch_op:
        batch_op.create_index('ix_external_import_project', ['project_id', 'created_at'], unique=False)

    op.create_table('external_results',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('import_id', sa.String(length=36), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('upstream_id', sa.String(length=200), nullable=False),
    sa.Column('case_external_id', sa.String(length=200), nullable=True),
    sa.Column('epoch', sa.Integer(), nullable=True),
    sa.Column('provider', sa.String(length=200), nullable=True),
    sa.Column('input', sa.JSON(), nullable=False),
    sa.Column('expected', sa.JSON(), nullable=True),
    sa.Column('output', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('assertions', sa.JSON(), nullable=False),
    sa.Column('scores', sa.JSON(), nullable=False),
    sa.Column('error', sa.JSON(), nullable=True),
    sa.Column('extra', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['import_id'], ['external_imports.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('import_id', 'ordinal', name='uq_external_result_ordinal')
    )

    from eval_triage.db.migrate import immutable_trigger_ddl

    for statement in immutable_trigger_ddl(EXTERNAL_TABLES):
        op.execute(statement)


def downgrade() -> None:
    from eval_triage.db.migrate import drop_immutable_trigger_ddl

    for statement in drop_immutable_trigger_ddl(EXTERNAL_TABLES):
        op.execute(statement)
    op.drop_table('external_results')
    with op.batch_alter_table('external_imports', schema=None) as batch_op:
        batch_op.drop_index('ix_external_import_project')
    op.drop_table('external_imports')
