# Frontend and deployment

The Vue frontend is distributed as the standard custom element `<dlf-search-webcomponent>`. The production core image serves both its loader and the API, making the component easy to embed without a separate frontend service.

## Frontend composition

`src/dlf-search-webcomponent.ce.vue` owns the search workflow and composes focused UI components for the intro, search bar, progress, result documents, filter pickers, examples, and feedback. API access is isolated in `src/api/` services; TypeScript interfaces mirror backend request and response models.

At mount time the component loads:

- runtime feedback and example configuration from `/api/config`;
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

### Create a release

Merge the release changes into `main` and wait for the relevant CI checks to pass. The script always tags the selected remote's published `main` commit, regardless of your checked-out branch or local changes. After confirmation, it fetches that commit without changing your checkout. If remote `main` changed during the prompts, run the script again to review the updated commit.

The local helper requires only Python, Git, and your existing Git login with permission to push tags. No GitHub CLI or personal access token is required. Merge `.github/workflows/release-project.yml` and the updated script into `main` before the first bundled release. The local script pushes tags; GitHub Actions then publishes the release using its automatically provided `GITHUB_TOKEN` with `contents: write` and `actions: read` permissions.

From the repository root, run the interactive helper:

```bash
python scripts/release.py
```

The script asks whether to rebuild **both**, **core**, or **indexer**, then asks for a **patch**, **minor**, or **major** increment for the project release and selected components:

- **Patch**: bug fixes, e.g. `1.2.3` → `1.2.4`.
- **Minor**: backward-compatible features, e.g. `1.2.3` → `1.3.0`.
- **Major**: breaking changes, e.g. `1.2.3` → `2.0.0`.

Component versions are calculated independently from the highest stable `core-vX.Y.Z` and `indexer-vX.Y.Z` tags on the remote. The project gets its own `vX.Y.Z` version, calculated from stable project tags. Prerelease and unrelated tags are ignored; without a stable tag, the baseline is `0.0.0`. If you rebuild only one component, the other component's highest stable image version is reused. An existing release of that component is required; otherwise, select both images.

The script shows the commit, project version, component tags, and image names, then asks for confirmation. It creates annotated tags for the selected components and the project and pushes them together atomically. Unrelated tags are not pushed. Local tag collisions stop the release. The project tag annotation stores the bundle metadata for recovery.

To preview without creating or pushing tags, or to select a different configured remote:

```bash
python scripts/release.py --dry-run
python scripts/release.py --remote upstream
```

After pushing the tags, the local script prints the [GitHub Actions](https://github.com/it-at-m/Dienstleistungsfinder-KI/actions) link and exits. The project tag starts **Release project**, which waits for **Release core image** and **Release indexer image**, matching each image's exact tag and source commit. It also checks the original build of a reused image. Once both builds have succeeded, it creates one GitHub Release named **Dienstleistungsfinder KI vX.Y.Z**, lists both image versions and build links, and attaches `release.json` containing the bundle's versions and source commits. The packages remain separate in GHCR; the project release groups them into one documented bundle. Package version files are not changed.

The project workflow waits up to one hour for image builds. If an image workflow fails, rerun it in the GitHub Actions web interface and wait for success, then rerun **Release project** for the same project tag. Its annotation preserves the exact bundle, so no new version increment or tags are needed. The GitHub Release is created as a draft, the manifest is uploaded, and only then is it published. Rerunning the workflow can finish an existing draft and recognizes an already published release. If a local push fails, tags are retained and recovery commands are printed; inspect the remote before retrying.

To publish only a component image manually, create and push its tag, for example:

```bash
git tag -a core-v1.0.1 -m "Release core-v1.0.1"
git push origin refs/tags/core-v1.0.1:refs/tags/core-v1.0.1
```

Replace the example version with the next unused version. Use `indexer-vX.Y.Z` for an indexer release. Manual component tags trigger image builds but do not create a bundled GitHub Release.

## Production checklist

1. Use distinct least-privilege Qdrant credentials for the core and indexer.
2. Keep model and vector settings identical across both images.
3. Set a strong `DLF_SESSION_SECRET` and explicit `DLF_ALLOWED_ORIGINS`.
4. Disable `/docs` with `DLF_ENABLE_DOCS=false` if interactive API documentation is not intended publicly.
5. Configure health probes against `/api/healthz`.
6. Run and validate the indexer before routing users to a new collection.
7. Pin image digests and retain Qdrant snapshots for rollback.

Environment-specific OpenShift resources, schedules, secrets, and promotion rules are deliberately outside this public repository.
