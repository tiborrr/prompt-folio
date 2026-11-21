from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mistralai.client.models import (
    CompletionChunk,
    CompletionEvent,
    CompletionResponseStreamChoice,
    DeltaMessage,
    DeltaMessageContent,
    ToolCall,
)

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
    raw_chunks: list[dict[str, object]] = [
        {"type": "thinking", "thinking": []},
        {"type": "text", "text": "ok"},
    ]
    assert message_text(raw_chunks) == "ok"


@pytest.mark.asyncio
async def test_ask_mistral_uses_large_4_and_hides_thinking():
    from mistralai.client.models import TextChunk, ThinkChunk

    message = MagicMock(
        tool_calls=None,
        content=[
            ThinkChunk(thinking=[TextChunk(text="internal")]),
            TextChunk(text="Visible answer"),
        ],
    )
    complete_async = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=message)])
    )
    service = MistralService(api_key="test")
    service.client = MagicMock(**{"chat.complete_async": complete_async})

    result = await service.ask_mistral([ChatMessageData(role="user", content="Hi")])

    assert result == "Visible answer"
    kwargs = complete_async.call_args.kwargs
    assert kwargs["model"] == "mistral-large-4"
    assert kwargs["reasoning_effort"] == "low"


def _stream_event(
    content: DeltaMessageContent | None = None,
    tool_calls: list[ToolCall] | None = None,
) -> CompletionEvent:
    delta = DeltaMessage(content=content, tool_calls=tool_calls)
    return CompletionEvent(
        data=CompletionChunk(
            id="x",
            model="mistral-large-4",
            choices=[
                CompletionResponseStreamChoice(index=0, delta=delta, finish_reason=None)
            ],
        )
    )


class _FakeStream:
    def __init__(self, events: list[CompletionEvent]):
        self._events: list[CompletionEvent] = list(events)

    def __aiter__(self) -> _FakeStream:
        return self

    async def __anext__(self) -> CompletionEvent:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


@pytest.mark.asyncio
async def test_stream_mistral_yields_text_and_skips_thinking():
    from mistralai.client.models import TextChunk, ThinkChunk

    stream_async = AsyncMock(
        return_value=_FakeStream(
            [
                _stream_event([ThinkChunk(thinking=[TextChunk(text="secret")])]),
                _stream_event("Hello "),
                _stream_event([TextChunk(text="there!")]),
            ]
        )
    )
    service = MistralService(api_key="test")
    service.client = MagicMock(**{"chat.stream_async": stream_async})

    pieces = [
        p
        async for p in service.stream_mistral(
            [ChatMessageData(role="user", content="Hi")]
        )
    ]

    assert "".join(pieces) == "Hello there!"
    kwargs = stream_async.call_args.kwargs
    assert kwargs["model"] == "mistral-large-4"
    assert kwargs["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_stream_mistral_runs_tool_call_then_continues():
    from mistralai.client.models import FunctionCall

    tool_call = ToolCall(
        id="call1",
        index=0,
        function=FunctionCall(
            name="update_user_profile", arguments='{"name": "Sam", "intent": "hiring"}'
        ),
    )
    stream_async = AsyncMock(
        side_effect=[
            _FakeStream([_stream_event(tool_calls=[tool_call])]),
            _FakeStream([_stream_event("Nice to meet you, Sam.")]),
        ]
    )
    service = MistralService(api_key="test")
    service.client = MagicMock(**{"chat.stream_async": stream_async})
    callback = AsyncMock()

    history = [ChatMessageData(role="user", content="I'm Sam, hiring")]
    pieces = [
        p
        async for p in service.stream_mistral(
            history, tools=[{"type": "function"}], tool_callback=callback
        )
    ]

    assert "".join(pieces) == "Nice to meet you, Sam."
    callback.assert_awaited_once_with("Sam", None, "hiring")
    assert history[-1].role == "tool"
    assert history[-1].tool_call_id == "call1"
    assert history[-2].tool_calls is not None


@pytest.mark.asyncio
async def test_stream_mistral_apologises_when_the_api_fails():
    stream_async = AsyncMock(side_effect=RuntimeError("down"))
    service = MistralService(api_key="test")
    service.client = MagicMock(**{"chat.stream_async": stream_async})

    pieces = [
        p
        async for p in service.stream_mistral(
            [ChatMessageData(role="user", content="Hi")]
        )
    ]
    assert pieces == ["I'm sorry, I'm having trouble connecting to my brain right now."]


@pytest.mark.asyncio
async def test_finish_reply_hides_leaked_tool_text():
    from app.services import visible_reply_text

    callback = AsyncMock()
    text = 'Thanks! update_user_profile {"name": "Kim"} What do you need?'
    assert (
        await MistralService.finish_reply(text, callback)
        == "Thanks!  What do you need?"
    )
    callback.assert_awaited_once_with("Kim", None, None)
    assert visible_reply_text('Sure. update_user_profile {"na') == "Sure. "
    assert (
        await MistralService.finish_reply("   ")
        == "Got it! How else can I help you today?"
    )
