# Ionity NoteCad - Brain | Policy 986 AED | License AED 900
"""Every test that takes the `farm` fixture runs on SQLite, and also on Postgres when NC_BRAIN_TEST_PG_URL is set
(e.g. postgresql://postgres@/notecad_test?host=/var/tmp&port=5433). Each Postgres run gets its own schema."""
import os
import sys
import uuid
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))                       # notecad_brain
sys.path.insert(0, str(HERE.parents[2] / "companion"))         # notecad_companion (LLM + embedding clients)
sys.path.insert(0, str(HERE.parent))                           # farm.py

PG = os.environ.get("NC_BRAIN_TEST_PG_URL")


def _pg_url_with_schema() -> tuple[str, str]:
    import psycopg
    schema = "t_" + uuid.uuid4().hex[:10]
    with psycopg.connect(PG, autocommit=True) as c:
        c.execute(f"create schema {schema}")
    sep = "&" if "?" in PG else "?"
    return f"{PG}{sep}options=-csearch_path%3D{schema}", schema


@pytest.fixture(params=["sqlite"] + (["postgres"] if PG else []))
def farm(request):
    from farm import make_brain, seed_farm
    if request.param == "postgres":
        url, schema = _pg_url_with_schema()
        b = make_brain(url)
        yield b, seed_farm(b)
        b.db.close()
        import psycopg
        with psycopg.connect(PG, autocommit=True) as c:
            c.execute(f"drop schema {schema} cascade")
    else:
        b = make_brain()
        yield b, seed_farm(b)
