"""Signal wiring placeholder (NTF-001).

No signals are connected yet. Trigger domains (projects, contributions,
moderation, github_sync, recognition) call ``apps.notifications.services.notify``
directly from their services; this module exists so a later wave can move to
event-driven dispatch without hunting for the integration point. Connect
receivers here — never in other apps' code.
"""
