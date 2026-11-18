"""Create scans and spatial features."""

from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("""
        CREATE TABLE scans (
            id UUID PRIMARY KEY,
            filename TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'awaiting_upload'
                CHECK (status IN ('awaiting_upload', 'queued', 'done', 'failed')),
            object_version TEXT,
            point_count INTEGER,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE features (
            scan_id UUID PRIMARY KEY REFERENCES scans(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            location GEOMETRY(PointZ, 26918) NOT NULL,
            height_m DOUBLE PRECISION NOT NULL
        )
    """)
    op.execute("CREATE INDEX features_location_idx ON features USING GIST (location)")


def downgrade() -> None:
    op.execute("DROP TABLE features")
    op.execute("DROP TABLE scans")
