# 29th Infantry Division — Finance Department

The Finance Department (Finance Corps) of the 29th Infantry Division keeps the
unit's finances in order. The unit runs on its members' donations, which pay for
the game servers, the website and the other services the unit uses. The
department records every donation and expense, thanks the members who donate,
and gives recurring donors the weapons passes their donations earn them.

The weekly work follows the same steps each time:

- A **Finance Officer** reads the weekly donations post in *Finance Office ›
  Finance Donations*, publishes the acknowledgment post in *Promotions & Awards*
  and files a finance record for every donation and expense on the personnel
  site.
- A **Finance Clerk** gives each recurring donor their weapons pass on the
  personnel site, sends the donors a PM about it and confirms in the donations
  topic that the passes were processed.

The **29th Finance Officer app** automates both jobs. It is a desktop app with
one tab per role. Each tab reads the donations post, shows a preview you can
check and correct, and only writes to the forum and the personnel site when you
confirm.

---

## Contents

- [Before you start](#before-you-start)
- [Downloading the app](#downloading-the-app)
- [Building the app](#building-the-app)
  - [Windows](#windows)
  - [macOS](#macos)
  - [Linux](#linux)
  - [Running from source](#running-from-source-without-building)
- [Signing in and credentials](#signing-in-and-credentials)
- [Where the app keeps its files](#where-the-app-keeps-its-files)
- [Checking for errors](#checking-for-errors)
- [Good practice](#good-practice)
- [Finance Officer — Donations tab](#finance-officer--donations-tab)
- [Finance Clerk — Weapon Passes tab](#finance-clerk--weapon-passes-tab)
- [Command line](#command-line)
- [Making a release](#making-a-release)
- [For developers](#for-developers)

---

## Before you start

You need:

- **A forums.29th.org account** with access to the Finance Office category. The
  personnel site (www.29th.org) signs you in through the forum, so there is no
  second password.
- **Permissions on the personnel site** for the job you do: *Finance Records*
  for the Finance Officer tab, *Passes* for the Finance Clerk tab.
- **The app itself.** Most people download a ready-made app (see
  [Downloading the app](#downloading-the-app)), which needs nothing else.
  Building it yourself needs Python 3.10 or newer with Tkinter (the window
  library), on the operating system you want to run the app on.

---

## Downloading the app

Ready-made apps for Windows, Mac and Linux are on the
[**Releases page**](https://github.com/OsakaDS/29th-Finance/releases). Download
them **only from there**, never from a file someone sends you. GitHub builds
every release from the code in this repository.

| System | File | How to open it |
|---|---|---|
| Windows | `29th-Donations-Windows.zip` | Unzip it, then double-click `29th Donations.exe`. |
| Mac (Apple chip, M1 or later) | `29th-Donations-macOS.zip` | Double-click the zip, then drag `29th Donations.app` to *Applications*. |
| Linux | `29th-Donations-Linux.tar.gz` | Run `tar -xzf 29th-Donations-Linux.tar.gz`, then `"./29th Donations"`. |

The apps aren't signed, so the first time you open one:

- **Windows:** if SmartScreen warns about it, click **More info › Run anyway**.
- **Mac:** if it says the app can't be opened, go to *System Settings › Privacy
  & Security*, scroll down and click **Open Anyway** next to *29th Donations*.
  On macOS 14 and earlier, right-clicking the app and choosing **Open** also
  works.

After that it opens normally.

**Check your download (optional).** Each release lists a SHA-256 checksum for
every file. Work out the checksum of the file you downloaded and compare it
with the one on the release. If it doesn't match, don't open the file.

- Windows (PowerShell):
  ```bash
  Get-FileHash 29th-Donations-Windows.zip -Algorithm SHA256
  ```
- Mac:
  ```bash
  shasum -a 256 29th-Donations-macOS.zip
  ```
- Linux:
  ```bash
  sha256sum 29th-Donations-Linux.tar.gz
  ```

---

## Building the app

PyInstaller turns the app into a standalone program. It can only build for the
system it runs on: build the Windows app on Windows, the Mac app on a Mac and
the Linux app on Linux.

**Always build from the latest code**, and rebuild after every update. Builds
are never committed: `build/` and `dist/` are created on your computer when you
build.

Download the code first, either with `git clone` or with GitHub's *Code ›
Download ZIP*, then open a terminal in that folder.

### Windows

1. Install Python from [python.org](https://www.python.org/downloads/windows/).
   In the installer, tick **Add python.exe to PATH**. Keep **tcl/tk and IDLE**
   ticked, because the app needs it.
2. In PowerShell or Command Prompt, in the project folder, run:
   ```bash
   py -m pip install -r requirements.txt
   ```
   ```bash
   py build_app.py
   ```
3. The result is **`dist\29th Donations.exe`**, a single file of about 25 MB.
   Copy it anywhere and double-click it.

If the app is still open, Windows won't let the build replace it. Close the app
first, or run `py build_app.py --force` to close it for you.

The app isn't signed, so Windows SmartScreen may warn about it the first time.
Click **More info › Run anyway**.

Put an `app.ico` next to `build_app.py` before building to give the app an icon.

### macOS

1. In Terminal, in the project folder, run:
   ```bash
   ./build_mac.sh
   ```
   The script finds a Python that has Tkinter. If your Homebrew Python is
   missing it, the script installs `python-tk`. It then sets up a `.venv`,
   installs the requirements and builds the app. If it says no suitable Python
   was found, install Python from
   [python.org](https://www.python.org/downloads/macos/) and run it again.
2. The result is **`dist/29th Donations.app`**. Drag it to *Applications*.
3. The app isn't signed. The first time you open it, allow it as described in
   [Downloading the app](#downloading-the-app).

Put an `app.icns` next to `build_app.py` before building to give the app an icon.

### Linux

1. Install Python with Tkinter and venv. On Debian or Ubuntu:
   ```bash
   sudo apt install python3 python3-tk python3-venv
   ```
   (Fedora: `sudo dnf install python3 python3-tkinter`.)
2. In the project folder:
   ```bash
   python3 -m venv .venv
   ```
   ```bash
   .venv/bin/python -m pip install -r requirements.txt
   ```
   ```bash
   .venv/bin/python build_app.py
   ```
3. The result is **`dist/29th Donations`**, a single executable of about 15 MB.
   Start it from a terminal:
   ```bash
   "./dist/29th Donations"
   ```
   Some file managers will also start it with a double-click.

### Running from source (without building)

After installing the requirements as above, start the window directly:

```bash
python donation_gui.py
```

On a Mac, once `./build_mac.sh` has run, use `.venv/bin/python donation_gui.py`.

---

## Signing in and credentials

The app uses your **forums.29th.org username and password**. Both tabs share
the same sign-in.

- **The login screen:** the app opens on a login box, and the tabs stay hidden
  until you sign in. The app checks your username and password with the forum
  itself, so a wrong password is caught straight away and the box says why.
- **Remember me:** ticked, your login is saved in `credentials.json`, and the
  next time you open the app it signs you in automatically. If the saved login
  no longer works (for example, after a password change), the login box opens
  with the error. Unticked, nothing is saved and you sign in every time.
- **Sign out:** the bar above the tabs shows *Signed in as …* and a **Sign
  out** button. Signing out clears both tabs, deletes the saved login and
  returns to the login box, so someone else can sign in with their own
  account. You can't sign out while a tab is still working.
- **Command line:** the scripts read the same file. You can also create it by
  hand:
  ```json
  { "username": "YourForumUsername", "password": "..." }
  ```

Keep your credentials safe:

- `credentials.json` holds your password in **plain text**. Don't put it in a
  shared or synced folder, and never send it to anyone.
- The built app never contains a password, so it is safe to copy to another
  computer. Each person signs in with their own account.
- `credentials.json` is listed in `.gitignore`, so it is never committed. Never
  remove it from that list.
- If your password may have leaked, change it on the forum and click **Sign
  out** in the app.

---

## Where the app keeps its files

| File | What it is |
|---|---|
| `credentials.json` | Your saved sign-in, if you ticked *Remember me* |
| `automation_results.json` | Audit trail of the last real Finance Officer run |
| `finance_clerk_automation_results.json` | Audit trail of the last real Finance Clerk run |
| `finance_clerk_settings.json` | Finance Clerk setup: PM text, reply, finance officers, opt-out link |
| `startup-error.log` | Written only if the built app crashes as it opens |
| `passes_list_debug.html` | Written only if the passes list on the personnel site can't be read |

Where these files are depends on how you run the app:

| Running the app as | Folder |
|---|---|
| Windows `.exe` or Linux executable | The folder the app is in |
| macOS `.app` | `~/Library/Application Support/29th Donations` |
| From source (`python donation_gui.py`) | The project folder |

All of these files are listed in `.gitignore`.

---

## Checking for errors

**The Activity pane.** Each tab logs every step at the bottom of the window.
Normal steps are white, **successes are green**, **warnings are amber** (look
at these, but nothing failed) and **failures are red**. When something goes
wrong a dialog box also appears. The full explanation is in the Activity pane.

**Dry run.** Tick **Dry run (don't write anything)** to run everything without
writing. Nothing is posted, filed, created or sent, and the Activity pane shows
exactly what would have happened.

**Audit files.** After each real run, `automation_results.json` (Finance
Officer) and `finance_clerk_automation_results.json` (Finance Clerk) record
what was read, what was written and the result of every step. Open them in any
text editor to check a run afterwards, or to see what still needs doing by
hand.

**The app doesn't open.** Look for `startup-error.log` (see
[where the app keeps its files](#where-the-app-keeps-its-files)), which says
what went wrong. *"No module named '_tkinter'"* means the Python used to build
had no Tkinter. Install Python with Tkinter as described in
[Building the app](#building-the-app) and rebuild. On a Mac, running
`./build_mac.sh` again fixes this.

**Common messages**

| Message | What to do |
|---|---|
| *Forum login failed* (on the login box) | Check the username and password. The app uses your normal forum login. |
| *Could not reach forums.29th.org* | Check your internet connection and try again. |
| *Site login failed … may lack the permissions* | Your account can't open the Finance Records page (Finance Officer tab) or the New Pass page (Finance Clerk tab). Ask for the permission. |
| *Could not open topic* | Check the link, and check that your account can read that category. |
| *No donations or expenses could be read* | The link doesn't point at a donations topic with a table. |
| *Skipped … no matching user* | The name in the post didn't match exactly one member on the site. Do that one by hand. Everything else still goes through. |
| *Could not read the passes list* | The Finance Clerk tab couldn't read www.29th.org/manage/passes?scope=all, so it stopped without writing anything. Send `passes_list_debug.html` and the Activity lines to whoever maintains the app. |
| *The New Pass form has changed* | The New Pass form on the personnel site changed. The message lists the fields it found. Send it to whoever maintains the app. |
| *The forum asks to wait N s* | The forum limits how fast you can post. The app waits and sends again by itself. |
| *request … failed …; retrying* | The connection was slow. Reads are retried automatically. |

**Reporting a problem.** Send the red lines from the Activity pane, the audit
file of that run and, if there is one, `startup-error.log` or
`passes_list_debug.html`. Never send `credentials.json`.

---

## Good practice

- **Dry run first.** When the donations post looks unusual, or after the app
  has been updated, tick **Dry run**, check the Activity pane, then run it for
  real.
- **Read the preview.** The app finds members by name and rank. Before you
  submit, check the names, amounts, dates and every amber note.
- **Run each donations post once per tab.** After a real run, the tab clears
  the preview so it can't be submitted twice. The Finance Clerk tab also checks
  for existing passes. Still, don't load the same post again to "try once
  more". Check the audit file and finish anything left by hand.
- **Finish failures by hand.** If one record, pass or PM fails, the rest still
  go through, and the Activity pane says exactly what is left to do.
- **Keep the app up to date.** Download the latest code and rebuild. Don't pass
  around old copies of the app.
- **One account, one person.** Sign in with your own account, so the forum and
  the personnel site show who did the work.

---

## Finance Officer — Donations tab

The Finance Officer tab reads the weekly donations post, publishes the
acknowledgment post and files the finance records.

### How to use it

1. **Paste the link** to the weekly donations topic, for example
   `https://forums.29th.org/t/donations-july-26-august-1/12345`. Leave the box
   empty to use the most recent donations post.
2. Click **Load preview**. The app reads the post, looks up each donor's rank
   and lifetime donated total, and shows the exact acknowledgment post. The
   title and the text can both be edited, and whatever is in the box when you
   submit is what gets posted.
3. Click **Submit post + records**. After a confirmation dialog, the app:
   - creates the acknowledgment topic in *Promotions & Awards*. Each donor gets
     a thank-you block with their new lifetime total;
   - files a **finance record** for every donation (Forum = Discourse, Topic
     ID = the new topic);
   - files a **finance record** for every expense, with the vendor matched
     automatically.
4. Click **Open created topic** to see the new post in your browser.

**The post was created but the records failed?** Enter the topic's number in
**Post already exists? Reuse topic ID** and submit again. The records are filed
against that topic and no second post is made.

### How it reads the post

- **Tables** are read by their header row (`#Nr | Name | Date | Amount | Fee |
  Type …`), so the column order can change. An `Expenses …` heading switches
  from donors to expenses, so one post can contain both.
- **Ranks** (`T/4`, `FSgt.`, `Cpl.` …) are split off the name. **Lifetime
  totals** come from each member's public profile
  (`www.29th.org/members/<name>`). The acknowledgment shows the previous total
  plus this week's donation.
- **Members** are matched to the personnel site by their profile name. If
  several members share a name, rank and full name decide. If the app still
  can't tell, it skips the donor and says so.
- **Vendors** are matched by pattern, so partial names and typos still land on
  the right option: "NuclearFallout Enterprises" → Nuclear Fallout, "Dream
  host" → Dreamhost, "DigitalOcean" → Digital Ocean, Inc. An unknown vendor
  becomes **Other**, with its name in the record's Notes.
- **Safety:** reads retry on timeouts, but writes never retry, so a slow
  connection can't create a duplicate post or record. If the topic can't be
  created, no records are filed.

---

## Finance Clerk — Weapon Passes tab

The Finance Clerk tab gives recurring donors their weapons passes, sends them a
PM about it and replies in the donations topic.

### The rules

| Recurring donation | Weapons pass |
|---|---|
| under $5 | none |
| $5 – $14.99 | one week (Sunday – Saturday) |
| $15 and above | two weeks |

- **Leadership gets no pass.** That means Cpl. and above. T/5, T/4, T/3 and T/2
  are not leadership.
- **Retired members get no pass.** Rank and status come from each member's
  current profile on www.29th.org, not from the post.
- **Members who opted out** of the PM still get their pass, but no PM. The list
  is a forum topic in the Finance Office.

### First-time setup

Names and links that belong to the unit are not in the code. You enter them
once on each computer, and they are saved in `finance_clerk_settings.json`,
which is never committed:

1. **Finance officers:** in *Finance officers (member pages)*, enter the
   member-page names of the Chief and the Assistant Chief Finance Officer,
   separated by a comma. For example, `smith, jones` means
   www.29th.org/members/smith and …/jones.
2. **Signature:** in the PM text, add your signature image above the closing
   lines, as you would in a forum post.
3. Click **Save PM/officers as default**.
4. **Opt-out list:** the first time you click **Open opt-out list**, paste the
   link to the opt-out topic. It is saved straight away.

Until the officers are set, **Load preview** stops and tells you to set them.

### How to use it

1. **Paste the link** to the donations topic, or leave the box empty for the
   latest. Then choose the **pass week**: *This week* or *Next week*. The exact
   dates of one-week and two-week passes are shown next to each choice.
2. Click **Load preview**. The table lists every donor:

   | Column | Shows |
   |---|---|
   | Pass / PM | ☑ will get it, ☐ won't, — can't (see Notes) |
   | Tier, Pass dates | The pass the donation earns, and its dates |
   | Forum user | The account the PM goes to, from the member's profile |
   | Notes | Why a donor is left out: below $5, leadership, retired, duplicate … |

   Rows in **red** already have this exact pass (see below). **Amber** rows are
   left out by the rules. **Grey** rows can't get a pass.
3. Check the table:
   - Click **Open opt-out list** and **untick PM** (double-click it) for anyone
     on that list. Adding people to the list stays manual.
   - Double-click **Pass** to change it. The app asks you to confirm before it
     breaks a rule.
   - Changing the week updates every date straight away.
4. Check the **PM** text on the left. `{start}` and `{end}` become the pass
   dates. The **Will be sent** box on the right shows every pass, with its
   reason, and every PM with its recipients.
5. Click **Create passes + send PMs**. After a confirmation, the app:
   - creates a **Recurring Donation** pass on www.29th.org/manage/passes for
     each ticked donor, with the reason, for example
     `T/5 Doe recurrently donated 10 dollars on the 16th of November`;
   - checks the passes list again to confirm every new pass is really there;
   - sends one **Weapon Pass** PM per set of dates. The recipients are those
     donors plus the Chief and Assistant Chief Finance Officer;
   - replies **Weapon passes processed!** in the donations topic.

### Duplicates

The app reads www.29th.org/manage/passes?scope=all when you load the preview,
and again right before writing. A member can be on that page several times, as
long as the Start Date, End Date or Type differ. A donor who already has a pass
with the **same Start Date, End Date and Type** is shown in red as an error,
and nothing is written for them. If the page can't be read, the app stops
before writing anything rather than guess.

### When something fails

If a pass or a PM fails, the rest still go through. The reply is then **not**
posted, so you can finish by hand first: create the missing pass, send the PM,
then reply in the topic. The Activity pane and
`finance_clerk_automation_results.json` list what was done and what wasn't.

### Settings

The PM text, the reply and the **finance officers** can be edited on the tab.
The PM goes to the officers' forum accounts, found through their profiles. The
app only follows profile links to forums.29th.org. When the Chief or Assistant
Chief Finance Officer changes, update the field and save again. **Save
PM/officers as default** stores your changes in `finance_clerk_settings.json`,
along with the opt-out link. Delete that file to start the setup again.

---

## Command line

Both jobs can also run without the window. They read the same
`credentials.json`.

```bash
python donation_automation.py --dry-run          # Finance Officer: preview only
```
```bash
python donation_automation.py --url <topic-url>  # Finance Officer: a specific post (default: latest)
```
```bash
python finance_clerk.py --dry-run --url <topic-url> --week next   # Finance Clerk: preview only
```

Leave out `--dry-run` to write for real. `donation_automation.py --topic-id
<id>` reuses an existing acknowledgment topic.

---

## Making a release

Releases are built automatically by GitHub Actions
(`.github/workflows/release.yml`). Nobody needs to build the apps on their own
computer, and nobody needs a Windows PC.

1. Open the [Releases page](https://github.com/OsakaDS/29th-Finance/releases)
   and click **Draft a new release**.
2. Under **Choose a tag**, type the new version and click **Create new tag**.
   Use `v1.0.1` for fixes and `v1.1.0` for new features. The target is `main`.
3. Give it a title, and write what changed in the description.
4. Click **Publish release**.

GitHub then builds the Windows, Mac and Linux apps, which takes about 10
minutes. It attaches them and `SHA256SUMS.txt` to the release, and adds the
checksums and a link to the build log to the description. You can follow the
build on the **Actions** tab. If a build fails, its log there shows why. Fix
the problem, delete the release and its tag, and publish it again.

**Test build without releasing:** on the **Actions** tab, open *Build and
release* and click **Run workflow**. The three files appear under that run's
*Artifacts* for 14 days. Nothing is published. Every pull request gets the same
test build automatically, so check that its three builds pass before merging.

---

## For developers

| File | What it does |
|---|---|
| `donation_gui.py` | Starts the app; the Donations tab |
| `login_gui.py` | The login screen, the account bar with **Sign out**, and the tabs around them |
| `donation_automation.py` | Finance Officer logic: login, reading posts and profiles, posting, finance records |
| `finance_clerk_gui.py` | The Finance Clerk tab |
| `finance_clerk.py` | Finance Clerk logic: tiers, duplicates, passes, PMs, reply |
| `build_app.py` | Builds the app with PyInstaller (Windows, macOS, Linux) |
| `build_mac.sh` | One-step macOS build |
| `.github/workflows/release.yml` | Builds all three apps on GitHub and attaches them to each release |
| `requirements.txt` | Python packages: `requests`, `beautifulsoup4`, `pyinstaller` |

- Each tab works in two phases: `prepare()` only reads and builds the preview,
  and `execute()` writes. Keep any new write in `execute()`, and make it
  respect `dry_run`.
- Network calls run on a background thread. Only the window thread touches the
  window. Results come back through a queue.
- The forum is Discourse, and posts go through its JSON API. The personnel site
  is Active Admin. Its forms are read from the page (`/manage/.../new`) rather
  than hard-coded, so small changes to the site are reported clearly.
- Never commit `credentials.json`, the audit files or the settings file. They
  are in `.gitignore`.
- Work on a branch and open a pull request.
