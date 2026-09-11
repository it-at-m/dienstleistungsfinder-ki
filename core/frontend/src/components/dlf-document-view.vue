<script setup lang="ts">
/* eslint-disable vue/no-v-html */
import type DLFAnswer from "@/types/DLFAnswer";

import MarkdownIt from "markdown-it";
import { computed } from "vue";

const markdown = new MarkdownIt({
  html: true, // Erlaubt HTML im Markdown
});

// Anpassen der Überschriften mit einem Plugin
markdown.renderer.rules.heading_open = (tokens, idx, options, env, self) => {
  const token = tokens[idx];
  if (!token) return "";
  const level = token.tag; // h1, h2, etc.
  // Decrease heading level by 1 (e.g., h1 -> h2, h2 -> h3)
  const currentLevel = parseInt(level.substring(1));
  const newLevel = Math.min(currentLevel + 2, 6); // Ensure it doesn't go beyond h6
  return `<h${newLevel}>`;
};

markdown.renderer.rules.heading_close = (tokens, idx, options, env, self) => {
  const token = tokens[idx];
  if (!token) return "";
  const level = token.tag; // h1, h2, etc.
  // Decrease heading level by 1 (e.g., h1 -> h2, h2 -> h3)
  const currentLevel = parseInt(level.substring(1));
  const newLevel = Math.min(currentLevel + 2, 6); // Ensure it doesn't go beyond h6
  return `</h${newLevel}>`;
};

const props = defineProps<{
  dlfDoc: DLFAnswer;
  headerPrefix: string;
  showOrginalText: boolean;
}>();

// Render markdown to HTML. The input comes from the backend and is
// processed via MarkdownIt with controlled options; this HTML is then
// injected via v-html below.
const genMarkdown = (text: string) => {
  return markdown.render(text);
};

const text = computed(() =>
  genMarkdown("**Originaltext:** " + props.dlfDoc.answer_text)
);
const ai_response = computed(() =>
  props.dlfDoc.ai_response ? genMarkdown(props.dlfDoc.ai_response) : ""
);
</script>

<template>
  <div>
    <div
      :class="
        showOrginalText
          ? 'm-dataset-item__inner mobile-ordering-normal'
          : 'm-dataset-item__inner mobile-ordering-ai'
      "
    >
      <h3 class="m-dataset-item__headline headline">
        <a
          class="doc_link"
          :href="dlfDoc.doc_url"
          target="_blank"
          :aria-label="dlfDoc.doc_base_name"
          >{{ dlfDoc.doc_base_name }}</a
        >
      </h3>
      <!--
        Intentionally rendering trusted markdown output as HTML.
        eslint-disable-next-line vue/no-v-html
      -->
      <div
        v-if="showOrginalText"
        class="marked_text m-dataset-item__text"
        aria-label="Zitat relevanter Text"
        v-html="text"
      />
      <!--
        Intentionally rendering AI response markdown output as HTML.
        eslint-disable-next-line vue/no-v-html
      -->
      <div
        v-else
        class="ai_response"
        v-html="ai_response"
      />
    </div>
  </div>
</template>

<style scoped>
@media screen and (max-width: 768px) {
  .mobile-ordering-ai {
    flex-direction: column-reverse;
  }

  .mobile-ordering-normal {
    flex-direction: column;
  }
}

.doc_link {
  text-decoration: none;
}

.doc_link:hover {
  text-decoration: underline;
}

.marked_text {
  margin: 0;
  padding: 16px;
}

.headline {
  margin-bottom: 0px;
  padding-bottom: 16px;
}

.ai_response {
  margin: 0;
  padding: 16px;
  background-color: #e5eef5;
  border-radius: 10px;
  width: 100%;
}

:deep(.ai_response > ul) {
  list-style-type: "> ";
  padding-left: 20px;
}

:deep(.ai_response > ul > li > ul) {
  list-style-type: circle;
}

:deep(.marked_text > ul) {
  list-style-type: "> ";
  padding-left: 20px;
}

:deep(.marked_text > ul > li > ul) {
  list-style-type: circle;
}
</style>
