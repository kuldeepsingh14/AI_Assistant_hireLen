# Hosting HireLens free

Backend on **Render** (free web service), frontend on **Vercel** (free hobby).
Both read from one repository.

---

## Before you start: make the repo private

The `backend/data/seed/` folder is how the site survives a restart — Render's
free disk is wiped on every deploy and every wake-from-sleep, so the resume has
to be committed to come back. That puts your phone number and email in git
history permanently.

**Recommended: keep the GitHub repo private.** Vercel and Render both deploy
from private repos on their free tiers, so you lose nothing.

If you want the repo public, leave `backend/data/seed/` empty and re-upload your
resume through the admin console after each restart.

Never commit `backend/.env` or `backend/data/analytics.db` — the first holds your
API key, the second holds recruiters' contact details. Both are already in
`.gitignore`.

---

## 1. Push the repo

```bash
git init
git add .
git commit -m "Initial commit: HireLens"
git branch -M main
git remote add origin https://github.com/<you>/hirelens.git
git push -u origin main
```

---

## 2. Backend on Render

1. **New → Blueprint**, point it at the repo. Render reads `render.yaml`.
2. Fill the variables it marks as required:

   | Variable | Value |
   | --- | --- |
   | `GROQ_API_KEY` | free key from <https://console.groq.com/keys> |
   | `ALLOWED_ORIGINS` | your Vercel URL — fill in after step 3, then redeploy |
   | `OWNER_NAME` | leave blank to read the name from your resume |

   `ADMIN_TOKEN` is generated for you. Copy it from the Render dashboard —
   it's what unlocks the admin console.

3. Wait for the first deploy, then check `https://<service>.onrender.com/api/health`.

`EMBEDDER=lexical` is set deliberately. Do not switch it to `fastembed` on the
free tier: loading the ONNX model exceeds 512 MB and the worker is OOM-killed
mid-request, which surfaces as a 502 rather than an obvious memory error.

---

## 3. Frontend on Vercel

1. Put your Render URL in `frontend/src/environments/environment.prod.ts`:

   ```ts
   export const environment = {
     production: true,
     apiUrl: 'https://hirelens-api.onrender.com',
   };
   ```

   Commit and push.

2. **Add New → Project**, import the repo, and set:

   | Setting | Value |
   | --- | --- |
   | Root Directory | `frontend` |
   | Framework Preset | Other |

   `frontend/vercel.json` handles the build command, output directory, and SPA
   routing.

3. Deploy, then copy the Vercel URL back into Render's `ALLOWED_ORIGINS` and
   redeploy the backend.

**If the site loads but every request fails**, it is almost always
`ALLOWED_ORIGINS` not matching the Vercel URL exactly — scheme included, no
trailing slash. The app's error message names the origin it was refused from.

---

## 4. Stop the backend falling asleep

Render suspends a free service after ~15 minutes idle; the next visitor waits
~50 seconds. `.github/workflows/keep-alive.yml` pings it every 10 minutes.

Enable it by setting one repo variable:

> Settings → Secrets and variables → Actions → Variables → New variable
> `API_URL` = `https://hirelens-api.onrender.com`

Render allows 750 instance-hours per month and a month is ~730 hours, so **one**
always-awake free service fits. If you already keep another service awake this
way, they will not both fit and Render will suspend them.

---

## 5. Seed the profile

So the site is never empty after a restart, commit into `backend/data/seed/`:

- your resume — one `.pdf`, `.docx`, `.txt`, or `.md`
- `notes.md` *(optional)* — the context notes from the admin console

They are indexed on boot **only when no profile is already loaded**, so an
upload through the console always wins while the server is running.

To export the notes you have already written, open the admin console, copy the
notes box, and save it as `backend/data/seed/notes.md`.

---

## What does not survive a restart

| Data | Survives? | Why |
| --- | --- | --- |
| Resume + notes | Yes, if seeded | Re-indexed from the committed files |
| Uploaded resume (console) | No | Ephemeral disk |
| Question log | No | SQLite file on the ephemeral disk |
| Recruiter contacts | **No** | Same — export anything you need |

Recruiter contacts being lost on a restart is the one that stings. Check the
admin console periodically, or move `analytics.db` onto a Render persistent disk
(a paid add-on) if inbound leads start mattering.

---

## Costs

Everything above is free: Render free web service, Vercel hobby, Groq free tier,
GitHub Actions free minutes. The limits that bite first are Groq's 8,000
tokens/minute (see the rate-limit section in `README.md`) and Render's 750
instance-hours.
