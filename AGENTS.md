# AGENTS.md — Madblog

## Description
A Python Markdown-based blogging platform with ActivityPub and Webmentions support.

## Context
Design decisions are documented under `./docs/agents`. Directories and files follow the `<nn>-title` naming convention, with `<nn>` being the number of the design decision.

## Correctness
- **Always run `pytest`** after code modifications, before committing. Fix any issues it reports before proceeding.
- Every new feature or code change should be accompanied by at least a unit test in order to keep test coverage high.
- **Do not commit** after implementing, unless prompted explicitly.

## Style
- **Always run `pre-commit run --all-files`** after code modifications, before committing. Fix any issues it reports before proceeding.

## Commit messages
Generate a semantically correct git commit message with textwrap at 80 chars for the staged changes (and _ONLY_ for the staged changes).

1. First line: conventional commit format (type: concise description) (remember to use semantic types like feat, fix, docs, style, refactor, perf, test, chore, etc.)
2. Optional bullet points if more context helps:
3. Keep the second line blank
4. Keep them short and direct
5. Focus on what changed
6. Always be terse
7. Don't overly explain
8. Drop any fluffy or formal language

Generate ONLY the commit message - no introduction, no explanation, no quotes around it.

## Documentation
- When adding or changing public API (new classes, functions, parameters), update the corresponding section in `README.md`.
- Key areas: **API** section (data model, WebFinger, publishing), **Configuration Reference** (fields, parameters), **Quick Start** examples.
- Keep docstrings and README in sync — the README is the primary user-facing reference.
- The base URL for the repository is https://git.fabiomanganiello.com/madblog, and it runs on a Forgejo instance. Keep that in mind when you want to attach references to the codebase.

## CHANGELOG
- Add an _Unreleased_ section (if not already present) to `CHANGELOG.md`.
- Write in the _Unreleased_ section a brief description of the changes made since the latest git tag, leveraging both the git log and git diff commands to generate the description.
- Use the conventions in the CHANGELOG (e.g. _Added_, _Fixed_, _Removed_, _Changed_) for the names of the subsections.
- Reference links to the issues should be added as URLs to the issue numbers, e.g. `[#1234](https://github.com/...)`, using the appropriate URL remote configured for this git repository.
