import asyncio
import json
import os
import struct
import subprocess
import zlib

import pytest
from playwright.async_api import async_playwright


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
            _ = await page.goto("http://127.0.0.1:3006/")

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
        _ = process.wait()


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
            _ = await page.goto("http://127.0.0.1:3007/manage")
            await page.fill('input[name="password"]', "test_secure_password")
            await page.click('button[type="submit"]')

            # Wait for dashboard to load
            _ = await page.wait_for_selector('h2:has-text("Settings")', timeout=5000)

            # 2. Inject raw markdown/text into the context via API to simulate Mistral output
            # We use the page.request context which shares cookies
            response = await page.request.post(
                "http://127.0.0.1:3007/manage/update_raw",
                form={
                    "raw_context": "Hello Markdown fallback test!\n\nThis is a new paragraph."
                },
            )
            assert response.ok

            # 3. Reload the page to the context tab and wait for Alpine/EditorJS to initialize
            _ = await page.goto("http://127.0.0.1:3007/manage/context")
            await asyncio.sleep(1)  # Give EditorJS a moment to mount

            # 4. Verify EditorJS rendered the fallback text
            editor_content = page.locator(".ce-paragraph")
            await editor_content.first.wait_for(state="visible", timeout=5000)

            text_content = await page.locator(".ce-block__content").all_inner_texts()
            full_text = " ".join(text_content)

            assert "Hello Markdown fallback test!" in full_text
            assert "This is a new paragraph." in full_text

            await browser.close()
    finally:
        process.terminate()
        _ = process.wait()


@pytest.mark.asyncio
async def test_ui_editor_loads_all_block_tools():
    """Saved context with every block type (and a List 1.x list) renders in Editor.js."""
    env = os.environ.copy()
    env["ENVIRONMENT"] = "TEST"
    env["DB_PATH"] = "sqlite+aiosqlite:///:memory:"
    env["ADMIN_PASSWORD"] = "test_secure_password"
    env["RECAPTCHA_CLIENT_SIDE_KEY"] = ""

    process = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--port", "3008"], env=env
    )

    saved: dict[str, object] = {
        "time": 1,
        "version": "2.26.5",
        "blocks": [
            {"type": "header", "data": {"text": "About me", "level": 2}},
            {"type": "paragraph", "data": {"text": "Intro text"}},
            {
                "type": "list",
                "data": {"style": "unordered", "items": ["Legacy item one", "Two"]},
            },
            {"type": "delimiter", "data": {}},
            {"type": "code", "data": {"code": "print('hi')"}},
        ],
    }

    try:
        await asyncio.sleep(2)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))

            _ = await page.goto("http://127.0.0.1:3008/manage")
            await page.fill('input[name="password"]', "test_secure_password")
            await page.click('button[type="submit"]')
            _ = await page.wait_for_selector('h2:has-text("Settings")', timeout=5000)

            response = await page.request.post(
                "http://127.0.0.1:3008/manage/update_raw",
                form={"raw_context": json.dumps(saved)},
            )
            assert response.ok

            _ = await page.goto("http://127.0.0.1:3008/manage/context")
            await page.locator(".ce-header").first.wait_for(
                state="visible", timeout=5000
            )

            assert await page.locator(".ce-header").inner_text() == "About me"
            assert await page.locator(".cdx-list").count() == 1
            assert "Legacy item one" in await page.locator(".cdx-list").inner_text()
            assert await page.locator(".ce-delimiter").count() == 1
            assert (
                "print('hi')" in await page.locator(".ce-code__textarea").input_value()
            )
            assert errors == []

            await browser.close()
    finally:
        process.terminate()
        _ = process.wait()


def _solid_png(width: int, height: int) -> bytes:
    """A minimal RGB PNG, so the test needs no image library."""
    raw = b"".join(b"\x00" + b"\xd0\x60\x50" * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.mark.asyncio
async def test_ui_avatar_crop_and_upload():
    env = os.environ.copy()
    env["ENVIRONMENT"] = "TEST"
    env["DB_PATH"] = "sqlite+aiosqlite:///:memory:"
    env["ADMIN_PASSWORD"] = "test_secure_password"
    env["RECAPTCHA_CLIENT_SIDE_KEY"] = ""

    process = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--port", "3009"], env=env
    )

    try:
        await asyncio.sleep(2)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))

            _ = await page.goto("http://127.0.0.1:3009/manage")
            await page.fill('input[name="password"]', "test_secure_password")
            await page.click('button[type="submit"]')
            _ = await page.wait_for_selector('h2:has-text("Settings")', timeout=5000)

            _ = await page.goto("http://127.0.0.1:3009/manage/settings")
            await page.set_input_files(
                '#avatar-section input[type="file"]',
                files=[
                    {
                        "name": "photo.png",
                        "mimeType": "image/png",
                        "buffer": _solid_png(640, 480),
                    }
                ],
            )

            selection = page.locator("#avatar-section cropper-selection")
            await selection.wait_for(state="visible", timeout=5000)
            await selection.scroll_into_view_if_needed()
            box = await selection.bounding_box()
            assert box is not None
            assert abs(box["width"] - box["height"]) < 2  # square crop

            # Dragging the selection far past the image edge stops at the image
            image_box = await page.locator(
                "#avatar-section cropper-image"
            ).bounding_box()
            assert image_box is not None
            center_x = box["x"] + box["width"] / 2
            center_y = box["y"] + box["height"] / 2
            await page.mouse.move(center_x, center_y)
            await page.mouse.down()
            await page.mouse.move(center_x - 400, center_y - 400, steps=10)
            await page.mouse.up()
            moved = await selection.bounding_box()
            assert moved is not None
            assert moved["x"] < box["x"]  # it did move
            assert moved["x"] >= image_box["x"] - 1
            assert moved["y"] >= image_box["y"] - 1

            async with page.expect_response(
                lambda r: (
                    r.url.endswith("/manage/avatar") and r.request.method == "POST"
                )
            ) as upload:
                await page.click("#avatar-submit-btn")
            assert (await upload.value).ok

            await (
                page.locator("#avatar-save-status")
                .get_by_text("Avatar updated")
                .wait_for(timeout=5000)
            )
            assert await page.locator("#avatar-section cropper-canvas").count() == 0

            avatar = await page.request.get("http://127.0.0.1:3009/avatar")
            png = await avatar.body()
            assert png.startswith(b"\x89PNG")
            assert struct.unpack(">II", png[16:24]) == (400, 400)
            assert errors == []

            await browser.close()
    finally:
        process.terminate()
        _ = process.wait()
