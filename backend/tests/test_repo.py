import asyncio

from app.db.repo import Repo


class _Conn:
    def __init__(self, sink):
        self.sink = sink

    async def execute(self, stmt, params=None):
        self.sink.append((str(stmt), params))


class _Tx:
    def __init__(self, engine):
        self.engine = engine

    async def __aenter__(self):
        self.engine.transactions += 1
        return _Conn(self.engine.executed)

    async def __aexit__(self, *a):
        return False


class FakeEngine:
    def __init__(self):
        self.executed, self.transactions = [], 0

    def begin(self):
        return _Tx(self)


async def test_writes_are_batched_into_few_transactions_and_flush_waits():
    repo = Repo("postgresql://x")
    repo.engine = FakeEngine()
    for i in range(250):
        repo.enqueue("insert into t values (:i)", {"i": i})
    task = asyncio.create_task(repo._writer())
    assert await repo.flush(timeout=5)
    task.cancel()
    assert len(repo.engine.executed) == 250, "nothing may be lost"
    assert repo.engine.transactions <= 5, "250 rows must not cost 250 round trips"
    assert [p["i"] for _, p in repo.engine.executed] == list(range(250)), "order is preserved"


async def test_flush_returns_immediately_when_nothing_is_queued():
    repo = Repo(None)
    assert await repo.flush(timeout=1)
