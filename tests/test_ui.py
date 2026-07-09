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
    env["RECAPTCHA_CLIENT_SIDE_KEY"] = ""

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

@pytest.mark.asyncio
async def test_ui_editor_fallback():
    env = os.environ.copy()
    env["ENVIRONMENT"] = "TEST"
    env["DB_PATH"] = "sqlite+aiosqlite:///:memory:"
    env["ADMIN_PASSWORD"] = "test_secure_password"
    env["RECAPTCHA_CLIENT_SIDE_KEY"] = ""

    process = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--port", "3007"], env=env
    )

    try:
        await asyncio.sleep(2)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # 1. Log in
            await page.goto("http://127.0.0.1:3007/manage")
            await page.fill('input[name="password"]', "test_secure_password")
            await page.click('button[type="submit"]')
            
            # Wait for dashboard to load
            await page.wait_for_selector('h2:has-text("Settings")', timeout=5000)

            # 2. Inject raw markdown/text into the context via API to simulate Mistral output
            # We use the page.request context which shares cookies
            response = await page.request.post(
                "http://127.0.0.1:3007/manage/update_raw",
                form={"raw_context": "Hello Markdown fallback test!\n\nThis is a new paragraph."}
            )
            assert response.ok

            # 3. Reload the page to the context tab and wait for Alpine/EditorJS to initialize
            await page.goto("http://127.0.0.1:3007/manage/context")
            await asyncio.sleep(1) # Give EditorJS a moment to mount

            # 4. Verify EditorJS rendered the fallback text
            editor_content = page.locator('.ce-paragraph')
            await editor_content.first.wait_for(state="visible", timeout=5000)
            
            text_content = await page.locator('.ce-block__content').all_inner_texts()
            full_text = " ".join(text_content)
            
            assert "Hello Markdown fallback test!" in full_text
            assert "This is a new paragraph." in full_text

            await browser.close()
    finally:
        process.terminate()
        process.wait()
