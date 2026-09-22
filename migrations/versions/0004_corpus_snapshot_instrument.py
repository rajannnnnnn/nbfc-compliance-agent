"""corpus_snapshot, regulation_instrument, regulation_supersession

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE corpus_snapshot (
            id                  uuid PRIMARY KEY,
            created_at          timestamptz NOT NULL DEFAULT now(),
            instrument_manifest jsonb NOT NULL,
            embedding_model     text  NOT NULL,
            embedding_dimension int   NOT NULL,
            parser_version      text  NOT NULL,
            chunk_count         int   NOT NULL,
            is_active           boolean NOT NULL DEFAULT false,
            notes               text
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_snapshot_active ON corpus_snapshot (is_active) WHERE is_active")

    op.execute(
        """
        CREATE TABLE regulation_instrument (
            id                        uuid PRIMARY KEY,
            snapshot_id               uuid NOT NULL REFERENCES corpus_snapshot(id) ON DELETE CASCADE,
            code                      text NOT NULL,
            official_title            text NOT NULL,
            circular_number           text,
            notification_id           text,
            issued_on                 date,
            effective_from            date,
            effective_to              date,
            status                    instrument_status   NOT NULL,
            applies_to_entity_types   entity_type[]       NOT NULL DEFAULT '{nbfc}',
            citable                   boolean             NOT NULL DEFAULT true,
            verification_status       verification_status NOT NULL,
            verification_note         text,
            source_url                text NOT NULL,
            source_sha256             char(64) NOT NULL,
            retrieved_at              timestamptz NOT NULL,
            page_count                int,
            parser_version            text NOT NULL,
            superseded_by_code        text,
            UNIQUE (snapshot_id, code)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE regulation_supersession (
            id                        uuid PRIMARY KEY,
            snapshot_id               uuid NOT NULL REFERENCES corpus_snapshot(id) ON DELETE CASCADE,
            superseding_instrument_id uuid NOT NULL REFERENCES regulation_instrument(id) ON DELETE CASCADE,
            superseded_circular_number text NOT NULL,
            superseded_title          text NOT NULL,
            superseded_on             date NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS regulation_supersession")
    op.execute("DROP TABLE IF EXISTS regulation_instrument")
    op.execute("DROP INDEX IF EXISTS uq_snapshot_active")
    op.execute("DROP TABLE IF EXISTS corpus_snapshot")
