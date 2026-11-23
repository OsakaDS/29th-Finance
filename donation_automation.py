#!/usr/bin/env python3
"""
29th Infantry Division - Donation Automation
============================================
Flow:
1. Find a "Donations <Month Day> - <Month Day>" topic in the
   finance-office/finance-donations category (by URL, or the latest one).
2. Parse donors (Name, Date, Amount, Fee) and Expenses from the first post.
3. For each donor, read their lifetime Donated total and rank from their
   public member page on www.29th.org.
4. Build one acknowledgment block per donor, join them, and create a single
   topic in promotions-and-awards (category 34). Capture its topic id.
5. Submit a finance record for every donor (Forum = Discourse, Topic ID =
   the new topic's id) and for every expense (with a matched Vendor).

The work is split into two phases so a GUI can preview before writing:
    plan = bot.prepare(url)   # read-only: login, parse, compose
    bot.execute(plan)         # writes: create topic, submit records

Usage:
    python donation_automation.py            # real run (latest topic)
    python donation_automation.py --dry-run  # parse + preview only, no writes
    python donation_automation.py --url URL  # use a specific donations topic
    python donation_gui.py                   # graphical version

Requirements:
    pip install requests beautifulsoup4
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

FORUM = "https://forums.29th.org"
SITE = "https://www.29th.org"
DONATIONS_CATEGORY_PATH = "c/finance-office/finance-donations/114"
PROMOTIONS_CATEGORY_ID = 34

TITLE_RE = re.compile(r"^Donations\s+\w+\s+\d{1,2}\s*-\s*\w+\s+\d{1,2}", re.I)
MONEY_RE = re.compile(r"\$?\s*([\d,]+\.?\d*)")
DATE_FORMATS = ("%d %B", "%d %b", "%B %d", "%b %d", "%m/%d/%Y", "%Y-%m-%d",
                "%d %B %Y", "%B %d %Y")


def app_dir():
    """Folder to read/write app files from.

    When frozen by PyInstaller the script lives in a temp extraction dir, so
    credentials and results must sit next to the .exe instead. On macOS the
    executable is inside the .app bundle, which may be read-only (and writing
    there breaks the bundle), so use ~/Library/Application Support.
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            path = os.path.expanduser("~/Library/Application Support/29th Donations")
            os.makedirs(path, exist_ok=True)
            return path
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def app_file(name):
    return os.path.join(app_dir(), name)


def money(text):
    m = MONEY_RE.search(text or "")
    return float(m.group(1).replace(",", "")) if m else None


def parse_date(text):
    """Parse the loose date formats used in the posts. Returns date or None."""
    text = (text or "").strip()
    for fmt in DATE_FORMATS:
        try:
            p = datetime.strptime(text, fmt)
            if p.year == 1900:  # no year in the post: assume the current one
                p = p.replace(year=datetime.now().year)
            return p
        except ValueError:
            pass
    return None


class AutomationError(Exception):
    """Raised for failures the user needs to see (login, permissions, parsing)."""


class LoggingRetry(Retry):
    """Retry that reports each retry, so a slow or failing connection shows up
    in the log instead of looking like a hang (all attempts take minutes)."""

    log = None

    def new(self, **kw):
        retry = super().new(**kw)
        retry.log = self.log
        return retry

    def increment(self, method=None, url=None, response=None, error=None, *args, **kw):
        retry = super().increment(method, url, response, error, *args, **kw)
        if self.log:
            reason = error or (f"status {response.status}" if response else "unknown error")
            self.log(f"  Warning: request to {url} failed ({reason}); retrying...", "warn")
        return retry


class DonationAutomator:
    def __init__(self, username, password, dry_run=False, log=None):
        self.username = username
        self.password = password
        self.dry_run = dry_run
        # log(message, tag=None) — the GUI colour-codes by tag; the CLI ignores it.
        self.log = log or (lambda message, tag=None: print(message))
        self._logged_in = False
        # Page that proves the site login worked and the account may use it.
        self.site_check_path = "/manage/finance_records/new"
        self.site_check_label = "finance records"
        # Lazy caches: a member's profile and a surname's dropdown options are
        # fetched at most once per run, however many times they are needed.
        self._profile_cache = {}
        self._options_cache = {}
        self.session = requests.Session()
        # Retry GETs (safe to repeat) on timeouts and transient server errors.
        # POSTs are never retried automatically: a retry after a slow-but-
        # successful response would create duplicate posts/records.
        retry = LoggingRetry(total=4, backoff_factor=2,
                             status_forcelist=[429, 500, 502, 503, 504],
                             allowed_methods=frozenset(["GET", "HEAD"]))
        retry.log = self.log
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        })

    # ------------------------------------------------------------------ auth

    def login(self):
        """Log in to both sites. Safe to call repeatedly."""
        if self._logged_in:
            return
        self.login_forum()
        self.login_site()
        self._logged_in = True

    def login_forum(self):
        """Log in to Discourse via its JSON API."""
        self.log("Logging in to forums.29th.org...")
        r = self.session.get(f"{FORUM}/session/csrf.json",
                             headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30)
        r.raise_for_status()
        csrf = r.json()["csrf"]

        r = self.session.post(
            f"{FORUM}/session",
            data={"login": self.username, "password": self.password},
            headers={"X-CSRF-Token": csrf, "X-Requested-With": "XMLHttpRequest"},
            timeout=30,
        )
        data = r.json() if "json" in r.headers.get("Content-Type", "") else {}
        if r.status_code != 200 or data.get("error"):
            raise AutomationError(
                f"Forum login failed: {data.get('error', 'status ' + str(r.status_code))}")
        self.log(f"  Logged in as {data.get('user', {}).get('username', self.username)}")

    def login_site(self):
        """Log in to www.29th.org by riding the Discourse OAuth flow."""
        self.log("Logging in to www.29th.org via forum OAuth...")
        r = self.session.get(f"{SITE}/", timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        token = soup.find("meta", attrs={"name": "csrf-token"})["content"]

        # POST /auth/discourse redirects through the forum and back; since the
        # forum session cookie is already set, this completes automatically.
        self.session.post(f"{SITE}/auth/discourse",
                          data={"authenticity_token": token},
                          timeout=60, allow_redirects=True)
        check = self.session.get(f"{SITE}{self.site_check_path}", timeout=30,
                                 allow_redirects=False)
        if check.status_code != 200:
            raise AutomationError(
                f"Site login failed (status {check.status_code} on the "
                f"{self.site_check_label} page). The account may lack the "
                f"permissions for it.")
        self.log("  Site login OK.")

    # ------------------------------------------------------- read forum data

    @staticmethod
    def topic_id_from_url(url):
        """Extract the trailing topic id from a Discourse topic URL."""
        m = re.search(r"/t/[^/]+/(\d+)", url) or re.search(r"(\d{3,})\s*$", url.strip())
        if not m:
            raise AutomationError(
                f"Could not find a topic id in the URL:\n{url}\n\n"
                f"Expected something like {FORUM}/t/donations-july-26-august-1/12345")
        return int(m.group(1))

    def get_topic(self, topic_id):
        r = self.session.get(f"{FORUM}/t/{topic_id}.json", timeout=30)
        if r.status_code != 200:
            raise AutomationError(
                f"Could not open topic {topic_id} (status {r.status_code}). "
                f"Check the link and that your account can read that category.")
        data = r.json()
        return {"id": data["id"], "title": data["title"],
                "cooked": data["post_stream"]["posts"][0]["cooked"]}

    def get_latest_donations_topic(self):
        r = self.session.get(f"{FORUM}/{DONATIONS_CATEGORY_PATH}.json", timeout=30)
        r.raise_for_status()
        topics = r.json()["topic_list"]["topics"]
        for t in sorted(topics, key=lambda t: t.get("created_at", ""), reverse=True):
            if TITLE_RE.match(t["title"]):
                return self.get_topic(t["id"])
        raise AutomationError("No 'Donations Month Day - Month Day' topic found "
                              "in the finance donations category.")

    RANK_RE = re.compile(
        r"^(?:T/\d|Pvt|PFC|Cpl|Sgt|FSgt|SSgt|S/Sgt|T/Sgt|1Sgt|MSgt|M/Sgt|1stSgt|SgtMaj|CSM|"
        r"2Lt|1Lt|2ndLt|1stLt|Capt|Cpt|Maj|LtCol|Lt\.?\s?Col|Col|Gen|WO1|CW[2-5]|Rct)\.?\s+",
        re.I,
    )

    def parse_donations_post(self, cooked_html):
        """Return (donors, expenses). Each entry: name, last_name, rank, date,
        amount, fee, profile_url (donors only).

        Tables have a header row (#Nr | Name | Date | Amount | Fee | Type | ...),
        so columns are mapped by header text, not by position. The section is
        decided by the nearest preceding "Donations ..." / "Expenses ..." heading.
        """
        soup = BeautifulSoup(cooked_html, "html.parser")
        donors, expenses = [], []
        in_expenses = False

        def make_row(name, date, amount, fee, links, kind=""):
            name = re.sub(r"\s*\d+\s*$", "", name).strip()  # trailing badge counts
            m = self.RANK_RE.match(name)
            rank = m.group(0).strip() if m else ""
            clean = name[m.end():].strip() if m else name
            if not clean or amount is None:
                return None
            parsed = parse_date(date)
            return {
                "name": clean,
                "last_name": clean.split()[-1],
                "rank": rank,
                "date": date.strip(),
                "date_iso": parsed.strftime("%Y-%m-%d") if parsed else date.strip(),
                "amount": amount,
                "fee": fee if fee is not None else 0.0,
                "profile_url": links[0] if links else None,
                "type": kind.strip(),
            }

        for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "strong", "table"]):
            text = el.get_text(" ", strip=True)
            if el.name != "table":
                if re.match(r"^expenses\b", text, re.I):
                    in_expenses = True
                elif re.match(r"^donations\b", text, re.I):
                    in_expenses = False
                continue

            rows = el.find_all("tr")
            if not rows:
                continue
            header = [c.get_text(" ", strip=True).lower()
                      for c in rows[0].find_all(["th", "td"])]

            def col(label, default=None):
                for i, h in enumerate(header):
                    if label in h:
                        return i
                return default

            i_name, i_date = col("name", 1), col("date", 2)
            i_amount, i_fee = col("amount", 3), col("fee", 4)
            i_type = col("type")

            for tr in rows[1:]:
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if len(cells) <= max(i_name, i_date, i_amount):
                    continue
                links = [a["href"] for a in tr.find_all("a", href=True)
                         if "/manage/users/" in a["href"]]
                row = make_row(
                    cells[i_name], cells[i_date], money(cells[i_amount]),
                    money(cells[i_fee]) if i_fee is not None and len(cells) > i_fee else None,
                    links,
                    cells[i_type] if i_type is not None and len(cells) > i_type else "",
                )
                if row:
                    (expenses if in_expenses else donors).append(row)

        return donors, expenses

    # ------------------------------------------- lifetime donated total + rank

    @staticmethod
    def profile_slug(donor):
        """The member's profile slug, taken from the link in the donations post."""
        link = donor.get("profile_url")
        if link:
            return link.rstrip("/").rsplit("/", 1)[-1]
        return donor["last_name"].lower()

    def get_profile(self, donor):
        """Fetch the member's profile once and cache it by slug.

        Returns {'name', 'rank', 'donated'} or None. Repeat donors (and the
        later member-id lookup) reuse the cached copy instead of refetching.

        The /manage/users/<slug> page needs permissions this account may not
        have, but /members/<slug> is public and carries the same details:
            <img alt="PFC" title="Private, First Class">
            <h1 class="user-profile-header__title">
                Private, First Class John A. Doe</h1>
            <dt>Donated</dt><dd>$465</dd>
        """
        slug = self.profile_slug(donor)
        if slug in self._profile_cache:
            return self._profile_cache[slug]

        url = f"{SITE}/members/{slug}"
        r = self.session.get(url, timeout=30)
        if r.status_code != 200:
            self.log(f"  Warning: could not open {url} (status {r.status_code})")
            self._profile_cache[slug] = None
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        header = soup.find(class_=re.compile(r"user-profile-header"))

        rank = rank_full = None
        if header:
            img = header.find("img", alt=True)
            if img:
                rank = (img.get("alt") or "").strip() or None
                rank_full = (img.get("title") or "").strip() or None

        # The heading is "<full rank> <full name>"; drop the rank to get the
        # canonical name the site knows this member by.
        name = None
        title_el = soup.find(class_=re.compile(r"user-profile-header__title"))
        if title_el:
            name = title_el.get_text(" ", strip=True)
            if rank_full and name.lower().startswith(rank_full.lower()):
                name = name[len(rank_full):].strip()

        donated = None
        for dt in soup.find_all("dt", string=re.compile(r"donated", re.I)):
            dd = dt.find_next_sibling("dd")
            if dd:
                donated = money(dd.get_text(" ", strip=True))
                break
        if donated is None:
            self.log(f"  Warning: no Donated value found on {url}")

        # Membership status ("Member", "Retired", ...) and the forum account
        # link (forums.29th.org/user-by-id/<id>/summary), used by the
        # Finance Clerk tab.
        status = forum_url = None
        for dt in soup.find_all("dt"):
            label = dt.get_text(" ", strip=True).lower()
            dd = dt.find_next_sibling("dd")
            if not dd:
                continue
            if label == "status":
                status = dd.get_text(" ", strip=True) or None
            elif label.startswith("forum"):
                a = dd.find("a", href=True)
                forum_url = a["href"] if a else None

        # Possible numeric user ids, from the profile header only (the page nav
        # carries the logged-in user's own id, which must not be picked up).
        # Only ever used to pick between dropdown candidates, never trusted alone.
        ids = set()
        scope = str(header) if header else ""
        for pat in (r"/users/(\d+)", r"data-user-id=[\"'](\d+)", r"user[_-]id[\"'=:\s]+(\d+)"):
            ids.update(re.findall(pat, scope, re.I))

        profile = {"name": name, "rank": rank, "donated": donated,
                   "status": status, "forum_url": forum_url,
                   "ids": sorted(ids)}
        self._profile_cache[slug] = profile
        return profile

    # --------------------------------------------------------- compose posts

    @staticmethod
    def format_block(donor, total):
        parsed = parse_date(donor["date"])
        date = parsed.strftime("%d %B %Y").lstrip("0") if parsed else donor["date"]
        ranked_name = f"{donor['rank']} {donor['last_name']}".strip() \
            if donor.get("rank") else donor["last_name"]
        return (
            f"{ranked_name}, on {date}, your recurring donation of "
            f"${donor['amount']:.2f} was successfully received. The Colonel, as well as "
            f"the entire unit, would like to thank you for your generous donation to the unit.\n\n"
            f"This brings {ranked_name}'s lifetime total up to ${total:.2f}"
            f"\n\n"
            f"![](https://29th.dreamhosters.com/personnel/includes/donated/?amt={total:.2f})\n\n"
            f"___"
        )

    def create_summary_topic(self, title, body):
        if self.dry_run:
            self.log("\n--- DRY RUN: would create topic ---")
            self.log(f"Title: {title}\n\n{body}\n--- end ---")
            return "DRYRUN"
        r = self.session.get(f"{FORUM}/session/csrf.json",
                             headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30)
        csrf = r.json()["csrf"]
        r = self.session.post(
            f"{FORUM}/posts.json",
            data={"title": title, "raw": body, "category": PROMOTIONS_CATEGORY_ID},
            headers={"X-CSRF-Token": csrf, "X-Requested-With": "XMLHttpRequest"},
            timeout=60,
        )
        if r.status_code != 200:
            raise AutomationError(
                f"Failed to create the topic ({r.status_code}): {r.text[:300]}")
        data = r.json()
        topic_id = data["topic_id"]
        self.log(f"  Created topic {topic_id}: "
                 f"{FORUM}/t/{data.get('topic_slug', 'topic')}/{topic_id}")
        return topic_id

    # ------------------------------------------------------- finance records
    #
    # Field names and allowed values come from the personnel-v3 source
    # (github.com/29th/personnel-v3): the form posts finance_record[...]
    # fields to /manage/finance_records; vendor and forum_id are enums
    # submitted by key (e.g. "nuclear_fallout", "discourse").

    VENDOR_PATTERNS = [
        (r"game\s*servers?", "game_servers"),
        (r"branz", "branzone"),
        (r"dream\s*host", "dreamhost"),
        (r"nuclear|fallout", "nuclear_fallout"),
        (r"digital\s*ocean", "digital_ocean"),
        (r"goog|g[o0]+gle", "google"),
    ]
    VENDOR_LABELS = {
        "notapplicable": "N/A", "game_servers": "Game Servers",
        "branzone": "Branzone", "dreamhost": "Dreamhost",
        "nuclear_fallout": "Nuclear Fallout", "digital_ocean": "Digital Ocean, Inc",
        "google": "Google", "other": "Other",
    }

    def match_vendor(self, name):
        """Return (vendor_key, notes). Unknown vendors become Other with the
        original name preserved in Notes."""
        for pattern, key in self.VENDOR_PATTERNS:
            if re.search(pattern, name, re.I):
                return key, ""
        return "other", name

    @staticmethod
    def _name_key(text):
        """Normalise a name for comparison: lowercase words, no punctuation.

        Handles both "Doe, John A." (dropdown) and "John A. Doe"
        (profile/post) by returning a sorted set of word stems.
        """
        text = re.sub(r"\([^)]*\)", " ", text or "")        # drop "(HD 2025-01-13)"
        text = re.sub(r"[^\w\s-]", " ", text).lower()
        return {w for w in text.split() if len(w) > 1}      # ignore initials

    @staticmethod
    def _rank_of(text):
        """Normalised leading rank of a dropdown/post string ('2Lt.' -> '2lt')."""
        m = DonationAutomator.RANK_RE.match((text or "").strip())
        return m.group(0).strip().rstrip(".").lower() if m else ""

    @staticmethod
    def _full_name_key(text):
        """Like _name_key but keeps middle initials ('James A.' -> {'james','a'}),
        and drops the rank so it can't pollute the comparison."""
        text = re.sub(r"\([^)]*\)", " ", text or "")
        text = DonationAutomator.RANK_RE.sub("", text.strip(), count=1)
        text = re.sub(r"[^\w\s-]", " ", text).lower()
        return set(text.split())

    def _narrow_matches(self, matches, name, ranks):
        """Several users share a name: narrow by rank first, then full name
        (including middle initials). A step that would leave nobody is skipped,
        since ranks change with promotions."""
        wanted_ranks = {r for r in (self._rank_of(r + " x") for r in ranks if r) if r}
        by_rank = [x for x in matches if self._rank_of(x["text"]) in wanted_ranks]
        if by_rank:
            matches = by_rank
        if len(matches) > 1:
            wanted = self._full_name_key(name)
            by_name = [x for x in matches if self._full_name_key(x["text"]) >= wanted]
            if by_name:
                matches = by_name
        return matches

    def _user_options(self, term):
        """All dropdown options for a search term, following pagination.

        The endpoint returns a page at a time; without walking the pages a
        common surname (e.g. Smith) hides the member we want.
        """
        if term in self._options_cache:
            return self._options_cache[term]
        # Paging is zero-based: no `page` param is the first page, `page=1` the
        # second, and so on. Asking for page 1 first silently skips everyone.
        results, page = [], 0
        while page <= 20:
            params = {"term": term}
            if page:
                params["page"] = page
            r = self.session.get(
                f"{SITE}/manage/users/all_options",
                params=params,
                headers={"X-Requested-With": "XMLHttpRequest"},
                timeout=30,
            )
            if r.status_code != 200:
                self.log(f"  Warning: user search failed for '{term}' "
                         f"(status {r.status_code})")
                break
            payload = r.json()
            results.extend(payload.get("results", []))
            if not payload.get("pagination", {}).get("more"):
                break
            page += 1
        self._options_cache[term] = results
        return results

    def resolve_member_id(self, donor):
        """Resolve the site's user id for a donor.

        Matches on the canonical name from the member's own profile page (the
        link in the donations post), which can differ from how the post spells
        it, then falls back to the post's name.
        """
        profile = self.get_profile(donor)          # cached; no extra request
        site_name = (profile or {}).get("name")
        names = [n for n in (site_name, donor["name"]) if n]

        for name in names:
            last = name.split()[-1]
            options = self._user_options(last)
            wanted = self._name_key(name)
            exact = [x for x in options if self._name_key(x["text"]) >= wanted]
            if len(exact) == 1:
                return exact[0]["id"]
            if len(exact) > 1:
                ranks = [donor.get("rank"), (profile or {}).get("rank")]
                profile_ids = {str(i) for i in (profile or {}).get("ids", [])}
                self.log(f"  Debug: {len(exact)} users match '{name}' "
                         f"(post rank '{donor.get('rank')}', profile rank "
                         f"'{(profile or {}).get('rank')}', profile name "
                         f"'{site_name}', profile ids {sorted(profile_ids)}):")
                for x in exact:
                    self.log(f"    id={x['id']} rank='{self._rank_of(x['text'])}' "
                             f"text='{x['text']}'")
                narrowed = [x for x in exact if str(x["id"]) in profile_ids]
                how = "profile user id"
                if len(narrowed) != 1:
                    narrowed = self._narrow_matches(exact, name, ranks)
                    how = "rank/full name"
                if len(narrowed) == 1:
                    self.log(f"  Note: picked '{narrowed[0]['text']}' by {how}.")
                    return narrowed[0]["id"]
                exact = narrowed
                self.log(f"  Warning: {len(exact)} users match '{name}': "
                         f"{[x['text'] for x in exact]}")
                return None
            # No full match: fall back to surname + first name.
            first = name.split()[0].lower()
            near = [x for x in options
                    if last.lower() in x["text"].lower()
                    and first in self._name_key(x["text"])]
            if len(near) == 1:
                return near[0]["id"]

        options = self._user_options(donor["last_name"])
        self.log(f"  Warning: no unique user match for '{donor['name']}'"
                 + (f" (site profile says '{site_name}')" if site_name else "")
                 + f"; {len(options)} option(s) searched.")
        return None

    def _new_record_form(self):
        """Fetch the new-record form; return (post_url, base_data with token)."""
        r = self.session.get(f"{SITE}/manage/finance_records/new", timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form", action=re.compile(r"finance_records"))
        if form is None:
            raise AutomationError("Finance record form not found — check permissions.")
        action = form.get("action") or "/manage/finance_records"
        data = {inp["name"]: inp.get("value", "")
                for inp in form.find_all("input", attrs={"name": True})
                if inp.get("type") in (None, "hidden", "text", "number")}
        # Textareas must be sent too. `notes` is NOT NULL in the database with
        # no default, so omitting it makes the insert fail with a 500.
        for area in form.find_all("textarea", attrs={"name": True}):
            data[area["name"]] = area.get_text() or ""
        data["commit"] = "Create Finance record"
        return (SITE + action if action.startswith("/") else action), data

    def submit_record(self, fields, description):
        if self.dry_run:
            self.log(f"  DRY RUN finance record ({description}): {fields}")
            return True
        url, data = self._new_record_form()
        data.update(fields)
        r = self.session.post(url, data=data, timeout=60, allow_redirects=False)
        if r.status_code in (302, 303):
            self.log(f"  OK: {description}")
            return True
        if r.status_code >= 500:
            # The site itself errored. Nothing was saved (the exception rolls
            # the transaction back), so this is not a duplicate risk.
            req_id = r.headers.get("x-request-id", "n/a")
            self.log(f"  FAILED ({r.status_code}): {description} — the personnel "
                     f"site returned a server error; nothing was saved. "
                     f"Request id {req_id}", "error")
            return False
        # Rails re-renders the form with errors on validation failure.
        errors = BeautifulSoup(r.text, "html.parser").find_all(class_=re.compile("error"))
        msg = "; ".join(e.get_text(" ", strip=True) for e in errors[:3]) or "(no message)"
        self.log(f"  FAILED ({r.status_code}): {description} — {msg[:200]}")
        return False

    def submit_donation_record(self, donor, topic_id):
        member_id = self.resolve_member_id(donor)
        if member_id is None:
            self.log(f"  Skipped {donor['name']}: no matching user on the site.")
            return False
        return self.submit_record({
            "finance_record[date]": donor["date_iso"],
            "finance_record[member_id]": str(member_id),
            "finance_record[vendor]": "notapplicable",
            "finance_record[amount_received]": f"{donor['amount']:.2f}",
            "finance_record[fee]": f"{donor['fee']:.2f}",
            "finance_record[forum_id]": "discourse",
            "finance_record[topic_id]": str(topic_id),
        }, f"donation {donor['name']} ${donor['amount']:.2f}")

    def submit_expense_record(self, expense):
        vendor_key, notes = self.match_vendor(expense["name"])
        fields = {
            "finance_record[date]": expense["date_iso"],
            "finance_record[vendor]": vendor_key,
            "finance_record[amount_paid]": f"{expense['amount']:.2f}",
            "finance_record[fee]": f"{expense['fee']:.2f}",
        }
        if notes:
            fields["finance_record[notes]"] = notes
        return self.submit_record(
            fields, f"expense {expense['name']} ${expense['amount']:.2f} "
                    f"(vendor: {self.VENDOR_LABELS[vendor_key]})")

    # ------------------------------------------------------------- phase one

    def prepare(self, url=None):
        """Read-only phase: log in, parse the post, compose the summary.

        Returns a plan dict: source_topic, title, body, donors, expenses.
        Nothing is written to either site.
        """
        self.login()

        topic = self.get_topic(self.topic_id_from_url(url)) if url \
            else self.get_latest_donations_topic()
        self.log(f"Source topic: {topic['title']} (id {topic['id']})")

        donors, expenses = self.parse_donations_post(topic["cooked"])
        if not donors and not expenses:
            raise AutomationError(
                "No donations or expenses could be read from that post. "
                "Check that the link points to a donations topic with a table.")
        self.log(f"Parsed {len(donors)} donor(s), {len(expenses)} expense(s).")

        blocks = []
        for d in donors:
            profile = self.get_profile(d) or {}
            donated = profile.get("donated")
            if donated is None:
                donated = 0.0
                self.log(f"  Warning: no prior Donated total for {d['name']}; "
                         f"lifetime total will only reflect this donation.")
            # Rank from the post's Name column wins; else the member page's.
            if not d.get("rank") and profile.get("rank"):
                d["rank"] = profile["rank"]
            # The site's own spelling of the name, used to match the member later.
            if profile.get("name"):
                d["site_name"] = profile["name"]
                if profile["name"] != d["name"]:
                    self.log(f"  Note: post says '{d['name']}', site profile says "
                             f"'{profile['name']}'.")
                d["last_name"] = profile["name"].split()[-1]
            d["lifetime_total"] = donated + d["amount"]
            blocks.append(self.format_block(d, d["lifetime_total"]))

        for e in expenses:
            key, notes = self.match_vendor(e["name"])
            e["vendor_key"], e["vendor_label"] = key, self.VENDOR_LABELS[key]
            e["notes"] = notes

        m = re.search(r"Donations\s+(.+)", topic["title"], re.I)
        title = f"Donations ({m.group(1).strip()})" if m else topic["title"]

        return {"source_topic": topic["id"], "source_title": topic["title"],
                "title": title, "body": "\n\n".join(blocks),
                "donors": donors, "expenses": expenses}

    # ------------------------------------------------------------- phase two

    def execute(self, plan, existing_topic_id=None):
        """Write phase: create the summary topic, then submit finance records.

        Pass existing_topic_id to reuse a topic that was already posted (e.g.
        when the post went up but the records failed) instead of creating a
        duplicate.
        """
        self.login()

        if existing_topic_id:
            topic_id = str(existing_topic_id).strip()
            self.log(f"Using existing topic {topic_id} — no new post will be created.")
        else:
            topic_id = self.create_summary_topic(plan["title"], plan["body"])
            if not topic_id:
                raise AutomationError("Topic creation failed; no records were submitted.")

        donors, expenses = plan["donors"], plan["expenses"]
        self.log(f"Submitting {len(donors)} donation record(s)...")
        ok = sum(self.submit_donation_record(d, topic_id) for d in donors)
        if expenses:
            self.log(f"Submitting {len(expenses)} expense record(s)...")
        ok_exp = sum(self.submit_expense_record(e) for e in expenses)

        self.log(f"\nDone. Donations {ok}/{len(donors)}, "
                 f"expenses {ok_exp}/{len(expenses)}.")

        results = {"timestamp": datetime.now().isoformat(),
                   "source_topic": plan["source_topic"], "summary_topic": topic_id,
                   "donations_ok": ok, "expenses_ok": ok_exp,
                   "donors": donors, "expenses": expenses}
        if not self.dry_run:
            with open(app_file("automation_results.json"), "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, default=str)
            self.log("Audit trail written to automation_results.json")
        return results

    def run(self, url=None, existing_topic_id=None):
        plan = self.prepare(url)
        self.execute(plan, existing_topic_id=existing_topic_id)
        return 0


CREDENTIALS_FILE = "credentials.json"


def load_credentials(path=None):
    with open(path or app_file(CREDENTIALS_FILE), encoding="utf-8") as f:
        creds = json.load(f)
    return creds["username"], creds["password"]


def save_credentials(username, password, path=None):
    path = path or app_file(CREDENTIALS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"username": username, "password": password}, f, indent=2)
    return path


def delete_credentials(path=None):
    """Remove the saved credentials file. Returns True if one was deleted."""
    path = path or app_file(CREDENTIALS_FILE)
    try:
        os.remove(path)
    except FileNotFoundError:
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description="29th ID donation automation")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse and preview everything without posting or submitting")
    ap.add_argument("--url", help="Donations topic URL (default: latest in category)")
    ap.add_argument("--topic-id", help="Reuse an already-posted summary topic id "
                                       "instead of creating a new post")
    args = ap.parse_args()

    try:
        username, password = load_credentials()
    except FileNotFoundError:
        print('credentials.json not found. Create it with:\n'
              '  {"username": "YourForumUsername", "password": "..."}')
        return 1

    bot = DonationAutomator(username, password, dry_run=args.dry_run)
    try:
        return bot.run(args.url, existing_topic_id=args.topic_id)
    except AutomationError as e:
        print(f"\nError: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
