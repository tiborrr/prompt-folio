import pytest
import asyncio
import httpx
import subprocess
import os


@pytest.mark.asyncio
async def test_chat_sse_flow_real():
    # Start the real uvicorn server in the background
    env = os.environ.copy()
    env["ENVIRONMENT"] = "TEST"
    env["DB_PATH"] = "sqlite+aiosqlite:///:memory:"

    # We use port 31234 for testing
    process = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--port", "31234"], env=env
    )

    try:
        # Wait for the server to start
        await asyncio.sleep(2)

        async with httpx.AsyncClient(base_url="http://127.0.0.1:31234") as client:
            # 1. Connect to / to get a session
            response = await client.get("/")
            assert response.status_code == 200
            session_id = response.cookies.get("session_id")
            assert session_id is not None

            events_received = []

            async def consume_sse():
                async with client.stream(
                    "GET", f"/stream/{session_id}"
                ) as stream_response:
                    assert stream_response.status_code == 200
                    async for line in stream_response.aiter_lines():
                        if line.strip():
                            events_received.append(line)

            # Start consuming in background
            consumer_task = asyncio.create_task(consume_sse())

            # Wait a tiny bit for the connection to be established
            await asyncio.sleep(0.5)

            # 3. Post a message to /chat
            chat_response = await client.post(
                "/chat",
                data={"message": "Hello world!"},
            )

            # 500 error expected because Mistral key is missing,
            # BUT the user message should still be broadcast via SSE before the error.
            print("Chat status code:", chat_response.status_code)

            # Wait for the broadcast to propagate through the queue
            await asyncio.sleep(1.0)

            # Cancel the consumer
            consumer_task.cancel()

            print("Events received:", events_received)
            assert len(events_received) > 0, "No SSE events received!"

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
    finally:
        process.terminate()
        process.wait()
