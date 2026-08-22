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

> **This puts your resume in your git history.** If the repository is public,
> your phone number and email become permanently searchable. Keep the repo
> private, or leave this folder empty and re-upload through the console after
> each restart.
