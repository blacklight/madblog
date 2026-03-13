# AGENTS.md — Madblog

## Description
A Python Markdown-based blogging platform with ActivityPub and Webmentions support.

## Context
Read `./docs/ARCHITECTURE.md` for an overview of the design.

Design decisions are documented under `./docs/agents`. Directories and files follow the `<nn>-title` naming convention, with `<nn>` being the number of the design decision.

## Correctness
- **Always run `pytest`** after code modifications, before committing. Fix any issues it reports before proceeding.
- Every new feature or code change should be accompanied by at least a unit test in order to keep test coverage high.
- **Do not commit** after implementing, unless prompted explicitly.

## Style
- **Always run `pre-commit run --all-files`** after code modifications, before committing. Fix any issues it reports before proceeding. Note that it's not required to run tests again after modifications triggered by `pre-commit`.

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

## Execution style

### Conclusion of an implementation phase

An implementation phase is considered concluded when I have reviewed and acknowledged the changes in the chat, or, for large tasks (see next paragraphs), when all the phases have been completed and I have reviewed and acknowledged the work.

- Any user-facing changes should be documented in the `README.md` (only if such changes are relevant to `README.md`).
- Any architectural changes, API changes or additions/deletions of modules should be documented in `docs/ARCHITECTURE.md` (only if such changes are relevant for an architecture document).
- Update the `CHANGELOG.md` by adding the new feature under the _Unreleased_ section (generate it if necessary).
- At the end of an implementation phase, and upon acknowledgment from my side, write down a commit message in the chat after checking again the git status, following the guidelines specified previously in this document (but _do not_ commit_).

### Large tasks

When addressing large tasks that require several iterations and validation cycles, or when I explicitly say "this is a large task", use a structured approach:

- **Context directory**: Document your process under `docs/<nnn>-feature`, where `<nn>` is the number of the feature. Add a `README.md` under that folder that briefly describes the feature at a very high level, and then proceed with adding relevant links in the README to additional sub-pages as they get added.

- **Keep track of the HEAD commit** at this point. It'll be useful later to identify where the implementation of the new features started, in order to generate consistent commit messages or CHANGELOG items, or rollback.

- **Keep track of follow-ups**: Everything that we agree to be a follow-up after mutual acknowledgment in the research, planning or implementation phases should be written to `99-FOLLOW-UP.md` in the feature documentation folder.

- **Research**: Look into `/README.md`, `docs/ARCHITECTURE.md` and any place under `docs` that may contain relevant context. Scan the code when the answers don't come from the existing documentation. Write down your findings and proposed approaches into `01-RESEARCH.md` under the feature documentation folder.

- **Iterate over the research document**: I may add comments, either on the document itself or in the chat, that require further iterations. When that's the case, keep refining the research document until I suggest to proceed with the planning.

- **Planning**: Re-read the research document and proceed with proposing a plan. Write down the plan into `02-PLAN.md` under the feature documentation folder. The plan should be split in phases.

- **Iterate over the plan document**: Same guidelines as _Iterate over the research document_.

- **Implementation**: Re-read the plan document and proceed with coding. Implement one phase at the time, and proceed with the next point only when instructed with an `ok` from my side.

- **Summary**: Upon mutual acknowledgment of the implementation, write down a summary of your implementation into `docs/<nnn>-feature/implementation/<nn>-<description>.md`.  When I say `ok` or `next` you can proceed with implementing the next phase. Keep iterating until the last phase.

- **Revise**: After all implementation phases are completed, go through the summaries generated under `docs/<nnn>-feature/implementation` and, if necessary, fill missing gaps either in the tests or in the documentation.

- **Wrap up**: When the implementation is completed, updated `CHANGELOG.md` with a summary of the feature, under the _Unreleased_ section (create it if missing), following the guidelines for `CHANGELOG` generation already outlined previously in this document.

- **Follow-ups**: Give a last read to the produced documents and write any follow-ups to `99-FOLLOW-UP.md` in the feature documentation folder.
