# CCA-F Learning Path, open course

Mohammed Mustafa's CCA-F course as an open website: the course material and the practice exam.
No Claude tutor. Anyone can read without signing in, and their ticks, highlights and notes stay in
that browser. Anyone can also create an account (email and password), which saves the same record
on the server so it follows them to any browser. Nobody else sees it: there is no admin page and
no tracking.

Live at https://ccaf.core.kapitaresearch.com, on kapita-core through Coolify (project `ccaf-course`).
After a push to `main`, redeploy the app in Coolify.

- `index.html` is `course/learning-path.html` from `Kapita-Research/ccaf-server` (course v2.8),
  unchanged on disk. `server.py` swaps a few lines as it serves it (`SWAPS`) to keep the tutor off
  and turn on the page's own progress sync when someone is signed in. If a new course version moves
  those lines, the server refuses to start and says which one, rather than serving a broken page.
- `server.py` is standard-library Python. Data lives in `/data` (a Coolify volume): `users.json`
  (passwords hashed with PBKDF2), `sessions.json`, and `progress/<id>.json`.
- There is no password reset. A forgotten password means a new account.
- To update the course, replace the two HTML files with the new version, push, and redeploy.
