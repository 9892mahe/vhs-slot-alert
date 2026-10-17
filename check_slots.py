"""
VHS Berlin exam-slot watcher -> Telegram alert.

What it does (each run):
  1. Opens the Berlin VHS course search and searches for SEARCH_TERM.
  2. Reads every result page (district, course number, date, free places).
  3. Keeps only exams whose date is between WINDOW_START and WINDOW_END.
  4. Compares with the last run (state.json) and sends a Telegram message when:
       - a course in the window shows free places (status is not "belegt"), or
       - a brand-new course date in the window is published (even if already full).
  5. Saves the new state to state.json.

Settings come from environment variables (set in the GitHub workflow file):
  TELEGRAM_BOT_TOKEN   (secret)  - from @BotFather
  TELEGRAM_CHAT_ID     (secret)  - your chat id; if empty, the script tries to find it
  SEARCH_TERM          default "Sprachtest zur Einbürgerung"
  WINDOW_START         default "2026-12-01"   (YYYY-MM-DD)
  WINDOW_END           default "2027-01-31"   (YYYY-MM-DD)
  FORCE_SUMMARY        "1" = always send a status summary (used for manual test runs)
"""

import json
import os
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = "https://www.vhsit.berlin.de/VHSKURSE/BusinessPages/"
SEARCH_URL = os.environ.get("VHS_SEARCH_URL", BASE + "CourseSearch.aspx")
DETAIL_URL = BASE + "CourseDetail.aspx?id={id}"

SEARCH_TERM = os.environ.get("SEARCH_TERM", "Sprachtest zur Einbürgerung")
WINDOW_START = date.fromisoformat(os.environ.get("WINDOW_START") or "2026-12-01")
WINDOW_END = date.fromisoformat(os.environ.get("WINDOW_END") or "2027-01-31")
FORCE_SUMMARY = os.environ.get("FORCE_SUMMARY", "0") == "1"
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Field ids on the VHS search page (checked on the live site, Oct 2026)
SEARCH_BOX = "#ctl00_Content_SimpleSearch1_SimpleSearchBox_txtSearchTerm"
SEARCH_BUTTON = "#ctl00_Content_btnSearch"
RESULT_TABLE = "#ctl00_Content_ILDataGrid1"
NEXT_PAGE = 'input[src$="arrow_right.gif"]'  # disabled version is arrow_right_dis.gif

# JavaScript run inside the page to read the result table
EXTRACT_JS = """
() => {
  const t = document.querySelector('%s');
  if (!t) return null;
  return [...t.rows]
    .filter(r => r.cells.length >= 8 && /\\d{2}\\.\\d{2}\\.\\d{4}/.test(r.cells[5].innerText))
    .map(r => {
      const m = r.innerHTML.match(/CourseDetail\\.aspx\\?id=(\\d+)/i);
      return {
        district: r.cells[2].innerText.trim(),
        nr:       r.cells[3].innerText.trim(),
        title:    r.cells[4].innerText.trim(),
        start:    r.cells[5].innerText.trim().replace(/\\s+/g, ' '),
        free:     r.cells[6].innerText.trim(),
        note:     r.cells[7].innerText.trim().replace(/\\s+/g, ' '),
        id:       m ? m[1] : null
      };
    });
}
""" % RESULT_TABLE


# ---------------------------------------------------------------- Telegram
def tg_send(text):
    if not TOKEN or not CHAT_ID:
        print("[telegram not configured] would send:\n" + text)
        return
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": "true"},
        timeout=30,
    )
    if not r.ok:
        print("Telegram error:", r.status_code, r.text)


def find_chat_id():
    """If no chat id is set, use the last chat that messaged the bot."""
    if not TOKEN:
        return ""
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=30)
        updates = r.json().get("result", [])
        for u in reversed(updates):
            msg = u.get("message") or u.get("channel_post") or {}
            if msg.get("chat", {}).get("id"):
                cid = str(msg["chat"]["id"])
                print(f"Found chat id {cid} - save it as the TELEGRAM_CHAT_ID secret.")
                return cid
    except Exception as e:
        print("Could not look up chat id:", e)
    print("No chat id found. Send any message to your bot in Telegram, then run again.")
    return ""


# ---------------------------------------------------------------- Scraping
def launch_browser(p):
    try:
        return p.chromium.launch(channel="chrome")  # Chrome is preinstalled on GitHub runners
    except Exception:
        try:
            return p.chromium.launch()
        except Exception:
            subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps",
                            "chromium"], check=True)
            return p.chromium.launch()


def scrape():
    courses = []
    with sync_playwright() as p:
        browser = launch_browser(p)
        page = browser.new_page(locale="de-DE")
        page.set_default_timeout(60000)
        page.goto(SEARCH_URL, wait_until="load")
        page.fill(SEARCH_BOX, SEARCH_TERM)
        with page.expect_navigation(wait_until="load"):
            page.click(SEARCH_BUTTON)

        for _ in range(30):  # safety limit on number of pages
            rows = page.evaluate(EXTRACT_JS)
            if rows is None:
                body = page.inner_text("body")
                if "Anzahl Treffer: 0" in body or "keine" in body.lower():
                    break  # no courses at all - not an error
                raise RuntimeError("Result table not found - the VHS page may have changed.")
            courses.extend(rows)
            nxt = page.query_selector(NEXT_PAGE)
            if not nxt:
                break
            with page.expect_navigation(wait_until="load"):
                nxt.click()
        browser.close()

    # remove duplicates (same course number)
    unique = {}
    for c in courses:
        unique[c["nr"]] = c
    return list(unique.values())


def course_date(c):
    return datetime.strptime(c["start"][:10], "%d.%m.%Y").date()


def is_free(c):
    s = c["free"].strip().lower()
    return s not in ("", "belegt", "0")


# ---------------------------------------------------------------- Messages
def fmt(c):
    link = DETAIL_URL.format(id=c["id"]) if c.get("id") else BASE + "CourseSearch.aspx"
    return (f"📍 <b>{c['district']}</b> – {c['start']}\n"
            f"Kurs {c['nr']} · Plätze: <b>{c['free']}</b>\n"
            f"<a href=\"{link}\">Open course page</a>")


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"courses": {}, "fail_count": 0, "initialized": False}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
                          encoding="utf-8")


def main():
    global CHAT_ID
    if TOKEN and not CHAT_ID:
        CHAT_ID = find_chat_id()

    state = load_state()
    try:
        all_courses = scrape()
    except Exception as e:
        state["fail_count"] = state.get("fail_count", 0) + 1
        print("Scrape failed:", repr(e))
        if state["fail_count"] == 3:  # warn once after 3 failures in a row
            tg_send("⚠️ Exam-slot bot: could not read the VHS website 3 times in a row.\n"
                    f"Error: {e}\nI will keep trying. Please check the site manually meanwhile.")
        save_state(state)
        sys.exit(1)

    if state.get("fail_count", 0) >= 3:
        tg_send("✅ Exam-slot bot: VHS website readable again.")
    state["fail_count"] = 0

    window = [c for c in all_courses if WINDOW_START <= course_date(c) <= WINDOW_END]
    window.sort(key=course_date)
    old = state.get("courses", {})
    first_run = not state.get("initialized", False)

    free_now, new_dates = [], []
    for c in window:
        prev = old.get(c["nr"])
        if is_free(c) and (prev is None or not is_free(prev) or FORCE_SUMMARY):
            free_now.append(c)
        elif prev is None and not first_run:
            new_dates.append(c)

    if free_now:
        tg_send("🟢 <b>FREE EXAM SEAT!</b> Book quickly:\n\n" + "\n\n".join(fmt(c) for c in free_now))
    if new_dates:
        tg_send("🆕 <b>New exam date(s) published</b> (full – waitlist possible):\n\n"
                + "\n\n".join(fmt(c) for c in new_dates))

    if first_run or FORCE_SUMMARY:
        n_free = sum(is_free(c) for c in window)
        lines = [f"🤖 Exam-slot bot is running.",
                 f"Search: “{SEARCH_TERM}”",
                 f"Window: {WINDOW_START:%d.%m.%Y} – {WINDOW_END:%d.%m.%Y}",
                 f"All results found: {len(all_courses)} · in your window: {len(window)} · with free places: {n_free}"]
        if window:
            lines.append("")
            lines += [f"• {c['start'][:10]} {c['district']} – {c['free']}" for c in window]
        tg_send("\n".join(lines))

    state["courses"] = {c["nr"]: c for c in window}
    state["initialized"] = True
    save_state(state)
    print(f"OK: {len(all_courses)} courses, {len(window)} in window, "
          f"{len(free_now)} free alerts, {len(new_dates)} new-date alerts")


if __name__ == "__main__":
    main()
