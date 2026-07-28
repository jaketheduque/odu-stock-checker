#!/usr/bin/env python3
"""Check Digikey and Mouser stock for a part and email a list of recipients
when it comes in stock.

Runs in GitHub Actions every 30 minutes. Uses the official distributor APIs
(both free) because the product pages themselves sit behind Cloudflare/Akamai
bot protection and cannot be scraped from a datacenter IP.

Required environment variables:
  MOUSER_API_KEY         Mouser Search API key (https://www.mouser.com/api-hub/)
  DIGIKEY_CLIENT_ID      Digikey app client id (https://developer.digikey.com)
  DIGIKEY_CLIENT_SECRET  Digikey app client secret
  GMAIL_USER             Gmail address used to send notifications
  GMAIL_APP_PASSWORD     Gmail app password (https://myaccount.google.com/apppasswords)
  RECIPIENT_EMAILS       Comma-separated list of notification recipients

Optional:
  NOTIFY_EVERY_RUN       "1" to email on every run while in stock (default:
                         only email when a source transitions to in-stock)
"""

import json
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

import requests

PART_NUMBER = "GK0WBM-P16WBC0-000L"

DIGIKEY_URL = "https://www.digikey.com/en/products/detail/odu/GK0WBM-P16WBC0-000L/16279730"
MOUSER_URL = "https://www.mouser.com/ProductDetail/ODU/GK0WBM-P16WBC0-000L"

STATE_FILE = Path(__file__).parent / "state.json"
FAILURE_ALERT_THRESHOLD = 5


def check_mouser():
    """Return quantity in stock at Mouser, or None if the check failed."""
    api_key = os.environ.get("MOUSER_API_KEY")
    if not api_key:
        print("Mouser: MOUSER_API_KEY not set, skipping")
        return None
    try:
        resp = requests.post(
            "https://api.mouser.com/api/v1/search/partnumber",
            params={"apiKey": api_key},
            json={"SearchByPartRequest": {"mouserPartNumber": PART_NUMBER}},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        errors = data.get("Errors") or []
        if errors:
            print(f"Mouser: API errors: {errors}")
            return None
        parts = data.get("SearchResults", {}).get("Parts") or []
        for part in parts:
            if part.get("ManufacturerPartNumber", "").upper() == PART_NUMBER:
                # Availability looks like "0 In Stock" / "28 In Stock"
                match = re.match(r"\s*(\d+)", part.get("Availability") or "")
                qty = int(match.group(1)) if match else 0
                print(f"Mouser: {qty} in stock")
                return qty
        print(f"Mouser: part {PART_NUMBER} not found in search results")
        return None
    except (requests.RequestException, ValueError) as exc:
        print(f"Mouser: check failed: {exc}")
        return None


def check_digikey():
    """Return quantity in stock at Digikey, or None if the check failed."""
    client_id = os.environ.get("DIGIKEY_CLIENT_ID")
    client_secret = os.environ.get("DIGIKEY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Digikey: DIGIKEY_CLIENT_ID/SECRET not set, skipping")
        return None
    try:
        token_resp = requests.post(
            "https://api.digikey.com/v1/oauth2/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            timeout=30,
        )
        token_resp.raise_for_status()
        token = token_resp.json()["access_token"]

        resp = requests.get(
            f"https://api.digikey.com/products/v4/search/{PART_NUMBER}/productdetails",
            headers={
                "Authorization": f"Bearer {token}",
                "X-DIGIKEY-Client-Id": client_id,
                "X-DIGIKEY-Locale-Site": "US",
                "X-DIGIKEY-Locale-Language": "en",
                "X-DIGIKEY-Locale-Currency": "USD",
            },
            timeout=30,
        )
        resp.raise_for_status()
        qty = resp.json()["Product"]["QuantityAvailable"]
        print(f"Digikey: {qty} in stock")
        return int(qty)
    except (requests.RequestException, ValueError, KeyError) as exc:
        print(f"Digikey: check failed: {exc}")
        return None


def send_email(subject, body, recipients):
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not password:
        print("Email: GMAIL_USER/GMAIL_APP_PASSWORD not set, cannot send")
        return False
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(user, password)
            smtp.sendmail(user, recipients, msg.as_string())
        print(f"Email: sent to {len(recipients)} recipient(s)")
        return True
    except (smtplib.SMTPException, OSError) as exc:
        print(f"Email: send failed: {exc}")
        return False


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {"digikey_in_stock": False, "mouser_in_stock": False,
                "consecutive_failures": 0, "failure_alerted": False}


def main():
    recipients = [e.strip() for e in os.environ.get("RECIPIENT_EMAILS", "").split(",") if e.strip()]
    notify_every_run = os.environ.get("NOTIFY_EVERY_RUN") == "1"

    state = load_state()
    results = {"digikey": check_digikey(), "mouser": check_mouser()}

    configured = [
        name for name, env_vars in (
            ("digikey", ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET")),
            ("mouser", ("MOUSER_API_KEY",)),
        )
        if all(os.environ.get(v) for v in env_vars)
    ]
    all_failed = bool(configured) and all(results[name] is None for name in configured)

    if all_failed:
        state["consecutive_failures"] += 1
        if state["consecutive_failures"] >= FAILURE_ALERT_THRESHOLD and not state["failure_alerted"]:
            owner = os.environ.get("GMAIL_USER")
            if owner and send_email(
                f"[stock-checker] {PART_NUMBER}: checks failing",
                f"All configured stock checks have failed {state['consecutive_failures']} "
                "times in a row. Check the GitHub Actions logs.",
                [owner],
            ):
                state["failure_alerted"] = True
    else:
        state["consecutive_failures"] = 0
        state["failure_alerted"] = False

    newly_in_stock = []
    for name, qty, url in (
        ("Digikey", results["digikey"], DIGIKEY_URL),
        ("Mouser", results["mouser"], MOUSER_URL),
    ):
        key = f"{name.lower()}_in_stock"
        if qty is None:
            continue  # failed check: keep previous state, never treat as out of stock
        in_stock = qty > 0
        if in_stock and (not state[key] or notify_every_run):
            newly_in_stock.append(f"{name}: {qty} in stock\n  {url}")
        state[key] = in_stock

    if newly_in_stock:
        body = (
            f"ODU {PART_NUMBER} is available to order right now:\n\n"
            + "\n\n".join(newly_in_stock)
            + "\n\n-- automated stock checker"
        )
        if recipients:
            send_email(f"IN STOCK: ODU {PART_NUMBER}", body, recipients)
        else:
            print("Email: no RECIPIENT_EMAILS configured, skipping notification")

    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")

    if not configured:
        print("No API credentials configured — set MOUSER_API_KEY and/or "
              "DIGIKEY_CLIENT_ID + DIGIKEY_CLIENT_SECRET as repo secrets.")
        sys.exit(1)


if __name__ == "__main__":
    main()
