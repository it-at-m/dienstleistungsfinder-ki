import type { FeedbackConfig } from "@/types/FeedbackConfig";

export const USE_MOCK_DATA: boolean = import.meta.env.VITE_USE_MOCK_DATA
  ? import.meta.env.VITE_USE_MOCK_DATA === "true"
  : false;

export const ENABLE_ADVANCED_FILTERS: boolean = import.meta.env
  .VITE_ENABLE_ADVANCED_FILTERS
  ? import.meta.env.VITE_ENABLE_ADVANCED_FILTERS !== "false"
  : false;

export function getAPIBaseURL(): string {
  if (import.meta.env.VITE_VUE_APP_API_URL) {
    return import.meta.env.VITE_VUE_APP_API_URL;
  } else {
    return new URL(import.meta.url).origin;
  }
}

// FEEDBACK
// Default mailto templates used until config endpoint overwrites them.
export const DEFAULT_FEEDBACK_CONFIG: FeedbackConfig = {
  positive: {
    to: "itm.kicc@muenchen.de",
    subject: "KI-Suche Feedback",
    body: "Hallo,\n\nich habe positives Feedback für euch:",
  },
  negative: {
    to: "itm.kicc@muenchen.de",
    subject: "KI-Suche Problem",
    body: "Hallo,\n\nich hatte folgendes Problem mit der KI-Suche:",
  },
};

// DLF-SEARCH-WEBCOMPONENT
export const DEFAULT_EXAMPLES = [
  "Was brauche ich alles, um mich umzumelden?",
  "Wie kann ich meinen Personalausweis verlängern?",
  "Wo ist mein Wahlbüro für die Bundestagswahl?",
  "Meine Oma braucht einen Computer, gibt es einen Zuschuss?",
  "Wie tausche ich meinen alten Führerschein um?",
  "Kann ich eine Sozialwohnung bekommen?",
];

export const DEFAULT_FRONTEND_CONFIG = {
  feedback: DEFAULT_FEEDBACK_CONFIG,
  examples: DEFAULT_EXAMPLES,
};
//API
export const RETRIEVAL_ENDPOINT = "/api/retrieval";
export const ANSWER_ENDPOINT = "/api/answer";
export const SCORE_ENDPOINT = "/api/score";
export const CONFIG_ENDPOINT = "/api/config";
export const CATEGORIES_ENDPOINT = "/api/categories";
export const QUERY_LENGTH_LIMIT_ERROR_TYPE = "string_too_long";
export const KEYWORDS_ENDPOINT = "/api/keywords";
