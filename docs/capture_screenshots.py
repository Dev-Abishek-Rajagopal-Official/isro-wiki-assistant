"""
Walk through the running app like a user and save the README screenshots to docs/screenshots/.
Doubles as an end-to-end smoke test: it fails if any step of the UI does not work.

Needs the stack running (setup.ps1 / setup.sh) and Playwright:
    pip install playwright            # uses the installed Microsoft Edge (or: playwright install chromium)

    DEMO_EMAIL=... DEMO_PASSWORD=... ADMIN_EMAIL=... ADMIN_PASSWORD=... python docs/capture_screenshots.py
        --register   create the demo user first (otherwise it signs in)
        --flows      run only some parts: user, voice, admin, mobile, consoles (default: all)
        --only 20-   save only shots whose name starts with these prefixes (e.g. "20-,21-")

Voice: Chromium plays docs/assets/voice-question.wav as the microphone (--use-file-for-fake-audio-capture).

The admin email must be in ADMIN_EMAILS and the account created with scripts/create_admin.py.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

OUT = Path(__file__).resolve().parent / "screenshots"
APP = os.getenv("APP_URL", "http://localhost:3000")
API = os.getenv("API_URL", "http://localhost:8000")
QDRANT = os.getenv("QDRANT_DASHBOARD", "http://localhost:6333/dashboard")
PGADMIN = os.getenv("PGADMIN_URL", "http://localhost:5050")
RUN_TIMEOUT = 240_000  # ms, one agent run

Q1 = "Which rocket launched Chandrayaan-3, and what were the mission's main objectives?"
Q2 = "Is Cartosat-3 still in orbit today, and which rocket launched it?"
Q_OOS = "Who commanded NASA's Apollo 11 mission?"
Q_MANY = "List all ISRO launches from 2021 till today as a table with date, rocket, payload and outcome."
# Spoken question fed to the browser as its microphone (Chromium fake capture): "When is ISRO's next launch,
# and what will it carry?"
VOICE_WAV = Path(__file__).resolve().parent / "assets" / "voice-question.wav"


class Shots:
    def __init__(self, only: list[str] | None):
        self.only = only
        OUT.mkdir(parents=True, exist_ok=True)

    def want(self, name: str) -> bool:
        return not self.only or any(name.startswith(p) for p in self.only)

    def take(self, page: Page, name: str, settle: float = 0.8) -> None:
        if not self.want(name):
            return
        time.sleep(settle)  # let charts / transitions finish
        page.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=82)
        print(f"  saved {name}.jpg", flush=True)


def wait_run_done(page: Page) -> None:
    """A run is finished when no 'Working on it…' indicator is left on the page."""
    page.wait_for_function("() => !document.body.innerText.includes('Working on it')", timeout=RUN_TIMEOUT)
    time.sleep(1.5)


def ask(page: Page, question: str) -> None:
    box = page.get_by_label("Your question")
    box.fill(question)
    page.get_by_role("button", name="Send").click()
    expect(page.get_by_text("Working on it").first).to_be_visible(timeout=30_000)


def open_last_steps(page: Page) -> None:
    page.get_by_text(re.compile(r"^\d+ steps · ")).last.click()
    time.sleep(0.5)


def sign_in(page: Page, email: str, password: str) -> None:
    page.goto(f"{APP}/login")
    page.locator("input[type=email]").fill(email)
    page.locator("input[type=password]").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(re.compile(r"^(?!.*/login).*$"), timeout=20_000)


def voice_and_many_agents(page: Page, shots: Shots) -> None:
    """08a: a question asked by voice (speech-to-text step); 08b/08c: a question needing three agents."""
    if not (shots.want("08a") or shots.want("08b") or shots.want("08c")):
        return
    page.get_by_role("button", name="New conversation").click()
    expect(page.get_by_text("what would you like to know")).to_be_visible(timeout=20_000)
    if shots.want("08a"):
        page.get_by_role("button", name="Ask by voice").click()
        expect(page.get_by_text("Recording…")).to_be_visible(timeout=10_000)
        time.sleep(5)                                   # the WAV is ~3.5 s; Chromium plays it as the microphone
        page.get_by_role("button", name="Stop recording and send").click()
        expect(page.get_by_text("Working on it").first).to_be_visible(timeout=30_000)
        wait_run_done(page)
        open_last_steps(page)
        shots.take(page, "08a-voice-question")
    ask(page, Q_MANY)
    wait_run_done(page)
    open_last_steps(page)
    page.get_by_text(re.compile(r"^\d+ steps · ")).last.scroll_into_view_if_needed()
    page.mouse.move(860, 450)
    page.mouse.wheel(0, -200)
    shots.take(page, "08b-three-agents")
    tables = page.locator("main table")
    if tables.count():
        tables.last.scroll_into_view_if_needed()
    else:                                              # the model chose a list - show the answer instead
        page.get_by_text("Run details").last.scroll_into_view_if_needed()
        page.mouse.wheel(0, 500)
    shots.take(page, "08c-launch-table")
    page.get_by_text("Run details").last.click()
    shots.take(page, "08d-run-details-summary")
    page.get_by_role("tab", name="AgentState").click()
    shots.take(page, "08e-run-details-agentstate")
    page.keyboard.press("Escape")
    usage_shots(page, shots)


def usage_shots(page: Page, shots: Shots) -> None:
    page.get_by_role("link", name="My usage").click()
    expect(page.get_by_text("Questions asked and AI tokens used")).to_be_visible(timeout=20_000)
    shots.take(page, "13-usage", settle=2)
    page.get_by_role("button", name="LLM role").click()
    shots.take(page, "13b-usage-by-role", settle=2)


def user_flow(page: Page, shots: Shots, email: str, password: str, register: bool) -> str:
    if register:
        page.goto(f"{APP}/register")
        page.locator("input:not([type=email]):not([type=password])").first.fill("Priya Sharma")
        page.locator("input[type=email]").fill(email)
        page.locator("input[type=password]").fill(password)
        shots.take(page, "01-sign-up")
        page.get_by_role("button", name="Create account").click()
        page.wait_for_url(re.compile(r"^(?!.*/register).*$"), timeout=20_000)
    else:
        sign_in(page, email, password)
    expect(page.get_by_text("what would you like to know")).to_be_visible(timeout=20_000)
    shots.take(page, "02-welcome")

    # 1st question: knowledge base
    ask(page, Q1)
    expect(page.get_by_text(re.compile(r"passages? found")).first).to_be_visible(timeout=RUN_TIMEOUT)
    shots.take(page, "03-live-steps", settle=0.3)
    wait_run_done(page)
    shots.take(page, "04-answer-citations")
    thread_url = page.url

    open_last_steps(page)
    page.locator("button", has_text=re.compile(r"^Knowledge base")).last.click()
    page.get_by_role("tab", name=re.compile("Tool calls")).click()
    shots.take(page, "05-step-tool-calls")
    page.get_by_role("tab", name=re.compile("LLM calls")).click()
    shots.take(page, "06-step-llm-calls")
    page.keyboard.press("Escape")
    page.get_by_text("Run details").last.click()
    shots.take(page, "07-run-details")
    page.keyboard.press("Escape")

    # follow-up needing two sources (knowledge base + CelesTrak)
    ask(page, Q2)
    wait_run_done(page)
    open_last_steps(page)
    shots.take(page, "08-multi-agent")

    # out of scope, in a new conversation
    page.get_by_role("button", name="New conversation").click()
    expect(page.get_by_text("what would you like to know")).to_be_visible(timeout=20_000)
    ask(page, Q_OOS)
    wait_run_done(page)
    shots.take(page, "09-out-of-scope")

    # sidebar: back to the first conversation, add a thread, show the options menu
    page.goto(thread_url)
    page.wait_for_load_state("networkidle")
    page.get_by_text("New thread").first.click()
    time.sleep(1.5)
    page.get_by_label("Conversation options").nth(1).click()   # the first conversation is now 2nd in the list
    shots.take(page, "10-sidebar")
    page.keyboard.press("Escape")

    # history of the first thread
    page.goto(thread_url)
    page.wait_for_load_state("networkidle")
    page.get_by_role("link", name="History").click()
    expect(page.get_by_text("Thread history")).to_be_visible(timeout=20_000)
    shots.take(page, "11-history-steps", settle=1.5)
    page.get_by_role("button", name="AgentState timeline").click()
    shots.take(page, "12-history-agentstate", settle=1.5)

    usage_shots(page, shots)
    return thread_url


def admin_flow(page: Page, shots: Shots, email: str, password: str) -> None:
    page.evaluate("localStorage.clear()")
    sign_in(page, email, password)
    page.goto(f"{APP}/admin")
    expect(page.get_by_text("System-wide analytics")).to_be_visible(timeout=20_000)
    shots.take(page, "14-admin-overview", settle=2.5)
    for tab, name in [("Agents & routes", "15-admin-agents"), ("Tools (MCP)", "16-admin-tools")]:
        page.get_by_role("tab", name=tab).click()
        shots.take(page, name, settle=2)
    page.get_by_role("tab", name="Users").click()
    page.get_by_text("Priya Sharma").first.click()
    shots.take(page, "17-admin-users", settle=2.5)
    page.keyboard.press("Escape")
    page.get_by_role("tab", name="System").click()
    shots.take(page, "18-admin-system", settle=2)


def mobile_flow(browser, shots: Shots, email: str, password: str, thread_url: str) -> None:
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                              is_mobile=True, has_touch=True)
    page = ctx.new_page()
    sign_in(page, email, password)
    page.goto(thread_url)
    page.wait_for_load_state("networkidle")
    shots.take(page, "19-mobile", settle=2)
    ctx.close()


def pgadmin_llm_calls(page: Page) -> None:
    """Expand the pre-registered server down to its tables (the password comes from the mounted pgpass) and
    show the table list (no row data, so nothing sensitive)."""
    page.goto(PGADMIN)
    expect(page.get_by_text(re.compile(r"^Servers( \(\d+\))?$")).first).to_be_visible(timeout=60_000)
    time.sleep(2)                                      # pgAdmin restores tree + tabs asynchronously
    # pgAdmin (desktop mode) restores the tabs left open last time - close data / query tabs first
    for _ in range(10):
        open_tabs = page.get_by_role("tab", name=re.compile(r"@isro-postgres"))
        if not open_tabs.count():
            break
        open_tabs.first.get_by_role("button", name="Close").click()
        time.sleep(0.5)
        for answer in ("Don't save", "Yes"):          # unsaved-changes prompt, if any
            if page.get_by_role("button", name=answer).count():
                page.get_by_role("button", name=answer).first.click()
    path = ["ISRO assistant", "isro-postgres", "Databases", "isro_agent", "Schemas", "public", "Tables"]
    def item(text: str):                               # visible tree label (hidden panels reuse names)
        return page.get_by_text(re.compile(rf"^{re.escape(text)}( \(\d+\))?$")).filter(visible=True).first

    for node, child in zip(path, path[1:] + ["llm_calls"]):
        if item(child).count():
            continue                                 # already expanded (pgAdmin remembers its tree)
        # click the node's expand arrow (left of icon + label); a disconnected server only connects on the first
        # click (password from the mounted pgpass, no prompt), so retry until its children appear
        for _ in range(4):
            box = item(node).bounding_box()
            page.mouse.click(box["x"] - 32, box["y"] + box["height"] / 2)
            try:
                item(child).wait_for(timeout=8_000)
                break
            except Exception:  # noqa: BLE001
                continue
        item(child).wait_for(timeout=5_000)
    item("Tables").click()                             # select the node: Properties lists every table
    page.get_by_role("tab", name=re.compile(r"^Properties")).first.click()
    expect(page.get_by_text("llm_calls").filter(visible=True).first).to_be_visible(timeout=20_000)


def consoles_flow(page: Page, shots: Shots) -> None:
    page.goto(f"{QDRANT}#/collections")
    expect(page.get_by_text("isro_chunks").first).to_be_visible(timeout=20_000)
    shots.take(page, "20-qdrant-collections", settle=1.5)
    page.goto(f"{QDRANT}#/collections/isro_chunks")
    page.wait_for_load_state("networkidle")
    shots.take(page, "21-qdrant-point", settle=3)

    if shots.want("22-"):
        pgadmin_llm_calls(page)
        shots.take(page, "22-pgadmin", settle=2)

    page.goto(f"{API}/docs")
    expect(page.get_by_text("ISRO Assistant API").first).to_be_visible(timeout=20_000)
    shots.take(page, "23-api-docs", settle=1.5)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated name prefixes")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--flows", default="user,voice,admin,mobile,consoles",
                    help="which parts to run (comma-separated): user, voice, admin, mobile, consoles")
    args = ap.parse_args()
    shots = Shots([p for p in args.only.split(",") if p] or None)
    user, upw = os.environ["DEMO_EMAIL"], os.environ["DEMO_PASSWORD"]
    admin, apw = os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"]

    with sync_playwright() as p:
        fake_mic = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                    f"--use-file-for-fake-audio-capture={VOICE_WAV}%noloop"]
        browser = p.chromium.launch(channel=os.getenv("PW_CHANNEL", "msedge"), headless=not args.headed,
                                    args=fake_mic)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, permissions=["microphone"])
        page = ctx.new_page()
        flows = set(args.flows.split(","))
        thread_url = user_flow(page, shots, user, upw, args.register) if "user" in flows else ""
        if "voice" in flows:
            if "user" not in flows:
                sign_in(page, user, upw)
            voice_and_many_agents(page, shots)
        if "admin" in flows:
            admin_flow(page, shots, admin, apw)
        if "mobile" in flows and thread_url:
            mobile_flow(browser, shots, user, upw, thread_url)
        if "consoles" in flows:
            consoles_flow(page, shots)
        browser.close()
    print("done")


if __name__ == "__main__":
    sys.exit(main())
