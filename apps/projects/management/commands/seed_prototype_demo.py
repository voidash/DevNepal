from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import MemberProfile, MemberSkill, User
from apps.blogs.enums import BlogModerationState, BlogPostType, BlogStatus
from apps.blogs.models import BlogPost, BlogVersion
from apps.blogs.services import render_safe_markdown
from apps.contributions.enums import ContributionSource, ImpactTier, VerificationStatus
from apps.contributions.models import ContributionRecord
from apps.github_sync.enums import Provider, SyncState
from apps.github_sync.models import GithubStarterTask, RepositoryConnection
from apps.ministries.enums import ContactVerificationStatus, OrgStatus, PublisherStatus
from apps.ministries.models import MinistryOrganization, MinistryPublisher
from apps.projects.enums import (
    ContributionMode,
    DifficultyLevel,
    EffortBand,
    MaintainerRole,
    OwnershipVerificationStatus,
    ProjectStatus,
    ProjectType,
    ResponseSla,
    SignoffModel,
    TaskStatus,
)
from apps.projects.models import Project, ProjectMaintainer, ProjectTask, ProjectVersion
from apps.recognition.enums import AwardStatus, BadgeKind
from apps.recognition.models import Badge, BadgeAward, ContributionScore, ScoringPolicy
from apps.taxonomy.enums import ContentLanguage, TermVocabulary
from apps.taxonomy.models import ApprovedLicense, Skill, TaxonomyTerm


class Command(BaseCommand):
    help = "Seed compact, idempotent prototype demonstration data without login credentials."

    def handle(self, *args, **options):
        with transaction.atomic():
            records = seed_prototype_demo()
        self.stdout.write(
            self.style.SUCCESS(
                "Seeded prototype demo: "
                f"{records['ministries']} ministries, {records['projects']} projects, "
                f"{records['members']} public members."
            )
        )


def seed_prototype_demo() -> dict[str, int]:
    """DSC-001/GOV-004/BLG-004/REC-002: create deterministic prototype demo records."""
    admin = _user(
        "demo-pmo-admin",
        first_name="Bikash",
        last_name="Neupane",
        email="demo-pmo-admin@example.invalid",
        is_superuser=True,
        is_staff=True,
    )
    publisher = _user(
        "demo-doit-publisher",
        first_name="Rajan",
        last_name="Koirala",
        email="demo-doit-publisher@example.invalid",
    )
    sabina = _user(
        "sabina-lamichhane",
        first_name="Sabina",
        last_name="Lamichhane",
        email="sabina-lamichhane@example.invalid",
    )
    kritika = _user(
        "kritika-poudel",
        first_name="Kritika",
        last_name="Poudel",
        email="kritika-poudel@example.invalid",
    )
    rohan = _user(
        "rohan-karki",
        first_name="Rohan",
        last_name="Karki",
        email="rohan-karki@example.invalid",
    )
    aarati = _user(
        "aarati-shrestha",
        first_name="Aarati",
        last_name="Shrestha",
        email="aarati-shrestha@example.invalid",
    )
    bibek = _user(
        "bibek-gurung",
        first_name="Bibek",
        last_name="Gurung",
        email="bibek-gurung@example.invalid",
    )
    sujata = _user(
        "sujata-tamang",
        first_name="Sujata",
        last_name="Tamang",
        email="sujata-tamang@example.invalid",
    )
    prakash = _user(
        "prakash-adhikari",
        first_name="Prakash",
        last_name="Adhikari",
        email="prakash-adhikari@example.invalid",
    )
    nisha = _user(
        "nisha-maharjan",
        first_name="Nisha",
        last_name="Maharjan",
        email="nisha-maharjan@example.invalid",
    )
    address_maintainer = _user(
        "prakash-bhandari",
        first_name="Prakash",
        last_name="Bhandari",
        email="prakash-bhandari@example.invalid",
    )
    health_maintainer = _user(
        "maya-karmacharya",
        first_name="Maya",
        last_name="Karmacharya",
        email="maya-karmacharya@example.invalid",
    )

    _profile(kritika, "Frontend developer", "Hetauda", "Engineering · Localization")
    _profile(rohan, "Civic data · transport and GTFS", "Butwal", "Engineering · Data")
    _profile(
        aarati,
        "Frontend engineer · accessibility and Nepali typography",
        "Lalitpur",
        "Engineering · UI/UX · Localization",
    )
    _profile(bibek, "Backend engineer · Go and PostgreSQL", "Pokhara", "Engineering · QA")
    _profile(
        sujata,
        "Technical writer · API documentation",
        "Lalitpur",
        "Documentation · Localization",
    )
    _profile(prakash, "ML engineer · Devanagari OCR", "Biratnagar", "Engineering · Data")
    _profile(nisha, "Product designer · public-sector forms", "Bhaktapur", "UI/UX · Research")

    doit, _ = MinistryOrganization.objects.get_or_create(
        slug="department-of-information-technology",
        defaults={
            "name_en": "Department of Information Technology",
            "name_ne": "सूचना प्रविधि विभाग",
            "abbreviation": "DoIT",
            "description": "Prototype ministry organization for public digital-service work.",
            "contact_email": "doit-demo@example.invalid",
            "website_url": "https://example.invalid/doit",
            "status": OrgStatus.ACTIVE,
            "provisioned_by": admin,
            "provisioned_at": timezone.now(),
        },
    )
    _dhm, _ = MinistryOrganization.objects.get_or_create(
        slug="department-of-hydrology-and-meteorology",
        defaults={
            "name_en": "Department of Hydrology and Meteorology",
            "name_ne": "जल तथा मौसम विज्ञान विभाग",
            "abbreviation": "DHM",
            "description": "Prototype ministry organization for public hazard-information work.",
            "contact_email": "dhm-demo@example.invalid",
            "website_url": "https://example.invalid/dhm",
            "status": OrgStatus.ACTIVE,
            "provisioned_by": admin,
            "provisioned_at": timezone.now(),
        },
    )
    mofaga, _ = MinistryOrganization.objects.get_or_create(
        slug="ministry-of-federal-affairs-and-general-administration",
        defaults={
            "name_en": "Ministry of Federal Affairs and General Administration",
            "name_ne": "संघीय मामिला तथा सामान्य प्रशासन मन्त्रालय",
            "abbreviation": "MoFAGA",
            "description": "Prototype ministry organization for address-data collaboration.",
            "contact_email": "mofaga-demo@example.invalid",
            "website_url": "https://example.invalid/mofaga",
            "status": OrgStatus.ACTIVE,
            "provisioned_by": admin,
            "provisioned_at": timezone.now(),
        },
    )
    mohp, _ = MinistryOrganization.objects.get_or_create(
        slug="ministry-of-health-and-population",
        defaults={
            "name_en": "Ministry of Health and Population",
            "name_ne": "स्वास्थ्य तथा जनसंख्या मन्त्रालय",
            "abbreviation": "MoHP",
            "description": "Prototype ministry organization for public health API collaboration.",
            "contact_email": "mohp-demo@example.invalid",
            "website_url": "https://example.invalid/mohp",
            "status": OrgStatus.ACTIVE,
            "provisioned_by": admin,
            "provisioned_at": timezone.now(),
        },
    )
    MinistryPublisher.objects.get_or_create(
        user=publisher,
        ministry=doit,
        defaults={
            "title": "Ministry Publisher",
            "official_email": "rajan-demo@example.invalid",
            "status": PublisherStatus.ACTIVE,
            "assigned_by": admin,
            "contact_verification_status": ContactVerificationStatus.VERIFIED,
            "contact_verified_at": timezone.now(),
        },
    )
    MinistryPublisher.objects.get_or_create(
        user=address_maintainer,
        ministry=mofaga,
        defaults={
            "title": "Address Schema Maintainer",
            "official_email": "prakash-bhandari-demo@example.invalid",
            "status": PublisherStatus.ACTIVE,
            "assigned_by": admin,
            "contact_verification_status": ContactVerificationStatus.VERIFIED,
            "contact_verified_at": timezone.now(),
        },
    )
    MinistryPublisher.objects.get_or_create(
        user=health_maintainer,
        ministry=mohp,
        defaults={
            "title": "Health Registry Maintainer",
            "official_email": "maya-karmacharya-demo@example.invalid",
            "status": PublisherStatus.ACTIVE,
            "assigned_by": admin,
            "contact_verification_status": ContactVerificationStatus.VERIFIED,
            "contact_verified_at": timezone.now(),
        },
    )
    MinistryPublisher.objects.get_or_create(
        user=sabina,
        ministry=doit,
        defaults={
            "title": "Accessibility Maintainer",
            "official_email": "sabina-demo@example.invalid",
            "status": PublisherStatus.ACTIVE,
            "assigned_by": admin,
            "contact_verification_status": ContactVerificationStatus.VERIFIED,
            "contact_verified_at": timezone.now(),
        },
    )

    license_obj = _license()
    engineering = _contribution_type("Engineering")
    localization = _contribution_type("Localization")
    documentation = _contribution_type("Documentation")
    skills = _skills("React", "Accessibility Audit", "Translation EN-NE", "PostgreSQL")
    _member_skill(kritika, _skills("Accessibility Audit")[0])
    _member_skill(kritika, _skills("Translation EN-NE")[0])
    _member_skill(rohan, _skills("PostgreSQL")[0])
    _member_skill(aarati, _skills("React")[0])
    _member_skill(bibek, _skills("PostgreSQL")[0])
    _member_skill(sujata, _skills("Technical Writing")[0])
    _member_skill(prakash, _skills("Python")[0])
    _member_skill(nisha, _skills("UI/UX Design")[0])

    sewa = _government_project(
        slug="sewa-portal-accessibility-remediation",
        title_en="Civic Help Directory",
        title_ne="नागरिक सहायता निर्देशिका",
        owner=publisher,
        ministry=doit,
        license_obj=license_obj,
        summary_en=(
            "Discover Government of Nepal public help programmes and improve their bilingual, "
            "accessible programme data in public."
        ),
        summary_ne="नेपाल सरकारका सार्वजनिक सहायता कार्यक्रम खोज्न र तिनको खुला डेटा सुधार्न सहयोग गर्नुहोस्।",
        repository_url="https://github.com/voidash/civic-help-directory",
        issue_tracker_url="https://github.com/voidash/civic-help-directory/issues",
        documentation_url="https://github.com/voidash/civic-help-directory#readme",
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        deadline=date(2026, 11, 30),
    )
    _maintainer(sewa, publisher, MaintainerRole.LEAD)
    _maintainer(sewa, sabina, MaintainerRole.MAINTAINER)
    sewa.contribution_types.set([engineering, localization, documentation])
    sewa.skills.set(skills)
    _task(
        sewa,
        "Add Nepali eligibility text for scholarship programs",
        "Translate the scholarship eligibility guidance while preserving source links.",
        "https://github.com/voidash/civic-help-directory/issues/7",
    )
    _task(
        sewa,
        "Check health subsidy contact details against official sources",
        "Verify public contact information and cite the source used.",
        "https://github.com/voidash/civic-help-directory/issues/8",
    )
    repository, _ = RepositoryConnection.objects.get_or_create(
        provider=Provider.GITHUB,
        repository_id=1_357_413_723,
        defaults={
            "installation_id": 159_188_767,
            "repository_node_id": "R_kgDOUOh9Ww",
            "full_name": "voidash/civic-help-directory",
            "is_public": True,
            "project": sewa,
            "granted_scopes": ["metadata:read", "issues:read"],
            "sync_state": SyncState.IDLE,
            "last_synced_at": timezone.now(),
            "task_snapshot_at": timezone.now(),
            "activated_by": publisher,
        },
    )
    _starter_task(
        repository,
        7,
        "Add Nepali eligibility text for scholarship programs",
        ["good first issue"],
    )
    _starter_task(
        repository,
        8,
        "Check health subsidy contact details against official sources",
        ["help wanted"],
    )
    _starter_task(
        repository,
        9,
        "Document keyboard-first contribution workflow",
        ["good first issue"],
    )

    address_schema = _government_project(
        slug="unified-local-address-schema",
        title_en="Unified Local Address Schema",
        title_ne="एकीकृत स्थानीय ठेगाना ढाँचा",
        owner=address_maintainer,
        ministry=mofaga,
        license_obj=license_obj,
        summary_en=(
            "An open JSON schema and validation library for addresses across all 753 local "
            "levels, wards and tole names."
        ),
        summary_ne="७५३ स्थानीय तह, वडा र टोल नामका लागि खुला JSON schema र validation library।",
        repository_url="",
        issue_tracker_url="",
        documentation_url="",
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
        estimated_effort=EffortBand.SMALL,
        response_sla=ResponseSla.WITHIN_24_HOURS,
    )
    _maintainer(address_schema, address_maintainer, MaintainerRole.LEAD)
    address_schema.contribution_types.set([engineering, documentation])
    address_schema.skills.set(_skills("Python", "Documentation", "Data Analysis"))
    _task(
        address_schema,
        "Document ward and tole name validation",
        "Documentation task for the unified local address schema.",
        "",
    )

    health_registry = _government_project(
        slug="health-facility-registry-api",
        title_en="Health Facility Registry API",
        title_ne="स्वास्थ्य संस्था दर्ता API",
        owner=health_maintainer,
        ministry=mohp,
        license_obj=license_obj,
        summary_en=(
            "Public read API and documentation for the national registry of hospitals, health "
            "posts and birthing centres."
        ),
        summary_ne="अस्पताल, स्वास्थ्य चौकी र प्रसूति केन्द्रको राष्ट्रिय दर्ताका लागि सार्वजनिक API।",
        repository_url="",
        issue_tracker_url="",
        documentation_url="",
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        contribution_mode=ContributionMode.OPEN_DIRECT,
        difficulty=DifficultyLevel.BEGINNER,
        estimated_effort=EffortBand.SMALL,
        response_sla=ResponseSla.WITHIN_24_HOURS,
    )
    _maintainer(health_registry, health_maintainer, MaintainerRole.LEAD)
    health_registry.contribution_types.set([engineering, documentation])
    health_registry.skills.set(_skills("Documentation", "Data Analysis"))
    _task(
        health_registry,
        "Improve the first API contribution guide",
        "Beginner-friendly documentation task for the public health registry API.",
        "",
    )

    sajhabus, sajhabus_created = Project.objects.get_or_create(
        slug="sajhabus-timetable",
        defaults={
            "project_type": ProjectType.PERSONAL,
            "title_en": "SajhaBus Timetable",
            "title_ne": "साझाबस समयतालिका",
            "owner": rohan,
            "summary_en": ("Open GTFS feed for Kathmandu Valley bus routes, maintained by riders."),
            "summary_ne": "यात्रीले मर्मत गर्ने काठमाडौं उपत्यका बस रुटको खुला GTFS feed।",
            "description_md": (
                "Validated with the MobilityData GTFS validator and used by community apps."
            ),
            "repository_url": "https://github.com/rohank/sajhabus-gtfs",
            "documentation_url": "https://example.invalid/sajhabus/docs",
            "contribution_mode": ContributionMode.OPEN_DIRECT,
            "difficulty": DifficultyLevel.BEGINNER,
            "estimated_effort": EffortBand.SMALL,
            "status": ProjectStatus.OPEN_FOR_CONTRIBUTION,
            "published_at": timezone.now(),
            "ownership_verification": OwnershipVerificationStatus.VERIFIED_GITHUB,
        },
    )
    if not sajhabus_created:
        sajhabus.summary_en = (
            "Open GTFS feed for Kathmandu Valley bus routes, maintained by riders."
        )
        sajhabus.summary_ne = "यात्रीले मर्मत गर्ने काठमाडौं उपत्यका बस रुटको खुला GTFS feed।"
        sajhabus.save(update_fields=["summary_en", "summary_ne", "updated_at"])
    sajhabus.skills.set(_skills("Python", "Data Analysis"))
    _community_project(
        slug="nepalidate-js",
        title_en="NepaliDate.js",
        title_ne="नेपाली मिति",
        owner=aarati,
        summary_en=(
            "Bikram Sambat ↔ Gregorian conversion with locale formatting. Used by 40+ "
            "community apps."
        ),
        description_md="Maintainer since 2024. TypeScript · GitHub · npm.",
        verified=True,
        skills=_skills("JavaScript", "PostgreSQL"),
    )
    _community_project(
        slug="bhasha-ocr",
        title_en="Bhasha OCR",
        title_ne="भाषा OCR",
        owner=prakash,
        summary_en="Devanagari OCR fine-tuned on Nepali newsprint and handwritten forms.",
        description_md="Python · PyTorch · GitHub · Demo.",
        verified=True,
        skills=_skills("Python", "Machine Learning"),
    )
    _community_project(
        slug="ropani-square-metre-converter",
        title_en="Ropani ↔ m² Converter",
        title_ne="रोपनी ↔ वर्ग मिटर रूपान्तरण",
        owner=nisha,
        summary_en=(
            "Land-unit conversion (ropani, aana, paisa, dam, bigha, kattha) as a tiny "
            "library and PWA."
        ),
        description_md="JavaScript · GitHub · Demo.",
        verified=False,
        skills=_skills("JavaScript", "UI/UX Design"),
    )

    completed = _government_project(
        slug="sewa-portal-accessibility-completed",
        title_en="Sewa Portal Accessibility Completion",
        title_ne="सेवा पोर्टल पहुँचयोग्यता सम्पन्न",
        owner=publisher,
        ministry=doit,
        license_obj=license_obj,
        summary_en="A completed public accessibility delivery record.",
        summary_ne="सम्पन्न सार्वजनिक पहुँचयोग्यता वितरण अभिलेख।",
        repository_url="https://github.com/doit-np/sewa-portal",
        issue_tracker_url="https://github.com/doit-np/sewa-portal/issues",
        documentation_url="https://github.com/doit-np/sewa-portal#readme",
        status=ProjectStatus.COMPLETED,
        completion=True,
    )
    _maintainer(completed, publisher, MaintainerRole.LEAD)
    completed.contribution_types.set([engineering, localization, documentation])

    first = _contribution(
        sewa,
        kritika,
        localization,
        publisher,
        "Nepali error-message labels",
        "Verified localization evidence for bilingual error recovery.",
        "https://github.com/doit-np/sewa-portal/pull/131",
    )
    second = _contribution(
        completed,
        aarati,
        engineering,
        publisher,
        "Keyboard navigation remediation",
        "Verified engineering work for keyboard operation across high-traffic forms.",
        "https://github.com/doit-np/sewa-portal/pull/128",
    )

    _blogs(aarati, rohan)
    policy = _policy(admin)
    code_shipper = _badge("code-shipper", "Code Shipper", "Verified code contribution")
    _badge("heard-bug-hunter", "Heard Bug Hunter", "Verified quality contribution")
    _award(code_shipper, kritika, first, admin)
    _award(code_shipper, aarati, second, admin)
    _score(first, policy, 8)
    _score(second, policy, 16)

    return {"ministries": 4, "projects": 8, "members": 7}


def _user(username, **defaults):
    user, created = User.objects.get_or_create(username=username, defaults=defaults)
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def _profile(user, headline, location, preferences):
    return MemberProfile.objects.update_or_create(
        user=user,
        defaults={
            "headline": headline,
            "bio": f"Prototype demo profile for {user.get_full_name()}.",
            "location": location,
            "contribution_preferences": preferences,
            "preferred_language": ContentLanguage.ENGLISH,
            "field_visibility": {"location": "public", "skills": "public", "links": "public"},
            "directory_discoverable": True,
        },
    )[0]


def _license():
    license_obj = ApprovedLicense.objects.filter(spdx_id="Apache-2.0", is_approved=True).first()
    if license_obj is None:
        raise CommandError("The approved Apache-2.0 taxonomy record is required before seeding.")
    return license_obj


def _contribution_type(label):
    term = TaxonomyTerm.objects.filter(
        vocabulary=TermVocabulary.CONTRIBUTION_TYPE, label=label, is_active=True
    ).first()
    if term is None:
        raise CommandError(f"The active contribution type {label!r} is required before seeding.")
    return term


def _skills(*names):
    skills = list(Skill.objects.filter(name__in=names, is_active=True))
    if len(skills) != len(names):
        raise CommandError("The starter skill taxonomy is required before seeding.")
    return skills


def _member_skill(user, skill):
    return MemberSkill.objects.get_or_create(
        user=user,
        skill=skill,
        defaults={"self_rating": "intermediate"},
    )[0]


def _government_project(
    *,
    slug,
    title_en,
    title_ne,
    owner,
    ministry,
    license_obj,
    summary_en,
    summary_ne,
    repository_url,
    issue_tracker_url,
    documentation_url,
    status,
    deadline=None,
    completion=False,
    contribution_mode=ContributionMode.APPLICATION,
    difficulty=DifficultyLevel.INTERMEDIATE,
    estimated_effort=EffortBand.MEDIUM,
    response_sla=ResponseSla.WITHIN_3_DAYS,
):
    defaults = {
        "project_type": ProjectType.GOVERNMENT,
        "title_en": title_en,
        "title_ne": title_ne,
        "owner": owner,
        "ministry": ministry,
        "license": license_obj,
        "summary_en": summary_en,
        "summary_ne": summary_ne,
        "description_md": summary_en,
        "problem_statement": "Citizen-facing forms need accessible bilingual error recovery.",
        "target_users": "Citizens, ward-office staff, and people using assistive technology.",
        "expected_outcome": "WCAG 2.2 AA conformance for high-traffic services.",
        "success_indicators": "No critical accessibility issues on the priority service forms.",
        "difficulty": difficulty,
        "estimated_effort": estimated_effort,
        "contributor_capacity": 12,
        "contribution_mode": contribution_mode,
        "prerequisites": "React, WCAG basics, and Nepali reading are helpful.",
        "communication_channel": "https://github.com/doit-np/sewa-portal/discussions",
        "response_sla": response_sla,
        "repository_url": repository_url,
        "default_branch": "main",
        "issue_tracker_url": issue_tracker_url,
        "documentation_url": documentation_url,
        "code_of_conduct_url": "https://example.invalid/code-of-conduct",
        "governance_model": "maintainer_consensus",
        "outcome_ownership": "Department of Information Technology",
        "escalation_path": "Named project maintainers, then the ministry publisher.",
        "completion_criteria": (
            "Accessibility audit, bilingual recovery, and release notes are published."
        ),
        "signoff_model": SignoffModel.DCO,
        "third_party_rights_confirmed": True,
        "data_classification": "public",
        "security_contact": "security-demo@example.invalid",
        "vulnerability_disclosure_url": "https://example.invalid/security",
        "prohibited_data_statement": "Do not submit personal or production data.",
        "status": status,
        "status_changed_at": timezone.now(),
        "published_at": timezone.now(),
        "deadline": deadline,
        "last_maintainer_activity_at": timezone.now(),
    }
    if completion:
        defaults.update(
            {
                "outcome_summary": (
                    "Fourteen high-traffic services now meet WCAG 2.2 AA for keyboard operation, "
                    "Nepali labels, and bilingual error recovery."
                ),
                "deliverables": [
                    {
                        "label": "sewa-portal v4.2 release notes",
                        "url": "https://github.com/doit-np/sewa-portal/releases/tag/v4.2",
                    },
                    {
                        "label": "Accessibility audit report v3",
                        "url": "https://example.invalid/audit-v3",
                    },
                ],
                "impact_summary": (
                    "An estimated 1.1 million monthly requests are more usable with "
                    "assistive technology."
                ),
                "lessons_learned": (
                    "A shared Nepali aria-label glossary and non-code QA evidence should begin "
                    "earlier."
                ),
            }
        )
    project, created = Project.objects.get_or_create(slug=slug, defaults=defaults)
    if not created:
        for field, value in defaults.items():
            setattr(project, field, value)
        project.save(update_fields=[*defaults, "updated_at"])
    if created or project.current_version_id is None:
        version = ProjectVersion.objects.create(
            project=project,
            version_number=1,
            snapshot={"title_en": project.title_en, "status": project.status},
            submitted_by=owner,
            published_at=timezone.now(),
            published_by=owner,
        )
        project.current_version = version
        project.save(update_fields=["current_version"])
    return project


def _community_project(
    *, slug, title_en, title_ne, owner, summary_en, description_md, verified, skills
):
    project, created = Project.objects.get_or_create(
        slug=slug,
        defaults={
            "project_type": ProjectType.PERSONAL,
            "title_en": title_en,
            "title_ne": title_ne,
            "owner": owner,
            "summary_en": summary_en,
            "description_md": description_md,
            "contribution_mode": ContributionMode.OPEN_DIRECT,
            "difficulty": DifficultyLevel.BEGINNER,
            "estimated_effort": EffortBand.SMALL,
            "status": ProjectStatus.OPEN_FOR_CONTRIBUTION,
            "published_at": timezone.now(),
            "ownership_verification": (
                OwnershipVerificationStatus.VERIFIED_GITHUB
                if verified
                else OwnershipVerificationStatus.UNVERIFIED
            ),
        },
    )
    if not created:
        project.project_type = ProjectType.PERSONAL
        project.title_en = title_en
        project.title_ne = title_ne
        project.owner = owner
        project.summary_en = summary_en
        project.description_md = description_md
        project.contribution_mode = ContributionMode.OPEN_DIRECT
        project.difficulty = DifficultyLevel.BEGINNER
        project.estimated_effort = EffortBand.SMALL
        project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
        project.ownership_verification = (
            OwnershipVerificationStatus.VERIFIED_GITHUB
            if verified
            else OwnershipVerificationStatus.UNVERIFIED
        )
        project.save(
            update_fields=[
                "project_type",
                "title_en",
                "title_ne",
                "owner",
                "summary_en",
                "description_md",
                "contribution_mode",
                "difficulty",
                "estimated_effort",
                "status",
                "ownership_verification",
                "updated_at",
            ]
        )
    project.skills.set(skills)
    return project


def _maintainer(project, user, role):
    return ProjectMaintainer.objects.get_or_create(
        project=project,
        user=user,
        defaults={"role": role, "can_review_merge": True},
    )[0]


def _task(project, title, description, issue_url):
    return ProjectTask.objects.get_or_create(
        project=project,
        title=title,
        defaults={
            "description": description,
            "is_starter": True,
            "issue_url": issue_url,
            "status": TaskStatus.OPEN,
        },
    )[0]


def _starter_task(repository, number, title, labels):
    return GithubStarterTask.objects.get_or_create(
        repository=repository,
        github_issue_id=number,
        defaults={
            "number": number,
            "title": title,
            "url": f"https://github.com/{repository.full_name}/issues/{number}",
            "labels": labels,
            "source_updated_at": timezone.now(),
        },
    )[0]


def _contribution(
    project, contributor, contribution_type, verifier, title, description, evidence_url
):
    return ContributionRecord.objects.get_or_create(
        project=project,
        contributor=contributor,
        title=title,
        defaults={
            "contribution_type": contribution_type,
            "description": description,
            "evidence_url": evidence_url,
            "source": ContributionSource.MAINTAINER_ATTESTATION,
            "status": VerificationStatus.ACCEPTED,
            "impact_tier": ImpactTier.STANDARD,
            "verified_by": verifier,
            "verified_at": timezone.now(),
            "verification_note": "Accepted prototype demonstration contribution.",
        },
    )[0]


def _blogs(aarati, rohan):
    markdown = (
        "# Why this is hard\n\nBikram Sambat needs a maintained calendar table, "
        "not Gregorian arithmetic."
    )
    native, created = BlogPost.objects.get_or_create(
        author=aarati,
        title="Handling Bikram Sambat dates in PostgreSQL without losing your mind",
        defaults={
            "excerpt": "A calendar table, conversion lookup, and tests for NepaliDate.js.",
            "post_type": BlogPostType.NATIVE,
            "content_markdown": markdown,
            "content_rendered": render_safe_markdown(markdown),
            "language": ContentLanguage.ENGLISH,
            "reading_time_minutes": 9,
            "status": BlogStatus.PUBLISHED,
            "moderation_state": BlogModerationState.NOT_REVIEWED,
            "published_at": timezone.now(),
        },
    )
    if created:
        BlogVersion.objects.get_or_create(
            post=native,
            version_number=1,
            defaults={"snapshot": {"title": native.title}, "created_by": aarati},
        )
    external, created = BlogPost.objects.get_or_create(
        author=rohan,
        title="Publishing GTFS rider reports for SajhaBus",
        defaults={
            "excerpt": "An external write-up about validating community transit data.",
            "post_type": BlogPostType.EXTERNAL,
            "canonical_url": "https://medium.com/@rohank/sajhabus-gtfs-demo",
            "language": ContentLanguage.ENGLISH,
            "reading_time_minutes": 6,
            "status": BlogStatus.PUBLISHED,
            "moderation_state": BlogModerationState.NOT_REVIEWED,
            "published_at": timezone.now(),
        },
    )
    if created:
        BlogVersion.objects.get_or_create(
            post=external,
            version_number=1,
            defaults={"snapshot": {"title": external.title}, "created_by": rohan},
        )


def _policy(admin):
    policy = ScoringPolicy.objects.filter(is_active=True).first()
    if policy is not None:
        return policy
    latest_version = (
        ScoringPolicy.objects.order_by("-version").values_list("version", flat=True).first()
    )
    version = (latest_version or 0) + 1
    return ScoringPolicy.objects.create(
        version=version,
        rules={
            "minor": 2,
            "standard": 8,
            "major": 16,
            "default": 4,
            "badges": {"code-shipper": {"minimum_points": 8}},
            "anomaly_review": {"velocity_threshold": 20, "duplicate_threshold": 2},
        },
        document_url="https://example.invalid/scoring-policy",
        approved_by=admin,
        activated_at=timezone.now(),
        is_active=True,
    )


def _badge(slug, name, description):
    return Badge.objects.get_or_create(
        slug=slug,
        defaults={
            "name": name,
            "description": description,
            "criteria_md": description,
            "kind": BadgeKind.CONTRIBUTION,
            "is_active": True,
        },
    )[0]


def _award(badge, recipient, contribution, issuer):
    return BadgeAward.objects.get_or_create(
        badge=badge,
        recipient=recipient,
        status=AwardStatus.ACTIVE,
        defaults={"contribution": contribution, "issuer": issuer},
    )[0]


def _score(contribution, policy, points):
    return ContributionScore.objects.get_or_create(
        contribution=contribution,
        defaults={"policy": policy, "points": points},
    )[0]
