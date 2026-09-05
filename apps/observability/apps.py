from django.apps import AppConfig


class ObservabilityConfig(AppConfig):
    name = "apps.observability"

    def ready(self):
        from apps.observability.tracing import configure_tracing

        configure_tracing()
