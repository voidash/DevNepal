from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("github_sync", "0002_repository_task_snapshot_and_starter_tasks")]

    operations = [
        migrations.AddField(
            model_name="repositoryconnection",
            name="access_revoked_reason",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="repositoryconnection",
            name="next_sync_attempt_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="repositoryconnection",
            name="sync_failure_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
