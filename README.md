# recent hydrology-ML papers

[![Live site](https://img.shields.io/badge/live%20site-online-1572a1)](https://issamsouassi.github.io/recent-hydrology-ml-papers/)

A tiny static website that lists **recent papers at the intersection of
hydrology and AI / machine learning / deep learning**, bucketed into
*this week / this month / this year*. It pulls metadata from two free,
no-key sources and re-renders in the browser — no backend, no build step.

Maintained by **Issam Souassi**, University of Waterloo.
Inspired by [isogeni.es](https://isogeni.es/) and the
"recent post-quantum papers" site it is modeled on.

- **arXiv** — via the public [Atom API](https://info.arxiv.org/help/api/index.html)
  (categories `physics.ao-ph`, `physics.geo-ph`, `cs.LG`, `stat.ML`, `eess.SP`).
- **Crossref** — via the public [REST API](https://api.crossref.org/), which
  indexes journal articles **and preprints** across essentially every publisher
  (Water Resources Research, Journal of Hydrology, HESS, EGUsphere/Copernicus
  discussion papers, Environmental Modelling & Software, ...).

## How it works

```
scraper/scrape.py  ──>  papers_arxiv.txt
                   ──>  papers_crossref.txt
index.html  ──(fetch + render in the browser)──>  the page
```

The scraper keeps a paper only if its title/abstract looks like **hydrology
AND** like **AI/ML/DL** (see the keyword lists in `scraper/scrape.py`). It then
attaches finer-grained topic tags and writes one line per paper:

```
title;;;authors;;;id;;;date_class;;;repo;;;date;;;categories;;;link
```

| field        | meaning                                                        |
|--------------|----------------------------------------------------------------|
| `title`      | paper title                                                    |
| `authors`    | comma-separated author names                                   |
| `id`         | arXiv id (`2611.13346`) or DOI (`10.1016/j.jhydrol.2026.xxxx`) |
| `date_class` | `last_week` / `last_month` / `last_year`                       |
| `repo`       | a code URL (github/gitlab/zenodo/HF) if found, else `none`     |
| `date`       | `YYYY-MM-DD` (published / submitted date)                      |
| `categories` | comma-separated subset of the topic tags below                 |
| `link`       | canonical URL to the paper                                     |

### Topic tags

Every kept paper gets the broad `ml-hydrology` tag. On top of that it may also
get any of these narrower tags, which drive the on-page topic filter:

| tag                  | what it captures                                            |
|----------------------|-------------------------------------------------------------|
| `ml-hydrology`       | the broad field (all kept papers)                           |
| `deep-learning`      | neural nets, LSTMs/CNNs/transformers, PINNs, GNNs, ...       |
| `lstm`               | long short-term memory models specifically                  |
| `rainfall-runoff`    | rainfall-runoff / streamflow / discharge modeling           |
| `forecasting`        | forecasting, nowcasting, early warning, lead-time studies   |
| `regional-hydrology` | regionalization, large-sample, ungauged basins, CAMELS, PUB |

The page has two filter rows: **topic** (all / deep learning / LSTM /
rainfall-runoff / forecasting / regional) and **source** (all / arXiv /
Crossref), plus a **search box** that filters by title and author.

## Running the scraper

No third-party dependencies — Python 3.8+ standard library only.

```bash
python3 scraper/scrape.py                 # 400-day lookback (default)
python3 scraper/scrape.py --days 180      # shorter window
python3 scraper/scrape.py --skip-arxiv    # only refresh Crossref
python3 scraper/scrape.py --skip-crossref # only refresh arXiv
```

A full run takes a few minutes because both APIs are queried politely (with
short sleeps between pages).

## Viewing locally

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

A plain `file://` open will **not** work: the page fetches the `.txt` files,
which browsers block over `file://`.

## Tuning what gets included

Precision/recall is governed entirely by the keyword lists in
`scraper/scrape.py`:

- `HYDRO_CI` — case-insensitive hydrology phrases (gate 1).
- `ML_CI` / `ML_CS` — AI/ML phrases and **case-sensitive** acronyms (gate 2).
  A paper is kept only if it matches *both* gates.
- `TAG_*` lists — attach the finer-grained tags once a paper is kept.

Case-sensitive acronyms (`LSTM`, `CNN`, `GAN`, `AI`, ...) are matched with exact
capitalisation on purpose, so they don't collide with ordinary words.

To add a new niche (say, *water quality*):
1. Add its phrases to `HYDRO_CI` if not already covered.
2. Add a `TAG_WATER_QUALITY_CI` list and a branch in `classify()`.
3. Add the tag to `valid_tags`/styling in `index.html` (a `.tag-...` CSS rule
   and a `<span class="filter" data-cat="...">` in the topic filter row).

## Automatic updates

`.github/workflows/update.yml` re-runs the scraper every 6 hours and commits
the refreshed `.txt` files. You can also trigger it on demand from the repo's
**Actions** tab (it has `workflow_dispatch` enabled).

## Publishing to GitHub Pages (free)

You do **not** need to buy a domain. GitHub Pages serves the site for free at
`https://<your-username>.github.io/<repo-name>/`.

1. Create an empty repo on GitHub, e.g. `recent-hydrology-ml-papers`
   (Settings → do not add a README; this folder already has one).
2. From this folder:
   ```bash
   git init
   git add .
   git commit -m "initial commit: hydrology-ML papers site"
   git branch -M main
   git remote add origin https://github.com/<your-username>/recent-hydrology-ml-papers.git
   git push -u origin main
   ```
3. On GitHub: **Settings → Pages → Build and deployment → Source: Deploy from a
   branch**, branch `main`, folder `/ (root)`. Save.
4. Wait ~1 minute, then open `https://<your-username>.github.io/recent-hydrology-ml-papers/`.
5. (Optional) To use a custom domain later, buy one (~$10–15/yr), add a `CNAME`
   file containing just the domain, and point the domain's DNS at GitHub Pages.

The scheduled workflow keeps the data fresh automatically after the first push.

## Project layout

```
recent-hydrology-ml-papers/
├── index.html                     # the website (HTML + CSS + vanilla JS)
├── papers_arxiv.txt               # scraped data: arXiv
├── papers_crossref.txt            # scraped data: Crossref
├── robots.txt
├── scraper/
│   └── scrape.py                  # the harvester (stdlib only)
├── .github/workflows/update.yml   # 6-hourly auto-refresh
├── README.md                      # this file
└── AGENTS.md                      # orientation for AI coding assistants
```
