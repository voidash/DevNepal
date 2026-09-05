import sys
import types
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.github_sync.enums import ProcessingState
from apps.github_sync.models import ProviderEvent
from apps.github_sync.tests.factories import (
    ProviderEventFactory,
    RepositoryConnectionFactory,
)

pytestmark = [pytest.mark.integration, pytest.mark.github_webhook, pytest.mark.django_db]


def install_fake_contributions(monkeypatch, calls):
    module = types.ModuleType("apps.contributions.services")

    def record_candidate_from_github(parsed, project):
        calls.append((parsed, project))

    module.record_candidate_from_github = record_candidate_from_github
    monkeypatch.setitem(sys.modules, "apps.contributions.services", module)


def block_contributions(monkeypatch):
    monkeypatch.setitem(sys.modules, "apps.contributions.services", None)


class TestProcessGithubEventsCommand:
    def test_drains_pending_events_and_prints_result(self, monkeypatch):
        """GIT-005: the worker entrypoint drains PENDING events and prints the tally."""
        calls = []
        install_fake_contributions(monkeypatch, calls)
        ProviderEventFactory()
        ProviderEventFactory()
        out = StringIO()

        call_command("process_github_events", stdout=out)

        assert len(calls) == 2
        output = out.getvalue()
        assert "processed=2" in output
        assert "failed=0" in output

    def test_limit_bounds_one_worker_pass(self, monkeypatch):
        """GIT-005/A9: --limit bounds a single drain; the backlog stays queued."""
        calls = []
        install_fake_contributions(monkeypatch, calls)
        ProviderEventFactory()
        ProviderEventFactory()
        ProviderEventFactory()
        out = StringIO()

        call_command("process_github_events", limit=2, stdout=out)

        assert len(calls) == 2
        assert ProviderEvent.objects.filter(processing_state=ProcessingState.PENDING).count() == 1
        assert "processed=2" in out.getvalue()

    def test_blocked_events_are_reported_without_failing_the_run(self, monkeypatch):
        """GIT-005: rows blocked by a missing contributions module keep the worker exit clean."""
        block_contributions(monkeypatch)
        event = ProviderEventFactory()
        out = StringIO()

        call_command("process_github_events", stdout=out)

        output = out.getvalue()
        assert "blocked=1" in output
        assert str(event.pk) in output
        event.refresh_from_db()
        assert event.processing_state == ProcessingState.PENDING

    def test_failures_are_logged_and_fail_the_run(self, monkeypatch, caplog):
        """GIT-005: unmapped-repo failures are logged and exit nonzero for the scheduler."""
        install_fake_contributions(monkeypatch, [])
        connection = RepositoryConnectionFactory(project=None)
        ProviderEventFactory(node_id=connection.repository_node_id)
        err = StringIO()

        with pytest.raises(CommandError):
            call_command("process_github_events", stdout=StringIO(), stderr=err)

        assert "failed=1" in err.getvalue()
        assert "process_github_events" in caplog.text

    def test_rejects_non_positive_limit(self):
        """GIT-005: a non-positive --limit is a configuration error, not an unbounded run."""

        with pytest.raises(CommandError):
            call_command("process_github_events", limit=0)
