# VODUM documentation

Source for the [VODUM documentation website](https://nexius2.github.io/vodum-docs/),
published from [Nexius2/vodum-docs](https://github.com/Nexius2/vodum-docs).
The application lives in [Nexius2/VODUM](https://github.com/Nexius2/VODUM).

## Preview locally

Run these commands from the documentation root (this folder, or the root of the
standalone documentation repository):

```bash
python -m venv .venv
# Activate the virtual environment for your shell, then:
python -m pip install -r requirements.txt
python -m mkdocs serve
```

Open the local URL printed by MkDocs. The dependency versions are those used to
validate this theme. No external font service is required.

## Build and validate

```bash
python -m mkdocs build --strict --clean
```

The generated site is in `site/`. Do not commit generated output or virtual
environments. The previous `servers`, `libraries`, `mailing` and `discord` pages
remain as links to their replacement guides so existing bookmarks still work.

## Theme and content

- `mkdocs.yml`: navigation, search, dark/light mode and repository links.
- `docs/assets/stylesheets/extra.css`: VODUM slate surfaces and indigo accents.
- `docs/assets/images/vodum.png`: the application's existing icon.
- `docs/`: guides, technical references and recent feature overview.

Guides retain their existing English language. Describe the behavior implemented
in VODUM and mark experimental features and limits explicitly. A local source
change is not a claim that the feature is deployed on every installation.

## Publish

The GitHub Pages workflow builds and deploys on pushes to `main` in the standalone
`vodum-docs` repository, or when manually dispatched there. It installs the same
requirements and uses strict compilation before uploading the site artifact.

When maintaining this folder inside the VODUM application checkout, transfer its
contents to the documentation repository root, preserving `.github/workflows`,
`docs`, `requirements.txt` and `mkdocs.yml`. It is not a separate Git checkout here;
pushing the parent VODUM repository does not publish this documentation repository.
