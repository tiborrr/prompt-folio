import pytest
import asyncio
import httpx

import os

os.environ["ENVIRONMENT"] = "TEST"
os.environ["DB_PATH"] = "sqlite+aiosqlite:///:memory:"

from app.main import app


@pytest.mark.asyncio
async def test_chat_sse_flow():
    from httpx import ASGITransport

    transport = ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Connect to / to get a session
        response = await client.get("/")
        assert response.status_code == 200
        session_id = response.cookies.get("session_id")
        assert session_id is not None

        events_received = []

        async def consume_sse():
            async with client.stream("GET", f"/stream/{session_id}") as stream_response:
                assert stream_response.status_code == 200
                async for line in stream_response.aiter_lines():
                    if line.strip():
                        events_received.append(line)

        # Start consuming in background
        consumer_task = asyncio.create_task(consume_sse())

        # Wait a tiny bit for the connection to be established
        await asyncio.sleep(0.2)

        # 3. Post a message to /chat
        chat_response = await client.post(
            "/chat",
            data={"message": "Hello world!"},
            cookies={"session_id": session_id},
        )

        assert chat_response.status_code == 204  # Returns 204 No Content for HTMX

        # Wait for the broadcast to propagate through the queue
        await asyncio.sleep(0.5)

        # Cancel the consumer
        consumer_task.cancel()

        assert len(events_received) > 0, "No SSE events received!"

        # Print out to see exactly what we received to debug the formatting
        print("Events received:", events_received)

        event_found = False
        data_found = False

        for line in events_received:
            if line.startswith("event: chat_message"):
                event_found = True
            elif line.startswith("data: ") and "Hello world!" in line:
                data_found = True

        assert event_found, "The 'event: chat_message' was not properly formatted"
        assert data_found, (
            "The 'data: ' payload was not properly formatted or missing the message content"
        )
