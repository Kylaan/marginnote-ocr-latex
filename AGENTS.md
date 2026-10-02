# Project instructions

Read README.md and docs/AGENT_WORKFLOW.md before changing question data.
Preserve source images/database and raw OCR. Put reviewed corrections in
json/manual/fixups.json with local evidence. Do not infer missing question text
from answers. Only process images.question for question OCR.

Do not call an OCR endpoint merely to validate this delivered instance; offline
validation, dry-run and mock tests are sufficient. Do not read user credential
files or write credentials into repository data.

Use isolated candidate directories for multiple agents, only when delegation
has been authorized. One writer merges results. Run tools/check_project.py
before delivery. If changing typesetting, regenerate, compile and verify both
editions; describe automated and visual verification separately.

Do not initialize/push a remote repository without a user request to do so.
The project is an upload-ready directory and already includes LFS attributes.
