import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class Config:
    # Telegram Bot Configuration
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    API_ID: int = int(os.getenv("API_ID", "0"))
    API_HASH: str = os.getenv("API_HASH", "")
    
    # PW API Configuration
    DEFAULT_HEADERS = {
        'client-id': '5eb393ee95fab7468a79d189',
        'client-type': 'WEB',
        'client-version': '200',
        'content-type': 'application/json',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    }
    
    # Download Configuration
    DOWNLOAD_DIR: str = os.getenv("DOWNLOAD_DIR", "./downloads")
    MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "8"))
    
    # Admin Configuration
    ADMIN_IDS: list = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

config = Config()