# PHOGBS Platform

Django backend and web app for the Port-Harcourt Oil & Gas Business School
digital learning platform. The full specification is in
[design/PHOGBS SRS.docx](design/PHOGBS%20SRS.docx).

Built so far: the **management platform's sign-in and onboarding flows** from
the designs in [design/](design/). The other platform features come later.

## Setup

Requires Python 3.12+. Settings are split by environment:

| Module | Used by | Database |
|---|---|---|
| `config.settings.dev` | `manage.py` (default) | SQLite at `db.sqlite3` |
| `config.settings.prod` | `wsgi.py` / `asgi.py` (default) | PostgreSQL from `DATABASE_URL` |

Shared settings live in `config/settings/base.py`. Production requires
`SECRET_KEY`, `ALLOWED_HOSTS` and `DATABASE_URL` (see `.env.example`). To run
management commands against production, set
`DJANGO_SETTINGS_MODULE=config.settings.prod`.

For local development:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py createcachetable   # used by the sign-in throttle
.\.venv\Scripts\python manage.py createsuperuser
.\.venv\Scripts\python manage.py runserver
```

Open http://127.0.0.1:8000/. In development, emails (invitations, password
resets) are printed to the console instead of being sent.

Run the tests with `python manage.py test apps`.

## Deploying to Vercel

Vercel runs `config/wsgi.py`, which uses production settings. There's no `.env`
file there, so set these in **Project → Settings → Environment Variables**:

| Variable | Value |
|---|---|
| `SECRET_KEY` | A long random string, e.g. from `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DATABASE_URL` | A hosted PostgreSQL URL (Neon, Supabase, Vercel Postgres…). Vercel can't reach a database on your own computer, and SQLite doesn't persist there. |
| `ALLOWED_HOSTS` | Only needed for a custom domain, e.g. `admin.phogbs.com`. The `*.vercel.app` domains are added automatically. |
| `CSRF_TRUSTED_ORIGINS` | Only for a custom domain, e.g. `https://admin.phogbs.com`. |
| `RESEND_API_KEY`, `DEFAULT_FROM_EMAIL` | Resend API key, and a From address on a domain verified in Resend, so invitation and password-reset emails send. |

Redeploy after changing variables. Then set up the database once from your
machine, pointing at the hosted database:

```powershell
$env:DJANGO_SETTINGS_MODULE="config.settings.prod"
$env:SECRET_KEY="any-value"
$env:ALLOWED_HOSTS="localhost"
$env:DATABASE_URL="postgres://...your hosted database..."
.\venv\Scripts\python manage.py migrate
.\venv\Scripts\python manage.py createcachetable
.\venv\Scripts\python manage.py createsuperuser
```

Static files are served by WhiteNoise. **Uploaded ID documents need an
S3-compatible bucket before they will work on Vercel**, because its file
system is read-only and wiped between requests.

## How accounts work

Accounts are **invite-only**:

1. An administrator opens **Django admin → Invitations → Add**
   (`/django-admin/`), enters an email address and role, and saves. An
   invitation email is sent. The *Resend* and *Revoke* actions are on the
   invitation list.
2. The invitee opens the link, sees their assigned role (step 1 of 2), and sets
   a password (step 2 of 2). Links expire after 7 days and work only once.
3. They sign in at `/auth/login/`. On first sign-in they complete their profile
   (name and phone, then NIN or BVN plus an ID document) and land on the
   dashboard.

Sign-in rules:

- Five failed attempts within 15 minutes, for the same email from the same IP
  address, lock that combination for the rest of the 15 minutes. A single IP
  address is limited to 20 failures.
- A deactivated account sees the "inactive" message only after entering the
  correct password, so the message doesn't reveal which accounts exist.
- "Keep me logged in" keeps the session for 30 days. Otherwise the session ends
  when the browser closes.
- Passwords need at least 12 characters, with an uppercase letter, a lowercase
  letter, and a number or symbol. Common passwords are also rejected.

## Overview dashboard

School administrators and super administrators land on the Overview at `/`.
It's built from
`design/Overview dashboard (School administrator & super admin)/`. Other roles
see a placeholder until their dashboards are designed.

- **Live data:** Total Staff, plus the Needs Attention items for pending
  invitations and staff who haven't finished setup. Their links open
  pre-filtered admin lists.
- **Not built yet:** programmes, revenue, learners, the schedule and the trend
  charts. When `DASHBOARD_SAMPLE_DATA` is on (the dev default), they show
  sample figures, and a "Sample data" badge appears beside the date. When it's
  off (always in production), they show the design's empty states. Replace
  each sample block in `apps/dashboard/metrics.py` with real queries as the
  modules are built.
- **Navigation:** sidebar items for modules that don't exist yet open a
  "coming soon" page (`/workspace/<section>/`). Staff Directory links to the
  Django admin.
- **Charts:** plain SVG drawn by `static/js/app.js`, with hover tooltips.

## Layout

| Path | What it holds |
|---|---|
| `config/` | Settings, URLs, WSGI/ASGI |
| `apps/accounts/` | User model and roles, invitations, sign-in, password reset, onboarding, accounts API |
| `apps/dashboard/` | Placeholder dashboard (no design yet) |
| `templates/` | Page and email templates |
| `static/` | `css/auth.css`, `js/auth.js`, logo |

### API (`/api/v1/`)

Uses session authentication for now. Add token or JWT authentication when the
mobile app is built.

| Endpoint | Purpose |
|---|---|
| `GET me/` | Current user |
| `POST/DELETE me/identity-document/` | Upload or clear the ID document during setup (used by the upload widget) |
| `POST identity/lookup/` | `{method, number}` → name registered to the NIN/BVN, if any |
| `POST invitations/` | Invite a user (staff with the `add_invitation` permission) |

## Decisions and open items

- **NIN/BVN name lookup** needs a licensed identity provider (e.g. Dojah,
  Prembly, Smile ID). The interface is in `apps/accounts/identity.py`. Until a
  provider is configured, no name is shown under the number field.
- **Accepted ID document types** are PNG, JPG, GIF and PDF, up to 5 MB, and
  each file's contents are checked against its type. The design listed SVG;
  it's excluded because SVG files can contain scripts. PDF was added because
  scanned IDs are often PDFs.
- **Where ID documents are stored:** in `MEDIA_ROOT/private/`, which is never
  served publicly. Admins download them from the user's admin page. In
  production, switch the `private` storage to S3-compatible storage with
  private access.
- **NIN/BVN numbers** are stored in plain text and shown masked in the admin.
  Field-level encryption (SRS §58) is still to do.
- **Email is sent during the web request.** Move this to a background task
  queue when one is added.
- **Wording changes from the designs:** the invitation screen says "your
  account" (the design said "their"), and the button says "Activate Account"
  (the design said "Active Account").
- **Password-reset error message:** when sending the reset email fails, the
  page still shows "Check your mail". Showing an error only for real accounts
  would reveal which addresses have accounts. The "couldn't process" message
  appears only for failures that affect everyone, such as the database being
  down.
- **Styling:** the CSS is hand-written using the colours and spacing from the
  designs, so there's no build step. Revisit Tailwind if the dashboard UI grows.
