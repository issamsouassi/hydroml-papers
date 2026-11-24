# AGENTS.md — orientation for AI coding assistants

This file orients any AI assistant (Claude, Cursor, Copilot, Kiro, etc.)
working on this repository. Humans: see `README.md` for the user-facing guide.

## What this project is

A **dependency-free static website** that lists recent papers at the
intersection of **hydrology** and **AI/ML/DL**. There is no backend, no
database, and no build step. The browser fetches two plain-text data files and
renders them with vanilla JavaScript.

Maintainer: Issam Souassi, University of Waterloo.

## Architecture (the whole system in one picture)

```
scraper/scrape.py  ──writes──>  papers_arxiv.txt, papers_crossref.txt
index.html  ──fetch()──>  those .txt files  ──renders──>  the page
.github/workflows/update.yml  ──runs scrape.py every 6h, commits the .txt
```

Three moving parts, each independently editable:

1. **`scraper/scrape.py`** — Python 3.8+, **standard library only** (urllib,
   xml.etree, json, re). Harvests arXiv (Atom API) and Crossref (REST API),
   filters by keyword, and emits the `.txt` files. Do NOT add third-party
   dependencies: the GitHub Actions runner installs nothing.
2. **`index.html`** — a single self-contained file (inline CSS + inline JS).
   No framework, no bundler. Loads `papers_arxiv.txt` and `papers_crossref.txt`
   at runtime.
3. **`.github/workflows/update.yml`** — scheduled job that re-runs the scraper
   and commits refreshed data. Needs `permissions: contents: write`.

## The data contract (CRITICAL — keep both sides in sync)

Each line of `papers_arxiv.txt` / `papers_crossref.txt` is ONE paper with
exactly **8 fields** joined by the literal 3-char delimiter `;;;`:

```
title;;;authors;;;id;;;date_class;;;repo;;;date;;;categories;;;link
```

- Field order and count are a contract between `scrape.py` (`to_line()`) and
  `index.html` (`fetchPapers()` → `line.split(';;;')`, indices `v[0]`..`v[7]`).
- `date_class` ∈ {`last_week`, `last_month`, `last_year`}.
- `categories` is a comma-separated subset of the topic tags.
- The `;;;` delimiter is stripped from any field text by `clean()`.

**If you add, remove, or reorder a field, you MUST update BOTH files.**
After changing either side, re-validate (see "How to verify" below).

## Topic tags

`classify(text)` returns a set of tags, or empty set (= drop the paper).
A paper is kept only if it matches BOTH gates:
- gate 1 hydrology: `HYDRO_CI`
- gate 2 AI/ML/DL: `ML_CI` (case-insensitive) or `ML_CS` (case-sensitive)
...and is NOT caught by the exclusion gate `EXCLUDE_CI` (strong non-hydrology
domain signals like nuclear steam generators, plasma/battery "discharge", oil &
gas "reservoirs"). Add to `EXCLUDE_CI` when a false positive recurs from a
specific domain rather than loosening/tightening the hydro terms themselves.

The keyword lists were tuned against the maintainer's ~165-paper Zotero library
as a test fixture: ~76% recall on recent (2023+) genuine hydrology+ML papers
with 0 false positives on an unrelated wastewater/pharmacology cluster in the
same library. The remaining misses are out-of-scope by design (pure-ML
foundation papers, pure-hydrology dataset/review/metrics papers). Do NOT chase
100% recall by admitting generic words like "framework"/"benchmark" — that
blurs the ML focus and floods the feed. Named large-sample benchmark datasets
(CAMELS/Caravan/LamaH/HYSETS) count as ML-relevant on purpose, since they are
the infrastructure of ML-hydrology.

Kept papers always get `ml-hydrology`, plus any of:
`deep-learning`, `lstm`, `transformer`, `generative`, `rainfall-runoff`,
`forecasting`, `regional-hydrology`, `uncertainty`, `evaluation`, `extremes`
(each driven by a `TAG_*` list). The `uncertainty`, `evaluation`, `extremes`,
and `generative` tags were added because probabilistic forecasting, skill
metrics (NSE/KGE/CRPS), hydrological extremes (floods/low-flow), and generative
models (VAE/diffusion/flows) are top themes in the maintainer's library.
`lstm`, `transformer`, and `generative` are deep-learning method subsets;
generative-model terms also satisfy the ML gate (a diffusion/VAE/GAN paper is
unambiguously ML).

Case-sensitive lists (`ML_CS`, `TAG_DEEP_CS`, ...) exist so short acronyms
(`LSTM`, `CNN`, `GAN`, `AI`, `ML`, `DL`) don't match ordinary lowercase words.
Keep new acronyms case-sensitive; keep descriptive phrases case-insensitive.

To add a new topic tag end-to-end:
1. `scrape.py`: add a `TAG_<NAME>_CI/_CS` list + a branch in `classify()`.
2. `index.html`: add a `.tag-<name>` CSS rule and a
   `<span class="filter" data-cat="<name>">` in `#topic-filters`.
3. (optional) add the tag to the validator's `valid_tags` set.

## Source-specific notes (hard-won, don't regress these)

- **arXiv**: query is scoped by category AND hydrology-term AND ML-term; the
  regexes in `classify()` re-filter afterwards. Page with `start`/`max_results`,
  sorted by `submittedDate desc`; stop once a page's oldest item predates the
  lookback cutoff. Sleep ~3s between pages (arXiv asks for politeness).
- **Crossref**:
  - Use `query.bibliographic` with several FOCUSED two-word phrases, run
    separately and merged by DOI. A single broad `query` matches ~300k loosely
    related works ranked by relevance and is non-deterministic — avoid it.
  - Page with `offset` (NOT `cursor`) when using `sort=published`. Crossref
    returns HTTP 400 for `cursor` + `sort=published`; `offset` + sort works.
    Crossref caps `offset` around 10k; we stop at 2k per query as a safety valve.
  - Query BOTH `type:journal-article` AND `type:posted-content`. Preprints
    (EGUsphere/Copernicus HESS discussion papers, bioRxiv, Research Square,
    SSRN) are `posted-content`; without it they are silently dropped even when
    they match perfectly. Each query runs once per type.
  - Some preprints (notably Copernicus) expose no abstract to Crossref, so
    `classify()` sees title-only and may attach fewer fine-grained tags. This
    is a metadata limitation, not a bug — the paper still appears.
  - Dates: publishers often set only a future 'print' date (e.g. 2027-03) with
    no online date. `_crossref_date(item, now)` prefers true online dates and,
    when the best date is in the future, falls back to `created` (DOI
    registration) so recency is honest. It never returns a future date. Do NOT
    reintroduce "clamp future to today" — it dumped everything into last_week.
  - Set a real `mailto` (CONTACT_EMAIL) for Crossref's faster "polite pool".

## How to run

```bash
python3 scraper/scrape.py                 # full 400-day refresh
python3 scraper/scrape.py --days 30        # quick test window
python3 scraper/scrape.py --skip-crossref  # arXiv only
python3 scraper/scrape.py --skip-arxiv     # Crossref only
python3 -m http.server 8000                # preview at http://localhost:8000
```

## How to verify a change (do this before declaring done)

1. Run the scraper (a short `--days 30` run is fine for a smoke test).
2. Confirm the data still satisfies the 8-field contract. Quick check:
   ```bash
   awk -F';;;' 'NF!=8{print FILENAME":"NR" has "NF" fields"}' \
       papers_arxiv.txt papers_crossref.txt
   ```
   (no output = every line has 8 fields)
3. Spot-check a few titles are genuinely hydrology + ML (watch for false
   positives like non-hydrology uses of "discharge", or non-ML uses of "AI").
4. If you touched `index.html`, serve locally and confirm papers render in all
   three buckets and that each topic/source filter narrows the list.

## Conventions / guardrails

- Python stdlib only. No `requirements.txt`, no `pip install`.
- Keep `index.html` a single self-contained file (no external JS/CSS except
  the Google Fonts link).
- Be polite to the APIs: keep the inter-request sleeps.
- Don't commit huge data: the `.txt` files are small by design (one line/paper,
  ~1 year of papers). The workflow commits them; that's intended.
```
