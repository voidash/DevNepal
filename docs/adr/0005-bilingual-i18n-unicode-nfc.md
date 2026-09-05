# ADR 0005: Bilingual i18n (en + ne) with Unicode NFC normalization

Date: 2026-09-03
Status: Accepted

## Context

NFR-I18N-01 (Must) requires the interface to support English and Nepali with Unicode
storage/search, language switching, locale-aware dates, and translation fallback without
broken layouts. §14.3 requires all platform-owned interface text, validation, and core
policies in both languages at launch, and government project title/summary in both
languages (Appendix A). DSC-003 (Must) requires search and URLs to support Nepali
Unicode with stable, human-readable slugs. MEM-002 records a member's preferred language.

Devanagari text arrives from macOS (NFD-prone), Windows, and Android (NFC) keyboards in
mixed normalization forms. Two strings that render identically ("नेपाली") can differ
byte-wise, silently breaking `icontains` search equality, unique constraints, and slug
matching — this is a hard correctness issue for DSC-003, not a cosmetic one. For fonts,
Devanagari needs a script-aware family (Noto Sans Devanagari) while the design system's
Latin grotesque is Inter (ADR 0007); §14.3 requires low-bandwidth behavior, so fonts must
be efficient to serve.

## Decision

- `LANGUAGES = ["en", "नेपाली (ne)"]` with `LocaleMiddleware`; `LANGUAGE_CODE = "en"`;
  Nepali translations live in `locale/ne/LC_MESSAGES/django.po`, regenerated with
  `makemessages -l ne` whenever templates change. Every user-facing string goes through
  `gettext`/`{% trans %}` — no hardcoded UI text anywhere.
- Locale-aware dates render in `Asia/Kathmandu` with UTC storage (`USE_TZ = True`).
- **NFC normalization at the save boundary**: all user-entered text that becomes
  searchable, uniquely constrained, or slug-relevant is normalized with
  `unicodedata.normalize("NFC", value)` before persistence (model save/clean helpers).
  Slugs are generated from NFC text so URLs stay stable; search operates on NFC columns,
  and query input is normalized the same way before comparison.
- Fonts: Noto Sans Devanagari (Devanagari + fallback for ne) paired with Inter (Latin),
  served as subset webfonts with `font-display: swap`.

## Consequences

Positive: Nepali and English search behave identically regardless of the user's platform
(DSC-003, A4); slugs and uniqueness are byte-stable; the bilingual content model of §14.3
is mechanical (parallel fields for title/summary, single gettext source for UI).

Negative/risk: normalization must be applied consistently — a single un-normalized write
path reintroduces the bug, so tests cite DSC-003 at every searchable/slug field; any
future bulk import (external article import, BLG-005) must normalize too. Subsetting and
self-hosting two font families adds a small build step; both are open (OFL-licensed)
fonts, keeping §12.4 rights simple.

Relevant SRS: §14.3, Appendix A, DSC-003, NFR-I18N-01, MEM-002, A4, A8.
