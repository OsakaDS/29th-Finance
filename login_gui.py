"""
29th Infantry Division - Finance Department app: login screen and window shell
==============================================================================
The window opens on a login box. The tabs are not shown, and cannot be used,
until the forum (forums.29th.org) has accepted the username and password.
Once signed in, a bar above the tabs shows the account and a Sign out button.

Saved credentials (credentials.json, "Remember me") are tried automatically at
start-up; if the forum rejects them the login box shows why.
"""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import requests

from donation_automation import (CREDENTIALS_FILE, FORUM, AutomationError,
                                 DonationAutomator, delete_credentials,
                                 load_credentials, save_credentials)

PAD = 10


def verify_forum_login(username, password):
    """Sign in to the forum to check the credentials. Raises AutomationError
    with a message for the user when they are rejected or the forum can't be
    reached."""
    bot = DonationAutomator(username, password, log=lambda *_a, **_k: None)
    try:
        bot.login_forum()
    except AutomationError:
        raise
    except requests.RequestException as e:
        raise AutomationError(f"Could not reach {FORUM}. Check your internet "
                              f"connection and try again.\n\n({type(e).__name__})")
    except (KeyError, ValueError) as e:
        raise AutomationError(f"The forum gave an unexpected answer ({e}). "
                              f"Try again in a moment.")


class LoginScreen(ttk.Frame):
    """Centred login box. Calls on_success(username, password, remember)."""

    def __init__(self, parent, on_success):
        super().__init__(parent)
        self.on_success = on_success
        self.results = queue.Queue()
        self.busy = False

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(2, weight=2)

        box = ttk.Frame(self, padding=24, relief="groove", borderwidth=1)
        box.grid(row=1, column=0)
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="29th Infantry Division", font=("TkDefaultFont", 16, "bold")
                  ).grid(row=0, column=0, columnspan=2)
        ttk.Label(box, text="Finance Department", font=("TkDefaultFont", 12)
                  ).grid(row=1, column=0, columnspan=2, pady=(0, PAD))
        ttk.Label(box, foreground="#666",
                  text="Sign in with your forums.29th.org account."
                  ).grid(row=2, column=0, columnspan=2, pady=(0, PAD))

        ttk.Label(box, text="Username:").grid(row=3, column=0, sticky="w")
        self.user_var = tk.StringVar()
        self.user_entry = ttk.Entry(box, textvariable=self.user_var, width=32)
        self.user_entry.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=3)

        ttk.Label(box, text="Password:").grid(row=4, column=0, sticky="w")
        self.pass_var = tk.StringVar()
        self.pass_entry = ttk.Entry(box, textvariable=self.pass_var, show="•", width=32)
        self.pass_entry.grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=3)

        self.remember_var = tk.BooleanVar(value=True)
        self.remember_chk = ttk.Checkbutton(
            box, text=f"Remember me on this computer (saves {CREDENTIALS_FILE})",
            variable=self.remember_var)
        self.remember_chk.grid(row=5, column=0, columnspan=2, sticky="w", pady=(PAD, 0))

        self.signin_btn = ttk.Button(box, text="Sign in", command=self.submit)
        self.signin_btn.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))

        self.progress = ttk.Progressbar(box, mode="indeterminate")
        self.progress.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.progress.grid_remove()

        self.message_var = tk.StringVar()
        self.message = ttk.Label(box, textvariable=self.message_var, foreground="#c0392b",
                                 wraplength=340, justify="center")
        self.message.grid(row=8, column=0, columnspan=2, pady=(6, 0))

        for widget in (self.user_entry, self.pass_entry):
            widget.bind("<Return>", lambda _e: self.submit())
        self.after(100, self._drain)

    # ------------------------------------------------------------------ API

    def reset(self, username="", message="", error=False):
        """Show an empty (or pre-filled) login box."""
        self.user_var.set(username)
        self.pass_var.set("")
        self.remember_var.set(True)
        self._show_message(message, error)
        (self.pass_entry if username else self.user_entry).focus_set()

    def try_saved(self, username, password):
        """Sign in with saved credentials, as if typed."""
        self.user_var.set(username)
        self.pass_var.set(password)
        self.remember_var.set(True)
        self.submit()

    # ------------------------------------------------------------ internals

    def _show_message(self, text, error=True):
        self.message.configure(foreground="#c0392b" if error else "#555")
        self.message_var.set(text)

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "!disabled"
        for widget in (self.user_entry, self.pass_entry, self.remember_chk,
                       self.signin_btn):
            widget.state([state])
        if busy:
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def submit(self):
        if self.busy:
            return
        username = self.user_var.get().strip()
        password = self.pass_var.get()
        if not username or not password:
            self._show_message("Enter both your username and password.")
            return
        remember = self.remember_var.get()
        self._set_busy(True)
        self._show_message(f"Signing in to {FORUM} as {username}…", error=False)

        # Network work off the UI thread; the result comes back via a queue.
        def worker():
            try:
                verify_forum_login(username, password)
            except AutomationError as e:
                message = str(e)
                self.results.put(lambda: self._failed(message))
            except Exception as e:  # anything unexpected
                message = f"{type(e).__name__}: {e}"
                self.results.put(lambda: self._failed(message))
            else:
                self.results.put(lambda: self._succeeded(username, password, remember))

        threading.Thread(target=worker, daemon=True).start()

    def _failed(self, message):
        self._set_busy(False)
        self.pass_var.set("")
        self._show_message(message)
        self.pass_entry.focus_set()

    def _succeeded(self, username, password, remember):
        self._set_busy(False)
        self.pass_var.set("")
        self._show_message("")
        self.on_success(username, password, remember)

    def _drain(self):
        while True:
            try:
                callback = self.results.get_nowait()
            except queue.Empty:
                break
            callback()
        self.after(100, self._drain)


class AppShell:
    """The window: the login screen, or the account bar plus the tabs."""

    def __init__(self, root):
        from donation_gui import DonationGUI
        from finance_clerk_gui import FinanceClerkTab

        self.root = root
        root.title("29th ID — Finance Department")
        root.geometry("1000x860")
        root.minsize(760, 640)

        self.login = LoginScreen(root, self._signed_in)

        self.main = ttk.Frame(root)
        bar = ttk.Frame(self.main, padding=(PAD, 6, PAD, 0))
        bar.pack(fill="x")
        self.account_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.account_var,
                  font=("TkDefaultFont", 11, "bold")).pack(side="left")
        ttk.Button(bar, text="Sign out", command=self.sign_out).pack(side="right")

        notebook = ttk.Notebook(self.main)
        notebook.pack(fill="both", expand=True, pady=(6, 0))
        donations = ttk.Frame(notebook)
        clerk = ttk.Frame(notebook)
        notebook.add(donations, text="Donations")
        notebook.add(clerk, text="Finance Clerk — Weapon Passes")
        self.donations = DonationGUI(root, donations)
        self.clerk = FinanceClerkTab(root, clerk, self.donations)

        self._show_login()
        try:
            username, password = load_credentials()
        except FileNotFoundError:
            self.login.reset()
        except (KeyError, ValueError):
            self.login.reset(message=f"{CREDENTIALS_FILE} is unreadable — please "
                                     f"sign in again.")
        else:
            self.login.try_saved(username, password)

    # --------------------------------------------------------------- views

    def _show_login(self):
        self.main.pack_forget()
        self.login.pack(fill="both", expand=True)

    def _show_main(self):
        self.login.pack_forget()
        self.main.pack(fill="both", expand=True)

    # ------------------------------------------------------------- account

    def _signed_in(self, username, password, remember):
        if remember:
            try:
                save_credentials(username, password)
            except OSError as e:
                messagebox.showwarning("Remember me",
                                       f"Signed in, but the login could not be "
                                       f"saved:\n{e}")
        else:
            # Unticked: don't leave an older saved login behind either.
            try:
                delete_credentials()
            except OSError:
                pass
        self.donations.set_account(username, password)
        self.clerk.reset()
        self.account_var.set(f"Signed in as {username}")
        self._show_main()

    def sign_out(self):
        if self.donations.busy or self.clerk.busy:
            messagebox.showinfo("Sign out", "Wait for the current task to finish "
                                            "before signing out.")
            return
        if not messagebox.askyesno(
                "Sign out",
                "Sign out of the app?\n\nThe saved login on this computer is "
                "deleted too, so the next person signs in with their own "
                "account.", parent=self.root):
            return
        try:
            delete_credentials()
        except OSError as e:
            messagebox.showerror("Sign out", f"Signed out, but {CREDENTIALS_FILE} "
                                             f"could not be deleted:\n{e}")
        self.donations.set_account(None, None)
        self.clerk.reset()
        self.account_var.set("")
        self._show_login()
        self.login.reset(message="Signed out.", error=False)
