# JC SMART Brain audit — 2026-10-02

Reviewed all 14 original Python source files and all three original test files,
plus the complete FAQ JSON, Render blueprint, dependency files, and run commands.
The original 44 tests passed. The expanded suite contains 89 tests.

## Fixes

- Fixed the undefined configuration logger and centralized the package-relative
  FAQ fallback for recall, retrieval, and birthdays. Added FAQ package data.
- Kept BM25 importable without Chroma, moved Chroma to an explicit optional extra,
  avoided querying empty vector collections, invalidated BM25 after ingestion,
  and replaced colliding sequential vector document IDs with content hashes.
- Added decimal arithmetic for two operands instead of relying on four hardcoded
  examples. Handles Thai operators, signed operands, and division by zero.
- Applied compliance checks to FAQ hits. Recognizes explicit Thai negations and
  prohibition lists, accepts structured response citations, and removes duplicate
  income flags. This remains a heuristic checker, not semantic verification.
- Corrected response routing for chunks-only and LLM-error fallbacks.
- Created memory directories before writes, serialized in-process writes, used
  unique generated session IDs, preserved actual response metadata, and kept
  memory failures from replacing a valid answer. Removed an unused cache-update
  function that imported nonexistent APIs.
- Rejected blank queries and malformed birthday payloads; birthday requests now
  require a recipient instead of implicitly sending to a default account.
- Moved blocking birthday/generation handlers to FastAPI worker threads. Validated
  generation options and malformed UGC scenes; constrained endpoint download
  paths; forwarded count/email and implemented async video submission.
- Fixed missing media directories, inline image decoding errors, unnamed scene
  filenames, image-model reuse for video generation, and model validation.
- Loaded Google Flow credentials through the existing environment/.env settings.
- Pinned Render's Python runtime and used its current auto-deploy field. Fixed
  the Makefile module path and configured pytest's source path.
- Isolated tests from local credentials and memory; replaced two unconditional
  internal self-test successes with actual assertions.

## Verification

- All 59 FAQ entries have nonempty string answers; JSON parses successfully.
- All source modules import; source and tests compile without syntax errors.
- All requested live curl checks completed against the specified Uvicorn command
  on `127.0.0.1:8765`:

| Request | HTTP | Result |
| --- | --- | --- |
| GET `/health` | 200 | status ok |
| GET `/` | 200 | service metadata |
| `/brain`: pv คืออะไร | 200 | PV answer |
| `/brain`: อวยพรวันเกิด | 200 | birthday wish |
| `/brain`: 123+456 | 200 | 579 |
| `/brain`: มีผลิตภัณฑ์อะไรบ้าง | 200 | product categories |
| `/brain`: หาสาขาใกล้ตัว | 200 | branch guidance |
| `/brain`: ขึ้น Platinum ยังไง | 200 | Platinum FAQ |
| `/brain`: สวัสดี | 200 | greeting |
| `/brain`: หวยออกเลขอะไร | 200 | fallback, ungrounded |
| `/brain/birthday`: TEST / funny | 200 | generated wish; pushed false |
| `/brain`: empty object | 422 | missing query |
| `/brain/generate`: missing prompt | 200 | structured validation error |
| `/brain/generate`: malformed scene | 200 | structured validation error |

The birthday delivery attempt was rejected by LINE because authorization was
missing. Successful external LINE delivery and paid image/video generation are
not verified; generation success paths are tested with mocks. The listed business
answers were checked for response behavior, not against current company policies.

Deployment settings were checked against Render's
[Python version](https://render.com/docs/python-version) and
[Blueprint specification](https://render.com/docs/blueprint-spec) documentation.
No remote deployment was performed. The free plan's local storage is ephemeral.

Final verification after stopping the server: **89 passed** with
`PYTHONPATH=src .venv/bin/pytest tests/ -v --tb=short`. A separate clean Python
3.11 environment installed `requirements.txt`, passed `pip check`, and also
passed all **89 tests** without Chroma. Compilation and `git diff --check` passed.
Port 8765 was confirmed closed.
