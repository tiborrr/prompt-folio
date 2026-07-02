

# Mistral API Models
MODEL_CHAT = "mistral-large-latest"
MODEL_OCR = "mistral-ocr-latest"

# Chat Roles
ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"

# Application Defaults
# Removed hardcoded defaults; these are now handled via Settings (.env)

# UI / Magic Numbers
MAX_CHAT_DEPTH = 3
ADMIN_NOTIFICATION_TRUNCATE_LEN = 50
NEW_SESSION_NOTIFICATION_MSG_COUNT = 4

# Cookies & Sessions
ADMIN_SESSION_COOKIE_NAME = "admin_session"
COOKIE_MAX_AGE_SECONDS = 86400

# Rate Limits
RATE_LIMIT_GLOBAL = "50/minute"
RATE_LIMIT_CHAT = "10/minute"

# Security Headers
SECURITY_HEADERS = {
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Content-Security-Policy-Report-Only": "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; object-src 'none'; base-uri 'none';",
}

# Tools (JSON Schema for Mistral)
UPDATE_USER_PROFILE_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "update_user_profile",
        "description": "Updates the database with the user's name and their core intent for visiting the portfolio.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The user's name, if they have provided it.",
                },
                "intent": {
                    "type": "string",
                    "description": "The user's intent or reason for visiting (e.g. 'hiring for frontend', 'just browsing', 'looking for AI engineer').",
                },
            },
            "required": [],
        },
    },
}
