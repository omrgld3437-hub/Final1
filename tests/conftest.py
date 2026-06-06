import asyncio
import inspect
import os
import tempfile
from pathlib import Path


TEST_DB = Path(
    os.environ.get(
        "TRADERTRAILING_TEST_DB",
        str(Path(tempfile.gettempdir()) / "tradertrailing_pytest.db"),
    )
)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("BREACH_SHUTDOWN", "0")


def pytest_configure(config):
    asyncio.set_event_loop(asyncio.new_event_loop())
    TEST_DB.parent.mkdir(parents=True, exist_ok=True)
    from app.db.base import Base, engine
    from app.db.schema_guard import run_schema_guard

    Base.metadata.create_all(bind=engine)
    run_schema_guard(engine)


def pytest_pyfunc_call(pyfuncitem):
    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None
    fixture_names = pyfuncitem._fixtureinfo.argnames
    kwargs = {name: pyfuncitem.funcargs[name] for name in fixture_names}
    try:
        asyncio.run(test_func(**kwargs))
    finally:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return True
