from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas import ChatMessageData
from app.services import MistralService


@pytest.mark.asyncio
@patch("app.services.Mistral")
async def test_ask_mistral(mock_mistral_class: MagicMock):
    # Setup mock
    mock_client = MagicMock()
    mock_mistral_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Mocked response!"))]
    mock_client.chat.complete_async = AsyncMock(return_value=mock_response)

    service = MistralService(api_key="fake")
    history = [ChatMessageData(role="user", content="Hello")]
    response = await service.ask_mistral(history)

    assert response == "Mocked response!"
    mock_client.chat.complete_async.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.Mistral")
async def test_generate_profile_from_docs(mock_mistral_class: MagicMock):
    # Setup mock
    mock_client = MagicMock()
    mock_mistral_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="Mocked profile response!"))
    ]
    mock_client.chat.complete_async = AsyncMock(return_value=mock_response)

    service = MistralService(api_key="fake")

    # Mock uploaded document
    from app.schemas import UploadedDocument

    doc = UploadedDocument(
        filename="test.md", content=b"# Title\nThis is a test document."
    )

    existing_profile = "Existing profile text"
    response = await service.generate_profile_from_docs(
        [doc], "Test Owner", existing_profile
    )

    assert response == "Mocked profile response!"
    mock_client.chat.complete_async.assert_called_once()

    # Verify existing profile was passed in prompt
    call_kwargs = mock_client.chat.complete_async.call_args.kwargs
    messages = call_kwargs.get("messages", [])
    user_message = next((m for m in messages if m["role"] == "user"), None)
    assert user_message is not None
    assert "Existing profile text" in user_message["content"]
    assert "test.md" in user_message["content"]


def test_message_text_drops_thinking_chunks():
    from mistralai.client.models import TextChunk, ThinkChunk

    from app.services import message_text

    content = [
        ThinkChunk(thinking=[TextChunk(text="secret reasoning")]),
        TextChunk(text="Hello "),
        TextChunk(text="there!"),
    ]
    assert message_text(content) == "Hello there!"
    assert message_text("plain") == "plain"
    assert message_text(None) == ""
    assert (
        message_text(
            [{"type": "thinking", "thinking": []}, {"type": "text", "text": "ok"}]
        )
        == "ok"
    )


@pytest.mark.asyncio
async def test_ask_mistral_uses_large_4_and_hides_thinking():
    from mistralai.client.models import TextChunk, ThinkChunk

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                tool_calls=None,
                content=[
                    ThinkChunk(thinking=[TextChunk(text="internal")]),
                    TextChunk(text="Visible answer"),
                ],
            )
        )
    ]
    mock_client.chat.complete_async = AsyncMock(return_value=mock_response)
    service = MistralService(api_key="test")
    service.client = mock_client

    result = await service.ask_mistral([ChatMessageData(role="user", content="Hi")])

    assert result == "Visible answer"
    kwargs = mock_client.chat.complete_async.call_args.kwargs
    assert kwargs["model"] == "mistral-large-4"
    assert kwargs["reasoning_effort"] == "low"
