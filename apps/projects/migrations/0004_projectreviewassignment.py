import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.taxonomy.fields


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0003_communitytermsacceptance"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectReviewAssignment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                ("due_at", models.DateTimeField(db_index=True)),
                ("reviewer_note", apps.taxonomy.fields.NFCTextField(blank=True, default="")),
                ("checklist", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assigned_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="review_assignments_made",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "project",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="review_assignment",
                        to="projects.project",
                    ),
                ),
                (
                    "reviewer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assigned_project_reviews",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="review_assignments",
                        to="projects.projectversion",
                    ),
                ),
            ],
            options={"ordering": ["due_at", "project"]},
        )
    ]
