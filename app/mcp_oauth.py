"""OAuth 2.1 authorization server for the MCP endpoint.

Implements the MCP SDK's ``OAuthAuthorizationServerProvider`` on top of the
app's SQLite database. The SDK serves the protocol endpoints (/authorize,
/token, /register, /revoke and the .well-known metadata); this module stores
clients and tokens, and sends the browser to /oauth/consent, where the admin
logs in with the normal /manage password and approves the client.
"""

import json
import secrets
import time
import uuid
from typing import override
from urllib.parse import urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthToken as OAuthTokenResponse
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col, delete, select

from app.config import Settings
from app.database import get_engine
from app.dependencies import hash_session_token
from app.models import OAuthClient, OAuthToken

MCP_SCOPE = "profile"
REQUEST_TTL_SECONDS = 10 * 60
CODE_TTL_SECONDS = 5 * 60
ACCESS_TOKEN_TTL_SECONDS = 60 * 60
REFRESH_TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
# Stored token data: a JSON object
_JSON_OBJECT: TypeAdapter[dict[str, object]] = TypeAdapter(dict[str, object])


def host_matches(host: str, pattern: str) -> bool:
    """``example.com`` matches only that host; ``*.example.com`` matches the
    domain and all its subdomains; ``*`` matches any host."""
    if pattern == "*":
        return True
    if pattern.startswith("*."):
        domain = pattern[2:]
        return host == domain or host.endswith(f".{domain}")
    return host == pattern


def redirect_uri_allowed(uri: str, allowed_hosts: set[str]) -> bool:
    """https on an allowed host, or http(s) on loopback (Claude Code, MCP Inspector)."""
    parsed = urlparse(uri)
    host = (parsed.hostname or "").lower()
    if host in LOOPBACK_HOSTS:
        return parsed.scheme in {"http", "https"}
    return parsed.scheme == "https" and any(
        host_matches(host, pattern) for pattern in allowed_hosts
    )


class PendingAuthorization:
    """An /authorize request waiting for the admin's approval on /oauth/consent."""

    def __init__(
        self,
        request_id: str,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ):
        self.request_id: str = request_id
        self.client: OAuthClientInformationFull = client
        self.params: AuthorizationParams = params

    @property
    def client_name(self) -> str:
        return self.client.client_name or self.client.client_id or "Unknown client"

    @property
    def redirect_host(self) -> str:
        return urlparse(str(self.params.redirect_uri)).netloc


class DatabaseOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self, config: Settings):
        self.config: Settings = config
        self.resource_url: str = f"{config.base_url}/mcp"
        self.allowed_hosts: set[str] = {
            h.strip().lower()
            for h in config.mcp_allowed_redirect_hosts.split(",")
            if h.strip()
        }

    def _session(self) -> AsyncSession:
        engine = get_engine(self.config.sqlite_url)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()

    # ------------------------------------------------------------------ clients

    @override
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with self._session() as db:
            row = await db.get(OAuthClient, client_id)
        if row is None:
            return None
        return OAuthClientInformationFull.model_validate_json(row.data)

    @override
    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        for uri in client_info.redirect_uris or []:
            if not redirect_uri_allowed(str(uri), self.allowed_hosts):
                raise RegistrationError(
                    error="invalid_redirect_uri",
                    error_description=(
                        f"Redirect URI not allowed: {uri}. Add its host to "
                        "MCP_ALLOWED_REDIRECT_HOSTS on the server to allow this client."
                    ),
                )
        assert client_info.client_id is not None
        async with self._session() as db:
            db.add(
                OAuthClient(
                    client_id=client_info.client_id,
                    data=client_info.model_dump_json(exclude_none=True),
                )
            )
            await db.commit()

    # ------------------------------------------------------------ authorization

    @override
    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if not redirect_uri_allowed(str(params.redirect_uri), self.allowed_hosts):
            raise AuthorizeError(
                error="invalid_request", error_description="Redirect URI not allowed."
            )
        assert client.client_id is not None
        request_id = secrets.token_urlsafe(32)
        async with self._session() as db:
            await self._store(
                db,
                token=request_id,
                kind="request",
                client_id=client.client_id,
                grant_id=str(uuid.uuid4()),
                ttl=REQUEST_TTL_SECONDS,
                data=params.model_dump(mode="json"),
            )
            await db.commit()
        return f"{self.config.base_url}/oauth/consent?request_id={request_id}"

    async def load_pending(self, request_id: str) -> PendingAuthorization | None:
        async with self._session() as db:
            row = await self._load(db, request_id, "request")
        if row is None:
            return None
        client = await self.get_client(row.client_id)
        if client is None:
            return None
        params = AuthorizationParams.model_validate_json(row.data)
        return PendingAuthorization(request_id, client, params)

    async def complete_pending(self, request_id: str, approved: bool) -> str | None:
        """Turn an approved request into an authorization code. Returns the URL to
        send the browser back to the client, or None for an unknown request."""
        async with self._session() as db:
            row = await self._load(db, request_id, "request")
            if row is None:
                return None
            await db.delete(row)
            params = AuthorizationParams.model_validate_json(row.data)
            redirect_uri = str(params.redirect_uri)
            if not approved:
                await db.commit()
                return construct_redirect_uri(
                    redirect_uri,
                    error="access_denied",
                    error_description="The owner denied access.",
                    state=params.state,
                )

            code = secrets.token_urlsafe(32)
            auth_code = AuthorizationCode(
                code=code,
                # Grant only the scope this server knows
                scopes=[MCP_SCOPE],
                expires_at=time.time() + CODE_TTL_SECONDS,
                client_id=row.client_id,
                code_challenge=params.code_challenge,
                redirect_uri=params.redirect_uri,
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                # This server is the only resource, so bind tokens to it
                resource=params.resource or self.resource_url,
                subject="owner",
            )
            await self._store(
                db,
                token=code,
                kind="code",
                client_id=row.client_id,
                grant_id=row.grant_id,
                ttl=CODE_TTL_SECONDS,
                data=auth_code.model_dump(mode="json", exclude={"code"}),
            )
            await db.commit()
        return construct_redirect_uri(redirect_uri, code=code, state=params.state)

    @override
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with self._session() as db:
            row = await self._load(db, authorization_code, "code")
        if row is None or row.client_id != client.client_id:
            return None
        return AuthorizationCode.model_validate(
            {**_JSON_OBJECT.validate_json(row.data), "code": authorization_code}
        )

    @override
    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthTokenResponse:
        async with self._session() as db:
            row = await self._load(db, authorization_code.code, "code")
            if row is None:
                raise TokenError(
                    error="invalid_grant",
                    error_description="Authorization code already used or expired.",
                )
            await db.delete(row)
            response = await self._issue_tokens(
                db,
                client_id=row.client_id,
                grant_id=row.grant_id,
                scopes=authorization_code.scopes,
                resource=authorization_code.resource,
                subject=authorization_code.subject,
            )
            await db.commit()
        return response

    # ---------------------------------------------------------- refresh tokens

    @override
    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        async with self._session() as db:
            row = await self._load(db, refresh_token, "refresh")
        if row is None or row.client_id != client.client_id:
            return None
        return RefreshToken.model_validate(
            {
                **_JSON_OBJECT.validate_json(row.data),
                "token": refresh_token,
                "client_id": row.client_id,
                "expires_at": row.expires_at,
            }
        )

    @override
    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthTokenResponse:
        async with self._session() as db:
            row = await self._load(db, refresh_token.token, "refresh")
            if row is None:
                raise TokenError(
                    error="invalid_grant", error_description="Refresh token expired."
                )
            # Rotate: the old refresh token and its access tokens stop working
            _ = await db.execute(
                delete(OAuthToken).where(col(OAuthToken.grant_id) == row.grant_id)
            )
            response = await self._issue_tokens(
                db,
                client_id=row.client_id,
                grant_id=row.grant_id,
                scopes=scopes or refresh_token.scopes,
                resource=refresh_token.resource,
                subject=refresh_token.subject,
            )
            await db.commit()
        return response

    # ----------------------------------------------------------- access tokens

    @override
    async def load_access_token(self, token: str) -> AccessToken | None:
        async with self._session() as db:
            row = await self._load(db, token, "access")
        if row is None:
            return None
        return AccessToken.model_validate(
            {
                **_JSON_OBJECT.validate_json(row.data),
                "token": token,
                "client_id": row.client_id,
                "expires_at": row.expires_at,
            }
        )

    @override
    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with self._session() as db:
            row = await db.get(OAuthToken, hash_session_token(token.token))
            if row is not None:
                _ = await db.execute(
                    delete(OAuthToken).where(col(OAuthToken.grant_id) == row.grant_id)
                )
                await db.commit()

    # ----------------------------------------------------------------- helpers

    async def _issue_tokens(
        self,
        db: AsyncSession,
        *,
        client_id: str,
        grant_id: str,
        scopes: list[str],
        resource: str | None,
        subject: str | None,
    ) -> OAuthTokenResponse:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        data: dict[str, object] = {
            "scopes": scopes,
            "resource": resource,
            "subject": subject,
        }
        await self._store(
            db,
            token=access,
            kind="access",
            client_id=client_id,
            grant_id=grant_id,
            ttl=ACCESS_TOKEN_TTL_SECONDS,
            data=data,
        )
        await self._store(
            db,
            token=refresh,
            kind="refresh",
            client_id=client_id,
            grant_id=grant_id,
            ttl=REFRESH_TOKEN_TTL_SECONDS,
            data=data,
        )
        return OAuthTokenResponse(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    @staticmethod
    async def _store(
        db: AsyncSession,
        *,
        token: str,
        kind: str,
        client_id: str,
        grant_id: str,
        ttl: int,
        data: dict[str, object],
    ) -> None:
        now = int(time.time())
        # Drop expired rows while we are here
        _ = await db.execute(delete(OAuthToken).where(col(OAuthToken.expires_at) < now))
        db.add(
            OAuthToken(
                token_hash=hash_session_token(token),
                kind=kind,
                client_id=client_id,
                grant_id=grant_id,
                expires_at=now + ttl,
                data=json.dumps(data),
            )
        )

    @staticmethod
    async def _load(db: AsyncSession, token: str, kind: str) -> OAuthToken | None:
        result = await db.execute(
            select(OAuthToken).where(
                OAuthToken.token_hash == hash_session_token(token),
                OAuthToken.kind == kind,
                col(OAuthToken.expires_at) >= int(time.time()),
            )
        )
        return result.scalar_one_or_none()
