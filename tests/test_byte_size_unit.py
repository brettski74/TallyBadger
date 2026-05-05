import pytest

from tallybadger.core.byte_size import parse_byte_size


def test_parse_byte_size_plain_int() -> None:
    assert parse_byte_size(1024) == 1024
    assert parse_byte_size("1024") == 1024


def test_parse_byte_size_k_suffix() -> None:
    assert parse_byte_size("512k") == 512 * 1024
    assert parse_byte_size("1K") == 1024


def test_parse_byte_size_m_suffix() -> None:
    assert parse_byte_size("5M") == 5 * 1024 * 1024
    assert parse_byte_size("1m") == 1024 * 1024


def test_parse_byte_size_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        parse_byte_size(0)
    with pytest.raises(ValueError, match="positive"):
        parse_byte_size(-1)
    with pytest.raises(ValueError, match="positive"):
        parse_byte_size("0")


def test_parse_byte_size_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="invalid byte size"):
        parse_byte_size("5MB")
    with pytest.raises(ValueError, match="invalid byte size"):
        parse_byte_size("")
