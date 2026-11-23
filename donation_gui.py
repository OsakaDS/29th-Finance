#!/usr/bin/env python3
"""
29th Infantry Division - Donation Automation (GUI)
==================================================
Paste the link to a weekly donations topic, preview the post that will be
created, then submit it and record the finances in one click.

    python donation_gui.py

Network work runs on a background thread; the UI thread only ever touches
widgets, with log lines passed back through a queue.

Requirements:
    pip install requests beautifulsoup4      (tkinter ships with Python)
"""

import queue
import sys
import threading
import traceback
import webbrowser

from donation_automation import (CREDENTIALS_FILE, FORUM, AutomationError,
                                 DonationAutomator, app_file, delete_credentials,
                                 load_credentials, save_credentials)


def report_startup_error(message):
    """Print a startup failure, and log it when there is no console.

    A built app (.exe / .app) has no terminal, so a crash at launch is
    otherwise invisible: the app just never opens.
    """
    print(message, file=sys.stderr)
    if getattr(sys, "frozen", False):
        try:
            with open(app_file("startup-error.log"), "w", encoding="utf-8") as f:
                f.write(message + "\n")
        except OSError:
            pass


try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:
    if sys.platform == "darwin":
        hint = ("Install Python from python.org (it includes Tkinter), or with "
                "Homebrew run:\n    brew install python-tk@%d.%d" % sys.version_info[:2])
    else:
        hint = "Reinstall Python with the 'tcl/tk and IDLE' option enabled."
    report_startup_error("This Python has no Tkinter, which the app's window "
                         f"needs ({sys.executable}).\n{hint}")
    sys.exit(1)

PAD = 10

# Consolas and Windows point sizes don't exist / look tiny on macOS.
if sys.platform == "darwin":
    MONO, SIZE = "Menlo", 12
else:
    MONO, SIZE = "Consolas", 10


class CredentialsDialog(tk.Toplevel):
    """Modal sign-in prompt used when credentials.json is missing or bad."""

    def __init__(self, parent, username=""):
        super().__init__(parent)
        self.title("Sign in — 29th ID forum account")
        self.resizable(False, False)
        self.result = None

        frame = ttk.Frame(self, padding=PAD)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Your forums.29th.org account is used to read the\n"
                              "donations post and submit the records.",
                  foreground="#555").grid(row=0, column=0, columnspan=2,
                                          sticky="w", pady=(0, PAD))

        ttk.Label(frame, text="Username:").grid(row=1, column=0, sticky="w")
        self.user_var = tk.StringVar(value=username)
        user_entry = ttk.Entry(frame, textvariable=self.user_var, width=32)
        user_entry.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=2)

        ttk.Label(frame, text="Password:").grid(row=2, column=0, sticky="w")
        self.pass_var = tk.StringVar()
        pass_entry = ttk.Entry(frame, textvariable=self.pass_var, show="•", width=32)
        pass_entry.grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=2)

        self.save_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text=f"Remember me (saves {CREDENTIALS_FILE} "
                                    f"next to the app)",
                        variable=self.save_var).grid(row=3, column=0, columnspan=2,
                                                     sticky="w", pady=(PAD, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(PAD, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=0)
        ttk.Button(buttons, text="Sign in", command=self._accept).grid(
            row=0, column=1, padx=(6, 0))

        self.bind("<Return>", lambda _e: self._accept())
        self.bind("<Escape>", lambda _e: self.destroy())
        (pass_entry if username else user_entry).focus_set()

        self.transient(parent)
        self.grab_set()
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _accept(self):
        user, password = self.user_var.get().strip(), self.pass_var.get()
        if not user or not password:
            messagebox.showwarning("Sign in", "Enter both a username and password.",
                                   parent=self)
            return
        self.result = (user, password, self.save_var.get())
        self.destroy()


class DonationGUI:
    def __init__(self, root, parent=None):
        self.root = root
        # The tab this view lives in (the window itself when used standalone).
        self.parent = parent or root
        self.bot = None
        self.plan = None
        self.busy = False
        self.messages = queue.Queue()
        self.results = queue.Queue()  # callbacks from the worker thread

        root.title("29th ID — Finance Officer")
        root.geometry("1000x820")
        root.minsize(760, 620)

        self._build_widgets()
        self._load_credentials()
        self.root.after(100, self._drain_messages)

    # --------------------------------------------------------------- layout

    def _build_widgets(self):
        root = self.parent
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=3)   # preview grows most
        root.rowconfigure(4, weight=1)   # log grows a little

        # --- source row -----------------------------------------------------
        top = ttk.Frame(root, padding=(PAD, PAD, PAD, 0))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Donations post:").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(top, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        self.url_entry.bind("<Return>", lambda _e: self.on_preview())

        self.preview_btn = ttk.Button(top, text="Load preview", command=self.on_preview)
        self.preview_btn.grid(row=0, column=2)

        ttk.Label(top, foreground="#666",
                  text="Paste a topic link, e.g. "
                       f"{FORUM}/t/donations-july-26-august-1/12345   "
                       "(leave blank to use the latest post)"
                  ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # --- parsed summary -------------------------------------------------
        self.summary_var = tk.StringVar(
            value="No post loaded yet — paste the donations post link above "
                  "(or leave it blank for the latest) and click Load preview.")
        ttk.Label(root, textvariable=self.summary_var, padding=(PAD, PAD, PAD, 0),
                  font=("TkDefaultFont", SIZE - 1, "bold")).grid(row=1, column=0, sticky="w")

        # --- preview --------------------------------------------------------
        preview = ttk.LabelFrame(root, text="Post preview (editable)",
                                 padding=(6, 4))
        preview.grid(row=2, column=0, sticky="nsew", padx=PAD, pady=(4, 0))
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(1, weight=1)

        title_row = ttk.Frame(preview)
        title_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        title_row.columnconfigure(1, weight=1)
        ttk.Label(title_row, text="Title:").grid(row=0, column=0, sticky="w")
        self.title_var = tk.StringVar()
        ttk.Entry(title_row, textvariable=self.title_var).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))

        self.preview_text = tk.Text(preview, wrap="word", height=16,
                                    font=(MONO, SIZE), undo=True)
        self.preview_text.grid(row=1, column=0, sticky="nsew")
        pscroll = ttk.Scrollbar(preview, orient="vertical",
                                command=self.preview_text.yview)
        pscroll.grid(row=1, column=1, sticky="ns")
        self.preview_text.configure(yscrollcommand=pscroll.set)

        # --- actions --------------------------------------------------------
        actions = ttk.Frame(root, padding=(PAD, PAD, PAD, 0))
        actions.grid(row=3, column=0, sticky="ew")
        actions.columnconfigure(4, weight=1)

        self.submit_btn = ttk.Button(actions, text="Submit post + records",
                                     command=self.on_submit, state="disabled")
        self.submit_btn.grid(row=0, column=0)

        # Explains why Submit is greyed out until a preview has been loaded.
        self.submit_hint = tk.StringVar(value="← load a preview first")
        ttk.Label(actions, textvariable=self.submit_hint,
                  foreground="#a06010").grid(row=0, column=1, padx=(8, 0), sticky="w")

        self.dry_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions, text="Dry run (don't write anything)",
                        variable=self.dry_var).grid(row=0, column=2, padx=(10, 0))

        # Recovery: if the post already went up but records failed, reuse its id
        # instead of posting a duplicate.
        reuse = ttk.Frame(actions)
        reuse.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(reuse, text="Post already exists? Reuse topic ID:",
                  foreground="#666").grid(row=0, column=0, sticky="w")
        self.reuse_var = tk.StringVar()
        ttk.Entry(reuse, textvariable=self.reuse_var, width=12).grid(
            row=0, column=1, padx=(6, 0))
        ttk.Label(reuse, text="(leave blank to create a new post)",
                  foreground="#666").grid(row=0, column=2, padx=(6, 0))

        self.open_btn = ttk.Button(actions, text="Open created topic",
                                   command=self.on_open_topic, state="disabled")
        self.open_btn.grid(row=0, column=3, padx=(10, 0))

        # Account buttons sit on the second row, in their own frame, so they
        # never get squeezed out of view on a narrow window.
        account = ttk.Frame(actions)
        account.grid(row=1, column=4, columnspan=3, sticky="e", pady=(6, 0))
        self.signin_btn = ttk.Button(account, text="Sign in…", command=self.on_sign_in)
        self.signin_btn.grid(row=0, column=0)
        self.signout_btn = ttk.Button(account, text="Delete credentials",
                                      command=self.on_delete_credentials)
        self.signout_btn.grid(row=0, column=1, padx=(6, 0))

        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=6, padx=(10, 0), sticky="e")

        # --- log ------------------------------------------------------------
        logframe = ttk.LabelFrame(root, text="Activity", padding=(6, 4))
        logframe.grid(row=4, column=0, sticky="nsew", padx=PAD, pady=(6, 0))
        logframe.columnconfigure(0, weight=1)
        logframe.rowconfigure(0, weight=1)

        self.log_text = tk.Text(logframe, wrap="word", height=8, state="disabled",
                                font=(MONO, SIZE - 1), background="#1e1e1e",
                                foreground="#d4d4d4")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        lscroll = ttk.Scrollbar(logframe, orient="vertical",
                                command=self.log_text.yview)
        lscroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=lscroll.set)
        self.log_text.tag_configure("warn", foreground="#e5c07b")
        self.log_text.tag_configure("error", foreground="#e06c75")
        self.log_text.tag_configure("ok", foreground="#98c379")

        # --- status bar -----------------------------------------------------
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(root, textvariable=self.status_var, relief="sunken",
                  anchor="w", padding=(6, 3)).grid(row=5, column=0, sticky="ew",
                                                   padx=PAD, pady=(6, PAD))

    # ----------------------------------------------------------- credentials

    def _load_credentials(self):
        """Load saved credentials, or prompt for them on first run."""
        self.username = self.password = None
        try:
            self.username, self.password = load_credentials()
            self.log(f"Signed in as '{self.username}'.")
            self.status_var.set(f"Ready — signed in as {self.username}.")
            self._refresh_signin_ui()
            return
        except FileNotFoundError:
            self.log("No saved credentials — please sign in.")
        except (KeyError, ValueError) as e:
            self.log(f"{CREDENTIALS_FILE} is unreadable ({e}) — please sign in.", "warn")
        self.root.after(200, self.on_sign_in)

    def on_sign_in(self):
        dialog = CredentialsDialog(self.root, username=self.username or "")
        self.root.wait_window(dialog)
        if not dialog.result:
            if not self.username:
                self.status_var.set("Not signed in — click 'Sign in' to continue.")
                self.preview_btn.state(["disabled"])
            return
        self.username, self.password, remember = dialog.result
        if remember:
            try:
                path = save_credentials(self.username, self.password)
                self.log(f"Credentials saved to {path}")
            except OSError as e:
                self.log(f"Could not save credentials: {e}", "warn")
        self.log(f"Signed in as '{self.username}'.")
        self.status_var.set(f"Ready — signed in as {self.username}.")
        self.preview_btn.state(["!disabled"])
        self._refresh_signin_ui()

    def _refresh_signin_ui(self):
        if self.username:
            self.signin_btn.configure(text=f"Sign in as… ({self.username})")
        else:
            self.signin_btn.configure(text="Sign in…")

    def on_delete_credentials(self):
        """Forget the signed-in account and delete credentials.json."""
        if self.busy:
            return
        if not messagebox.askyesno(
                "Delete credentials",
                f"Delete the saved credentials ({CREDENTIALS_FILE}) and sign out?\n\n"
                "You will need to sign in again before loading a post.",
                parent=self.root):
            return
        try:
            existed = delete_credentials()
        except OSError as e:
            self.log(f"Could not delete credentials: {e}", "error")
            messagebox.showerror("Delete credentials", str(e), parent=self.root)
            return
        self.username = self.password = None
        self.bot = None
        self.plan = None
        self.submit_btn.state(["disabled"])
        self.preview_btn.state(["disabled"])
        self._refresh_signin_ui()
        self.log("Saved credentials deleted." if existed
                 else "No saved credentials file; signed out.")
        self.status_var.set("Signed out — click 'Sign in' to continue.")

    # ------------------------------------------------------------- threading

    def log(self, message, tag=None):
        """Thread-safe: queue a line for the UI thread to render."""
        self.messages.put((str(message), tag))

    def _drain_messages(self):
        while True:
            try:
                message, tag = self.messages.get_nowait()
            except queue.Empty:
                break
            if tag is None:  # colour-code by content when not tagged explicitly
                low = message.lower()
                if "failed" in low or "error" in low:
                    tag = "error"
                elif "warning" in low or "skipped" in low:
                    tag = "warn"
                elif low.strip().startswith("ok:") or "created topic" in low:
                    tag = "ok"
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message + "\n", tag or ())
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        # After the log lines, so a failure's log output appears before its dialog.
        while True:
            try:
                callback = self.results.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:  # keep polling, or the window stops updating
                self.log(traceback.format_exc(), "error")
        self.root.after(100, self._drain_messages)

    def _run_async(self, work, on_success):
        """Run `work()` off the UI thread, then `on_success(result)` on it."""
        self.busy = True
        self._set_controls_enabled(False)
        self.progress.start(12)

        # The worker must not call Tk itself (not even root.after): Tk is not
        # thread-safe, and on macOS such calls can be silently dropped, leaving
        # the app stuck. Results go through a queue that _drain_messages polls.
        def worker():
            # Build the message inside the except block: Python deletes `e` when
            # the block ends, so a lambda that reads `e` later raises NameError
            # and the error is never shown.
            try:
                result = work()
            except AutomationError as e:
                message = str(e)
                self.results.put(lambda: self._on_failure(message))
            except Exception as e:  # network, parsing, anything unexpected
                message = f"{type(e).__name__}: {e}"
                self.results.put(lambda: self._on_failure(message))
            else:
                self.results.put(lambda: self._on_success(on_success, result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_success(self, callback, result):
        self.busy = False
        self.progress.stop()
        self._set_controls_enabled(True)
        callback(result)

    def _on_failure(self, message):
        self.busy = False
        self.progress.stop()
        self._set_controls_enabled(True)
        self.log(message, "error")
        self.status_var.set("Failed — see the activity log.")
        messagebox.showerror("Automation error", message)

    def _set_controls_enabled(self, enabled):
        state = "!disabled" if enabled else "disabled"
        self.preview_btn.state([state])
        self.url_entry.state([state])
        self.signin_btn.state([state])
        self.signout_btn.state([state])
        # Submit stays disabled until there is a plan to submit.
        if enabled and self.plan:
            self.submit_btn.state(["!disabled"])
        else:
            self.submit_btn.state(["disabled"])

    def _new_bot(self):
        return DonationAutomator(self.username, self.password,
                                 dry_run=self.dry_var.get(), log=self.log)

    # --------------------------------------------------------------- actions

    def on_preview(self):
        if self.busy:
            return
        if not self.username or not self.password:
            self.on_sign_in()
            if not self.username:
                return
        url = self.url_var.get().strip() or None
        self.plan = None
        self.open_btn.state(["disabled"])
        self.created_topic_url = None
        self.status_var.set("Loading post and member totals...")
        self.log("\n" + "=" * 60)
        self.log("Building preview...")

        self.bot = self._new_bot()
        self._run_async(lambda: self.bot.prepare(url), self._show_preview)

    def _show_preview(self, plan):
        self.plan = plan
        self.title_var.set(plan["title"])
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", plan["body"])

        donors, expenses = plan["donors"], plan["expenses"]
        total = sum(d["amount"] for d in donors)
        spent = sum(e["amount"] for e in expenses)
        summary = (f"{len(donors)} donation(s) totalling ${total:,.2f}"
                   f"   •   {len(expenses)} expense(s) totalling ${spent:,.2f}"
                   f"   •   source: {plan['source_title']}")
        self.summary_var.set(summary)

        for d in donors:
            self.log(f"  {d.get('rank', '')} {d['name']}: {d['date']} "
                     f"${d['amount']:.2f} (fee ${d['fee']:.2f}) → "
                     f"lifetime ${d['lifetime_total']:.2f}")
        for e in expenses:
            self.log(f"  expense {e['name']}: {e['date']} ${e['amount']:.2f} "
                     f"→ vendor '{e['vendor_label']}'"
                     + (f" (notes: {e['notes']})" if e["notes"] else ""))

        self.submit_btn.state(["!disabled"])
        self.submit_hint.set("")
        self.status_var.set("Preview ready — review the text, then submit.")

    def on_submit(self):
        if self.busy or not self.plan:
            return
        donors, expenses = self.plan["donors"], self.plan["expenses"]
        dry = self.dry_var.get()
        reuse = self.reuse_var.get().strip() or None
        topic_line = (f"Reuse existing topic:\n  {reuse} (no new post)"
                      if reuse else f"Create topic:\n  {self.title_var.get()}")
        confirm = (
            f"{'DRY RUN — nothing will be written.' if dry else 'This will write to the live site.'}\n\n"
            f"{topic_line}\n\n"
            f"Then submit {len(donors)} donation record(s) "
            f"and {len(expenses)} expense record(s).\n\nProceed?"
        )
        if not messagebox.askyesno("Confirm submission", confirm, icon="question"):
            return

        # Use whatever is currently in the preview box, so manual edits count.
        self.plan["title"] = self.title_var.get().strip()
        self.plan["body"] = self.preview_text.get("1.0", "end").strip()

        self.status_var.set("Submitting...")
        self.log("\n" + "=" * 60)
        self.log("Submitting post and finance records...")

        self.bot.dry_run = dry
        plan = self.plan
        self._run_async(lambda: self.bot.execute(plan, existing_topic_id=reuse),
                        self._after_submit)

    def _after_submit(self, results):
        topic_id = results["summary_topic"]
        if topic_id and topic_id != "DRYRUN":
            self.created_topic_url = f"{FORUM}/t/{topic_id}"
            self.open_btn.state(["!disabled"])
        total = len(results["donors"]) + len(results["expenses"])
        done = results["donations_ok"] + results["expenses_ok"]
        self.status_var.set(f"Finished — {done}/{total} records submitted, "
                            f"topic {topic_id}.")
        if done < total:
            messagebox.showwarning(
                "Some records failed",
                f"{done} of {total} finance records were submitted.\n\n"
                "The topic was created. Check the activity log for the ones "
                "that failed and add them manually.")
        else:
            messagebox.showinfo("Done", f"Topic created and all {total} finance "
                                        f"records submitted.")
        # A plan must not be submitted twice.
        self.plan = None
        self.submit_btn.state(["disabled"])
        self.submit_hint.set("← load a preview first")

    def on_open_topic(self):
        if getattr(self, "created_topic_url", None):
            webbrowser.open(self.created_topic_url)


def main():
    try:
        run()
    except Exception:
        report_startup_error(traceback.format_exc())
        raise


def run():
    root = tk.Tk()
    try:
        root.call("source", "sun-valley.tcl")  # optional nicer theme if present
    except tk.TclError:
        pass
    from finance_clerk_gui import FinanceClerkTab

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    donations = ttk.Frame(notebook)
    clerk = ttk.Frame(notebook)
    notebook.add(donations, text="Donations")
    notebook.add(clerk, text="Finance Clerk — Weapon Passes")
    app = DonationGUI(root, donations)
    FinanceClerkTab(root, clerk, app)
    root.mainloop()


if __name__ == "__main__":
    main()
