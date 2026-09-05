import { readdir, readFile, access } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('.', import.meta.url)), '..', '..')
const templateRoots = [join(root, 'templates'), join(root, 'apps')]

async function collectTemplates(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) files.push(...(await collectTemplates(path)))
    else if (entry.name.endsWith('.html')) files.push(path)
  }
  return files
}

const templates = (
  await Promise.all(templateRoots.map((dir) => collectTemplates(dir)))
).flat()

for (const template of templates) await access(template)

const templateSources = await Promise.all(templates.map((template) => readFile(template, 'utf8')))
const referencedStylesheets = new Set(
  templateSources.flatMap((html) =>
    [...html.matchAll(/{% static ['"]([^'"]+\.css)['"] %}/g)].map((match) => match[1]),
  ),
)
const orphanStylesheets = (await readdir(join(root, 'static', 'src')))
  .filter((name) => name.endsWith('.css'))
  .map((name) => `src/${name}`)
  .filter((name) => !referencedStylesheets.has(name))

if (orphanStylesheets.length > 0) {
  throw new Error(`Unreferenced custom stylesheets found: ${orphanStylesheets.join(', ')}`)
}

const cssFiles = [
  'src/devnepal.css',
  'src/base.css',
  'src/components.css',
  'src/tokens.css',
  'src/onboarding.css',
  'src/public-discovery.css',
]
const forbidden = [
  'linear-gradient(',
  'radial-gradient(',
  'backdrop-filter:',
  'box-shadow:',
  '--shadow-sm:',
  '--shadow-md:',
  '--discovery-rule:',
]
const legacyClasses = [
  'pattern-grid',
  'pattern-dots',
  'pattern-diagonal',
  'pattern-noise',
  'dn-badge-official',
  'dn-badge-suitable',
  'dn-badge-response',
  'dn-badge-community',
]

const cssViolations = []
for (const cssFile of cssFiles) {
  const css = await readFile(join(root, 'static', cssFile), 'utf8')
  for (const pattern of forbidden) {
    if (css.includes(pattern)) cssViolations.push(`${cssFile}: ${pattern}`)
  }
}

for (const cssFile of cssFiles.filter((cssFile) => cssFile !== 'src/tokens.css')) {
  const css = await readFile(join(root, 'static', cssFile), 'utf8')
  if (/#[\da-f]{3,8}\b/i.test(css)) cssViolations.push(`${cssFile}: raw color value`)
}

for (const cssFile of ['src/onboarding.css', 'src/public-discovery.css']) {
  const css = await readFile(join(root, 'static', cssFile), 'utf8')
  if (/\/\*/.test(css)) cssViolations.push(`${cssFile}: explanatory CSS comment`)
}

const componentsCss = await readFile(join(root, 'static', 'src/components.css'), 'utf8')
if (/\.dn-state-dot\s*\{[^}]*width:\s*10px;[^}]*height:\s*10px/s.test(componentsCss)) {
  cssViolations.push('src/components.css: decorative state dot')
}
if (/[^{}]*\.dn-section-kicker[^{}]*\{[^}]*text-transform:\s*uppercase/s.test(componentsCss)) {
  cssViolations.push('src/components.css: repeated uppercase section eyebrow')
}
if (/[^{}]*\.section__header[^{}]*\{[^}]*text-transform:\s*uppercase/s.test(componentsCss)) {
  cssViolations.push('src/components.css: inherited uppercase page header')
}
if (!/\.section__header\s*\{[^}]*display:\s*flex/s.test(componentsCss)) {
  cssViolations.push('src/components.css: missing responsive page-header layout')
}

const onboardingCss = await readFile(join(root, 'static', 'src/onboarding.css'), 'utf8')
if (/\.dn-onboarding__heading\s*>\s*p:first-child\s*\{[^}]*text-transform:\s*uppercase/s.test(onboardingCss)) {
  cssViolations.push('src/onboarding.css: repeated uppercase onboarding eyebrow')
}

const baseCss = await readFile(join(root, 'static', 'src/base.css'), 'utf8')
for (const required of ['h1 {\n  font-size: clamp(', 'main :where(p, li, dd) a:not(.btn)']) {
  if (!baseCss.includes(required)) cssViolations.push(`src/base.css: missing ${required}`)
}
if (!/a\s*\{[^}]*color:\s*var\(--color-accent-700\)/s.test(baseCss)) {
  cssViolations.push('src/base.css: default links use low-contrast accent')
}

const shellCss = await readFile(join(root, 'static', 'src/devnepal.css'), 'utf8')
const navigationCues = [
  [/\.dn-primary-nav a\[aria-current="page"\]\s*\{[^}]*text-decoration:\s*underline/s, 'primary navigation'],
  [/\.mobile-nav a\[aria-current="page"\]\s*\{[^}]*border-left:/s, 'mobile navigation'],
  [/\.dn-admin-nav a\[aria-current="page"\]\s*\{[^}]*text-decoration:\s*underline/s, 'admin navigation'],
]
for (const [pattern, name] of navigationCues) {
  if (!pattern.test(shellCss)) cssViolations.push(`src/devnepal.css: missing ${name} cue`)
}

for (const [css, name] of [
  [componentsCss, 'src/components.css'],
  [shellCss, 'src/devnepal.css'],
]) {
  if (/color:\s*var\(--color-bg\);[^}]*background:\s*var\(--color-accent(?:-600)?\)/s.test(css)) {
    cssViolations.push(`${name}: low-contrast text-bearing accent`)
  }
}

if (cssViolations.length > 0) {
  throw new Error(`Banned design-system patterns found: ${cssViolations.join(', ')}`)
}

const templateViolations = []
for (const template of templates) {
  const html = await readFile(template, 'utf8')
  const name = template.replace(`${root}/`, '')
  const extendsBase = /{% extends ["'][^"']+["'] %}/.test(html)
  const hasBlocks = /{% block\s/.test(html)
  const isPartial =
    template.includes(`${join('/')}components${join('/')}`) ||
    name.split('/').pop().startsWith('_') ||
    (!extendsBase && !hasBlocks)

  for (const legacy of legacyClasses) {
    if (html.includes(legacy)) templateViolations.push(`${name}: legacy class ${legacy}`)
  }
  if (!extendsBase && !isPartial && !html.includes('primer.css')) {
    templateViolations.push(`${name}: does not load Primer CSS`)
  }
  if (!extendsBase && !isPartial && !html.includes('dn-skip-link')) {
    templateViolations.push(`${name}: missing a skip link`)
  }
  if (/\bonclick\s*=/i.test(html)) {
    templateViolations.push(`${name}: uses inline onclick handler`)
  }
  for (const match of html.matchAll(/<img\b[^>]*>/g)) {
    if (!/\balt="[^"]*"/.test(match[0])) {
      templateViolations.push(`${name}: image without alt text`)
    }
  }
}

if (templateViolations.length > 0) {
  throw new Error(`Template contract violations:\n${templateViolations.join('\n')}`)
}

const base = await readFile(join(root, 'templates/base.html'), 'utf8')
for (const required of [
  '<meta name="description"',
  'dn-product-header',
  'dn-primary-nav',
  'dn-skip-link',
  'primer.css',
  'devnepal.css',
]) {
  if (!base.includes(required)) throw new Error(`templates/base.html is missing: ${required}`)
}

for (const viewName of [
  'projects:home',
  'projects:government',
  'projects:community',
  'projects:about',
  'projects:list',
  'accounts:member_directory',
  'accounts:login',
  'accounts:signup',
  'accounts:dashboard',
  'blogs:list',
  'recognition:leaderboard',
  'recognition:my_profile',
  'notifications:list',
  'projects:application_list',
  'administration:console',
  'administration:feature_flags',
  'projects:review_queue',
  'projects:authoring_dashboard',
  'moderation:case_queue',
  'contributions:verification_queue',
  'ministries:organization_list',
  'taxonomy:skill_suggestion_review_list',
  'recognition:badge_list',
  'audit:ops_dashboard',
  'audit:audit_log',
]) {
  const marker = `request.resolver_match.view_name == '${viewName}'`
  if (!base.includes(marker)) throw new Error(`templates/base.html lacks current-page state: ${viewName}`)
}

console.log(`Validated ${templates.length} templates and ${cssFiles.length} stylesheets against the DevNepal design-system contract.`)
