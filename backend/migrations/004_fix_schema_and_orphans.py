"""
Zero-data-loss migration script:
1. Extends matrix_snapshots with batch_stem_id.
2. Recovers orphaned session references in annotation_sessions so no legacy data is lost.
3. Migrates negative-ID pseudo-sessions to real batch_stem_id foreign keys.
4. Makes session_id nullable where appropriate and enforces mutual exclusivity (session_id XOR batch_stem_id).
5. Adds partial unique constraints and restores all foreign key constraints with ON DELETE CASCADE.
All operations execute inside a single transactional block to ensure ACID atomicity.
"""

import asyncio
import os
import sys
from dotenv import load_dotenv
import asyncpg

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

async def run_migration():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set in environment or .env")
        sys.exit(1)

    print("Connecting to database...")
    conn = await asyncpg.connect(DATABASE_URL)

    try:
        # Pre-check row counts
        counts_before = {
            "annotation_sessions": await conn.fetchval("SELECT count(*) FROM annotation_sessions"),
            "matrix_snapshots": await conn.fetchval("SELECT count(*) FROM matrix_snapshots"),
            "relations": await conn.fetchval("SELECT count(*) FROM relations"),
            "spans": await conn.fetchval("SELECT count(*) FROM spans"),
            "batch_stems": await conn.fetchval("SELECT count(*) FROM batch_stems"),
            "batches": await conn.fetchval("SELECT count(*) FROM batches"),
            "stems": await conn.fetchval("SELECT count(*) FROM stems"),
            "users": await conn.fetchval("SELECT count(*) FROM users"),
            "auth_sessions": await conn.fetchval("SELECT count(*) FROM auth_sessions"),
        }
        print("Pre-migration row counts:", counts_before)

        async with conn.transaction():
            print("Beginning migration transaction...")

            # 1. Recover orphan session IDs in spans/relations/snapshots before adding FKs
            missing_sessions = await conn.fetch("""
                SELECT DISTINCT s_id FROM (
                    SELECT session_id AS s_id FROM spans WHERE session_id > 0
                    UNION
                    SELECT session_id AS s_id FROM relations WHERE session_id > 0
                    UNION
                    SELECT session_id AS s_id FROM matrix_snapshots WHERE session_id > 0
                ) combined
                WHERE s_id NOT IN (SELECT id FROM annotation_sessions)
                ORDER BY s_id;
            """)
            if missing_sessions:
                print(f"Found {len(missing_sessions)} orphaned session IDs to recover: {[r['s_id'] for r in missing_sessions]}")
                for r in missing_sessions:
                    sid = r["s_id"]
                    stem_desc = f"Recovered annotation session {sid}"
                    await conn.execute("""
                        INSERT INTO annotation_sessions (id, username, stem_text, status, created_at)
                        VALUES ($1, 'legacy_recovered', $2, 'done', now())
                        ON CONFLICT (id) DO NOTHING;
                    """, sid, stem_desc)

                # Reset sequence for annotation_sessions
                await conn.execute("""
                    SELECT setval(
                        pg_get_serial_sequence('annotation_sessions', 'id'),
                        COALESCE((SELECT MAX(id) FROM annotation_sessions), 1)
                    );
                """)
                print("Recovered orphan sessions and updated ID sequence.")

            # 2. Add batch_stem_id column to matrix_snapshots if not exists
            await conn.execute("""
                ALTER TABLE matrix_snapshots ADD COLUMN IF NOT EXISTS batch_stem_id INT;
            """)
            print("Ensured batch_stem_id column exists on matrix_snapshots.")

            # 3. Make session_id nullable on spans, relations, matrix_snapshots first
            await conn.execute("ALTER TABLE spans ALTER COLUMN session_id DROP NOT NULL;")
            await conn.execute("ALTER TABLE relations ALTER COLUMN session_id DROP NOT NULL;")
            await conn.execute("ALTER TABLE matrix_snapshots ALTER COLUMN session_id DROP NOT NULL;")
            print("Made session_id nullable on spans, relations, matrix_snapshots.")

            # 4. Migrate negative session_id rows to batch_stem_id
            updated_snaps = await conn.execute("""
                UPDATE matrix_snapshots
                SET batch_stem_id = ABS(session_id),
                    session_id = NULL
                WHERE session_id < 0;
            """)
            print(f"Migrated matrix_snapshots negative IDs: {updated_snaps}")

            updated_spans = await conn.execute("""
                UPDATE spans
                SET batch_stem_id = COALESCE(batch_stem_id, ABS(session_id)),
                    session_id = NULL
                WHERE session_id < 0;
            """)
            print(f"Migrated spans negative IDs: {updated_spans}")

            updated_relations = await conn.execute("""
                UPDATE relations
                SET batch_stem_id = COALESCE(batch_stem_id, ABS(session_id)),
                    session_id = NULL
                WHERE session_id < 0;
            """)
            print(f"Migrated relations negative IDs: {updated_relations}")

            # 5. Drop old unique constraint on relations and recreate partial unique indexes
            await conn.execute("ALTER TABLE relations DROP CONSTRAINT IF EXISTS relations_session_id_span_i_id_span_j_id_key;")
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_relations_session
                ON relations(session_id, span_i_id, span_j_id)
                WHERE session_id IS NOT NULL;
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_relations_batch_stem
                ON relations(batch_stem_id, span_i_id, span_j_id)
                WHERE batch_stem_id IS NOT NULL;
            """)
            print("Created partial unique indexes on relations.")

            # 6. Recreate partial unique indexes on matrix_snapshots
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_matrix_snapshots_session
                ON matrix_snapshots(session_id)
                WHERE session_id IS NOT NULL;
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_matrix_snapshots_batch_stem
                ON matrix_snapshots(batch_stem_id)
                WHERE batch_stem_id IS NOT NULL;
            """)
            print("Created partial unique indexes on matrix_snapshots.")

            # 7. Add foreign key constraints with ON DELETE CASCADE
            # Spans FKs
            await conn.execute("ALTER TABLE spans DROP CONSTRAINT IF EXISTS spans_session_id_fkey;")
            await conn.execute("""
                ALTER TABLE spans
                ADD CONSTRAINT spans_session_id_fkey
                FOREIGN KEY (session_id) REFERENCES annotation_sessions(id) ON DELETE CASCADE;
            """)
            await conn.execute("ALTER TABLE spans DROP CONSTRAINT IF EXISTS spans_batch_stem_id_fkey;")
            await conn.execute("""
                ALTER TABLE spans
                ADD CONSTRAINT spans_batch_stem_id_fkey
                FOREIGN KEY (batch_stem_id) REFERENCES batch_stems(id) ON DELETE CASCADE;
            """)

            # Relations FKs
            await conn.execute("ALTER TABLE relations DROP CONSTRAINT IF EXISTS relations_session_id_fkey;")
            await conn.execute("""
                ALTER TABLE relations
                ADD CONSTRAINT relations_session_id_fkey
                FOREIGN KEY (session_id) REFERENCES annotation_sessions(id) ON DELETE CASCADE;
            """)
            await conn.execute("ALTER TABLE relations DROP CONSTRAINT IF EXISTS relations_batch_stem_id_fkey;")
            await conn.execute("""
                ALTER TABLE relations
                ADD CONSTRAINT relations_batch_stem_id_fkey
                FOREIGN KEY (batch_stem_id) REFERENCES batch_stems(id) ON DELETE CASCADE;
            """)

            # Matrix snapshots FKs
            await conn.execute("ALTER TABLE matrix_snapshots DROP CONSTRAINT IF EXISTS matrix_snapshots_session_id_fkey;")
            await conn.execute("""
                ALTER TABLE matrix_snapshots
                ADD CONSTRAINT matrix_snapshots_session_id_fkey
                FOREIGN KEY (session_id) REFERENCES annotation_sessions(id) ON DELETE CASCADE;
            """)
            await conn.execute("ALTER TABLE matrix_snapshots DROP CONSTRAINT IF EXISTS matrix_snapshots_batch_stem_id_fkey;")
            await conn.execute("""
                ALTER TABLE matrix_snapshots
                ADD CONSTRAINT matrix_snapshots_batch_stem_id_fkey
                FOREIGN KEY (batch_stem_id) REFERENCES batch_stems(id) ON DELETE CASCADE;
            """)
            print("Reinstated all foreign key constraints with ON DELETE CASCADE.")

            # 8. Add mutual exclusivity check constraints
            await conn.execute("ALTER TABLE spans DROP CONSTRAINT IF EXISTS chk_spans_owner;")
            await conn.execute("""
                ALTER TABLE spans
                ADD CONSTRAINT chk_spans_owner
                CHECK ((session_id IS NOT NULL AND batch_stem_id IS NULL) OR (session_id IS NULL AND batch_stem_id IS NOT NULL));
            """)

            await conn.execute("ALTER TABLE relations DROP CONSTRAINT IF EXISTS chk_relations_owner;")
            await conn.execute("""
                ALTER TABLE relations
                ADD CONSTRAINT chk_relations_owner
                CHECK ((session_id IS NOT NULL AND batch_stem_id IS NULL) OR (session_id IS NULL AND batch_stem_id IS NOT NULL));
            """)

            await conn.execute("ALTER TABLE matrix_snapshots DROP CONSTRAINT IF EXISTS chk_matrix_snapshots_owner;")
            await conn.execute("""
                ALTER TABLE matrix_snapshots
                ADD CONSTRAINT chk_matrix_snapshots_owner
                CHECK ((session_id IS NOT NULL AND batch_stem_id IS NULL) OR (session_id IS NULL AND batch_stem_id IS NOT NULL));
            """)
            print("Added mutual exclusivity CHECK constraints (session_id XOR batch_stem_id).")

        # Post-check row counts
        counts_after = {
            "annotation_sessions": await conn.fetchval("SELECT count(*) FROM annotation_sessions"),
            "matrix_snapshots": await conn.fetchval("SELECT count(*) FROM matrix_snapshots"),
            "relations": await conn.fetchval("SELECT count(*) FROM relations"),
            "spans": await conn.fetchval("SELECT count(*) FROM spans"),
            "batch_stems": await conn.fetchval("SELECT count(*) FROM batch_stems"),
            "batches": await conn.fetchval("SELECT count(*) FROM batches"),
            "stems": await conn.fetchval("SELECT count(*) FROM stems"),
            "users": await conn.fetchval("SELECT count(*) FROM users"),
            "auth_sessions": await conn.fetchval("SELECT count(*) FROM auth_sessions"),
        }
        print("Post-migration row counts:", counts_after)

        for table in ["matrix_snapshots", "relations", "spans", "batch_stems", "batches", "stems", "users"]:
            assert counts_after[table] == counts_before[table], f"Data loss detected in {table}! Expected {counts_before[table]}, got {counts_after[table]}"

        print("Migration SUCCESS: Zero data loss verified!")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration())
