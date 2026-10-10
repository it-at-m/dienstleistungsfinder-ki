# Hugging Face Dataset Setup

The indexer can export transformed, vector-free documents to these public Hugging Face datasets:

- `it-at-m/munich-city-services`
- `it-at-m/munich-city-info`

Both datasets use the CC BY 4.0 license. Confirm that the source content may be published under this license before provisioning or exporting data.

## One-Time Provisioning

Install and authenticate the current Hugging Face CLI with an `it-at-m` account that can create and write dataset repositories. Prefer the `HF_TOKEN` environment variable instead of passing a token on the command line.

From `indexer/`, run:

```shell
HF_TOKEN=... bash scripts/create_hf_datasets.sh
```

The script verifies authentication, creates the two public dataset repositories if needed, and uploads the versioned dataset cards from `dataset_cards/`. It is idempotent, but must be run deliberately; the indexer itself never creates repositories or updates their README files.

## Runtime Access

Give the token used by the scheduled indexer job write access to both repositories. Set `HF_TOKEN` and `HF_DATASET_EXPORT_ENABLED=true` in the job's secret configuration. Do not commit tokens to `.env` files.

Before enabling the job, check both repository cards, source attribution, visibility, and organization access controls in Hugging Face.
