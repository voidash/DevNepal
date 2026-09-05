import datetime

import pytest
from django.template.loader import render_to_string
from django.utils import timezone

from apps.contributions.enums import VerificationStatus
from apps.contributions.tests.factories import ContributionRecordFactory
from apps.github_sync.services import annual_contribution_calendar
from apps.github_sync.tests.factories import GithubConnectionFactory
from apps.github_sync.views import calendar_context
from apps.ministries.tests.factories import UserFactory

pytestmark = [pytest.mark.django_db]

CALENDAR_TEMPLATE = "github_sync/calendar.html"


def utc_at(day, hour=10):
    return datetime.datetime(day.year, day.month, day.day, hour, tzinfo=datetime.UTC)


def accept(user, *, day, count=1, hour=10):
    return [
        ContributionRecordFactory(
            contributor=user,
            status=VerificationStatus.ACCEPTED,
            verified_at=utc_at(day, hour),
            revoked_at=None,
        )
        for _ in range(count)
    ]


class TestAnnualContributionCalendarService:
    def test_counts_only_accepted_verified_records_of_linked_user(self):
        """GIT-009/BR-005: the calendar counts accepted verified records only, never raw events."""
        connection = GithubConnectionFactory(show_annual_calendar=True)
        other = UserFactory()
        accept(connection.user, day=datetime.date(2025, 3, 10), count=2)
        accept(connection.user, day=datetime.date(2025, 3, 11))
        accept(other, day=datetime.date(2025, 3, 10))
        ContributionRecordFactory(
            contributor=connection.user,
            status=VerificationStatus.CANDIDATE,
            verified_at=utc_at(datetime.date(2025, 3, 12)),
        )
        ContributionRecordFactory(
            contributor=connection.user,
            status=VerificationStatus.REJECTED,
            verified_at=utc_at(datetime.date(2025, 3, 13)),
        )
        ContributionRecordFactory(
            contributor=connection.user,
            status=VerificationStatus.REVOKED,
            verified_at=utc_at(datetime.date(2025, 3, 14)),
            revoked_at=utc_at(datetime.date(2025, 4, 1)),
        )
        ContributionRecordFactory(
            contributor=connection.user,
            status=VerificationStatus.ACCEPTED,
            verified_at=utc_at(datetime.date(2025, 3, 15)),
            revoked_at=utc_at(datetime.date(2025, 4, 2)),
        )

        calendar = annual_contribution_calendar(connection, 2025)

        assert calendar.counts[datetime.date(2025, 3, 10)] == 2
        assert calendar.counts[datetime.date(2025, 3, 11)] == 1
        assert calendar.counts[datetime.date(2025, 3, 12)] == 0
        assert calendar.counts[datetime.date(2025, 3, 13)] == 0
        assert calendar.counts[datetime.date(2025, 3, 14)] == 0
        assert calendar.counts[datetime.date(2025, 3, 15)] == 0
        assert calendar.total == 3
        assert sum(calendar.counts.values()) == calendar.total

    @pytest.mark.parametrize(
        ("year", "expected_days"), [(2025, 365), (2024, 366)], ids=["normal", "leap"]
    )
    def test_covers_every_day_of_the_year(self, year, expected_days):
        """GIT-009: the calendar spans every day of the year, 365 or 366 entries."""
        connection = GithubConnectionFactory(show_annual_calendar=True)

        calendar = annual_contribution_calendar(connection, year)

        assert len(calendar.counts) == expected_days
        assert next(iter(calendar.counts)) == datetime.date(year, 1, 1)
        assert list(calendar.counts)[-1] == datetime.date(year, 12, 31)
        assert calendar.total == 0
        assert calendar.longest_streak == 0
        assert calendar.busiest_month == datetime.date(year, 1, 1)

    def test_streak_and_busiest_month_across_month_and_year_boundaries(self):
        """GIT-009: streaks cross month boundaries; adjacent-year records never leak in."""
        connection = GithubConnectionFactory(show_annual_calendar=True)
        accept(connection.user, day=datetime.date(2023, 12, 30))
        accept(connection.user, day=datetime.date(2025, 1, 2))
        accept(connection.user, day=datetime.date(2024, 2, 27))
        accept(connection.user, day=datetime.date(2024, 2, 28))
        accept(connection.user, day=datetime.date(2024, 2, 29))
        accept(connection.user, day=datetime.date(2024, 3, 1), count=3)
        accept(connection.user, day=datetime.date(2024, 3, 2))

        calendar = annual_contribution_calendar(connection, 2024)

        assert calendar.counts[datetime.date(2024, 2, 27)] == 1
        assert calendar.counts[datetime.date(2024, 2, 28)] == 1
        assert calendar.counts[datetime.date(2024, 2, 29)] == 1
        assert calendar.counts[datetime.date(2024, 3, 1)] == 3
        assert calendar.counts[datetime.date(2024, 3, 2)] == 1
        assert calendar.total == 7
        assert calendar.longest_streak == 5
        assert calendar.busiest_month == datetime.date(2024, 3, 1)

    def test_buckets_days_in_kathmandu_time(self):
        """GIT-009/AGENTS-8: days are bucketed in Asia/Kathmandu, not UTC."""
        connection = GithubConnectionFactory(show_annual_calendar=True)
        accept(connection.user, day=datetime.date(2024, 2, 29), hour=19)

        calendar = annual_contribution_calendar(connection, 2024)

        assert calendar.counts[datetime.date(2024, 2, 29)] == 0
        assert calendar.counts[datetime.date(2024, 3, 1)] == 1
        assert calendar.total == 1
        assert calendar.longest_streak == 1

    def test_builds_from_a_single_query(self, django_assert_num_queries):
        """GIT-009: the calendar year is built from one values query, no N+1."""
        connection = GithubConnectionFactory(show_annual_calendar=True)
        accept(connection.user, day=datetime.date(2024, 2, 27), count=3)
        accept(connection.user, day=datetime.date(2024, 3, 1), count=2)

        with django_assert_num_queries(1):
            annual_contribution_calendar(connection, 2024)


class TestCalendarContext:
    def test_opted_out_connection_gets_no_calendar(self):
        """GIT-009: the calendar is consent-gated; without opt-in nothing is prepared."""
        connection = GithubConnectionFactory(show_annual_calendar=False)
        accept(connection.user, day=datetime.date(2025, 3, 10))

        context = calendar_context(connection.user, 2025)

        assert context["connection"] is None
        assert context["calendar"] is None

    def test_revoked_connection_gets_no_calendar(self):
        """GIT-011/GIT-009: a revoked connection renders the calendar nowhere."""
        connection = GithubConnectionFactory(show_annual_calendar=True, revoked_at=timezone.now())
        accept(connection.user, day=datetime.date(2025, 3, 10))

        context = calendar_context(connection.user, 2025)

        assert context["connection"] is None
        assert context["calendar"] is None

    def test_opted_in_connection_gets_grid_and_totals(self):
        """GIT-009: opted-in members get the year grid, totals and freshness stamp."""
        connection = GithubConnectionFactory(show_annual_calendar=True)
        accept(connection.user, day=datetime.date(2025, 3, 10), count=2)

        context = calendar_context(connection.user, 2025)

        calendar = context["calendar"]
        assert context["connection"] == connection
        assert calendar["year"] == 2025
        assert calendar["total"] == 2
        assert calendar["longest_streak"] == 1
        assert calendar["busiest_month"] == datetime.date(2025, 3, 1)
        assert len(calendar["rows"]) == 7
        assert len(calendar["rows"][0]["cells"]) == 53
        assert calendar["months"][0]["start"] == datetime.date(2025, 1, 1)
        assert calendar["fetched_at"] is not None

    def test_defaults_to_current_year(self):
        """GIT-009: without a year argument the current year is summarized."""
        connection = GithubConnectionFactory(show_annual_calendar=True)

        context = calendar_context(connection.user)

        assert context["calendar"]["year"] == timezone.localdate().year


class TestCalendarTemplate:
    def render_for(self, connection, year):
        return render_to_string(CALENDAR_TEMPLATE, calendar_context(connection.user, year))

    def test_renders_nothing_when_opted_out(self):
        """GIT-009: with consent off the template renders nothing, not an empty block."""
        connection = GithubConnectionFactory(show_annual_calendar=False)
        accept(connection.user, day=datetime.date(2025, 3, 10))

        html = self.render_for(connection, 2025)

        assert html.strip() == ""

    def test_renders_nothing_when_revoked(self):
        """GIT-011/GIT-009: a revoked connection renders nothing even with consent on."""
        connection = GithubConnectionFactory(show_annual_calendar=True, revoked_at=timezone.now())
        accept(connection.user, day=datetime.date(2025, 3, 10))

        html = self.render_for(connection, 2025)

        assert html.strip() == ""

    def test_template_guard_holds_even_with_injected_calendar(self):
        """GIT-009/BR-005: the template re-checks consent and revocation client-side flags."""
        connection = GithubConnectionFactory(show_annual_calendar=True)
        accept(connection.user, day=datetime.date(2025, 3, 10), count=2)
        payload = calendar_context(connection.user, 2025)["calendar"]

        connection.show_annual_calendar = False
        opted_out = render_to_string(
            CALENDAR_TEMPLATE, {"connection": connection, "calendar": payload}
        )
        connection.show_annual_calendar = True
        connection.revoked_at = timezone.now()
        revoked = render_to_string(
            CALENDAR_TEMPLATE, {"connection": connection, "calendar": payload}
        )

        assert opted_out.strip() == ""
        assert revoked.strip() == ""

    def test_renders_verified_record_labels_and_totals(self):
        """GIT-009-U1/BR-005-U1: source, freshness, totals and the separate-measure note."""
        connection = GithubConnectionFactory(show_annual_calendar=True)
        accept(connection.user, day=datetime.date(2024, 2, 27), count=2)
        accept(connection.user, day=datetime.date(2024, 2, 28))
        accept(connection.user, day=datetime.date(2024, 3, 1), count=4)
        accept(connection.user, day=datetime.date(2024, 3, 2), count=2)
        accept(connection.user, day=datetime.date(2024, 3, 3))

        html = self.render_for(connection, 2024)

        assert "DevNepal verified record" in html
        assert "not GitHub" in html
        assert "10 accepted contributions in 2024" in html
        assert "Longest streak 3 days" in html
        assert "Busiest month March" in html
        assert "Generated" in html
        assert "<caption" in html
        assert 'scope="col"' in html
        assert 'scope="row"' in html
        assert "February" in html
        assert "March" in html

    def test_grid_cells_carry_intensity_levels_and_day_labels(self):
        """GIT-009/BR-005: a weeks-by-7 grid with 5 buckets and per-day accessible text."""
        connection = GithubConnectionFactory(show_annual_calendar=True)
        accept(connection.user, day=datetime.date(2024, 3, 1), count=4)

        html = self.render_for(connection, 2024)

        assert html.count("dn-cal-cell is-level-") >= 366
        assert "is-level-4" in html
        assert "is-level-0" in html
        for label in ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"):
            assert f">{label}</th>" in html
        assert 'colspan="5"' in html
        assert "4 accepted contributions" in html
