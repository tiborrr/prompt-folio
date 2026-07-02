import pytest
from unittest.mock import patch, AsyncMock, MagicMock
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
    history = [{"role": "user", "content": "Hello"}]
    response = await service.ask_mistral(history)

    assert response == "Mocked response!"
    mock_client.chat.complete_async.assert_called_once()
