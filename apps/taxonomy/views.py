from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.permissions import is_super_admin, privileged_mfa_required
from apps.taxonomy.enums import SuggestionStatus
from apps.taxonomy.forms import (
    LicenseApprovalForm,
    LicenseForm,
    LicenseWithdrawalForm,
    SkillForm,
    SkillMergeForm,
    SkillSuggestionForm,
    SuggestionReviewForm,
)
from apps.taxonomy.models import ApprovedLicense, Skill, SkillSuggestion, TaxonomyVersion
from apps.taxonomy.services import (
    DuplicateSuggestionError,
    ExistingSkillError,
    SkillAlreadyExistsError,
    SkillMergeError,
    SkillNotPublishableError,
    SuggestionAlreadyResolvedError,
    approve_license,
    create_skill,
    license_project_counts,
    merge_skills,
    record_license,
    review_suggestion,
    set_skill_active,
    skill_usage_counts,
    suggest_skill,
    withdraw_license,
)


def _require_super_admin(user):
    if not is_super_admin(user):
        raise PermissionDenied


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["GET", "POST"])
def skill_suggestion_create(request):
    """MEM-004: authenticated members submit missing skills for Super Admin review."""
    if request.method == "POST":
        form = SkillSuggestionForm(request.POST)
        if form.is_valid():
            try:
                suggest_skill(
                    request.user,
                    form.cleaned_data["term_name"],
                    form.cleaned_data["note"],
                )
            except DuplicateSuggestionError:
                form.add_error("term_name", _("This term is already awaiting review."))
            except ExistingSkillError:
                form.add_error("term_name", _("This skill is already in the taxonomy."))
            else:
                return redirect("taxonomy:skill_suggestion_create")
        return render(request, "taxonomy/skill_suggestion_form.html", {"form": form}, status=400)
    return render(request, "taxonomy/skill_suggestion_form.html", {"form": SkillSuggestionForm()})


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET"])
def skill_suggestion_review_list(request):
    """D4/ADM-001: only verified Super Admins can view pending skill suggestions."""
    _require_super_admin(request.user)
    suggestions = SkillSuggestion.objects.filter(status=SuggestionStatus.PENDING).select_related(
        "suggested_by"
    )
    return render(
        request,
        "taxonomy/skill_suggestion_review_list.html",
        {"suggestions": suggestions},
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def skill_suggestion_review(request, pk):
    """D4/ADM-001: a verified Super Admin approves or rejects one pending suggestion."""
    _require_super_admin(request.user)
    suggestion = get_object_or_404(SkillSuggestion, pk=pk, status=SuggestionStatus.PENDING)
    form = SuggestionReviewForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "taxonomy/skill_suggestion_review_list.html",
            {
                "suggestions": SkillSuggestion.objects.filter(
                    status=SuggestionStatus.PENDING
                ).select_related("suggested_by"),
                "review_error": _("Choose whether to approve or reject the suggestion."),
            },
            status=400,
        )
    try:
        review_suggestion(
            request.user,
            suggestion,
            approve=form.cleaned_data["decision"] == SuggestionReviewForm.APPROVE,
        )
    except (SkillAlreadyExistsError, SuggestionAlreadyResolvedError):
        return render(
            request,
            "taxonomy/skill_suggestion_review_list.html",
            {
                "suggestions": SkillSuggestion.objects.filter(
                    status=SuggestionStatus.PENDING
                ).select_related("suggested_by"),
                "review_error": _("This suggestion can no longer be reviewed."),
            },
            status=409,
        )
    return redirect("taxonomy:skill_suggestion_review_list")


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def skill_management(request):
    """ADM-001/D5.5: the bilingual skills catalogue, its usage and its version history."""
    _require_super_admin(request.user)
    form = SkillForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            try:
                create_skill(request.user, **form.cleaned_data)
            except SkillAlreadyExistsError:
                messages.error(request, _("That skill already exists."))
            else:
                messages.success(request, _("Skill added."))
                return redirect("taxonomy:skill_management")
        else:
            messages.error(request, _("A skill needs at least an English name."))

    usage = skill_usage_counts()
    skills = list(Skill.objects.order_by("name"))
    for skill in skills:
        skill.usage_count = usage.get(skill.pk, 0)
    return render(
        request,
        "taxonomy/skill_management.html",
        {
            "skills": skills,
            "form": form,
            "merge_form": SkillMergeForm(),
            "pending_suggestions": SkillSuggestion.objects.filter(
                status=SuggestionStatus.PENDING
            ).select_related("suggested_by"),
            "versions": TaxonomyVersion.objects.select_related("actor")[:20],
            "current_version": TaxonomyVersion.objects.order_by("-version")
            .values_list("version", flat=True)
            .first()
            or 0,
        },
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def skill_state(request, slug):
    """ADM-001/D5.5: deprecate a skill or bring it back into the pickers."""
    _require_super_admin(request.user)
    skill = get_object_or_404(Skill, slug=slug)
    activate = request.POST.get("state") == "active"
    try:
        set_skill_active(request.user, skill, is_active=activate)
    except SkillNotPublishableError:
        messages.error(request, _("Add the Nepali name before this skill can appear in pickers."))
    else:
        messages.success(
            request,
            _("%(skill)s is active.") % {"skill": skill.name}
            if activate
            else _("%(skill)s is deprecated and hidden from pickers.") % {"skill": skill.name},
        )
    return redirect("taxonomy:skill_management")


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def skill_merge(request, slug):
    """ADM-001/D5.5: merge a duplicate skill, re-tagging the members and projects using it."""
    _require_super_admin(request.user)
    source = get_object_or_404(Skill, slug=slug)
    form = SkillMergeForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Name the skill to merge into."))
        return redirect("taxonomy:skill_management")
    target = Skill.objects.filter(slug=form.cleaned_data["target"]).first()
    if target is None:
        messages.error(request, _("No skill matches that slug."))
        return redirect("taxonomy:skill_management")
    try:
        merge_skills(request.user, source, target)
    except SkillMergeError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request,
            _("%(source)s merged into %(target)s; members and projects were re-tagged.")
            % {"source": source.name, "target": target.name},
        )
    return redirect("taxonomy:skill_management")


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def license_management(request):
    """ADM-001/D5.6: approved SPDX licences with their legal references and state."""
    _require_super_admin(request.user)
    form = LicenseForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            record_license(request.user, **form.cleaned_data)
            messages.success(request, _("Licence recorded as pending legal approval."))
            return redirect("taxonomy:license_management")
        messages.error(request, _("The licence could not be recorded."))

    counts = license_project_counts()
    licenses = list(ApprovedLicense.objects.order_by("-is_approved", "spdx_id"))
    for record in licenses:
        record.project_count = counts.get(record.pk, 0)
    return render(
        request,
        "taxonomy/license_management.html",
        {"licenses": licenses, "form": form},
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_POST
def license_decision(request, pk):
    """ADM-001/D5.6: record legal approval, or withdraw a licence from future use."""
    _require_super_admin(request.user)
    record = get_object_or_404(ApprovedLicense, pk=pk)
    if request.POST.get("intent") == "withdraw":
        form = LicenseWithdrawalForm(request.POST)
        if not form.is_valid():
            messages.error(request, _("Withdrawing a licence requires a reason."))
            return redirect("taxonomy:license_management")
        withdraw_license(request.user, record, reason=form.cleaned_data["reason"])
        messages.success(
            request,
            _("%(spdx)s withdrawn from future use. Published projects keep it.")
            % {"spdx": record.spdx_id},
        )
        return redirect("taxonomy:license_management")

    form = LicenseApprovalForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Approval needs its legal reference."))
        return redirect("taxonomy:license_management")
    approve_license(request.user, record, legal_reference=form.cleaned_data["legal_reference"])
    messages.success(request, _("%(spdx)s approved.") % {"spdx": record.spdx_id})
    return redirect("taxonomy:license_management")
