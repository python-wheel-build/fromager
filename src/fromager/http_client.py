"""
This module acts as a HTTP client with the Retry approach to make code more resilient to network hiccups and connection issues
It has been adopted from: https://www.raelldottin.com/2023/09/enhancing-resilience-in-your-python.html
"""

import requests
from requests.adapters import HTTPAdapter, Retry


class HTTPClient:
    # Set up the retries, backoff_factor and status_forcelist
    def __init__(self, base_url, retries=5, backoff_factor=0.1, status_forcelist=None):
        self.base_url = base_url
        self.session = requests.Session()

        if status_forcelist is None:
            status_forcelist = [500, 502, 503, 504]

        # Initialize the retries object
        retries = Retry(
            total=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
        )

        # Initialize the adapter object
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    # Get request function to make HTTP GET request using session and Retry
    def get_request(self, endpoint="", **kwargs):
        url = f"{self.base_url}{endpoint}"
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response
