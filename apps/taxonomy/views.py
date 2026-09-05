from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.permissions import is_super_admin, privileged_mfa_required
from apps.taxonomy.enums import SuggestionStatus
from apps.taxonomy.forms import SkillSuggestionForm, SuggestionReviewForm
from apps.taxonomy.models import SkillSuggestion
from apps.taxonomy.services import (
    DuplicateSuggestionError,
    ExistingSkillError,
    SkillAlreadyExistsError,
    SuggestionAlreadyResolvedError,
    review_suggestion,
    suggest_skill,
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
