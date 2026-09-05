from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.notifications.forms import EmailPreferencesForm
from apps.notifications.services import (
    mark_read,
    notifications_for,
    preferences_for,
    update_email_preferences,
)


@login_required(login_url=reverse_lazy("accounts:login"))
@require_GET
def notification_list(request):
    return render(
        request,
        "notifications/list.html",
        {"notifications": notifications_for(request.user)},
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def notification_read(request, pk):
    if not notifications_for(request.user).filter(pk=pk).exists():
        raise Http404
    mark_read(request.user, [pk])
    return redirect("notifications:list")


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def notification_read_all(request):
    mark_read(
        request.user,
        notifications_for(request.user).filter(read_at__isnull=True).values_list("pk", flat=True),
    )
    return redirect("notifications:list")


@login_required(login_url=reverse_lazy("accounts:login"))
@require_http_methods(["GET", "POST"])
def email_preferences(request):
    """NTF-002: member UI for non-essential email categories and digest frequency."""
    preference = preferences_for(request.user)
    form = EmailPreferencesForm(request.POST or None, instance=preference)
    if request.method == "POST" and form.is_valid():
        update_email_preferences(request.user, **form.cleaned_data)
        messages.success(request, _("Email preferences saved."))
        return redirect("notifications:email_preferences")
    return render(request, "notifications/preferences.html", {"form": form})
