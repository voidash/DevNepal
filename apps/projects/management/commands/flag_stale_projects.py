import logging

from django.utils import timezone

from apps.observability.commands import InstrumentedCommand
from apps.projects.enums import ProjectStatus
from apps.projects.models import Project
from apps.projects.services import flag_expired, flag_stale

logger = logging.getLogger(__name__)


class Command(InstrumentedCommand):
    help = (
        "GOV-010/GOV-012/D5: flag expired deadlines and stale maintainer response on live "
        "projects without changing any project status."
    )

    def handle(self, *args, **options):
        now = timezone.now()
        today = timezone.localdate()
        expired = 0
        stale = 0
        live_projects = Project.objects.filter(
            status__in=(ProjectStatus.OPEN_FOR_CONTRIBUTION, ProjectStatus.PAUSED)
        )
        for project in live_projects.iterator():
            try:
                expired += int(flag_expired(project, today=today))
                stale += int(flag_stale(project, now=now))
            except Exception:
                logger.exception(
                    "staleness sweep failed; project=%s status=%s", project.pk, project.status
                )
        self.stdout.write(
            self.style.SUCCESS(
                f"Flagged {expired} expired deadline(s) and {stale} stale project(s)."
            )
        )
