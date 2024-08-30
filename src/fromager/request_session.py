import requests
from requests.adapters import HTTPAdapter

session = requests.Session()
_adapter = HTTPAdapter(max_retries=5)
session.mount("http://", _adapter)
session.mount("https://", _adapter)
