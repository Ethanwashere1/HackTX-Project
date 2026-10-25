"""one profile per person; per-event match data on event_members; social_lookups cache.

- profiles: one row per user (unique user_id), shared across events, plus `socials`.
  Existing per-event rows collapse to one per user (the one with a summary, else the newest).
- event_members: gains profile_text, embedding vector(768), embedded_at, snowflake_synced_at
  (copied from the old per-event profile) and loses socials (merged into the user's profile,
  later joins replacing handles of the same kind).
- social_lookups: SerpAPI cache, unique (kind, handle).

Downgrade rebuilds one profile per event membership from the person profile.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24 23:30:00
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _merge_socials(current: list[dict], submitted: list[dict]) -> list[dict]:
    """Same rule as the join: submitted kinds replace the existing handles of that kind."""
    kinds = {s.get("kind") for s in submitted}
    return [s for s in current if s.get("kind") not in kinds] + list(submitted)


def upgrade() -> None:
    conn = op.get_bind()

    # event_members: per-event match data.
    op.add_column('event_members', sa.Column(
        'profile_text', sqlmodel.sql.sqltypes.AutoString(), server_default='', nullable=False))
    op.add_column('event_members', sa.Column('embedding', Vector(768), nullable=True))
    op.add_column('event_members', sa.Column('embedded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('event_members', sa.Column(
        'snowflake_synced_at', sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE event_members m SET profile_text = p.profile_text, embedding = p.embedding,"
        " embedded_at = p.embedded_at"
        " FROM profiles p WHERE p.event_id = m.event_id AND p.user_id = m.user_id"
    )

    # profiles: keep one row per user.
    op.add_column('profiles', sa.Column(
        'socials', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.execute(
        "DELETE FROM profiles p USING ("
        "  SELECT id, row_number() OVER (PARTITION BY user_id"
        "    ORDER BY (summary IS NOT NULL) DESC, updated_at DESC, id DESC) AS rn FROM profiles"
        ") r WHERE p.id = r.id AND r.rn > 1"
    )
    op.drop_constraint('fk_profiles_event_member', 'profiles', type_='foreignkey')
    op.drop_constraint('uq_profiles_event_user', 'profiles', type_='unique')
    op.drop_index(op.f('ix_profiles_user_id'), table_name='profiles')
    op.drop_column('profiles', 'event_id')  # also drops its FK to events
    op.drop_column('profiles', 'profile_text')
    op.drop_column('profiles', 'embedding')
    op.drop_column('profiles', 'embedded_at')
    op.create_unique_constraint('uq_profiles_user', 'profiles', ['user_id'])
    # Members without a profile row (none expected) get an empty one.
    op.execute(
        "INSERT INTO profiles (id, user_id, traits, transcript, socials, updated_at)"
        " SELECT DISTINCT ON (m.user_id) 'prf_' || substr(md5(m.user_id), 1, 26), m.user_id,"
        "  '{}', '[]', '[]', now()"
        " FROM event_members m WHERE NOT EXISTS (SELECT 1 FROM profiles p WHERE p.user_id = m.user_id)"
    )

    # Move event_members.socials onto the profile, oldest join first.
    merged: dict[str, list[dict]] = {}
    for user_id, socials in conn.execute(sa.text(
        "SELECT user_id, socials FROM event_members ORDER BY joined_at, id"
    )):
        merged[user_id] = _merge_socials(merged.get(user_id, []), socials or [])
    for user_id, socials in merged.items():
        conn.execute(
            sa.text("UPDATE profiles SET socials = CAST(:s AS jsonb) WHERE user_id = :u"),
            {"s": json.dumps(socials), "u": user_id},
        )
    op.alter_column('profiles', 'socials', server_default=None)
    op.drop_column('event_members', 'socials')

    op.create_table('social_lookups',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('handle', sqlmodel.sql.sqltypes.AutoString(length=300), nullable=False),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False),
    sa.Column('notes', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('ok', 'failed')", name='ck_social_lookups_status'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kind', 'handle', name='uq_social_lookups_kind_handle')
    )


def downgrade() -> None:
    op.drop_table('social_lookups')

    # event_members.socials back from the person profile.
    op.add_column('event_members', sa.Column(
        'socials', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.execute(
        "UPDATE event_members m SET socials = p.socials FROM profiles p WHERE p.user_id = m.user_id"
    )
    op.alter_column('event_members', 'socials', server_default=None)

    # profiles: one row per event membership again.
    op.drop_constraint('uq_profiles_user', 'profiles', type_='unique')
    op.add_column('profiles', sa.Column('event_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('profiles', sa.Column(
        'profile_text', sqlmodel.sql.sqltypes.AutoString(), server_default='', nullable=False))
    op.add_column('profiles', sa.Column('embedding', Vector(768), nullable=True))
    op.add_column('profiles', sa.Column('embedded_at', sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "INSERT INTO profiles (id, event_id, user_id, summary, traits, transcript,"
        " interview_input_mode, social_notes, socials, profile_text, embedding, embedded_at, updated_at)"
        " SELECT 'prf_' || substr(md5(m.id), 1, 26), m.event_id, m.user_id, p.summary,"
        "  COALESCE(p.traits, '{}'), COALESCE(p.transcript, '[]'), p.interview_input_mode,"
        "  p.social_notes, '[]', m.profile_text, m.embedding, m.embedded_at,"
        "  COALESCE(p.updated_at, m.joined_at)"
        " FROM event_members m LEFT JOIN profiles p ON p.user_id = m.user_id AND p.event_id IS NULL"
    )
    op.execute("DELETE FROM profiles WHERE event_id IS NULL")
    op.alter_column('profiles', 'profile_text', server_default=None)
    op.alter_column('profiles', 'event_id', nullable=False)
    op.drop_column('profiles', 'socials')
    op.create_foreign_key(
        'profiles_event_id_fkey', 'profiles', 'events', ['event_id'], ['id'], ondelete='CASCADE')
    op.create_unique_constraint('uq_profiles_event_user', 'profiles', ['event_id', 'user_id'])
    op.create_foreign_key(
        'fk_profiles_event_member', 'profiles', 'event_members',
        ['event_id', 'user_id'], ['event_id', 'user_id'], ondelete='CASCADE')
    op.create_index(op.f('ix_profiles_user_id'), 'profiles', ['user_id'], unique=False)

    op.drop_column('event_members', 'snowflake_synced_at')
    op.drop_column('event_members', 'embedded_at')
    op.drop_column('event_members', 'embedding')
    op.drop_column('event_members', 'profile_text')
