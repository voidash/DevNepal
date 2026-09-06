import re
from pathlib import Path

import pytest
from django.conf import settings


@pytest.mark.unit
def test_high_traffic_templates_use_shared_component_contracts():
    """A8/NFR-A11Y-01: shared components make catalog and account UI accessible.

    Legacy classes are banned as exact class tokens: the design-system's own
    dn-project-grid / dn-form-stack must not trip the substring check.
    """
    root = Path(settings.BASE_DIR)
    templates = (
        root / "apps/projects/templates/projects/project_list.html",
        root / "apps/projects/templates/projects/project_detail.html",
        root / "apps/projects/templates/projects/application_list.html",
        root / "apps/projects/templates/projects/application_detail.html",
        root / "apps/projects/templates/projects/application_timeline.html",
        root / "apps/accounts/templates/accounts/login.html",
        root / "apps/accounts/templates/accounts/profile_edit.html",
        root / "apps/accounts/templates/accounts/dashboard.html",
        root / "apps/accounts/templates/accounts/session_list.html",
        root / "apps/accounts/templates/accounts/public_profile.html",
        root / "apps/accounts/templates/accounts/profile_preview.html",
        root / "apps/accounts/templates/accounts/mfa_setup.html",
    )
    legacy_classes = (
        "page-section",
        "section-heading",
        "filter-bar",
        "results-count",
        "project-grid",
        "project-card",
        "status-badge",
        "project-detail",
        "form-stack",
        "form-error",
        "form-actions",
        "auth-panel",
        "empty-state",
        "pattern-grid",
        "pattern-dots",
        "pattern-diagonal",
        "pattern-noise",
    )

    for template in templates:
        content = template.read_text()
        class_tokens = {
            token for match in re.findall(r'class="([^"]*)"', content) for token in match.split()
        }
        assert not (class_tokens & set(legacy_classes)), template


@pytest.mark.unit
def test_base_shell_uses_the_prototype_navigation_and_design_tokens():
    """DSC-001/NFR-A11Y-01: the shared shell presents trusted public navigation.

    The product header stays light while the government identity and legal bands
    use the deeper accessible step of the same platform-blue palette.
    """
    root = Path(settings.BASE_DIR)
    base = (root / "templates/base.html").read_text()
    devnepal_css = (root / "static/src/devnepal.css").read_text()
    tokens_css = (root / "static/src/tokens.css").read_text()

    assert "href=\"{% static 'vendor/primer/primer.css' %}\"" in base
    assert "href=\"{% static 'src/devnepal.css' %}?v=20260906n\"" in base
    assert "href=\"{% static 'images/devnepal-mark.svg' %}\"" in base
    assert 'class="btn dn-skip-link" href="#main-content"' in base
    assert "नेपाल सरकार · Government of Nepal" in base
    assert 'class="dn-product-header"' in base
    assert 'class="dn-brand-mark"' not in base
    assert ".dn-brand:hover," in devnepal_css
    assert ".dn-brand:focus:not(:focus-visible)," in devnepal_css
    assert ".dn-brand:active { border: 0; outline: 0; }" in devnepal_css
    assert "color: var(--color-accent-700); text-decoration: none;" in devnepal_css
    assert "color: var(--color-text); text-decoration: none;" in devnepal_css
    assert (
        '.dn-primary-nav a[aria-current="page"] { color: var(--color-accent-700); '
        "text-decoration: none; }"
    ) in devnepal_css
    assert 'class="dn-header-search" role="search"' not in base
    assert 'class="lang-switch"' in base
    assert "dn-state-banner" in base and "is-success" in base and "is-danger" in base
    assert "--color-bg: #f2f5f7;" in tokens_css
    assert "--color-surface: #e5e9ee;" in tokens_css
    assert "--color-text: #181c20;" in tokens_css
    assert "--color-accent: #5395fc;" in tokens_css
    assert '--font-heading: "Inter"' in tokens_css
    assert '"Noto Sans Devanagari"' in tokens_css
    assert "background: var(--color-bg);" in devnepal_css
    assert "border-radius: 0;" in devnepal_css
    assert "body { min-width: 320px" in devnepal_css
    assert "--devnepal-header-bg" not in devnepal_css
    for banned in ("linear-gradient(", "radial-gradient(", "backdrop-filter:"):
        assert banned not in devnepal_css


@pytest.mark.unit
def test_shared_navigation_keeps_the_compact_menu_through_tablet_widths():
    """A8/NFR-A11Y-01: navigation avoids overflow before the wide desktop breakpoint."""
    css = (Path(settings.BASE_DIR) / "static/src/devnepal.css").read_text()

    assert "@media (max-width: 1179px)" in css
    assert "@media (min-width: 1180px)" in css


@pytest.mark.unit
def test_home_audience_cards_keep_complete_borders_at_every_width():
    """DSC-001/NFR-A11Y-01: audience cards share one complete neutral treatment."""
    css = (Path(settings.BASE_DIR) / "static/src/devnepal.css").read_text()
    home = (Path(settings.BASE_DIR) / "apps/projects/templates/projects/home.html").read_text()

    assert ".dn-get-started-grid article + article { border-left: 0;" not in css
    assert ".dn-get-started-grid article + article { border-top: 0;" not in css
    assert "dn-get-started-ministry" not in css
    assert "dn-get-started-ministry" not in home


@pytest.mark.unit
def test_shared_shell_loads_one_coherent_design_system_after_primer():
    """NFR-A11Y-01/DSC-001: shared styles have a predictable, accessible cascade."""
    base = (Path(settings.BASE_DIR) / "templates/base.html").read_text()
    stylesheets = re.findall(r"href=\"\{% static '([^']+\.css)' %\}(?:\?[^\"]+)?\"", base)

    assert stylesheets == [
        "vendor/primer/primer.css",
        "src/tokens.css",
        "src/base.css",
        "src/components.css",
        "src/devnepal.css",
        "src/onboarding.css",
        "src/public-discovery.css",
    ]


@pytest.mark.unit
def test_status_and_form_contracts_preserve_textual_state_and_error_association():
    """A8/NFR-A11Y-01: states and validation errors have programmatic text."""
    root = Path(settings.BASE_DIR)
    catalog = (root / "apps/projects/templates/projects/project_list.html").read_text()
    detail = (root / "apps/projects/templates/projects/project_detail.html").read_text()
    octicon = (root / "templates/components/status_octicon.html").read_text()
    login = (root / "apps/accounts/templates/accounts/login.html").read_text()
    profile_edit = (root / "apps/accounts/templates/accounts/profile_edit.html").read_text()

    assert 'class="dn-catalog-results' in catalog
    assert '<article class="card blueprint">' in catalog
    assert '{% include "components/status_octicon.html"' in catalog
    assert "{{ project.get_status_display }}" in catalog
    assert "dn-state-banner is-danger" in login
    assert "dn-state-banner is-danger" in profile_edit
    assert 'role="alert"' in login
    assert 'aria-describedby="{{ form.username.id_for_label }}_error"' in login
    assert 'aria-describedby="{{ form.password.id_for_label }}_error"' in login

    for status in (
        "draft",
        "in_review",
        "changes_requested",
        "approved",
        "open_for_contribution",
        "paused",
        "completed",
        "cancelled",
    ):
        assert f'project_status == "{status}"' in octicon, status
    assert 'viewBox="0 0 16 16"' in octicon
    assert 'aria-hidden="true"' in octicon
    assert 'class="Label"' in detail
    assert '{% include "components/status_octicon.html"' in detail


@pytest.mark.unit
def test_official_provenance_uses_textual_prototype_labels():
    """A8/NFR-A11Y-01/GOV-011: provenance is explicit text, never color alone."""
    root = Path(settings.BASE_DIR)
    catalog = (root / "apps/projects/templates/projects/project_list.html").read_text()
    detail = (root / "apps/projects/templates/projects/project_detail.html").read_text()

    assert 'class="tag tag-accent">{% trans "Official" %}' in catalog
    assert 'class="tag tag-neutral">{% trans "Community project" %}' in catalog
    assert 'class="Label Label--outline">{% trans "Official" %}' in detail
    assert 'class="Label Label--secondary">{% trans "Community" %}' in detail

    for template in (catalog, detail):
        assert "badge--official" not in template
        assert "badge--community" not in template
        assert "status__glyph" not in template
        assert "--color-accent" not in template


@pytest.mark.unit
def test_project_detail_carries_contribution_and_accountability_sheets():
    """A1.3/A2.2/NFR-A11Y-01: project facts and accountability remain textual."""
    detail = (
        Path(settings.BASE_DIR) / "apps/projects/templates/projects/project_detail.html"
    ).read_text()

    assert 'class="dn-accountability"' in detail
    assert detail.count('class="dn-accountability-item"') >= 6
    assert '{% trans "Project sheet" %}' in detail
    assert "project.suitability" in detail and "confirmed_at" in detail
    assert "maintainer_assignments" in detail
    assert "get_response_sla_display" in detail
    assert '{% trans "No maintainer assigned yet" %}' in detail
    assert '{% trans "Suitability checklist not started" %}' in detail
    assert '{% trans "First-response commitment not yet published" %}' in detail


@pytest.mark.unit
def test_transition_css_keeps_focus_motion_and_target_contracts():
    """A8/NFR-A11Y-01: visible focus, reduced motion, and 44px targets still hold."""
    base_css = (Path(settings.BASE_DIR) / "static/src/base.css").read_text()
    shell_css = (Path(settings.BASE_DIR) / "static/src/devnepal.css").read_text()
    components_css = (Path(settings.BASE_DIR) / "static/src/components.css").read_text()
    tokens_css = (Path(settings.BASE_DIR) / "static/src/tokens.css").read_text()

    assert ":focus-visible" in base_css
    assert "outline:" in base_css
    assert ".dn-product-header :focus-visible" in base_css
    assert "@media (prefers-reduced-motion: reduce)" in base_css
    assert "transition-duration: 0.01ms !important;" in base_css
    assert "animation-duration: 0.01ms !important;" in base_css
    assert "scroll-behavior: auto !important;" in base_css
    assert "@view-transition" in base_css
    assert "navigation: auto" in base_css
    view_transition = base_css.split("@view-transition", 1)[1].split("@media", 1)[0]
    assert "animation: none" in view_transition
    assert "mix-blend-mode: normal" in view_transition
    assert "140ms" not in view_transition
    assert "--target-min: 44px;" in tokens_css
    assert ".btn" in shell_css or ".btn" in components_css
    for selector in (
        ".lang-switch button",
        ".mobile-nav a",
        ".dn-footer a",
    ):
        assert selector in shell_css
    assert "flex-wrap: wrap" in shell_css
    assert ".dn-state-dot" in components_css


@pytest.mark.unit
def test_mechanical_design_gate_matches_the_authority_rule_set():
    """A8/NFR-A11Y-01: the template corpus is gated by the design-system check rules.

    static/src/design_check.mjs adapts the authoritative scripts/check.mjs rule set:
    no gradients, Primer link present, skip link, image alt text, and no inline
    onclick handlers across every rendered template surface.
    """
    gate = (Path(settings.BASE_DIR) / "static/src/design_check.mjs").read_text()

    for rule in (
        "'linear-gradient('",
        "'radial-gradient('",
        "backdrop-filter:",
        "primer.css",
        "dn-skip-link",
        'alt="[^"]*"',
        "onclick",
    ):
        assert rule in gate, rule


def _read(relative: str) -> str:
    return (Path(settings.BASE_DIR) / relative).read_text()


@pytest.mark.unit
def test_blog_templates_use_issue_rows_context_header_and_form_layout():
    """A8/NFR-A11Y-01/BLG-005/D13: blog surfaces reuse the shared design-system grammar.

    Public discovery uses featured/stream rows with provenance, personal listings
    retain workflow-state rows, and authoring uses named form fields.
    """
    blog_list = _read("apps/blogs/templates/blogs/blog_list.html")
    my_list = _read("apps/blogs/templates/blogs/my_blog_list.html")
    detail = _read("apps/blogs/templates/blogs/blog_detail.html")
    form = _read("apps/blogs/templates/blogs/blog_form.html")

    assert 'class="public-discovery__feature blueprint"' in blog_list
    assert 'class="public-discovery__row"' in blog_list
    assert 'class="public-discovery__aside"' in blog_list
    assert 'class="dn-issue-list"' in my_list
    assert 'class="dn-issue-row"' in my_list
    assert '{% include "components/status_octicon.html"' in my_list
    assert "{{ post.get_status_display }}" in my_list

    assert '{% trans "Official" %}' in blog_list
    assert "{{ post.get_language_display }}" in blog_list
    assert "reading_time_minutes" in blog_list
    assert "canonical_url" in blog_list
    assert "noopener noreferrer external" in blog_list

    assert 'class="public-discovery__breadcrumb"' in detail
    assert 'class="public-discovery__article-header"' in detail
    assert '{% trans "Official government publication" %}' in detail
    assert 'class="public-discovery__aside"' in detail

    assert 'class="dn-form-layout"' in form
    assert 'class="dn-form-stack"' in form
    assert 'class="dn-field"' in form
    assert "as_p" not in form
    assert '{% trans "Save draft" %}' in form
    assert '{% trans "Preview and run checks" %}' in form
    assert '{% trans "Publish" %}' in form
    assert '{% trans "Unpublish" %}' in form
    assert '{% trans "Archive" %}' in form
    assert "{% url 'blogs:publish' post.pk %}" in form
    assert "{% url 'blogs:unpublish' post.pk %}" in form
    assert "{% url 'blogs:archive' post.pk %}" in form


@pytest.mark.unit
def test_taxonomy_suggestion_surfaces_use_form_layout_and_sla_review_rows():
    """A8/NFR-A11Y-01/MEM-004/D4: suggestions use the form layout and SLA review rows.

    The suggestion form uses dn-form-layout with programmatic labels; the review
    queue renders dn-review-row rows carrying an age/SLA Label with overdue
    emphasis that never relies on color alone.
    """
    form_template = _read("apps/taxonomy/templates/taxonomy/skill_suggestion_form.html")
    review = _read("apps/taxonomy/templates/taxonomy/skill_suggestion_review_list.html")

    assert 'class="dn-form-layout"' in form_template
    assert 'class="dn-form-stack"' in form_template
    assert 'class="dn-field"' in form_template
    assert 'for="{{ form.term_name.id_for_label }}"' in form_template
    assert 'for="{{ form.note.id_for_label }}"' in form_template
    assert "as_p" not in form_template

    assert 'class="dn-review-list"' in review
    assert 'class="dn-review-row' in review
    assert '{% now "U"' in review
    assert "432000" in review
    assert "is-overdue" in review
    assert '{% trans "Overdue: over 5 days since intake" %}' in review
    assert 'class="Label Label--danger"' in review
    assert "timesince" in review
    assert 'value="approve"' in review
    assert 'value="reject"' in review
    assert "{% url 'taxonomy:skill_suggestion_review' suggestion.pk %}" in review
    assert 'role="alert"' in review


@pytest.mark.unit
def test_notification_templates_use_issue_rows_counters_and_settings_rows():
    """A8/NFR-A11Y-01/NTF-001/NTF-002: the feed is an issue list, preferences are settings rows.

    The in-app feed renders dn-issue-list rows with a read/unread state Octicon
    partial and an unread Counter; email preferences render as dn-settings-list
    rows while keeping the mandatory-notice statement and labeled controls.
    """
    listing = _read("apps/notifications/templates/notifications/list.html")
    preferences = _read("apps/notifications/templates/notifications/preferences.html")
    octicon = _read("apps/notifications/templates/notifications/components/read_state_octicon.html")

    assert 'class="dn-issue-list"' in listing
    assert 'class="dn-issue-row"' in listing
    assert '{% include "notifications/components/read_state_octicon.html"' in listing
    assert 'class="Counter"' in listing
    assert "{% regroup notifications by read_at" in listing
    assert '{% trans "Mark all as read" %}' in listing
    assert '{% trans "Mark as read" %}' in listing
    assert '{% trans "Email preferences" %}' in listing
    assert "context_url" in listing
    assert "visually-hidden" in listing
    assert "{% url 'notifications:read' notification.pk %}" in listing
    assert "{% url 'notifications:read_all' %}" in listing

    assert 'class="dn-settings-list"' in preferences
    assert 'class="dn-setting-row"' in preferences
    assert "cannot be disabled" in preferences
    assert "as_p" not in preferences
    assert '{% trans "Save preferences" %}' in preferences
    assert "{% url 'notifications:email_preferences' %}" in preferences
    assert "{% url 'notifications:list' %}" in preferences

    for state in ("unread", "read"):
        assert f'read_state == "{state}"' in octicon, state
    assert octicon.count('viewBox="0 0 16 16"') == octicon.count("<svg") == 2
    assert octicon.count('aria-hidden="true"') == 2


@pytest.mark.unit
def test_project_pages_carry_a_context_header_with_underline_tabs_and_counters():
    """A8/NFR-A11Y-01: project pages use the repository-style context header.

    Authority: devnepal-design-system prompt (Shell and navigation) and
    examples/project.html. The context header carries owner / project hierarchy,
    a provenance label, and an underline tab bar; tab counters are real counts.
    """
    authoring = _read("apps/projects/templates/projects/authoring_detail.html")
    detail = _read("apps/projects/templates/projects/project_detail.html")
    application = _read("apps/projects/templates/projects/application_detail.html")
    timeline = _read("apps/projects/templates/projects/application_timeline.html")

    for template in (authoring, detail, application, timeline):
        assert 'class="dn-page-header"' in template
        assert 'class="dn-repo-title"' in template
        assert 'class="dn-repo-title-separator" aria-hidden="true">/<' in template
        assert "<h1>" in template

    for template in (authoring, application, timeline):
        assert 'class="dn-tabs" aria-label=' in template
        assert 'class="dn-tab" aria-current="page"' in template

    assert 'id="overview"' in detail
    assert '{% trans "Overview" %}</a>' not in detail
    assert "{% url 'projects:updates' project.slug %}" not in detail
    assert 'href="#updates"' not in detail

    for tab, route in (
        ("Overview", "projects:authoring_detail"),
        ("Readiness", "projects:authoring_readiness"),
        ("Attachments", "projects:authoring_attachment"),
        ("Updates", "projects:authoring_updates"),
        ("Questions", "projects:authoring_questions"),
    ):
        assert f"{{% url '{route}' project.slug %}}" in authoring, tab
    for anchor in ("overview", "readiness", "attachments", "updates", "questions"):
        assert f'id="{anchor}"' in authoring, anchor
    assert 'href="#readiness"' not in authoring
    assert 'href="#attachments"' not in authoring
    assert 'href="#updates"' not in authoring
    assert 'href="#questions"' not in authoring
    assert "active_tab" in authoring
    assert "{{ publish_readiness_violations|length }}" in authoring
    assert "{{ project.attachments.all|length }}" in authoring
    assert "{{ project.updates.all|length }}" in authoring
    assert "{{ project.screening_questions.all|length }}" in authoring

    assert 'aria-current="page" href="#application-detail">{% trans "Detail" %}' in application
    assert "{% url 'projects:application_timeline' application.pk %}" in application
    assert "{% url 'projects:application_detail' application.pk %}" in timeline
    assert 'aria-current="page" href="#timeline">{% trans "Timeline" %}' in timeline


@pytest.mark.unit
def test_unicode_status_glyphs_are_replaced_by_the_octicon_partial():
    """A8/NFR-A11Y-01/GIT-005: status is text plus an Octicon, never a glyph font.

    The status_octicon partial pattern is the only icon treatment for workflow
    state across project, application, contribution, and moderation templates.
    """
    octicon = _read("templates/components/status_octicon.html")
    statuses = (
        "draft",
        "in_review",
        "changes_requested",
        "approved",
        "open_for_contribution",
        "paused",
        "completed",
        "cancelled",
        "submitted",
        "info_requested",
        "waitlisted",
        "accepted",
        "declined",
        "withdrawn",
        "candidate",
        "pending_info",
        "rejected",
        "revoked",
        "new",
        "under_review",
        "action_taken",
        "closed_no_action",
        "appealed",
        "escalated",
    )
    for status in statuses:
        assert f'project_status == "{status}"' in octicon, status
    assert octicon.count('aria-hidden="true"') == octicon.count("<svg")
    assert octicon.count('viewBox="0 0 16 16"') == octicon.count("<svg")

    scoped = [
        "apps/projects/templates/projects/application_list.html",
        "apps/projects/templates/projects/application_detail.html",
        "apps/projects/templates/projects/application_timeline.html",
        "apps/contributions/templates/contributions/detail.html",
        "apps/moderation/templates/moderation/case_queue.html",
    ]
    for relative in scoped:
        template = _read(relative)
        assert '{% include "components/status_octicon.html"' in template, relative
        assert "status__glyph" not in template, relative
        for glyph in ("◧", "▣", "⏸", "◷", "☒", "■"):
            assert glyph not in template, relative


@pytest.mark.unit
def test_forms_use_the_design_system_form_layout_and_field_patterns():
    """A8/NFR-A11Y-01/GOV-003: forms use dn-form-layout with named dn-field controls.

    Authority: devnepal-design-system examples/publish.html. Every control keeps a
    programmatic label, help text is associated in the field stack, and validation
    errors render inside the field.
    """
    for relative in (
        "apps/projects/templates/projects/authoring_form.html",
        "apps/contributions/templates/contributions/evidence_form.html",
        "apps/moderation/templates/moderation/report_form.html",
        "apps/ministries/templates/ministries/organization_form.html",
    ):
        template = _read(relative)
        assert 'class="dn-form-layout"' in template, relative
        assert 'class="dn-form-stack"' in template, relative
        assert 'class="dn-field"' in template, relative
        assert 'class="dn-field-help"' in template or "{{ field.help_text }}" in template
        if relative != "apps/projects/templates/projects/authoring_form.html":
            assert 'class="dn-sidebar"' in template, relative
        assert "as_p" not in template, relative

    authoring = _read("apps/projects/templates/projects/authoring_detail.html")
    assert authoring.count('class="dn-form-stack"') >= 6
    assert 'class="field-group"' not in authoring


@pytest.mark.unit
def test_settings_pages_use_settings_list_rows():
    """A8/NFR-A11Y-01/AUTH-008: connections and confirmations use settings rows.

    Authority: devnepal-design-system examples/access.html; each row pairs a
    named state with its consequence and action.
    """
    connection = _read("apps/github_sync/templates/github_sync/connection.html")
    assert 'class="dn-settings-list"' in connection
    assert connection.count('class="dn-setting-row"') >= 6
    assert "{% url 'github_sync:disconnect' %}" in connection
    assert '{% trans "Connected" %}' in connection
    assert '{% trans "Disconnected" %}' in connection

    contact = _read("apps/ministries/templates/ministries/contact_confirmation.html")
    assert 'class="dn-settings-list"' in contact
    assert 'class="dn-setting-row"' in contact
    assert '{% trans "Confirm email" %}' in contact


@pytest.mark.unit
def test_moderation_case_queue_uses_review_rows_with_sla_overdue_emphasis():
    """A8/NFR-A11Y-01/ADM-002: review work is queue rows sorted with SLA urgency.

    Rows carry the dn-review-row grammar, gain is-overdue when the case is older
    than five days, and overdue state always includes visible text so it never
    relies on color alone.
    """
    queue = _read("apps/moderation/templates/moderation/case_queue.html")

    assert 'class="dn-review-list"' in queue
    assert 'class="dn-review-row' in queue
    assert '{% now "U" as queue_now_unix %}' in queue
    assert "432000" in queue
    assert "is-overdue" in queue
    assert '{% trans "Overdue: over 5 days since intake" %}' in queue
    assert 'class="Label Label--danger"' in queue
    assert 'role="status"' in queue
    assert "aria-label=\"{% trans 'Moderation case pages' %}\"" in queue
    assert 'aria-current="page"' in queue
    assert "{% url 'moderation:case_detail' case.pk %}" in queue


@pytest.mark.unit
def test_conversation_pages_use_the_pr_timeline_grammar():
    """A8/NFR-A11Y-01/DSC-008: decisions and verification use the PR timeline.

    Authority: devnepal-design-system examples/application.html; append-only
    activity renders as dn-timeline items with header and body regions.
    """
    for relative in (
        "apps/projects/templates/projects/application_timeline.html",
        "apps/contributions/templates/contributions/detail.html",
        "apps/contributions/templates/contributions/history.html",
    ):
        template = _read(relative)
        assert 'class="dn-timeline"' in template, relative
        assert 'class="dn-timeline-item"' in template, relative
        assert 'class="dn-timeline-item-header"' in template, relative
        assert 'class="dn-timeline-item-body"' in template, relative

    application = _read("apps/projects/templates/projects/application_detail.html")
    assert 'class="dn-timeline"' in application


@pytest.mark.unit
def test_footer_has_four_columns_with_resolvable_translated_links():
    """A8/NFR-A11Y-01/BR-006: the footer matches the shell grammar without dead links.

    Four columns: Platform, Policies, Help, and the official-platform note. Every
    link is a translated, route-guarded {% url ... as %} lookup so a link without
    a route is omitted instead of failing to resolve.
    """
    base = _read("templates/base.html")

    assert 'class="dn-footer"' in base
    assert 'class="dn-container dn-footer-grid"' in base
    assert 'class="dn-footer-platform"' in base
    assert 'class="dn-footer-note"' in base
    assert "dn-footer-brand" not in base
    assert base.count("<footer") == 1
    for label in ("Platform", "Policies", "Help"):
        assert f"aria-label=\"{{% trans '{label}' %}}\"" in base, label
        assert f'<h2>{{% trans "{label}" %}}</h2>' in base, label
    assert '<h2>{% trans "Official platform" %}</h2>' in base
    assert "नेपाल सरकारको सार्वजनिक सहयोग मञ्च।" in base

    assert base.count("{% url ") == base.count("{% url ") and "_url %}" in base
    assert '<a href="{% url' not in base.split("<footer")[1]
    assert '<li><a href="{{ issues_url }}">{% trans "Open issues" %}</a></li>' in base
    assert '<li><a href="{{ government_url }}">{% trans "Government Projects" %}</a></li>' in base
    assert "report_url" not in base
    assert "github_connection_url" not in base

    footer_css = _read("static/src/devnepal.css")
    footer_link_rule = (
        ".dn-footer a { display: inline-flex; align-items: center;"
        " min-height: var(--target-min, 44px);"
    )
    assert footer_link_rule in footer_css
    assert ".dn-footer { margin-top: var(--space-10); padding: var(--space-10) 0 0;" in (footer_css)
    # The footer closes on the same state colour the header opens with, and names
    # the publishing authority with the emblem rather than in prose alone.
    assert ".dn-footer-legal { margin-top: var(--space-10);" in footer_css
    assert "background: var(--color-state); color: var(--color-paper);" in footer_css
    assert 'class="dn-footer-identity"' in base
    assert 'class="dn-footer-emblem"' in base
    assert ".dn-footer-grid { display: grid; gap: var(--space-6) var(--space-8); }" in footer_css
    assert "@media (min-width: 640px) { .dn-footer-grid { grid-template-columns:" in footer_css
    assert "repeat(2, minmax(0, 1fr)); } }" in footer_css
    assert (
        ".dn-footer-grid { grid-template-columns: 1.4fr repeat(3, minmax(0, 1fr)) 1.1fr; }"
        in footer_css
    )
    assert (
        ".dn-footer-platform ul { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));"
        in footer_css
    )


@pytest.mark.unit
def test_public_demo_layouts_keep_filters_visible_and_mobile_actions_tappable():
    """DSC-001/DSC-002/NFR-A11Y-01: core public layouts avoid empty rails and tiny actions."""
    shell_css = _read("static/src/devnepal.css")
    catalog = _read("apps/projects/templates/projects/project_list.html")

    assert '<details class="dn-catalog-filters" open>' in catalog
    assert ".dn-catalog-filters > summary { display: none;" in shell_css
    assert "@media (max-width: 1000px)" in shell_css
    assert (
        ".dn-catalog-filters > summary { display: flex; min-height: var(--control-lg);" in shell_css
    )
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in shell_css
    assert ".dn-provider-profile { padding-block: var(--space-4) var(--space-16);" in shell_css
    assert (
        ".dn-github-project .dn-issue-row > a:last-child { display: inline-flex; "
        "min-height: var(--target-min);"
    ) in shell_css
