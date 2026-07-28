# ODU GK0WBM-P16WBC0-000L stock checker

Checks Digikey and Mouser every 30 minutes via GitHub Actions and emails a
list of recipients when the part becomes available to order.

It uses the distributors' **official free APIs** instead of scraping the
product pages — both pages sit behind Cloudflare/Akamai bot protection and
return CAPTCHA challenges to automated requests, so scraping is not viable
(especially from GitHub's datacenter IPs).

## One-time setup

Add these under **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Where to get it |
|---|---|
| `MOUSER_API_KEY` | Sign in at [mouser.com/api-hub](https://www.mouser.com/api-hub/), request a **Search API** key (instant, free) |
| `DIGIKEY_CLIENT_ID` / `DIGIKEY_CLIENT_SECRET` | Create an account at [developer.digikey.com](https://developer.digikey.com), create an **Organization → Production App** with the *Product Information V4* API enabled, copy the Client ID and Secret |
| `GMAIL_USER` | The Gmail address that sends the notifications |
| `GMAIL_APP_PASSWORD` | Generate at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (requires 2FA on the account) |
| `RECIPIENT_EMAILS` | Comma-separated list, e.g. `a@x.com, b@y.com` |

You can start with just the Mouser key (it's instant) — a source with missing
credentials is skipped with a log message, not treated as out of stock.

## Behavior

- Emails **once** when a source transitions from out-of-stock to in-stock
  (state is committed back to `state.json`). Set a repo **variable**-style
  secret `NOTIFY_EVERY_RUN=1` to email on every run while stock remains.
- If every configured check fails 5 runs in a row, `GMAIL_USER` gets a
  single warning email so silent breakage doesn't go unnoticed.
- Test manually anytime: **Actions → Check ODU part stock → Run workflow**.

## Notes

- GitHub schedules are best-effort; runs may start a few minutes late.
- GitHub disables cron workflows in repos with **no activity for 60 days**.
  State commits count as activity, but if the part stays out of stock that
  long, GitHub emails you and shows a "Re-enable workflow" button — click it,
  or push any commit.
