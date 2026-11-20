import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.rate_limit import Limiter, RateLimitExceeded


def _app(limiter: Limiter) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(RateLimitExceeded)
    async def _(request: Request, exc: RateLimitExceeded):
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(str(exc), status_code=429)

    @app.get("/a")
    @limiter.limit("2/minute")
    async def a(request: Request, q: int = 0):
        return {"q": q}

    @app.get("/b")
    @limiter.limit("2/minute")
    async def b(request: Request):
        return {}

    return app


@pytest.mark.asyncio
async def test_limit_blocks_after_n_hits_per_route():
    limiter = Limiter()
    async with AsyncClient(
        transport=ASGITransport(app=_app(limiter)), base_url="http://test"
    ) as client:
        # Query parameters still reach the endpoint through the wrapper
        assert (await client.get("/a?q=7")).json() == {"q": 7}
        assert (await client.get("/a")).status_code == 200
        assert (await client.get("/a")).status_code == 429
        # Another route has its own bucket
        assert (await client.get("/b")).status_code == 200

        limiter.reset()
        assert (await client.get("/a")).status_code == 200


@pytest.mark.asyncio
async def test_limit_is_per_client():
    limiter = Limiter(key_func=lambda request: request.headers["x-client"])
    async with AsyncClient(
        transport=ASGITransport(app=_app(limiter)), base_url="http://test"
    ) as client:
        for _ in range(2):
            assert (
                await client.get("/b", headers={"x-client": "1"})
            ).status_code == 200
        assert (await client.get("/b", headers={"x-client": "1"})).status_code == 429
        assert (await client.get("/b", headers={"x-client": "2"})).status_code == 200


def test_endpoint_without_request_parameter_is_rejected():
    limiter = Limiter()

    @limiter.limit("1/minute")
    async def no_request() -> None: ...

    with pytest.raises(TypeError):
        import asyncio

        asyncio.run(no_request())


@pytest.mark.asyncio
async def test_login_is_limited_to_five_attempts():
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for _ in range(5):
            response = await client.post("/manage/login", data={"password": "wrong"})
            assert response.status_code != 429
        response = await client.post("/manage/login", data={"password": "wrong"})
        assert response.status_code == 429
        assert "too fast" in response.text
