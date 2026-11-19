import re
import argparse
from functools import wraps

"""
utils.py

This module contains utility functions for validating various types of input values.
These functions are used to ensure that input values meet specific criteria before
they are processed by other parts of the application.

Functions:
    validate_hex(value): Validate that the given string is a valid hexadecimal string.
    validate_string(value): Validate that the given string is a non-empty string.
    validate_private_key(value): Validate that the given string is a valid private key format.
    validate_date(value): Validate that the given date string follows the ISO 8601 format.
    validate_types(value): Validate that the given string is a comma-separated list of valid log types.
"""


def validate_hex(value):
    """
    validate_hex function checks if the input is a valid ObjectID hexadecimal string.
    """
    if not re.fullmatch(r"^[0-9a-fA-F]{24}$", value):
        raise argparse.ArgumentTypeError(f"{value} is not a valid ObjectID hexadecimal string")

    return value


def validate_string(value):
    """
    validate_string function checks if the input is a valid string.
    """
    if not isinstance(value, str) or not value.strip():
        raise argparse.ArgumentTypeError(f"{value} is not a valid string")

    return value


def validate_private_key(value):
    """
    validate_private_key function checks if the input is a valid private key format.
    """
    if not re.fullmatch(r"[0-9a-fA-F-]+", value):
        raise argparse.ArgumentTypeError(f"{value} is not a valid private key format")

    return value


def validate_date(value):
    """
    Validate that the given date string follows the ISO 8601 format: YYYY-MM-DDTHH:MM:SS.MMM.

    Args:
        value (str): The date string to validate.

    Returns:
        str: The validated date string.

    Raises:
        argparse.ArgumentTypeError: If the date string does not follow the ISO 8601 format.
    """
    iso_8601_pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z"
    if not re.fullmatch(iso_8601_pattern, value):
        raise argparse.ArgumentTypeError(
            f"{value} is not a valid date format. Use 'YYYY-MM-DDTHH:MM:SS.MMMZ'"
        )
    return value


def validate_types(value):
    """
    Validate that the given string is a comma-separated list of valid log types.

    Args:
        value (str): The comma-separated list of log types to validate.

    Returns:
        list: The validated list of log types.

    Raises:
        argparse.ArgumentTypeError: If any of the log types are not valid.
    """
    valid_types = [
        "TRIGGER_FAILURE",
        "TRIGGER_ERROR_HANDLER",
        "DB_TRIGGER",
        "AUTH_TRIGGER",
        "SCHEDULED_TRIGGER",
        "FUNCTION",
        "SERVICE_FUNCTION",
        "STREAM_FUNCTION",
        "SERVICE_STREAM_FUNCTION",
        "AUTH",
        "WEBHOOK",
        "ENDPOINT",
        "PUSH",
        "API",
        "API_KEY",
        "GRAPHQL",
        "SYNC_CONNECTION_START",
        "SYNC_CONNECTION_END",
        "SYNC_SESSION_START",
        "SYNC_SESSION_END",
        "SYNC_CLIENT_WRITE",
        "SYNC_ERROR",
        "SYNC_OTHER",
        "SCHEMA_ADDITIVE_CHANGE",
        "SCHEMA_GENERATION",
        "SCHEMA_VALIDATION",
        "LOG_FORWARDER",
    ]
    types = value.split(",")
    for t in types:
        if t not in valid_types:
            raise argparse.ArgumentTypeError(
                f"{t} is not a valid type. Valid types are: {', '.join(valid_types)}"
            )

    return value
