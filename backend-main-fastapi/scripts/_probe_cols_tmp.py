import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402
from pipeline.config import pg_database_url  # noqa: E402

with psycopg.connect(pg_database_url()) as pg, pg.cursor() as cur:
    for t in ("knowledge_chunks", "chunk_vectors", "knowledge_points", "subject_chapters"):
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name=%s ORDER BY ordinal_position", (t,))
        print(f"--- {t} ---")
        print(" | ".join(f"{c}:{d}" for c, d in cur.fetchall()))
