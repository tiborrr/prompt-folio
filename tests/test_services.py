import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.services import MistralService
from app.schemas import ChatMessageData


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
    mock_response.choices = [MagicMock(message=MagicMock(content="Mocked profile response!"))]
    mock_client.chat.complete_async = AsyncMock(return_value=mock_response)

    service = MistralService(api_key="fake")
    
    # Mock uploaded document
    from app.schemas import UploadedDocument
    doc = UploadedDocument(filename="test.md", content=b"# Title\nThis is a test document.")
    
    existing_profile = "Existing profile text"
    response = await service.generate_profile_from_docs([doc], "Test Owner", existing_profile)

    assert response == "Mocked profile response!"
    mock_client.chat.complete_async.assert_called_once()
    
    # Verify existing profile was passed in prompt
    call_kwargs = mock_client.chat.complete_async.call_args.kwargs
    messages = call_kwargs.get("messages", [])
    user_message = next((m for m in messages if m["role"] == "user"), None)
    assert user_message is not None
    assert "Existing profile text" in user_message["content"]
    assert "test.md" in user_message["content"]
