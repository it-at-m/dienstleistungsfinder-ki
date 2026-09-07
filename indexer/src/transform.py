import os
import re

from dotenv import load_dotenv
from markdownify import markdownify
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from src.data_models import (
    DetailedArticle,
    ExtractionArtifact,
    Language,
    MultiValueField,
    TextValueField,
    TransformationArtifact,
    TransformedArticle,
)
from src.logtools import getLogger

logger = getLogger()


languages = {
    "de": Language(
        name="de",
        field_headings={
            "sf1": "Zusammenfassung",
            "sf2": "Verantwortliches Referat",
            "sf6": "Benötigte Unterlagen",
            "sf7": "Besonderheiten",
            "sf12": "Voraussetzungen",
            "sf13": "Zu beachten",
            "sf14": "Wichtiger Hinweis",
            "sf16": "Gebührenrahmen",
            "sf17": "Zahlungsarten",
            "sf18": "Bearbeitungszeit",
            "sf19": "Rechtliche Grundlagen",
            "sf20": "Fragen und Antworten",
            "sf21": "ID Gebärden-Video",
            "sf23": 'Link "Leichte Sprache"',
            "sf24": "Redaktionshinweis",
        },
        description_heading="Beschreibung",
        summary_heading="Zusammenfassung",
        links_heading="Weiterführende Links",
        keywords_heading="Schlagwörter",
    ),
    "en": Language(
        name="en",
        field_headings={
            "sf1": "Summary",
            "sf2": "Responsible Department",
            "sf6": "Required Documents",
            "sf7": "Special Considerations",
            "sf12": "Prerequisites",
            "sf13": "Please Note",
            "sf14": "Important Information",
            "sf16": "Fee Range",
            "sf17": "Payment Methods",
            "sf18": "Processing Time",
            "sf19": "Legal Basis",
            "sf20": "Questions and Answers",
            "sf21": "Sign Language Video ID",
            "sf23": 'Link "Easy Language"',
            "sf24": "Editorial Note",
        },
        description_heading="Description",
        summary_heading="Summary",
        links_heading="Further Links",
        keywords_heading="Keywords",
    ),
}


def _remove_html_elements(s: str) -> str:
    html_pattern = re.compile("<.*?>")
    return re.sub(html_pattern, "", s)


def transform(detailed_articles: list[DetailedArticle]) -> list[TransformedArticle]:
    """
    Transforms detailed articles into documents by building HTML and transforming it to Markdown.
    Args:
        detailed_articles (list[DetailedArticle]): A list of DetailedArticle objects.
    Returns:
        list[Document]: A list of Document objects.
    """
    transformed_articles: list[TransformedArticle] = []
    logger.info(f"Starting transformation for {len(detailed_articles)} articles")
    with logging_redirect_tqdm(loggers=[logger]):
        for article in tqdm(detailed_articles):
            language: Language = languages.get(article.language) or languages["de"]
            links = {}
            online_services = []
            html_elements = [f"<h1>{article.name}</h1>"]

            if len(article.description) > 0:
                # the DETAILED_ARTICLE description contains html tags that need to be removed
                # fixing the issue here in transform() seems more intuitive and transparent than at time of api extraction and validation
                # origin of issue extract.py line 44 (api retrieval)
                # if fixed in api --> remove line 100
                html_elements.append(f"<h2>{language.description_heading}</h2>\n{article.description}")
                article.description = _remove_html_elements(article.description)

            for field in article.fields:
                if field.name == "SUMMARY":
                    html_elements.insert(1, f"<h2>{language.summary_heading}</h2>\n{field.value}")  # type: ignore

                if isinstance(field, MultiValueField) and field.link_field_name == "ONLINE_SERVICE":
                    if len(field.values) > 1:
                        logger.debug(f"multiple online serivces in article: {article.id}")
                    service_name = (
                        [field.values[i].label for i in range(len(field.values))]
                        if len(field.values) > 0
                        else ["Online Service"]
                    )
                    service_url = (
                        [field.values[i].uri for i in range(len(field.values))] if len(field.values) > 0 else [""]
                    )
                    online_service_md = [f"[{service_name[i]}]({service_url[i]})" for i in range(len(service_name))]
                    online_services.extend(online_service_md)

                elif isinstance(field, TextValueField):
                    header = language.field_headings.get(field.id, " ")  # Fail-safe empty string
                    html_elements.append(f"<h2>{header}</h2>\n{field.value}")

                elif isinstance(field, MultiValueField):
                    for link in field.values:
                        if link.uri not in links:
                            links[link.uri] = link.label

            if len(links) > 0:
                links_html = f"<h2>{language.links_heading}</h2>\n<ul>"
                for uri, label in links.items():
                    links_html += f'<li><a href="{uri}">{label}</a></li>\n'
                links_html += "</ul>"
                html_elements.append(links_html)

            if len(article.keywords) > 0:
                keywords_html = f"<h2>{language.keywords_heading}</h2>\n<ul>"
                for keyword in article.keywords:
                    keywords_html += f"<li>{keyword}</li>"
                keywords_html += "</ul>"
                html_elements.append(keywords_html)

            html_content = "\n".join(html_elements)
            md_content = markdownify(html_content, heading_style="ATX")

            transformed_article = TransformedArticle.model_validate(article.model_dump())
            transformed_article.online_services = online_services
            transformed_article.page_content = md_content
            transformed_articles.append(transformed_article)

    return transformed_articles


def main():
    """
    Entry point of the transformation script.
    Reads the extraction artifact, runs the transformation, and saves the transformation artifact.

    Corresponding Environment variables:
        EXTRACTION_FILENAME: Path to the extraction JSON file (default: "artifacts/extraction.json")
        TRANSFORMATION_FILENAME: Path to save the transformation JSON file (default: "artifacts/transformation.json")
    """
    logger.info("Transformation script started")
    load_dotenv()

    EXTRACTION_FILENAME = os.getenv("EXTRACTION_FILENAME", "artifacts/extraction.json")

    logger.debug(f"Loading extraction artifact from {EXTRACTION_FILENAME} (can be specified in EXTRACTION_FILENAME)")
    with open(EXTRACTION_FILENAME, "r", encoding="utf-8") as file:
        extraction = ExtractionArtifact.model_validate_json(file.read())

    logger.info(f"Extraction artifact with {len(extraction.detailed_articles)} articles loaded")

    transformed_articles = transform(extraction.detailed_articles)
    transformation = TransformationArtifact(documents=transformed_articles)

    TRANSFORMATION_FILENAME = os.getenv("TRANSFORMATION_FILENAME", "artifacts/transformation.json")
    logger.debug(
        f"Saving transformation artifact to {TRANSFORMATION_FILENAME} (can be specified in TRANSFORMATION_FILENAME)"
    )
    with open(TRANSFORMATION_FILENAME, "w", encoding="utf-8") as file:
        file.write(transformation.model_dump_json(indent=2))

    logger.info(f"Transformation artifact with {len(transformed_articles)} document saved. Script finished.")


if __name__ == "__main__":
    main()
