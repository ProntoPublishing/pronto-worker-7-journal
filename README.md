# Pronto Worker 7 — Journal/Planner Builder (Low-Content)

Airtable Book Metadata → `interior.pdf` + `journal_manifest.json`.
No manuscript, no W1, no text pipeline anywhere. Spec:
`W7_Journal_WorkOrder_v0` rev B (FROZEN 2026-07-18).

The first zero-dependency worker: JOURNAL → COVER (E1 no-manuscript
mode) → KDPPREP (E5 low-content checklist), all existing machinery —
W7 writes `Interior Page Count` = TOTAL exactly as W2 ≥1.7.1 does.

## The central rule (rev B)

ALL KDP math runs on **TOTAL printed pages**, never the
customer-facing body count. TOTAL = body + 4 pinned front-matter
pages (half-title recto / blank verso / title recto / © verso; body
opens recto on page 5). Bounds 24–828 TOTAL → body 20–824. The
gutter bracket is selected by TOTAL — the named boundary trap: body
150 → total 154 → 0.5″ bracket, where a body-count lookup would
manufacture a violation.

## Templates

Lined (5/16″ pitch, header rule) · Dot Grid (5 mm, centered) ·
Blank · Prompted (one prompt/page, house serif, overflow → hold).
Pure geometry functions, full float precision, mirrored gutter-aware
margins derived from (trim, TOTAL). Deterministic PDF: ReportLab
invariant=1, vendored Lora statics (OFL), grayscale ink only.

## Tripwires (R7)

- **W7-001** template missing/unrecognized → FAIL
- **W7-002** TOTAL out of bounds → hold (note shows body AND total)
- **W7-003** prompts missing/short/overflow → hold
- **W7-004** page size/count self-check → FAIL

## Test

```
bash test.sh
```

---
Pronto Publishing
