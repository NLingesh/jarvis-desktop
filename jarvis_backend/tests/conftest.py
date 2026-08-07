"""Shared pytest configuration.

- Disables the background Vosk model preload (which loads a ~68 MB model) so
  the test suite exits quickly and does not hang on interpreter shutdown.
- Closes the shared aiosqlite connections (memory manager / vault) after the
  last test. They are normally closed by the app lifespan shutdown, which never
  runs for plain ``TestClient`` instances; leaving them open keeps their
  non-daemon worker threads alive and hangs pytest at interpreter exit.
"""

import asyncio
import os

os.environ.setdefault("JARVIS_SKIP_STT_PRELOAD", "1")
os.environ.setdefault("JARVIS_SKIP_PROACTIVE", "1")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _close_backend_connections():
    yield
    try:
        import routes.state as state_mod

        asyncio.run(state_mod.memory_manager.close())
        asyncio.run(state_mod.vault.close())
    except Exception:
        pass
