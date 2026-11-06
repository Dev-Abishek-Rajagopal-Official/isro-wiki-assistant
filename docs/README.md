# docs – diagrams and screenshots

| Path | Content |
|---|---|
| `images/architecture.svg` | containers, data stores and external services |
| `images/agent-workflow.svg` | one question through the LangGraph agent (router → rewriter / MCP tools / generator → final) |
| `images/rag-pipeline.svg` | knowledge-base ingestion and hybrid retrieval |
| `images/setup-flow.svg` | what `setup.ps1` / `setup.sh` do, step by step |
| `screenshots/` | the UI walkthrough used in the main README, plus Qdrant, pgAdmin and the API docs |
| `capture_screenshots.py` | regenerates `screenshots/` by driving the running app with Playwright – also an end-to-end smoke test |

Regenerate the screenshots (stack running, admin account created with `scripts/create_admin.py`):

```bash
pip install playwright        # uses the installed Microsoft Edge; or: playwright install chromium + PW_CHANNEL=chromium
DEMO_EMAIL=you@example.com DEMO_PASSWORD=... ADMIN_EMAIL=... ADMIN_PASSWORD=... python docs/capture_screenshots.py --register
```

The diagrams are hand-written SVG – edit them as text.
