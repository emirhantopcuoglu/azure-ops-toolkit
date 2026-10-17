"""Plain-text rendering shared by CLI commands."""

from collections.abc import Sequence

TABLE_COLUMN_GAP = "  "
TAG_SEPARATOR = ";"
BYTES_PER_UNIT_STEP = 1024
BYTE_UNITS = ("B", "KB", "MB", "GB", "TB")


def format_bytes(byte_count: float) -> str:
    """Render a byte count with a binary (1024-based) unit, e.g. 50381 -> '49.2 KB'."""
    value = float(byte_count)
    for unit in BYTE_UNITS[:-1]:
        if abs(value) < BYTES_PER_UNIT_STEP:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= BYTES_PER_UNIT_STEP
    return f"{value:.1f} {BYTE_UNITS[-1]}"


def format_tags(tags: dict[str, str]) -> str:
    """Flatten tags into a stable single-line form: key=value pairs sorted by key."""
    return TAG_SEPARATOR.join(f"{key}={value}" for key, value in sorted(tags.items()))


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Render rows as left-aligned columns sized to their widest cell."""
    all_rows = [headers, *rows]
    column_widths = [max(len(row[index]) for row in all_rows) for index in range(len(headers))]
    lines = [
        TABLE_COLUMN_GAP.join(cell.ljust(width) for cell, width in zip(row, column_widths)).rstrip()
        for row in all_rows
    ]
    return "\n".join(lines)
