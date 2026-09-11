import type AnswerInput from "@/types/AnswerInput";
import type DLFAnswer from "@/types/DLFAnswer";
import type RetrievalInput from "@/types/RetrievalInput";
import type RetrievalResult from "@/types/RetrievalResult";
import type { RetrievedDocument } from "@/types/RetrievalResult";

import {
  ANSWER_ENDPOINT,
  getAPIBaseURL,
  QUERY_LENGTH_LIMIT_ERROR_TYPE,
  RETRIEVAL_ENDPOINT,
  SCORE_ENDPOINT,
} from "@/util/constants";

type Callback<T> = (result: T) => void;

class ContentFilterException extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ContentFilterException";
  }
}

/**
 * Service class for performing search operations against the backend API.
 */
export default class SearchService {
  static retrieval(
    input: RetrievalInput,
    signal: AbortSignal
  ): Promise<RetrievalResult | undefined> {
    return fetch(`${getAPIBaseURL()}${RETRIEVAL_ENDPOINT}`, {
      method: "POST",
      signal: signal,
      body: JSON.stringify(input), // Add the input as the request body
      headers: {
        "Content-Type": "application/json", // Set the content type header
      },
    }).then((response) => {
      if (response.status !== 200) {
        Promise.reject(
          "Retrieval in den Dokumenten konnte nicht durchgeführt werden"
        );
      } else return response.json() as unknown as RetrievalResult;
    });
  }

  static score(input: {
    value: boolean;
    run_id: string;
  }): Promise<string | void> {
    return fetch(`${getAPIBaseURL()}${SCORE_ENDPOINT}`, {
      method: "POST",
      body: JSON.stringify(input), // Add the input as the request body
      headers: {
        "Content-Type": "application/json", // Set the content type header
      },
    }).then((response) => {
      if (response.status !== 200) {
        Promise.reject("Score konnte nicht durchgeführt werden");
      } else Promise.resolve("Score erfolgreich");
    });
  }

  static answer(
    input: AnswerInput,
    signal: AbortSignal
  ): Promise<DLFAnswer | undefined> {
    return fetch(`${getAPIBaseURL()}${ANSWER_ENDPOINT}`, {
      method: "POST",
      signal: signal,
      body: JSON.stringify(input), // Add the input as the request body
      headers: {
        "Content-Type": "application/json", // Set the content type header
      },
    }).then((response) => {
      if (response.status !== 200) {
        return Promise.reject(
          response.status + ": Antwort konnte nicht generiert werden"
        );
      } else return response.json() as unknown as DLFAnswer;
    });
  }

  /**
   * Performs a search based on the provided query.
   *
   * @param query - The search query.
   * @param onProcessed - Callback function called when a DLFDocument is processed.
   * @param onFailure - Callback function called when an error occurs during search.
   * @param onComplete - Callback function called when the search is complete.
   * @param onRetrieval - Callback function called when documents are retrieved.
   * @param signal - The AbortSignal used to cancel the search.
   * @throws {ApiError} If the query is empty or null.
   */
  static search(
    query: string | null | undefined,
    onProcessed: Callback<DLFAnswer>,
    onFailure: Callback<RetrievedDocument>,
    onComplete: Callback<void>,
    onRetrieval: Callback<RetrievalResult>,
    signal: AbortSignal,
    keywords?: string[],
    categories?: string[]
  ): Promise<void> {
    const hasKeywordFilters = !!(keywords && keywords.length > 0);
    const hasCategoryFilters = !!(categories && categories.length > 0);
    if (query || hasKeywordFilters || hasCategoryFilters) {
      return SearchService.performSearch(
        query ?? "",
        onProcessed,
        onFailure,
        onComplete,
        onRetrieval,
        signal,
        keywords,
        categories
      );
    }
    return Promise.reject("Die Anfrage is leer");
  }

  /**
   * Performs a search operation.
   *
   * @param query - The search query.
   * @param onProcessed - Callback function called when a document is succesfully processed with the answer chain.
   * @param onFailure - Callback function called when a document answer chain fails.
   * @param onComplete - Callback function called when the search operation is complete.
   * @param onRetrieval - Callback function called when documents are retrieved.
   * @param signal - The AbortSignal used to cancel the search operation.
   * @returns A Promise that resolves when the search operation is complete.
   */
  private static async performSearch(
    query: string,
    onProcessed: Callback<DLFAnswer>,
    onFailure: Callback<RetrievedDocument>,
    onComplete: Callback<void>,
    onRetrieval: Callback<RetrievalResult>,
    signal: AbortSignal,
    keywords?: string[],
    categories?: string[]
  ): Promise<void> {
    let retrievalInput: RetrievalInput;
    const textQuery = (query ?? "").trim();
    const hasTextQuery = textQuery.length > 0;
    const hasKeywords = !!(keywords && keywords.length > 0);
    const hasCategories = !!(categories && categories.length > 0);
    const fallbackTerms: string[] = [];
    if (hasKeywords && keywords) {
      fallbackTerms.push(...keywords);
    }
    if (hasCategories && categories) {
      fallbackTerms.push(...categories);
    }
    const effectiveQuery = hasTextQuery ? textQuery : fallbackTerms.join(" ");
    retrievalInput = SearchService.buildRetrievalInput(effectiveQuery, {
      keywords: hasKeywords ? keywords : undefined,
      categories: hasCategories ? categories : undefined,
    });
    return SearchService.retrieval(retrievalInput, signal)
      .then(async (retrievalResult) => {
        if (!retrievalResult) {
          return Promise.reject("Es konnten keine Dokumente gefunden werden");
        }
        onRetrieval(retrievalResult);
        for (const doc of retrievalResult.retrieval_documents) {
          await SearchService.answer(
            {
              doc: {
                id: doc.id,
                collection: doc.collection,
              },
              enhanced_query: retrievalResult.enhanced_query,
              run_id: retrievalResult.run_id,
            },
            signal
          )
            .then((answer) => {
              if (answer) onProcessed(answer);
              else onFailure(doc);
            })
            .catch((err: any) => {
              const errorMsg = String(err);
              if (!errorMsg.includes("404")) {
                console.debug(err);
              }
              onFailure(doc);
              if (errorMsg.includes("422")) {
                throw new ContentFilterException(errorMsg);
              }
            });
        }
        onComplete();
      })
      .catch((e: any) => {
        let message = e;
        if (e instanceof ContentFilterException)
          message =
            "Die Anfrage enthält möglicherweise unzulässige oder sensible Inhalte und wurde daher blockiert. Bitte formulieren Sie Ihre Frage um.";
        onComplete();
        if (!signal.aborted) return Promise.reject(message);
      });
  }

  private static buildRetrievalInput(
    query: string,
    options: Partial<
      Pick<RetrievalInput, "keywords" | "categories" | "run_id">
    > = {}
  ): RetrievalInput {
    const { keywords, categories, run_id } = options;
    const input: RetrievalInput = {
      query,
      result: "minimal",
      collections: "all", //["service"] as RetrievalInput["collections"],
      category_match: "any",
      rerank: true,
    };
    if (keywords && keywords.length > 0) {
      input.keywords = keywords;
    }
    if (categories && categories.length > 0) {
      input.categories = categories;
    }
    if (run_id) {
      input.run_id = run_id;
    }
    return input;
  }
}
