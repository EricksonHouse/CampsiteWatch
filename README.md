# campwatch

A personal ReserveCalifornia cancellation scanner. It watches specific parks
and site types, and notifies you the moment a matching cancellation opens up.
You still click through and book it yourself -- it never submits a
reservation or payment (see "Why it doesn't auto-book" below).

**This build runs continuously on your Windows desktop**, kept always-on.
GitHub still hosts your config and the mobile editor app (see Part 3) --
your desktop pulls the latest settings from there automatically every 5
minutes, so editing from your phone still works without touching the
desktop directly.

Important, given how it's confirmed to behave: ReserveCalifornia blocks
traffic from cloud-hosting IP ranges (confirmed during setup -- GitHub
Codespaces got a 403, a home internet connection got a clean 200). Your home
connection is not blocked, which is exactly why this setup works and a
cloud-hosted scheduler (GitHub Actions, a cheap VPS) would not, without
extra workarounds.

---

## Part 1: Get campwatch running on your desktop

You already have Python installed and working (confirmed via `python
--version` during setup). From a Command Prompt, in the folder where you
extracted this project:

```
pip install -r requirements.txt
python campwatch.py lookup "your park name"
```

Fill in `config.yaml` (copy from `config.example.yaml`) with the
`facility_id` values that prints, your date ranges, and keywords. Then run:

```
python campwatch.py test-notify --config config.yaml
```

to confirm your notification channel works, and finally:

```
python campwatch.py run --config config.yaml
```

This starts continuous mode: it checks active-hours, runs due watches, sends
notifications, and loops, forever, until the window is closed or the machine
shuts down.

---

## Part 2: Keep it running without babysitting it

A few things need to be true for this to work unattended:

1. **Prevent sleep.** Windows Settings -> System -> Power & battery ->
   Screen and sleep -> set "When plugged in, put my device to sleep" to
   **Never**. The screen can still turn off, that's fine -- sleep is what
   would actually stop the script.
2. **Start it automatically** (so a reboot or Windows Update doesn't
   silently kill it and leave you unaware):
   - Open **Task Scheduler** (search from the Start menu)
   - **Create Task** -> name it `campwatch`
   - Under **Triggers**: New -> **At log on**
   - Under **Actions**: New -> Program: `python`, Arguments: `campwatch.py
     run --config config.yaml`, Start in: the full path to your campwatch
     folder
   - Under **Conditions**: uncheck "Start the task only if the computer is
     on AC power" if this is a laptop
   - Save. It'll now start automatically every time you log in.
3. **Check on it occasionally.** `campwatch.log` in the project folder
   records every cycle. If notifications stop arriving, that's the first
   place to look.

---

## Part 3: Editing settings from your phone (still works)

The mobile app in `docs/index.html` still edits `config.yaml` on GitHub
exactly as before -- see the setup steps further down (GitHub Pages, access
token, add to home screen). What's new: your desktop needs to know to pull
those edits down.

**One-time setup on the desktop:** create a file named `remote_settings.json`
in the same folder as `config.yaml`:

```json
{
  "owner": "yourusername",
  "repo": "campwatch",
  "token": "github_pat_..."
}
```

Use the same fine-grained token you created for the mobile app (Contents:
read/write, scoped to this one repo). Omit `"token"` entirely if your repo
is public.

**Keep this file local only.** It's not part of the files you uploaded to
GitHub, and it should never end up there -- it's the one file in this whole
setup that holds a credential capable of modifying your repo.

Once this file exists, `campwatch.py run` checks GitHub for an updated
`config.yaml` every 5 minutes and reloads it automatically -- no restart
needed. If GitHub is unreachable for any reason, it logs a warning and keeps
running on whatever config it already has, rather than stopping.

---

## Part 4: setting up the GitHub side (once), for the mobile editor

The desktop runs the scanner; GitHub just hosts `config.yaml` and the mobile
app that edits it. GitHub Actions (`.github/workflows/campwatch.yml`) is
included in this project but **not used** in this setup -- it's there in
case you ever move the scanner to always-on cloud hardware later. Ignore it
for now.

### 1. Create a GitHub account
github.com -> Sign up. Free.

### 2. Create a repository
- Click the **+** in the top right -> **New repository**
- Name it something like `campwatch`
- Set it to **Private** (recommended -- see "Public vs private" below)
- Click **Create repository**

### 3. Upload the files
On your new repo's page: **Add file -> Upload files**, then drag in every
file from this folder, preserving folder structure.

### 4. Edit config.yaml on GitHub
On github.com, open `config.yaml` in your repo and click the pencil (edit)
icon. Fill in the same `facility_id`, dates, and keywords you already put in
your local `config.yaml` on the desktop -- these two copies (local and
GitHub) are your working config and the "source of truth" respectively.
Leave `notifications.email.from_password` etc. as placeholder text; those
aren't used from GitHub in this setup, only from your local file.

### 5. Notification credentials stay local
Since the desktop runs the scanner directly (not GitHub Actions), your
Gmail app password / ntfy topic / SMS gateway go directly into your local
`config.yaml`, not into GitHub Secrets. Nothing sensitive needs to leave
your desktop.

---

## Part 1.5: mobile-friendly config editor (optional but recommended)

A form-based page lives in `docs/index.html`. It edits your park watchlist,
schedule, and speed settings without you ever opening GitHub's file editor
or touching YAML. It runs entirely in your phone's browser and talks
directly to GitHub's API -- no separate server, nothing hosted by me.

**Setup (once):**

1. **Enable GitHub Pages.** Repo -> Settings -> Pages -> under "Build and
   deployment," set Source to "Deploy from a branch," Branch to `main`,
   folder to `/docs`. Save. GitHub gives you a URL like
   `https://yourusername.github.io/campwatch/` -- that's your app.
2. **Create a scoped access token.** github.com -> your profile photo ->
   Settings -> Developer settings -> Personal access tokens -> Fine-grained
   tokens -> Generate new token. Set:
   - Repository access: **Only select repositories** -> your campwatch repo
   - Permissions: **Contents** = Read and write (that's the only one you need)
   - Copy the token (starts with `github_pat_`) -- you won't see it again.
   - Use this exact same token in your desktop's `remote_settings.json`
     (Part 3 above) so both the phone and the desktop authenticate the
     same way.
3. **Open the app URL on your phone**, enter your GitHub username, repo
   name, and the token. It stores the token in your phone's browser storage
   only -- never sent anywhere but api.github.com.
4. **Add to Home Screen** (Safari share button -> Add to Home Screen) so it
   opens like a normal app, no browser chrome, no login prompt.

From then on: open the app, edit parks/dates/keywords/schedule/speed with
normal form fields, tap Save. It commits `config.yaml` to GitHub. Your
desktop picks up the change within 5 minutes (see Part 3 above) -- no
"Scan now" button needed in this setup, since the scanner is always running
rather than waiting for a trigger.

**What it deliberately can't touch:** notification credentials (email
password, ntfy topic). In this desktop setup those live only in your local
`config.yaml`, never on GitHub at all -- the mobile app only ever
sees/edits the non-sensitive watchlist and schedule fields.

A stolen or leaked token from this page could modify your GitHub-hosted
config, not your local credentials or anything else -- that's the ceiling of
what the Contents scope above allows. Still, if you ever lose your phone,
revoke the token immediately from GitHub's Developer settings page.

## Public vs private repository

**Private is the right call here.** Since GitHub Actions isn't your runner
in this setup, the "Actions minutes" budget that would push people toward a
public repo doesn't apply -- there's no meaningful downside to keeping it
private. GitHub Pages (which serves the mobile app) and the Contents API
(which the app uses to read/write `config.yaml`) both work the same on
private repos, just authenticated with your token instead of being open to
anyone.

## Reference: running on GitHub Actions instead (not used in this setup)

If you ever move off the desktop (a Raspberry Pi, a cloud VPS, or back to
GitHub Actions if ReserveCalifornia's cloud-IP block is ever lifted), the
`.github/workflows/campwatch.yml` file and the `run-once` command are built
for exactly that -- a single pass triggered externally, rather than the
continuous loop (`run`) you're using now. Nothing further to do here unless
that becomes relevant later.

---

## Why it doesn't auto-book

I deliberately built this to stop at "notify you with a link," not "complete
the reservation." Two reasons:

1. **Terms of service.** ReserveCalifornia, like most reservation platforms,
   almost certainly prohibits automated purchase completion in its user
   agreement -- worth reading the current terms at reservecalifornia.com
   yourself before assuming otherwise. Monitoring public availability data
   and notifying yourself is what every existing tool in this space does
   (CampNab, Outdoorithm, Campkey, Camphero) and is defensible as "checking
   a webpage." Programmatically completing a paid transaction is a
   different category of automation and is the piece most likely to get an
   account suspended.
2. **It's genuinely brittle.** Real booking flows have session tokens,
   bot-detection, and payment steps designed to slow down exactly this kind
   of automation, and would need constant maintenance to keep working even
   setting the ToS question aside.

## Known limitations / things to verify yourself

- The API request/response schema is verified against a currently-maintained
  open-source reference implementation as of Aug 2026, but it's unofficial
  and undocumented, and can change without notice. Run `lookup` first to
  confirm it still works before trusting this for a real trip.
- "Premium" is approximated via keyword matching on site names, not a
  guaranteed metadata field -- check the keyword list against real results
  for your target parks and adjust.
- If `lookup` or a scheduled run starts failing (check the Actions tab for a
  red X and open the log), ReserveCalifornia most likely changed its
  endpoint or response shape. See the docstring at the top of `rc_client.py`
  for how to find the current endpoint via a browser's Network tab.
