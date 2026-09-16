from app.services.inline_tools import InlineToolParser


def test_parser_handles_fragmented_markers_and_multiple_actions() -> None:
    parser = InlineToolParser()
    visible, calls, errors = [], [], []
    for chunk in ["Before <ss-", 'tool>{"name":"advanceTime","arguments":{"minutes":5}}</ss-', "tool> after"]:
        text, found, failed = parser.feed(chunk)
        visible.append(text); calls.extend(found); errors.extend(failed)
    tail, failed = parser.finish(); visible.append(tail); errors.extend(failed)
    assert "".join(visible) == "Before  after"
    assert calls == [{"name": "advanceTime", "arguments": {"minutes": 5}}]
    assert errors == []


def test_parser_suppresses_malformed_and_unterminated_envelopes() -> None:
    parser = InlineToolParser()
    text, calls, errors = parser.feed("safe<ss-tool>{bad}</ss-tool>still safe")
    assert text == "safestill safe" and not calls and errors[0].code == "malformed_envelope"
    parser.feed("<ss-tool>{")
    tail, errors = parser.finish()
    assert tail == "" and errors[0].code == "unterminated_envelope"


def test_parser_recovers_adjacent_actions_and_hidden_trailing_commentary() -> None:
    parser = InlineToolParser()
    text, calls, errors = parser.feed(
        'before<ss-tool>{"name":"startMinigame","arguments":{"game_key":"circled_teeth"}}'
        '{"name":"advanceTime","arguments":{"minutes":1}} trailing explanation</ss-tool>after'
    )
    assert text == "beforeafter"
    assert [call["name"] for call in calls] == ["startMinigame", "advanceTime"]
    assert errors == []
