from pathlib import Path

import pytest
from django.conf import settings

pytestmark = pytest.mark.unit


def _template(name: str) -> str:
    return (Path(settings.BASE_DIR) / "apps/projects/templates/projects" / name).read_text()


def test_prototype_ministry_and_application_surfaces_make_workflow_state_explicit():
    """C2/D2/C3/C5; GOV-004/GOV-005/GOV-009/DSC-007/DSC-008: the prototype's
    authoring, review, application-decision, and completion surfaces expose their current
    state, next action, and append-only history in the rendered UI."""
    authoring = _template("authoring_detail.html")
    application_detail = _template("application_detail.html")
    application_timeline = _template("application_timeline.html")
    application_list = _template("application_list.html")

    assert '{% trans "Current project state" %}' in authoring
    assert '{% trans "Next lifecycle action" %}' in authoring
    assert 'class="dn-timeline"' in authoring
    changes_requested = (
        '{% trans "Changes requested: address the recorded review comments, save the revision, '
        'then resubmit." %}'
    )
    assert changes_requested in authoring
    assert '{% trans "Ready for publication" %}' in authoring

    assert '{% trans "Current application status" %}' in application_detail
    assert '{% trans "Available decision" %}' in application_detail
    assert 'class="dn-timeline"' in application_detail
    assert '{% trans "Current application status" %}' in application_timeline
    assert 'class="dn-timeline"' in application_timeline
    assert 'class="dn-issue-list"' in application_list
