import argparse
import json
from auth import authenticate
from log_pager import LogPager
from logger import Logger
from utils import (
    validate_hex,
    validate_string,
    validate_private_key,
    validate_date,
    validate_types,
)


def parse_filtering_args(filtering_args):
    """
    Parse filtering arguments into a dictionary.

    Args:
        filtering_args (list): List of key-value pairs.

    Returns:
        dict: Dictionary of parsed key-value pairs.
    """
    filter_dic = {}
    for arg in filtering_args:
        key, value = arg.split("=")
        filter_dic[key] = value
    return filter_dic


def main():
    parser = argparse.ArgumentParser(
        description="Fetch logs from App Services Application using pagination."
    )
    parser.add_argument(
        "project_id", type=validate_hex, help="Atlas Project ID (hexadecimal string)"
    )
    parser.add_argument("app_id", type=validate_hex, help="App ID (string)")
    parser.add_argument(
        "public_api_key", type=validate_string, help="Atlas Public API Key (string)"
    )
    parser.add_argument(
        "private_api_key",
        type=validate_private_key,
        help="Atlas Private API Key (hexadecimal string)",
    )
    parser.add_argument(
        "--start_date",
        type=validate_date,
        default=None,
        help="Start Date in ISO 8601 format (YYYY-MM-DDTHH:MM:SS.MMMZ)",
    )
    parser.add_argument(
        "--end_date",
        type=validate_date,
        default=None,
        help="End Date in ISO 8601 format (YYYY-MM-DDTHH:MM:SS.MMMZ)",
    )
    parser.add_argument(
        "--user_id",
        type=validate_hex,
        default=None,
        help="Return only log messages associated with the given user_id.",
    )
    parser.add_argument(
        "--co_id",
        type=validate_hex,
        default=None,
        help="Return only log messages associated with the given request Correlation ID.",
    )
    parser.add_argument(
        "--type",
        type=validate_types,
        default=None,
        help="Comma-separated list of log types to fetch",
    )
    parser.add_argument(
        "--errors_only", action="store_true", help="Return only error log messages"
    )
    parser.add_argument(
        "--filter",
        nargs="+",
        help="Filter logs by key-value pairs (e.g., --filter key1=value1 key2=value2)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    filter_dic = parse_filtering_args(args.filter) if args.filter else {}

    logger = Logger(verbose=args.verbose)
    logger.info("Starting log fetching process...")

    try:
        access_token = authenticate(args.public_api_key, args.private_api_key)
        query_params = {
            "start_date": args.start_date,
            "end_date": args.end_date,
            "type": args.type,
            "user_id": args.user_id,
            "co_id": args.co_id,
        }
        if args.errors_only:
            query_params["errors_only"] = (
                "true"  # Add the only_error parameter if the flag is specified
            )

        pager = LogPager(
            args.project_id,
            args.app_id,
            access_token,
            query_params,
            filtering=filter_dic,  # Pass the filtering dictionary
            logger=logger,
        )

        all_logs = pager.get_all_logs()
        with open("logs.json", "w") as file:
            json.dump(all_logs, file, indent=4)

        logger.info("Log fetching process completed successfully.")

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")


if __name__ == "__main__":
    main()
