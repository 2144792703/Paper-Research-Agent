import os
from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("MODEL")
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")

REQUEST_TIMEOUT = os.getenv('REQUEST_TIMEOUT', '600.0')
MAX_RETRIES = os.getenv('MAX_RETRIES', '2')