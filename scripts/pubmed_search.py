#!/usr/bin/env python3
"""Run deterministic PubMed keyword searches and emit normalized JSON.

Filters relevant to the covalent-probe-discovery workflow:

* Review exclusion (on by default). Review and systematic-review articles are
  removed via PubMed's ``Publication Type`` filter so primary chemistry
  literature dominates the shortlist.
* Optional publication-year window (``--min-year`` / ``--max-year``) applied
  via PubMed's ``[PDAT]`` field. Both ends are inclusive. Strongly recommended
  for reproducible academic surveys: pick a hard date window so the search is
  re-runnable.
* Optional journal whitelist (``--journal``, repeatable) applied via PubMed's
  ``[TA]`` (journal abbreviation) field. Off by default — a too-narrow
  whitelist can hide good chemistry in less obvious venues.
* Page-count parsing. When PubMed exposes a usable pagination range, the page
  count is included in the output so downstream steps can skip excessively
  long articles without waiting for a PDF download.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable


ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
USER_AGENT = "covalent-probe-discovery/1.0 (PubMed E-utilities client)"

REVIEW_EXCLUSION_CLAUSE = (
    "NOT (review[pt] OR systematic review[pt] OR meta-analysis[pt])"
)


@dataclass
class SearchHit:
    pmid: str
    matched_queries: list[str]
    first_query_index: int


def fetch_json(url: str, params: dict[str, str]) -> dict:
    request_url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        request_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_xml(url: str, params: dict[str, str]) -> ET.Element:
    request_url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        request_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/xml,text/xml",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return ET.fromstring(response.read())


def chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def flatten_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def parse_pubdate(article: ET.Element) -> str:
    for path in (
        "./MedlineCitation/Article/ArticleDate",
        "./MedlineCitation/Article/Journal/JournalIssue/PubDate",
        "./PubmedData/History/PubMedPubDate[@PubStatus='pubmed']",
    ):
        node = article.find(path)
        if node is None:
            continue
        year = flatten_text(node.find("Year"))
        month = flatten_text(node.find("Month"))
        day = flatten_text(node.find("Day"))
        medline_date = flatten_text(node.find("MedlineDate"))
        if year:
            parts = [year]
            if month:
                parts.append(month)
            if day:
                parts.append(day)
            return "-".join(parts)
        if medline_date:
            return medline_date
    return ""


def parse_abstract(article: ET.Element) -> str:
    abstract = article.find("./MedlineCitation/Article/Abstract")
    if abstract is None:
        return ""
    parts: list[str] = []
    for node in abstract.findall("AbstractText"):
        label = (node.attrib.get("Label") or node.attrib.get("NlmCategory") or "").strip()
        text = flatten_text(node)
        if not text:
            continue
        parts.append(f"{label}: {text}" if label else text)
    return "\n\n".join(parts).strip()


_PAGE_RANGE_RE = re.compile(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$")


def parse_page_count(article: ET.Element) -> int | None:
    """Return the number of pages for the article if PubMed reports a range.

    PubMed's ``MedlinePgn`` is free text. Typical forms:

    * ``"12345-12378"`` — simple range, page count = 34.
    * ``"e12345"`` or ``"1e02"`` — online-only locators, no length information.
    * ``"S1-S8"`` — supplement pages.

    When the value cannot be parsed as a clean numeric range, ``None`` is
    returned. Callers should treat missing page counts as unknown, not zero.
    """
    node = article.find("./MedlineCitation/Article/Pagination/MedlinePgn")
    if node is None:
        return None
    raw = flatten_text(node)
    if not raw:
        return None
    match = _PAGE_RANGE_RE.match(raw)
    if not match:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    if end < start:
        return None
    return end - start + 1


def parse_publication_types(article: ET.Element) -> list[str]:
    types: list[str] = []
    for node in article.findall(
        "./MedlineCitation/Article/PublicationTypeList/PublicationType"
    ):
        text = flatten_text(node)
        if text and text not in types:
            types.append(text)
    return types


def parse_article_ids(article: ET.Element) -> tuple[str, str]:
    doi = ""
    pmcid = ""
    for article_id in article.findall("./PubmedData/ArticleIdList/ArticleId"):
        id_type = (article_id.attrib.get("IdType") or "").lower()
        value = flatten_text(article_id)
        if id_type == "doi" and value and not doi:
            doi = value
        if id_type == "pmc" and value and not pmcid:
            pmcid = value if value.startswith("PMC") else f"PMC{value}"
    return doi, pmcid


def parse_articles(root: ET.Element, hit_map: dict[str, SearchHit]) -> list[dict]:
    articles: list[dict] = []
    for article in root.findall("./PubmedArticle"):
        pmid = flatten_text(article.find("./MedlineCitation/PMID"))
        if not pmid or pmid not in hit_map:
            continue
        title = flatten_text(article.find("./MedlineCitation/Article/ArticleTitle"))
        journal = flatten_text(article.find("./MedlineCitation/Article/Journal/ISOAbbreviation"))
        if not journal:
            journal = flatten_text(article.find("./MedlineCitation/Article/Journal/Title"))
        doi, pmcid = parse_article_ids(article)
        authors = []
        for author in article.findall("./MedlineCitation/Article/AuthorList/Author"):
            collective = flatten_text(author.find("CollectiveName"))
            if collective:
                authors.append(collective)
                continue
            last_name = flatten_text(author.find("LastName"))
            initials = flatten_text(author.find("Initials"))
            if last_name:
                authors.append(f"{last_name} {initials}".strip())
        articles.append(
            {
                "pmid": pmid,
                "title": title,
                "abstract": parse_abstract(article),
                "journal": journal,
                "pubdate": parse_pubdate(article),
                "doi": doi,
                "pmcid": pmcid,
                "authors": authors,
                "publication_types": parse_publication_types(article),
                "page_count": parse_page_count(article),
                "matched_queries": hit_map[pmid].matched_queries,
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            }
        )
    articles.sort(key=lambda item: hit_map[item["pmid"]].first_query_index)
    return articles


def load_queries(args: argparse.Namespace) -> list[str]:
    queries: list[str] = []
    if args.query:
        queries.extend(args.query)
    if args.query_file:
        with open(args.query_file, "r", encoding="utf-8") as handle:
            queries.extend(line.strip() for line in handle if line.strip())
    if not queries and not sys.stdin.isatty():
        queries.extend(line.strip() for line in sys.stdin if line.strip())
    ordered = list(OrderedDict.fromkeys(query for query in queries if query.strip()))
    if not ordered:
        raise SystemExit("No queries supplied. Use --query, --query-file, or stdin.")
    return ordered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", help="PubMed query phrase. Repeatable.")
    parser.add_argument("--query-file", help="File containing one query per line.")
    parser.add_argument("--retmax", type=int, default=20, help="Max results per query.")
    parser.add_argument(
        "--sort",
        default="date",
        choices=("date", "relevance", "pub_date"),
        help="PubMed sort mode.",
    )
    parser.add_argument(
        "--tool",
        default="covalent-probe-discovery",
        help="NCBI tool name.",
    )
    parser.add_argument("--email", default="", help="Contact email for NCBI requests.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument(
        "--include-reviews",
        action="store_true",
        help="Do not filter out review / systematic-review / meta-analysis articles.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help=(
            "Drop articles whose parseable page count exceeds this value. "
            "Articles without a parseable page range pass through untouched. "
            "Set to 0 to disable the filter."
        ),
    )
    parser.add_argument(
        "--min-year",
        type=int,
        help=(
            "Lower bound (inclusive) on publication year, applied via PubMed "
            "[PDAT]. Recommended for reproducible academic surveys."
        ),
    )
    parser.add_argument(
        "--max-year",
        type=int,
        help=(
            "Upper bound (inclusive) on publication year, applied via PubMed "
            "[PDAT]. Recommended for reproducible academic surveys."
        ),
    )
    parser.add_argument(
        "--journal",
        action="append",
        default=[],
        metavar="ABBR",
        help=(
            "Restrict results to one or more journals by ISO abbreviation "
            "(applied via PubMed [TA]). Repeatable. Off by default. "
            "Example: --journal 'J Am Chem Soc' --journal 'Angew Chem Int Ed Engl'."
        ),
    )
    return parser


def apply_review_filter(query: str) -> str:
    lowered = query.lower()
    if "review[pt]" in lowered or "publication type" in lowered:
        return query
    return f"({query}) {REVIEW_EXCLUSION_CLAUSE}"


def build_year_clause(min_year: int | None, max_year: int | None) -> str:
    """Build a PubMed [PDAT] range clause. Both ends inclusive.

    Empty string if neither bound is provided. PubMed accepts open-ended
    ranges by substituting ``"3000"`` for an unbounded upper end and
    ``"1900"`` for an unbounded lower end, but to keep the emitted query
    auditable we require an explicit value on each side that was actually
    requested.
    """
    if min_year is None and max_year is None:
        return ""
    low = str(min_year) if min_year is not None else "1900"
    high = str(max_year) if max_year is not None else "3000"
    return f'AND ("{low}"[PDAT] : "{high}"[PDAT])'


def build_journal_clause(journals: list[str]) -> str:
    """Build a PubMed ``([TA] OR [TA] ...)`` clause from a journal whitelist.

    Empty string if no journals were requested.
    """
    cleaned = [j.strip() for j in journals if j and j.strip()]
    if not cleaned:
        return ""
    terms = " OR ".join(f'"{j}"[TA]' for j in cleaned)
    return f"AND ({terms})"


def filter_articles_by_page_count(
    articles: list[dict], max_pages: int
) -> tuple[list[dict], list[dict]]:
    if max_pages <= 0:
        return articles, []
    kept: list[dict] = []
    dropped: list[dict] = []
    for article in articles:
        page_count = article.get("page_count")
        if isinstance(page_count, int) and page_count > max_pages:
            dropped.append(
                {
                    "pmid": article.get("pmid"),
                    "title": article.get("title"),
                    "page_count": page_count,
                }
            )
            continue
        kept.append(article)
    return kept, dropped


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    queries = load_queries(args)
    exclude_reviews = not args.include_reviews
    if (
        args.min_year is not None
        and args.max_year is not None
        and args.min_year > args.max_year
    ):
        raise SystemExit("--min-year must be <= --max-year")
    year_clause = build_year_clause(args.min_year, args.max_year)
    journal_clause = build_journal_clause(args.journal)

    hit_map: dict[str, SearchHit] = {}
    query_summaries: list[dict] = []
    for index, query in enumerate(queries):
        effective_query = apply_review_filter(query) if exclude_reviews else query
        for extra in (year_clause, journal_clause):
            if extra:
                effective_query = f"({effective_query}) {extra}"
        payload = {
            "db": "pubmed",
            "retmode": "json",
            "retmax": str(args.retmax),
            "sort": args.sort,
            "term": effective_query,
            "tool": args.tool,
        }
        if args.email:
            payload["email"] = args.email
        result = fetch_json(ESEARCH_URL, payload)["esearchresult"]
        id_list = result.get("idlist", [])
        query_summaries.append(
            {
                "query": query,
                "effective_query": effective_query,
                "count": int(result.get("count", 0)),
                "returned_pmids": id_list,
            }
        )
        for pmid in id_list:
            if pmid not in hit_map:
                hit_map[pmid] = SearchHit(
                    pmid=pmid,
                    matched_queries=[query],
                    first_query_index=index,
                )
            elif query not in hit_map[pmid].matched_queries:
                hit_map[pmid].matched_queries.append(query)
        time.sleep(0.12)

    articles: list[dict] = []
    pmids = list(hit_map.keys())
    for batch in chunked(pmids, 100):
        payload = {
            "db": "pubmed",
            "retmode": "xml",
            "id": ",".join(batch),
            "tool": args.tool,
        }
        if args.email:
            payload["email"] = args.email
        root = fetch_xml(EFETCH_URL, payload)
        articles.extend(parse_articles(root, hit_map))
        time.sleep(0.12)

    articles, dropped_long = filter_articles_by_page_count(articles, args.max_pages)

    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "filters": {
            "exclude_reviews": exclude_reviews,
            "max_pages": args.max_pages,
            "min_year": args.min_year,
            "max_year": args.max_year,
            "journals": list(args.journal),
        },
        "queries": query_summaries,
        "query_count": len(queries),
        "unique_article_count": len(articles),
        "dropped_by_page_count": dropped_long,
        "articles": articles,
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
