# campwatch

A personal ReserveCalifornia cancellation scanner. It watches specific parks
and site types, and notifies you the moment a matching cancellation opens up.
You still click through and book it yourself -- it never submits a
reservation or payment (see "Why it doesn't auto-book" below).

This version is built to run entirely on GitHub Actions -- no desktop,
terminal, or always-on machine required. Setup is done through github.com in
a browser.

---

## Part 1: One-time setup (browser only, ~15 minutes)

### 1. Create a GitHub account
github.com -> Sign up. Free.

### 2. Create a repository
- Click the **+** in the top right -> **New repository**
- Name it something like `campwatch`
- Set it to **Private** (recommended -- see "Public vs private" below)
- Click **Create repository**

### 3. Upload the files
On your new repo's page: **Add file -> Upload files**, then drag in every
file from this folder, preserving the `.github/workflows/campwatch.yml` path
(GitHub's upload UI supports dragging a whole folder structure, or you can
create `.github/workflows/campwatch.yml` by hand via **Add file -> Create
new file** and pasting its contents if drag-and-drop flattens it).

Do **not** put real credentials in `config.yaml` before uploading -- edit
`config.yaml` in the repo afterward (see step 5) with placeholder-safe
values, and provide credentials via Secrets instead (step 6).

### 4. Find your facility IDs
You need this before the config makes sense, and it requires running Python
once. Easiest path with no local setup: use **GitHub Codespaces** (a free,
browser-based VS Code + terminal that runs in the cloud -- click **Code ->
Codespaces -> Create codespace** on your repo). In the terminal that opens:

```bash
pip install -r requirements.txt
python campwatch.py lookup "Pfeiffer Big Sur"
```

This prints every matching park and its facilities with their `facility_id`.
Repeat for each park you care about. Close the Codespace when done (it's
free for a generous monthly quota and you'll only use minutes occasionally).

### 5. Edit config.yaml
On github.com, open `config.yaml` in your repo and click the pencil (edit)
icon. Fill in:
- `facility_id` for each park (from step 4)
- `start_date` / `end_date` for what you're watching
- `keywords` to approximate "premium" (see note in the file)
- `schedule.active_hours` -- when you want to actually receive alerts
- Leave `notifications.email.from_password` etc. as placeholder text --
  these get overridden by Secrets in the next step and are ignored if a
  Secret is set.

Commit the change directly to `main`.

### 6. Add your credentials as Secrets
Repo -> **Settings -> Secrets and variables -> Actions -> New repository
secret**. Add whichever of these you're using:

| Secret name | Value |
|---|---|
| `CAMPWATCH_NTFY_TOPIC` | A hard-to-guess topic name, e.g. `banyan-camp-a8f3d2` |
| `CAMPWATCH_EMAIL_FROM` | Your Gmail address |
| `CAMPWATCH_EMAIL_PASSWORD` | A Gmail [App Password](https://support.google.com/accounts/answer/185833) (not your real password) |
| `CAMPWATCH_EMAIL_TO` | Where to send alerts (can be the same address) |
| `CAMPWATCH_SMS_GATEWAY` | e.g. `5551234567@txt.att.net` -- see carrier list below |

**Recommendation for your setup (iPhone, no desktop use): use ntfy.** Install
the free ntfy app from the App Store, open it, subscribe to the same topic
name you put in the Secret. That's it -- no email/SMTP fuss, and pushes
arrive like a normal notification. You can enable email or SMS in addition
if you want belt-and-suspenders.

Carrier SMS gateways: `@txt.att.net` (AT&T), `@vtext.com` (Verizon),
`@tmomail.net` (T-Mobile), `@messaging.sprintpcs.com` (Sprint).

### 7. Turn it on and test it
Repo -> **Actions** tab -> you should see the "campwatch" workflow listed.
Click into it -> **Run workflow** (this is the manual trigger button, in
addition to its 5-minute schedule) -> **Run workflow**. Watch it execute;
green check = success. Check your phone for a notification if any watch had
availability (or run `test-notify` in a Codespace first to confirm channels
work before your first real run).

From here it runs itself, every 5 minutes, forever, for free.

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
   - Permissions: **Contents** = Read and write, **Actions** = Read and
     write (the second one only if you want the "Scan now" button)
   - Copy the token (starts with `github_pat_`) -- you won't see it again.
3. **Open the app URL on your phone**, enter your GitHub username, repo
   name, and the token. It stores the token in your phone's browser storage
   only -- never sent anywhere but api.github.com.
4. **Add to Home Screen** (Safari share button -> Add to Home Screen) so it
   opens like a normal app, no browser chrome, no login prompt.

From then on: open the app, edit parks/dates/keywords/schedule/speed with
normal form fields, tap Save. It commits `config.yaml` for you. A "Scan now"
button also lets you trigger an off-schedule check on demand.

**What it deliberately can't touch:** notification credentials (email
password, ntfy topic). Those stay as GitHub Secrets, edited through GitHub's
own Settings page -- something you'll set up once and rarely revisit, versus
watchlist edits you'll make often. Keeping credentials out of a page that
holds a repo-write token in local storage is the safer split.

A stolen or leaked token from this page could modify your config, not your
Secrets or anything outside this one repo -- that's the ceiling of what the
Contents+Actions scopes above allow. Still, if you ever lose your phone,
revoke the token immediately from GitHub's Developer settings page.

## Public vs private repository

- **Private** (recommended default): your park/date watchlist stays visible
  only to you. GitHub's free plan includes 2,000 Actions minutes/month for
  private repos. A 5-minute schedule with a small watchlist (2-3 coverage +
  1 targeted watch) uses roughly 1,000-1,500 minutes/month in practice --
  within budget, but if you add many watches or see "workflow minutes used
  up" warnings, either widen `coverage_interval_minutes` or switch the repo
  to public.
- **Public**: Actions minutes are unlimited and free regardless of plan,
  since the repo counts as open source. The only real downside is anyone can
  see which parks and dates you're watching (never your credentials -- those
  stay in Secrets either way, which are never exposed in a public repo).

## Part 2 (optional): running continuously on your own machine instead

The `run` command (vs `run-once`) does the same thing as a persistent loop,
for a Raspberry Pi or cloud VPS you leave on -- not needed given your setup,
but here for reference: `python campwatch.py run --config config.yaml`.

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
