# wiki_clean download – Wikipedia downloader and cleaner

`wiki_clean_download.py` builds `../wiki documents/` from the free MediaWiki API.

1. **Crawl** 7 root categories (Indian Space Research Organisation, Space programme of India, ISRO satellites,
   Satellites of India, Earth observation satellites of India, Space launch vehicles of India, ISRO facilities)
   breadth-first to depth 3 (the whole tree), with a cycle guard and an off-topic filter (births, alumni,
   stubs …). 487 titles → 468 articles kept.
2. **Fetch** the rendered HTML of each article (`action=parse`) – unlike plain-text extracts it keeps the
   infobox and tables.
3. **Clean** to Markdown: drop citation markers, navboxes, hatnotes, images and reference sections; infobox →
   "Key facts" list; wikitables → Markdown tables (rowspan / colspan expanded); headings kept for chunking.
4. **Save one article at a time** (front matter + Markdown, one CSV row) – low memory, and an interrupted run
   resumes where it stopped.
5. **Keywords**: TF-IDF pass over the saved files, written to each file and to the CSV.

## Run

From the repo root, via the setup script (`WIKI_DOWNLOAD=true`) or directly:

```bash
docker compose --profile jobs run --rm wiki
```

Standalone:

```bash
pip install -r requirements.txt
python wiki_clean_download.py                                   # full run, resumes, only new titles
python wiki_clean_download.py --titles "Chandrayaan-3" --out ../sample_docs   # try a few articles
python wiki_clean_download.py --fresh                           # start over
```

Wikimedia asks API clients for a contact in the User-Agent: set `WIKI_CONTACT` (a URL or email).
