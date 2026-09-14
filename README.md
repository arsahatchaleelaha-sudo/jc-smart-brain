# JC SMART Brain — สมองกลางที่ทุก agent เรียกใช้ร่วมกัน
#
# Spec: ARCHITECTURE.md (phase plan, 6 layers, API contract, success metrics)
# This repo = Path B ของแผนซ่อม jwizs.com -> สร้างสมองกลางที่ cache-first, grounded, compliance-guarded

## สร้างเมื่อไหร่
2026-09-08 — เริ่มจาก Phase 0 (skeleton + health check + pgvector + 1 test)

## สิ่งที่มีตอนนี้
- `src/brain/` — FastAPI app + 6 layers (sense/recall/ground/reason/guard/learn)
- `tests/` — test ทุก layer + acceptance
- `kb/` — KB ไฟล์ .md (จาก J&C_FAQ_Master_100 + Blueprint)
- `deploy/` — emergent.host + fallback deploy

## วิธีรัน
```bash
uv sync          # ติดตั้ง deps
uv run make dev  # รัน local (โหนด + pgvector)
uv run make test # pytest ทั้งหมด
```

## กฎ
- test-first — ไม่มี test = ยังไม่เสร็จ
- ทำทีละ phase — Phase ปัจจุบันต้อง pytest เขียว ก่อนไป phase ถัดไป
- ไม่ hardcode secret — ทุก key จาก env (.env)
- ทุกคำตอบต้อง grounded — reason layer ตอบจาก retrieved chunks เท่านั้น + citation

## เชื่อมต่อกับ jwizs.com
Phase 5 (ARCHITECTURE.md §7.5) — jwizs.com เรียก POST /brain แทน logic เดิม
เริ่มจาก 1 endpoint, A/B เทียบคุณภาพ+cost, ค่อยๆ ย้าย
