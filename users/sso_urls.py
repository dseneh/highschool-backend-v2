from django.urls import path

from users.sso_views import (
    GlobalLogoutView,
    SsoBootstrapView,
    SsoAuthorizeView,
    SsoRefreshView,
    SsoTokenExchangeView,
    TenantLogoutView,
)


urlpatterns = [
    path("bootstrap", SsoBootstrapView.as_view(), name="sso-bootstrap"),
    path("bootstrap/", SsoBootstrapView.as_view(), name="sso-bootstrap-slash"),
    path("authorize", SsoAuthorizeView.as_view(), name="sso-authorize"),
    path("authorize/", SsoAuthorizeView.as_view(), name="sso-authorize-slash"),
    path("token", SsoTokenExchangeView.as_view(), name="sso-token-exchange"),
    path("token/", SsoTokenExchangeView.as_view(), name="sso-token-exchange-slash"),
    path("refresh", SsoRefreshView.as_view(), name="sso-refresh"),
    path("refresh/", SsoRefreshView.as_view(), name="sso-refresh-slash"),
    path("logout", GlobalLogoutView.as_view(), name="sso-global-logout"),
    path("logout/", GlobalLogoutView.as_view(), name="sso-global-logout-slash"),
    path("tenant/logout", TenantLogoutView.as_view(), name="sso-tenant-logout"),
    path("tenant/logout/", TenantLogoutView.as_view(), name="sso-tenant-logout-slash"),
]
