from urllib.parse import urlsplit

from django.db import migrations, models


def backfill_onboarding_identity(apps, schema_editor):
    request_model = apps.get_model("ministries", "MinistryOnboardingRequest")
    for request in request_model.objects.all().iterator():
        host = (urlsplit(request.website_url).hostname or "").lower()
        domain = host.removeprefix("www.")
        evidence = {
            "reference": request.nomination_reference,
            "signatory_name": request.signatory_name,
            "focal_contact": request.focal_contact,
        }
        request_model.objects.filter(pk=request.pk).update(
            official_domain=domain,
            nomination_evidence=evidence,
        )


class Migration(migrations.Migration):
    dependencies = [("ministries", "0004_ministryonboardingrequest")]

    operations = [
        migrations.AddField(
            model_name="ministryonboardingrequest",
            name="official_domain",
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=253),
        ),
        migrations.AddField(
            model_name="ministryonboardingrequest",
            name="nomination_evidence",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="ministryonboardingrequest",
            name="pmo_attested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_onboarding_identity, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="ministryonboardingrequest",
            name="official_domain",
            field=models.CharField(db_index=True, editable=False, max_length=253),
        ),
        migrations.AddConstraint(
            model_name="ministryonboardingrequest",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="new"),
                fields=("official_domain",),
                name="uniq_open_onboarding_domain",
            ),
        ),
    ]
