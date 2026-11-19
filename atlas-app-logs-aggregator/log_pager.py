import requests
from logger import Logger
from config import ADMIN_API_BASE_URL

"""
log_pager.py

This module contains the LogPager class, which is responsible for fetching logs
from a MongoDB Atlas App Services application using pagination.

Classes:
    LogPager: A class to handle pagination and fetching logs from MongoDB Atlas.
"""


class LogPager:
    """
    A class to handle pagination and fetching logs from MongoDB Atlas.

    Attributes:
        logs_endpoint (str): The endpoint URL for fetching logs.
        query_params (dict): The query parameters for the log request.
        auth_headers (dict): The authorization headers for the log request.
        logger (Logger): The logger instance for logging operations.
    """

    def __init__(
        self,
        project_id,
        app_id,
        access_token,
        query_params={},
        filtering={},
        logger=None,
    ):
        """
        Initialize the LogPager with project ID, app ID, access token, query parameters, and logger.

        Args:
            project_id (str): The Atlas Project ID.
            app_id (str): The App ID.
            access_token (str): The access token obtained from MongoDB Atlas.
            query_params (dict, optional): The query parameters for the log request. Defaults to {}.
            logger (Logger, optional): The logger instance for logging operations. Defaults to None.
        """
        self.logs_endpoint = (
            f"{ADMIN_API_BASE_URL}/groups/{project_id}/apps/{app_id}/logs"
        )
        self.query_params = query_params
        self.filtering = filtering
        self.auth_headers = {"Authorization": f"Bearer {access_token}"}
        self.logger = logger or Logger()

    def get_next_page(self, prev_page=None):
        """
        Fetch the next page of logs.

        Args:
            prev_page (dict, optional): The previous page of logs. Defaults to None.

        Returns:
            dict: The next page of logs.

        Raises:
            Exception: If there are no more pages to fetch.
            requests.exceptions.HTTPError: If the HTTP request returned an unsuccessful status code.
        """
        next_end_date = prev_page.get("nextEndDate") if prev_page else None
        self.logger.debug(f"Fetching logs with end date: {next_end_date}")
        next_skip = prev_page.get("nextSkip") if prev_page else None
        self.logger.debug(f"Fetching logs with skip: {next_skip}")
        if prev_page and not next_end_date:
            self.logger.error("Paginated API does not have any more pages.")
            raise Exception("Paginated API does not have any more pages.")

        params = {**self.query_params, "end_date": next_end_date, "skip": next_skip}
        self.logger.debug(f"Fetching logs with params: {params}")
        try:
            response = requests.get(
                self.logs_endpoint, headers=self.auth_headers, params=params
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP error occurred: {e}")
            try:
                error_message = response.json().get(
                    "error", "No error message provided"
                )
                self.logger.error(f"Error message from response: {error_message}")
            except ValueError as e:
                self.logger.error("Failed to parse error message from response")
            raise e

    def filter_logs(self, logs):
        """
        Filter logs based on the filtering dictionary.

        Args:
            logs (list): List of log entries.

        Returns:
            list: Filtered list of log entries.
        """
        if not self.filtering:
            return logs

        def log_matches_filter(log):
            """
            Check if a log entry matches the filtering criteria and log the process.

            Args:
                log (dict): A log entry.

            Returns:
                bool: True if the log entry matches the filtering criteria, False otherwise.
            """
            for (
                key,
                value,
            ) in (
                self.filtering.items()
            ):  # iterates over the key-value pairs in the filtering dictionary.

                log_value = log.get(key)
                if log_value is None:
                    self.logger.debug(f"Key '{key}' not found in log entry: {log}")
                    return False
                if log_value != value:
                    self.logger.debug(
                        f"Value mismatch for key '{key}': expected '{value}', found '{log_value}'"
                    )
                    return False
            return True

        """
        Iterates over each log in the logs list and applies the log_matches_filter function.
        * Only the first log entry matches the filtering criteria, so it is included in the filtered_logs list.
        * The other log entries do not match the criteria and are excluded from the filtered_logs list.
        """
        filtered_logs = [log for log in logs if log_matches_filter(log)]
        return filtered_logs

    def get_all_logs(self):
        """
        Fetch all logs using pagination.

        Returns:
            list: A list of all logs.

        Raises:
            requests.exceptions.HTTPError: If the HTTP request returned an unsuccessful status code.
        """
        logs = []
        has_next = True
        prev_page = None
        page_number = 1  # Initialize page counter
        while has_next:
            self.logger.info(
                f"Fetching page {page_number}..."
            )  # Log current page number
            page = self.get_next_page(prev_page)
            filtered_logs = self.filter_logs(page["logs"])
            logs.extend(filtered_logs)
            has_next = "nextEndDate" in page
            prev_page = page
            page_number += 1  # Increment page counter
        return logs
