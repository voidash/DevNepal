import logging
from unittest import mock

import pytest

from apps.analytics.enums import EventName
from apps.analytics.models import AnalyticsEventRecord
from apps.analytics.services import AnalyticsEventError
from apps.contributions.enums import VerificationStatus
from apps.contributions.services import ContributionAnalyticsError, verify
from apps.contributions.tests.factories import ContributionRecordFactory
from apps.projects.tests.factories import ProjectMaintainerFactory

pytestmark = pytest.mark.django_db


@pytest.mark.integration
def test_accepted_contribution_records_an_idempotent_project_event():
    """ANL-001: accepted government contribution records an opaque-source analytics event."""
    record = ContributionRecordFactory()
    maintainer = ProjectMaintainerFactory(project=record.project).user

    verify(maintainer, record, VerificationStatus.ACCEPTED, "Accepted after review")

    event = AnalyticsEventRecord.objects.get()
    assert event.event_name == EventName.CONTRIBUTION_ACCEPTED
    assert event.ministry_id == record.project.ministry_id
    assert event.project_id == record.project_id
    assert event.source_ref == f"contribution:{record.pk}"


@pytest.mark.integration
def test_contribution_acceptance_rolls_back_when_analytics_persistence_fails(caplog):
    """ANL-001: contribution acceptance is not committed without its required analytics event."""
    record = ContributionRecordFactory()
    maintainer = ProjectMaintainerFactory(project=record.project).user

    with (
        caplog.at_level(logging.ERROR, logger="apps.contributions.services"),
        mock.patch(
            "apps.contributions.services.record_event",
            side_effect=AnalyticsEventError("storage unavailable"),
        ),
        pytest.raises(ContributionAnalyticsError, match="analytics"),
    ):
        verify(maintainer, record, VerificationStatus.ACCEPTED, "Accepted after review")

    record.refresh_from_db()
    assert record.status == VerificationStatus.CANDIDATE
    assert not AnalyticsEventRecord.objects.exists()
    assert "Contribution analytics recording failed" in caplog.text
