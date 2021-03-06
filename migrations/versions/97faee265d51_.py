"""empty message

Revision ID: 97faee265d51
Revises: 069f0ca00172
Create Date: 2016-08-09 23:54:29.205993

"""

# revision identifiers, used by Alembic.
revision = '97faee265d51'
down_revision = '069f0ca00172'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table('audit_event',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('type', sa.String(), nullable=True),
    sa.Column('data', postgresql.JSONB(), nullable=True),
    sa.Column('student_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['student_id'], ['student.id'], onupdate='CASCADE', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_event_student_id'), 'audit_event', ['student_id'], unique=False)
    op.drop_column(u'practice', 'app_version')
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.add_column(u'practice', sa.Column('app_version', sa.VARCHAR(), autoincrement=False, nullable=True))
    op.drop_index(op.f('ix_audit_event_student_id'), table_name='audit_event')
    op.drop_table('audit_event')
    ### end Alembic commands ###
