"""
TellCoSOL SAM.gov collector — initial connection test.

This script:
1. Loads the SAM.gov API key from the repository .env file.
2. Requests a small number of solar-related opportunities.
3. Displays basic request information.
4. Saves the raw API response as JSON.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


# ------------------------------------------------------------
# PROJECT PATHS
# ------------------------------------------------------------

# This file is located at:
# repository/scripts/collect_sam_data.py
#
# parents[1] moves up from "scripts" to the repository root.
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"

DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------
# LOAD API KEY
# ------------------------------------------------------------

ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)

SAM_API_KEY = os.getenv("SAM_API_KEY")

if not SAM_API_KEY:
    raise RuntimeError(
        "SAM_API_KEY was not found. "
        "Confirm that the repository root contains a .env file with:\n"
        "SAM_API_KEY=your_actual_key"
    )


# ------------------------------------------------------------
# API CONFIGURATION
# ------------------------------------------------------------

API_URL = "https://api.sam.gov/opportunities/v2/search"

TODAY = date.today()
THIRTY_DAYS_AGO = TODAY - timedelta(days=30)

POSTED_FROM = THIRTY_DAYS_AGO.strftime("%m/%d/%Y")
POSTED_TO = TODAY.strftime("%m/%d/%Y")

SEARCH_KEYWORD = "solar"
LIMIT = 10
OFFSET = 0


# ------------------------------------------------------------
# API REQUEST
# ------------------------------------------------------------

def request_opportunities() -> dict[str, Any]:
    """
    Request a small test page of SAM.gov opportunities.
    """

    params = {
        "api_key": SAM_API_KEY,
        "postedFrom": POSTED_FROM,
        "postedTo": POSTED_TO,
        "title": SEARCH_KEYWORD,
        "limit": LIMIT,
        "offset": OFFSET,
    }

    print("Calling SAM.gov...")
    print(f"Posting period: {POSTED_FROM} to {POSTED_TO}")
    print(f"Title keyword: {SEARCH_KEYWORD}")
    print(f"Requested records: {LIMIT}")

    response = requests.get(
        API_URL,
        params=params,
        timeout=60,
    )

    print(f"HTTP status: {response.status_code}")

    if response.status_code == 401:
        raise RuntimeError(
            "SAM.gov returned 401 Unauthorized. "
            "Check that the API key was copied correctly."
        )

    if response.status_code == 403:
        raise RuntimeError(
            "SAM.gov returned 403 Forbidden. "
            "The API key may not have access or may have reached a limit."
        )

    if response.status_code == 404:
        return {
            "totalRecords": 0,
            "opportunitiesData": [],
        }

    response.raise_for_status()

    return response.json()


# ------------------------------------------------------------
# SAVE RAW JSON
# ------------------------------------------------------------

def save_raw_response(payload: dict[str, Any]) -> Path:
    """
    Save the raw API response for validation and later cleaning.
    """

    output_file = (
        RAW_DATA_DIR
        / f"sam_test_{TODAY.strftime('%Y_%m_%d')}.json"
    )

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            payload,
            file,
            indent=2,
            ensure_ascii=False,
        )

    return output_file


# ------------------------------------------------------------
# MAIN PROGRAM
# ------------------------------------------------------------

def main() -> None:
    """
    Run the initial SAM.gov API connection test.
    """

    payload = request_opportunities()

    records = payload.get("opportunitiesData", [])
    total_records = payload.get("totalRecords", 0)

    print()
    print(f"Total matching records reported: {total_records}")
    print(f"Records returned in this request: {len(records)}")

    if records:
        print()
        print("First opportunity:")
        print(f"Title: {records[0].get('title')}")
        print(f"Notice ID: {records[0].get('noticeId')}")
        print(f"Posted date: {records[0].get('postedDate')}")
    else:
        print("No matching opportunities were returned.")

    output_file = save_raw_response(payload)

    print()
    print(f"Raw response saved to:")
    print(output_file)


if __name__ == "__main__":
    main()
