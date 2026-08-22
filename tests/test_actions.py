from danmakufuzz.headless.actions import parse_actions_text


def test_parse_actions_supports_repeat_counts() -> None:
    stream = parse_actions_text(
        """
        # comment
        2 stay
        left_fast
        """
    )
    assert stream.actions == ("stay", "stay", "left_fast")
