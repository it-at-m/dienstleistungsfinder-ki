<script setup lang="ts">
import type {
  FeedbackConfig,
  MailtoTemplateConfig,
} from "@/types/FeedbackConfig";

import { MucButton } from "@muenchen/muc-patternlab-vue";
import { computed } from "vue";

import FeedbackState from "@/types/FeedbackState";

const props = defineProps<{
  config: FeedbackConfig;
  query: string;
  runId: string;
}>();
const state = defineModel<FeedbackState>();
const emit = defineEmits<{
  score: [value: boolean];
}>();

const setState = (new_state: FeedbackState) => {
  state.value = new_state;
};

const isTemplateConfigured = (template?: MailtoTemplateConfig) => {
  return Boolean(template?.to && template?.subject && template?.body);
};

const buildMailBody = (baseBody: string) => {
  const contextLines = [
    "",
    "---- Kontext ----",
    props.runId && `Run ID: ${props.runId.replace(/-/g, "")}`,
    props.query && `Suchanfrage: ${props.query}`,
  ].filter(Boolean);

  const sanitizedBody = baseBody.trimEnd();
  return contextLines.length
    ? `${sanitizedBody}\n${contextLines.join("\n")}`
    : sanitizedBody;
};

const openMailClient = (template: MailtoTemplateConfig) => {
  if (!isTemplateConfigured(template)) {
    return;
  }
  const params = new URLSearchParams({
    subject: template.subject,
    body: buildMailBody(template.body),
  });
  const recipient = encodeURIComponent(template.to);
  window.location.href = `mailto:${recipient}?${params.toString()}`;
};

const positiveMailAvailable = computed(() =>
  isTemplateConfigured(props.config?.positive)
);
const negativeMailAvailable = computed(() =>
  isTemplateConfigured(props.config?.negative)
);

const handlePositiveFeedback = () => {
  setState(FeedbackState.POSITVE);
  emit("score", true);
};

const handleNegativeFeedback = () => {
  setState(FeedbackState.NEGATIVE);
  emit("score", false);
};

const openKIMuenchen = () => {
  window.open("https://ki.muenchen.de/ki-systeme/dlf", "_blank")?.focus();
};
</script>
<template>
  <div
    class="feedback-container"
    style="background-color: #e5eef5"
  >
    <div class="container">
      <div
        class="m-callout feedback-callout callout-margin"
        style="background-color: #ffffff"
      >
        <div class="m-callout__inner">
          <div class="m-callout__body">
            <div class="m-callout__body__inner">
              <div class="m-callout__headline">
                <h2>
                  <template v-if="state == FeedbackState.CONTEXTUAL">
                    Haben Sie eine passende Antwort erhalten?
                  </template>
                  <template v-else-if="state == FeedbackState.PENDING_SEARCH">
                    Lernen Sie unsere KI-Suche besser kennen!
                  </template>
                  <template v-else> Danke für Ihre Rückmeldung! </template>
                </h2>
              </div>

              <div class="m-callout__content">
                <template v-if="state == FeedbackState.PENDING_SEARCH">
                  <div>
                    <p class="docs-paragraph">
                      In einer Beta-Version testen wir aktuell eine Suche mit
                      Künstlicher Intelligenz. Wie das genau funktioniert,
                      erklären wir Ihnen auf unserer Dokumentations-Webseite.
                    </p>
                    <muc-button
                      variant="secondary"
                      class="open-extern-button"
                      icon="ext-link"
                      @click="openKIMuenchen()"
                    >
                      ki.muenchen.de besuchen
                    </muc-button>
                  </div>
                </template>
                <template v-else-if="state == FeedbackState.CONTEXTUAL">
                  <p>
                    Helfen Sie uns, unsere KI-Suche zu verbessern: Geben Sie uns
                    eine Rückmeldung! Haben Sie die richtige Antwort gefunden?
                  </p>
                </template>
                <template v-else-if="state == FeedbackState.POSITVE">
                  <p>
                    Schön, dass Ihnen unsere KI-Suche geholfen hat. Sie möchten
                    uns noch etwas mitteilen? Wir freuen uns über Ihr Feedback:
                  </p>
                </template>
                <template v-else>
                  <p>
                    Schade, dass die KI-Suche Ihre Erwartungen nicht erfüllt
                    hat. Ein genaueres Feedback hilft uns, das Problem zu
                    beheben:
                  </p>
                </template>
                <div
                  v-if="state != FeedbackState.PENDING_SEARCH"
                  class="action-group"
                >
                  <template v-if="state == FeedbackState.CONTEXTUAL">
                    <muc-button
                      variant="secondary"
                      class="feedback-button"
                      icon="thumb-up-outline"
                      @click="handlePositiveFeedback()"
                    >
                      Ja, ich bin zufrieden
                    </muc-button>
                    <muc-button
                      variant="secondary"
                      class="feedback-button"
                      icon="thumb-down-outline"
                      @click="handleNegativeFeedback()"
                    >
                      Nein, das geht besser
                    </muc-button>
                  </template>
                  <template v-else-if="state == FeedbackState.POSITVE">
                    <muc-button
                      v-if="positiveMailAvailable"
                      variant="secondary"
                      class="feedback-button"
                      icon="ext-link"
                      @click="() => openMailClient(config.positive)"
                    >
                      Feedback geben
                    </muc-button>
                    <p
                      v-else
                      class="feedback-hint"
                    >
                      Feedback-E-Mail ist aktuell nicht konfiguriert.
                    </p>
                  </template>
                  <template v-else-if="state == FeedbackState.NEGATIVE">
                    <muc-button
                      v-if="negativeMailAvailable"
                      variant="secondary"
                      class="feedback-button"
                      icon="ext-link"
                      @click="() => openMailClient(config.negative)"
                    >
                      Problem beschreiben
                    </muc-button>
                    <p
                      v-else
                      class="feedback-hint"
                    >
                      Problem-Feedback ist aktuell nicht verfügbar.
                    </p>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
<style scoped>
.feedback-container {
  padding-bottom: 40px;
  padding-top: 40px;
}

.feedback-button {
  margin-bottom: 0em;
}

.feedback-hint {
  color: var(--color-neutrals-grey, #3a5368);
  font-size: 0.9rem;
  margin: 0;
}

.callout-margin {
  margin-left: 20%;
  margin-right: 20%;
}

.m-callout__content ul li {
  padding-left: 0;
}

.feedback-callout {
  padding-top: 32px;
  margin-top: 0;
}

.open-extern-button {
  margin-top: 16px;
}

.docs-paragraph {
  margin-bottom: 16px;
}

.action-group {
  display: flex;
  justify-content: space-between;
  margin-top: 1.5em;
}

@media screen and (max-width: 768px) {
  .callout-margin {
    margin-left: 0%;
    margin-right: 0%;
  }

  .feedback-button {
    margin-bottom: 16px;
  }
}

@media (max-width: 768px) {
  .action-group {
    flex-direction: column;
  }
}
</style>
