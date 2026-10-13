"""
URL configuration for credit_mate_ai project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns: path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns: path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns: path('blog/', include('blog.urls'))
"""

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from banks.views import data_quality_dashboard

from . import views

urlpatterns = [
    path("health/", views.health_check, name="health_check"),
    # Staff-only data-quality snapshot; must precede the admin include so it
    # is never swallowed by the admin URLconf.
    path("admin/data-quality/", data_quality_dashboard, name="data-quality-dashboard"),
    path("admin/", admin.site.urls),
    path("api/v1/", include("banks.api.urls")),
    path("api/v1/", include("credit_cards.api.urls")),
    path("api/v1/auth/", include("accounts.urls")),
    path("api/search/", include("search.api.urls")),
    path("api-auth/", include("rest_framework.urls")),
    # OpenAPI / Swagger / Redoc schema generation
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/docs/swagger/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/v1/docs/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
