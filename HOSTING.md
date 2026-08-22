# Hosting HireLens free

Backend on **Render** (free web service), frontend on **Vercel** (free hobby).
Both read from one repository.

---

## This repository is public

Render's free disk is ephemeral: **every deploy wipes it**, and since every code
push triggers a deploy, anything uploaded through the admin console disappears
regularly.

`backend/data/seed/` solves that without leaking anything. It holds a
**contact-free** copy of the résumé — phone number and email stripped — plus the
context notes. On boot, if no profile is loaded, both are indexed automatically.
So the assistant answers correctly after every deploy, and the only thing a
public repo costs you is the résumé *download* button, which needs the original
file uploaded through the console.

Visitors do not see a broken site in that window: the assistant says it is being
set up, and the composer is disabled. It never routes a visitor to the admin
screen.

If you later decide the convenience is worth it, make the repo private first,
then drop your resume and a `notes.md` into `backend/data/seed/`. It is indexed
on boot whenever no profile is loaded.

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

## 5. Profile content

The assistant seeds itself from `backend/data/seed/` on every boot, so there is
nothing to do after a deploy.

Two settings are worth having in Render → Environment:

| Variable | Value | Why |
| --- | --- | --- |
| `OWNER_NAME` | `Kuldeep Singh` | Shows the name from the first paint, even before anything is indexed |
| `OWNER_PRONOUNS` | `he/him`, `she/her`, or `they/them` | The one thing that cannot be read from a résumé |

To enable the résumé **download** button, upload the original file through the
admin console. That copy lives on the ephemeral disk, so redo it after a deploy
if the download matters to you.

To update the seeded content, edit `backend/data/seed/resume.md` or `notes.md`
and push.

---

## What does not survive a restart

| Data | Survives? | Why |
| --- | --- | --- |
| Résumé answers + notes | **Yes** | Re-indexed from `backend/data/seed/` |
| Résumé PDF download | No | The original file is not committed on a public repo |
| Question log | No | SQLite file on the ephemeral disk |
| Recruiter contacts | **No** | Same — export anything you need |

Recruiter contacts being lost is the one that stings, since those are real
inbound leads. Check the admin console periodically rather than assuming they
will keep. Moving `analytics.db` onto a Render persistent disk (a paid add-on)
is the only way to make them durable.

Keep-alive keeps the service awake, so in practice the disk is only wiped by a
redeploy rather than by idling.

Your local copies live in `backend/data/` (gitignored): `index/notes.txt` holds
the notes text you can paste straight back into the console, and
`resume/` holds the last resume you uploaded.

---

## Costs

Everything above is free: Render free web service, Vercel hobby, Groq free tier,
GitHub Actions free minutes. The limits that bite first are Groq's 8,000
tokens/minute (see the rate-limit section in `README.md`) and Render's 750
instance-hours.
