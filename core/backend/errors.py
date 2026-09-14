from fastapi import HTTPException


class AnswerChainException(Exception):
    """Raised when an answer chain is broken."""

    pass


class QuestionNotAnswerableException(AnswerChainException):
    """Raised when a question is not deemed answerable by the model."""

    def __init__(self):
        self.message = "Question is not answerable"
        super().__init__(self.message)


class QuoteNotFoundException(AnswerChainException):
    """Exception raised when a quote is not found in the article."""

    def __init__(self, quote: str, article_md: str):
        self.quote = quote
        self.article_md = article_md
        self.message = "Quote not found in the article."
        super().__init__(self.message)


class NoAnswerFoundException(HTTPException):
    """Exception raised when no answer is found by LLM for a question."""

    def __init__(self, document: str):
        self.status_code = 404
        self.detail = f"No answer found in document '{document}'."
        super().__init__(self.status_code, self.detail)


class ContentFilterException(HTTPException):
    """
    Exception raised when the language model API triggers a content filter.
    """

    def __init__(self):
        self.status_code = 422
        self.detail = "Content filter was triggered by question."
        super().__init__(self.status_code, self.detail)
