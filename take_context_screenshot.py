import asyncio
import os
from playwright.async_api import async_playwright

async def main():
    artifacts_dir = "/Users/tiborcasteleijn/.gemini/antigravity/brain/2827c9ad-49c5-42de-ac3b-5baf63fda273"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        print("Navigating to login...")
        await page.goto("http://127.0.0.1:3005/manage")
        await asyncio.sleep(1)
        await page.fill('input[name="password"]', "secret")
        await page.click('button[type="submit"]')
        await asyncio.sleep(2)

        print("Navigating to integrations...")
        await page.goto("http://127.0.0.1:3005/manage/context")
        await asyncio.sleep(2)
        await page.screenshot(path=os.path.join(artifacts_dir, "screenshot_manage_integrations.png"), full_page=True)
        
        await browser.close()

asyncio.run(main())
