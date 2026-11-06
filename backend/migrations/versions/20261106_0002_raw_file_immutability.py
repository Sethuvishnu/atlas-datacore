"""raw_data_files immutability

Original source files are evidence. Block deletion of registry rows and any change to the
fields that identify the stored bytes. import_status may still change (PENDING -> SUCCEEDED...).

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION raw_data_files_protect() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'raw_data_files rows are immutable evidence and cannot be deleted (id=%)', OLD.id;
      END IF;
      IF NEW.checksum IS DISTINCT FROM OLD.checksum
         OR NEW.storage_path IS DISTINCT FROM OLD.storage_path
         OR NEW.filename IS DISTINCT FROM OLD.filename
         OR NEW.source_id IS DISTINCT FROM OLD.source_id
         OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes THEN
        RAISE EXCEPTION 'raw_data_files identity fields are immutable (id=%)', OLD.id;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    CREATE TRIGGER trg_raw_data_files_protect
    BEFORE UPDATE OR DELETE ON raw_data_files
    FOR EACH ROW EXECUTE FUNCTION raw_data_files_protect();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_raw_data_files_protect ON raw_data_files")
    op.execute("DROP FUNCTION IF EXISTS raw_data_files_protect()")
