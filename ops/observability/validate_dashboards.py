#!/usr/bin/env python3
"""CI check: every checked-in Grafana dashboard is well-formed and self-consistent.

Catches the class of mistake a human actually makes editing this JSON by hand:
a typo'd datasource uid, a panel with no query, a dashboard missing its uid/title.
It is not a Grafana schema validator and does not parse PromQL — `promtool check
rules` covers alerting/recording-rule PromQL; ad-hoc panel queries are not checked
for syntax here.
"""

import json
import sys
from pathlib import Path

DASHBOARDS_DIR = Path(__file__).parent / "grafana" / "dashboards"
EXPECTED_DATASOURCE_UID = "devnepal-prometheus"


def validate_dashboard(path: Path) -> list[str]:
    errors = []
    try:
        dashboard = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"{path.name}: invalid JSON ({exc})"]

    for field in ("uid", "title"):
        if not dashboard.get(field):
            errors.append(f"{path.name}: missing required field {field!r}")

    panels = dashboard.get("panels")
    if not panels:
        errors.append(f"{path.name}: has no panels")
        return errors

    for panel in panels:
        panel_label = f"{path.name} panel {panel.get('id', '?')} ({panel.get('title', '?')!r})"
        if not panel.get("title"):
            errors.append(f"{panel_label}: missing a title")

        datasource = panel.get("datasource", {})
        if datasource.get("uid") != EXPECTED_DATASOURCE_UID:
            errors.append(
                f"{panel_label}: datasource uid is {datasource.get('uid')!r}, "
                f"expected {EXPECTED_DATASOURCE_UID!r}"
            )

        targets = panel.get("targets", [])
        if not targets:
            errors.append(f"{panel_label}: has no query targets")
        for target in targets:
            if not target.get("expr", "").strip():
                errors.append(f"{panel_label}: target {target.get('refId', '?')} has an empty expr")

    return errors


def main() -> int:
    dashboard_files = sorted(DASHBOARDS_DIR.glob("*.json"))
    if not dashboard_files:
        print(f"no dashboards found under {DASHBOARDS_DIR}", file=sys.stderr)
        return 1

    all_errors = []
    for path in dashboard_files:
        all_errors.extend(validate_dashboard(path))

    if all_errors:
        print("Dashboard validation failed:", file=sys.stderr)
        for error in all_errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"{len(dashboard_files)} dashboards valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
