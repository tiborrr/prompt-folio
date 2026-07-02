import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models import ChatMessage
from sqlmodel import select, col


@pytest.mark.asyncio
async def test_chat_db_integration():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Start session by hitting index
        response = await client.get("/")
        assert response.status_code == 200

        session_id = response.cookies.get("session_id")
        assert session_id is not None

        # Send a chat message
        response = await client.post(
            "/chat",
            data={"message": "Hello Tibor!"},
            cookies={"session_id": session_id},
        )
        assert response.status_code == 204

        # Verify DB
        from sqlalchemy.ext.asyncio import create_async_engine

        test_db_engine = create_async_engine(
            "sqlite+aiosqlite:///file:testdb?mode=memory&cache=shared&uri=true"
        )
        async with test_db_engine.begin() as conn:
            result = await conn.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(col(ChatMessage.created_at))
            )
            messages = result.all()
            # 2 system msgs, 1 assistant greeting, 1 user msg, 1 assistant reply
            assert len(messages) == 5
            assert messages[3].role == "user"
            assert messages[3].content == "Hello Tibor!"
            assert messages[4].role == "assistant"
            assert messages[4].content == "Fake AI Response"
