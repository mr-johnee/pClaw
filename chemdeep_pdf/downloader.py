"""Download open-access PDFs through legal machine-readable routes.

Strategy order:

1. Europe PMC direct PDF endpoints for records marked open access there.
2. PMC's official OA Web Service and OA package tarballs for PMC OA-subset
   records. When a package is available, extract the primary article PDF from
   the archive instead of scraping the PMC article webpage.
3. Unpaywall-reported OA PDF locations and non-PMC landing pages.

PMC article webpages are intentionally not scraped for PDF links because that
browser-style path is not the compliant bulk-download route documented by PMC.
"""

from __future__ import annotations

import io
import logging
import re
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlparse

import httpx

from .settings import settings

logger = logging.getLogger("chemdeep-pdf-downloader")

USER_AGENT = "covalent-probe-discovery/1.0 (OA PDF downloader)"
EUROPE_PMC_SEARCH_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPE_PMC_PDF_API = "https://europepmc.org/api/getPdf"
PMC_OA_SERVICE_API = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
PDF_LINK_PATTERNS = (
    r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']',
    r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
    r'href=["\']([^"\']*/pdf[^"\']*)["\']',
)


def _sanitize_doi(doi: str) -> str:
    if not doi:
        return ""

    cleaned = doi.strip()
    for prefix in (
        "suppl/",
        "abs/",
        "full/",
        "pdf/",
        "pdfplus/",
        "epdf/",
        "doi/",
        "article/",
        "10.1021/suppl/",
        "https://doi.org/",
        "http://doi.org/",
    ):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix) :]

    for pattern in (r"\.s\d+$", r"\.suppl\d*$", r"_ESI$", r"\.SI$"):
        updated = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        if updated != cleaned:
            cleaned = updated
            break

    if not cleaned.startswith("10."):
        match = re.search(r"(10\.\d{4,}/[^\s]+)", cleaned)
        if match:
            cleaned = match.group(1)
    return cleaned


def build_article_url(doi: str = "", article_url: str = "") -> str | None:
    explicit_url = (article_url or "").strip()
    if explicit_url:
        return explicit_url

    sanitized = _sanitize_doi(doi)
    if not sanitized:
        return None
    return f"https://doi.org/{sanitized}"


def _article_dir_for(
    sanitized_doi: str, output_dir: str | Path | None
) -> Path:
    article_id = re.sub(r'[\\/*?:"<>|]', "_", sanitized_doi.lower())
    base = Path(output_dir) if output_dir else settings.root_dir / "articles"
    path = base / article_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_unpaywall_api_url(doi: str) -> str:
    email = settings.unpaywall_email.strip()
    if not email:
        raise ValueError(
            "CHEM_PDF_UNPAYWALL_EMAIL or UNPAYWALL_EMAIL must be set before "
            "using the Unpaywall fallback."
        )
    return (
        f"{settings.unpaywall_api_base.rstrip('/')}/{quote(doi, safe='')}"
        f"?email={quote(email, safe='@._+-')}"
    )


def _build_europe_pmc_search_url(doi: str) -> str:
    query = urlencode(
        {
            "query": f'DOI:"{doi}"',
            "format": "json",
            "pageSize": 1,
            "resultType": "core",
        }
    )
    return f"{EUROPE_PMC_SEARCH_API}?{query}"


def _client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=settings.request_timeout_seconds,
        trust_env=False,
        headers={"User-Agent": USER_AGENT},
    )


def _fetch_unpaywall_record(client: httpx.Client, doi: str) -> dict[str, Any]:
    response = client.get(_build_unpaywall_api_url(doi))
    if response.status_code == 404:
        raise ValueError("DOI not found in Unpaywall")
    response.raise_for_status()
    return response.json()


def _fetch_europe_pmc_record(
    client: httpx.Client, doi: str
) -> dict[str, Any] | None:
    response = client.get(_build_europe_pmc_search_url(doi))
    response.raise_for_status()
    payload = response.json()
    results = ((payload.get("resultList") or {}).get("result")) or []
    if not results:
        return None
    result = results[0]
    return result if isinstance(result, dict) else None


def _fetch_pmc_oa_record(
    client: httpx.Client, pmcid: str
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    response = client.get(PMC_OA_SERVICE_API, params={"id": pmcid})
    response.raise_for_status()

    attempt: dict[str, Any] = {
        "strategy": "pmc_oa_service",
        "pmcid": pmcid,
        "service_url": str(response.url),
    }

    root = ET.fromstring(response.text)
    error = root.find("error")
    if error is not None:
        attempt["status"] = "failed"
        attempt["error_code"] = error.attrib.get("code") or ""
        attempt["error"] = (error.text or "").strip() or "PMC OA service error"
        return None, attempt

    record = root.find(".//record")
    if record is None:
        attempt["status"] = "failed"
        attempt["error"] = "PMC OA service returned no record."
        return None, attempt

    links = [
        {
            "format": link.attrib.get("format") or "",
            "href": link.attrib.get("href") or "",
            "updated": link.attrib.get("updated") or "",
        }
        for link in record.findall("link")
    ]
    attempt["status"] = "ok"
    attempt["license"] = record.attrib.get("license") or ""
    attempt["links"] = links
    return {
        "id": record.attrib.get("id") or pmcid,
        "license": record.attrib.get("license") or "",
        "links": links,
    }, attempt


def _location_key(location: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(location.get("url_for_pdf") or ""),
        str(location.get("url_for_landing_page") or ""),
        str(location.get("url") or ""),
    )


def _iter_oa_locations(record: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for key in ("best_oa_location", "first_oa_location"):
        location = record.get(key)
        if isinstance(location, dict):
            dedupe_key = _location_key(location)
            if dedupe_key not in seen:
                seen.add(dedupe_key)
                candidates.append(location)
    for location in record.get("oa_locations") or []:
        if not isinstance(location, dict):
            continue
        dedupe_key = _location_key(location)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidates.append(location)
    return candidates


def _normalize_pmcid(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    match = re.search(r"(PMC\d+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return text.upper()


def _is_pmc_host_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower()
    return "pmc.ncbi.nlm.nih.gov" in netloc or (
        "ncbi.nlm.nih.gov" in netloc and "/pmc/" in path
    )


def _response_looks_like_pdf(response: httpx.Response) -> bool:
    content_type = (response.headers.get("content-type") or "").lower()
    return "application/pdf" in content_type or response.url.path.lower().endswith(".pdf")


def _write_pdf_if_valid(pdf_path: Path, content: bytes) -> str | None:
    if not content.startswith(b"%PDF-"):
        return None
    pdf_path.write_bytes(content)
    return str(pdf_path)


def _extract_pdf_urls_from_html(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for pattern in PDF_LINK_PATTERNS:
        for match in re.finditer(pattern, html, flags=re.IGNORECASE):
            candidate = match.group(1).strip()
            if not candidate:
                continue
            absolute = urljoin(base_url, candidate)
            if absolute in seen:
                continue
            seen.add(absolute)
            urls.append(absolute)
    return urls


def _download_pdf_url(
    client: httpx.Client, pdf_url: str, pdf_path: Path
) -> tuple[str | None, str]:
    response = client.get(pdf_url)
    if response.status_code >= 400:
        return None, f"HTTP {response.status_code}"
    saved = _write_pdf_if_valid(pdf_path, response.content)
    if saved:
        return saved, str(response.url)
    return None, f"Non-PDF or invalid PDF response from {response.url}"


def _try_europe_pmc(
    client: httpx.Client,
    doi: str,
    pdf_path: Path,
) -> tuple[str | None, dict[str, Any], dict[str, Any] | None]:
    attempt: dict[str, Any] = {
        "strategy": "europe_pmc",
        "doi": doi,
    }
    try:
        record = _fetch_europe_pmc_record(client, doi)
    except Exception as exc:  # pragma: no cover - network variability
        attempt["status"] = "failed"
        attempt["error"] = f"Europe PMC lookup failed: {exc}"
        return None, attempt, None

    if not record:
        attempt["status"] = "failed"
        attempt["error"] = "Europe PMC did not return a record for this DOI."
        return None, attempt, None

    pmcid = _normalize_pmcid(str(record.get("pmcid") or ""))
    attempt["pmid"] = record.get("pmid") or ""
    attempt["pmcid"] = pmcid
    attempt["is_open_access"] = str(record.get("isOpenAccess") or "")

    full_text_urls = ((record.get("fullTextUrlList") or {}).get("fullTextUrl")) or []
    pdf_urls: list[str] = []
    seen: set[str] = set()
    for item in full_text_urls:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        if (
            str(item.get("documentStyle") or "").lower() == "pdf"
            and str(item.get("availabilityCode") or "").upper() == "OA"
        ):
            seen.add(url)
            pdf_urls.append(url)

    if pmcid:
        epmc_pdf = f"{EUROPE_PMC_PDF_API}?pmcid={quote(pmcid, safe='')}"
        if epmc_pdf not in seen:
            pdf_urls.insert(0, epmc_pdf)

    attempt["candidate_pdf_urls"] = pdf_urls[:10]
    if str(record.get("isOpenAccess") or "").upper() != "Y":
        attempt["status"] = "failed"
        attempt["error"] = "Europe PMC record is not marked open access."
        return None, attempt, record

    for pdf_url in pdf_urls:
        saved, detail = _download_pdf_url(client, pdf_url, pdf_path)
        if saved:
            attempt["status"] = "ok"
            attempt["downloaded_from"] = detail
            return saved, attempt, record

    attempt["status"] = "failed"
    attempt["error"] = "Europe PMC did not yield a valid downloadable PDF."
    return None, attempt, record


def _candidate_http_urls_for_ftp_href(href: str) -> list[str]:
    if not href.startswith("ftp://ftp.ncbi.nlm.nih.gov/"):
        return []

    path = href[len("ftp://ftp.ncbi.nlm.nih.gov") :]
    candidates = [f"https://ftp.ncbi.nlm.nih.gov{path}"]
    if "/pub/pmc/oa_package/" in path:
        deprecated = path.replace(
            "/pub/pmc/oa_package/",
            "/pub/pmc/deprecated/oa_package/",
            1,
        )
        if deprecated != path:
            candidates.append(f"https://ftp.ncbi.nlm.nih.gov{deprecated}")
    return candidates


def _primary_pdf_sort_key(name: str) -> tuple[int, int, str]:
    lowered = name.lower()
    noisy_tokens = ("supp", "support", "appendix", "si", "supplement")
    penalty = 1 if any(token in lowered for token in noisy_tokens) else 0
    return (penalty, lowered.count("/"), lowered)


def _extract_pdf_from_tgz_bytes(
    archive_bytes: bytes,
    pdf_path: Path,
) -> tuple[str | None, str]:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.isfile() and member.name.lower().endswith(".pdf")
            ]
            if not members:
                return None, "OA package did not contain a PDF."

            members.sort(key=lambda member: _primary_pdf_sort_key(member.name))
            chosen = members[0]
            fileobj = archive.extractfile(chosen)
            if fileobj is None:
                return None, f"Could not extract {chosen.name} from OA package."
            content = fileobj.read()
            saved = _write_pdf_if_valid(pdf_path, content)
            if saved:
                return saved, chosen.name
            return None, f"Extracted file {chosen.name} was not a valid PDF."
    except tarfile.TarError as exc:
        return None, f"OA package was unreadable: {exc}"


def _try_pmc_oa_service(
    client: httpx.Client,
    pmcid: str,
    pdf_path: Path,
) -> tuple[str | None, dict[str, Any]]:
    record, attempt = _fetch_pmc_oa_record(client, pmcid)
    if not record:
        return None, attempt

    link_candidates = record.get("links") or []
    pdf_http_candidates: list[str] = []
    tgz_http_candidates: list[str] = []

    for link in link_candidates:
        href = str(link.get("href") or "").strip()
        fmt = str(link.get("format") or "").lower()
        if not href:
            continue
        if href.startswith("http://") or href.startswith("https://"):
            target_urls = [href]
        else:
            target_urls = _candidate_http_urls_for_ftp_href(href)

        if fmt == "pdf":
            pdf_http_candidates.extend(target_urls)
        elif fmt == "tgz":
            tgz_http_candidates.extend(target_urls)

    deduped_pdf_urls: list[str] = []
    seen_urls: set[str] = set()
    for url in pdf_http_candidates:
        if url not in seen_urls:
            seen_urls.add(url)
            deduped_pdf_urls.append(url)

    deduped_tgz_urls: list[str] = []
    for url in tgz_http_candidates:
        if url not in seen_urls:
            seen_urls.add(url)
            deduped_tgz_urls.append(url)

    attempt["candidate_pdf_urls"] = deduped_pdf_urls[:10]
    attempt["candidate_tgz_urls"] = deduped_tgz_urls[:10]

    for pdf_url in deduped_pdf_urls:
        saved, detail = _download_pdf_url(client, pdf_url, pdf_path)
        if saved:
            attempt["status"] = "ok"
            attempt["downloaded_from"] = detail
            return saved, attempt

    for tgz_url in deduped_tgz_urls:
        response = client.get(tgz_url)
        if response.status_code >= 400:
            continue
        saved, archive_member = _extract_pdf_from_tgz_bytes(response.content, pdf_path)
        if saved:
            attempt["status"] = "ok"
            attempt["downloaded_from"] = tgz_url
            attempt["archive_member"] = archive_member
            return saved, attempt

    attempt["status"] = "failed"
    attempt["error"] = "PMC OA service record existed, but no valid PDF could be extracted."
    return None, attempt


def _try_location(
    client: httpx.Client, location: dict[str, Any], pdf_path: Path
) -> tuple[str | None, dict[str, Any]]:
    attempt: dict[str, Any] = {
        "strategy": "unpaywall_location",
        "host_type": location.get("host_type") or "",
        "evidence": location.get("evidence") or "",
        "license": location.get("license") or "",
        "version": location.get("version") or "",
        "url": location.get("url") or "",
        "url_for_pdf": location.get("url_for_pdf") or "",
        "url_for_landing_page": location.get("url_for_landing_page") or "",
    }

    pdf_url = str(location.get("url_for_pdf") or "").strip()
    landing_url = (
        str(location.get("url_for_landing_page") or "").strip()
        or str(location.get("url") or "").strip()
    )

    if _is_pmc_host_url(pdf_url) or _is_pmc_host_url(landing_url):
        attempt["status"] = "skipped_policy"
        attempt["error"] = (
            "PMC webpage URLs are not downloaded through Unpaywall fallback. "
            "Use Europe PMC or the PMC OA service instead."
        )
        return None, attempt

    if pdf_url:
        saved, detail = _download_pdf_url(client, pdf_url, pdf_path)
        if saved:
            attempt["downloaded_from"] = detail
            attempt["status"] = "ok"
            return saved, attempt
        attempt["pdf_attempt_error"] = detail

    if not landing_url:
        attempt["status"] = "failed"
        attempt["error"] = "No OA PDF URL or landing page in location."
        return None, attempt

    response = client.get(landing_url)
    if response.status_code >= 400:
        attempt["status"] = "failed"
        attempt["error"] = f"Landing page returned HTTP {response.status_code}"
        return None, attempt

    if _response_looks_like_pdf(response):
        saved = _write_pdf_if_valid(pdf_path, response.content)
        if saved:
            attempt["downloaded_from"] = str(response.url)
            attempt["status"] = "ok"
            return saved, attempt

    html = response.text
    discovered_pdf_urls = _extract_pdf_urls_from_html(html, str(response.url))
    attempt["discovered_pdf_urls"] = discovered_pdf_urls[:10]
    allowed_pdf_urls = [
        url
        for url in discovered_pdf_urls
        if not _is_pmc_host_url(url)
    ]
    skipped_pmc_urls = [
        url
        for url in discovered_pdf_urls
        if _is_pmc_host_url(url)
    ]
    if skipped_pmc_urls:
        attempt["skipped_policy_urls"] = skipped_pmc_urls[:10]

    for discovered_pdf_url in allowed_pdf_urls:
        saved, detail = _download_pdf_url(client, discovered_pdf_url, pdf_path)
        if saved:
            attempt["downloaded_from"] = detail
            attempt["status"] = "ok"
            return saved, attempt

    attempt["status"] = "failed"
    attempt["error"] = "OA landing page did not expose a downloadable PDF."
    return None, attempt


def download_pdf_for_paper(
    doi: str,
    title: str = "",
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Download an open-access PDF for a paper identified by DOI."""

    sanitized_doi = _sanitize_doi(doi)
    if not sanitized_doi:
        return {
            "success": False,
            "doi": doi,
            "title": title,
            "error": "Missing a valid DOI.",
        }

    article_url = build_article_url(sanitized_doi)
    article_dir = _article_dir_for(sanitized_doi, output_dir)
    pdf_path = article_dir / "paper.pdf"

    try:
        with _client() as client:
            attempts: list[dict[str, Any]] = []
            europe_record: dict[str, Any] | None = None

            saved, europe_attempt, europe_record = _try_europe_pmc(
                client, sanitized_doi, pdf_path
            )
            attempts.append(europe_attempt)
            if saved:
                return {
                    "success": True,
                    "doi": sanitized_doi,
                    "title": title or str(europe_record.get("title") or ""),
                    "article_url": article_url,
                    "pdf_path": saved,
                    "content_source": "europe_pmc_pdf",
                    "download_strategy": "europe_pmc",
                    "pmcid": _normalize_pmcid(str(europe_record.get("pmcid") or "")),
                    "pmid": str(europe_record.get("pmid") or ""),
                    "download_attempt": europe_attempt,
                    "attempted_strategies": attempts,
                }

            pmcid = _normalize_pmcid(
                str((europe_record or {}).get("pmcid") or "")
            )
            if pmcid:
                saved, pmc_attempt = _try_pmc_oa_service(client, pmcid, pdf_path)
                attempts.append(pmc_attempt)
                if saved:
                    return {
                        "success": True,
                        "doi": sanitized_doi,
                        "title": title or str((europe_record or {}).get("title") or ""),
                        "article_url": article_url,
                        "pdf_path": saved,
                        "content_source": "pmc_oa_package_pdf",
                        "download_strategy": "pmc_oa_service",
                        "pmcid": pmcid,
                        "pmid": str((europe_record or {}).get("pmid") or ""),
                        "download_attempt": pmc_attempt,
                        "attempted_strategies": attempts,
                    }

            record = _fetch_unpaywall_record(client, sanitized_doi)
            oa_locations = _iter_oa_locations(record)

            if not record.get("is_oa") or not oa_locations:
                return {
                    "success": False,
                    "doi": sanitized_doi,
                    "title": title or record.get("title") or "",
                    "article_url": article_url,
                    "oa_status": record.get("oa_status") or "",
                    "is_oa": bool(record.get("is_oa")),
                    "pmcid": pmcid,
                    "attempted_strategies": attempts,
                    "error": "No compliant OA PDF route was found for this DOI.",
                }

            location_attempts: list[dict[str, Any]] = []
            for location in oa_locations:
                saved, attempt = _try_location(client, location, pdf_path)
                location_attempts.append(attempt)
                attempts.append(attempt)
                if saved:
                    return {
                        "success": True,
                        "doi": sanitized_doi,
                        "title": title or record.get("title") or "",
                        "article_url": article_url,
                        "pdf_path": saved,
                        "content_source": "unpaywall_open_access_pdf",
                        "download_strategy": "unpaywall",
                        "is_oa": bool(record.get("is_oa")),
                        "oa_status": record.get("oa_status") or "",
                        "journal_name": record.get("journal_name") or "",
                        "publisher": record.get("publisher") or "",
                        "best_oa_location": record.get("best_oa_location") or {},
                        "pmcid": pmcid,
                        "download_attempt": attempt,
                        "attempted_strategies": attempts,
                    }

            return {
                "success": False,
                "doi": sanitized_doi,
                "title": title or record.get("title") or "",
                "article_url": article_url,
                "is_oa": bool(record.get("is_oa")),
                "oa_status": record.get("oa_status") or "",
                "journal_name": record.get("journal_name") or "",
                "publisher": record.get("publisher") or "",
                "best_oa_location": record.get("best_oa_location") or {},
                "pmcid": pmcid,
                "attempted_locations": location_attempts,
                "attempted_strategies": attempts,
                "error": (
                    "Open-access signals were found, but none of the compliant "
                    "download strategies yielded a valid PDF."
                ),
            }
    except httpx.HTTPStatusError as exc:
        return {
            "success": False,
            "doi": sanitized_doi,
            "title": title,
            "article_url": article_url,
            "error": f"Upstream service returned HTTP {exc.response.status_code}",
        }
    except ValueError as exc:
        return {
            "success": False,
            "doi": sanitized_doi,
            "title": title,
            "article_url": article_url,
            "error": str(exc),
        }
    except Exception as exc:  # pragma: no cover - network variability
        logger.warning("OA PDF download failed for %s: %s", sanitized_doi, exc)
        return {
            "success": False,
            "doi": sanitized_doi,
            "title": title,
            "article_url": article_url,
            "error": str(exc),
        }
