import { CATEGORIES_ENDPOINT, getAPIBaseURL } from "@/util/constants";

export default class CategoryService {
  /** Fetches available category filters, returning an empty list on failure. */
  static async list(): Promise<string[]> {
    try {
      const res = await fetch(`${getAPIBaseURL()}${CATEGORIES_ENDPOINT}`, {
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
