#!/usr/bin/env bash
set -euo pipefail

: "${HF_TOKEN:?Set HF_TOKEN to an it-at-m token with dataset write access.}"

hf auth whoami

create_dataset() {
    local repository="$1"
    local card="$2"

    hf repos create "$repository" --type dataset --public --exist-ok
    hf upload "$repository" "$card" README.md --type dataset --commit-message "Add dataset card"
}

create_dataset "it-at-m/munich-city-services" "dataset_cards/munich-city-services.README.md"
create_dataset "it-at-m/munich-city-info" "dataset_cards/munich-city-info.README.md"
