# wiki documents – the corpus

468 English Wikipedia articles about ISRO and the Indian space programme, cleaned into Markdown by
`../wiki_clean download/wiki_clean_download.py`. This folder is the input of the knowledge base
(`../isro rag/build_knowledge_base.py`).

| File | Content |
|---|---|
| `<Article_title>.md` | one article: YAML front matter (title, url, pageid, **revid**, last_edited, short description, Wikidata id, categories, TF-IDF keywords, licence, fetched_at), then the article as Markdown – lead, a **"Key facts"** list built from the infobox, `##` sections, and tables as Markdown tables |
| `wiki_metadata.csv` | one row per article: the same metadata plus word / section / table counts – the setup script checks every row has its file before indexing |
| `skipped_articles.csv` | titles found in the category crawl but skipped (too short after cleaning, duplicates) |

## Updating

The articles are committed, so a fresh setup does not need to call Wikipedia. To fetch new articles set
`WIKI_DOWNLOAD=true` in `.env` (or run `setup.ps1 -DownloadWiki` / `setup.sh --download-wiki`). The download
resumes: titles already saved are not fetched again, only new ones. The knowledge base is then re-chunked and
re-indexed automatically (unchanged chunks reuse cached embeddings).

## Licence

Wikipedia text is licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
Each file keeps its source URL and revision id; answers in the app cite and link the article they used.
Content © Wikipedia contributors.
