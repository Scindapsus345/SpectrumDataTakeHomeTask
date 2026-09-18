import shutil
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
import pytest_asyncio
from testcontainers.community.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for PostgreSQL integration tests")
    with PostgresContainer("postgres:17.11-bookworm", driver=None) as postgres:
        yield postgres.get_connection_url()


@pytest_asyncio.fixture
async def pg_pool(postgres_dsn: str) -> AsyncIterator[asyncpg.Pool]:
    pool = await asyncpg.create_pool(postgres_dsn, min_size=1, max_size=4)
    if pool is None:
        raise RuntimeError("asyncpg did not create a pool")
    yield pool
    await pool.execute("TRUNCATE pages")
    await pool.close()
