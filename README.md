# CCA-F Learning Path, open course

Mohammed Mustafa's CCA-F course as an open website: the course material and the practice exam,
with no sign-in, no accounts and no Claude tutor. Each reader's ticks, highlights and notes stay in
their own browser.

Live at https://ccaf.core.kapitaresearch.com, served by
nginx on kapita-core through Coolify (project `ccaf-course`). After a push to `main`, redeploy the app in Coolify.

`index.html` is `course/learning-path.html` from `Kapita-Research/ccaf-server` (course v2.8),
unchanged. Opened without the tutor relay, the page keeps its tutor dormant by design. To update the
course, replace the two HTML files with the new version and push.
