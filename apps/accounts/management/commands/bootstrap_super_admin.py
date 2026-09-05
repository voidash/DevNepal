import logging
import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.audit.services import record_audit
from apps.taxonomy.fields import normalize_nfc

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "AUTH-003: provision the first Super Admin through a controlled deployment step; "
        "refuses to run once any superuser exists."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            required=True,
            help="Username for the first Super Admin.",
        )
        parser.add_argument(
            "--password",
            default="",
            help="Explicit password for local development only; omit to print a one-time password.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        username = normalize_nfc(str(options["username"]))
        try:
            UnicodeUsernameValidator()(username)
        except ValidationError as exc:
            raise CommandError(f"invalid username: {username!r}") from exc

        if User.objects.filter(is_superuser=True).exists():
            raise CommandError("a superuser already exists; bootstrap is refused (AUTH-003)")

        provided_password = str(options["password"])
        generate_password = not provided_password
        password = provided_password or secrets.token_urlsafe(18)

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email="",
                    password=password,
                    is_staff=True,
                    is_superuser=True,
                )
                record_audit(
                    actor=user,
                    action="auth.super_admin_bootstrap",
                    obj=user,
                    after={"username": username},
                    source="cli",
                )
        except IntegrityError as exc:
            logger.exception("bootstrap_super_admin could not create the first super admin")
            raise CommandError(f"could not create super admin {username!r}") from exc

        self.stdout.write(f"super admin created: {username}")
        if generate_password:
            self.stdout.write(f"generated-password: {password}")
        else:
            self.stdout.write("explicit password applied; rotate it before any shared use")
