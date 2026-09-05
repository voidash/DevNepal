from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import (
    AuditBulkMutationError,
    bulk_update_guard,
    record_audit,
)
from apps.audit.tests.factories import AuditEventFactory, UserFactory


def _event_at(moment, **kwargs):
    with mock.patch("django.utils.timezone.now", return_value=moment):
        return AuditEventFactory(**kwargs)


@pytest.mark.django_db
@pytest.mark.unit
def test_adm008_u1_update_via_save_raises_permission_error():
    """ADM-008-U1: re-saving an existing AuditEvent is denied (PermissionError), row unchanged."""
    event = AuditEventFactory(action="project.publish")
    event.action = "tampered"
    with pytest.raises(PermissionError, match="immutable"):
        event.save()
    event.refresh_from_db()
    assert event.action == "project.publish"


@pytest.mark.django_db
@pytest.mark.unit
def test_adm008_u1_instance_delete_raises_permission_error():
    """ADM-008-U1: deleting a single AuditEvent row is denied (PermissionError), row retained."""
    event = AuditEventFactory()
    with pytest.raises(PermissionError, match="cannot be deleted"):
        event.delete()
    assert AuditEvent.objects.filter(pk=event.pk).exists()


@pytest.mark.django_db
@pytest.mark.unit
def test_adm008_u1_queryset_update_bypasses_model_guard():
    """ADM-008-U1: queryset .update() bypasses the model save() guard — documented ORM-level gap."""
    event = AuditEventFactory(action="project.publish")
    AuditEvent.objects.filter(pk=event.pk).update(action="tampered")
    event.refresh_from_db()
    assert event.action == "tampered"


@pytest.mark.django_db
@pytest.mark.unit
def test_adm008_u1_queryset_delete_bypasses_model_guard():
    """ADM-008-U1: queryset .delete() bypasses the model guard — documented ORM-level gap."""
    event = AuditEventFactory()
    AuditEvent.objects.filter(pk=event.pk).delete()
    assert not AuditEvent.objects.filter(pk=event.pk).exists()


@pytest.mark.django_db
@pytest.mark.unit
def test_adm008_u1_bulk_update_guard_blocks_queryset_update():
    """ADM-008-U1: bulk_update_guard() blocks queryset .update() on AuditEvent rows."""
    assert issubclass(AuditBulkMutationError, PermissionError)
    AuditEventFactory()
    with bulk_update_guard():
        with pytest.raises(AuditBulkMutationError, match="ADM-008"):
            AuditEvent.objects.update(action="tampered")


@pytest.mark.django_db
@pytest.mark.unit
def test_adm008_u1_bulk_update_guard_blocks_queryset_delete():
    """ADM-008-U1: bulk_update_guard() blocks queryset .delete() on AuditEvent."""
    AuditEventFactory()
    with bulk_update_guard():
        with pytest.raises(AuditBulkMutationError, match="ADM-008"):
            AuditEvent.objects.all().delete()
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.unit
def test_adm008_u1_bulk_update_guard_blocks_queryset_bulk_update():
    """ADM-008-U1: bulk_update_guard() blocks queryset .bulk_update() on AuditEvent."""
    event = AuditEventFactory(action="project.publish")
    event.action = "tampered"
    with bulk_update_guard():
        with pytest.raises(AuditBulkMutationError, match="ADM-008"):
            AuditEvent.objects.bulk_update([event], ["action"])
    event.refresh_from_db()
    assert event.action == "project.publish"


@pytest.mark.django_db
@pytest.mark.unit
def test_adm008_u1_guard_keeps_append_path_open():
    """SEC-008: inside bulk_update_guard(), record_audit() still appends new rows."""
    actor = UserFactory()
    with bulk_update_guard():
        event = record_audit(actor=actor, action="project.publish", obj=actor)
    assert AuditEvent.objects.filter(pk=event.pk).exists()


@pytest.mark.django_db
@pytest.mark.unit
def test_adm008_u1_guard_restores_default_manager_on_exit():
    """ADM-008-U1: bulk_update_guard() restores the original manager on exit (also on exception)."""
    original = AuditEvent.objects
    with bulk_update_guard():
        assert AuditEvent.objects is not original
    assert AuditEvent.objects is original
    with pytest.raises(RuntimeError):
        with bulk_update_guard():
            raise RuntimeError("boom")
    assert AuditEvent.objects is original


@pytest.mark.django_db
@pytest.mark.unit
def test_adm008_u2_superuser_delete_denied_and_audited():
    """ADM-008-U2: a Super Admin delete attempt is denied and the denial itself is audited."""
    superadmin = UserFactory(is_superuser=True, is_staff=True)
    event = AuditEventFactory(actor=superadmin, action="role.grant.super_admin")
    with pytest.raises(PermissionError):
        event.delete()
    denial = record_audit(
        actor=superadmin,
        action="audit.delete.denied",
        obj=event,
        result="denied",
        correlation_id="corr-adm008",
    )
    assert AuditEvent.objects.filter(pk=denial.pk, actor=superadmin, result="denied").exists()


@pytest.mark.django_db
@pytest.mark.unit
def test_sec008_u1_record_audit_captures_full_context():
    """SEC-008-U1: record_audit stores actor, action, object, result and correlation ID."""
    actor = UserFactory()
    event = record_audit(
        actor=actor,
        action="project.publish",
        obj=actor,
        before={"status": "in_review"},
        after={"status": "published"},
        correlation_id="corr-sec008",
    )
    assert isinstance(event, AuditEvent)
    assert event.pk
    assert event.actor == actor
    assert event.action == "project.publish"
    assert event.content_type == ContentType.objects.get_for_model(actor)
    assert event.object_id == str(actor.pk)
    assert event.source == "web"
    assert event.result == "success"
    assert event.correlation_id == "corr-sec008"
    assert event.created_at is not None


@pytest.mark.django_db
@pytest.mark.unit
def test_sec008_u1_record_audit_without_object():
    """SEC-008-U1: record_audit without obj leaves content_type null and object_id empty."""
    event = record_audit(actor=UserFactory(), action="system.maintenance")
    assert event.content_type is None
    assert event.object_id == ""


@pytest.mark.django_db
@pytest.mark.unit
def test_sec008_u1_record_audit_anonymous_actor():
    """SEC-008-U1: record_audit accepts an anonymous None actor (system/anonymous events)."""
    event = record_audit(actor=None, action="system.bootstrap", correlation_id="corr-sys")
    assert event.actor is None
    assert AuditEvent.objects.filter(pk=event.pk, actor__isnull=True).exists()


@pytest.mark.django_db
@pytest.mark.unit
def test_sec008_u2_failed_attempt_is_auditable():
    """SEC-008-U2: failed authorization attempts are audited via result='failure'."""
    member = UserFactory()
    event = record_audit(
        actor=member,
        action="authz.denied",
        obj=member,
        result="failure",
        correlation_id="corr-sec008u2",
    )
    assert AuditEvent.objects.filter(pk=event.pk, result="failure").exists()


@pytest.mark.django_db
@pytest.mark.unit
def test_gov005_review_mirror_records_before_after_versions():
    """GOV-005: review actions mirror before/after version snapshots into the audit trail."""
    event = record_audit(
        actor=UserFactory(),
        action="project.review.approve",
        before={"version": 2, "status": "in_review"},
        after={"version": 3, "status": "approved"},
        correlation_id="corr-gov005",
    )
    stored = AuditEvent.objects.get(pk=event.pk)
    assert stored.before == {"version": 2, "status": "in_review"}
    assert stored.after == {"version": 3, "status": "approved"}


@pytest.mark.django_db
@pytest.mark.unit
def test_auth003_partial_super_admin_grant_is_audited():
    """AUTH-003: a Super Admin grant writes an audit event attributable to the named actor."""
    granter = UserFactory(is_superuser=True, is_staff=True)
    grantee = UserFactory()
    event = record_audit(
        actor=granter,
        action="role.grant.super_admin",
        obj=grantee,
        before={"is_superuser": False},
        after={"is_superuser": True},
        correlation_id="corr-auth003",
    )
    assert event.actor == granter
    assert event.object_id == str(grantee.pk)


@pytest.mark.django_db
@pytest.mark.unit
def test_sec008_audit_trail_orders_newest_first():
    """SEC-008: the audit trail is queryable newest-first (§9.1 audit event timestamp)."""
    start = timezone.now()
    _event_at(start, action="audit.oldest")
    _event_at(start + timedelta(seconds=10), action="audit.middle")
    _event_at(start + timedelta(seconds=20), action="audit.newest")
    assert list(AuditEvent.objects.values_list("action", flat=True)) == [
        "audit.newest",
        "audit.middle",
        "audit.oldest",
    ]


@pytest.mark.django_db
@pytest.mark.unit
def test_sec008_query_indexes_present():
    """SEC-008: lookup indexes exist on the audit table (object trail, action/time, correlation)."""
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, AuditEvent._meta.db_table)
    indexed = {tuple(info["columns"]) for info in constraints.values() if info.get("index")}
    assert {
        ("content_type_id", "object_id"),
        ("action", "created_at"),
        ("correlation_id",),
    } <= indexed
