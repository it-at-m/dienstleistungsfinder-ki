# Frontend and deployment

The Vue frontend is distributed as the standard custom element `<dlf-search-webcomponent>`. The production core image serves both its loader and the API, making the component easy to embed without a separate frontend service.

## Frontend composition

`src/dlf-search-webcomponent.ce.vue` owns the search workflow and composes focused UI components for the intro, search bar, progress, result documents, filter pickers, examples, and feedback. API access is isolated in `src/api/` services; TypeScript interfaces mirror backend request and response models.

At mount time the component loads:

- runtime feedback, example, and scrubber configuration from `/api/config`;
- available filter values from `/api/keywords` and `/api/categories`.

A search can start from text, keyword filters, category filters, or a combination. `AbortController` cancels an in-flight request when a newer search begins. After retrieval, answer requests run per candidate and results appear incrementally.

## Embed the component

Build output includes a loader that imports the hashed component bundle:

```html
<script src="https://your-core.example/loader.js" type="module"></script>

<dlf-search-webcomponent></dlf-search-webcomponent>
```

Host pages can preconfigure comma-separated metadata filters:

```html
<dlf-search-webcomponent
  categories="Residence, Mobility"
  keywords="registration, appointment"
></dlf-search-webcomponent>
```

The component uses Shadow DOM through Vue's custom-element build. It imports the Munich design-system stylesheet and bundles icon sprites and component styles.

## Build modes

| Command in `core/frontend` | Result                                               |
| -------------------------- | ---------------------------------------------------- |
| `npm run dev`              | Vite development server on port 8082                 |
| `npm run build`            | Production web-component bundle in `dist/`           |
| `npm run buildlocal`       | Builds and copies assets into `core/backend/static/` |
| `npm run lint`             | ESLint and Prettier checks                           |

The post-build process generates `loader.js` with the actual hashed JavaScript filename, so embedding pages do not need to know Vite's asset hash.

## Core container

`core/Dockerfile` has two stages:

1. A Node 24 UBI image installs frontend dependencies, downloads the pinned design-system CSS, and runs the production build.
2. A minimal UBI image installs the Python backend with `uv`, copies the backend and built frontend, runs as UID 1001, exposes port 8080, and starts `python app.py`.

The indexer uses its own minimal UBI image and also runs as UID 1001. `/app/artifacts` is group-writable for OpenShift-compatible arbitrary-UID execution.

## Local orchestration

`compose.yaml` defines three services:

| Service   | Port | Persistence                | Start policy                    |
| --------- | ---- | -------------------------- | ------------------------------- |
| `qdrant`  | 6333 | Named volume `qdrant-data` | Normal                          |
| `core`    | 8080 | Stateless                  | Normal; depends on Qdrant       |
| `indexer` | none | Writes Qdrant              | Only with the `indexer` profile |

Proxy variables are accepted as image build arguments and runtime `NO_PROXY` includes Qdrant and localhost.

## CI and releases

Core CI checks the Python backend, lints and builds the frontend, and builds the combined container. Indexer CI runs Ruff, pytest, and an image build. The two applications release independently from semantic version tags:

| Git tag          | Published image                                          |
| ---------------- | -------------------------------------------------------- |
| `core-vX.Y.Z`    | `ghcr.io/it-at-m/dienstleistungsfinder-ki-core:X.Y.Z`    |
| `indexer-vX.Y.Z` | `ghcr.io/it-at-m/dienstleistungsfinder-ki-indexer:X.Y.Z` |

Release workflows also publish `sha-<commit>` tags, software bills of materials, and provenance attestations. Deployments should pin a reviewed semantic version and immutable digest rather than `latest`.

## Production checklist

1. Use distinct least-privilege Qdrant credentials for the core and indexer.
2. Keep model and vector settings identical across both images.
3. Set a strong `DLF_SESSION_SECRET` and explicit `DLF_ALLOWED_ORIGINS`.
4. Disable `/docs` with `DLF_ENABLE_DOCS=false` if interactive API documentation is not intended publicly.
5. Configure health probes against `/api/healthz`.
6. Run and validate the indexer before routing users to a new collection.
7. Pin image digests and retain Qdrant snapshots for rollback.

Environment-specific OpenShift resources, schedules, secrets, and promotion rules are deliberately outside this public repository.
