import { getAPIBaseURL, KEYWORDS_ENDPOINT } from "@/util/constants";

export default class KeywordService {
  /** Fetches available keyword filters, returning an empty list on failure. */
  static async list(): Promise<string[]> {
    try {
      const res = await fetch(`${getAPIBaseURL()}${KEYWORDS_ENDPOINT}`, {
        method: "GET",
        headers: {
          Accept: "application/json",
        },
      });
      if (!res.ok) return [];
      const data = (await res.json()) as string[];
      return data;
    } catch {
      return [];
    }
  }
}
