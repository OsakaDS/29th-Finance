"""
29th Infantry Division - Finance Clerk tab (weapon passes)
==========================================================
Second tab of the Finance Officer app. Shares the signed-in account with the
Donations tab; keeps its own activity log, dry-run switch and audit file
(finance_clerk_automation_results.json).
"""

import queue
import sys
import threading
import traceback
import webbrowser
from datetime import timedelta

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from donation_automation import FORUM, AutomationError
from finance_clerk import (PM_TITLE, RESULTS_FILE, FinanceClerk,
                           apply_week, load_settings, pm_groups, render_pm,
                           save_settings, week_start)

PAD = 10
MONO, SIZE = ("Menlo", 12) if sys.platform == "darwin" else ("Consolas", 10)
CHECK, EMPTY, LOCKED = "☑", "☐", "—"

COLUMNS = (
    ("pass", "Pass", 46, "center"),
    ("pm", "PM", 40, "center"),
    ("donor", "Donor", 150, "w"),
    ("amount", "Amount", 70, "e"),
    ("donated", "Donated on", 90, "w"),
    ("tier", "Tier", 70, "w"),
    ("dates", "Pass dates", 150, "w"),
    ("forum", "Forum user", 100, "w"),
    ("note", "Notes", 260, "w"),
)


class FinanceClerkTab:
    def __init__(self, root, parent, app):
        self.root = root
        self.parent = parent
        self.app = app              # the Donations view: owns the credentials
        self.clerk = None
        self.plan = None
        self.busy = False
        self.messages = queue.Queue()
        self.results = queue.Queue()
        self.settings = load_settings()
        self._build_widgets()
        self._update_week_labels()
        self.root.after(100, self._drain)

    # --------------------------------------------------------------- layout

    def _build_widgets(self):
        p = self.parent
        p.columnconfigure(0, weight=1)
        p.rowconfigure(3, weight=3)
        p.rowconfigure(4, weight=2)
        p.rowconfigure(6, weight=1)

        top = ttk.Frame(p, padding=(PAD, PAD, PAD, 0))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Donations post:").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(top, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=6)
        self.url_entry.bind("<Return>", lambda _e: self.on_preview())
        self.preview_btn = ttk.Button(top, text="Load preview", command=self.on_preview)
        self.preview_btn.grid(row=0, column=2)
        ttk.Label(top, foreground="#666",
                  text=f"e.g. {FORUM}/t/donations-november-15-november-21/12345   "
                       "(leave blank to use the latest post)"
                  ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # Week choice, with the exact dates so they can be checked.
        week = ttk.Frame(p, padding=(PAD, 6, PAD, 0))
        week.grid(row=1, column=0, sticky="ew")
        ttk.Label(week, text="Pass week:").grid(row=0, column=0, sticky="w")
        self.week_var = tk.StringVar(value="next")
        self.week_labels = {}
        for i, choice in enumerate(("this", "next")):
            lbl = tk.StringVar()
            self.week_labels[choice] = lbl
            ttk.Radiobutton(week, textvariable=lbl, value=choice, variable=self.week_var,
                            command=self.on_week_change).grid(row=i, column=1,
                                                              sticky="w", padx=(8, 0))
        ttk.Label(week, foreground="#666",
                  text="Tiers: under $5 no pass • $5–$14.99 one week • $15+ two weeks "
                       "• no passes for Cpl.+ leadership or retired members"
                  ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 0))

        self.summary_var = tk.StringVar(
            value="No post loaded yet — paste the donations post link and click Load preview.")
        ttk.Label(p, textvariable=self.summary_var, padding=(PAD, 6, PAD, 0),
                  font=("TkDefaultFont", SIZE - 1, "bold")).grid(row=2, column=0, sticky="w")

        # Donor table.
        table = ttk.LabelFrame(p, text="Donors — double-click Pass or PM to tick/untick "
                                        "(untick PM for members on the opt-out list)",
                               padding=(6, 4))
        table.grid(row=3, column=0, sticky="nsew", padx=PAD, pady=(4, 0))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS],
                                 show="headings", height=8)
        for key, label, width, anchor in COLUMNS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=key in ("note", "donor"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        ts = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        ts.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=ts.set)
        self.tree.tag_configure("blocked", foreground="#999")
        self.tree.tag_configure("error", foreground="#c0392b")
        self.tree.tag_configure("off", foreground="#a06010")
        self.tree.bind("<Double-1>", self.on_toggle)

        # Messages: editable PM template + what will be sent.
        msgs = ttk.Frame(p, padding=(PAD, 6, PAD, 0))
        msgs.grid(row=4, column=0, sticky="nsew")
        msgs.columnconfigure(0, weight=3)
        msgs.columnconfigure(1, weight=2)
        msgs.rowconfigure(0, weight=1)

        tpl = ttk.LabelFrame(msgs, text=f"PM '{PM_TITLE}' (editable — {{start}} and "
                                        f"{{end}} become the pass dates)", padding=(6, 4))
        tpl.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tpl.columnconfigure(0, weight=1)
        tpl.rowconfigure(0, weight=1)
        self.tpl_text = tk.Text(tpl, wrap="word", height=8, font=(MONO, SIZE - 1), undo=True)
        self.tpl_text.grid(row=0, column=0, sticky="nsew")
        tsc = ttk.Scrollbar(tpl, orient="vertical", command=self.tpl_text.yview)
        tsc.grid(row=0, column=1, sticky="ns")
        self.tpl_text.configure(yscrollcommand=tsc.set)
        self.tpl_text.insert("1.0", self.settings["pm_template"])

        out = ttk.LabelFrame(msgs, text="Will be sent", padding=(6, 4))
        out.grid(row=0, column=1, sticky="nsew")
        out.columnconfigure(0, weight=1)
        out.rowconfigure(0, weight=1)
        self.out_text = tk.Text(out, wrap="word", height=8, font=(MONO, SIZE - 1),
                                state="disabled", background="#1e1e1e",
                                foreground="#d4d4d4", insertbackground="#d4d4d4")
        self.out_text.grid(row=0, column=0, sticky="nsew")

        reply = ttk.Frame(msgs)
        reply.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        reply.columnconfigure(1, weight=1)
        reply.columnconfigure(3, weight=1)
        ttk.Label(reply, text="Reply in donations topic:").grid(row=0, column=0, sticky="w")
        self.reply_var = tk.StringVar(value=self.settings["reply_text"])
        ttk.Entry(reply, textvariable=self.reply_var).grid(row=0, column=1, sticky="ew",
                                                           padx=(6, 10))
        ttk.Label(reply, text="Finance officers (member pages):").grid(row=0, column=2,
                                                                      sticky="w")
        self.officers_var = tk.StringVar(value=", ".join(self.settings["finance_officers"]))
        ttk.Entry(reply, textvariable=self.officers_var).grid(row=0, column=3, sticky="ew",
                                                              padx=(6, 0))

        # Actions.
        actions = ttk.Frame(p, padding=(PAD, PAD, PAD, 0))
        actions.grid(row=5, column=0, sticky="ew")
        actions.columnconfigure(4, weight=1)
        self.submit_btn = ttk.Button(actions, text="Create passes + send PMs",
                                     command=self.on_submit, state="disabled")
        self.submit_btn.grid(row=0, column=0)
        self.dry_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions, text="Dry run (don't write anything)",
                        variable=self.dry_var).grid(row=0, column=1, padx=(10, 0))
        ttk.Button(actions, text="Open opt-out list",
                   command=self.on_open_opt_out).grid(row=0, column=2, padx=(10, 0))
        ttk.Button(actions, text="Save PM/officers as default",
                   command=self.on_save_settings).grid(row=0, column=3, padx=(6, 0))
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=5, sticky="e")

        logframe = ttk.LabelFrame(p, text="Activity", padding=(6, 4))
        logframe.grid(row=6, column=0, sticky="nsew", padx=PAD, pady=(6, 0))
        logframe.columnconfigure(0, weight=1)
        logframe.rowconfigure(0, weight=1)
        self.log_text = tk.Text(logframe, wrap="word", height=6, state="disabled",
                                font=(MONO, SIZE - 1), background="#1e1e1e",
                                foreground="#d4d4d4")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        ls = ttk.Scrollbar(logframe, orient="vertical", command=self.log_text.yview)
        ls.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=ls.set)
        self.log_text.tag_configure("warn", foreground="#e5c07b")
        self.log_text.tag_configure("error", foreground="#e06c75")
        self.log_text.tag_configure("ok", foreground="#98c379")

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(p, textvariable=self.status_var, relief="sunken", anchor="w",
                  padding=(6, 3)).grid(row=7, column=0, sticky="ew", padx=PAD,
                                       pady=(6, PAD))

    # ------------------------------------------------------------ threading

    def log(self, message, tag=None):
        self.messages.put((str(message), tag))

    def _drain(self):
        while True:
            try:
                message, tag = self.messages.get_nowait()
            except queue.Empty:
                break
            if tag is None:
                low = message.lower()
                if "failed" in low or "error" in low:
                    tag = "error"
                elif "warning" in low or "skipped" in low:
                    tag = "warn"
                elif low.strip().startswith("ok:"):
                    tag = "ok"
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message + "\n", tag or ())
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        while True:
            try:
                callback = self.results.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                self.log(traceback.format_exc(), "error")
        self.root.after(100, self._drain)

    def _run_async(self, work, on_success):
        self.busy = True
        self._set_enabled(False)
        self.progress.start(12)

        def worker():
            try:
                result = work()
            except AutomationError as e:
                message = str(e)
                self.results.put(lambda: self._on_failure(message))
            except Exception as e:
                message = f"{type(e).__name__}: {e}"
                self.results.put(lambda: self._on_failure(message))
            else:
                self.results.put(lambda: self._done(on_success, result))

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, callback, result):
        self.busy = False
        self.progress.stop()
        self._set_enabled(True)
        callback(result)

    def _on_failure(self, message):
        self.busy = False
        self.progress.stop()
        self._set_enabled(True)
        self.log(message, "error")
        self.status_var.set("Failed — see the activity log.")
        messagebox.showerror("Finance Clerk error", message)

    def _set_enabled(self, enabled):
        state = "!disabled" if enabled else "disabled"
        self.preview_btn.state([state])
        self.url_entry.state([state])
        self.submit_btn.state(["!disabled" if enabled and self.plan else "disabled"])

    # ---------------------------------------------------------------- week

    def _update_week_labels(self):
        for choice, var in self.week_labels.items():
            start = week_start(choice)
            one = start + timedelta(days=6)
            two = start + timedelta(days=13)
            name = "This week" if choice == "this" else "Next week"
            var.set(f"{name}: Sun {start:%b %d} – Sat {one:%b %d, %Y}   "
                    f"(2-week passes: to Sat {two:%b %d, %Y})")

    def on_week_change(self):
        self._update_week_labels()
        if self.plan and not self.busy:
            apply_week(self.plan, self.week_var.get())
            self._refresh()

    # -------------------------------------------------------------- preview

    def _settings_from_ui(self):
        self.settings["pm_template"] = self.tpl_text.get("1.0", "end").rstrip()
        self.settings["reply_text"] = self.reply_var.get().strip()
        self.settings["finance_officers"] = [
            s.strip() for s in self.officers_var.get().split(",") if s.strip()]
        return self.settings

    def on_open_opt_out(self):
        """Open the opt-out topic; ask for its link the first time."""
        url = (self.settings.get("opt_out_url") or "").strip()
        if not url:
            url = (simpledialog.askstring(
                "Opt-out list",
                "Paste the link to the forum topic that lists the members who\n"
                "don't want the weapon pass PM. It is saved on this computer.",
                parent=self.root) or "").strip()
            if not url:
                return
            if not url.startswith(FORUM + "/"):
                messagebox.showwarning("Opt-out list",
                                       f"The link must be a {FORUM} topic.")
                return
            self.settings["opt_out_url"] = url
            try:
                save_settings(self._settings_from_ui())
                self.log("Saved the opt-out list link.", "ok")
            except OSError as e:
                self.log(f"Could not save the opt-out list link: {e}", "warn")
        webbrowser.open(url)

    def on_save_settings(self):
        try:
            save_settings(self._settings_from_ui())
            self.log("Saved the PM template, reply and finance officers as default.", "ok")
        except OSError as e:
            messagebox.showerror("Save settings", str(e))

    def on_preview(self):
        if self.busy:
            return
        if not self.app.username or not self.app.password:
            self.app.on_sign_in()
            if not self.app.username:
                return
        url = self.url_var.get().strip() or None
        settings = dict(self._settings_from_ui())
        week = self.week_var.get()
        self.plan = None
        self.status_var.set("Loading post, members and existing passes...")
        self.log("\n" + "=" * 60)
        self.log("Building weapon pass preview...")
        self.clerk = FinanceClerk(self.app.username, self.app.password,
                                  dry_run=self.dry_var.get(), log=self.log)
        self._run_async(lambda: self.clerk.prepare(url, week=week, settings=settings),
                        self._show_preview)

    def _show_preview(self, plan):
        self.plan = plan
        self._refresh()
        self.submit_btn.state(["!disabled"])
        self.status_var.set("Preview ready — check the passes and PMs, then submit.")

    def _refresh(self):
        """Redraw the donor table and the 'will be sent' panel from the plan."""
        plan = self.plan
        self.tree.delete(*self.tree.get_children())
        if not plan:
            return
        for i, r in enumerate(plan["donors"]):
            blocked = bool(r.get("block"))
            dates = (f"{r['start']:%b %d} – {r['end']:%b %d, %Y}"
                     if r.get("start") else "")
            tier = {0: "none", 1: "1 week", 2: "2 weeks"}[r["weeks"]]
            note = r.get("block_note") or r.get("note") or ""
            if r.get("result"):
                note = f"[{r['result']}] {note}".strip()
            tag = ("error" if r.get("block") == "duplicate" else
                   "blocked" if blocked else "" if r["give_pass"] else "off")
            self.tree.insert("", "end", iid=str(i), tags=(tag,), values=(
                LOCKED if blocked else (CHECK if r["give_pass"] else EMPTY),
                LOCKED if blocked or not r.get("forum_username")
                else (CHECK if r["send_pm"] else EMPTY),
                f"{r['rank']} {r['last_name']}".strip(),
                f"${r['amount']:.2f}", r["date"], tier, dates,
                r.get("forum_username") or "", note))

        donors = plan["donors"]
        n_pass = sum(1 for r in donors if r["give_pass"] and not r.get("block"))
        n_dup = sum(1 for r in donors if r.get("block") == "duplicate")
        self.summary_var.set(
            f"{len(donors)} donor(s) • {n_pass} pass(es) to create"
            + (f" • {n_dup} duplicate(s) — error, nothing written for them" if n_dup else "")
            + f" • source: {plan['source_title']}")

        officers = [o["username"] for o in plan["officers"]]
        lines = []
        for r in donors:
            if r["give_pass"] and not r.get("block"):
                lines.append(f"PASS {r['rank']} {r['last_name']}: "
                             f"{r['start']:%b %d} – {r['end']:%b %d}\n"
                             f"  Reason: {r['reason']}")
        groups = pm_groups(plan)
        for (start, end), rows in groups.items():
            me = (self.app.username or "").lower()
            to = []
            for name in [r["forum_username"] for r in rows] + officers:
                if name.lower() != me and name.lower() not in [t.lower() for t in to]:
                    to.append(name)
            lines.append(f"\nPM '{PM_TITLE}' — {start:%b %d} to {end:%b %d}\n"
                         f"  To: {', '.join(to)}\n"
                         f"  Valid from the {render_pm('{start}', start, end)} "
                         f"to the {render_pm('{end}', start, end)}")
        if not groups:
            lines.append("\nNo PMs (nobody ticked for a PM).")
        lines.append(f"\nReply in topic {plan['source_topic']}: {self.reply_var.get()}")
        self.out_text.configure(state="normal")
        self.out_text.delete("1.0", "end")
        self.out_text.insert("1.0", "\n".join(lines).strip())
        self.out_text.configure(state="disabled")

    def on_toggle(self, event):
        if not self.plan or self.busy:
            return
        row_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not row_id or col not in ("#1", "#2"):
            return
        r = self.plan["donors"][int(row_id)]
        if r.get("block"):
            messagebox.showinfo("Can't give a pass",
                                f"{r['rank']} {r['last_name']}: {r['block_note']}.")
            return
        if col == "#1":
            if not r["give_pass"] and r.get("note") and not r["default_pass"]:
                if not messagebox.askyesno(
                        "Override the rules?",
                        f"{r['rank']} {r['last_name']} is excluded: {r['note']}.\n\n"
                        "Give them a pass anyway?"):
                    return
            r["give_pass"] = not r["give_pass"]
            r["send_pm"] = r["give_pass"] and bool(r.get("forum_username"))
        else:
            if not r["give_pass"] or not r.get("forum_username"):
                return
            r["send_pm"] = not r["send_pm"]
        self._refresh()

    # --------------------------------------------------------------- submit

    def on_submit(self):
        if self.busy or not self.plan:
            return
        plan = self.plan
        plan["pm_template"] = self.tpl_text.get("1.0", "end").rstrip()
        plan["reply_text"] = self.reply_var.get().strip()
        chosen = [r for r in plan["donors"] if r["give_pass"] and not r.get("block")]
        if not chosen:
            messagebox.showwarning("Nothing to do", "No donors are ticked for a pass.")
            return
        if "{start}" not in plan["pm_template"] or "{end}" not in plan["pm_template"]:
            if not messagebox.askyesno("PM template",
                                       "The PM has no {start}/{end} placeholders, so it "
                                       "won't show the pass dates. Send it anyway?"):
                return
        dry = self.dry_var.get()
        groups = pm_groups(plan)
        confirm = (
            f"{'DRY RUN — nothing will be written.' if dry else 'This will write to the live site.'}\n\n"
            f"Create {len(chosen)} Recurring Donation pass(es),\n"
            f"send {len(groups)} PM(s) (with the finance officers as recipients),\n"
            f"then reply in the donations topic:\n  {plan['reply_text']}\n\nProceed?")
        if not messagebox.askyesno("Confirm", confirm, icon="question"):
            return
        self.status_var.set("Submitting...")
        self.log("\n" + "=" * 60)
        self.log("Creating weapon passes...")
        self.clerk.dry_run = dry
        self._run_async(lambda: self.clerk.execute(plan), self._after_submit)

    def _after_submit(self, results):
        self._refresh()
        created, chosen = results["created"], results["chosen"]
        failed_pms = [p for p in results["pms"] if str(p["result"]).startswith("failed")]
        where = "" if results["dry_run"] else f"\n\nDetails saved to {RESULTS_FILE}."
        self.status_var.set(f"Finished — {created}/{chosen} passes, "
                            f"{len(results['pms'])} PM(s).")
        if created < chosen or failed_pms or not results["reply"]:
            messagebox.showwarning(
                "Finished with problems",
                f"{created} of {chosen} passes created, "
                f"{len(results['pms']) - len(failed_pms)} of {len(results['pms'])} PMs sent."
                f"{'' if results['reply'] else ' No reply was posted.'}\n\n"
                f"Check the activity log for what needs doing by hand.{where}")
        else:
            messagebox.showinfo("Done", f"{created} passes created, "
                                        f"{len(results['pms'])} PM(s) sent and the "
                                        f"reply posted.{where}")
        if not results["dry_run"]:
            # A plan must not be submitted twice.
            self.plan = None
            self.submit_btn.state(["disabled"])
