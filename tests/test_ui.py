import pytest
import asyncio
from playwright.async_api import async_playwright
import subprocess
import os


@pytest.mark.asyncio
async def test_ui_chat_message():
    env = os.environ.copy()
    env["ENVIRONMENT"] = "TEST"
    env["DB_PATH"] = "sqlite+aiosqlite:///:memory:"

    process = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--port", "3006"], env=env
    )

    try:
        await asyncio.sleep(2)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # Capture console
            page.on("console", lambda msg: print(f"Browser console: {msg.text}"))

            # Go to the chat page
            await page.goto("http://127.0.0.1:3006/")

            # Wait for SSE to connect
            await asyncio.sleep(1)

            # Type a message
            await page.fill('input[name="message"]', "Hello world!")

            # Click send
            await page.click(".send-btn")

            # Wait for message to appear via SSE
            # The message should have the text "Hello world!" inside a user bubble
            message_locator = page.locator('.message.user:has-text("Hello world!")')
            await message_locator.wait_for(state="visible", timeout=5000)

            assert await message_locator.is_visible()

            await browser.close()
    finally:
        process.terminate()
        process.wait()
