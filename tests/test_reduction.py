from danmakufuzz.reduction import ddmin_sequence, first_prefix_divergence, first_true_index


def test_ddmin_sequence_reduces_to_required_element() -> None:
    result = ddmin_sequence(
        [1, 2, 99, 3, 4],
        lambda items: 99 in items,
        max_evaluations=32,
    )

    assert result.items == (99,)
    assert result.evaluations > 0
    assert result.exhausted_budget is False


def test_first_true_index_bisects_monotonic_predicate() -> None:
    result = first_true_index([1, 3, 5, 7, 9], lambda value: value >= 7)

    assert result.index == 3
    assert result.item == 7
    assert result.exhausted_budget is False


def test_first_prefix_divergence_reports_length_and_value_changes() -> None:
    assert first_prefix_divergence([1, 2, 3], [1, 2, 4]) == 2
    assert first_prefix_divergence([{"tick": 1}, {"tick": 2}], [{"tick": 1}], project=lambda item: item["tick"]) == 1
    assert first_prefix_divergence([1, 2], [1, 2]) is None
