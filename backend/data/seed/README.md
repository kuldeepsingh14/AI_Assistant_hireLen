# Seed profile

Files here are committed with the repo and loaded automatically **when no
profile is already indexed** — which is every restart on a host with an
ephemeral disk, such as Render's free tier.

Put in this folder:

- **Your resume** — one `.pdf`, `.docx`, `.txt`, or `.md` file. The first
  matching file in alphabetical order is used.
- **`notes.md`** *(optional)* — the same context notes you'd write in the admin
  console: job-search status, what you're learning, what you want next.

Uploading through the admin console always takes precedence while the server is
running; these files only fill an empty profile.

> **This repository is public, so what lives here is public and permanent.**
> `resume.md` is therefore a *contact-free* copy: the phone number and email
> address have been stripped. Everything else — employers, projects, education —
> is the same information a public LinkedIn profile carries.
>
> Do not add the original PDF here while the repo is public. Uploading it through
> the admin console still enables the résumé download for visitors; it just does
> not survive a redeploy.
