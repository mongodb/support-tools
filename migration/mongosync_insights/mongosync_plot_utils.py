def format_byte_size(bytes):
    # Define the conversion factors
    kilobyte = 1024
    megabyte = kilobyte * 1024
    gigabyte = megabyte * 1024
    terabyte = gigabyte * 1024
    # Determine the appropriate unit and calculate the value
    if bytes >= terabyte:
        value = bytes / terabyte
        unit = 'TeraBytes'
    elif bytes >= gigabyte:
        value = bytes / gigabyte
        unit = 'GigaBytes'
    elif bytes >= megabyte:
        value = bytes / megabyte
        unit = 'MegaBytes'
    elif bytes >= kilobyte:
        value = bytes / kilobyte
        unit = 'KiloBytes'
    else:
        value = bytes
        unit = 'Bytes'
    # Return the value rounded to two decimal places and the unit separately
    return round(value, 4), unit

def convert_bytes(bytes, target_unit):
    # Define conversion factors
    kilobyte = 1024
    megabyte = kilobyte * 1024
    gigabyte = megabyte * 1024
    terabyte = gigabyte * 1024
    # Perform conversion based on target unit
    if target_unit == 'KiloBytes':
        value = bytes / kilobyte
    elif target_unit == 'MegaBytes':
        value = bytes / megabyte
    elif target_unit == 'GigaBytes':
        value = bytes / gigabyte
    elif target_unit == 'TeraBytes':
        value = bytes / terabyte
    else:
        value = bytes
    # Return the converted value rounded to two decimal places and the unit
    return round(value, 4)