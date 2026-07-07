import asyncio
import os
from playwright.async_api import async_playwright

async def main():
    artifacts_dir = "/Users/tiborcasteleijn/.gemini/antigravity/brain/2827c9ad-49c5-42de-ac3b-5baf63fda273"
    
    async with async_playwright() as p:
        # Connect to existing dev server on port 3005
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        print("Navigating to public chat...")
        await page.goto("http://127.0.0.1:3005")
        await asyncio.sleep(2)
        await page.screenshot(path=os.path.join(artifacts_dir, "screenshot_public_chat.png"), full_page=True)

        print("Typing a message in public chat...")
        await page.fill('input[name="message"]', "Hello, this is a test message to see how it looks.")
        await page.click(".send-btn")
        await asyncio.sleep(3)
        await page.screenshot(path=os.path.join(artifacts_dir, "screenshot_public_chat_active.png"), full_page=True)

        print("Navigating to manage area...")
        await page.goto("http://127.0.0.1:3005/manage")
        await asyncio.sleep(1)

        print("Logging in...")
        await page.fill('input[name="password"]', "change_this_to_a_secure_password_its_now_changed")
        await page.click('button[type="submit"]')
        await asyncio.sleep(2)
        
        # We should be on dashboard now
        await page.screenshot(path=os.path.join(artifacts_dir, "screenshot_manage_dashboard.png"), full_page=True)

        print("Navigating to context...")
        await page.click("text=Context")
        await asyncio.sleep(2)
        await page.screenshot(path=os.path.join(artifacts_dir, "screenshot_manage_context.png"), full_page=True)

        print("Navigating to appearance...")
        await page.click("text=Appearance")
        await asyncio.sleep(2)
        await page.screenshot(path=os.path.join(artifacts_dir, "screenshot_manage_appearance.png"), full_page=True)

        await browser.close()
        print("Screenshots taken successfully.")

if __name__ == "__main__":
    asyncio.run(main())
