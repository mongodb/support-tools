def format_bytes_compact(size_bytes):
    """Human-readable byte size (e.g. 6.2 GB)."""
    if size_bytes is None or size_bytes < 0:
        return "—"
    if size_bytes == 0:
        return "0 B"
    import math

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    tier = min(len(units) - 1, int(math.log(size_bytes, 1024)) if size_bytes >= 1024 else 0)
    value = size_bytes / (1024 ** tier)
    decimals = 0 if value >= 100 or tier == 0 else 1
    return f"{value:.{decimals}f} {units[tier]}"


def format_lag_time_seconds(seconds):
    """Format seconds as human-readable duration (e.g. 26m 22s)."""
    if seconds is None or seconds < 0:
        return "—"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def format_count(value):
    if value is None:
        return "—"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "—"


def format_ratio(numerator, denominator):
    return f"{format_count(numerator)} / {format_count(denominator)}"


def format_byte_size(size_bytes):
    kilobyte = 1024
    megabyte = kilobyte * 1024
    gigabyte = megabyte * 1024
    terabyte = gigabyte * 1024
    if size_bytes >= terabyte:
        value = size_bytes / terabyte
        unit = 'TeraBytes'
    elif size_bytes >= gigabyte:
        value = size_bytes / gigabyte
        unit = 'GigaBytes'
    elif size_bytes >= megabyte:
        value = size_bytes / megabyte
        unit = 'MegaBytes'
    elif size_bytes >= kilobyte:
        value = size_bytes / kilobyte
        unit = 'KiloBytes'
    else:
        value = size_bytes
        unit = 'Bytes'
    return round(value, 4), unit

def convert_bytes(size_bytes, target_unit):
    kilobyte = 1024
    megabyte = kilobyte * 1024
    gigabyte = megabyte * 1024
    terabyte = gigabyte * 1024
    if target_unit == 'KiloBytes':
        value = size_bytes / kilobyte
    elif target_unit == 'MegaBytes':
        value = size_bytes / megabyte
    elif target_unit == 'GigaBytes':
        value = size_bytes / gigabyte
    elif target_unit == 'TeraBytes':
        value = size_bytes / terabyte
    else:
        value = size_bytes
    return round(value, 4)
