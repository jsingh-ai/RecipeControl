import asyncio
import os
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest

TEST_DB = Path(f"/tmp/recipecontrol-tests-{os.getpid()}.db")
os.environ["APP_DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SOURCE_ADAPTER"] = "fixture"

from recipecontrol.api import app  # noqa: E402
from recipecontrol.database import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client() -> "APIClient":
    return APIClient()


class APIClient:
    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as current:
                return await current.request(method, url, **kwargs)

        return asyncio.run(send())

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)
