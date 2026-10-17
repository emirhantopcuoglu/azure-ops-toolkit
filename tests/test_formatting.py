import pytest

from opsctl.formatting import format_bytes


@pytest.mark.parametrize(
    ("byte_count", "expected"),
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (50381.6, "49.2 KB"),
        (5 * 1024**2, "5.0 MB"),
        (3 * 1024**4, "3.0 TB"),
        (2048 * 1024**4, "2048.0 TB"),
    ],
)
def test_format_bytes_uses_largest_binary_unit_below_1024(byte_count, expected):
    assert format_bytes(byte_count) == expected
