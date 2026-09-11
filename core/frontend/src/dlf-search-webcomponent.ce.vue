<script setup lang="ts">
import type DLFAnswer from "@/types/DLFAnswer";

import { MucCallout } from "@muenchen/muc-patternlab-vue";
import customIconsSprite from "@muenchen/muc-patternlab-vue/assets/icons/custom-icons.svg?raw";
import mucIconsSprite from "@muenchen/muc-patternlab-vue/assets/icons/muc-icons.svg?raw";
import { computed, nextTick, onMounted, ref } from "vue";

import type FrontendConfig from "./types/FrontendConfig";
import type { RetrievedDocument } from "./types/RetrievalResult";
import type RetrievalResult from "./types/RetrievalResult";

import CategoryService from "@/api/CategoryService";
import KeywordService from "@/api/KeywordService";
import SearchService from "@/api/SearchService";
import dlfIconsSprite from "@/assets/custom-icons.svg?raw";
import dlfDocumentList from "@/components/dlf-document-list.vue";
import dlfExampleList from "@/components/dlf-example-list.vue";
import dlfFeedback from "@/components/dlf-feedback.vue";
import dlfIntro from "@/components/dlf-intro.vue";
import dlfListPicker from "@/components/dlf-list-picker.vue";
import dlfProgress from "@/components/dlf-progress.vue";
import dlfSearchbar from "@/components/dlf-searchbar.vue";
import {
  DEFAULT_FRONTEND_CONFIG,
  ENABLE_ADVANCED_FILTERS,
} from "@/util/constants";
import ConfigService from "./api/ConfigService";
import FeedbackState from "./types/FeedbackState";

const props = defineProps<{
  categories?: string;
  keywords?: string;
}>();

let abortController = new AbortController();

const found_documents = ref<DLFAnswer[]>([]);
const loading_docs = ref<RetrievedDocument[]>([]);
const loading = ref<boolean>(false);
const initial = ref<boolean>(true);
const current_loading_step = ref<number>(0);
const progress_msg = ref<string>("Suche relevante Artikel");
const fehler = ref<string>("");
const feedback_state = defineModel<FeedbackState>({
  default: FeedbackState.PENDING_SEARCH,
});
const current_run_id = ref<string>("");
const config = ref<FrontendConfig>(DEFAULT_FRONTEND_CONFIG);
const number_of_loading_steps = ref<number>(13);
const searchquery = ref<string>("");
const documentListRef = ref<HTMLElement | null>(null);

// Metadata filters
const metadataKeywords = ref<string[]>([]);
const allKeywords = ref<string[]>([]);
const metadataCategories = ref<string[]>([]);
const allCategories = ref<string[]>([]);
const showAdvancedFilters = ref<boolean>(false);
const advancedFiltersEnabled = ENABLE_ADVANCED_FILTERS;
const hasActiveFilters = computed(
  () => metadataKeywords.value.length > 0 || metadataCategories.value.length > 0
);

function toggleAdvancedFilters() {
  if (!advancedFiltersEnabled) {
    return;
  }
  showAdvancedFilters.value = !showAdvancedFilters.value;
}

function clearAllFilters() {
  if (!advancedFiltersEnabled) {
    return;
  }
  metadataKeywords.value = [];
  metadataCategories.value = [];
  submitQuery(searchquery.value);
}

function applyFilters() {
  if (!advancedFiltersEnabled) {
    return;
  }
  submitQuery(searchquery.value);
}

onMounted(() => {
  ConfigService.get().then((c) => {
    config.value = c;
  });
  // Load available keywords for suggestions
  KeywordService.list()
    .then((list) => {
      allKeywords.value = list;
    })
    .catch(() => {
      allKeywords.value = [];
    });
  CategoryService.list()
    .then((list) => {
      allCategories.value = list;
    })
    .catch(() => {
      allCategories.value = [];
    });
});

const loading_progress = computed(() => {
  return (current_loading_step.value / number_of_loading_steps.value) * 100;
});

/**
 * Callback function for document retrieval.
 *
 * @param {RetrievalResult} retrievalResult - The retrieved documents.
 */
const onRetrievalCallback = (retrievalResult: RetrievalResult) => {
  current_run_id.value = retrievalResult.run_id;
  progress_msg.value = `Verarbeite relevante Artikel`;
  number_of_loading_steps.value =
    retrievalResult.retrieval_documents.length + 3;
  current_loading_step.value = 3;
  loading_docs.value = retrievalResult.retrieval_documents;
};

/**
 * Scrolls to the document list container with smooth behavior
 */
const scrollToResults = () => {
  nextTick(() => {
    if (documentListRef.value) {
      documentListRef.value.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }
  });
};

/**
 * Callback function for a succesfully processed document with the answer chain.
 *
 * @param {DLFAnswer} doc - The processed document.
 */
const onProcessedCallback = (doc: DLFAnswer) => {
  const isFirstDocument = found_documents.value.length === 0;
  found_documents.value.push(doc);
  current_loading_step.value = current_loading_step.value + 1;
  loading_docs.value = loading_docs.value.filter(
    (d) => d.name !== doc.doc_base_name
  );

  // Scroll to first result when it's found
  if (isFirstDocument) {
    feedback_state.value = FeedbackState.CONTEXTUAL;
    scrollToResults();
  }
};

/**
 * Callback function for a failed processing during the answer chain.
 *
 * @param {RetrievedDocument} failedDoc - The failed document.
 */
const onFailedCallback = (failedDoc: RetrievedDocument) => {
  current_loading_step.value = current_loading_step.value + 1;
  loading_docs.value = loading_docs.value.filter(
    (d) => d.name !== failedDoc.name
  );
};

/**
 * Callback function for the completion of all search callbacks (1 retrieval and n answer chains).
 */
const onCompleteCallback = () => {
  if (found_documents.value.length === 0) {
    feedback_state.value = FeedbackState.CONTEXTUAL;
  }
  loading.value = false;
};

const resetInitialState = () => {
  if (loading.value) {
    abortController.abort();
    abortController = new AbortController();
  }
  feedback_state.value = FeedbackState.PENDING_SEARCH;
  found_documents.value = [];
  loading_docs.value = [];
  loading.value = false;
  fehler.value = "";
  initial.value = true;
  metadataKeywords.value = [];
  metadataCategories.value = [];
};

const resetLoadingState = () => {
  progress_msg.value = "Suche relevante Artikel";
  current_loading_step.value = 1;
  number_of_loading_steps.value = 12;
  found_documents.value = [];
  loading_docs.value = [];
  loading.value = true;
  fehler.value = "";
  feedback_state.value = FeedbackState.PENDING_SEARCH;
};
/**
 * Submits a query for searching documents.
 *
 * @param {string} query - The query string to search for.
 */
const submitQuery = (query: string) => {
  searchquery.value = query;

  const propCategories = props.categories
    ? props.categories
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
    : [];
  const propKeywords = props.keywords
    ? props.keywords
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
    : [];

  const combinedCategories = [
    ...new Set([...metadataCategories.value, ...propCategories]),
  ];
  const combinedKeywords = [
    ...new Set([...metadataKeywords.value, ...propKeywords]),
  ];

  // Allow keywords-only search: proceed if either query or keywords exist
  if (
    query.trim() === "" &&
    combinedKeywords.length === 0 &&
    combinedCategories.length === 0
  ) {
    return;
  }
  initial.value = false;
  if (loading.value) {
    abortController.abort();
    abortController = new AbortController();
  }
  resetLoadingState();

  SearchService.search(
    query,
    onProcessedCallback,
    onFailedCallback,
    onCompleteCallback,
    onRetrievalCallback,
    abortController.signal,
    combinedKeywords,
    combinedCategories
  ).catch((e: string) => {
    fehler.value = e;
  });
};

/**
 * Scores the given trace with user feedback
 *
 * @param {boolean} value - The value to score the result.
 */
const scoreResult = (value: boolean) => {
  if (current_run_id.value === "") {
    console.debug("No run_id available for scoring.");
  } else {
    SearchService.score({
      run_id: current_run_id.value,
      value: value,
    });
  }
};
</script>

<template>
  <link
    href="https://assets.muenchen.de/mde/1.1.19/css/style.css"
    rel="stylesheet"
  />
  <main>
    <div>
      <div v-html="mucIconsSprite" />
      <div v-html="customIconsSprite" />
      <div v-html="dlfIconsSprite" />

      <dlf-intro labelfor="dlf-searchbar">
        <dlf-searchbar
          id="dlf-searchbar"
          :submit-query="submitQuery"
          :query="searchquery"
          :on-clear="resetInitialState"
        />
        <div
          v-if="advancedFiltersEnabled"
          class="advanced-controls"
        >
          <button
            type="button"
            class="advanced-toggle"
            :aria-expanded="showAdvancedFilters ? 'true' : 'false'"
            aria-controls="keyword-filter-section"
            @click="toggleAdvancedFilters"
          >
            {{ showAdvancedFilters ? "Filter verbergen" : "Erweiterte Suche" }}
          </button>
        </div>
        <div
          v-if="advancedFiltersEnabled && showAdvancedFilters"
          id="keyword-filter-section"
          class="keyword-filter"
        >
          <dlf-list-picker
            v-model="metadataKeywords"
            label="Stichwörter hinzufügen"
            :items="allKeywords"
            placeholder="Stichwort eingeben"
            add-button-label="Stichwort hinzufügen"
            add-button-aria-label="Weiteres Stichwort hinzufügen"
          />
          <dlf-list-picker
            v-model="metadataCategories"
            label="Kategorien hinzufügen"
            :items="allCategories"
            placeholder="Kategorie eingeben"
            add-button-label="Kategorie hinzufügen"
            add-button-aria-label="Weitere Kategorie hinzufügen"
          />
          <div
            v-if="hasActiveFilters"
            class="filter-actions"
          >
            <button
              type="button"
              class="apply-filters"
              @click="applyFilters"
            >
              Filter anwenden
            </button>
            <button
              type="button"
              class="clear-filters"
              @click="clearAllFilters"
            >
              Alle Filter entfernen
            </button>
          </div>
        </div>
      </dlf-intro>

      <div class="container">
        <div class="m-component__grid">
          <div class="main-body-container">
            <dlf-example-list
              v-if="!loading && initial"
              :examples="config.examples"
              :submit-query="submitQuery"
            />

            <div v-else>
              <div
                v-if="
                  loading == false &&
                  found_documents.length == 0 &&
                  initial == false &&
                  fehler == ''
                "
              >
                <muc-callout type="warning">
                  <template #header
                    >Wir haben leider keine passende Dienstleistung zu Ihrer
                    Suchanfrage gefunden.</template
                  >
                  <template #content>
                    <p>
                      Entschuldigung. Für ihre Frage konnte unsere Künstliche
                      Intelligenz leider kein passendes Ergebnis finden.
                      Vielleicht versuchen Sie es noch einmal mit einer anderen
                      Frage?
                    </p>
                  </template>
                </muc-callout>
              </div>
              <div v-if="fehler != ''">
                <muc-callout
                  title="No documents found"
                  type="error"
                >
                  <template #header>Ein Fehler ist aufgetreten.</template>
                  <template #content>
                    <p>{{ fehler }}</p>
                  </template>
                </muc-callout>
              </div>

              <div
                v-if="found_documents.length > 0"
                ref="documentListRef"
              >
                <dlf-document-list
                  :documents="found_documents"
                  :loading-documents="loading_docs"
                />
              </div>
              <div class="progress-container">
                <dlf-progress
                  v-if="loading"
                  :progress="loading_progress"
                  :msg="progress_msg"
                  :style="{
                    marginTop: found_documents.length > 0 ? '40px' : '0',
                  }"
                />
              </div>
            </div>
            <div style="height: 48px"></div>
            <muc-callout
              title="Disclaimer"
              type="info"
              class="heading disclaimer-callout"
            >
              <template #header>Rechtliche Hinweise</template>
              <template #content>
                <p>
                  Die von diesem System bereitgestellten Informationen dienen
                  als erste Orientierung und können keine rechtliche oder
                  fachspezifische Beratung ersetzen. Die Stadt München übernimmt
                  keine Gewähr für die Richtigkeit und Vollständigkeit der
                  automatisch generierten Antworten und empfiehlt bei wichtigen
                  Angelegenheiten den direkten Kontakt mit den zuständigen
                  städtischen Behörden.
                </p>
              </template>
            </muc-callout>
          </div>
        </div>
      </div>
      <dlf-feedback
        v-model="feedback_state"
        :config="config.feedback"
        :run-id="current_run_id"
        :query="searchquery"
        @score="scoreResult"
      ></dlf-feedback>
    </div>
  </main>
</template>

<style>
@import "@muenchen/muc-patternlab-vue/assets/css/custom-style.css";
@import "@muenchen/muc-patternlab-vue/muc-patternlab-vue.css";

.heading {
  margin-bottom: 0.5em;
}

.disclaimer-callout {
  margin-left: 0.375rem;
  margin-right: 0.375rem;
}

.main-body-container {
  margin-left: 20%;
  margin-right: 20%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  width: 100%;
  padding-bottom: 56px;
  padding-top: 56px;
}

@media screen and (max-width: 768px) {
  .main-body-container {
    padding-top: 40px;
    padding-bottom: 40px;
  }
}

.content-container {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.progress-container {
  display: flex;
  justify-content: center;
}

@media screen and (max-width: 768px) {
  .main-body-container {
    margin-left: 0%;
    margin-right: 0%;
  }
}

/* simple styling for keyword chips */
.advanced-controls {
  margin-top: 12px;
  display: flex;
  justify-content: flex-start;
}

.advanced-toggle {
  background-color: #eef3ff;
  color: #1b2a4e;
  border: 1px solid #c9d6ff;
  border-radius: 6px;
  padding: 8px 14px;
  font-size: 0.95rem;
  cursor: pointer;
  transition:
    background-color 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease;
}

.advanced-toggle:hover,
.advanced-toggle:focus {
  background-color: #e0e8ff;
  border-color: #b3c4ff;
}

.advanced-toggle:focus {
  outline: 3px solid rgba(36, 59, 114, 0.25);
  outline-offset: 2px;
}

.advanced-toggle[aria-expanded="true"] {
  background-color: #e0e8ff;
  border-color: #b3c4ff;
  color: #18264a;
}

.keyword-filter {
  margin-top: 12px;
}

.keyword-filter > * + * {
  margin-top: 16px;
}

.filter-actions {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.apply-filters {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background-color: #243b72;
  border: 1px solid #243b72;
  border-radius: 6px;
  color: #ffffff;
  cursor: pointer;
  transition:
    background-color 0.2s ease,
    border-color 0.2s ease;
}

.apply-filters:hover,
.apply-filters:focus {
  background-color: #1b2a4e;
  border-color: #1b2a4e;
}

.apply-filters:focus {
  outline: 3px solid rgba(36, 59, 114, 0.25);
  outline-offset: 2px;
}

.clear-filters {
  margin-top: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background-color: #ffffff;
  border: 1px solid #c9d6ff;
  border-radius: 6px;
  color: #1b2a4e;
  cursor: pointer;
  transition:
    background-color 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease;
}

.clear-filters:hover,
.clear-filters:focus {
  background-color: #e0e8ff;
  border-color: #b3c4ff;
}

.clear-filters:focus {
  outline: 3px solid rgba(36, 59, 114, 0.25);
  outline-offset: 2px;
}
</style>
