import pytest

from mean import mean
from normalize import normalize_scores
from report import build_report


def test_mean_basic() -> None:
    assert mean([1, 2, 3]) == 2


def test_mean_empty() -> None:
    with pytest.raises(ValueError):
        mean([])


def test_normalize_range() -> None:
    assert normalize_scores([0, 5, 10]) == [0.0, 0.5, 1.0]


def test_normalize_empty() -> None:
    assert normalize_scores([]) == []


def test_normalize_constant() -> None:
    assert normalize_scores([3, 3, 3]) == [0.0, 0.0, 0.0]


def test_report_shape() -> None:
    report = build_report([0, 5, 10])
    assert report["mean"] == 5
    assert report["normalized"] == [0.0, 0.5, 1.0]
