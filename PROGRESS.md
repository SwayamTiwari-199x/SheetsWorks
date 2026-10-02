# PROGRESS

CURRENT STAGE: 1 (Scaffold, schema, storage)

## Done
- Stage 0 (accepted): `RULES.md` + `rules.json` written (~40 distinct source URLs cited; rules.json parses). Post-acceptance fixes: layout_rule clarity on apostrophe-year dates, bullet word min aligned at 15, §0 AI-detector line reworded to "rarely, per limited evidence", SPEC.md now has per-version `include_personal_details` toggle and verified-blocks/unverified-warns validator rule.

## Notes / decisions
- rules.json is a summary of RULES.md; RULES.md is prose-of-truth with sources. App code reads rules.json.
- REC: treat photo/DOB/gender/marital/father's-name as omit-by-default (even in India) — legacy biodata fields noted but not endorsed.
- AI-detection stance per SPEC §2/§10: no detector-evasion features; defense is user's own facts + human review (TopResume 2025 survey: 19.6% reject AI resumes outright).
- Market snapshot dated 2026-10-02 — needs `refresh_market_data` every ~3 months.

## Known issues
(none yet)
