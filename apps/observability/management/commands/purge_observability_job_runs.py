from django.core.management.base import CommandError

from apps.observability.commands import InstrumentedCommand
from apps.observability.services import purge_job_runs


class Command(InstrumentedCommand):
    help = "NFR-MNT-01: purge expired completed observability job history."

    def add_arguments(self, parser):
        parser.add_argument("--retention-days", type=int)

    def handle(self, *args, **options):
        try:
            deleted = purge_job_runs(retention_days=options["retention_days"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Purged {deleted} expired job run(s)."))
