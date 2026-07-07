import pytest
import os
from httpx import ASGITransport, AsyncClient
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.main import app
from app.models import SiteSettings, AdminSession

os.environ["ENVIRONMENT"] = "TEST"
os.environ["DB_PATH"] = "sqlite+aiosqlite:///:memory:"

@pytest.mark.asyncio
async def test_manage_context_upload_and_rebuild():
    transport = ASGITransport(app=app)
    
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create admin session
        from app.database import get_engine
        from app.dependencies import get_db_session_factory
        from app.config import settings
        
        engine = get_engine(settings.sqlite_url)
        from sqlmodel import SQLModel
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        
        factory = get_db_session_factory(settings)
        async with factory() as db:
            admin_session = AdminSession(token="test_admin_token")
            db.add(admin_session)
            site_settings = SiteSettings(id=1, owner_name="Test Owner")
            db.add(site_settings)
            await db.commit()

        cookies = {"admin_session": "test_admin_token"}

        # 1. Test upload
        files = [('files', ('test.pdf', b'dummy pdf content', 'application/pdf'))]
        upload_response = await client.post(
            "/manage/upload", 
            files=files,
            cookies=cookies
        )
        assert upload_response.status_code == 200
        assert b"hx-swap-oob" in upload_response.content
        assert b"test.pdf" in upload_response.content

        # 2. Test rebuild
        rebuild_response = await client.post(
            "/manage/rebuild_context",
            cookies=cookies
        )
        assert rebuild_response.status_code == 200
        assert b"hx-swap-oob" in rebuild_response.content
