# Running the multi-participant study

What this deployment does, concretely:

- Each participant connects one of your **Google sandbox accounts** via a
  real OAuth flow (Gmail + Calendar, one combined consent).
- The poller reads their unread mail, classifies it, and **drafts a
  reply directly into their Gmail Drafts folder** — nothing is ever sent
  automatically. That's the human-in-the-loop for replies: a draft sits
  there until a person opens Gmail and sends it.
- A meeting-classified email **never books a calendar event by itself**.
  It creates a *pending proposal* instead. A reviewer looks at it on the
  `/admin` page and explicitly approves or rejects it — only approval
  calls the Calendar API and actually creates the event.
- No database of raw email content exists. The one thing persisted is a
  small SQLite file (`study.db`) holding each participant's OAuth token
  (encrypted at rest), pending-proposal metadata, a per-email log
  (category/handler/short preview, backing the check-in page below), and
  participants' daily feedback. See `NOTES.md` for the fuller data-flow
  writeup.
- Each participant gets one private link — shown once on the "Connected"
  page right after they sign in — to a **daily check-in page**
  (`/checkin/{token}`). It shows "Day N of the study," what the pipeline
  did with each of today's emails, and collects their feedback: per-email
  correct/wrong, an overall 1–10 draft-quality rating, and free-text
  notes. One submission per participant per day; visiting again the same
  day shows a "thanks, come back tomorrow" state instead of the form.

The `/admin` page, the "Connected" page, and the check-in page are all
**plain server-rendered HTML, deliberately built to look reasonably clean
rather than as throwaway placeholders** — but still simple single-file
pages with no framework, easy to swap out later if you redesign the study
UI. Every action any of them trigger is a plain JSON/HTTP endpoint:

| Action | Endpoint |
|---|---|
| Start OAuth for a participant | `GET /auth/start?participant_id=<id>` (redirects to Google) |
| OAuth callback (registered with Google, not called by a UI) | `GET /auth/callback` |
| Disconnect + delete a participant's data | `POST /auth/disconnect?participant_id=<id>` |
| List pending meeting proposals | `GET /admin/pending` (header `X-Admin-Token`) |
| Approve a proposal → really books the event | `POST /admin/pending/{id}/approve` |
| Reject a proposal | `POST /admin/pending/{id}/reject` |
| Classify one email with no account (the "simulated form" option) | `POST /route-email` |
| A participant's daily check-in page | `GET /checkin/{checkin_token}` |
| Submit a day's feedback | `POST /checkin/{checkin_token}/submit` |

## 1. Google Cloud Console (once)

1. In the same project as your sandbox accounts, create an OAuth client
   of type **Web application** (not "Desktop app" — that's the older
   single-account flow in `credentials.json`/`test_gmail.py`).
2. Add an **authorized redirect URI** matching `OAUTH_REDIRECT_URI`
   below exactly, e.g. `https://your-deployment.example.com/auth/callback`.
3. Download its client secret JSON, save it as `oauth_client_secret.json`
   (path is configurable — see `.env.example`).
4. On the OAuth consent screen, keep publishing status as **Testing**
   and add every sandbox participant account as a **test user**. This
   avoids Google's verification review entirely (only required for
   "In production" + 100+ users) — the tradeoff is a 100 test-user cap,
   plenty for a study.

## 2. Configure and run

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY, TOKEN_ENCRYPTION_KEY, ADMIN_TOKEN

pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

This single process serves the API/OAuth routes *and* runs the poller
loop in a background thread, checking every connected participant's
inbox every `POLL_INTERVAL_SECONDS`.

## 3. Enroll participants

Send each participant (or open yourself, once per sandbox account):

```
<your-url>/auth/start?participant_id=p01
```

Pick your own `participant_id` per account (`p01`, `p02`, ...) so you can
tell them apart later — omit it and a random one is generated.

## 4. Review proposed meetings

Open `<your-url>/admin`, enter your `ADMIN_TOKEN`, and approve/reject each
proposal. Approving calls the Calendar API right then, on that
participant's own calendar.

## What's still a placeholder, on purpose

- `/admin` and the post-connect page are minimal HTML, meant to be
  replaced once you've decided the real study UI (participant-facing?
  researcher-facing? both?). Nothing else needs to change — build
  against the endpoints table above.
- Admin auth is a single shared token header, fine for a small study,
  not for anything wider.
- The routing log (`logs/routing_log.jsonl`) still keeps a 200-char
  reply preview per email — worth trimming or covering explicitly in
  your consent form before the study starts.
