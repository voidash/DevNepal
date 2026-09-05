# DevNepal

Public collaboration and developer-community platform for the Government of Nepal —
Office of the Prime Minister and Council of Ministers, Digital Collaboration Initiative.

DevNepal is a trusted registry and collaboration layer, not a replacement for GitHub.
Source code, branches, issues, pull requests, CI, and code review stay in approved
repositories. DevNepal provides identity, project discovery, structured project
metadata, applications and participation records, verified contribution events,
community content, recognition, governance, and reporting.

## Repository contents

| Path | Description |
| --- | --- |
| [`docs/DevNepal_Requirements_and_Scope_v0.9.docx`](docs/DevNepal_Requirements_and_Scope_v0.9.docx) | Software Requirements Specification and Project Scope, v0.9 (2 Sep 2026) — draft for stakeholder validation |
| [`prototype/index.html`](prototype/index.html) | Self-contained clickable prototype (single bundled HTML file, no build step) |

## Viewing the prototype

Open `prototype/index.html` directly in a browser, or serve it locally:

```
python3 -m http.server 8000
```

then visit http://localhost:8000/prototype/

## Status

The requirements document is **v0.9, draft for stakeholder validation**. It does not by
itself approve policy, procurement, data processing, hosting, open-source licensing, or
public release of any government system. Validation is pending across business
ownership, ministry operating model, security and hosting, privacy and legal, and
community governance.

## Roles

Three authorization roles are defined: **Super Admin**, **Ministry Publisher**, and
**Member**. Public visitors are an unauthenticated access state, not an administrative
role. Ministries are represented by an organization record with named officer accounts —
shared ministry credentials are not acceptable.
