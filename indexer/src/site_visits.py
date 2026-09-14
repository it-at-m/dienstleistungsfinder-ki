import os
import re
from collections.abc import Iterable

from dotenv import load_dotenv
from httpx import Client, HTTPError
from qdrant_client import QdrantClient
from truststore import inject_into_ssl

from src.data_models import InfoSite, ServiceSite
from src.logtools import getLogger

# Inject into SSL for corporate proxy support
inject_into_ssl()

# Load environment variables
load_dotenv()

# Logger
logger = getLogger()

# Constants
ETRACKER_BASE_URL = os.getenv("ETRACKER_URL_BASE")
ETRACKER_TOKEN = os.getenv("ETRACKER_TOKEN")
API_IDS_URL = os.getenv("API_IDS_URL", "https://stadt.muenchen.de/service/rs/befi/services/list")
API_AUTH_USER = os.getenv("API_AUTH_USER")
API_AUTH_PASS = os.getenv("API_AUTH_PASS")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

# Regex Patterns
_SERVICE_RE = re.compile(r"/service/info/(?P<slug>[^/]+)/(?P<id>\d{4,})/(?:n0/)?(?:$|[?#])")
_INFO_SLUG_RE = re.compile(r"/infos/(?P<slug>[^/?#]+)")


def fetch_etracker_report() -> list:
    """Fetches the EAPage report from Etracker API."""
    if not ETRACKER_BASE_URL or not ETRACKER_TOKEN:
        raise ValueError("ETRACKER_URL_BASE and ETRACKER_TOKEN must be set in environment variables.")

    url = f"{ETRACKER_BASE_URL}/report/EAPage/data"
    token_name = "X-ET-Token"

    request_params = {
        "limit": 100000,
        "offset": 0,
        "attributes": "page_name,url",
        "startDate": "2025-07-01",
        "endDate": "2025-07-31",
        "figures": "unique_visits,unique_visitors,visits_cookie_rate,visitors_cookie_rate,visits_per_visitor_with_cookie,page_impressions,entry_pages,exit_page,bounces_per_visit,staytime_per_unique_visits_v2,staytime_bouncer_per_bounce",
        "sortColumn": "unique_visits",
        "sortOrder": 1,
        "extendedFilters": '[{"input":["stadt.muenchen.de"],"type":"contains","attributeId":"url","filter":"include","filterType":"extended","category":"attribute"}]',
        "isCompareMode": "false",
        "attributionModel": "lastAd",
        "displayType": "flat",
        "requestSource": "rest_request",
    }

    try:
        with Client(proxy=os.getenv("HTTPS_PROXY"), follow_redirects=True) as client:
            response = client.get(url, headers={token_name: ETRACKER_TOKEN}, params=request_params, timeout=60)
            response.raise_for_status()
            return response.json()
    except HTTPError as e:
        print(f"Etracker request failed: {e}")
        raise


def fetch_valid_api_ids() -> set[str]:
    """Fetches valid Service IDs from the internal API."""
    try:
        auth = (API_AUTH_USER, API_AUTH_PASS) if API_AUTH_USER and API_AUTH_PASS else None
        with Client(proxy=os.getenv("HTTPS_PROXY"), follow_redirects=True) as client:
            response = client.get(API_IDS_URL, auth=auth, timeout=30)
            response.raise_for_status()
            ids_dict = response.json()
            return {str(item["id"]) for item in ids_dict["ids"]}
    except HTTPError as e:
        print(f"API IDs request failed: {e}")
        raise


def process_etracker_data() -> tuple[dict[str, ServiceSite], dict[str, ServiceSite], dict[str, InfoSite]]:
    """
    Fetches and processes Etracker data.
    Returns:
        - services_sites_dict: Map of Service ID -> ServiceSite (filtered by valid API IDs)
        - services_slug_dict: Map of Service Slug -> ServiceSite (unfiltered)
        - info_sites_dict: Map of Info Slug -> InfoSite
    """
    print("Fetching Etracker report...")
    report = fetch_etracker_report()

    print("Fetching valid API IDs...")
    valid_api_ids = fetch_valid_api_ids()

    services_sites_dict: dict[str, ServiceSite] = {}
    services_slug_dict: dict[str, ServiceSite] = {}
    info_sites_dict: dict[str, InfoSite] = {}

    info_base_url = "stadt.muenchen.de/infos/"
    service_base_url = "stadt.muenchen.de/service/info/"

    # Iterate starting from index 1 as per notebook logic (assuming index 0 is header/metadata)
    for site_data in report[1:]:
        if not isinstance(site_data, dict) or "url" not in site_data:
            continue

        url = site_data.get("url", "")
        unique_visits = site_data.get("unique_visits", 0)
        page_name = site_data.get("page_name", "")

        if info_base_url in url:
            match = _INFO_SLUG_RE.search(url)
            if match:
                slug = match.group("slug")
                if slug in info_sites_dict:
                    if unique_visits > info_sites_dict[slug].unique_visits:
                        info_sites_dict[slug].unique_visits = unique_visits
                        info_sites_dict[slug].url = url
                else:
                    info_sites_dict[slug] = InfoSite(url=url, page_name=page_name, unique_visits=unique_visits)

        elif url.startswith(service_base_url):
            match = _SERVICE_RE.search(url)
            if match:
                s_id = match.group("id")
                s_slug = match.group("slug")

                # Update ID dict
                if s_id in services_sites_dict:
                    if unique_visits > services_sites_dict[s_id].unique_visits:
                        services_sites_dict[s_id].unique_visits = unique_visits
                        services_sites_dict[s_id].url = url
                else:
                    services_sites_dict[s_id] = ServiceSite(url=url, page_name=page_name, unique_visits=unique_visits)

                # Update Slug dict
                if s_slug in services_slug_dict:
                    if unique_visits > services_slug_dict[s_slug].unique_visits:
                        services_slug_dict[s_slug].unique_visits = unique_visits
                        services_slug_dict[s_slug].url = url
                else:
                    services_slug_dict[s_slug] = ServiceSite(url=url, page_name=page_name, unique_visits=unique_visits)

    # Filter services_sites_dict by valid API IDs
    filtered_services_sites = {k: v for k, v in services_sites_dict.items() if k in valid_api_ids}

    return filtered_services_sites, services_slug_dict, info_sites_dict


def get_urls_from_qdrant(collection_name: str) -> set[str]:
    """Fetches all source URLs from a Qdrant collection."""
    if not QDRANT_URL:
        print("Qdrant credentials missing.")
        return set()

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, port=None)
    urls = set()
    offset = None

    print(f"Fetching URLs from Qdrant collection '{collection_name}'...")
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload
            if payload and "metadata" in payload and "source" in payload["metadata"]:
                urls.add(payload["metadata"]["source"])

        if offset is None:
            break
    return urls


def match_qdrant_urls(
    service_urls: set[str],
    info_urls: set[str],
    services_sites_dict: dict[str, ServiceSite],
    services_slug_dict: dict[str, ServiceSite],
    info_sites_dict: dict[str, InfoSite],
) -> tuple[dict[str, int], dict[str, int]]:
    """Matches Qdrant URLs with Etracker visit data."""
    matched_service_visits: dict[str, int] = {}
    matched_info_visits: dict[str, int] = {}

    # Process Service URLs
    for qdrant_url in service_urls:
        match = _SERVICE_RE.search(qdrant_url)
        if match:
            service_id = match.group("id")
            service_slug = match.group("slug")

            if service_id in services_sites_dict:
                matched_service_visits[qdrant_url] = int(services_sites_dict[service_id].unique_visits)
            elif service_slug in services_slug_dict:
                matched_service_visits[qdrant_url] = int(services_slug_dict[service_slug].unique_visits)
            else:
                matched_service_visits[qdrant_url] = 0

    # Process Info URLs
    for qdrant_url in info_urls:
        match = _INFO_SLUG_RE.search(qdrant_url)
        if match:
            info_slug = match.group("slug")
            if info_slug in info_sites_dict:
                matched_info_visits[qdrant_url] = int(info_sites_dict[info_slug].unique_visits)
            else:
                matched_info_visits[qdrant_url] = 0

    return matched_service_visits, matched_info_visits


def _chunked(iterable: list, size: int) -> Iterable[list]:
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def add_site_visits_to_qdrant_collection(
    *,
    collection_name: str,
    matched_visits_by_url: dict[str, int],
    start_date: str,
    end_date: str,
    batch_size: int = 256,
) -> None:
    """
    Updates points in `collection_name` by adding matched site visits to payload metadata.

    Writes:
        payload["metadata"]["site_stats"] = {
            "unique_visits": <int>,
            "source": "etracker",
            "startDate": <str>,
            "endDate": <str>
        }

    Matching key:
        payload["metadata"]["source"] (URL string) -> matched_visits_by_url[url]
    """
    if not QDRANT_URL:
        raise ValueError("QDRANT_URL must be set.")
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, port=None)

    print(f"Updating Qdrant collection '{collection_name}' with site visits...")
    offset = None
    total_points = 0
    total_updated = 0

    pending: list[tuple[int | str, dict]] = []

    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        for point in points:
            total_points += 1
            payload = point.payload or {}
            md = payload.get("metadata") or {}
            src = md.get("source")

            if not isinstance(src, str) or not src:
                logger.warning(
                    f"Point ID {point.id} in collection '{collection_name}' has no valid source URL; skipping."
                )
                continue

            visits = int(matched_visits_by_url.get(src, 0))

            # Preserve existing metadata; only add/overwrite site_stats subtree
            new_md = dict(md)
            new_md["site_stats"] = {
                "unique_visits": visits,
                "source": "etracker",
                "startDate": start_date,
                "endDate": end_date,
            }

            pending.append((point.id, {"metadata": new_md}))  # type: ignore

        # Flush pending updates in batches
        if pending:
            for batch in _chunked(pending, batch_size):
                # set_payload modifies payload of the specified points. However set_payload sets same payload for all given points.
                # Therefore: do per-point set_payload calls (still batched by loop for control).
                for pid, payload_patch in batch:
                    client.set_payload(
                        collection_name=collection_name,
                        payload=payload_patch,
                        points=[pid],
                    )
                    total_updated += 1
            pending.clear()

        if offset is None:
            break

    print(
        f"Done. Scanned {total_points} points in '{collection_name}', updated {total_updated} points with site_visits."
    )


def add_site_visits_main() -> None:
    """Enrich service and information collections with configured eTracker visit counts."""
    if not ETRACKER_BASE_URL or not ETRACKER_TOKEN:
        logger.info("Etracker enrichment skipped because ETRACKER_URL_BASE or ETRACKER_TOKEN is not configured.")
        return

    try:
        s_ids, s_slugs, infos = process_etracker_data()
        print(f"Processed {len(s_ids)} valid service IDs.")
        print(f"Processed {len(s_slugs)} service slugs.")
        print(f"Processed {len(infos)} info sites.")

        service_urls_qdrant = get_urls_from_qdrant("service")
        info_urls_qdrant = get_urls_from_qdrant("info")

        print(f"Found {len(service_urls_qdrant)} URLs in 'service' collection.")
        print(f"Found {len(info_urls_qdrant)} URLs in 'info' collection.")

        matched_services, matched_infos = match_qdrant_urls(
            service_urls_qdrant, info_urls_qdrant, s_ids, s_slugs, infos
        )

        print(f"Matched visits for {len(matched_services)} service URLs.")
        print(f"Matched visits for {len(matched_infos)} info URLs.")

        print("adding site visits to qdrant collections...")
        add_site_visits_to_qdrant_collection(
            collection_name="service",
            matched_visits_by_url=matched_services,
            start_date="N/A",
            end_date="N/A",
        )
        add_site_visits_to_qdrant_collection(
            collection_name="info",
            matched_visits_by_url=matched_infos,
            start_date="N/A",
            end_date="N/A",
        )

    except Exception as e:
        print(f"An error occurred: {e}")
