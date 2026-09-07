import json
import os
import random
import re
from collections.abc import Iterable
from html import unescape
from uuid import NAMESPACE_URL, uuid5

from httpx import Client, HTTPError
from langchain_core.documents.base import Document
from truststore import inject_into_ssl

from src.data_models import ArticleNode, JcrNode, SearchResponse
from src.utils import get_with_retry

inject_into_ssl()

# NOTE: the limit key in the URL should control the maximum number of articles fetched in a single request,
# however, this key does not work properly! The fixed limit is set to 100 by the api.
MAGNOLIA_URL = "https://stadt.muenchen.de/.rest/delivery/InfoArticleEndpoint?offset={offset}"
MAGNOLIA_NAMESPACE = uuid5(NAMESPACE_URL, "https://stadt.muenchen.de/info")

HEADING_FIELDS = ("title", "headline", "breadcrumbTitle", "anchorTitle")
BODY_TEXT_FIELDS = ("text", "teaserText", "summary", "caption", "metaDescription")

# Treat other keys that *look* like text as textual too (optional)
LIKELY_TEXT_KEY = re.compile(r"(?:^|_)(headline|caption|text|summary|desc|description)$", re.I)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def _fetch_articles(url: str | None = None, total: int = 10000) -> SearchResponse:
    result: SearchResponse = SearchResponse()
    offset = 0

    timeout_sec: float = float(os.getenv("HTTP_TIMEOUT_SEC", "20"))
    https_proxy: str | None = os.getenv("HTTPS_PROXY", None)

    if not url:
        url = MAGNOLIA_URL

    # fetch articles in batches, because the API has a fixed limit of 100 articles per request
    with Client(proxy=https_proxy, timeout=timeout_sec, follow_redirects=True) as client:
        while offset < total:
            try:
                api_resp = get_with_retry(client=client, url=url.format(offset=offset))
                api_json = api_resp.json()
                if total > 3000:
                    total = api_json["total"] if "total" in api_json else 3000
                offset += 100
                if api_json.get("results") != []:
                    article_batch = SearchResponse.model_validate(api_json)
                    # first batch returns the total amount of articles that can be retrieved via api
                    # default for total in searchresponse is 0
                    if result.total == 0:
                        result = article_batch
                    else:
                        result.results.extend(article_batch.results)

            except HTTPError as e:
                print(f"Error fetching articles: {e}")
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON response: {e}")

    return result


def _check_for_easy_language(urlTitle: str) -> bool:
    """Check if the article is in leichte sprache based on its urlTitle."""
    ls_indicators = ["leichte-sprache", "leichtesprache", "-ls", "inleichtersprache"]
    return any(indicator in urlTitle for indicator in ls_indicators)


def _magnolia_article_to_doc(article: ArticleNode) -> Document:
    """Convert a Magnolia article to a LangChain Document."""
    metadata = {
        "name": article.title,
        "language": "de",  # for now all articles are in German
        "id": article.id,
        "source": f"https://stadt.muenchen.de/infos/{article.urlTitle}",
        "description": article.summary,
        "easy_language": _check_for_easy_language(article.urlTitle) if article.urlTitle else False,
        "public": article.hideArticle,
        "created_at": article.last_modified,
        # TODO: generate keywords
    }
    return Document(
        page_content=extract_text_markdown(article, include_headings=True, include_likely_extras=False),
        metadata=metadata,
        id=str(uuid5(namespace=MAGNOLIA_NAMESPACE, name=article.urlTitle if article.urlTitle else "unknown")),
    )


def _to_text(s: str) -> str:
    # strip HTML and normalize whitespace
    return _WS_RE.sub(" ", _TAG_RE.sub("", unescape(s))).strip()


def _iter_text_blocks(
    node: "JcrNode",
    *,
    include_headings: bool = True,
    include_likely_extras: bool = False,
) -> Iterable[tuple[str, str]]:
    """
    Yields tuples of (kind, text) where kind is 'h1','h2','p'.
    Headings come first for each node, then body text, then recurse into children
    honoring Magnolia's @nodes order via node.children_ordered().
    """
    # 1) headings
    if include_headings:
        for i, k in enumerate(HEADING_FIELDS, start=1):
            v = getattr(node, k, None)
            if isinstance(v, str) and (v := _to_text(v)):
                yield (f"h{min(i, 2)}", v)  # map earlier fields to higher-level headings

    # 2) main text fields
    for k in BODY_TEXT_FIELDS:
        v = getattr(node, k, None)
        if isinstance(v, str) and (v := _to_text(v)):
            yield ("p", v)

    # 3) any extra string fields that look like text
    if include_likely_extras:
        declared = set(getattr(node, "model_fields", {}).keys())
        for k, v in node.__dict__.items():
            if k in declared or k in {"children", "nodes_order"} or k.startswith("_") or not isinstance(v, str):
                continue
            if (v2 := _to_text(v)) and LIKELY_TEXT_KEY.search(k):
                # treat extra titles as h2, others as paragraphs
                kind = "h2" if "title" in k.lower() or "headline" in k.lower() else "p"
                yield (kind, v2)

    # 4) recurse
    for child in node.children_ordered():
        yield from _iter_text_blocks(
            child, include_headings=include_headings, include_likely_extras=include_likely_extras
        )


def extract_text_plain(node: "JcrNode", include_headings: bool = True, include_likely_extras: bool = False) -> str:
    """Single plain-text blob, headings included as lines."""
    lines: list[str] = []
    for kind, txt in _iter_text_blocks(
        node, include_headings=include_headings, include_likely_extras=include_likely_extras
    ):
        lines.append(txt)
    return "\n\n".join(lines)


def extract_text_markdown(node: "JcrNode", include_headings: bool = True, include_likely_extras: bool = False) -> str:
    """Markdown with #/# # for headings and blank lines between blocks."""
    out: list[str] = []
    for kind, txt in _iter_text_blocks(
        node, include_headings=include_headings, include_likely_extras=include_likely_extras
    ):
        if kind == "h1":
            out.append(f"# {txt}")
        elif kind == "h2":
            out.append(f"## {txt}")
        else:
            out.append(txt)
    return "\n\n".join(out)


def main():
    fetched_articles: SearchResponse = _fetch_articles()
    docs: list[Document] = [_magnolia_article_to_doc(article) for article in fetched_articles.results]
    print(len(docs), "Magnolia documents fetched and parsed.")
    sample = random.sample(docs, 10)
    for i in sample:
        print(f"Document {i.metadata['name']}: {i.metadata}")


if __name__ == "__main__":
    main()
