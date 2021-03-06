"""empty message

Revision ID: 498ab45bc92d
Revises: d606efcaf6a6
Create Date: 2016-07-10 22:40:29.920714

"""

# revision identifiers, used by Alembic.
revision = '498ab45bc92d'
down_revision = 'd606efcaf6a6'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(u'practice_student_id_fkey', 'practice', type_='foreignkey')
    op.create_foreign_key(None, 'practice', 'student', ['student_id'], ['id'], onupdate='CASCADE', ondelete='CASCADE')
    op.drop_constraint(u'reminder_student_id_fkey', 'reminder', type_='foreignkey')
    op.create_foreign_key(None, 'reminder', 'student', ['student_id'], ['id'], onupdate='CASCADE', ondelete='CASCADE')
    op.drop_constraint(u'veritas_account_student_id_fkey', 'veritas_account', type_='foreignkey')
    op.create_foreign_key(None, 'veritas_account', 'student', ['student_id'], ['id'], onupdate='CASCADE', ondelete='CASCADE')
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'veritas_account', type_='foreignkey')
    op.create_foreign_key(u'veritas_account_student_id_fkey', 'veritas_account', 'student', ['student_id'], ['id'])
    op.drop_constraint(None, 'reminder', type_='foreignkey')
    op.create_foreign_key(u'reminder_student_id_fkey', 'reminder', 'student', ['student_id'], ['id'])
    op.drop_constraint(None, 'practice', type_='foreignkey')
    op.create_foreign_key(u'practice_student_id_fkey', 'practice', 'student', ['student_id'], ['id'])
    ### end Alembic commands ###
