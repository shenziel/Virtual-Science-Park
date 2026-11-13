# CLAUDE.md

@AGENTS.md

The file above is the team's shared rulebook. It is imported, not copied, so it can't drift, and it **takes precedence** over this file. Below are Claude Code–specific additions only.

## At the start of every session
1. Ask which role (Backend 1–3, UI 1–2) you are working for, unless the user already said. Repeat it back: "Working only in `<folder>`."
2. Read `contracts/` and the existing code in that folder before writing anything.
3. For new behaviour, write the pytest cases from the contract first, then the code.

## Permissions
- ✅ **Without asking:** read any file; run `pytest`, linters and the app locally; edit files inside the owner's folder.
- ⚠️ **Ask first:** installing a package; anything touching auth or permission checks; DB schema or migrations; prompts that ship inside an agent.
- ❌ **Refuse and explain:** editing another person's folder or `contracts/` (unless the user is Backend 1); force-pushing or committing to `main`; touching `.env` or secrets.

## Style
- Make the smallest change that does the job. No drive-by refactors or reformatting.
- Report test results honestly, failures included.
- Keep replies short: what changed, the test result, and anything the owner of another folder needs to know.
- Commit only when asked, on the person's own branch, with a Conventional Commit message.
