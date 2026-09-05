from django.db import models


class Province(models.TextChoices):
    KOSHI = "koshi", "Koshi"
    MADHESH = "madhesh", "Madhesh"
    BAGMATI = "bagmati", "Bagmati"
    GANDAKI = "gandaki", "Gandaki"
    LUMBINI = "lumbini", "Lumbini"
    KARNALI = "karnali", "Karnali"
    SUDURPASCHIM = "sudurpaschim", "Sudurpashchim"
    OUTSIDE_NEPAL = "outside_nepal", "Outside Nepal"


class Availability(models.TextChoices):
    AVAILABLE_NOW = "available_now", "Available now"
    LIMITED = "limited", "Limited (a few hours per week)"
    UNAVAILABLE = "unavailable", "Not available"


class LinkType(models.TextChoices):
    GITHUB = "github", "GitHub"
    MEDIUM = "medium", "Medium"
    WEBSITE = "website", "Personal website"
    PORTFOLIO = "portfolio", "Portfolio"
    LINKEDIN = "linkedin", "LinkedIn"
    OTHER = "other", "Other"


class Visibility(models.TextChoices):
    PUBLIC = "public", "Public"
    MEMBERS = "members", "Members only"
    PRIVATE = "private", "Private"
