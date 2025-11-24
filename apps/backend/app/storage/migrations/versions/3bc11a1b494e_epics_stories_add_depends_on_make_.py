from alembic import op
import sqlalchemy as sa

revision = '3bc11a1b494e'
down_revision = '9a6c27df1080'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name
    # Postgres requires explicit cast for JSON defaults
    json_default = sa.text("'[]'::jsonb") if dialect == "postgresql" else "[]"

    # --- EPICS ---
    with op.batch_alter_table('epics') as batch_op:
        # add depends_on with a temporary server default to pass NOT NULL
        batch_op.add_column(sa.Column('depends_on', sa.JSON(), server_default=json_default, nullable=False))

    # backfill priority_rank if the column exists and has NULLs (safe no-op if none)
    op.execute("UPDATE epics SET priority_rank = 1 WHERE priority_rank IS NULL")

    # Optional: drop the server default after data is consistent
    if dialect != "sqlite":  # SQLite can be finicky about altering defaults; safe to keep
        with op.batch_alter_table('epics') as batch_op:
            batch_op.alter_column('depends_on', server_default=None)

    # --- STORIES ---
    with op.batch_alter_table('stories') as batch_op:
        # add depends_on with temporary server default, NOT NULL
        batch_op.add_column(sa.Column('depends_on', sa.JSON(), server_default=json_default, nullable=False))

    # backfill stories.priority_rank before enforcing NOT NULL
    op.execute("UPDATE stories SET priority_rank = 1 WHERE priority_rank IS NULL")

    with op.batch_alter_table('stories') as batch_op:
        batch_op.alter_column('priority_rank', existing_type=sa.Integer(), nullable=False)
        batch_op.create_index('ix_stories_run_epic_rank', ['run_id', 'epic_id', 'priority_rank'], unique=False)

    # Optional: drop server default on stories.depends_on
    if dialect != "sqlite":
        with op.batch_alter_table('stories') as batch_op:
            batch_op.alter_column('depends_on', server_default=None)

    # NOTE: If you do NOT already have epics index (models define it), add it here:
    # op.create_index('ix_epics_run_rank', 'epics', ['run_id', 'priority_rank'], unique=False)

def downgrade():
    # If you created ix_epics_run_rank in upgrade(), drop it here first.
    with op.batch_alter_table('stories') as batch_op:
        batch_op.drop_index('ix_stories_run_epic_rank')
        batch_op.alter_column('priority_rank', existing_type=sa.Integer(), nullable=True)
        batch_op.drop_column('depends_on')

    with op.batch_alter_table('epics') as batch_op:
        batch_op.drop_column('depends_on')
