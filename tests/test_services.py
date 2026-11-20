from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas import ChatMessageData
from app.services import MistralService


def _mock_completion(mock_mistral_class: MagicMock, content: str) -> AsyncMock:
    """Make the patched Mistral client answer every completion with ``content``."""
    response = MagicMock(choices=[MagicMock(message=MagicMock(content=content))])
    complete_async = AsyncMock(return_value=response)
    mock_mistral_class.return_value = MagicMock(
        **{"chat.complete_async": complete_async}
    )
    return complete_async


@pytest.mark.asyncio
@patch("app.services.Mistral")
async def test_ask_mistral(mock_mistral_class: MagicMock):
    complete_async = _mock_completion(mock_mistral_class, "Mocked response!")

    service = MistralService(api_key="fake")
    history = [ChatMessageData(role="user", content="Hello")]
    response = await service.ask_mistral(history)

    assert response == "Mocked response!"
    complete_async.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.Mistral")
async def test_generate_profile_from_docs(mock_mistral_class: MagicMock):
    complete_async = _mock_completion(mock_mistral_class, "Mocked profile response!")

    service = MistralService(api_key="fake")

    # Mock uploaded document
    from app.schemas import UploadedDocument

    doc = UploadedDocument(
        filename="test.md", content=b"# Title\nThis is a test document."
    )

    existing_profile = "Existing profile text"
    response = await service.generate_profile_from_docs([doc], existing_profile)

    assert response == "Mocked profile response!"
    complete_async.assert_called_once()

    # Verify existing profile was passed in prompt
    messages = cast(list[dict[str, str]], complete_async.call_args.kwargs["messages"])
    user_message = next((m for m in messages if m["role"] == "user"), None)
    assert user_message is not None
    assert "Existing profile text" in user_message["content"]
    assert "test.md" in user_message["content"]
