"""Collect open SAM.gov opportunities for the TellCoSOL dashboard.

The SAM.gov Opportunities API does not currently support an ``active`` value
for the ``ptype`` parameter. This collector therefore searches by title and
posting period, then cleans, deduplicates, and separates open opportunities from expired notices.

Outputs are written for the dashboard only after a complete successful run.
Per-page JSON caches make interrupted Codespace runs resumable.

Award Notices are retained in the complete audit dataset but excluded from the current-opportunities Streamlit outputs.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from requests.exceptions import (
    ConnectTimeout,
    JSONDecodeError as RequestsJSONDecodeError,
    ReadTimeout,
    RequestException,
)
from urllib3.util.retry import Retry


API_URL = "https://api.sam.gov/opportunities/v2/search"
DEFAULT_KEYWORDS = (
    "microgrid",
    "solar",
    "BESS",
    "mobile power",
    "energy resilience",
    "water pumping",
    "telecom power",
    "clinic electrification",
    "mini-grid",
    "diesel generator",
    "disaster recovery",
)

NOTICE_TYPE_MAP = {
    "p": "Pre-Solicitation",
    "o": "Solicitation",
    "k": "Combined Synopsis/Solicitation",
    "r": "Sources Sought",
    "s": "Special Notice",
    "i": "Intent to Bundle",
    "a": "Award Notice",
    "g": "Sale of Surplus Property",
    "u": "Justification",
}


OPPORTUNITY_TYPE_NORMALIZATION = {
    "presolicitation": "Pre-Solicitation",
    "pre solicitation": "Pre-Solicitation",
    "pre-solicitation": "Pre-Solicitation",
    "combined synopsis/solicitation": "Combined Synopsis/Solicitation",
    "combined synopsis solicitation": "Combined Synopsis/Solicitation",
    "sources sought": "Sources Sought",
    "special notice": "Special Notice",
    "solicitation": "Solicitation",
    "award notice": "Award Notice",
}

AGENCY_NAME_RULES = (
    ("agriculture, department of", "Department of Agriculture"),
    ("department of agriculture", "Department of Agriculture"),
    ("interior, department of the", "Department of the Interior"),
    ("department of the interior", "Department of the Interior"),
    ("state, department of", "Department of State"),
    ("department of state", "Department of State"),
    ("energy, department of", "Department of Energy"),
    ("department of energy", "Department of Energy"),
    ("commerce, department of", "Department of Commerce"),
    ("department of commerce", "Department of Commerce"),
    ("transportation, department of", "Department of Transportation"),
    ("department of transportation", "Department of Transportation"),
    ("homeland security, department of", "Department of Homeland Security"),
    ("department of homeland security", "Department of Homeland Security"),
    ("veterans affairs, department of", "Department of Veterans Affairs"),
    ("department of veterans affairs", "Department of Veterans Affairs"),
    ("defense, department of", "Department of Defense"),
    ("department of defense", "Department of Defense"),
    ("dept of defense", "Department of Defense"),
    ("department of the army", "Department of Defense"),
    ("department of the navy", "Department of Defense"),
    ("department of the air force", "Department of Defense"),
    ("general services administration", "General Services Administration"),
    ("environmental protection agency", "Environmental Protection Agency"),
    ("national aeronautics and space administration", "NASA"),
    ("national science foundation", "National Science Foundation"),
    ("small business administration", "Small Business Administration"),
    ("agency for international development", "U.S. Agency for International Development"),
    ("usaid", "U.S. Agency for International Development"),
)

COUNTRY_NAME_RULES = {
    "us": "United States",
    "u.s.": "United States",
    "usa": "United States",
    "u.s.a.": "United States",
    "united states": "United States",
    "united states of america": "United States",
    "uganda": "Uganda",
}

FALSE_POSITIVE_PATTERNS = (
    (r"\bsolar shades?\b", "Solar shade product, not a solar-energy opportunity"),
    (r"\bsolar camera\b", "Solar appears in a camera product name"),
    (r"\bsolarcore\b", "Solar appears in a material or brand name"),
    (r"\btbess\b", "BESS appears only inside the unrelated acronym TBESS"),
)

REVIEW_PATTERNS = (
    (r"\bindustry days?\b", "Industry-day or outreach notice requires analyst review"),
    (r"\boutreach event\b", "Outreach event requires analyst review"),
)

DEADLINE_BANDS = (
    "<= 14 days",
    "15-30 days",
    "31-60 days",
    "60+ days",
    "No deadline",
    "Past deadline",
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PAGE_CACHE_DIR = RAW_DIR / "pages"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
HISTORY_DIR = DATA_DIR / "history"
LOG_DIR = PROJECT_ROOT / "logs"

CURRENT_PARQUET = DATA_DIR / "sam_opportunities_current.parquet"
CURRENT_CSV = DATA_DIR / "sam_opportunities_current.csv"
ALL_PARQUET = DATA_DIR / "sam_opportunities_all.parquet"
ALL_CSV = DATA_DIR / "sam_opportunities_all.csv"
REVIEW_PARQUET = DATA_DIR / "sam_opportunities_review.parquet"
REVIEW_CSV = DATA_DIR / "sam_opportunities_review.csv"
AGENCY_PARQUET = DATA_DIR / "opportunities_by_agency.parquet"
AGENCY_CSV = DATA_DIR / "opportunities_by_agency.csv"
TYPE_PARQUET = DATA_DIR / "opportunities_by_type.parquet"
TYPE_CSV = DATA_DIR / "opportunities_by_type.csv"
DEADLINE_PARQUET = DATA_DIR / "deadline_distribution.parquet"
DEADLINE_CSV = DATA_DIR / "deadline_distribution.csv"
SUMMARY_PARQUET = DATA_DIR / "dashboard_summary.parquet"
SUMMARY_CSV = DATA_DIR / "dashboard_summary.csv"
SOURCE_HEALTH_PARQUET = DATA_DIR / "source_health.parquet"
SOURCE_HEALTH_CSV = DATA_DIR / "source_health.csv"
FAILED_KEYWORDS_CSV = DATA_DIR / "failed_keywords.csv"
RUN_STATUS_JSON = DATA_DIR / "sam_run_status.json"

LOGGER = logging.getLogger("tellcosol.sam")


class CollectorError(RuntimeError):
    """A collection error with a flag for failures that must stop the run."""

    def __init__(self, message: str, *, fatal: bool = False) -> None:
        super().__init__(message)
        self.fatal = fatal


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def configure_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"collect_sam_data_{datetime.now():%Y%m%d_%H%M%S}.log"
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(console)
    LOGGER.addHandler(file_handler)
    return path


def ensure_directories() -> None:
    for directory in (
        DATA_DIR,
        RAW_DIR,
        PAGE_CACHE_DIR,
        CHECKPOINT_DIR,
        HISTORY_DIR,
        LOG_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or text.casefold() in {"none", "null", "nan", "n/a", "na"}:
        return None
    return text


def first_text(*values: Any) -> str | None:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return None


def nested_dict(record: dict[str, Any], key: str) -> dict[str, Any]:
    value = record.get(key)
    if isinstance(value, dict):
        return value
    data = record.get("data")
    if isinstance(data, dict) and isinstance(data.get(key), dict):
        return data[key]
    return {}


def named_value(value: Any) -> str | None:
    if isinstance(value, dict):
        return first_text(value.get("name"), value.get("code"))
    return clean_text(value)


def normalize_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = (clean_text(value) or "").casefold()
    if normalized in {"yes", "y", "true", "1", "active"}:
        return True
    if normalized in {"no", "n", "false", "0", "inactive", "archived"}:
        return False
    return None


def keyword_slug(keyword: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", keyword.casefold()).strip("-") or "query"


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def write_frame_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        if path.suffix == ".parquet":
            frame.to_parquet(temporary, index=False)
        elif path.suffix == ".csv":
            frame.to_csv(temporary, index=False, encoding="utf-8-sig")
        else:
            raise ValueError(f"Unsupported output type: {path.suffix}")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def save_frame_pair(frame: pd.DataFrame, parquet: Path, csv: Path) -> None:
    write_frame_atomic(frame, parquet)
    write_frame_atomic(frame, csv)


def build_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1.0,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "TellCoSOL-SAM-Dashboard/2.0",
        }
    )
    return session


def redacted_excerpt(response: requests.Response, api_key: str) -> str:
    return response.text.replace(api_key, "[REDACTED]").replace("\n", " ")[:400]


def fetch_page(
    session: requests.Session,
    *,
    api_key: str,
    keyword: str,
    posted_from: date,
    posted_to: date,
    page_size: int,
    page_index: int,
    connect_timeout: float,
    read_timeout: float,
) -> dict[str, Any]:
    # Do not pass ptype="active". ptype accepts notice-type codes, not status.
    params = {
        "api_key": api_key,
        "postedFrom": posted_from.strftime("%m/%d/%Y"),
        "postedTo": posted_to.strftime("%m/%d/%Y"),
        "title": keyword,
        "limit": page_size,
        "offset": page_index,
    }
    LOGGER.info("Requesting keyword=%r page=%s", keyword, page_index + 1)
    started = time.monotonic()
    try:
        response = session.get(
            API_URL,
            params=params,
            timeout=(connect_timeout, read_timeout),
        )
    except ConnectTimeout as exc:
        raise CollectorError(
            f"Connection timed out after {connect_timeout:g} seconds."
        ) from exc
    except ReadTimeout as exc:
        raise CollectorError(
            f"SAM.gov did not finish responding within {read_timeout:g} seconds."
        ) from exc
    except RequestException as exc:
        raise CollectorError(f"Request failed: {exc}") from exc

    LOGGER.info(
        "SAM.gov returned HTTP %s in %.1f seconds",
        response.status_code,
        time.monotonic() - started,
    )

    if response.status_code == 404:
        return {
            "totalRecords": 0,
            "limit": page_size,
            "offset": page_index,
            "opportunitiesData": [],
        }
    if response.status_code == 401:
        raise CollectorError("SAM.gov rejected SAM_API_KEY (HTTP 401).", fatal=True)
    if response.status_code == 403:
        raise CollectorError(
            "SAM.gov denied access or the key reached its limit (HTTP 403).",
            fatal=True,
        )
    if response.status_code == 429:
        raise CollectorError(
            "SAM.gov rate-limited the API key (HTTP 429). Stop and retry later.",
            fatal=True,
        )
    if response.status_code >= 400:
        raise CollectorError(
            f"SAM.gov returned HTTP {response.status_code}: "
            f"{redacted_excerpt(response, api_key)}",
            fatal=response.status_code == 400,
        )

    try:
        payload = response.json()
    except RequestsJSONDecodeError as exc:
        raise CollectorError(
            "SAM.gov returned invalid JSON: "
            f"{redacted_excerpt(response, api_key)}"
        ) from exc
    if not isinstance(payload, dict):
        raise CollectorError("SAM.gov returned an unexpected JSON structure.")
    records = payload.get("opportunitiesData", [])
    if records is None:
        payload["opportunitiesData"] = []
    elif not isinstance(records, list):
        raise CollectorError("opportunitiesData was not a list.")
    return payload


def cached_or_live_page(
    session: requests.Session,
    *,
    cache_path: Path,
    force: bool,
    **request_args: Any,
) -> tuple[dict[str, Any], bool]:
    if cache_path.exists() and not force:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(
                payload.get("opportunitiesData", []), list
            ):
                LOGGER.info("Resuming from %s", cache_path)
                return payload, True
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Ignoring unreadable cache %s", cache_path)

    payload = fetch_page(session, **request_args)
    write_json_atomic(cache_path, payload)
    return payload, False


def collect_keyword(
    session: requests.Session,
    *,
    api_key: str,
    run_id: str,
    keyword: str,
    posted_from: date,
    posted_to: date,
    page_size: int,
    max_pages: int,
    force: bool,
    connect_timeout: float,
    read_timeout: float,
    pause_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    reported_total = 0
    api_requests = 0
    cache_hits = 0
    truncated = False
    cache_root = (
        PAGE_CACHE_DIR
        / f"{posted_from:%Y%m%d}_{posted_to:%Y%m%d}"
        / f"limit_{page_size}"
        / keyword_slug(keyword)
    )

    for page_index in range(max_pages):
        payload, cache_hit = cached_or_live_page(
            session,
            cache_path=cache_root / f"page_{page_index:04d}.json",
            force=force,
            api_key=api_key,
            keyword=keyword,
            posted_from=posted_from,
            posted_to=posted_to,
            page_size=page_size,
            page_index=page_index,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )
        cache_hits += int(cache_hit)
        api_requests += int(not cache_hit)
        page_records = payload.get("opportunitiesData", [])
        try:
            reported_total = int(payload.get("totalRecords") or 0)
        except (TypeError, ValueError):
            reported_total = 0

        retrieved = utc_now().isoformat(timespec="seconds")
        for record in page_records:
            if isinstance(record, dict):
                copy = dict(record)
                copy["_matched_keyword"] = keyword
                copy["_retrieved_at"] = retrieved
                copy["_run_id"] = run_id
                records.append(copy)

        LOGGER.info(
            "Keyword %r: collected %s of %s reported records",
            keyword,
            len(records),
            reported_total,
        )
        if not page_records or len(records) >= reported_total > 0:
            break
        if len(page_records) < page_size:
            break
        if page_index + 1 >= max_pages:
            truncated = True
            break
        if not cache_hit and pause_seconds:
            time.sleep(pause_seconds)

    return records, {
        "keyword": keyword,
        "status": "Truncated" if truncated else "Completed",
        "records_collected": len(records),
        "records_reported_by_api": reported_total,
        "api_requests": api_requests,
        "cache_hits": cache_hits,
        "truncated": truncated,
        "error_type": None,
        "error_message": None,
        "checked_at_utc": utc_now().isoformat(timespec="seconds"),
    }


def normalize_agency_name(value: Any) -> str | None:
    """Return a consistent top-level buyer name for dashboard grouping."""

    text = clean_text(value)
    if not text:
        return None

    comparison = text.casefold()
    for phrase, canonical_name in AGENCY_NAME_RULES:
        if phrase in comparison:
            return canonical_name

    # Preserve the first organization when SAM.gov returns a hierarchy.
    first_segment = re.split(r"\s*(?:>|/|\||\.)\s*", text, maxsplit=1)[0]
    first_segment = clean_text(first_segment)
    if not first_segment:
        return None

    if first_segment.isupper() and len(first_segment) > 4:
        return first_segment.title()

    return first_segment


def agency_display(record: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return a canonical agency and preserve the original hierarchy."""

    path = clean_text(record.get("fullParentPathName"))
    for candidate in (
        record.get("department"),
        path,
        record.get("subTier"),
        record.get("office"),
    ):
        agency = normalize_agency_name(candidate)
        if agency:
            return agency, path

    return None, path


def opportunity_type(record: dict[str, Any], title: str | None) -> tuple[str, str | None]:
    """Return one standardized opportunity-type label."""

    code = first_text(record.get("type"), record.get("baseType"))
    title_key = (title or "").casefold()

    if re.search(r"\b(rfi|request for information)\b", title_key):
        return "RFI", code
    if re.search(r"\b(boa|blanket ordering agreement)\b", title_key):
        return "BOA", code
    if not code:
        return "Other", None

    code_key = code.casefold().strip()
    label = NOTICE_TYPE_MAP.get(code_key, code)
    normalized = OPPORTUNITY_TYPE_NORMALIZATION.get(
        (clean_text(label) or "").casefold(),
        clean_text(label) or "Other",
    )
    return normalized, code


def clean_location_value(value: Any) -> str | None:
    """Remove location placeholders such as 0 and Unknown."""

    text = clean_text(value)
    if not text:
        return None

    if text.casefold() in {
        "0",
        "00",
        "00000",
        "unknown",
        "not applicable",
        "not provided",
        "n/a",
    }:
        return None

    return text


def normalize_country_name(value: Any) -> str | None:
    """Standardize country names used in place-of-performance labels."""

    text = clean_location_value(value)
    if not text:
        return None

    key = text.casefold()
    if key in COUNTRY_NAME_RULES:
        return COUNTRY_NAME_RULES[key]

    if text.isupper() or text.islower():
        return text.title()

    return text


def extract_location(record: dict[str, Any]) -> dict[str, str | None]:
    """Extract and clean place-of-performance fields."""

    place = nested_dict(record, "placeOfPerformance")
    country = named_value(place.get("country")) or first_text(
        place.get("countryName"), place.get("countryCode")
    )
    state = named_value(place.get("state")) or first_text(
        place.get("stateName"), place.get("stateCode")
    )
    city = named_value(place.get("city"))
    zip_code = first_text(place.get("zip"), place.get("zipCode"))

    city = clean_location_value(city)
    state = clean_location_value(state)
    zip_code = clean_location_value(zip_code)
    country = normalize_country_name(country)

    if state and len(state) == 2:
        state = state.upper()
    elif state and (state.isupper() or state.islower()):
        state = state.title()

    parts = [part for part in (city, state, country) if part]
    return {
        "city": city,
        "state": state,
        "country": country,
        "zip_code": zip_code,
        "place_of_performance": ", ".join(parts) if parts else None,
    }


def extract_point_of_contact(record: dict[str, Any]) -> dict[str, str | None]:
    """Extract the primary SAM.gov point of contact when one is available."""

    contacts = record.get("pointOfContact")
    if contacts is None:
        contacts = nested_dict(record, "data").get("pointOfContact")
    if isinstance(contacts, dict):
        contacts = [contacts]
    if not isinstance(contacts, list):
        contacts = []

    primary: dict[str, Any] = {}
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        if not primary:
            primary = contact
        contact_type = (clean_text(contact.get("type")) or "").casefold()
        if contact_type in {"primary", "p"}:
            primary = contact
            break

    full_name = first_text(
        primary.get("fullName"),
        primary.get("fullname"),
        primary.get("name"),
    )
    if not full_name:
        full_name = first_text(
            " ".join(
                part
                for part in (
                    clean_text(primary.get("firstName")),
                    clean_text(primary.get("lastName")),
                )
                if part
            )
        )

    return {
        "primary_contact_name": full_name,
        "primary_contact_title": clean_text(primary.get("title")),
        "primary_contact_email": first_text(
            primary.get("email"), primary.get("emailAddress")
        ),
        "primary_contact_phone": first_text(
            primary.get("phone"), primary.get("phoneNumber")
        ),
    }


def extract_description(record: dict[str, Any]) -> str | None:
    """Extract text or a reference URL from SAM.gov's description field."""

    description = record.get("description")
    if description is None:
        description = nested_dict(record, "data").get("description")
    if isinstance(description, str):
        return clean_text(description)
    if isinstance(description, dict):
        return first_text(
            description.get("body"),
            description.get("text"),
            description.get("description"),
            description.get("href"),
        )
    if isinstance(description, list):
        fragments: list[str] = []
        for item in description:
            if isinstance(item, str):
                fragment = clean_text(item)
            elif isinstance(item, dict):
                fragment = first_text(
                    item.get("body"),
                    item.get("text"),
                    item.get("description"),
                    item.get("href"),
                )
            else:
                fragment = None
            if fragment:
                fragments.append(fragment)
        return " ".join(fragments) or None
    return None


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    notice_id = first_text(record.get("noticeId"), record.get("noticeID"))
    title = clean_text(record.get("title"))
    agency, agency_path = agency_display(record)
    type_label, type_code = opportunity_type(record, title)
    deadline = first_text(
        record.get("responseDeadLine"),
        record.get("responseDeadline"),
        record.get("reponseDeadLine"),
    )
    ui_link = clean_text(record.get("uiLink"))
    public_link = f"https://sam.gov/opp/{notice_id}/view" if notice_id else ui_link
    return {
        "notice_id": notice_id,
        "title": title,
        "agency": agency,
        "agency_code": clean_text(record.get("fullParentPathCode")),
        "agency_path": agency_path,
        "subtier": clean_text(record.get("subTier")),
        "office": clean_text(record.get("office")),
        "opportunity_type": type_label,
        "opportunity_type_code": type_code,
        "base_type": clean_text(record.get("baseType")),
        "posted_date": clean_text(record.get("postedDate")),
        "response_deadline": deadline,
        "archive_date": clean_text(record.get("archiveDate")),
        "active": normalize_boolean(record.get("active")),
        "set_aside": first_text(
            record.get("setAside"),
            record.get("typeOfSetAsideDescription"),
            record.get("setAsideDescription"),
        ),
        "set_aside_code": first_text(
            record.get("setAsideCode"), record.get("typeOfSetAside")
        ),
        "solicitation_number": clean_text(record.get("solicitationNumber")),
        "naics_code": clean_text(record.get("naicsCode")),
        "classification_code": clean_text(record.get("classificationCode")),
        "description": extract_description(record),
        "sam_gov_link": public_link,
        "api_ui_link": ui_link,
        "additional_information_link": clean_text(record.get("additionalInfoLink")),
        "resource_links": json.dumps(
            record.get("resourceLinks") or [], ensure_ascii=False
        ),
        "matched_keywords": clean_text(record.get("_matched_keyword")),
        "retrieved_at": clean_text(record.get("_retrieved_at")),
        "run_id": clean_text(record.get("_run_id")),
        **extract_location(record),
        **extract_point_of_contact(record),
    }


def join_keywords(values: pd.Series) -> str | None:
    unique: dict[str, str] = {}
    for value in values.dropna():
        for part in str(value).split("|"):
            text = clean_text(part)
            if text:
                unique.setdefault(text.casefold(), text)
    return " | ".join(unique.values()) or None


def classify_relevance(title: Any, description: Any, matched_keywords: Any) -> tuple[str, str | None, bool]:
    """Flag obvious keyword false positives without assigning a score."""

    combined = " ".join(
        part for part in (
            clean_text(title),
            clean_text(description),
            clean_text(matched_keywords),
        )
        if part
    ).casefold()

    for pattern, reason in FALSE_POSITIVE_PATTERNS:
        if re.search(pattern, combined, flags=re.IGNORECASE):
            return "Excluded", reason, False

    for pattern, reason in REVIEW_PATTERNS:
        if re.search(pattern, combined, flags=re.IGNORECASE):
            return "Needs Review", reason, True

    return "Included", None, True


def normalize_and_deduplicate(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [normalize_record(record) for record in records if isinstance(record, dict)]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "notice_id",
                "title",
                "agency",
                "agency_code",
                "opportunity_type",
                "base_type",
                "posted_date",
                "response_deadline",
                "days_left",
                "deadline_band",
                "set_aside",
                "place_of_performance",
                "description",
                "primary_contact_name",
                "primary_contact_title",
                "primary_contact_email",
                "primary_contact_phone",
                "sam_gov_link",
                "active",
                "matched_keywords",
                "run_id",
                "is_new_this_month",
                "is_closing_within_14_days",
                "is_open_for_response",
                "review_status",
                "review_reason",
                "dashboard_included",
            ]
        )

    for column in ("posted_date", "response_deadline", "archive_date", "retrieved_at"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
    frame["active"] = pd.array(frame["active"], dtype="boolean")

    fallback = (
        frame["solicitation_number"].fillna("").astype(str).str.casefold()
        + "|"
        + frame["title"].fillna("").astype(str).str.casefold()
        + "|"
        + frame["agency"].fillna("").astype(str).str.casefold()
    )
    valid_id = frame["notice_id"].fillna("").astype(str).str.strip().ne("")
    frame["_dedupe_key"] = frame["notice_id"].where(valid_id, "fallback|" + fallback)
    keyword_map = frame.groupby("_dedupe_key")["matched_keywords"].apply(join_keywords)
    frame = frame.sort_values("retrieved_at", ascending=False, na_position="last")
    # ``first`` selects the newest non-null value per column. This preserves
    # fields that are present in one keyword response but absent in another.
    frame = frame.groupby(
        "_dedupe_key", as_index=False, sort=False, dropna=False
    ).first()
    frame["matched_keywords"] = frame["_dedupe_key"].map(keyword_map)
    frame = frame.drop(columns="_dedupe_key")

    today = pd.Timestamp.now(tz="UTC").normalize()
    frame["days_left"] = pd.array(
        (frame["response_deadline"].dt.normalize() - today).dt.days,
        dtype="Int64",
    )

    def deadline_band(days: Any) -> str:
        if days is None or pd.isna(days):
            return "No deadline"
        value = int(days)
        if value < 0:
            return "Past deadline"
        if value <= 14:
            return "<= 14 days"
        if value <= 30:
            return "15-30 days"
        if value <= 60:
            return "31-60 days"
        return "60+ days"

    frame["deadline_band"] = frame["days_left"].map(deadline_band)
    month_start = today.replace(day=1)
    frame["is_new_this_month"] = (
        frame["posted_date"].notna()
        & frame["posted_date"].between(month_start, today, inclusive="both")
    )
    frame["is_closing_within_14_days"] = frame["days_left"].between(
        0, 14, inclusive="both"
    ).fillna(False)

    # SAM.gov's active flag does not guarantee that the response deadline
    # is still open. The dashboard therefore requires both an active record
    # and a non-expired deadline, while allowing notices with no deadline.
    frame["is_open_for_response"] = (
        frame["active"].eq(True)
        & ~frame["opportunity_type"].eq("Award Notice")
        & (
            frame["response_deadline"].isna()
            | frame["days_left"].ge(0)
        )
    ).fillna(False)

    relevance = [
        classify_relevance(title, description, keywords)
        for title, description, keywords in zip(
            frame["title"],
            frame["description"],
            frame["matched_keywords"],
        )
    ]
    frame["review_status"] = [item[0] for item in relevance]
    frame["review_reason"] = [item[1] for item in relevance]
    frame["dashboard_included"] = [item[2] for item in relevance]
    frame["source_system"] = "SAM.gov"
    return frame.sort_values(
        ["days_left", "posted_date", "title"],
        ascending=[True, False, True],
        na_position="last",
    ).reset_index(drop=True)


def create_dashboard_tables(open_opportunities: pd.DataFrame, run: dict[str, Any]) -> dict[str, pd.DataFrame]:
    agency = (
        open_opportunities.assign(agency=open_opportunities["agency"].fillna("Agency not provided"))
        .groupby("agency", dropna=False)
        .size()
        .reset_index(name="opportunity_count")
        .sort_values(["opportunity_count", "agency"], ascending=[False, True])
        .reset_index(drop=True)
    )
    notice_type = (
        open_opportunities.assign(
            opportunity_type=open_opportunities["opportunity_type"].fillna("Other")
        )
        .groupby("opportunity_type", dropna=False)
        .size()
        .reset_index(name="opportunity_count")
        .sort_values(
            ["opportunity_count", "opportunity_type"], ascending=[False, True]
        )
        .reset_index(drop=True)
    )
    counts = open_opportunities["deadline_band"].value_counts().to_dict()
    deadlines = pd.DataFrame(
        [
            {
                "deadline_band": band,
                "opportunity_count": int(counts.get(band, 0)),
                "display_order": index,
            }
            for index, band in enumerate(DEADLINE_BANDS, start=1)
        ]
    )
    summary = pd.DataFrame(
        [
            {
                "run_id": run["run_id"],
                "last_refresh_utc": run["completed_at_utc"],
                "posting_period_start": run["posted_from"],
                "posting_period_end": run["posted_to"],
                "total_active_opportunities": int(len(open_opportunities)),
                "new_this_month": int(open_opportunities["is_new_this_month"].sum()),
                "closing_within_14_days": int(
                    open_opportunities["is_closing_within_14_days"].sum()
                ),
                "distinct_agencies": int(open_opportunities["agency"].dropna().nunique()),
                "total_active_delta_30d": pd.NA,
                "new_this_month_delta_30d": pd.NA,
                "closing_14_days_delta_30d": pd.NA,
                "distinct_agencies_delta_30d": pd.NA,
                "comparison_available": False,
                "comparison_note": (
                    "Thirty-day deltas require a successful snapshot from "
                    "approximately 30 days earlier."
                ),
                "raw_keyword_matches": run["raw_keyword_matches"],
                "unique_records_before_active_filter": run["unique_records"],
                "unknown_active_status_records": run["unknown_active_status_records"],
                "keywords_completed": run["keywords_completed"],
                "keywords_failed": run["keywords_failed"],
                "keywords_truncated": len(run["truncated_keywords"]),
                "truncated_keyword_names": " | ".join(
                    run["truncated_keywords"]
                )
                or None,
                "run_status": run["status"],
            }
        ]
    )
    return {
        "agency": agency,
        "type": notice_type,
        "deadline": deadlines,
        "summary": summary,
    }


def publish_current(open_opportunities: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> None:
    # Publish the detail table last so the app never sees new detail with old summaries.
    save_frame_pair(tables["agency"], AGENCY_PARQUET, AGENCY_CSV)
    save_frame_pair(tables["type"], TYPE_PARQUET, TYPE_CSV)
    save_frame_pair(tables["deadline"], DEADLINE_PARQUET, DEADLINE_CSV)
    save_frame_pair(tables["summary"], SUMMARY_PARQUET, SUMMARY_CSV)
    save_frame_pair(open_opportunities, CURRENT_PARQUET, CURRENT_CSV)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect active SAM.gov opportunities for TellCoSOL."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Posting-date lookback window (default: 90 days).",
    )
    parser.add_argument("--keywords", nargs="+", default=list(DEFAULT_KEYWORDS))
    parser.add_argument(
        "--page-size",
        type=int,
        default=1000,
        help="SAM.gov results requested per page (default: 1000).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Maximum pages fetched for each keyword (default: 3).",
    )
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=45.0)
    parser.add_argument("--pause-seconds", type=float, default=0.5)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Publish even if one or more keyword searches fail.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Replace current dashboard files even when no active matches remain.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not 1 <= args.days <= 365:
        raise CollectorError("--days must be between 1 and 365.", fatal=True)
    if not 1 <= args.page_size <= 1000:
        raise CollectorError("--page-size must be between 1 and 1000.", fatal=True)
    if args.max_pages < 1:
        raise CollectorError("--max-pages must be at least 1.", fatal=True)
    if args.connect_timeout <= 0 or args.read_timeout <= 0:
        raise CollectorError("Timeouts must be greater than zero.", fatal=True)
    if args.pause_seconds < 0:
        raise CollectorError("--pause-seconds cannot be negative.", fatal=True)
    unique: dict[str, str] = {}
    for keyword in args.keywords:
        text = clean_text(keyword)
        if text:
            unique.setdefault(text.casefold(), text)
    if not unique:
        raise CollectorError("At least one keyword is required.", fatal=True)
    args.keywords = list(unique.values())


def main() -> int:
    ensure_directories()
    log_path = configure_logging()
    args = parse_args()
    try:
        validate_args(args)
    except CollectorError as exc:
        LOGGER.error("Configuration error: %s", exc)
        return 2

    load_dotenv(PROJECT_ROOT / ".env")
    api_key = (os.getenv("SAM_API_KEY") or "").strip()
    if not api_key:
        LOGGER.error(
            "SAM_API_KEY is missing. Add it as a Codespaces secret or to an "
            "uncommitted repository-root .env file."
        )
        return 2

    posted_to = date.today()
    posted_from = posted_to - timedelta(days=args.days)
    run_id = uuid.uuid4().hex
    started_at = utc_now().isoformat(timespec="seconds")
    all_records: list[dict[str, Any]] = []
    health_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    LOGGER.info("TellCoSOL SAM.gov collection started; run_id=%s", run_id)
    LOGGER.info(
        "Posting period %s to %s; %s keywords; maximum %s pages each",
        posted_from,
        posted_to,
        len(args.keywords),
        args.max_pages,
    )

    with build_session() as session:
        for number, keyword in enumerate(args.keywords, start=1):
            LOGGER.info("Keyword %s/%s: %s", number, len(args.keywords), keyword)
            try:
                records, health = collect_keyword(
                    session,
                    api_key=api_key,
                    run_id=run_id,
                    keyword=keyword,
                    posted_from=posted_from,
                    posted_to=posted_to,
                    page_size=args.page_size,
                    max_pages=args.max_pages,
                    force=args.force,
                    connect_timeout=args.connect_timeout,
                    read_timeout=args.read_timeout,
                    pause_seconds=args.pause_seconds,
                )
                all_records.extend(records)
                health_rows.append(health)
            except CollectorError as exc:
                failure = {
                    "keyword": keyword,
                    "status": "Failed",
                    "records_collected": 0,
                    "records_reported_by_api": 0,
                    "api_requests": 0,
                    "cache_hits": 0,
                    "truncated": False,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "checked_at_utc": utc_now().isoformat(timespec="seconds"),
                }
                failures.append(failure)
                health_rows.append(failure)
                LOGGER.error("Keyword %r failed: %s", keyword, exc)
                if exc.fatal:
                    break

    completed_at = utc_now().isoformat(timespec="seconds")
    raw_path = RAW_DIR / f"sam_matches_{run_id[:12]}.json"
    write_json_atomic(
        raw_path,
        {
            "run_id": run_id,
            "posted_from": posted_from,
            "posted_to": posted_to,
            "keywords": args.keywords,
            "records": all_records,
        },
    )

    normalized = normalize_and_deduplicate(all_records)
    explicitly_active = normalized.loc[normalized["active"].eq(True)].copy()
    open_opportunities = normalized.loc[
        normalized["is_open_for_response"].eq(True)
        & normalized["dashboard_included"].eq(True)
    ].copy()
    review_records = normalized.loc[
        normalized["review_status"].ne("Included")
    ].copy()
    unknown_active = int(normalized["active"].isna().sum()) if not normalized.empty else 0
    truncated_keywords = [
        row["keyword"] for row in health_rows if row.get("truncated")
    ]
    status = "Completed" if not failures and not truncated_keywords else "Partial"
    run = {
        "run_id": run_id,
        "status": status,
        "started_at_utc": started_at,
        "completed_at_utc": completed_at,
        "posted_from": posted_from.isoformat(),
        "posted_to": posted_to.isoformat(),
        "keywords_requested": len(args.keywords),
        "keywords_completed": len(health_rows) - len(failures),
        "keywords_failed": len(failures),
        "raw_keyword_matches": len(all_records),
        "unique_records": len(normalized),
        "active_records": len(explicitly_active),
        "open_records": len(open_opportunities),
        "expired_active_records": int((explicitly_active["days_left"] < 0).sum()) if not explicitly_active.empty else 0,
        "review_records": len(review_records),
        "inactive_records": int(normalized["active"].eq(False).sum())
        if not normalized.empty
        else 0,
        "unknown_active_status_records": unknown_active,
        "truncated_keywords": truncated_keywords,
        "raw_output": str(raw_path),
        "log_file": str(log_path),
    }

    source_health = pd.DataFrame(health_rows)
    save_frame_pair(normalized, ALL_PARQUET, ALL_CSV)
    save_frame_pair(review_records, REVIEW_PARQUET, REVIEW_CSV)
    save_frame_pair(source_health, SOURCE_HEALTH_PARQUET, SOURCE_HEALTH_CSV)
    pd.DataFrame(
        failures,
        columns=[
            "keyword",
            "status",
            "records_collected",
            "records_reported_by_api",
            "api_requests",
            "cache_hits",
            "truncated",
            "error_type",
            "error_message",
            "checked_at_utc",
        ],
    ).to_csv(
        FAILED_KEYWORDS_CSV, index=False, encoding="utf-8-sig"
    )
    save_frame_pair(
        normalized,
        CHECKPOINT_DIR / "sam_opportunities_partial.parquet",
        CHECKPOINT_DIR / "sam_opportunities_partial.csv",
    )
    write_json_atomic(RUN_STATUS_JSON, run)

    if (failures or truncated_keywords) and not args.allow_partial:
        LOGGER.error(
            "Run was partial because searches failed or reached --max-pages; "
            "current dashboard files were not replaced. Fix failures or rerun "
            "with a higher page cap. Use --allow-partial only intentionally."
        )
        return 1
    if open_opportunities.empty and not args.allow_empty:
        LOGGER.error(
            "No explicitly active matches were found; current dashboard files "
            "were not replaced. Inspect source_health.csv and the raw output."
        )
        return 1

    tables = create_dashboard_tables(open_opportunities, run)
    publish_current(open_opportunities, tables)
    snapshot_stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    write_frame_atomic(
        tables["summary"], HISTORY_DIR / f"dashboard_summary_{snapshot_stamp}.parquet"
    )

    LOGGER.info("Published %s open opportunities", len(open_opportunities))
    LOGGER.info("New this month: %s", int(open_opportunities["is_new_this_month"].sum()))
    LOGGER.info(
        "Closing within 14 days: %s",
        int(open_opportunities["is_closing_within_14_days"].sum()),
    )
    LOGGER.info("Distinct agencies: %s", open_opportunities["agency"].dropna().nunique())
    LOGGER.info("Dashboard detail file: %s", CURRENT_PARQUET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
