from rest_framework import serializers


class SsoAuthorizeSerializer(serializers.Serializer):
    client_id = serializers.CharField(max_length=120)
    redirect_uri = serializers.URLField(max_length=500)
    tenant = serializers.CharField(max_length=120)
    state = serializers.CharField(max_length=512)
    code_challenge = serializers.CharField(max_length=255)
    code_challenge_method = serializers.ChoiceField(choices=["S256"])
    return_to = serializers.CharField(max_length=500, required=False, allow_blank=True)


class SsoTokenExchangeSerializer(serializers.Serializer):
    grant_type = serializers.ChoiceField(choices=["authorization_code"])
    code = serializers.CharField(max_length=1024)
    client_id = serializers.CharField(max_length=120)
    redirect_uri = serializers.URLField(max_length=500)
    code_verifier = serializers.CharField(max_length=512)


class SsoRefreshSerializer(serializers.Serializer):
    grant_type = serializers.ChoiceField(choices=["refresh_token"])
    refresh_token = serializers.CharField(max_length=2048)


class TenantLogoutSerializer(serializers.Serializer):
    tenant_session_id = serializers.UUIDField(required=False)


class GlobalLogoutSerializer(serializers.Serializer):
    central_session_id = serializers.UUIDField(required=False)


class SsoBootstrapSerializer(serializers.Serializer):
    ttl_seconds = serializers.IntegerField(required=False, min_value=300, max_value=86400)
