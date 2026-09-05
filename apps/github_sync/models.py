import typing
import uuid

from django.db import models
from django.utils import timezone

from apps.github_sync.enums import DeliverySource, ProcessingState, Provider, SyncState
from apps.taxonomy.fields import NFCCharField, NFCTextField


class ProviderEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        invalid_fields = set(kwargs) - ProviderEvent.PROCESSING_FIELDS
        if invalid_fields:
            raise PermissionError(
                "ProviderEvent provenance fields are immutable (GIT-012, SEC-008)"
            )
        return super().update(**kwargs)


class ProviderEventManager(models.Manager.from_queryset(ProviderEventQuerySet)):
    pass


class GithubConnection(models.Model):
    """User-level provider connection [AUTH-002, AUTH-008; GIT-002, GIT-009, GIT-011; A3].

    Tokens never live here (data-model §8 secrets rule); only non-secret
    references, scopes and state are stored.
    """

    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="github_connection"
    )
    provider = models.CharField(10, choices=Provider.choices, default=Provider.GITHUB)
    github_user_id = models.BigIntegerField(unique=True)
    login = NFCCharField(100)
    scopes = models.JSONField(default=list)
    connected_at = models.DateTimeField(auto_now_add=True)
    consent_scopes = models.JSONField(default=list)
    consent_recorded_at = models.DateTimeField(default=timezone.now)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    show_annual_calendar = models.BooleanField(default=False)
    calendar_fetched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-connected_at"]

    def __str__(self) -> str:
        return f"{self.user.username} GitHub:{self.login}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class RepositoryConnection(models.Model):
    """Enrolled repository feeding a listed project [GIT-001, GIT-003, GIT-006, GIT-011]."""

    provider = models.CharField(10, choices=Provider.choices, default=Provider.GITHUB)
    installation_id = models.BigIntegerField()
    repository_id = models.BigIntegerField()
    repository_node_id = models.CharField(100, blank=True, default="")
    full_name = NFCCharField(250)
    # Existing connections are deliberately not assumed public. A new
    # enrollment records the App privacy bit before issue metadata can become
    # visible on a project page (GIT-010).
    is_public = models.BooleanField(default=False)
    project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="repository_connections",
    )
    granted_scopes = models.JSONField(default=list)
    sync_state = models.CharField(
        10, choices=SyncState.choices, default=SyncState.IDLE, db_index=True
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_cursor = models.CharField(255, blank=True, default="")
    health_note = NFCTextField(blank=True)
    sync_failure_count = models.PositiveIntegerField(default=0)
    next_sync_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    access_revoked_reason = models.CharField(max_length=40, blank=True, default="")
    task_snapshot_at = models.DateTimeField(null=True, blank=True)
    task_snapshot_note = NFCTextField(blank=True)
    activated_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="activated_repositories",
    )
    deactivated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["full_name"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(
                fields=["provider", "repository_id"], name="uniq_repo_connection"
            ),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["sync_state"], name="idx_repoconn_sync_state"),
            models.Index(fields=["project"], name="idx_repoconn_project"),
            models.Index(
                fields=["provider", "repository_node_id"], name="idx_repoconn_provider_node"
            ),
        ]

    def __str__(self) -> str:
        return self.full_name


class GithubStarterTask(models.Model):
    """Bounded public GitHub issue metadata for a listed project's task hand-off.

    GitHub remains the source of truth. This is a cache of title, number,
    selected labels and an external URL only: never issue bodies, comments, or
    private repository data (GIT-010; DSC-009).
    """

    repository = models.ForeignKey(
        RepositoryConnection, on_delete=models.CASCADE, related_name="starter_tasks"
    )
    github_issue_id = models.BigIntegerField()
    number = models.PositiveIntegerField()
    title = NFCCharField(300)
    url = models.URLField()
    labels = models.JSONField(default=list)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["repository", "number"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(
                fields=["repository", "github_issue_id"], name="uniq_github_starter_issue"
            ),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["repository", "number"], name="idx_startertask_repo_number"),
        ]

    def __str__(self) -> str:
        return f"{self.repository.full_name}#{self.number}: {self.title}"


class ProviderEvent(models.Model):
    """Immutable delivery ledger [GIT-004, GIT-005, GIT-012; A5, A9].

    Only processing fields may update after insert; provenance columns are
    write-once. Payload carries parsed fields only, never raw bodies or tokens
    [GIT-010].
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(10, choices=Provider.choices, default=Provider.GITHUB)
    event_type = models.CharField(100, db_index=True)
    delivery_id = models.CharField(200)
    provider_event_id = models.CharField(200)
    repository = models.ForeignKey(
        RepositoryConnection,
        null=True,
        on_delete=models.SET_NULL,
        related_name="provider_events",
    )
    actor = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="provider_events",
    )
    source = models.CharField(15, choices=DeliverySource.choices, default=DeliverySource.WEBHOOK)
    signature_valid = models.BooleanField(default=False)
    signature_note = models.CharField(50, blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    payload = models.JSONField(null=True, blank=True)
    payload_digest = models.CharField(64, blank=True, default="")
    processing_state = models.CharField(
        12,
        choices=ProcessingState.choices,
        default=ProcessingState.PENDING,
        db_index=True,
    )
    processing_attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    processed_at = models.DateTimeField(null=True, blank=True)
    correlation_id = models.CharField(100, blank=True, default="", db_index=True)

    PROCESSING_FIELDS = frozenset(
        {
            "repository",
            "repository_id",
            "actor",
            "actor_id",
            "processing_state",
            "processing_attempts",
            "last_error",
            "processed_at",
        }
    )
    WRITE_ONCE_FIELDS = frozenset(
        {
            "provider",
            "event_type",
            "delivery_id",
            "provider_event_id",
            "source",
            "signature_valid",
            "signature_note",
            "received_at",
            "payload",
            "payload_digest",
            "correlation_id",
        }
    )

    objects = ProviderEventManager()

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-received_at"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(
                fields=["provider", "delivery_id"], name="uniq_provider_delivery"
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_event_id"], name="uniq_provider_event"
            ),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(
                fields=["processing_state", "received_at"], name="idx_provevent_state_received"
            ),
            models.Index(fields=["repository", "received_at"], name="idx_provevent_repo_received"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_type} {self.provider_event_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            if self.pk != getattr(self, "_persisted_pk", self.pk):
                raise PermissionError(
                    "ProviderEvent provenance fields are immutable (GIT-012, SEC-008)"
                )
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                invalid_fields = set(update_fields) - self.PROCESSING_FIELDS
                if invalid_fields:
                    raise PermissionError(
                        "ProviderEvent provenance fields are immutable (GIT-012, SEC-008)"
                    )
            else:
                persisted = (
                    type(self)
                    ._base_manager.filter(pk=self.pk)
                    .values(*self.WRITE_ONCE_FIELDS)
                    .first()
                )
                if persisted is not None and any(
                    getattr(self, field) != persisted[field] for field in self.WRITE_ONCE_FIELDS
                ):
                    raise PermissionError(
                        "ProviderEvent provenance fields are immutable (GIT-012, SEC-008)"
                    )
        result = super().save(*args, **kwargs)
        self._persisted_pk = self.pk
        return result

    @classmethod
    def from_db(cls, db, field_names, values, *, fetch_mode=None):
        instance = super().from_db(db, field_names, values, fetch_mode=fetch_mode)
        instance._persisted_pk = instance.pk
        return instance
