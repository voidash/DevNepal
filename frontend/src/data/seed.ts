/**
 * Seed data — the ONE fixture set.
 *
 * Three consumers, deliberately: the Reference boards expand their canvas
 * templates from it, the Live screens read it through the MockAdapter, and the
 * Django lead loads the same records with `manage.py loaddata`. Change a
 * ministry's name here and it changes on every screen of every tier.
 *
 * Official names — ministries, people, project titles — are record, gazetted
 * in both scripts, and are lifted from the Gov design-system fixtures. They are
 * NOT interface copy and are never retranslated in a strings file.
 *
 * Field names below match the canvas's own template expressions exactly
 * ({{ p.statusClass }}, {{ m.tier }} …). Renaming one breaks a board.
 */

export const ministries = [
  { code: "DoIT",    name: "Department of Information Technology",  nameNe: "सूचना प्रविधि विभाग",              parent: "MoCIT",  domain: "doit.gov.np",    officers: 2, projects: 5, status: "Active",  statusClass: "tag-success", mfa: "Enforced", last: "Today, 10:12" },
  { code: "DHM",     name: "Department of Hydrology and Meteorology", nameNe: "जल तथा मौसम विज्ञान विभाग",     parent: "MoEWRI", domain: "dhm.gov.np",     officers: 2, projects: 1, status: "Active",  statusClass: "tag-success", mfa: "Enforced", last: "Yesterday" },
  { code: "MoLMCPA", name: "Ministry of Land Management, Cooperatives and Poverty Alleviation", nameNe: "भूमि व्यवस्था, सहकारी तथा गरिबी निवारण मन्त्रालय", domain: "molmcpa.gov.np", officers: 1, projects: 0, status: "Active", statusClass: "tag-success", mfa: "Enforced", last: "Today, 09:40" },
  { code: "MoHP",    name: "Ministry of Health and Population",      nameNe: "स्वास्थ्य तथा जनसंख्या मन्त्रालय", domain: "mohp.gov.np",    officers: 3, projects: 4, status: "Active",  statusClass: "tag-success", mfa: "Enforced", last: "3 days ago" },
  { code: "MoFAGA",  name: "Ministry of Federal Affairs and General Administration", nameNe: "सङ्घीय मामिला तथा सामान्य प्रशासन मन्त्रालय", domain: "mofaga.gov.np", officers: 2, projects: 3, status: "Active", statusClass: "tag-success", mfa: "Enforced", last: "5 days ago" },
  { code: "MoEST",   name: "Ministry of Education, Science and Technology", nameNe: "शिक्षा, विज्ञान तथा प्रविधि मन्त्रालय", domain: "moest.gov.np", officers: 1, projects: 3, status: "Pending", statusClass: "tag-warning", mfa: "Not yet",  last: "—" },
  { code: "MoALD",   name: "Ministry of Agriculture and Livestock Development", nameNe: "कृषि तथा पशुपन्छी विकास मन्त्रालय", domain: "moald.gov.np", officers: 1, projects: 1, status: "Active", statusClass: "tag-success", mfa: "Enforced", last: "2 weeks ago" },
] as const

export const projects = [
  { slug: "monsoon-flood-alert-gateway", title: "Monsoon Flood Alert Gateway", ne: "मनसुन बाढी चेतावनी गेटवे", ministry: "DHM", short: "DHM", summary: "SMS and app alerts from river-gauge telemetry for 14 flood-prone districts; open API for municipalities.", status: "Open", statusClass: "tag-success", stack: "Go · PostgreSQL · Flutter", types: ["Engineering", "Localization"], mode: "Remote", difficulty: "Intermediate", effort: "4–8 h/week", response: "Within 3 working days", tasks: 6, contributors: 4, updated: "2 days ago" },
  { slug: "sewa-portal-accessibility", title: "Sewa Portal Accessibility Remediation", ne: "सेवा पोर्टल पहुँचयोग्यता सुधार", ministry: "DoIT", short: "DoIT", summary: "Bring the citizen services portal to WCAG 2.2 AA: screen-reader labelling in Nepali, keyboard paths, contrast.", status: "Open", statusClass: "tag-success", stack: "React · TypeScript", types: ["Engineering", "UI/UX", "QA"], mode: "Remote", difficulty: "Beginner-friendly", effort: "2–4 h/week", response: "Within 2 working days", tasks: 9, contributors: 7, updated: "Today" },
  { slug: "land-records-open-data-api", title: "Land Records Open Data API", ne: "भूमि अभिलेख खुला डेटा API", ministry: "MoLMCPA", short: "MoLMCPA", summary: "Read-only API over published cadastral summaries, with rate limits and provenance headers.", status: "Draft", statusClass: "tag-neutral", stack: "Django · PostGIS", types: ["Engineering", "Documentation"], mode: "Remote", difficulty: "Advanced", effort: "8+ h/week", response: "Within 5 working days", tasks: 0, contributors: 0, updated: "Just created" },
  { slug: "nagarik-app-localisation", title: "Nagarik App Nepali Localisation", ne: "नागरिक एप नेपाली स्थानीयकरण", ministry: "DoIT", short: "DoIT", summary: "Translate and review 1,900 interface strings; Devanagari typography QA on Android and iOS.", status: "Open", statusClass: "tag-success", stack: "Flutter · Weblate", types: ["Localization", "QA"], mode: "Remote", difficulty: "Beginner-friendly", effort: "2–4 h/week", response: "Within 2 working days", tasks: 12, contributors: 11, updated: "Yesterday" },
  { slug: "school-census-pipeline", title: "School Census Data Pipeline", ne: "विद्यालय गणना डेटा पाइपलाइन", ministry: "MoEST", short: "MoEST", summary: "Validate and publish the annual school census as open data with a documented schema.", status: "Open", statusClass: "tag-success", stack: "Python · dbt", types: ["Data", "Documentation"], mode: "Hybrid · Kathmandu", difficulty: "Intermediate", effort: "4–8 h/week", response: "Within 4 working days", tasks: 3, contributors: 2, updated: "5 days ago" },
  { slug: "health-facility-registry", title: "Health Facility Registry", ne: "स्वास्थ्य संस्था दर्ता", ministry: "MoHP", short: "MoHP", summary: "Master list of facilities with geocodes, services and opening hours; FHIR Location export.", status: "Paused", statusClass: "tag-warning", stack: "Java · HAPI FHIR", types: ["Engineering", "Data"], mode: "Remote", difficulty: "Advanced", effort: "8+ h/week", response: "Paused", tasks: 4, contributors: 3, updated: "3 weeks ago" },
] as const

export const members = [
  { handle: "@sabina", name: "Sabina Rai",      nameNe: "सबिना राई",     head: "Front-end developer · accessibility", loc: "Lalitpur",   tier: "Contributor", skills: ["React", "Accessibility", "Nepali l10n"], open: "Government projects", verified: 1 },
  { handle: "@anish",  name: "Anish Maharjan",  nameNe: "अनिश महर्जन",   head: "Backend · Go and Postgres",           loc: "Kathmandu",  tier: "Trusted",     skills: ["Go", "PostgreSQL", "APIs"],              open: "Mentoring",           verified: 14 },
  { handle: "@prakriti", name: "Prakriti Sharma", nameNe: "प्रकृति शर्मा", head: "Technical writer",                   loc: "Pokhara",    tier: "Trusted",     skills: ["Documentation", "Nepali", "Markdown"],   open: "Documentation",       verified: 9 },
  { handle: "@bibek",  name: "Bibek Gurung",    nameNe: "विवेक गुरुङ",   head: "QA engineer · mobile",                loc: "Butwal",     tier: "Contributor", skills: ["QA", "Flutter", "Android"],              open: "Testing",             verified: 3 },
  { handle: "@sunita", name: "Sunita Tamang",   nameNe: "सुनिता तामाङ",  head: "Data engineer",                       loc: "Biratnagar", tier: "Ambassador",  skills: ["Python", "dbt", "Open data"],            open: "Government projects", verified: 27 },
  { handle: "@rohan",  name: "Rohan Shrestha",  nameNe: "रोहन श्रेष्ठ",  head: "UI designer",                         loc: "Bhaktapur",  tier: "Contributor", skills: ["UI/UX", "Figma", "Design systems"],      open: "Design reviews",      verified: 5 },
  { handle: "@nabin",  name: "Nabin Karki",     nameNe: "नविन कार्की",   head: "Security researcher",                 loc: "Dharan",     tier: "Trusted",     skills: ["Security", "Web", "Reporting"],          open: "Security reviews",    verified: 8 },
  { handle: "@dipa",   name: "Dipa Adhikari",   nameNe: "दीपा अधिकारी",  head: "Localisation lead",                   loc: "Hetauda",    tier: "MVP",         skills: ["Nepali l10n", "Weblate", "Typography"],  open: "Localization",        verified: 41 },
  { handle: "@kiran",  name: "Kiran Thapa",     nameNe: "किरण थापा",     head: "Student · first contributions",       loc: "Kathmandu",  tier: "Contributor", skills: ["JavaScript", "Git"],                     open: "Beginner tasks",      verified: 0 },
] as const

export const board = members
  .filter((m) => m.verified > 0)
  .sort((a, b) => b.verified - a.verified)
  .map((m, i) => ({
    rank: i + 1,
    name: m.name,
    handle: m.handle,
    loc: m.loc,
    tier: m.tier,
    score: m.verified * 38 + (9 - i) * 7,
    prs: Math.round(m.verified * 0.6),
    docs: Math.round(m.verified * 0.2),
    design: Math.round(m.verified * 0.1),
    qa: Math.round(m.verified * 0.1),
    badges: String(Math.min(6, 1 + Math.floor(m.verified / 6))),
    change: i % 3 === 0 ? "▲ 2" : i % 3 === 1 ? "—" : "▼ 1",
    projects: String(1 + (m.verified % 4)),
  }))

export const blogs = [
  { title: "Labelling forms in Nepali for screen readers", author: "Sabina Rai",     date: "2 Sep 2026", excerpt: "What NVDA and TalkBack actually read when an aria-label is Devanagari — and what they skip.", kind: "Member",   kindClass: "tag-neutral", lang: "EN", mins: "6 min", tags: "Accessibility · Nepali" },
  { title: "खुला डेटा प्रकाशन गर्दा ध्यान दिनुपर्ने कुरा", author: "Sunita Tamang", date: "28 Aug 2026", excerpt: "सरकारी डेटासेट सार्वजनिक गर्नुअघि स्किमा, प्रोभिनेन्स र अद्यावधिक तालिका किन चाहिन्छ।", kind: "Member", kindClass: "tag-neutral", lang: "NE", mins: "8 min", tags: "Open data" },
  { title: "Rate limiting a public government API",         author: "Anish Maharjan", date: "21 Aug 2026", excerpt: "Token buckets per API key, provenance headers, and why we log the referrer and nothing else.", kind: "Member",   kindClass: "tag-neutral", lang: "EN", mins: "9 min", tags: "APIs · Go" },
  { title: "Devanagari line-height is not Latin line-height", author: "Dipa Adhikari", date: "14 Aug 2026", excerpt: "Matras above and below the headline mean 1.5 clips. Where 1.75 comes from.", kind: "External · Medium", kindClass: "tag-outline", lang: "EN", mins: "5 min", tags: "Typography" },
  { title: "Testing a Flutter app on low-end Android",      author: "Bibek Gurung",  date: "7 Aug 2026",  excerpt: "A ₨ 9,000 phone, a 2G profile, and the checklist we now run before every release.", kind: "Member",   kindClass: "tag-neutral", lang: "EN", mins: "7 min", tags: "QA · Mobile" },
] as const

export const community = [
  { title: "NepaliDate.js",        owner: "@dipa",   stack: "TypeScript", summary: "Bikram Sambat ↔ Gregorian conversion with Devanagari numeral formatting.", links: "GitHub · npm · Docs",      verified: true,  unverified: false, updated: "3 days ago" },
  { title: "Preeti to Unicode",    owner: "@prakriti", stack: "Python",  summary: "Convert legacy Preeti-encoded documents to Unicode Devanagari, batch and CLI.", links: "GitHub · PyPI",            verified: true,  unverified: false, updated: "1 week ago" },
  { title: "Nepal Admin Boundaries", owner: "@sunita", stack: "GeoJSON",  summary: "Province, district and municipality boundaries, 2017 restructuring, CC-BY.", links: "GitHub · Download",        verified: true,  unverified: false, updated: "2 weeks ago" },
  { title: "Sajha Bus Tracker",    owner: "@anish",  stack: "Go · Flutter", summary: "Community-run live positions for Sajha Yatayat routes in the valley.",  links: "GitHub · App",             verified: false, unverified: true,  updated: "1 month ago" },
  { title: "Nepali Spellcheck",    owner: "@kiran",  stack: "Rust",       summary: "Hunspell-compatible dictionary and a VS Code extension.",                 links: "GitHub",                   verified: false, unverified: true,  updated: "2 months ago" },
  { title: "OpenSchool Nepal",     owner: "@rohan",  stack: "Figma · React", summary: "Design system and starter for school websites in both scripts.",       links: "GitHub · Figma community", verified: true,  unverified: false, updated: "5 days ago" },
] as const

export const badges = {
  myBadges: [
    { name: "First accepted",    ne: "पहिलो स्वीकृति",  icon: "◆", earned: "Earned 4 Sep 2026" },
    { name: "Accessibility",     ne: "पहुँचयोग्यता",     icon: "◈", earned: "Earned 4 Sep 2026" },
    { name: "Documentation",     ne: "दस्तावेज",         icon: "▣", earned: "Not yet" },
    { name: "Reviewer",          ne: "समीक्षक",          icon: "◉", earned: "Not yet" },
    { name: "Five verified",     ne: "पाँच प्रमाणित",    icon: "★", earned: "Not yet" },
    { name: "Mentor",            ne: "मार्गदर्शक",       icon: "✦", earned: "Not yet" },
  ],
  communityBadges: [
    { name: "First accepted",  ne: "पहिलो स्वीकृति", icon: "◆", desc: "A first verified contribution to any government project.",      how: "Automatic on first verified record" },
    { name: "Five verified",   ne: "पाँच प्रमाणित",   icon: "★", desc: "Five verified contributions across at least two projects.",       how: "Automatic" },
    { name: "Documentation",   ne: "दस्तावेज",        icon: "▣", desc: "Three accepted documentation contributions.",                     how: "Automatic" },
    { name: "Accessibility",   ne: "पहुँचयोग्यता",    icon: "◈", desc: "An accepted contribution tagged accessibility, confirmed by the ministry.", how: "Ministry confirms the tag" },
    { name: "Localisation",    ne: "स्थानीयकरण",      icon: "◇", desc: "Five hundred reviewed strings in Nepali or another language of Nepal.",  how: "Automatic from Weblate sync" },
    { name: "Reviewer",        ne: "समीक्षक",         icon: "◉", desc: "Ten reviews accepted by a maintainer.",                            how: "Maintainer marks the review" },
    { name: "Mentor",          ne: "मार्गदर्शक",      icon: "✦", desc: "Three first-time contributors reached a verified record with your help.", how: "Nominated by the mentee, confirmed by PMO" },
    { name: "Long haul",       ne: "निरन्तरता",       icon: "◎", desc: "Verified contributions in twelve different months.",               how: "Automatic" },
  ],
  securityBadges: [
    { name: "Responsible disclosure", ne: "जिम्मेवार खुलासा", icon: "⬢", desc: "A valid report through the security contact, fixed and credited.", how: "Security team confirms", mode: "Coordinated", modeClass: "tag-info" },
    { name: "Critical find",          ne: "गम्भीर खोज",       icon: "⬢", desc: "A report rated critical by the receiving ministry.",           how: "Security team confirms", mode: "Coordinated", modeClass: "tag-info" },
    { name: "Hardening",              ne: "सुदृढीकरण",        icon: "⬡", desc: "Accepted change that removes a class of vulnerability.",        how: "Maintainer marks the change", mode: "Public",  modeClass: "tag-neutral" },
    { name: "Dependency watch",       ne: "निर्भरता निगरानी", icon: "⬡", desc: "Five accepted dependency-update contributions.",                how: "Automatic", mode: "Public", modeClass: "tag-neutral" },
    { name: "Threat model",           ne: "खतरा मोडेल",       icon: "⬢", desc: "An accepted threat-model document for a project.",              how: "Ministry confirms", mode: "Coordinated", modeClass: "tag-info" },
    { name: "Incident support",       ne: "घटना सहयोग",       icon: "⬢", desc: "Named in a ministry's incident record as a contributor to the fix.", how: "PMO confirms", mode: "Coordinated", modeClass: "tag-info" },
    { name: "Security reviewer",      ne: "सुरक्षा समीक्षक",  icon: "⬡", desc: "Ten security reviews accepted by maintainers.",                 how: "Automatic", mode: "Public", modeClass: "tag-neutral" },
  ],
  prestige: [
    { name: "MVP",        ne: "एमभीपी",   icon: "✶", desc: "Granted by the Office of the Prime Minister for sustained, verified impact across ministries.", holders: "3 holders", link: "How MVP is decided" },
    { name: "Ambassador", ne: "राजदूत",   icon: "✷", desc: "Granted by the Office of the Prime Minister for growing the community — mentoring, events, first-contributor support.", holders: "5 holders", link: "How Ambassador is decided" },
  ],
} as const

/* Ministry-side lists (C3.1 dashboard, D2.1 review queue). */
export const pubProjects = [
  { title: "Sewa Portal Accessibility Remediation", state: "Live",            stateClass: "tag-success", apps: "3 new", cands: "2 to verify", response: "1.4 days avg", action: "Respond" },
  { title: "Nagarik App Nepali Localisation",       state: "Live",            stateClass: "tag-success", apps: "1 new", cands: "4 to verify", response: "0.8 days avg", action: "Verify" },
  { title: "DoIT API Gateway Docs",                 state: "In review",       stateClass: "tag-info",    apps: "—",     cands: "—",           response: "—",            action: "View" },
  { title: "Citizen ID Sandbox",                    state: "Changes requested", stateClass: "tag-warning", apps: "—",   cands: "—",           response: "—",            action: "Resubmit" },
  { title: "Legacy Forms Archive",                  state: "Completed",       stateClass: "tag-neutral", apps: "—",     cands: "—",           response: "—",            action: "Summary" },
] as const

export const apps = [
  { who: "Sabina Rai",     handle: "@sabina",  ws: "Screen-reader labelling (Nepali)", state: "Applied",  stateClass: "tag-info",    when: "2 hours ago" },
  { who: "Rohan Shrestha", handle: "@rohan",   ws: "Contrast and focus states",         state: "Applied",  stateClass: "tag-info",    when: "Yesterday" },
  { who: "Bibek Gurung",   handle: "@bibek",   ws: "Keyboard paths · QA",               state: "Accepted", stateClass: "tag-success", when: "3 days ago" },
  { who: "Kiran Thapa",    handle: "@kiran",   ws: "Screen-reader labelling (Nepali)", state: "Declined", stateClass: "tag-neutral", when: "4 days ago" },
] as const

export const queueRest = [
  { id: "GN-2026-023", title: "Land Records Open Data API",      ministry: "MoLMCPA", submitted: "Today, 09:40",  sla: "5 days left", state: "New",          stateClass: "tag-info",    reviewer: "Unassigned", checklist: "0 / 7" },
  { id: "GN-2026-022", title: "School Census Data Pipeline v2",  ministry: "MoEST",   submitted: "Yesterday",     sla: "4 days left", state: "In review",    stateClass: "tag-info",    reviewer: "B. Neupane", checklist: "4 / 7" },
  { id: "GN-2026-021", title: "Monsoon Flood Alert Gateway v3",  ministry: "DHM",     submitted: "29 Aug 2026",   sla: "1 day left",  state: "Changes sent", stateClass: "tag-warning", reviewer: "B. Neupane", checklist: "7 / 7" },
  { id: "GN-2026-020", title: "Health Facility Registry",        ministry: "MoHP",    submitted: "25 Aug 2026",   sla: "Overdue",     state: "Awaiting ministry", stateClass: "tag-warning", reviewer: "S. Poudel", checklist: "7 / 7" },
  { id: "GN-2026-019", title: "Nagarik App Nepali Localisation", ministry: "DoIT",    submitted: "20 Aug 2026",   sla: "—",           state: "Approved",     stateClass: "tag-success", reviewer: "B. Neupane", checklist: "7 / 7" },
] as const

/* ── the scope the reference boards render against ────────────────────────── */
export const referenceScope: Record<string, unknown> = {
  /* canvas presentation toggles — the narrative rail and trace notes are the
     designer's, not the user's */
  story: false,
  showTrace: false,
  isB: false,
  true: true,
  false: false,

  catalog: projects,
  featured: projects.slice(0, 3),
  community,
  communityFeatured: community.slice(0, 4),
  members,
  membersTop: members.slice(0, 4),
  board,
  boardTop: board.slice(0, 5),
  blogs,
  blogsTop: blogs.slice(0, 3),
  ministries,
  pubProjects,
  apps,
  queueRest,
  ...badges,
}
