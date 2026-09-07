from __future__ import annotations  # noqa: F404

from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PastDatetime,
    PositiveInt,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)


class InfoField(BaseModel):
    label: str | None
    id: str
    name: str
    type: str


class LinkClass(BaseModel):
    title: str
    text: str
    id: str
    internal: bool


class Link(BaseModel):
    uri: HttpUrl
    label: str
    linkClass: LinkClass


class MultiValueField(InfoField):
    type: str = "LINK"
    link_field_name: str | None = Field(default=None, validation_alias=AliasChoices("link_field_name", "name"))
    values: list[Link]


class TextValueField(InfoField):
    type: str = "TEXT"
    value: str


class Keyword(BaseModel):
    name: str = Field(description="Main keyword name (1-3 words)")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in [0,1]")


class KeywordResult(BaseModel):
    keywords: list[Keyword] = Field(default_factory=list)


class DetailedArticle(BaseModel):
    name: str
    language: str = Field(validation_alias=AliasChoices("language", AliasPath("categryPath", "name")))
    description: str = ""
    fields: list[MultiValueField | TextValueField | InfoField]
    keywords: set[str] = Field(validation_alias=AliasChoices("keywords", "synonyms"), default=set())
    categories: dict[str, Any] = Field(default_factory=dict)
    publicUrl: HttpUrl
    id: PositiveInt
    public: bool
    lastModification: PastDatetime

    @field_validator("language", mode="after")
    def validate_language(cls, input: str) -> str:
        if input in ["en", "de"]:
            return input
        elif input in ["Bürgerservice", "Rathaus"]:
            return "de"
        elif input in ["Citizen service", "Town hall"]:
            return "en"
        else:
            raise ValidationError("Invalid language input value", input)


class ArticleInfo(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True)]
    id: PositiveInt
    apiUrl: str
    keywords: set[str] = set()

    # exluded fields, may be added later
    # public: bool | None = None
    # lastModification: datetime | None = None

    # @field_serializer("lastModification", when_used="json")
    # def serialize_last_modification(lastModification: datetime):
    #     return int(lastModification.timestamp() * 1000)

    # @field_validator("lastModification", mode="before")
    # def validate_last_modification(lastModification: int):
    #     return datetime.fromtimestamp(lastModification / 1000)


class TransformedArticle(BaseModel):
    name: str
    language: str
    description: str = ""
    source: HttpUrl = Field(validation_alias=AliasChoices("source", "publicUrl"))
    public: bool
    id: PositiveInt
    lastModification: datetime
    keywords: set[str] = set()
    categories: dict[str, Any]
    online_services: list[str] | None = None
    page_content: str = ""


class CollectionArtifact(BaseModel):
    article_infos: list[ArticleInfo]


class ExtractionArtifact(BaseModel):
    detailed_articles: list[DetailedArticle]


class TransformationArtifact(BaseModel):
    documents: list[TransformedArticle]


class Language(BaseModel):
    name: str
    field_headings: dict[str, str]
    description_heading: str
    summary_heading: str
    links_heading: str
    keywords_heading: str


# --- Core recursive JCR/Magnolia node -----------------------------


class JcrNode(BaseModel):
    """Generic Magnolia/JCR node with dynamic, recursively nested children."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str = Field(alias="@name")
    path: str = Field(alias="@path")
    id: str = Field(alias="@id")
    node_type: str = Field(alias="@nodeType")
    last_modified: datetime | None = Field(default=None, alias="mgnl:lastModified")

    # Optional explicit child order given by Magnolia
    nodes_order: list[str] | None = Field(default=None, alias="@nodes")

    # All nested child nodes discovered dynamically (keys like "0", "1", "link", "images", ...)
    children: dict[str, "JcrNode"] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _extract_children(cls, data: Any) -> Any:
        """
        Move any nested objects that themselves look like JCR nodes
        (i.e., dict with '@nodeType') into a 'children' mapping.
        Keep all other fields as-is (Pydantic 'extra=allow').
        """
        if not isinstance(data, dict):
            return data

        reserved = {"@name", "@path", "@id", "@nodeType", "mgnl:lastModified", "@nodes"}
        children: dict[str, dict] = {}

        # We must not steal the "children" field if the input already had it
        for k, v in list(data.items()):
            if k in reserved or k == "children":
                continue
            if isinstance(v, dict) and "@nodeType" in v:
                children[k] = v
                data.pop(k)

        if children:
            data["children"] = {k: v for k, v in children.items()}
        return data

    def children_ordered(self) -> list["JcrNode"]:
        """
        Return children honoring Magnolia's @nodes ordering when present.
        Fallback: numeric-then-lexicographic order of child keys.
        """
        if self.nodes_order:
            return [self.children[k] for k in self.nodes_order if k in self.children]

        # Fallback ordering: numeric keys first by int value, then other keys lexicographically
        def sort_key(k: str):
            if k.isdigit():
                return (0, int(k))
            return (1, k)

        return [self.children[k] for k in sorted(self.children.keys(), key=sort_key)]


# --- Domain object extending the generic node (top-level "result" items) ---


class ArticleNode(JcrNode):
    # Common article fields seen in your payload (all optional/nullable)
    sprache: str | None = None
    summary: str | None = None
    breadcrumbTitle: str | None = None
    teaserText: str | None = None
    teaserTitle: str | None = None
    title: str | None = None
    hideArticle: bool | None = None
    urlTitle: str | None = None
    redaktionComment: str | None = None
    responsibility: list[str] | None = None
    mainCategory: str | None = None
    headline: str | None = None
    metaDescription: str | None = None
    last_modified: datetime | None = Field(alias="mgnl:lastModified", default=None)

    # Named child node commonly present at this level
    blocks: JcrNode | None = None

    @model_validator(mode="before")
    @classmethod
    def _validate_last_modified(cls, values: dict[str, Any]) -> dict[str, Any]:
        if "last_modified" not in values:
            values["last_modified"] = datetime.now()
        return values


# --- Top-level search/list response ----------------------------------------


class SearchResponse(BaseModel):
    total: int = 0
    offset: int = 0
    limit: int = 0
    results: list[ArticleNode] = []


# --- Data models for etracker site visits integration ----------------------
# Site datamodel: includes all fields from etracker report
# this is currently not used. Can be used for further extensions
class Site(BaseModel):
    url: str
    page_name: str
    unique_visits: int
    unique_visitors: int
    visits_cookie_rate: float | str
    visitors_cookie_rate: float | str
    visits_per_visitor_with_cookie: float | str
    page_impressions: int
    entry_pages: int
    exit_page: int
    bounces_per_visit: float | str
    staytime_per_unique_visits_v2: float | str
    staytime_bouncer_per_bounce: float | str


class ServiceSite(BaseModel):
    url: str
    page_name: str
    unique_visits: int


class InfoSite(BaseModel):
    url: str
    page_name: str
    unique_visits: int
