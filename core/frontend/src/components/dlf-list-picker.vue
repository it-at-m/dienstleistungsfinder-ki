<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

const props = defineProps<{
  label: string;
  items: string[];
  placeholder?: string;
  addButtonLabel?: string;
  addButtonAriaLabel?: string;
}>();

const emit = defineEmits<{
  (event: "item-selected", value: string): void;
  (event: "item-removed", value: string): void;
}>();

const selectedItems = defineModel<string[]>({ default: () => [] });

const draft = ref<string>("");
const isAdding = ref<boolean>(false);
const showSuggestions = ref<boolean>(false);
const errorMessage = ref<string>("");
const inputRef = ref<HTMLInputElement | null>(null);
let hideTimer: ReturnType<typeof setTimeout> | undefined;

const addAriaLabel = computed(() => {
  if (props.addButtonAriaLabel) {
    return props.addButtonAriaLabel;
  }
  return `${props.label} hinzufügen`;
});

const placeholderText = computed(() => props.placeholder ?? "Eintrag eingeben");

const availableItems = computed(() => {
  const lowerSelected = new Set(
    selectedItems.value.map((item) => item.toLowerCase())
  );
  return props.items.filter((item) => !lowerSelected.has(item.toLowerCase()));
});

const filteredSuggestions = computed(() => {
  const query = draft.value.trim().toLowerCase();
  const pool = availableItems.value;
  if (!query) {
    return pool.slice(0, 100);
  }
  return pool
    .filter((item) => item.toLowerCase().includes(query))
    .slice(0, 100);
});

watch(
  () => props.items,
  () => {
    if (!props.items.length) {
      resetInput();
    }
  }
);

function beginAdd() {
  if (!availableItems.value.length) {
    return;
  }
  isAdding.value = true;
  draft.value = "";
  errorMessage.value = "";
  showSuggestions.value = false;
  nextTick(() => inputRef.value?.focus());
}

function cancelAdd() {
  resetInput();
}

function resetInput() {
  isAdding.value = false;
  draft.value = "";
  errorMessage.value = "";
  showSuggestions.value = false;
  if (hideTimer !== undefined) {
    clearTimeout(hideTimer);
    hideTimer = undefined;
  }
}

function onInput() {
  errorMessage.value = "";
  showSuggestions.value = filteredSuggestions.value.length > 0;
}

function onFocus() {
  showSuggestions.value = filteredSuggestions.value.length > 0;
}

function onBlur() {
  hideTimer = setTimeout(() => {
    showSuggestions.value = false;
    hideTimer = undefined;
  }, 100);
}

function addItem(value: string) {
  if (!value) {
    return;
  }
  if (selectedItems.value.includes(value)) {
    errorMessage.value = "Eintrag wurde bereits hinzugefügt.";
    return;
  }
  selectedItems.value = [...selectedItems.value, value];
  emit("item-selected", value);
  resetInput();
}

function onEnter() {
  if (!filteredSuggestions.value.length) {
    errorMessage.value = "Bitte wählen Sie einen vorhandenen Eintrag aus.";
    return;
  }
  const firstItem = filteredSuggestions.value[0];
  if (firstItem) {
    addItem(firstItem);
  }
}

function removeItem(index: number) {
  const removed = selectedItems.value[index];
  selectedItems.value = selectedItems.value.filter((_, i) => i !== index);
  if (removed !== undefined) {
    emit("item-removed", removed);
  }
}

onBeforeUnmount(() => {
  if (hideTimer !== undefined) {
    clearTimeout(hideTimer);
  }
});
</script>

<template>
  <div class="list-picker">
    <label class="list-picker__label">{{ label }}</label>
    <div class="list-picker__chips">
      <span
        v-for="(item, index) in selectedItems"
        :key="item + index"
        class="list-picker__chip"
      >
        <span class="list-picker__chip-text">{{ item }}</span>
        <button
          type="button"
          class="list-picker__chip-remove"
          :aria-label="`${item} entfernen`"
          title="Entfernen"
          @click="removeItem(index)"
        >
          ×
        </button>
      </span>
      <button
        v-if="!isAdding"
        type="button"
        class="list-picker__add"
        :disabled="!availableItems.length"
        :aria-label="addAriaLabel"
        :title="addButtonLabel ?? addAriaLabel"
        @click="beginAdd"
      >
        +
      </button>
      <div
        v-else
        class="list-picker__input-wrapper"
      >
        <input
          ref="inputRef"
          v-model="draft"
          class="list-picker__input"
          :placeholder="placeholderText"
          :aria-expanded="showSuggestions ? 'true' : 'false'"
          :aria-label="placeholderText"
          @input="onInput"
          @focus="onFocus"
          @blur="onBlur"
          @keydown.enter.prevent="onEnter"
          @keydown.esc.prevent="cancelAdd"
        />
        <div
          v-if="showSuggestions && filteredSuggestions.length"
          class="list-picker__suggestions"
          role="listbox"
        >
          <button
            v-for="suggestion in filteredSuggestions"
            :key="suggestion"
            type="button"
            class="list-picker__suggestion"
            role="option"
            @mousedown.prevent="addItem(suggestion)"
          >
            {{ suggestion }}
          </button>
        </div>
      </div>
    </div>
    <div
      v-if="errorMessage"
      class="list-picker__error"
      role="alert"
    >
      {{ errorMessage }}
    </div>
  </div>
</template>

<style scoped>
.list-picker {
  display: flex;
  flex-direction: column;
}

.list-picker__label {
  display: block;
  font-size: 0.95rem;
  margin-bottom: 6px;
}

.list-picker__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.list-picker__chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: #eef3ff;
  border: 1px solid #c9d6ff;
  border-radius: 14px;
  color: #1b2a4e;
}

.list-picker__chip-text {
  line-height: 1.4;
}

.list-picker__chip-remove {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  color: #1b2a4e;
}

.list-picker__add {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: #eef3ff;
  border: 1px solid #c9d6ff;
  border-radius: 50%;
  color: #1b2a4e;
  font-size: 20px;
  cursor: pointer;
  transition:
    background-color 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease;
}

.list-picker__add:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.list-picker__add:not(:disabled):hover,
.list-picker__add:not(:disabled):focus {
  background: #e0e8ff;
  border-color: #b3c4ff;
}

.list-picker__add:focus {
  outline: 3px solid rgba(36, 59, 114, 0.25);
  outline-offset: 2px;
}

.list-picker__input-wrapper {
  position: relative;
}

.list-picker__input {
  min-width: 200px;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid #c7c7c7;
}

.list-picker__suggestions {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 10;
  background: #fff;
  border: 1px solid #c7c7c7;
  border-top: none;
  max-height: 220px;
  overflow-y: auto;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.list-picker__suggestion {
  width: 100%;
  text-align: left;
  padding: 8px 10px;
  background: #fff;
  border: none;
  border-bottom: 1px solid #eee;
  cursor: pointer;
}

.list-picker__suggestion:hover {
  background: #f5f7ff;
}

.list-picker__error {
  color: #a40000;
  font-size: 0.9rem;
  margin-top: 4px;
}
</style>
