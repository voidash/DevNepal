# DevNepal Design System — Implementation Spec

> **SUPERSEDED (coordinator ruling, 2026-09-05).** Design authority has moved to the
> Primer-based design system at `/Users/cdjk/github/llm/cad/devnepal-design-system/`
> (`DEVNEPAL_DESIGN_PROMPT.txt`, `src/devnepal.css`, `index.html`). That repository now
> governs all template/UI work (`templates/**`, `static/src/**`). This document is kept
> below as historical reference for the Swiss International spec it once defined
> bindingly; nothing in it is normative anymore.

---

## 1. Design principles (Swiss International, adapted)

1. **Objectivity over subjectivity.** The design recedes; content (projects, contributions, recognition) speaks. No decoration that content cannot justify.
2. **The grid is law.** 12-column grid, visible structure via 2 px / 4 px black borders, asymmetric column ratios (8:4, 7:5, 5:7, 9:3) on desktop. No centered text blocks.
3. **Typography is the interface.** Inter (Latin) + Noto Sans Devanagari (Nepali). Hierarchy is created by scale, weight, and position only.
4. **Active negative space.** Whitespace is structure. Narrative sections get `--space-32`+ (128 px) breathing room; data clusters (tables, dashboards) are dense.
5. **Flat, layered by pattern, not shadow.** No shadows, no gradients, no rounded corners. Depth comes only from the subtle background patterns in §5.4.
6. **Inclusive by design** (SRS §2.3): bilingual EN/NE, mobile-first, low-bandwidth tolerant, WCAG 2.2 AA. Every rule below exists to satisfy this.
7. **Crimson is a signal, never a fill.** Nepal crimson `#DC143C` is used ONLY for: primary CTAs, hover inversions, section number prefixes, and official-government indicators (GOV-011 badge). Nothing else. Ever.

---

## 2. Color tokens

### 2.1 Core palette

| Token | Hex | Role |
|---|---|---|
| `--color-bg` | `#FFFFFF` | Page canvas. The only large-fill background besides `--color-fg` inversions. |
| `--color-fg` | `#000000` | All primary text, borders, inverted surfaces. 21.00:1 on white. |
| `--color-bg-muted` | `#F2F2F2` | Secondary surfaces: card header strips, table zebra, sidebar panels. |
| `--color-bg-subtle` | `#E5E5E5` | Hover state on muted surfaces, pressed rows. |
| `--color-text-secondary` | `#595959` | Secondary/metadata text. 7.00:1 on white, 6.26:1 on `#F2F2F2`. |
| `--color-accent` | `#DC143C` | Nepal crimson. Restricted use — see §2.4. |
| `--color-border` | `#000000` | Structural borders (2 px / 4 px). |
| `--color-rule` | `#8C8C8C` | Hairline separators inside data tables only. 3.36:1 on white (passes WCAG 1.4.11 non-text 3:1). |

Greys darker than `#595959` are forbidden for text (e.g. `#767676` passes at 4.54:1 but leaves zero margin — do not use; `#B3B3B3` at 2.10:1 is decorative only, never text or component boundaries).

### 2.2 Status colors (SRS §6.1 lifecycle)

Status colors are the only additional hues in the system. They reinforce status; they never *are* the status. Every status badge carries a distinct glyph shape + localized text label (§7.4), satisfying SRS §14.2 "no color alone".

| Lifecycle state | Token | Hex | Contrast on `#FFFFFF` | Contrast on `#F2F2F2` | Glyph |
|---|---|---|---|---|---|
| Draft | `--status-draft` | `#595959` | 7.00:1 | 6.26:1 | hollow square |
| In review | `--status-review` | `#8A5A00` | 5.93:1 | 5.29:1 | half-filled square |
| Changes requested | `--status-changes` | `#9A3412` | 7.31:1 | 6.53:1 | exclamation square |
| Approved / scheduled | `--status-approved` | `#1D4ED8` | 6.70:1 | 5.99:1 | square with clock |
| Open for contribution | `--status-open` | `#1E6F30` | 6.23:1 | 5.56:1 | filled square with plus |
| Paused | `--status-paused` | `#92400E` | 7.09:1 | 6.33:1 | two vertical pause bars |
| Completed | `--status-completed` | `#0F766E` | 5.47:1 | 4.89:1 | filled square with check |
| Cancelled | `--status-cancelled` | `#991B1B` | 8.31:1 | 7.4:1 | square with diagonal cross |
| Archived | `--status-archived` | `#595959` | 7.00:1 | 6.26:1 | filled grey square |

All values ≥ 4.5:1 on both permitted chip surfaces, so status chips may sit on white or muted panels. Cancelled deliberately uses dark red `#991B1B`, NOT crimson — crimson is reserved by §2.4.

### 2.3 Form error and success

| Token | Hex | Use | Contrast on white |
|---|---|---|---|
| `--color-error` | `#9A3412` | Field-level error text, error summary, `aria-invalid` message icon | 7.31:1 |
| `--color-success` | `#1E6F30` | Inline confirmation text (with check glyph + text) | 6.23:1 |

Form errors must NOT use crimson. Crimson is brand/CTA signal, not validation signal. Errors are communicated by text + glyph + programmatic association (§7.8), never color alone.

### 2.4 Crimson usage rules (the four permitted uses)

WCAG 1.4.3 verified values:

| Combination | Ratio | Verdict |
|---|---|---|
| `#DC143C` text on `#FFFFFF` | 4.99:1 | **Passes AA normal text** (all sizes) |
| `#FFFFFF` text on `#DC143C` fill | 4.99:1 | **Passes AA normal text** (all sizes) |
| `#DC143C` text on `#F2F2F2` | 4.46:1 | **FAILS normal text.** Large text only: ≥ 24 px, or ≥ 18.66 px bold (700+) |
| `#DC143C` text on `#000000` | 4.21:1 | **FAILS normal text.** Large text (≥ 24 px / 18.66 px bold) and non-text accents (≥ 3:1) only |

House rules:

1. **Primary CTA**: solid crimson fill, white text, uppercase, weight 700, size ≥ 14 px, min height 48 px (56 px mobile). Hover: invert to black fill / white text (a permitted "hover inversion").
2. **Crimson text on white**: allowed at any size by math, but reserved for section number prefixes (`01.`, `02.` — ≥ 20 px, weight 700) and body-weight links inside text blocks. Do not use crimson for headings, labels, or body copy.
3. **Crimson text on `#F2F2F2` or `#000000`**: forbidden below large-text sizes. On muted panels, use the black-on-white pattern instead.
4. **Official-government indicator (GOV-011)**: the OFFICIAL badge is crimson fill + white text (§7.3). It appears ONLY on Super Admin-approved ministry projects. Never decorative crimson strips, rules, banners, or backgrounds.

### 2.5 Forbidden colors

- `#FF3000` (raw prompt's Swiss red) — retired, fails contrast (3.70:1 on white).
- Any gradient, any shadow color, any color not in §2.1–§2.3.
- Color overlays on photography; photos stay grayscale or unfiltered.

---

## 3. Typography

### 3.1 Font stacks

```css
:root {
  --font-latin: "Inter", "Noto Sans Devanagari", system-ui, -apple-system,
    "Segoe UI", sans-serif;
  --font-nepali: "Noto Sans Devanagari", "Inter", system-ui, sans-serif;
}
html { font-family: var(--font-latin); }
[lang="ne"] { font-family: var(--font-nepali); }
```

- Inter has no Devanagari glyphs; browsers fall back per-codepoint to Noto Sans Devanagari, so mixed-script paragraphs work with either stack. Blocks whose `lang="ne"` get the Nepali-first stack so Devanagari shaping and metrics come from Noto.
- AGENTS.md convention is binding: Devanagari webfont is Noto Sans Devanagari; Latin is Inter. No other families.

### 3.2 Weights

| Weight | Inter | Noto Sans Devanagari | Use |
|---|---|---|---|
| 400 | load | load | Body, table cells |
| 700 | load | load | Headings, labels, buttons, nav |
| 900 | home/hero only, async | — | Hero display, giant stat numerals |

Do not load Inter 500 (bandwidth, NFR-PERF-01). Emphasis in body text uses 700, not italics.

### 3.3 Type scale (rem ramp, 1 px = 0.0625 rem)

Base: `html { font-size: 100% }` — never set body font-size in px; user zoom must scale everything (WCAG 1.4.4).

| Token | Size | EN line-height | NE line-height | Use |
|---|---|---|---|---|
| `--fs-xs` | 0.75 rem (12 px) | 1.5 | 1.8 | Table headers, badges, fine print |
| `--fs-sm` | 0.875 rem (14 px) | 1.5 | 1.8 | Labels, meta, secondary text, buttons |
| `--fs-base` | 1 rem (16 px) | 1.5 | 1.8 | Body default |
| `--fs-md` | 1.125 rem (18 px) | 1.55 | 1.8 | Lead paragraphs, form labels |
| `--fs-lg` | 1.25 rem (20 px) | 1.4 | 1.7 | Card titles, h4 |
| `--fs-xl` | 1.5 rem (24 px) | 1.3 | 1.6 | h3 |
| `--fs-2xl` | 1.75 rem (28 px) | 1.25 | 1.55 | Sub-section h3 (page level) |
| `--fs-3xl` | 2 rem (32 px) | 1.2 | 1.5 | h2 |
| `--fs-4xl` | 2.5 rem (40 px) | 1.15 | 1.45 | Page h1 (mobile), h2 (home) |
| `--fs-5xl` | 3 rem (48 px) | 1.1 | 1.4 | h1 desktop |
| `--fs-6xl` | 3.5 rem (56 px) | 1.05 | 1.35 | Hero mobile |
| `--fs-7xl` | 4.5 rem (72 px) | 1.0 | 1.3 | Hero desktop, stat numerals |
| `--fs-8xl` | 6 rem (96 px) | 1.0 | 1.3 | Home hero desktop (max) |

Hero uses fluid sizing: `font-size: clamp(2.75rem, 9vw, 6rem);` — never fixed `10 rem` from the raw prompt (overflow risk at 320 px, WCAG 1.4.10).

**Nepali line-height rule (binding):** Devanagari matras (ें, ि, ् above/below the x-line) need more vertical room. Every Nepali text block uses the NE line-height column — minimum 1.6 for body, minimum 1.3 for display. Implemented globally:

```css
[lang="ne"] p, [lang="ne"] li, [lang="ne"] dd, [lang="ne"] dt { line-height: 1.8; }
[lang="ne"] h1, [lang="ne"] h2, [lang="ne"] h3 { line-height: 1.4; }
```

For small Nepali text (12–14 px utility classes), apply `font-size: 1.0625em` so matras stay legible.

### 3.4 Case and tracking

- **Uppercase** (`text-transform: uppercase`) applies to EN headings, labels, buttons, table headers, badges. It is a no-op on Devanagari — acceptable; never fake small-caps for Nepali.
- **Letter-spacing**: EN labels/badges `0.08em`; EN display ≥ 40 px may use `-0.02em`. **Devanagari letter-spacing is always `0`** — tracking breaks the shirorekha (headline stroke) and conjunct rendering:

```css
[lang="ne"] * { letter-spacing: 0 !important; }
```

### 3.5 Mixed-script paragraphs

- Inline Nepali inside an EN page (and vice versa) is wrapped: `<span lang="ne">…नेपाली…</span>` — required for screen-reader pronunciation (WCAG 1.3.1) and correct font fallback.
- Line-height is inherited from the block's `lang`, not the span.
- Numbers/dates inside a Nepali string use the locale-appropriate digits carried by the translated string (Devanagari digits ०१२३ in NE strings, Latin 0123 in EN).
- Never mix scripts inside a single word or button label. Bilingual labels are two elements (one per `lang`).

### 3.6 Font loading (NFR-PERF-01, SRS §14.3)

- **Self-hosted** woff2 only. No Google Fonts / third-party font CDN (extra DNS+TLS on Nepal 4G kills LCP).
- Subsets via `unicode-range`: Inter `latin` subset; Noto Sans Devanagari `devanagari` subset. Expected payload: Inter ≈ 40 KB/weight, Noto Devanagari ≈ 60 KB/weight.
- `<link rel="preload" as="font">` for exactly the first-pair body weights the current locale needs: EN pages preload Inter 400 + 700 latin; NE pages preload Noto Sans Devanagari 400 + 700. Inter 900 loads async (home hero only).
- `font-display: swap` on every `@font-face`. Define a metrics-matched local fallback (`size-adjust`, `ascent-override`) so swap does not shift layout (CLS).
- Total font budget per page: ≤ 150 KB woff2 over the wire.
- Pages must be fully usable with fonts not yet loaded or images disabled (SRS §14.3): system-ui fallback stack renders all content; no FOIT-only text, no icon fonts (icons are inline SVG, §8).

---

## 4. Grid and spacing

### 4.1 Base unit and spacing scale

Base unit 4 px. Scale (rem equivalents at 16 px):

| Token | px | rem |
|---|---|---|
| `--space-1` | 4 | 0.25 |
| `--space-2` | 8 | 0.5 |
| `--space-3` | 12 | 0.75 |
| `--space-4` | 16 | 1 |
| `--space-6` | 24 | 1.5 |
| `--space-8` | 32 | 2 |
| `--space-12` | 48 | 3 |
| `--space-16` | 64 | 4 |
| `--space-24` | 96 | 6 |
| `--space-32` | 128 | 8 |

No off-scale values (no 10 px, 20 px, 30 px margins). Component padding uses the scale; cards use `--space-6` (24 px) mobile / `--space-8` (32 px) desktop; narrative sections use `--space-12`–`--space-32`.

### 4.2 Grid

- **12 columns**, max container width 1440 px, centered.
- Gutters: 24 px (mobile/tablet), 24 px desktop; container side padding 24 px < 768 px, 32 px ≥ 768 px.
- Breakpoints: `sm` 640 px, `md` 768 px, `lg` 1024 px, `xl` 1280 px, `2xl` 1536 px.
- Desktop asymmetric ratios (from the Swiss prompt, kept): **8:4, 7:5, 5:7, 9:3** — e.g. main content 8 / sidebar 4 on project list; 5:7 on project detail (meta rail left, description right); 9:3 for dashboard tables.
- Tablet: two equal or 7:5 columns; mobile: single column, vertical stacking, order preserved.

### 4.3 Borders and radius

| Border | Use |
|---|---|
| 4 px solid `#000000` | Section-defining: header bottom edge, footer top edge, hero frame, dashboard panel frames |
| 2 px solid `#000000` | Cards, badges, inputs, buttons, filter groups, image frames, column dividers |
| 1 px solid `#8C8C8C` | Inside data tables only (row separators) |

- Border thickness never thins at mobile (raw prompt rule, kept).
- `border-radius: 0` everywhere. No exceptions.

### 4.4 Background patterns (flat depth, no shadows)

Exact recipes from the Swiss prompt, kept as the only "texture":

| Class | Recipe | Where allowed |
|---|---|---|
| `.pattern-grid` | 24×24 px black lines at 3% opacity (`repeating-linear-gradient`) | Hero composition areas, muted sidebars |
| `.pattern-dots` | 16×16 px dot matrix at 4% opacity (`radial-gradient`) | Section headers (behind label, not text) |
| `.pattern-diagonal` | 45° lines, 10 px spacing, 2% opacity | Accordion/FAQ panels, benefit strips |
| `.pattern-noise` | SVG fractal noise at 1.5% opacity | Body background, once |

Rules: never on pure black or crimson fills; never directly behind body text (place text on a solid white/black panel); decorative only — they carry no information; disabled entirely under `prefers-contrast: more` (§7.7) and inert under forced-colors mode.

---

## 5. — (reserved: see §7 components)

---

## 6. — (reserved: see §7 components)

---

## 7. Components (HTML/CSS contracts, no JS framework)

All interactive behavior must work without JavaScript (SRS §14.3: critical actions never depend on JS/hover/animation). JS may only enhance. Every user-visible string goes through `{% trans %}` / `gettext` (AGENTS rule 5); class names and structure below are the contract.

### 7.1 Site header

Black bottom border 4 px; white background; sticky on desktop with `scroll-padding-top: calc(header height + 8px)` on `html` so focus/anchors are never obscured (WCAG 2.4.11).

```html
<a class="skip-link" href="#main">{% trans "Skip to main content" %}</a>
<header class="site-header">
  <div class="site-header__inner">
    <a class="brand" href="/">
      <svg class="brand__mark" aria-hidden="true" focusable="false">…</svg>
      <span class="brand__name">DevNepal</span>
    </a>
    <nav class="site-nav" aria-label="{% trans 'Primary' %}">
      <ul class="site-nav__list">
        <li><a href="/projects/gov/" aria-current="page">{% trans "Government Projects" %}</a></li>
        <li><a href="/projects/community/">{% trans "Community Projects" %}</a></li>
        <li><a href="/members/">{% trans "Members" %}</a></li>
        <li><a href="/blogs/">{% trans "Tech Blogs" %}</a></li>
        <li><a href="/leaderboard/">{% trans "Leaderboard" %}</a></li>
        <li><a href="/about/">{% trans "About" %}</a></li>
      </ul>
    </nav>
    <div class="site-header__actions">
      <nav class="lang-switch" aria-label="{% trans 'Language' %}">
        <a href="/en/…" lang="en" hreflang="en" aria-current="true">EN</a>
        <span aria-hidden="true">|</span>
        <a href="/ne/…" lang="ne" hreflang="ne">नेपाली</a>
      </nav>
      <a class="btn btn--secondary" href="/accounts/login/">{% trans "Sign in" %}</a>
    </div>
  </div>
</header>
```

Contract:
- Nav areas match SRS §14.1; `Dashboard` link appears for authenticated users.
- Language switcher: plain links to locale-prefixed URLs (`/en/…`, `/ne/…`); active locale gets `aria-current="true"`; each link carries its own `lang` + `hreflang`. No JS, no cookies required.
- Every nav/link target ≥ 44×44 px hit area (min-height + padding).
- Mobile: nav collapses into a `<details class="mobile-nav"><summary>Menu</summary> …</details>` block (native, keyboard-operable, no JS). Summary is 56 px tall with 2 px black border.
- Hover (pointer devices only, `@media (hover: hover)`): link underline snaps in (2 px black); no slide/rotate animations on nav.

### 7.2 Footer

Black fill, white text (21:1), 4 px black top border, four columns ≥ 1024 px / two columns tablet / stacked mobile. Contains, in order: platform navigation (§14.1 areas), policies (privacy, terms, security contact, code of conduct), help/support (consistent location on every page — WCAG 3.2.6), and the government notice + contact block.

```html
<footer class="site-footer">
  <div class="site-footer__grid">
    <nav aria-label="{% trans 'Footer' %}">
      <h2 class="site-footer__heading">{% trans "Platform" %}</h2>
      <ul>…</ul>
    </nav>
    <nav aria-label="{% trans 'Policies' %}"> … </nav>
    <div class="site-footer__help">
      <h2 class="site-footer__heading">{% trans "Help" %}</h2>
      <ul>…</ul>
    </div>
    <div class="site-footer__gov">
      <h2 class="site-footer__heading">{% trans "Official platform" %}</h2>
      <p>{% trans "A Government of Nepal public collaboration platform." %}</p>
      <p lang="ne">{% trans "नेपाल सरकारको सार्वजनिक सहयोग मञ्च।" %}</p>
    </div>
  </div>
  <p class="site-footer__legal">© {% now "Y" %} DevNepal · {% trans "All content available in English and Nepali" %}</p>
</footer>
```

White links on black get 2 px white underline on hover/focus. No crimson in the footer.

### 7.3 Project card — government variant (GOV-011)

2 px black border, white fill, 24–32 px padding, no shadow, no radius. The OFFICIAL badge is the only crimson element.

```html
<article class="card card--gov">
  <header class="card__head">
    <p class="badge badge--official">
      <svg aria-hidden="true" focusable="false">…shield/square glyph…</svg>
      {% trans "Official government project" %}
    </p>
    <p class="card__owner">{% trans "Ministry of Education, Science and Technology" %}</p>
  </header>
  <h3 class="card__title"><a href="{{ project.get_absolute_url }}" class="card__title-link">{{ project.title_en }}</a></h3>
  <p class="card__title-ne" lang="ne">{{ project.title_ne }}</p>
  <p class="card__summary">{{ project.summary }}</p>
  <dl class="card__meta">
    <div><dt>{% trans "Status" %}</dt><dd>{% include "components/status_badge.html" %}</dd></div>
    <div><dt>{% trans "Contribution type" %}</dt><dd>{{ project.get_contribution_type_display }}</dd></div>
    <div><dt>{% trans "Deadline" %}</dt><dd><time datetime="{{ project.deadline|date:'c' }}">{{ project.deadline|localized_date }}</time></dd></div>
  </dl>
</article>
```

`.badge--official`: crimson `#DC143C` fill, white text 12 px / 700 / uppercase / `0.08em` tracking, 2 px black border, 8×16 px padding. Rendered **only** when the project is a Super Admin-approved ministry publication (GOV-011, Must). If the template cannot prove approval, the badge does not render — never a greyed-out or faked variant.

Bilingual titles: government projects require title + summary in both languages (SRS §14.3); the card shows EN title as the link and the NE title as a secondary line with `lang="ne"`.

Hover (hover-capable devices): whole card inverts to black fill, text to white, badge stays crimson (white-on-crimson 4.99:1 holds). Instant color change only, no transition transforms. Under `prefers-reduced-motion: reduce`, the inversion still applies (it is not motion) but with no transition duration.

### 7.4 Project card — community variant

Identical structure, three differences: header strip is `#F2F2F2` instead of white; the badge is `.badge--community` (white fill, 2 px black border, black text: "Community project"); owner is the member handle, not a ministry. No crimson anywhere on this card. This is the visual separation SRS §14.1 requires ("clearly separated from official projects").

### 7.5 Status badge

```html
<span class="status status--open">
  <svg class="status__glyph" aria-hidden="true" focusable="false">…filled square with plus…</svg>
  <span class="status__label">{% trans "Open for contribution" %}</span>
</span>
```

```css
.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--color-bg);
  border: 2px solid var(--color-border);
  font-size: var(--fs-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 4px 8px;
  min-height: 28px;
}
.status--open    { color: var(--status-open); }
.status__glyph   { width: 12px; height: 12px; }
[lang="ne"] .status { letter-spacing: 0; text-transform: none; }
```

Contract (SRS §14.2, "never color alone"):
- The glyph shape differs per state (§2.2 table) AND the localized text label is always present. Color is the third channel only.
- Modifier classes: `status--draft`, `status--review`, `status--changes`, `status--approved`, `status--open`, `status--paused`, `status--completed`, `status--cancelled`, `status--archived`.
- Nepali labels use the same lifecycle strings from `django.po` (e.g. "योगदानका लागि खुला").
- Chips render on white or `#F2F2F2` only (all pairs verified ≥ 4.5:1); never on black.

### 7.6 Filter / search bar (Government Projects list)

No-JS GET form; each control has a programmatic label; the results count is a polite live region.

```html
<form class="filterbar" method="get" role="search" action="{% url 'projects:gov-list' %}">
  <div class="filterbar__query">
    <label for="id_q">{% trans "Search projects" %}</label>
    <input type="search" id="id_q" name="q" value="{{ request.GET.q }}"
           placeholder="{% trans 'Keyword, ministry, or technology' %}"
           autocomplete="off">
  </div>
  <fieldset class="filterbar__group">
    <legend>{% trans "Status" %}</legend>
    <ul>
      <li><label><input type="checkbox" name="status" value="open"> {% trans "Open for contribution" %}</label></li>
      <li><label><input type="checkbox" name="status" value="paused"> {% trans "Paused" %}</label></li>
    </ul>
  </fieldset>
  <fieldset class="filterbar__group">
    <legend>{% trans "Contribution type" %}</legend>
    <select name="type" id="id_type"> … </select>
  </fieldset>
  <button type="submit" class="btn btn--primary">{% trans "Apply filters" %}</button>
  <a class="filterbar__reset" href="{% url 'projects:gov-list' %}">{% trans "Reset" %}</a>
</form>
<p class="filterbar__count" role="status">
  {% blocktranslate count counter=page_obj.paginator.count %}{{ counter }} project{% plural %}{{ counter }} projects{% endblocktranslate %}
</p>
```

Contract: inputs 2 px black border, 48 px min height; checkboxes 24×24 px with 44 px hit area via label padding; the search field matches Devanagari and Latin input identically (backend concern, but the field must never strip or transliterate — SRS §14.3); `role="status"` count announces updates (WCAG 4.1.3).

### 7.7 Stat block (home, dashboards, leaderboard)

```html
<div class="stat">
  <p class="stat__value">1,248</p>
  <p class="stat__label">{% trans "Verified contributions" %}</p>
  <p class="stat__trend">
    <svg aria-hidden="true">…up triangle…</svg>
    <span>+12% {% trans "this month" %}</span>
  </p>
</div>
```

```css
.stat {
  border: 2px solid var(--color-border);
  padding: var(--space-6);
  background: var(--color-bg);
}
.stat__value {
  font-size: clamp(2rem, 5vw, 4.5rem);
  font-weight: 900;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
[lang="ne"] .stat__value { line-height: 1.3; font-weight: 700; }
.stat__label {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-top: var(--space-2);
}
.stat__trend { color: var(--status-open); font-size: var(--fs-sm); }
```

Contract: trend direction is carried by glyph + sign + words ("+12% this month"), never by color alone (SRS §14.2 explicitly covers leaderboards/heatmaps); grids 4-up ≥ 1024 px, 2×2 tablet/mobile; numerals use tabular figures; Nepali numerals use Noto Devanagari 700 (no 900 cut — never synthesize bold).

### 7.8 Data table (dashboards, member lists, applications)

```html
<div class="table-scroll" tabindex="0" role="region" aria-label="{% trans 'Applications' %}">
  <table class="data-table">
    <caption class="visually-hidden">{% trans "Applications to your projects" %}</caption>
    <thead>
      <tr>
        <th scope="col">{% trans "Project" %}</th>
        <th scope="col">{% trans "Applicant" %}</th>
        <th scope="col">{% trans "Status" %}</th>
        <th scope="col" class="data-table__num">{% trans "Applied" %}</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <th scope="row"><a href="…">{{ application.project.title }}</a></th>
        <td>{{ application.member.username }}</td>
        <td>{% include "components/status_badge.html" %}</td>
        <td class="data-table__num"><time datetime="{{ application.created_at|date:'c' }}">{{ application.created_at|localized_date }}</time></td>
      </tr>
    </tbody>
  </table>
</div>
```

```css
.table-scroll { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.data-table thead th {
  border-top: 2px solid var(--color-border);
  border-bottom: 2px solid var(--color-border);
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  text-align: left;
  padding: var(--space-3) var(--space-4);
}
.data-table tbody th { font-weight: 700; text-align: left; }
.data-table td, .data-table tbody th { border-bottom: 1px solid var(--color-rule); padding: var(--space-3) var(--space-4); }
.data-table tbody tr:nth-child(even) { background: var(--color-bg-muted); }
.data-table__num { text-align: right; font-variant-numeric: tabular-nums; }
[lang="ne"] .data-table thead th { letter-spacing: 0; text-transform: none; }
```

Contract: sortable headers (when used) are `<button>` inside `th` with `aria-sort` on the `th`; the scroll wrapper gets `tabindex="0"` + `role="region"` + label so keyboard users can scroll horizontally (WCAG 1.4.10 / 2.1.1); zebra + row rules are redundant cues — row meaning never depends on them.

### 7.9 Form field pattern (bilingual labels, WCAG error recovery)

```html
<form method="post" novalidate>
  <fieldset class="field-group">
    <legend>{% trans "Project title (both languages required)" %}</legend>
    <div class="field">
      <label for="id_title_en" lang="en">{% trans "Title (English)" %}</label>
      <input type="text" id="id_title_en" name="title_en" required
             aria-required="true" aria-describedby="id_title_en_help"
             {% if form.title_en.errors %}aria-invalid="true"{% endif %}>
      <p id="id_title_en_help" class="field__help">{% trans "Public name shown in listings." %}</p>
      {% if form.title_en.errors %}
        <p class="field__error" id="id_title_en_error">
          <svg aria-hidden="true">…exclamation square…</svg>
          {{ form.title_en.errors.0 }}
        </p>
      {% endif %}
    </div>
    <div class="field">
      <label for="id_title_ne" lang="ne">{% trans "शीर्षक (नेपाली)" %}</label>
      <input type="text" id="id_title_ne" name="title_ne" lang="ne" required
             aria-required="true"
             {% if form.title_ne.errors %}aria-invalid="true"{% endif %}>
      …
    </div>
  </fieldset>
  <button type="submit" class="btn btn--primary">{% trans "Submit for review" %}</button>
</form>
```

```css
.field { display: grid; gap: var(--space-2); margin-bottom: var(--space-6); }
.field label { font-size: var(--fs-md); font-weight: 700; }
.field input, .field select, .field textarea {
  border: 2px solid var(--color-border);
  border-radius: 0;
  background: var(--color-bg);
  min-height: 48px;
  padding: var(--space-2) var(--space-3);
  font-size: var(--fs-base);
  font-family: inherit;
}
.field__help { color: var(--color-text-secondary); font-size: var(--fs-sm); }
.field__error { color: var(--color-error); font-weight: 700; font-size: var(--fs-sm); display: flex; gap: 6px; align-items: start; }
input[aria-invalid="true"] { border-color: var(--color-error); border-width: 2px; }
```

Contract (WCAG 3.3.1 / 3.3.2 / 3.3.3, SRS §14.2):
- Errors: text + glyph + `aria-invalid` + `aria-describedby` pointing at the error `<p>` id; border color change is a redundant cue only. On submit failure, render an error summary at the top of the form: a 2 px black-bordered panel titled "There is a problem", listing in-page anchor links to each errored field.
- Required is stated in words ("(required)" / "(आवश्यक)"), not by color or bare asterisk.
- Bilingual pairs (gov project title/summary, SRS §14.3) are grouped in a `fieldset` with a `legend`; each sub-field label carries its `lang`.
- Nepali inputs accept mixed NFC/NFD input (DSC-003 normalization is backend; the field never blocks or warns about it).
- Focus: `:focus-visible { outline: 2px solid #000; outline-offset: 2px; }` — no glow, no border-color-only focus.

### 7.10 Pagination

```html
<nav class="pagination" aria-label="{% trans 'Pagination' %}">
  <ul class="pagination__list">
    <li><a href="?page=3" rel="prev">{% trans "Previous" %}</a></li>
    <li><a href="?page=1" aria-label="{% trans 'Page 1' %}">1</a></li>
    <li><a href="?page=2" aria-label="{% trans 'Page 2' %}">2</a></li>
    <li><a href="?page=3" aria-label="{% trans 'Page 3' %}">3</a></li>
    <li><span aria-current="page" class="pagination__current">4</span></li>
    <li><a href="?page=5" rel="next">{% trans "Next" %}</a></li>
  </ul>
</nav>
```

```css
.pagination__list { display: flex; flex-wrap: wrap; gap: var(--space-2); list-style: none; }
.pagination a, .pagination__current {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  min-height: 44px;
  border: 2px solid var(--color-border);
  padding: 0 var(--space-2);
  font-weight: 700;
}
.pagination__current { background: var(--color-fg); color: var(--color-bg); }
.pagination [aria-disabled="true"] { color: var(--color-text-secondary); }
```

Contract: current page is black fill + `aria-current="page"` (state never color-alone); disabled directions render as `aria-disabled` spans; all targets ≥ 44×44 px.

### 7.11 Buttons

| Class | Appearance | Hover (hover-capable only) | Use |
|---|---|---|---|
| `.btn--primary` | `#DC143C` fill, white text, 2 px black border, uppercase 14 px/700, min-height 48 px (56 px mobile, full-width) | invert to black fill | One per view: submit, apply, publish |
| `.btn--secondary` | white fill, 2 px black border, black text | invert to black fill / white text | All non-primary actions |
| `.btn--danger` | black fill, white text, 2 px black border | underline text | Destructive confirm actions (never crimson) |

Buttons never scale/translate on hover; only instant color inversion (raw prompt rule, kept — and it satisfies "no subtle fades"). Minimum padding 12 px 24 px, sized to tolerate +40 % label growth (§8.3).

---

## 8. Bilingual layout rules (NFR-I18N-01, SRS §14.3)

### 8.1 Direction and mirroring

- English and Nepali are both **LTR**. No RTL mirroring is applied for Nepali. Layouts, arrows (→), and progress indicators keep their direction in both locales.
- `html[lang]` is always set server-side (`en` or `ne`); locale-prefixed URLs (`/en/…`, `/ne/…`) are the language switch mechanism (§7.1).

### 8.2 Language switching behavior

- Switching preserves the current path/query (drop only the locale prefix).
- The switcher itself renders both language names endonymically: "EN" and "नेपाली", each with correct `lang`/`hreflang`.
- Locale-aware dates: render in the active locale (Nepali months/digits in NE) via a `localized_date` helper wrapping Asia/Kathmandu formatting (AGENTS time rule); always emit machine-readable `<time datetime="…UTC ISO8601…">`.
- Translation fallback (NFR-I18N-01): if a Nepali string is missing, show the English string — never a broken placeholder; long descriptions that declare a single language (§14.3) display a language tag chip ("English only" / "अङ्ग्रेजी मात्र") on the content block.

### 8.3 Length-swap tolerance (Nepali runs longer)

- Nepali UI strings run up to ~40 % longer than English. Contract: **every button, nav item, badge, and tab must lay out correctly with the label in either locale at +40 % length.**
- No fixed-width buttons; no `white-space: nowrap` on bilingual controls; `min-width` set by the longer locale at build time.
- Buttons wrap to two lines rather than truncating; height grows, border stays 2 px.
- Nav items wrap to a second row on tablet; on mobile they live in the `<details>` menu.
- Never use `text-overflow: ellipsis` on labels, status badges, or nav — allowed only on data-table cells that have a detail view.
- Test every screen in both locales before sign-off; a layout that only works in English is a defect (NFR-I18N-01 "without mixed or broken layouts").

### 8.4 Mixed-layout discipline

- Page chrome (header/footer/nav/buttons) renders entirely in the active locale.
- User-generated bilingual content (project titles/summaries) renders each language in its own element with its own `lang` (§7.3); the secondary language is secondary typographically (smaller, `--color-text-secondary`), never hidden.
- Devanagari never letter-spaced (§3.4); Nepali line-heights per §3.3.

### 8.5 Low-bandwidth rules (SRS §14.3, NFR-PERF-01)

- Font strategy per §3.6 (self-hosted subset woff2, `font-display: swap`, metrics-matched fallback, ≤ 150 KB).
- Pages fully usable with images off: every image has an alt (informative) or `alt=""` (decorative); no information exists only in an image or background pattern.
- Media lazy-loaded (`loading="lazy"`, `decoding="async"`), sized responsively (`width`/`height` attributes to reserve space).
- Critical actions never depend on animation, hover, or drag (§14.3): all controls are anchors/buttons/forms that work keyboard-only and touch-only.
- No web fonts required for first interaction; system-ui fallback is acceptable rendering.

---

## 9. Accessibility rules — WCAG 2.2 AA mapping (NFR-A11Y-01, Must)

### 9.1 Contrast summary (all verified)

| Surface / pair | Ratio | Rule |
|---|---|---|
| Black text / white | 21.00:1 | Default everywhere |
| Black text / `#F2F2F2` | 18.76:1 | Muted panels |
| `#595959` text / white | 7.00:1 | Secondary text |
| Crimson text / white | 4.99:1 | Passes normal text; usage restricted per §2.4 |
| White text / crimson fill | 4.99:1 | Primary CTA, OFFICIAL badge |
| Crimson text / `#F2F2F2` | 4.46:1 | **Fails** — large text only (≥ 24 px, or ≥ 18.66 px bold) |
| Crimson text / black | 4.21:1 | **Fails** — large text / non-text only |
| All status colors / white & `#F2F2F2` | ≥ 4.89:1 | §2.2 table |
| Non-text: black borders, crimson fills | ≥ 3:1 vs adjacent | WCAG 1.4.11 |

**Crimson size/weight rules (the direct answer to "which sizes may use crimson"):**
- White text on crimson fill (CTA, OFFICIAL badge): any size ≥ 12 px, house floor 14 px / 700.
- Crimson text on white: any size by math; house rule limits it to links in running text and section numbers ≥ 20 px / 700.
- Crimson text on grey or black: only ≥ 24 px, or ≥ 18.66 px at weight 700+ (large-text threshold). Below that, use black.
- Large text = ≥ 24 px regular or ≥ 18.66 px (14 pt) bold, per WCAG.

### 9.2 Focus visibility (WCAG 2.4.7, 2.4.11)

```css
:focus-visible { outline: 2px solid #000000; outline-offset: 2px; }
.site-footer :focus-visible, .btn--primary:focus-visible, .card--inverted :focus-visible {
  outline-color: #ffffff;
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transform: none !important;
  }
  .pattern-grid, .pattern-dots, .pattern-diagonal, .pattern-noise { display: none; }
}
@media (prefers-contrast: more) {
  .pattern-grid, .pattern-dots, .pattern-diagonal, .pattern-noise { display: none; }
}
```

- Focus indicator: 2 px solid black outline with 2 px offset. On black/inverted surfaces: 2 px white. On crimson fills: 2 px black (4.21:1 ≥ 3:1 non-text). Never remove outlines; never replace with border-color change alone (raw prompt's red focus ring is replaced — crimson rings can vanish on crimson fills).
- Sticky header must never cover the focused element: `scroll-padding-top` set to header height + 8 px (WCAG 2.4.11).
- Forced-colors mode: do not rely on background inversions alone; borders remain and carry the component boundaries.

### 9.3 Target size (WCAG 2.5.8 and above)

Minimum hit area 44×44 px for every interactive element (links, buttons, checkboxes via label padding, pagination, language links) — exceeds the 2.2 AA floor of 24×24 (2.5.8) and meets the 2.5.5 AAA 44 px target as house baseline. Inline text links inside paragraphs are exempt per 2.5.8 exception, but sentence-level links get underline styling.

### 9.4 Never color alone (SRS §14.2, WCAG 1.4.1)

Applies to: status badges (glyph + text, §7.5), stat/leaderboard trends (sign + arrow + words, §7.7), form errors (text + glyph + `aria-invalid`, §7.9), table row states (text/position), contribution heatmaps when built (numeric values on every cell), filter states (checked state + text). If a state matters, its name is written on the screen.

### 9.5 Additional mapped requirements

| WCAG 2.2 SC | Rule in this system |
|---|---|
| 1.3.1 Info & Relationships | Semantic landmarks (`header/nav/main/footer`), `dl` for meta, `fieldset/legend`, per-element `lang` |
| 1.4.3 Contrast | §9.1 table; the only approved color pairs are those listed |
| 1.4.4 Resize text | 200 % zoom breaks nothing; rem-only type scale (§3.3) |
| 1.4.10 Reflow | 320 px width, no horizontal scroll except data tables in labeled scroll regions (§7.8) |
| 1.4.11 Non-text Contrast | ≥ 3:1 for borders, focus indicators, glyphs; `#8C8C8C` is the lightest approved structural grey |
| 1.4.12 Text Spacing | Layouts survive user spacing overrides: no fixed-height text containers; buttons grow |
| 2.1.1 Keyboard | Everything operable without a pointer; scrollable tables focusable (§7.8); no drag-only interactions (SRS §14.3) |
| 2.4.1 Bypass Blocks | Skip link is the first focusable element (§7.1) |
| 2.4.4 / 2.4.6 | Descriptive link text ("View project: {title}"), labeled sections; no "click here" |
| 2.4.7 / 2.4.11 | §9.2 |
| 2.5.8 Target Size | 44 px house floor (§9.3) |
| 3.2.6 Consistent Help | Help/support link in the same footer position on every page (§7.2) |
| 3.3.1–3.3.3 Errors | §7.9: inline errors + summary + suggestion text; no loss of user input on error |
| 3.3.8 Accessible Authentication | Login copy never demands cognitive puzzles; MFA flows follow the same form contract |
| 4.1.2 / 4.1.3 | Native elements everywhere; `role="status"` for result counts and async confirmations |
| 2.3.3 / reduced motion | §9.2 media query disables inversions-as-transitions, transforms, animations, and all patterns |

Testing gate (SRS §14.2): every template ships only after keyboard-only pass, screen-reader pass, 320 px reflow, 200 % zoom, reduced-motion, and both EN + NE locale rendering.

---

## 10. Do / Don't

**Do**

- Left-align all text flush to the grid; ragged right. Centered text only inside a centered stat/table numeral column.
- Use black borders (2 px / 4 px) as the visible skeleton; let whitespace and structure do the design.
- Use uppercase + tracking on Latin labels; weight and scale for hierarchy.
- Use crimson exactly for: primary CTA, hover inversion, section numbers, official-government badge (GOV-011).
- Pair every status color with its glyph and localized label.
- Set `lang` on every non-default-language string, including inline Nepali spans.
- Use rem-only sizes, 4 px spacing scale, tabular numerals in data.
- Ship server-rendered HTML that works with zero JS, then enhance.
- Keep the border weights at mobile (4 px stays 4 px).
- Test every screen in EN and NE at +40 % label length.

**Don't**

- No shadows, gradients, rounded corners, glows, or blur — flatness is absolute.
- No crimson decoration: no red strips, red banners, red icons, red links in nav, red errors. (`#FF3000` is banned outright.)
- No color-only status, trend, or error indication — ever (SRS §14.2).
- No centered paragraphs, justified text, or center-aligned forms.
- No letter-spacing or italic/small-caps on Devanagari (breaks shirorekha and conjuncts).
- No fixed `px` font sizes, no fixed-height buttons, no `white-space: nowrap` on bilingual controls.
- No hover-only affordances, drag-only controls, or animation-dependent actions (SRS §14.3).
- No scale/rotate/slide micro-animations; only instant color inversions, and none under reduced motion.
- No icon fonts; inline SVG with `aria-hidden="true"` + adjacent text labels.
- No ellipsis truncation on labels, badges, or nav items.
- No patterns behind body text, on black fills, or on crimson fills.
- No new colors, radii, or shadows introduced by app templates — this file is the complete palette.

---

## Appendix A — Token reference (paste into `static/src/tokens.css`)

```css
:root {
  --color-bg: #ffffff;
  --color-fg: #000000;
  --color-bg-muted: #f2f2f2;
  --color-bg-subtle: #e5e5e5;
  --color-text-secondary: #595959;
  --color-accent: #dc143c;
  --color-border: #000000;
  --color-rule: #8c8c8c;
  --color-error: #9a3412;
  --color-success: #1e6f30;

  --status-draft: #595959;
  --status-review: #8a5a00;
  --status-changes: #9a3412;
  --status-approved: #1d4ed8;
  --status-open: #1e6f30;
  --status-paused: #92400e;
  --status-completed: #0f766e;
  --status-cancelled: #991b1b;
  --status-archived: #595959;

  --font-latin: "Inter", "Noto Sans Devanagari", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-nepali: "Noto Sans Devanagari", "Inter", system-ui, sans-serif;

  --fs-xs: 0.75rem;
  --fs-sm: 0.875rem;
  --fs-base: 1rem;
  --fs-md: 1.125rem;
  --fs-lg: 1.25rem;
  --fs-xl: 1.5rem;
  --fs-2xl: 1.75rem;
  --fs-3xl: 2rem;
  --fs-4xl: 2.5rem;
  --fs-5xl: 3rem;
  --fs-6xl: 3.5rem;
  --fs-7xl: 4.5rem;
  --fs-8xl: 6rem;

  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-12: 3rem;
  --space-16: 4rem;
  --space-24: 6rem;
  --space-32: 8rem;

  --border-1: 1px solid var(--color-rule);
  --border-2: 2px solid var(--color-border);
  --border-4: 4px solid var(--color-border);
  --radius-none: 0;

  --container-max: 1440px;
  --grid-columns: 12;
  --target-min: 44px;
  --focus-outline: 2px solid #000000;
  --focus-offset: 2px;
}
```

## Appendix B — Requirement traceability

| Requirement | Where satisfied |
|---|---|
| SRS §2.3 Inclusive by design | §1.6, §8, §9 |
| SRS §6.1 lifecycle states | §2.2, §7.5 |
| SRS §14.1 navigation areas | §7.1, §7.2 |
| SRS §14.2 accessibility (incl. no-color-alone) | §2.2, §7.5, §7.7, §7.9, §9 |
| SRS §14.3 bilingual + low bandwidth | §3.6, §8, §9.5 |
| GOV-011 official badge | §2.4, §7.3 |
| NFR-A11Y-01 (WCAG 2.2 AA, Must) | §9 (full mapping table) |
| NFR-I18N-01 (EN/NE, switching, fallback) | §7.1, §8.1–8.4 |
| NFR-PERF-01 (LCP ≤ 2.5 s p75, Nepal 4G) | §3.6, §8.5 |
