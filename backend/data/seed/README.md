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

> **This puts your resume in your git history.** This repository is public, so
> the folder is deliberately left empty — a committed resume would make your
> phone number and email permanently searchable, and removing them later does
> not erase them from history.
>
> Only use this folder if you make the repository private first.
