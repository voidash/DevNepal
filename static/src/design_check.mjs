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

const cssFiles = ['src/devnepal.css', 'src/base.css', 'src/components.css', 'src/tokens.css']
const forbidden = ['linear-gradient(', 'radial-gradient(', 'backdrop-filter:', 'box-shadow: 0 20px']
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
  'dn-product-header',
  'dn-primary-nav',
  'dn-skip-link',
  'primer.css',
  'devnepal.css',
]) {
  if (!base.includes(required)) throw new Error(`templates/base.html is missing: ${required}`)
}

console.log(`Validated ${templates.length} templates and ${cssFiles.length} stylesheets against the DevNepal design-system contract.`)
