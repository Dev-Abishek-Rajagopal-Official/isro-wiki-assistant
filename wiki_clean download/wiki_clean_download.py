"""
Download ISRO / Indian space programme Wikipedia articles as clean, RAG-ready Markdown.

Pipeline
  1. Walk the category tree (root categories below, depth 3 = whole tree) to collect titles.
  2. For each title fetch the *rendered* HTML (action=parse). Unlike plain-text extracts this
     keeps infoboxes (key facts: mass, launch date, rocket, orbit...) and tables.
  3. Clean the HTML -> Markdown:
       - drop citation markers, edit links, navboxes, hatnotes, maintenance banners, images
       - infobox      -> "## Key facts" bullet list, placed after the lead section
       - wikitables   -> Markdown tables (rowspan/colspan expanded)
       - headings     -> #/##/### (so the ingestion step can chunk by section)
       - drop "See also", "References", "External links"... and empty sections
       - normalise unicode and whitespace
  4. Save each article as soon as it is cleaned: one .md with a YAML front matter header
     (title, url, ids, ...) plus one appended row in wiki_metadata.csv. Nothing piles up in memory,
     and a stopped run resumes where it left off.
  5. Keyword pass: re-read the saved files one at a time and add TF-IDF keywords
     (terms frequent in the article but rare across the corpus) to each file and to the CSV.

Usage
    pip install -r requirements.txt
    python wiki_clean_download.py                              # full run (resumes if interrupted)
    python wiki_clean_download.py --fresh                      # start over
    python wiki_clean_download.py --titles "Chandrayaan-3" "GSAT-7" --out ../sample_docs

Content licence: Wikipedia text is CC BY-SA 4.0 - credit Wikipedia and keep the URLs/revision ids.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

API = "https://en.wikipedia.org/w/api.php"
# Wikipedia asks API clients to identify themselves; replace with your own contact.
HEADERS = {"User-Agent": "isro-rag-assignment/0.2 (contact: your-email@example.com)"}

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE.parent / "wiki documents"

ROOT_CATEGORIES = [
    "Category:Indian Space Research Organisation",
    "Category:Space programme of India",
    "Category:ISRO satellites",
    "Category:Satellites of India",
    "Category:Earth observation satellites of India",
    "Category:Space launch vehicles of India",
    "Category:Indian Space Research Organisation facilities",
]
SKIP_CATEGORY_PATTERNS = re.compile(
    r"(births|deaths|alumni|people from|stubs|images|templates|wikipedia)", re.IGNORECASE
)
# Pulled in by the category walk but not about the Indian space programme.
EXCLUDE_TITLES = {"SpaceX Crew-12"}

# Sections that only hold references / navigation, not answerable content.
DROP_SECTIONS = {
    "see also", "references", "notes", "external links", "further reading", "bibliography",
    "citations", "sources", "footnotes", "gallery", "notes and references", "references and notes",
    "explanatory notes", "works cited", "general references", "cited sources",
}
# HTML elements that are noise for retrieval.
NOISE_SELECTORS = ", ".join([
    "sup.reference", "sup.noprint", "span.mw-editsection", ".navbox", ".navbox-styles",
    ".vertical-navbox", ".hatnote", ".reflist", "ol.references", ".mw-references-wrap",
    "style", "script", "link", "meta", ".ambox", ".ombox", ".metadata", ".noprint", ".sidebar",
    ".thumb", "figure", ".gallery", ".mw-empty-elt", ".shortdescription", ".sistersitebox",
    ".portal", ".portalbox", ".side-box", ".navigation-not-searchable", ".toc", ".mw-cite-backlink",
    "span.Z3988", ".infobox-image", ".mw-kartographer-maplink",
])

session = requests.Session()
session.headers.update(HEADERS)


# --------------------------------------------------------------------------- API helpers
def api_get(params: dict) -> dict:
    params = {**params, "format": "json", "formatversion": "2"}
    for attempt in range(4):
        try:
            resp = session.get(API, params=params, timeout=60)
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError(f"API request failed: {params}")


def category_members(category: str):
    params = {"action": "query", "list": "categorymembers", "cmtitle": category,
              "cmtype": "page|subcat", "cmlimit": "500"}
    while True:
        data = api_get(params)
        for m in data.get("query", {}).get("categorymembers", []):
            yield m["title"], m["ns"]
        if "continue" not in data:
            break
        params.update(data["continue"])


def collect_titles(roots: list[str], max_depth: int) -> dict[str, str]:
    """Breadth-first category walk. Returns {article_title: category_it_was_found_in}."""
    articles: dict[str, str] = {}
    seen: set[str] = set()
    queue = [(c, 0) for c in roots]
    while queue:
        cat, depth = queue.pop(0)
        if cat in seen:
            continue
        seen.add(cat)
        for title, ns in category_members(cat):
            if ns == 0:
                articles.setdefault(title, cat)
            elif ns == 14 and depth < max_depth and not SKIP_CATEGORY_PATTERNS.search(title):
                queue.append((title, depth + 1))
        time.sleep(0.1)
    print(f"Walked {len(seen)} categories, found {len(articles)} articles")
    return articles


def fetch_parsed(title: str) -> dict | None:
    data = api_get({
        "action": "parse", "page": title, "redirects": "1",
        "prop": "text|revid|categories|properties|displaytitle",
        "disableeditsection": "1", "disablelimitreport": "1", "disabletoc": "1",
    })
    return data.get("parse")


def fetch_last_edited(pageids: list[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for i in range(0, len(pageids), 50):
        batch = pageids[i:i + 50]
        data = api_get({"action": "query", "pageids": "|".join(map(str, batch)),
                        "prop": "revisions", "rvprop": "timestamp"})
        for p in data.get("query", {}).get("pages", []):
            revs = p.get("revisions") or [{}]
            out[p["pageid"]] = revs[0].get("timestamp", "")
    return out


# --------------------------------------------------------------------------- text cleaning
def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("​", "").replace("﻿", "")
    text = re.sub(r"\[(?:\d+|[a-z]|citation needed|note \d+|clarification needed|when\?|who\?|"
                  r"according to whom\?|failed verification|dead link|better source needed)\]",
                  "", text, flags=re.I)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" +([,.;:!?)])", r"\1", text)
    text = re.sub(r"\( +", "(", text)
    text = re.sub(r"\(\s*[,;]?\s*\)", "", text)
    return text.strip()


def inline_text(el: Tag, br: str = " ") -> str:
    """Text of an element on ONE line. `br` is used for <br> and between list items
    (" " for prose, "; " inside table cells and infobox values)."""
    for b in el.find_all("br"):
        b.replace_with(br)
    if br != " ":
        for li in el.find_all("li"):
            li.append(br)
    # Math: use the TeX alt text instead of the rendered image/MathML.
    for m in el.select("span.mwe-math-element"):
        math = m.find("math")
        alt = (math.get("alttext") if math else "") or m.get_text("")
        alt = re.sub(r"^\{\\displaystyle\s*(.*)\}$", r"\1", alt.strip())
        m.replace_with(f" {alt} ")
    text = el.get_text("").replace("\n", br if br != " " else " ")
    text = norm(text)
    if br != " ":
        text = re.sub(r"(?:\s*;\s*){2,}", "; ", text).strip("; ")
    return text


def table_to_markdown(table: Tag) -> list[str]:
    """Convert an HTML table to Markdown, expanding rowspan/colspan into a full grid."""
    caption = table.find("caption")
    cap = inline_text(caption) if caption else ""
    grid: dict[tuple[int, int], str] = {}
    header_rows: set[int] = set()
    rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    for r, tr in enumerate(rows):
        c = 0
        cells = tr.find_all(["th", "td"], recursive=False)
        if cells and all(cell.name == "th" for cell in cells):
            header_rows.add(r)
        for cell in cells:
            while (r, c) in grid:
                c += 1
            txt = inline_text(cell, br="; ").replace("|", "/")
            try:
                rs = max(1, min(int(cell.get("rowspan", 1)), 200))
                cs = max(1, min(int(cell.get("colspan", 1)), 50))
            except ValueError:
                rs = cs = 1
            # rowspan: repeat the value down (each row must stand alone);
            # colspan: value only in the first column, so wide note rows are not duplicated.
            for dr in range(rs):
                for dc in range(cs):
                    grid[(r + dr, c + dc)] = txt if (dc == 0 or r in header_rows) else ""
            c += cs
    if not grid:
        return []
    n_rows = max(k[0] for k in grid) + 1
    n_cols = max(k[1] for k in grid) + 1
    matrix = [[grid.get((r, c), "") for c in range(n_cols)] for r in range(n_rows)]
    matrix = [row for row in matrix if any(cell for cell in row)]
    if len(matrix) < 2 or n_cols < 2:
        # Not really tabular data: return the text as a plain line.
        flat = " ".join(cell for row in matrix for cell in row if cell)
        return [flat] if flat else []
    # Merge leading header rows (multi-level headers) into one header row.
    n_head = 0
    while n_head < len(rows) and n_head in header_rows and n_head < len(matrix) - 1:
        n_head += 1
    n_head = max(n_head, 1)
    header = []
    for c in range(n_cols):
        parts: list[str] = []
        for r in range(n_head):
            if matrix[r][c] and matrix[r][c] not in parts:
                parts.append(matrix[r][c])
        header.append(" - ".join(parts) or f"Column {c + 1}")
    lines = [f"Table: {cap}"] if cap else []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * n_cols)
    for row in matrix[n_head:]:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def infobox_to_lines(box: Tag) -> list[str]:
    lines: list[str] = []
    for tr in box.find_all("tr"):
        if tr.find_parent("table") is not box:
            continue
        label = tr.find("th", class_="infobox-label") or (
            tr.find("th") if tr.find("td", class_="infobox-data") else None)
        data = tr.find("td", class_="infobox-data")
        header = tr.find(["th", "td"], class_="infobox-header")
        if label and data:
            lbl, val = inline_text(label), inline_text(data, br="; ")
            val = re.sub(r"(;\s*){2,}", "; ", val)
            val = re.sub(r",\s*;", ",", val).strip("; ")
            if lbl and val:
                lines.append(f"- {lbl}: {val}")
        elif header:
            h = inline_text(header)
            if h:
                lines.append(f"- **{h}**")
    # Drop section labels that ended up with no facts under them.
    cleaned = [l for i, l in enumerate(lines)
               if not (l.startswith("- **") and (i + 1 == len(lines) or lines[i + 1].startswith("- **")))]
    return cleaned


def list_to_lines(lst: Tag, depth: int = 0) -> list[str]:
    lines: list[str] = []
    for i, li in enumerate(lst.find_all("li", recursive=False), 1):
        nested = [n.extract() for n in li.find_all(["ul", "ol"], recursive=False)]
        txt = inline_text(li)
        bullet = f"{i}." if lst.name == "ol" else "-"
        if txt:
            lines.append(f"{'  ' * depth}{bullet} {txt}")
        for n in nested:
            lines.extend(list_to_lines(n, depth + 1))
    return lines


class Renderer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.skip_level = 0  # >0 while inside a dropped section
        self.tables = 0

    def heading(self, h: Tag) -> None:
        level = int(h.name[1])
        text = inline_text(h)
        if self.skip_level and level > self.skip_level:
            return
        self.skip_level = level if text.lower() in DROP_SECTIONS else 0
        if not self.skip_level and text:
            self.lines += ["", "#" * level + " " + text, ""]

    def walk(self, node: Tag) -> None:
        for child in list(node.children):
            if isinstance(child, NavigableString):
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name
            classes = child.get("class") or []
            if name in {"h2", "h3", "h4", "h5", "h6"}:
                self.heading(child)
                continue
            if "mw-heading" in classes:
                h = child.find(["h2", "h3", "h4", "h5", "h6"])
                if h:
                    self.heading(h)
                continue
            if self.skip_level:
                continue
            if name == "p":
                txt = inline_text(child)
                if txt:
                    self.lines += [txt, ""]
            elif name in {"ul", "ol"}:
                self.lines += list_to_lines(child) + [""]
            elif name == "dl":
                for item in child.find_all(["dt", "dd"], recursive=False):
                    txt = inline_text(item)
                    if txt:
                        self.lines.append(f"**{txt}**" if item.name == "dt" else txt)
                self.lines.append("")
            elif name == "blockquote":
                txt = inline_text(child)
                if txt:
                    self.lines += [f"> {txt}", ""]
            elif name == "table":
                md = table_to_markdown(child)
                if md:
                    self.tables += 1
                    self.lines += md + [""]
            else:
                self.walk(child)


def drop_empty_sections(lines: list[str]) -> list[str]:
    def level(l: str) -> int:
        m = re.match(r"^(#+) ", l)
        return len(m.group(1)) if m else 0

    out: list[str] = []
    for i, line in enumerate(lines):
        lv = level(line)
        if lv:
            nxt = next((l for l in lines[i + 1:] if l.strip()), None)
            if nxt is None or (level(nxt) and level(nxt) <= lv):
                continue
        out.append(line)
    return out


def html_to_markdown(html: str) -> tuple[str, list[str], int, list[str]]:
    """Returns (markdown body, infobox lines, table count, top-level section names)."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("div.mw-parser-output") or soup
    for el in root.select(NOISE_SELECTORS):
        el.decompose()
    # Hidden machine-readable spans (e.g. ISO dates in infoboxes) duplicate visible text.
    for el in root.select("[style]"):
        if re.search(r"display\s*:\s*none", el.get("style", ""), re.I):
            el.decompose()
    infobox: list[str] = []
    for box in root.select("table.infobox"):
        infobox += infobox_to_lines(box)
        box.decompose()
    r = Renderer()
    r.walk(root)
    lines = drop_empty_sections(r.lines)
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    sections = [l[3:] for l in lines if l.startswith("## ")]
    return body, infobox, r.tables, sections


# --------------------------------------------------------------------------- keywords
STOPWORDS = set("""
a about above after again against all also although am an and any are as at be because been before
being below between both but by can could did do does doing down during each either et few for from
further had has have having he her here hers him his how however i if in into is it its itself just
later may me might more most much must my no nor not now of off on once one only or other our out over
own per s same several she should since so some such than that the their them then there these they
this those through thus to too two under until up upon us very via was we were what when where which
while who whom whose why will with within without would yet you your first second third new used use
using including include includes based known called made make many well part three four five year years
became become kilograms kilogram kg km kilometres kilometers miles lb watts tonnes minutes utc ist
july june january february march april may august september october november december
""".split())


def tokens(text: str) -> list[str]:
    text = re.sub(r"^\|.*\|$", " ", text, flags=re.M)  # ignore table rows for keywords
    return re.findall(r"[a-z][a-z0-9\-]*[a-z0-9]", text.lower())


def keyword_candidates(text: str) -> Counter:
    toks = tokens(text)
    c: Counter = Counter()
    for i, t in enumerate(toks):
        if t in STOPWORDS or len(t) < 3:
            continue
        c[t] += 1
        if i + 1 < len(toks):
            nxt = toks[i + 1]
            if nxt not in STOPWORDS and len(nxt) >= 3:
                c[f"{t} {nxt}"] += 1
    return c


def pick_keywords(c: Counter, df: Counter, n_docs: int, top_n: int = 10) -> list[str]:
    """TF-IDF: terms frequent in this article but rare across the corpus."""
    scored = []
    for term, tf in c.items():
        if tf < 2:
            continue
        idf = math.log((1 + n_docs) / (1 + df[term])) + 1
        boost = 1.3 if " " in term else 1.0  # phrases are more descriptive
        scored.append(((1 + math.log(tf)) * idf * boost, term))
    chosen: list[str] = []
    for _, term in sorted(scored, reverse=True):
        if any(term in ch for ch in chosen):
            continue
        chosen.append(term)
        if len(chosen) == top_n:
            break
    return chosen


FRONT_MATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.S)


def prose_from_markdown(md: str) -> str:
    """Article text without front matter and without the Key facts block."""
    body = FRONT_MATTER_RE.sub("", md, count=1)
    return re.sub(r"^## Key facts\n.*?(?=^## |\Z)", "", body, flags=re.M | re.S)


# --------------------------------------------------------------------------- main
def safe_name(title: str) -> str:
    return re.sub(r"[^\w\-]+", "_", title).strip("_")[:120]


def yaml_front_matter(meta: dict) -> str:
    # JSON scalars/arrays are valid YAML, so json.dumps gives safe quoting.
    return "---\n" + "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()) + "\n---\n"


def build_document(title: str, found_in: str, parsed: dict) -> dict:
    body, infobox, n_tables, sections = html_to_markdown(parsed["text"])
    props = parsed.get("properties") or {}
    if isinstance(props, list):  # formatversion quirks
        props = {p.get("name"): p.get("*") or p.get("value") for p in props}
    real_title = parsed["title"]
    cats = [c["category"].replace("_", " ") for c in parsed.get("categories", []) if not c.get("hidden")]

    # Put Key facts after the lead section (before the first ## heading).
    if infobox:
        facts = "## Key facts\n\n" + "\n".join(infobox)
        m = re.search(r"^## ", body, flags=re.M)
        body = (body[:m.start()] + facts + "\n\n" + body[m.start():]) if m else body + "\n\n" + facts
        sections = ["Key facts"] + sections

    return {
        "title": real_title,
        "url": "https://en.wikipedia.org/wiki/" + quote(real_title.replace(" ", "_")),
        "pageid": parsed["pageid"],
        "revid": parsed.get("revid"),
        "short_description": props.get("wikibase-shortdesc", ""),
        "wikidata_id": props.get("wikibase_item", ""),
        "found_in_category": found_in.removeprefix("Category:"),
        "wikipedia_categories": cats,
        "requested_title": title,
        "body": body,
        "has_infobox": bool(infobox),
        "table_count": n_tables,
        "sections": sections,
    }


META_FIELDS = [
    "file_name", "title", "url", "short_description", "keywords", "found_in_category",
    "wikipedia_categories", "pageid", "revid", "wikidata_id", "last_edited", "word_count",
    "char_count", "section_count", "sections", "has_infobox", "table_count", "requested_title",
    "source", "license", "fetched_at",
]
SKIP_FIELDS = ["title", "reason"]
META_CSV = "wiki_metadata.csv"
SKIP_CSV = "_skipped.csv"


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def open_append(path: Path, fields: list[str]):
    """Open a CSV for appending (utf-8-sig so Excel reads it); write the header if new."""
    new = not path.exists() or path.stat().st_size == 0
    f = open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8")
    w = csv.DictWriter(f, fieldnames=fields)
    if new:
        w.writeheader()
    return f, w


def download(args, out: Path) -> None:
    """Pass 1: fetch, clean and save each article immediately (nothing kept in memory)."""
    meta_path, skip_path = out / META_CSV, out / SKIP_CSV

    # Resume: titles already saved or permanently skipped in a previous run are not fetched again.
    existing = read_csv(meta_path)
    done = {r["requested_title"] for r in existing}
    seen_ids = {int(r["pageid"]) for r in existing}
    done |= {r["title"] for r in read_csv(skip_path) if not r["reason"].startswith("error")}

    if args.titles:
        titles = {t: "(manual)" for t in args.titles}
    else:
        titles = collect_titles(ROOT_CATEGORIES, args.depth)
    for t in EXCLUDE_TITLES:
        titles.pop(t, None)
    items = sorted(titles.items())
    if args.limit:
        items = items[:args.limit]
    todo = [(t, c) for t, c in items if t not in done]
    print(f"{len(items)} titles, {len(items) - len(todo)} already done, {len(todo)} to fetch", flush=True)

    meta_f, meta_w = open_append(meta_path, META_FIELDS)
    skip_f, skip_w = open_append(skip_path, SKIP_FIELDS)
    saved = skipped = 0
    try:
        for i, (title, cat) in enumerate(todo, 1):
            reason = None
            try:
                parsed = fetch_parsed(title)
            except RuntimeError as e:
                parsed, reason = None, f"error: {e}"
            if parsed is None:
                reason = reason or "missing"
            elif parsed["pageid"] in seen_ids:
                reason = f"duplicate of {parsed['title']}"
            if reason:
                skip_w.writerow({"title": title, "reason": reason})
                skip_f.flush()
                skipped += 1
                print(f"[{i}/{len(todo)}] SKIP {title}: {reason}", flush=True)
                continue

            doc = build_document(title, cat, parsed)
            del parsed
            if len(doc["body"]) < args.min_chars:
                skip_w.writerow({"title": title, "reason": f"too short ({len(doc['body'])} chars)"})
                skip_f.flush()
                skipped += 1
                print(f"[{i}/{len(todo)}] SKIP {title}: too short", flush=True)
                continue

            last_edited = fetch_last_edited([doc["pageid"]]).get(doc["pageid"], "")
            fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fname = safe_name(doc["title"]) + ".md"
            front = {
                "title": doc["title"],
                "url": doc["url"],
                "pageid": doc["pageid"],
                "revid": doc["revid"],
                "last_edited": last_edited,
                "short_description": doc["short_description"],
                "wikidata_id": doc["wikidata_id"],
                "found_in_category": doc["found_in_category"],
                "wikipedia_categories": doc["wikipedia_categories"],
                "keywords": [],  # filled in by the keyword pass
                "source": "Wikipedia",
                "license": "CC BY-SA 4.0",
                "fetched_at": fetched_at,
            }
            header = f"# {doc['title']}\n\n"
            if doc["short_description"]:
                header += f"_{doc['short_description']}_\n\n"
            (out / fname).write_text(yaml_front_matter(front) + "\n" + header + doc["body"] + "\n",
                                     encoding="utf-8")
            meta_w.writerow({
                "file_name": fname,
                "title": doc["title"],
                "url": doc["url"],
                "short_description": doc["short_description"],
                "keywords": "",
                "found_in_category": doc["found_in_category"],
                "wikipedia_categories": "; ".join(doc["wikipedia_categories"]),
                "pageid": doc["pageid"],
                "revid": doc["revid"],
                "wikidata_id": doc["wikidata_id"],
                "last_edited": last_edited,
                "word_count": len(doc["body"].split()),
                "char_count": len(doc["body"]),
                "section_count": len(doc["sections"]),
                "sections": "; ".join(doc["sections"]),
                "has_infobox": doc["has_infobox"],
                "table_count": doc["table_count"],
                "requested_title": title,
                "source": "Wikipedia",
                "license": "CC BY-SA 4.0",
                "fetched_at": fetched_at,
            })
            meta_f.flush()
            seen_ids.add(doc["pageid"])
            saved += 1
            print(f"[{i}/{len(todo)}] saved {fname}  ({len(doc['body'])} chars, "
                  f"{doc['table_count']} tables)", flush=True)
            del doc
            time.sleep(args.sleep)
    finally:
        meta_f.close()
        skip_f.close()
    print(f"\nPass 1 done: {saved} saved, {skipped} skipped this run", flush=True)


def add_keywords(out: Path) -> None:
    """Pass 2: TF-IDF keywords. Reads the saved files from disk one at a time, twice:
    first to count in how many articles each term appears, then to score and write keywords."""
    meta_path = out / META_CSV
    rows = read_csv(meta_path)
    if not rows:
        return
    df: Counter = Counter()
    for r in rows:
        df.update(keyword_candidates(prose_from_markdown((out / r["file_name"]).read_text(encoding="utf-8"))).keys())
    for r in rows:
        path = out / r["file_name"]
        md = path.read_text(encoding="utf-8")
        kws = pick_keywords(keyword_candidates(prose_from_markdown(md)), df, len(rows))
        m = FRONT_MATTER_RE.match(md)
        line = "keywords: " + json.dumps(kws, ensure_ascii=False)
        front = re.sub(r"^keywords: .*$", lambda _: line, m.group(0), count=1, flags=re.M)
        path.write_text(front + md[m.end():], encoding="utf-8")
        r["keywords"] = "; ".join(kws)
    tmp = meta_path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=META_FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(meta_path)
    print(f"Pass 2 done: keywords added to {len(rows)} documents and {META_CSV}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depth", type=int, default=3, help="category depth (3 = whole tree)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--min-chars", type=int, default=500, help="skip articles shorter than this after cleaning")
    ap.add_argument("--titles", nargs="*", help="only these titles (for testing)")
    ap.add_argument("--limit", type=int, help="only the first N titles (for testing)")
    ap.add_argument("--sleep", type=float, default=0.1, help="pause between articles")
    ap.add_argument("--fresh", action="store_true", help="delete previous output instead of resuming")
    ap.add_argument("--keywords-only", action="store_true", help="only (re)compute keywords")
    args = ap.parse_args()

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    if args.fresh:
        for p in list(out.glob("*.md")) + [out / META_CSV, out / SKIP_CSV]:
            p.unlink(missing_ok=True)

    if not args.keywords_only:
        download(args, out)
    add_keywords(out)
    n = len(read_csv(out / META_CSV))
    print(f"\n{n} documents in {out} (metadata: {META_CSV}, skipped: {SKIP_CSV})")


if __name__ == "__main__":
    main()
