# ADR 0007: Swiss International design system, adapted for DevNepal

Date: 2026-09-03
Status: Accepted

## Context

`docs/design/swiss-international-prompt.md` defines the visual language: objective
communication, the grid as law, grotesque sans-serif typography as structure, active
negative space, flat pattern-based texture instead of shadows, and a single functional
accent color ("Swiss Red" #FF3000) reserved for CTAs, focus, and critical emphasis —
never decoration. The prompt prescribes Tailwind-class ergonomics, `lucide-react` icons,
and UPPERCASE headings.

DevNepal constraints differ from the prompt's defaults: WCAG 2.2 Level AA is a Must
(NFR-A11Y-01; §14.2 adds: never color alone, ≥44px targets, reduced-motion support);
the UI is bilingual with Devanagari (NFR-I18N-01), which is a caseless script —
UPPERCASE styling cannot apply to Nepali text; §14.3 demands low-bandwidth behavior
(no heavy CSS/JS payloads); and the stack decision is server-rendered Django templates
with no JS framework (ADR 0001, §5.1 — a responsive web app, no native mobile, §5.2).
Finally, this is the Government of Nepal's platform: a Swiss-movement red reads better
here as Nepal's flag crimson.

Notably, #FF3000 on white measures ≈3.7:1 contrast — failing WCAG AA for normal text —
while crimson #DC143C on white measures ≈5.0:1, passing AA for all text sizes. The
adaptation is an accessibility improvement, not just branding.

## Decision

Adopt the Swiss International system with these binding adaptations:

- **Accent**: Nepal flag crimson `#DC143C` replaces `#FF3000` everywhere, keeping its
  Swiss role as the *only* signal color — CTAs, focus rings, hover inversion, section
  numbers — never decorative fill. The rest of the strict palette stands: white
  background, black foreground/borders, `#F2F2F2` muted surfaces, 0px radii, thick
  visible borders.
- **Typography**: Inter (Latin) paired with Noto Sans Devanagari (Nepali) at matching
  weights 400–900 (ADR 0005). Uppercase/tracking treatments apply to Latin only; Nepali
  hierarchy uses weight and scale. Massive-type compositions must be re-checked for
  Devanagari line-height and word-breaking.
- **Implementation**: server-rendered Django templates in `templates/` plus design tokens
  and patterns as CSS custom properties / classes in `static/src/`. No JS framework, no
  Tailwind runtime, no icon package dependency — the prompt's `lucide-react` icons are
  inlined as SVG symbols; textures are pure CSS (grid/dots/diagonal/noise).
- **Accessibility rules override aesthetics**: color never carries meaning alone (§14.2);
  interactive targets ≥44×44px; visible focus in crimson; all motion `prefers-reduced-
  motion`-safe; contrast verified per component against WCAG 2.2 AA before acceptance
  (§16.2 audit, A8).
- **Progressive enhancement only**: pages fully usable without JavaScript (§14.3
  low-bandwidth, NFR-PERF-01); JS, if any, decorates server-rendered output.

## Consequences

Positive: a distinctive, national-identity-consistent, low-bandwidth, framework-free UI
that is testable as HTML/CSS; crimson fixes the prompt's own AA gap on accent text.

Negative/risk: Devanagari breaks the prompt's uppercase assumption and its massive-type
rhythm — bilingual layouts need per-locale QA (§14.3); self-hosted subset fonts add a
build step; the design prompt remains the reference for composition, but wherever it
conflicts with WCAG or the no-framework decision, this ADR wins.

Relevant SRS: §5.1, §5.2, §14.1–14.3, NFR-A11Y-01, NFR-I18N-01, NFR-PERF-01, A8.
