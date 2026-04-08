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
