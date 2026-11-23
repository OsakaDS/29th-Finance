#!/usr/bin/env python3
"""
29th Infantry Division - Finance Clerk automation
=================================================
Turns a weekly donations post into weapon passes, following the Finance
Clerk instructions:

1. Read the donors from the donations topic (same parser as the Donations tab).
2. Decide each donor's pass from their recurring donation:
       below $5      -> no weapons pass
       $5 to $14.99  -> one week   (Sunday - Saturday)
       $15 and above -> two weeks
   Leadership (Cpl. and above; T/5, T/4, T/3, T/2 are not leadership) and
   retired members do not receive passes.
3. Check the existing passes so nobody gets the same pass twice.
4. Create a "Recurring Donation" pass for each donor on www.29th.org/manage/passes.
5. Send one "Weapon Pass" PM per date group to the donors, with the Chief and
   Assistant Chief Finance Officer as recipients too.
6. Reply "Weapon passes processed!" in the donations topic.

Like the Donations tab it runs in two phases, so the GUI can preview first:
    plan = clerk.prepare(url, week="next")   # read-only
    clerk.execute(plan)                      # writes

Usage:
    python finance_clerk.py --dry-run [--url URL] [--week this|next]
"""

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from urllib.parse import unquote

from bs4 import BeautifulSoup

from donation_automation import (FORUM, SITE, AutomationError, DonationAutomator,
                                 app_file, load_credentials, parse_date)

RESULTS_FILE = "finance_clerk_automation_results.json"
SETTINGS_FILE = "finance_clerk_settings.json"
PASS_TYPE_LABEL = "Recurring Donation"
PM_TITLE = "Weapon Pass"

# Unit-specific values (officers, opt-out topic, signature) are deliberately not
# in the code: they are entered on the tab once and saved locally in
# finance_clerk_settings.json, which is never committed.
DEFAULT_SETTINGS = {
    # Member-page slugs (www.29th.org/members/<slug>) of the Chief and the
    # Assistant Chief Finance Officer. They receive every PM.
    "finance_officers": [],
    # Forum topic listing members who don't want the weapon pass PM.
    "opt_out_url": "",
    "reply_text": "Weapon passes processed!",
    "pm_template": (
        "Hello Donators,\n\n"
        "**You will receive a [Weapons Passes](https://www.29th.org/wiki/Weapons_Passes)!**\n\n"
        "When is your weapon pass valid?:\n\n"
        "Your weapon pass will be valid from the **{start}** to the **{end}**\n\n"
        "Thank you for supporting the 29th Infantry Division. \n"
        "Enjoy your weapons pass! \n"
        "<hr>\n\n"
        "Best Regards,\n\n"
        "<em>29th Infantry Division\n"
        "Finance Corps\n"
        "Finance Clerk</em>\n\n"
        "**If you want to opt out of these messages, you can do so by replying to this PM**"
    ),
}


# ------------------------------------------------------------ pure helpers

def format_ordinal_date(dt):
    """8 March -> '8th of March'."""
    day = dt.day
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} of {dt.strftime('%B')}"


def pass_weeks(amount):
    """Weeks of weapons pass for a recurring donation amount."""
    if amount is None:
        return 0
    if amount >= 15:
        return 2
    if amount >= 5:
        return 1
    return 0


def week_start(choice, today=None):
    """Sunday that starts the pass. 'this' = the Sunday on or before today,
    'next' = the Sunday after that."""
    today = today or date.today()
    this_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    return this_sunday + timedelta(days=7) if choice == "next" else this_sunday


def pass_dates(start, weeks):
    """(start Sunday, end Saturday) for a pass of `weeks` weeks."""
    return start, start + timedelta(days=7 * weeks - 1)


def is_leadership(rank):
    """Cpl. and above is leadership; T/5, T/4, T/3, T/2 are not.

    Returns True/False, or None when the rank is unknown."""
    r = re.sub(r"[\s.]", "", (rank or "")).lower()
    if not r:
        return None
    if r.startswith("t/"):
        return False
    if r in {"rec", "rct", "recruit", "pvt", "pfc"}:
        return False
    return True


def format_amount(amount):
    return f"{amount:g}" if float(amount).is_integer() else f"{amount:.2f}"


def pass_reason(row):
    """'T/5 Doe recurrently donated 10 dollars on the 8th of March'."""
    parsed = parse_date(row["date"])
    when = format_ordinal_date(parsed) if parsed else row["date"]
    who = f"{row['rank']} {row['last_name']}".strip()
    return f"{who} recurrently donated {format_amount(row['amount'])} dollars on the {when}"


def find_duplicate(row, existing):
    """An existing pass with the same member, Start Date, End Date and Type
    (Recurring Donation), or None. The same member may have other passes
    with different dates."""
    if not row.get("start"):
        return None
    for p in existing:
        if "recurring" not in (p.get("type") or "").lower():
            continue
        if (p["start"], p["end"]) != (row["start"], row["end"]):
            continue
        if p.get("user_id") and row.get("member_id"):
            same = str(p["user_id"]) == str(row["member_id"])
        else:  # no link to compare: fall back to "Rank Lastname"
            same = _norm(p.get("user")) == _norm(f"{row['rank']} {row['last_name']}") \
                or _norm(p.get("user")).endswith(" " + _norm(row["last_name"]))
        if same:
            return p
    return None


def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[.]", "", (text or "")).lower()).strip()


def apply_week(plan, choice):
    """(Re)compute every row's pass dates for 'this' or 'next' week and redo
    the duplicate check. Safe to call again when the user changes the week."""
    start = week_start(choice)
    plan["week"] = choice
    plan["week_start"] = start
    for row in plan["donors"]:
        if row["weeks"]:
            row["start"], row["end"] = pass_dates(start, row["weeks"])
        else:
            row["start"] = row["end"] = None
        was_dup = row.get("block") == "duplicate"
        if row.get("block") and not was_dup:
            continue  # below tier / no user / repeat: never gets a pass
        dup = find_duplicate(row, plan["existing_passes"])
        if dup:
            row["block"] = "duplicate"
            row["block_note"] = (f"already has a Recurring Donation pass "
                                 f"{dup['start']:%b %d} – {dup['end']:%b %d, %Y}")
            row["give_pass"] = row["send_pm"] = False
        elif was_dup:
            row["block"] = None
            row["block_note"] = ""
            row["give_pass"] = row["default_pass"]
            row["send_pm"] = row["default_pass"] and bool(row.get("forum_username"))
    return plan


def pm_groups(plan):
    """{(start, end): [rows]} for rows that get a pass and a PM."""
    groups = {}
    for row in plan["donors"]:
        if row.get("give_pass") and row.get("send_pm") and row.get("start"):
            groups.setdefault((row["start"], row["end"]), []).append(row)
    return dict(sorted(groups.items()))


def render_pm(template, start, end):
    return template.replace("{start}", format_ordinal_date(start)) \
                   .replace("{end}", format_ordinal_date(end))


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(app_file(SETTINGS_FILE), encoding="utf-8") as f:
            settings.update(json.load(f))
    except (FileNotFoundError, ValueError):
        pass
    return settings


def save_settings(settings):
    with open(app_file(SETTINGS_FILE), "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- the clerk

class FinanceClerk:
    def __init__(self, username, password, dry_run=False, log=None):
        self.bot = DonationAutomator(username, password, dry_run=dry_run, log=log)
        self.bot.site_check_path = "/manage/passes/new"
        self.bot.site_check_label = "new pass"
        self.log = self.bot.log
        self.session = self.bot.session
        self._forum_names = {}

    @property
    def dry_run(self):
        return self.bot.dry_run

    @dry_run.setter
    def dry_run(self, value):
        self.bot.dry_run = value

    # ----------------------------------------------------------- forum side

    def forum_username(self, forum_url):
        """Forum username behind a profile's 'user-by-id/<id>' link.

        Discourse redirects /user-by-id/<id>/summary to /u/<username>/summary.
        """
        if not forum_url:
            return None
        if not forum_url.startswith(FORUM + "/"):
            # Only ever follow links to the unit's own forum.
            self.log(f"  Warning: ignored a forum profile link that isn't on "
                     f"{FORUM}: {forum_url}", "warn")
            return None
        if forum_url in self._forum_names:
            return self._forum_names[forum_url]
        name = None
        try:
            r = self.session.get(forum_url, timeout=30, allow_redirects=False)
            m = re.search(r"/u/([^/?#]+)", r.headers.get("Location", "") or "")
            if not m and r.status_code == 200:
                m = re.search(r"/u/([^/?#]+)", r.url)
            name = unquote(m.group(1)) if m else None
        except Exception as e:  # network trouble: reported as "no forum user"
            self.log(f"  Warning: could not open {forum_url} ({e})")
        self._forum_names[forum_url] = name
        return name

    def _forum_post(self, data, what):
        r = self.session.get(f"{FORUM}/session/csrf.json",
                             headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30)
        csrf = r.json()["csrf"]
        # The forum limits how fast an account may post (e.g. a reply right
        # after a PM) and answers 429 "please wait N seconds". Nothing was
        # posted then, so it is safe to wait and send again.
        for attempt in range(4):
            r = self.session.post(f"{FORUM}/posts.json", data=data,
                                  headers={"X-CSRF-Token": csrf,
                                           "X-Requested-With": "XMLHttpRequest"},
                                  timeout=60)
            if r.status_code != 429 or attempt == 3:
                break
            wait = self._wait_seconds(r)
            self.log(f"  The forum asks to wait {wait} s before posting again; "
                     f"waiting...", "warn")
            time.sleep(wait + 1)
        if r.status_code != 200:
            try:
                msg = "; ".join(r.json().get("errors", [])) or r.text[:300]
            except ValueError:
                msg = r.text[:300]
            raise AutomationError(f"Could not {what} ({r.status_code}): {msg}")
        return r.json()

    @staticmethod
    def _wait_seconds(r):
        """Seconds the forum asked us to wait (capped at 60)."""
        wait = None
        try:
            wait = (r.json().get("extras") or {}).get("wait_seconds")
        except ValueError:
            pass
        if wait is None:
            wait = r.headers.get("Retry-After")
        if wait is None:
            m = re.search(r"wait (\d+) second", r.text)
            wait = m.group(1) if m else 5
        try:
            return min(max(int(float(wait)), 1), 60)
        except (TypeError, ValueError):
            return 5

    def officers(self, slugs):
        """Resolve finance officer member slugs to forum usernames."""
        if not [s for s in slugs if s.strip()]:
            raise AutomationError(
                "No finance officers are set. Enter the member-page names of the "
                "Chief and Assistant Chief Finance Officer in 'Finance officers' "
                "(e.g. smith, jones for www.29th.org/members/smith), then click "
                "'Save PM/officers as default'.")
        found = []
        for slug in slugs:
            slug = slug.strip()
            if not slug:
                continue
            profile = self.bot.get_profile({"profile_url": None, "last_name": slug}) or {}
            username = self.forum_username(profile.get("forum_url"))
            label = f"{profile.get('rank') or ''} {profile.get('name') or slug}".strip()
            if not username:
                raise AutomationError(
                    f"Could not find the forum account of finance officer '{slug}' "
                    f"({SITE}/members/{slug}). Check the officer list in settings.")
            found.append({"slug": slug, "name": label, "username": username})
            self.log(f"  Finance officer: {label} → @{username}")
        return found

    # ------------------------------------------------------------ site side

    def existing_passes(self, since):
        """Recurring-donation-relevant passes ending on or after `since`.

        Reads the admin list sorted by end date (newest first) and stops once
        the passes end before `since`.
        """
        passes, page = [], 1
        while page <= 30:
            # Exactly the admin list page (newest end date first by default);
            # only the page number is added for later pages.
            params = {"scope": "all"}
            if page > 1:
                params["page"] = page
            r = self.session.get(f"{SITE}/manage/passes", params=params,
                                 headers={"Accept": "text/html"}, timeout=30)
            if r.status_code != 200:
                raise AutomationError(
                    f"Could not read the passes list (status {r.status_code}), so "
                    f"duplicates can't be checked. Nothing was written.")
            rows, diag = self._parse_pass_table(r.text)
            if diag["problem"]:
                path = app_file("passes_list_debug.html")
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(r.text)
                except OSError:
                    path = "(could not be saved)"
                self.log(f"  Passes list page {page}: {r.url}", "warn")
                self.log(f"  Tables: {diag['tables']}, headers: {diag['headers']}, "
                         f"body rows: {diag['body_rows']}, read: {len(rows)}", "warn")
                if diag.get("sample"):
                    self.log(f"  First row cells: {diag['sample']}", "warn")
                raise AutomationError(
                    f"Could not read the passes list ({diag['problem']}), so "
                    f"duplicates can't be checked. Nothing more was written.\n\n"
                    f"The page was saved to {path} — please send it to whoever "
                    f"maintains the app.")
            if not rows:
                break
            ends = [p["end"] for p in rows]
            if any(a < b for a, b in zip(ends, ends[1:])):
                raise AutomationError(
                    f"The passes list ({r.url}) is not sorted by End Date, newest "
                    f"first, so duplicates can't be checked reliably. Nothing was "
                    f"written.")
            passes.extend(p for p in rows if p["end"] >= since)
            if ends[-1] < since:
                break
            page += 1
        self.log(f"  {len(passes)} existing pass(es) end on or after {since:%b %d, %Y}.")
        return passes

    @staticmethod
    def _parse_pass_table(html):
        """Return (rows, diag). diag["problem"] is set when the page is not
        a passes list we can read, so a misread never looks like 'no passes'."""
        soup = BeautifulSoup(html, "html.parser")
        diag = {"problem": None, "tables": len(soup.find_all("table")),
                "headers": [], "body_rows": 0, "sample": None}
        table = soup.find("table", class_=re.compile(r"index_table")) or soup.find("table")
        if not table:
            # Active Admin shows a "blank slate" instead of a table when empty.
            if not soup.find(class_=re.compile(r"blank_slate")):
                diag["problem"] = "no table on the page"
            return [], diag
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        diag["headers"] = headers

        def idx(label):
            for i, h in enumerate(headers):
                if label in h:
                    return i
            return None

        i_user, i_start, i_end, i_type = idx("user"), idx("start"), idx("end"), idx("type")
        if None in (i_user, i_start, i_end):
            diag["problem"] = "the table has no User / Start Date / End Date columns"
            return [], diag
        rows = []
        body = table.find("tbody")
        trs = body.find_all("tr") if body else table.find_all("tr")[1:]
        diag["body_rows"] = len(trs)
        for tr in trs:
            cells = tr.find_all("td")
            if diag["sample"] is None:
                diag["sample"] = [c.get_text(" ", strip=True) for c in cells]
            if len(cells) <= max(i_user, i_start, i_end):
                continue
            start = _site_date(cells[i_start].get_text(" ", strip=True))
            end = _site_date(cells[i_end].get_text(" ", strip=True))
            if not start or not end:
                continue
            link = cells[i_user].find("a", href=True)
            m = re.search(r"/users/(\d+)", link["href"]) if link else None
            rows.append({
                "user": cells[i_user].get_text(" ", strip=True),
                "user_id": m.group(1) if m else None,
                "start": start, "end": end,
                "type": cells[i_type].get_text(" ", strip=True) if i_type is not None else "",
            })
        if trs and not rows:
            diag["problem"] = "none of the rows could be read"
        return rows, diag

    def _pass_form(self):
        """Read the New Pass form and work out its field names.

        Returns (post_url, base_data, fields) where `fields` maps member,
        start, end, type, reason to the form's input names (dates may be
        Rails (1i)/(2i)/(3i) selects) and type_value is the option for
        'Recurring Donation'.
        """
        r = self.session.get(f"{SITE}/manage/passes/new", timeout=30)
        if r.status_code != 200:
            raise AutomationError(f"Could not open the New Pass form (status {r.status_code}).")
        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form", action=re.compile(r"passes"))
        if form is None:
            raise AutomationError("New Pass form not found — check the account's permissions.")
        action = form.get("action") or "/manage/passes"

        data = {}
        for inp in form.find_all("input", attrs={"name": True}):
            if inp["name"].endswith("[]"):
                continue  # list fields (e.g. bulk member ids) are filled in per pass
            if inp.get("type") in ("hidden",) or inp["name"] in ("authenticity_token", "utf8"):
                data[inp["name"]] = inp.get("value", "")
        names = [el["name"] for el in form.find_all(["input", "select", "textarea"],
                                                     attrs={"name": True})]

        def pick(pattern):
            return [n for n in names if re.search(pattern, n)]

        fields = {}
        # Either one member (pass[member_id]) or a multi-select for creating
        # several at once (pass[bulk_member_ids][]); we send one member per pass.
        member = pick(r"\[(member|user)_id\]$") or pick(r"\[bulk_(member|user)_ids\]\[\]$")
        start = pick(r"\[start_date\]$") or pick(r"\[start_date\(\di\)\]$")
        end = pick(r"\[end_date\]$") or pick(r"\[end_date\(\di\)\]$")
        kind = pick(r"\[(type|pass_type|kind)\]$")
        reason = pick(r"\[reason\]$")
        missing = [k for k, v in (("member", member), ("start date", start),
                                  ("end date", end), ("type", kind),
                                  ("reason", reason)) if not v]
        if missing:
            raise AutomationError(
                f"The New Pass form has changed: could not find {', '.join(missing)}. "
                f"Fields seen: {', '.join(names)}")
        fields.update(member=member[0], start=start, end=end, type=kind[0],
                      reason=reason[0])

        select = form.find("select", attrs={"name": kind[0]})
        type_value = PASS_TYPE_LABEL
        if select is not None:
            opts = [(o.get("value", o.get_text(strip=True)), o.get_text(" ", strip=True))
                    for o in select.find_all("option")]
            match = [v for v, t in opts if "recurring" in t.lower()
                     or "recurring" in (v or "").lower()]
            if not match:
                raise AutomationError(
                    f"No '{PASS_TYPE_LABEL}' option in the pass type list: "
                    f"{[t for _v, t in opts]}")
            type_value = match[0]
        fields["type_value"] = type_value

        commit = form.find("input", attrs={"type": "submit", "name": True})
        if commit:
            data[commit["name"]] = commit.get("value", "")
        return (SITE + action if action.startswith("/") else action), data, fields

    @staticmethod
    def _date_fields(names, value):
        if len(names) == 1 and not names[0].endswith("i)]"):
            return {names[0]: value.strftime("%Y-%m-%d")}
        parts = {"1i": value.year, "2i": value.month, "3i": value.day}
        return {n: str(parts[re.search(r"\((\di)\)", n).group(1)]) for n in names}

    def create_pass(self, row, form):
        url, base, f = form
        data = dict(base)
        member_id = str(row["member_id"])
        if not f["member"].endswith("[]"):
            data[f["member"]] = member_id
        data.update(self._date_fields(f["start"], row["start"]))
        data.update(self._date_fields(f["end"], row["end"]))
        data[f["type"]] = f["type_value"]
        data[f["reason"]] = row["reason"]
        payload = list(data.items())
        if f["member"].endswith("[]"):
            # Rails multi-select: a blank hidden value plus the chosen id.
            payload += [(f["member"], ""), (f["member"], member_id)]
        r = self.session.post(url, data=payload, timeout=60, allow_redirects=False)
        if r.status_code in (302, 303):
            return True, r.headers.get("Location", "")
        if r.status_code >= 500:
            return False, (f"the personnel site returned a server error "
                           f"({r.status_code}); nothing was saved")
        errors = BeautifulSoup(r.text, "html.parser").find_all(
            class_=re.compile(r"error|inline-errors"))
        return False, ("; ".join(e.get_text(" ", strip=True) for e in errors[:3])
                       or f"status {r.status_code}")

    # ------------------------------------------------------------- phase one

    def prepare(self, url=None, week="next", settings=None):
        """Read-only: parse the post, work out each donor's pass, check for
        duplicates and resolve forum usernames. Nothing is written."""
        settings = settings or load_settings()
        self.bot.login()
        topic = self.bot.get_topic(self.bot.topic_id_from_url(url)) if url \
            else self.bot.get_latest_donations_topic()
        self.log(f"Source topic: {topic['title']} (id {topic['id']})")

        donors, _expenses = self.bot.parse_donations_post(topic["cooked"])
        if not donors:
            raise AutomationError("No donors could be read from that post.")
        self.log(f"Parsed {len(donors)} donor(s). Looking up members...")

        officers = self.officers(settings["finance_officers"])

        rows, seen = [], set()
        for d in donors:
            profile = self.bot.get_profile(d) or {}
            row = dict(d)
            row["rank"] = profile.get("rank") or d.get("rank") or ""
            if profile.get("name"):
                row["site_name"] = profile["name"]
                row["last_name"] = profile["name"].split()[-1]
            row["status"] = profile.get("status") or ""
            row["weeks"] = pass_weeks(d["amount"])
            row["block"], row["block_note"], notes = None, "", []

            # Soft exclusions: off by default, can be ticked by hand.
            excluded = []
            kind = (d.get("type") or "").lower()
            if kind and "recurr" not in kind:
                excluded.append(f"not a recurring donation ({d['type']})")
            lead = is_leadership(row["rank"])
            if lead:
                excluded.append(f"leadership ({row['rank']})")
            elif lead is None:
                excluded.append("rank unknown — check manually")
            status = row["status"].lower()
            if "retired" in status:
                excluded.append("retired")
            elif status and status != "member":
                excluded.append(f"status '{row['status']}' — check manually")
            elif not status:
                notes.append("status unknown")

            # Hard blocks: these rows can't get a pass.
            if not row["weeks"]:
                row["block"] = "tier"
                row["block_note"] = f"${d['amount']:.2f} is below the $5 tier"
            else:
                row["member_id"] = self.bot.resolve_member_id(row)
                if row["member_id"] is None:
                    row["block"] = "no_user"
                    row["block_note"] = "no matching user on the site"
                elif str(row["member_id"]) in seen:
                    row["block"] = "repeat"
                    row["block_note"] = "appears more than once in the post"
                else:
                    seen.add(str(row["member_id"]))

            row["forum_username"] = self.forum_username(profile.get("forum_url")) \
                if not row["block"] else None
            if not row["block"] and not row["forum_username"]:
                notes.append("no forum account found — no PM")

            row["reason"] = pass_reason(row)
            row["default_pass"] = not row["block"] and not excluded
            row["give_pass"] = row["default_pass"]
            row["send_pm"] = row["give_pass"] and bool(row["forum_username"])
            row["note"] = "; ".join(excluded + notes)
            rows.append(row)

        earliest = week_start("this") - timedelta(days=7)
        plan = {
            "source_topic": topic["id"], "source_title": topic["title"],
            "donors": rows, "officers": officers,
            "existing_passes": self.existing_passes(earliest),
            "pm_template": settings["pm_template"],
            "reply_text": settings["reply_text"],
        }
        apply_week(plan, week)
        for row in rows:
            if row["block"] == "duplicate":
                self.log(f"  Error: {row['rank']} {row['last_name']} "
                         f"{row['block_note']}.", "error")
        return plan

    # ------------------------------------------------------------- phase two

    def execute(self, plan):
        """Create the passes, send the PMs and reply in the donations topic."""
        self.bot.login()
        dry = self.dry_run
        chosen = [r for r in plan["donors"] if r.get("give_pass") and not r.get("block")]
        if not chosen:
            raise AutomationError("No donors are ticked to receive a pass.")

        # Re-check duplicates against the live list right before writing.
        self.log("Checking existing passes for duplicates...")
        plan["existing_passes"] = self.existing_passes(
            min(r["start"] for r in chosen) - timedelta(days=1))
        for row in plan["donors"]:
            row["result"] = None
        for row in chosen:
            dup = find_duplicate(row, plan["existing_passes"])
            if dup:
                row["result"] = "duplicate"
                self.log(f"  Error: {row['rank']} {row['last_name']} already has a "
                         f"Recurring Donation pass {dup['start']:%b %d} – "
                         f"{dup['end']:%b %d, %Y}. Nothing written for them.", "error")

        todo = [r for r in chosen if not r["result"]]
        form = None if dry else self._pass_form()
        self.log(f"Creating {len(todo)} pass(es)...")
        for row in todo:
            label = (f"{row['rank']} {row['last_name']}: {row['start']:%b %d} – "
                     f"{row['end']:%b %d, %Y}")
            if dry:
                self.log(f"  DRY RUN pass {label} — reason: {row['reason']}")
                row["result"] = "created"
                continue
            ok, info = self.create_pass(row, form)
            row["result"] = "created" if ok else "failed"
            row["result_info"] = info
            self.log(f"  OK: pass {label}" if ok else f"  FAILED: pass {label} — {info}",
                     "ok" if ok else "error")

        # Confirm each pass really exists: the bulk form can redirect even when
        # nothing was saved. Unconfirmed passes get no PM and block the reply.
        made = [r for r in todo if r["result"] == "created"]
        if made and not dry:
            self.log("Checking the new passes on the site...")
            fresh = self.existing_passes(min(r["start"] for r in made) - timedelta(days=1))
            for row in made:
                if not find_duplicate(row, fresh):
                    row["result"] = "unconfirmed"
                    self.log(f"  Warning: the pass for {row['rank']} {row['last_name']} "
                             f"is not in the passes list — check /manage/passes by hand. "
                             f"No PM sent for them.", "warn")

        # PMs: one per date group, only to donors whose pass went in.
        officer_names = [o["username"] for o in plan["officers"]]
        pms = []
        for (start, end), rows in pm_groups(plan).items():
            rows = [r for r in rows if r.get("result") == "created"]
            if not rows:
                continue
            recipients = []
            for name in [r["forum_username"] for r in rows] + officer_names:
                if name and name.lower() != self.bot.username.lower() \
                        and name.lower() not in [x.lower() for x in recipients]:
                    recipients.append(name)
            body = render_pm(plan["pm_template"], start, end)
            pm = {"start": start, "end": end, "recipients": recipients,
                  "donors": [f"{r['rank']} {r['last_name']}" for r in rows]}
            if dry:
                self.log(f"  DRY RUN PM '{PM_TITLE}' ({start:%b %d} – {end:%b %d}) "
                         f"to {', '.join(recipients)}")
                pm["result"] = "dry run"
            else:
                try:
                    data = self._forum_post({"title": PM_TITLE, "raw": body,
                                             "archetype": "private_message",
                                             "target_recipients": ",".join(recipients)},
                                            "send the PM")
                    pm["result"] = f"{FORUM}/t/{data['topic_id']}"
                    self.log(f"  OK: PM sent to {', '.join(recipients)} "
                             f"({pm['result']})", "ok")
                except AutomationError as e:
                    pm["result"] = f"failed: {e}"
                    self.log(f"  FAILED: PM to {', '.join(recipients)} — {e}", "error")
            pms.append(pm)

        problems = [r for r in chosen if r["result"] != "created"] \
            + [p for p in pms if str(p["result"]).startswith("failed")]
        created = [r for r in chosen if r["result"] == "created"]
        reply = None
        if not created:
            self.log("No passes were created, so no reply was posted.", "warn")
        elif problems:
            self.log("Some steps failed, so no reply was posted in the donations "
                     "topic. Fix them, then reply by hand.", "warn")
        elif dry:
            self.log(f"  DRY RUN reply in topic {plan['source_topic']}: "
                     f"{plan['reply_text']}")
            reply = "dry run"
        else:
            try:
                data = self._forum_post({"topic_id": plan["source_topic"],
                                         "raw": plan["reply_text"]},
                                        "reply in the donations topic")
                reply = f"{FORUM}/t/{plan['source_topic']}/{data.get('post_number', '')}"
                self.log(f"  OK: replied in the donations topic ({reply})", "ok")
            except AutomationError as e:
                reply = f"failed: {e}"
                self.log(f"  FAILED: reply — {e}", "error")

        results = {
            "timestamp": datetime.now().isoformat(),
            "dry_run": dry,
            "source_topic": plan["source_topic"],
            "source_title": plan["source_title"],
            "week": plan["week"],
            "passes": [{k: r.get(k) for k in (
                "name", "rank", "last_name", "member_id", "forum_username", "amount",
                "date", "weeks", "start", "end", "reason", "give_pass", "send_pm",
                "block", "block_note", "note", "result", "result_info")}
                for r in plan["donors"]],
            "pms": pms,
            "reply": reply,
        }
        n_ok = len(created)
        self.log(f"\nDone. Passes {n_ok}/{len(chosen)}, PMs {len(pms)}, "
                 f"reply: {reply or 'not posted'}.")
        if not dry:
            with open(app_file(RESULTS_FILE), "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, default=str, ensure_ascii=False)
            self.log(f"Audit trail written to {RESULTS_FILE}")
        results["created"], results["chosen"] = n_ok, len(chosen)
        return results


def _site_date(text):
    m = re.search(r"[A-Z][a-z]+ \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2}|\d{1,2} [A-Z][a-z]+ \d{4}",
                  text or "")
    text = m.group(0) if m else (text or "")
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    return None


def main():
    ap = argparse.ArgumentParser(description="29th ID Finance Clerk automation")
    ap.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    ap.add_argument("--url", help="Donations topic URL (default: latest)")
    ap.add_argument("--week", choices=("this", "next"), default="next",
                    help="Pass week (default: next)")
    args = ap.parse_args()
    try:
        username, password = load_credentials()
    except FileNotFoundError:
        print("credentials.json not found.")
        return 1
    clerk = FinanceClerk(username, password, dry_run=args.dry_run)
    try:
        plan = clerk.prepare(args.url, week=args.week)
        for r in plan["donors"]:
            print(f"{'PASS' if r['give_pass'] else '----'} {r['rank']} {r['last_name']}"
                  f" ${r['amount']:.2f} {r.get('start') or ''} {r.get('end') or ''}"
                  f" {r['block_note'] or r['note']}")
        clerk.execute(plan)
    except AutomationError as e:
        print(f"\nError: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
