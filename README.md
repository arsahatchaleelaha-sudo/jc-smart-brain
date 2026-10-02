# JC SMART Brain — สมองกลางที่ทุก agent เรียกใช้ร่วมกัน

สมองกลาง (brain middleware) ของ J&C — cache-first, grounded, compliance-guarded
สำหรับ jwizs.com และ agent อื่นๆ เรียกใช้งานผ่าน API

## สถานะปัจจุบัน

- **11 กลุ่มความรู้, 59 entries** ใน `src/brain/kb/faq_entries.json`
- **6-layer pipeline** สำเร็จ: sense → recall → ground → reason → guard → learn
- **89/89 pytest เขียว** — health, cache_hit, fallback, compliance, provenance, error handling
- **23/23 live comparison vs jwizs.com** — Brain 0 errors, 0 timeouts
- **LINE birthday push** สำเร็จ — POST /brain/birthday ส่งไป LINE API ได้ (quota เดือนนี้หมดแล้ว)

## โครงสร้าง

```
src/brain/
├── main.py              # FastAPI app + /health + /brain + /brain/birthday
├── config.py            # Settings (env + defaults)
├── models.py            # ThinkRequest, ThinkResponse, SourceDoc, ComplianceResult
├── pipeline.py          # Orchestrate 6 layers (asyncio.gather sense+recall)
├── layers/
│   ├── sense.py         # Intent classification
│   ├── recall.py        # FAQ cache (JSON lookup)
│   ├── ground.py        # BM25 keyword + vector store
│   ├── reason.py        # Anthropic LLM (asyncio.to_thread)
│   ├── guard.py         # Compliance check
│   └── learn.py         # Feedback memory
├── kb/
│   └── faq_entries.json # 11 groups, 59 entries
└── integrations/
    └── line_birthday.py # LINE push for birthday wishes

tests/
└── test_acceptance.py   # 10 acceptance tests

Makefile                  # dev, test, lint, clean
pyproject.toml            # deps + pytest config
README.md                 # นี้
```

## วิธีรัน

```bash
uv sync --extra dev # ติดตั้ง deps
uv run make dev    # รัน local (port 8000)
uv run make test   # pytest ทั้งหมด
uv run make lint   # ruff check
```

## API

### POST /brain
```json
{
  "query": "pv คืออะไร",
  "agent_id": "jwiz-customer"
}
```
Response: ThinkResponse (answer, route, grounded, compliance, provenance, cost, latency_ms)

### POST /brain/birthday
```json
{
  "user_id": "LINE_MID",
  "wish_type": "general|partner|team|customer|leader|short|long|funny|formal|line",
  "custom_text": "optional"
}
```
Response: {status, wish_type, wish_text, user_id, pushed, detail}

## KB ทั้งหมด (59 entries)

- greetings / smalltalk: 3 (สวัสดี, เฮ้ย, ลาก่อน)
- pv / pt / ppi: 4 (pv, bv, pt, ppi)
- ผลิตภัณฑ์ / catalog: 6 (สินค้ามีอะไรบ้าง, สินค้าทั้งหมด, catalog, สินค้า, มีผลิตภัณฑ์อะไรบ้าง, ผลิตภัณฑ์)
- บริษัท: 2 (j&c คืออะไร, join and coin)
- เรียนรู้ / coaching: 6 (learning center, ศูนย์การเรียนรู้, เริ่มประเมินตัวเอง, เริ่มยังไง, เริ่มต้น, 30 วันแรก)
- สนับสนุน: 4 (ติดต่อเจ้าหน้าที่, ช่วย, help, สนับสนุน)
- โฆษณา / content: 4 (โฆษณา, tiktok, clip, โพสต์)
- คณิตศาสตร์: 9 (บวก, ลบ, คูณ, หาร, เท่ากับ)
- สาขา: 4 (สาขา, สาขาใกล้ฉัน, หา, หาสาขาใกล้ตัว)
- ตำแหน่ง: 4 (ตำแหน่ง, เลื่อน, Platinum, ขึ้น Platinum)
- birthdays: 13 (อวยพรวันเกิด + 12 แบบย่อย)

## LINE Birthday Push

ส่งไป LINE user ได้จริง ตัวอย่าง:
```bash
curl -X POST http://localhost:8000/brain/birthday \
  -H "Content-Type: application/json" \
  -d '{"user_id": "LINE_MID", "wish_type": "funny"}'
```

`LINE_CHANNEL_SECRET` และ `LINE_ACCESS_TOKEN` ต้องตั้งใน `.env` จึงจะ push ได้ (ดู `.env.example`)

## กฎ

- test-first — ไม่มี test = ยังไม่เสร็จ
- ทำทีละ feature — แต่ละอย่างต้อง pytest เขียว
- ไม่ hardcode secret — ทุก key จาก env
- ทุกคำตอบต้อง grounded — reason layer ตอบจาก chunks + citation

## เชื่อมต่อกับ jwizs.com

jwizs.com เรียก POST /brain แทน logic เดิม
เริ่มจาก 1 endpoint, A/B เทียบคุณภาพ+cost, ค่อยๆ ย้าย


## Deployment and audit (2026-10-02)

The Render service installs `requirements.txt` and runs `brain.main:app` with
`PYTHONPATH=src`, Python 3.11.16, and `/health` as its health check. The default
installation uses BM25. Install `.[vector]` to enable the optional Chroma backend.
The bundled FAQ is included in package builds and resolves outside the repository
working directory. The free Render plan uses ephemeral local storage; session
memory and generated files are not durable across redeploys.

Run the audit suite with:

```bash
PYTHONPATH=src .venv/bin/pytest tests/ -v --tb=short
```

`/brain/birthday` requires an explicit `user_id`. Its `pushed` field reports LINE
success separately from generating the wish. The optional `jarvis_line` module
and its LINE credentials must be installed/configured to deliver messages.

`/brain/generate` reads `USEAPI_TOKEN` and `USEAPI_EMAIL` from environment or
`.env`. Its synchronous network calls run in FastAPI's worker threads. Downloads
are restricted to `FLOW_OUTPUT_DIR` (default `/tmp/google_flow_out`); a relative
`output_dir` is resolved under that directory. For multiple generated assets,
`urls` contains the returned URLs and `local_path` refers to the first download.
Video requests with `async_mode: true` return the upstream job ID and `job_status`.

See [AUDIT.md](AUDIT.md) for findings, verification, and external-service limits.
