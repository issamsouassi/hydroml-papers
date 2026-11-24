#!/usr/bin/env python3
"""
Harvest recent papers at the intersection of hydrology and
AI / machine learning / deep learning, from two open metadata sources:

  * arXiv      -- via the public Atom API (no key required)
  * Crossref   -- via the public REST API (no key required), which indexes
                  journal articles across essentially every publisher
                  (Water Resources Research, Journal of Hydrology, HESS, ...).

Results are written to flat text files consumed by index.html.

Output format (one paper per line):

    title;;;authors;;;id;;;date_class;;;repo;;;date;;;categories;;;link

  - title       paper title (single line)
  - authors     comma-separated author names
  - id          arXiv id (2501.01234) or DOI (10.1029/....)
  - date_class  one of: last_week, last_month, last_year
  - repo        source-code URL if we could find one, else "none"
  - date        YYYY-MM-DD (announced / published date)
  - categories  comma-separated topic tags (see TOPICS below)
  - link        canonical URL to the paper

Run:
    python3 scrape.py                 # 400-day lookback (default)
    python3 scrape.py --days 180      # shorter window
    python3 scrape.py --skip-crossref # only refresh arXiv
    python3 scrape.py --skip-arxiv    # only refresh Crossref

No third-party dependencies -- Python 3.8+ standard library only.
"""

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works"

# arXiv subject classes where hydrology + ML work tends to appear.
ARXIV_CATEGORIES = [
    "physics.ao-ph",   # atmospheric & oceanic physics
    "physics.geo-ph",  # geophysics
    "cs.LG",           # machine learning
    "stat.ML",         # statistics / ML
    "eess.SP",         # signal processing
]

# Put a real contact e-mail here. Crossref gives faster, more reliable
# service to requests that identify themselves ("polite pool").
CONTACT_EMAIL = "isouassi@uwaterloo.ca"
USER_AGENT = (
    "recent-hydrology-ml-papers/1.0 "
    f"(hydrology + ML paper index; mailto:{CONTACT_EMAIL})"
)

# How far back to look, in days. Anything older than ~1 year is dropped
# because the front-end only has week/month/year buckets.
DEFAULT_LOOKBACK_DAYS = 400

# Rolling-window thresholds (in days) used to assign a date_class.
WEEK_DAYS = 7
MONTH_DAYS = 30
YEAR_DAYS = 365

# --------------------------------------------------------------------------
# Keyword / topic matching
# --------------------------------------------------------------------------
#
# A paper is KEPT only if it looks like hydrology AND like AI/ML/DL. On top of
# that broad gate we attach finer-grained tags (deep-learning, lstm,
# rainfall-runoff, forecasting, regional-hydrology) so the front-end can offer
# progressively more specific filters.
#
# Two helpers:
#   _ci(...)  case-insensitive  -- for descriptive multi-word phrases.
#   _cs(...)  case-sensitive    -- for short acronyms that collide with
#                                  ordinary words (LSTM, GAN, CNN, ...).


def _ci(*words):
    return [re.compile(w, re.IGNORECASE) for w in words]


def _cs(*words):
    return [re.compile(w) for w in words]


# ---- broad gate 1: is this hydrology? -----------------------------------
HYDRO_CI = _ci(
    r"hydrolog",                 # hydrology, hydrological, hydrologic
    r"\bstreamflow\b",
    r"\brunoff\b",
    r"rainfall[- ]runoff",
    r"\briver (flow|discharge|basin|network)",
    r"(stream|river|peak|flood|water|inflow|outflow|basin|catchment|annual|daily|mean)[- ]?discharge",
    r"discharge (predict|forecast|simulat|estimat|measurement|hydrograph|data|series|record)",
    r"catchment",
    r"\bwatershed",
    r"drainage basin",
    r"flood (forecast|predict|simulat|inundation|risk|mapping)",
    r"drought (forecast|predict|index|monitor)",
    r"soil moisture",
    r"groundwater",
    r"aquifer",
    r"evapotranspiration",
    r"snow(pack|melt|[- ]water equivalent)",
    r"precipitation (nowcast|forecast|estimat|downscal)",
    r"water (level|table|balance|quality|resources)",
    r"reservoir (inflow|operation|storage)",
    r"stage[- ]discharge",
    r"\bbaseflow\b",
    r"rating curve",
    r"water cycle",
    r"land surface model",
    # large-sample / regionalization vocabulary (common in ML-hydrology)
    r"ungauged (basin|catchment)",
    r"large[- ]sample hydrolog",
    r"regionali[sz]ation",
    r"prediction(s)? in ungauged basins",
    r"hydrological model",
    r"hydrologic(al)? (signature|process|model|simulation|prediction)",
    r"\bCAMELS\b",
    r"\bCaravan\b",
    r"\bhydrograph\b",
    r"low[- ]flow",
    r"high[- ]flow",
    r"peak flow",
    r"flow duration curve",
    r"nash[- ]sutcliffe",
    r"\bKGE\b",
    r"precipitation (target|product|record|dataset)",
)

# ---- broad gate 2: is this AI / ML / DL? --------------------------------
ML_CI = _ci(
    r"machine learning",
    r"deep learning",
    r"neural network",
    r"artificial intelligence",
    r"data[- ]driven model",
    r"surrogate model",
    r"transfer learning",
    r"foundation model",
    r"physics[- ]informed",      # PINNs
    r"graph neural",
    r"reinforcement learning",
    r"gradient boost",
    r"random forest",
    r"support vector",
    r"gaussian process",
    r"ensemble learning",
    r"generative model",
    r"explainable (ai|artificial intelligence)",
    # modern / probabilistic ML vocabulary seen in hydrology-ML work
    r"diffusion model",
    r"state[- ]space model",
    r"mixture[- ]of[- ]experts",
    r"\bemulator\b",
    r"probabilistic (forecast|prediction|model)",
    r"deep generative",
    r"data[- ]driven (model|approach|method|prediction|framework)",
    r"attention mechanism",
    r"encoder[- ]decoder",
    r"autoencoder",
    # named large-sample benchmark datasets: these exist specifically as the
    # training/benchmark infrastructure for ML-hydrology, so a hydrology paper
    # centered on one is in scope even if it doesn't say "machine learning".
    r"\bCAMELS\b",
    r"\bCaravan\b",
    r"\bLamaH\b",
    r"\bHYSETS\b",
)
ML_CS = _cs(
    r"\bLSTM\b",
    r"\bGRU\b",
    r"\bCNN\b",
    r"\bRNN\b",
    r"\bGAN\b",
    r"\bGNN\b",
    r"\bMLP\b",
    r"\bXGBoost\b",
    r"\bLightGBM\b",
    r"\bTransformer\b",
    r"\bPINN(s)?\b",
    r"\bML\b",
    r"\bDL\b",
    r"\bAI\b",
    r"\bRF\b",
    r"\bSVM\b",
    r"\bSOM\b",
    r"\bELM\b",
)

# ---- fine-grained tags (attached when the broad gate already passed) -----
TAG_DEEP_CI = _ci(
    r"deep learning",
    r"neural network",
    r"physics[- ]informed",
    r"graph neural",
    r"attention mechanism",
    r"encoder[- ]decoder",
    r"autoencoder",
    r"generative model",
)
TAG_DEEP_CS = _cs(
    r"\bLSTM\b", r"\bGRU\b", r"\bCNN\b", r"\bRNN\b", r"\bGAN\b",
    r"\bGNN\b", r"\bTransformer\b", r"\bPINN(s)?\b", r"\bDL\b",
)

TAG_LSTM_CI = _ci(r"long short[- ]term memory")
TAG_LSTM_CS = _cs(r"\bLSTM\b")

TAG_RAINFALL_RUNOFF_CI = _ci(
    r"rainfall[- ]runoff",
    r"\brunoff (model|predict|simulat|generat)",
    r"streamflow (predict|simulat|generat|model)",
    r"discharge (predict|simulat|model)",
)

TAG_FORECAST_CI = _ci(
    r"forecast",
    r"nowcast",
    r"prediction",
    r"early warning",
    r"lead[- ]time",
)

TAG_REGIONAL_CI = _ci(
    r"regional(i[sz]ation| hydrolog| model)",
    r"large[- ]sample",
    r"ungauged (basin|catchment)",
    r"\bPUB\b",                      # Prediction in Ungauged Basins
    r"\bCAMELS\b",
    r"multi[- ](basin|catchment)",
    r"continental[- ]scale",
    r"spatial transferability",
    r"cross[- ](basin|catchment|region)",
)

# uncertainty / probabilistic prediction (a major theme in the maintainer's
# library: probabilistic streamflow forecasting, ensembles, quantiles, PIs).
TAG_UNCERTAINTY_CI = _ci(
    r"uncertaint",                   # uncertainty, uncertainties
    r"probabilistic",
    r"\bensemble (forecast|predict|member|mean|spread|kalman)",
    r"quantile (regression|loss|forecast)",
    r"prediction interval",
    r"confidence interval",
    r"bayesian",
    r"conformal prediction",
    r"predictive distribution",
    r"credible interval",
    r"aleatoric|epistemic",
)

# model evaluation / skill metrics / benchmarking (NSE, KGE, scoring rules,
# large-sample benchmarks — also heavily represented in the library).
TAG_EVALUATION_CI = _ci(
    r"nash[- ]sutcliffe",
    r"\bbenchmark",
    r"model (evaluation|performance|diagnostic|intercomparison)",
    r"scoring rule",
    r"\bCRPS\b",
    r"skill score",
    r"performance metric",
    r"evaluation (metric|framework|guideline)",
    r"calibration and validation",
)
TAG_EVALUATION_CS = _cs(
    r"\bNSE\b",
    r"\bKGE\b",
    r"\bRMSE\b",
    r"\bMAE\b",
)

# hydrological extremes: floods, extreme events, low-flow/droughts-as-extreme,
# flood-frequency analysis (16% of the maintainer's library — the largest
# previously-unfiltered theme).
TAG_EXTREMES_CI = _ci(
    r"extreme (event|flow|value|precipitat|rainfall|hydrolog|discharge)",
    r"\bflood\b",
    r"flood (forecast|predict|frequency|risk|inundation|mapping|event)",
    r"flash flood",
    r"low[- ]flow",
    r"peak flow",
    r"high[- ]flow",
    r"frequency analysis",
    r"return period",
    r"extreme value",
    r"heavy (rainfall|precipitation)",
)

# ---- exclusion gate: strong non-hydrology domain signals -----------------
# Some hydro terms ("water level", "discharge", "reservoir", "basin") are
# heavily reused in unrelated engineering fields. If the text shows a strong
# signal from one of those domains, drop it even if a weak hydro term matched.
# Examples this catches: nuclear steam-generator water-level control, plasma
# "discharge", battery "discharge", oil/gas "reservoirs".
EXCLUDE_CI = _ci(
    r"steam generator",
    r"nuclear (reactor|power plant|fuel)",
    r"\breactor core\b",
    r"dielectric (barrier )?discharge",
    r"plasma discharge",
    r"gas discharge",
    r"electrostatic discharge",
    r"partial discharge",             # high-voltage insulation
    r"battery (discharge|charging|state of charge)",
    r"capacitor",
    r"supercapacitor",
    r"oil (and|&) gas reservoir",
    r"petroleum reservoir",
    r"hydrocarbon reservoir",
    r"combustion chamber",
    r"blood (flow|pressure)",
    r"cash flow",
    r"traffic flow",
    r"water[- ]cooled",               # cooling systems, not hydrology
    # crop / plant pathology: these use "soil moisture", "leaf wetness" etc. as
    # minor features but are agronomy, not hydrology.
    r"crop disease",
    r"plant disease",
    r"disease (risk|incidence|severity|detection|classification) .{0,30}(crop|plant|leaf|tomato|pepper|wheat|maize|rice|vine)",
    r"leaf wetness",
    r"pest (detection|management|infestation)",
    r"plant patholog",
    # seismology / earthquake: may list "rainfall/hydrology/groundwater" as
    # incidental input parameters but are not hydrology papers.
    r"earthquake (forecast|predict|early warning|magnitude|catalog)",
    r"\bseismicit",
    r"seismic hazard",
    r"ground motion",
    r"\btectonic",
    r"fault (rupture|slip|geometry|zone)",
)

GITHUB_RE = re.compile(
    r"https?://(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org|zenodo\.org|huggingface\.co)/[^\s)\]\}<>\"']+",
    re.IGNORECASE,
)


def _matches(text, *pattern_lists):
    for patterns in pattern_lists:
        if any(p.search(text) for p in patterns):
            return True
    return False


def classify(text):
    """
    Return the set of topic tags for `text`, or an empty set if the paper
    does not pass the broad hydrology-AND-ML gate.
    """
    is_hydro = _matches(text, HYDRO_CI)
    is_ml = _matches(text, ML_CI, ML_CS)
    if not (is_hydro and is_ml):
        return set()
    # Drop papers with a strong non-hydrology domain signal (nuclear steam
    # generators, plasma/battery "discharge", oil & gas "reservoirs", ...).
    if _matches(text, EXCLUDE_CI):
        return set()

    tags = {"ml-hydrology"}  # broad bucket: everything that passed the gate
    if _matches(text, TAG_DEEP_CI, TAG_DEEP_CS):
        tags.add("deep-learning")
    if _matches(text, TAG_LSTM_CI, TAG_LSTM_CS):
        tags.add("lstm")
    if _matches(text, TAG_RAINFALL_RUNOFF_CI):
        tags.add("rainfall-runoff")
    if _matches(text, TAG_FORECAST_CI):
        tags.add("forecasting")
    if _matches(text, TAG_REGIONAL_CI):
        tags.add("regional-hydrology")
    if _matches(text, TAG_UNCERTAINTY_CI):
        tags.add("uncertainty")
    if _matches(text, TAG_EVALUATION_CI, TAG_EVALUATION_CS):
        tags.add("evaluation")
    if _matches(text, TAG_EXTREMES_CI):
        tags.add("extremes")
    return tags


def find_repo(text):
    m = GITHUB_RE.search(text or "")
    if not m:
        return "none"
    return m.group(0).rstrip(".,);]")


def date_class_for(date, now):
    age = (now - date).days
    if age < 0:
        age = 0
    if age <= WEEK_DAYS:
        return "last_week"
    if age <= MONTH_DAYS:
        return "last_month"
    if age <= YEAR_DAYS:
        return "last_year"
    return None


def clean(text):
    """Collapse whitespace, unescape HTML, and strip the ;;; delimiter."""
    if not text:
        return ""
    text = html.unescape(text)
    text = text.replace(";;;", "; ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# --------------------------------------------------------------------------
# HTTP helper
# --------------------------------------------------------------------------

def http_get(url, retries=5):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_err = e
            # Back off harder on rate limiting; honor Retry-After if present.
            if e.code == 429:
                retry_after = e.headers.get("Retry-After")
                try:
                    wait = int(retry_after)
                except (TypeError, ValueError):
                    wait = 10 * (attempt + 1)
                time.sleep(wait)
            else:
                time.sleep(2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001 - network flakiness, retry
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} tries: {url}\n{last_err}")


# --------------------------------------------------------------------------
# arXiv
# --------------------------------------------------------------------------

ATOM_NS = {"a": "http://www.w3.org/2005/Atom",
           "arxiv": "http://arxiv.org/schemas/atom"}


def arxiv_query_string():
    """Broad OR-joined keyword query, scoped to relevant categories.
    The regexes in classify() re-filter the results afterwards."""
    hydro_terms = [
        "hydrology", "streamflow", "rainfall-runoff", "runoff",
        "river discharge", "catchment", "watershed", "flood forecasting",
        "drought", "soil moisture", "groundwater", "evapotranspiration",
        "snowmelt", "precipitation forecasting", "water resources",
    ]
    ml_terms = [
        "machine learning", "deep learning", "neural network",
        "LSTM", "transformer", "physics-informed", "data-driven",
    ]
    hydro_q = " OR ".join(f'abs:"{t}"' for t in hydro_terms)
    ml_q = " OR ".join(f'abs:"{t}"' for t in ml_terms)
    cat_q = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    return f"({cat_q}) AND ({hydro_q}) AND ({ml_q})"


def fetch_arxiv(now, lookback_days):
    cutoff = now - dt.timedelta(days=lookback_days)
    search = arxiv_query_string()
    papers = {}
    start = 0
    page = 100
    while True:
        params = {
            "search_query": search,
            "start": start,
            "max_results": page,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = ARXIV_API + "?" + urllib.parse.urlencode(params)
        xml = http_get(url)
        root = ET.fromstring(xml)
        entries = root.findall("a:entry", ATOM_NS)
        if not entries:
            break
        oldest_on_page = None
        for e in entries:
            pub = e.findtext("a:published", default="", namespaces=ATOM_NS)
            try:
                pdate = dt.datetime.strptime(pub[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            oldest_on_page = (pdate if oldest_on_page is None
                              else min(oldest_on_page, pdate))

            raw_id = e.findtext("a:id", default="", namespaces=ATOM_NS)
            m = re.search(r"abs/([^v]+?)(v\d+)?$", raw_id)
            if not m:
                continue
            aid = m.group(1)

            title = clean(e.findtext("a:title", default="", namespaces=ATOM_NS))
            summary = clean(e.findtext("a:summary", default="", namespaces=ATOM_NS))
            comment = clean(e.findtext("arxiv:comment", default="", namespaces=ATOM_NS))

            cats = classify(title + " " + summary)
            if not cats:
                continue

            repo = find_repo(summary + " " + comment)
            authors = [clean(a.findtext("a:name", default="", namespaces=ATOM_NS))
                       for a in e.findall("a:author", ATOM_NS)]

            papers[aid] = {
                "title": title,
                "authors": [a for a in authors if a],
                "id": aid,
                "repo": repo,
                "date": pdate,
                "cats": cats,
                "link": f"https://arxiv.org/abs/{aid}",
            }

        start += page
        if oldest_on_page is not None and oldest_on_page < cutoff:
            break
        if start > 5000:  # safety valve
            break
        time.sleep(3)  # be polite to the arXiv API
    return list(papers.values())


# --------------------------------------------------------------------------
# Crossref
# --------------------------------------------------------------------------

def _crossref_date(item, now):
    """Pick the most relevant, non-future date from a Crossref item.

    Publishers often set only a 'print' date far in the future (e.g. 2027-03)
    with no online date. Using that would push the paper into the wrong recency
    bucket. So we:
      1. prefer true online/issued dates;
      2. if the best available date is in the future, fall back to 'created'
         (when Crossref first registered the record), which reflects real
         recency;
      3. never return a future date.
    Returns a date, or None if nothing usable.
    """
    def parse(key):
        node = item.get(key)
        if not node or not node.get("date-parts"):
            return None
        parts = node["date-parts"][0]
        if not parts:
            return None
        y = parts[0]
        m = parts[1] if len(parts) > 1 else 1
        d = parts[2] if len(parts) > 2 else 1
        try:
            return dt.date(int(y), int(m), int(d))
        except (ValueError, TypeError):
            return None

    created = parse("created")
    for key in ("published-online", "published", "issued", "published-print"):
        cand = parse(key)
        if cand is None:
            continue
        if cand <= now:
            return cand
        # candidate is in the future: prefer 'created' as the real signal
        if created is not None and created <= now:
            return created
        return now  # last resort: no better info than "around now"
    # no issue/print date at all -> fall back to created
    if created is not None:
        return min(created, now)
    return None


def fetch_crossref(now, lookback_days):
    cutoff = now - dt.timedelta(days=lookback_days)
    # Targeted bibliographic queries. Each is run separately, sorted by
    # publication date (newest first), and paged until we cross the cutoff.
    # Using focused two-word phrases keeps Crossref's relevance ranking tight
    # instead of scanning the ~300k loosely-matching works that a single broad
    # query returns. Results are merged by DOI, then re-filtered by classify().
    queries = [
        "hydrology deep learning",
        "hydrology machine learning",
        "streamflow deep learning",
        "rainfall runoff neural network",
        "flood forecasting machine learning",
        "soil moisture deep learning",
        "groundwater machine learning",
        "drought forecasting deep learning",
        "LSTM streamflow",
        "precipitation nowcasting deep learning",
        "evapotranspiration machine learning",
        "snowmelt runoff machine learning",
    ]
    select = ("DOI,title,author,abstract,issued,published,"
              "published-online,published-print,created,URL")
    # Crossref 'type' values we accept. 'journal-article' is published papers;
    # 'posted-content' is preprints (EGUsphere/Copernicus, bioRxiv, Research
    # Square, SSRN, ...). Without 'posted-content', preprints like the EGUsphere
    # HESS discussion papers never show up even when they match perfectly.
    types = ["journal-article", "posted-content"]
    papers = {}
    for query in queries:
        for work_type in types:
            offset = 0
            rows = 100
            done = False
            while not done:
                params = {
                    "query.bibliographic": query,
                    "filter": (f"from-pub-date:{cutoff.isoformat()},"
                               f"type:{work_type}"),
                    "sort": "published",
                    "order": "desc",
                    "rows": rows,
                    "offset": offset,
                    "select": select,
                    "mailto": CONTACT_EMAIL,
                }
                url = CROSSREF_API + "?" + urllib.parse.urlencode(params)
                raw = http_get(url)
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    break
                message = data.get("message", {})
                items = message.get("items", [])
                if not items:
                    break

                oldest_on_page = None
                for item in items:
                    titles = item.get("title") or []
                    title = clean(titles[0]) if titles else ""
                    if not title:
                        continue
                    abstract = clean(item.get("abstract", ""))

                    pdate = _crossref_date(item, now)
                    if pdate is None:
                        continue
                    oldest_on_page = (pdate if oldest_on_page is None
                                      else min(oldest_on_page, pdate))

                    doi = item.get("DOI", "")
                    if not doi or doi in papers:
                        continue

                    cats = classify(title + " " + abstract)
                    if not cats:
                        continue

                    authors = []
                    for a in item.get("author", []) or []:
                        name = " ".join(p for p in (a.get("given"), a.get("family")) if p)
                        if name:
                            authors.append(clean(name))

                    repo = find_repo(abstract)
                    papers[doi] = {
                        "title": title,
                        "authors": authors,
                        "id": doi,
                        "repo": repo,
                        "date": pdate,
                        "cats": cats,
                        "link": item.get("URL", f"https://doi.org/{doi}"),
                    }

                offset += rows
                if len(items) < rows:
                    done = True          # last page for this query/type
                # Date-sorted descending: once a page's oldest item predates
                # the cutoff, later pages are all older too -- stop.
                if oldest_on_page is not None and oldest_on_page < cutoff:
                    done = True
                if offset >= 2000:        # safety valve (Crossref caps offset)
                    done = True
                time.sleep(1)  # be polite to Crossref
    return list(papers.values())


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def to_line(p, now):
    dclass = date_class_for(p["date"], now)
    if dclass is None:
        return None
    fields = [
        p["title"],
        ", ".join(p["authors"]),
        p["id"],
        dclass,
        p["repo"],
        p["date"].isoformat(),
        ",".join(sorted(p["cats"])),
        p["link"],
    ]
    return ";;;".join(fields)


def write_file(path, papers, now):
    papers = sorted(papers, key=lambda p: p["date"], reverse=True)
    lines = []
    for p in papers:
        line = to_line(p, now)
        if line:
            lines.append(line)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        if lines:
            f.write("\n")
    return len(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS,
                    help="lookback window in days (default: %(default)s)")
    ap.add_argument("--arxiv-out", default="papers_arxiv.txt")
    ap.add_argument("--crossref-out", default="papers_crossref.txt")
    ap.add_argument("--skip-arxiv", action="store_true")
    ap.add_argument("--skip-crossref", action="store_true")
    args = ap.parse_args()

    now = dt.date.today()

    if not args.skip_crossref:
        print("Harvesting Crossref (REST API)...", file=sys.stderr)
        crossref = fetch_crossref(now, args.days)
        n = write_file(args.crossref_out, crossref, now)
        print(f"  wrote {n} Crossref papers -> {args.crossref_out}", file=sys.stderr)

    if not args.skip_arxiv:
        print("Harvesting arXiv (Atom API)...", file=sys.stderr)
        arxiv = fetch_arxiv(now, args.days)
        n = write_file(args.arxiv_out, arxiv, now)
        print(f"  wrote {n} arXiv papers -> {args.arxiv_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
