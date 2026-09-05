from django.db import migrations
from django.utils.text import slugify

SEEDED_SKILLS = [
    "Python",
    "Django",
    "JavaScript",
    "React",
    "UI/UX Design",
    "Technical Writing",
    "QA/Testing",
    "Security Review",
    "Data Analysis",
    "Translation EN-NE",
    "DevOps",
    "PostgreSQL",
    "Android",
    "iOS",
    "Machine Learning",
    "Accessibility Audit",
    "Project Management",
    "Research",
    "Documentation",
    "Graphic Design",
]

SEEDED_CONTRIBUTION_TYPES = [
    "Engineering",
    "UI/UX",
    "QA",
    "Security",
    "Data",
    "Documentation",
    "Localization",
    "Research",
    "Community support",
]

SEEDED_LICENSES = [
    ("MIT", "MIT License"),
    ("Apache-2.0", "Apache License 2.0"),
    ("BSD-3-Clause", "BSD 3-Clause 'New' or 'Revised' License"),
    ("GPL-3.0-or-later", "GNU General Public License v3.0 or later"),
    ("AGPL-3.0-or-later", "GNU Affero General Public License v3.0 or later"),
    ("CC-BY-4.0", "Creative Commons Attribution 4.0 International"),
]


def seed(apps, schema_editor):
    Skill = apps.get_model("taxonomy", "Skill")
    TaxonomyTerm = apps.get_model("taxonomy", "TaxonomyTerm")
    ApprovedLicense = apps.get_model("taxonomy", "ApprovedLicense")

    for name in SEEDED_SKILLS:
        Skill.objects.update_or_create(
            name=name,
            defaults={"slug": slugify(name, allow_unicode=True), "is_active": True},
        )
    for order, label in enumerate(SEEDED_CONTRIBUTION_TYPES):
        TaxonomyTerm.objects.update_or_create(
            vocabulary="contribution_type",
            label=label,
            defaults={"slug": slugify(label, allow_unicode=True), "sort_order": order, "is_active": True},
        )
    for spdx_id, name in SEEDED_LICENSES:
        ApprovedLicense.objects.update_or_create(
            spdx_id=spdx_id,
            defaults={
                "name": name,
                "reference_url": f"https://spdx.org/licenses/{spdx_id}.html",
                "is_approved": True,
                "is_default": False,
            },
        )


def unseed(apps, schema_editor):
    Skill = apps.get_model("taxonomy", "Skill")
    TaxonomyTerm = apps.get_model("taxonomy", "TaxonomyTerm")
    ApprovedLicense = apps.get_model("taxonomy", "ApprovedLicense")

    Skill.objects.filter(name__in=SEEDED_SKILLS).delete()
    TaxonomyTerm.objects.filter(
        vocabulary="contribution_type", label__in=SEEDED_CONTRIBUTION_TYPES
    ).delete()
    ApprovedLicense.objects.filter(spdx_id__in=[spdx_id for spdx_id, _ in SEEDED_LICENSES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("taxonomy", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
