import requests
from config import ADMIN_API_BASE_URL
from logger import Logger

"""
auth.py

This module contains the function for authenticating with MongoDB Atlas using
public and private API keys.

Constants:
    ADMIN_API_BASE_URL (str): The base URL for the MongoDB Atlas Admin API.

Functions:
    authenticate(public_api_key, private_api_key): Authenticate with MongoDB Atlas and obtain an access token.
"""


def authenticate(public_api_key, private_api_key, logger=None):
    """
    Authenticate with MongoDB Atlas using the provided public and private API keys.

    This function sends a POST request to the MongoDB Atlas authentication endpoint
    with the provided public and private API keys. If the authentication is successful,
    it returns the access token.

    Args:
        public_api_key (str): The public API key for MongoDB Atlas.
        private_api_key (str): The private API key for MongoDB Atlas.

    Returns:
        str: The access token obtained from MongoDB Atlas.

    Raises:
        requests.exceptions.HTTPError: If the HTTP request returned an unsuccessful status code.
        requests.exceptions.RequestException: For other types of request-related errors.
    """
    if logger is None:
        logger = Logger()

    url = f"{ADMIN_API_BASE_URL}/auth/providers/mongodb-cloud/login"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    payload = {"username": public_api_key, "apiKey": private_api_key}

    logger.info("Sending authentication request to MongoDB Atlas.")
    logger.debug(f"Authenticating to {url} with public key: {public_api_key}")
    response = requests.post(url, headers=headers, json=payload)
    try:
        response.raise_for_status()
        logger.info("Authentication successful.")
        logger.debug(f"Received access token: {response.json()['access_token']}")
        return response.json()["access_token"]
    except requests.exceptions.HTTPError as err:
        logger.error(f"Authentication failed: {err}")
        raise
