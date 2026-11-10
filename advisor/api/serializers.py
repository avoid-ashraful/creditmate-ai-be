from rest_framework import serializers


class AdvisorChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000)
    session_id = serializers.UUIDField(required=False)
    anon_id = serializers.CharField(max_length=64, required=False, default="")


class CitationSerializer(serializers.Serializer):
    product_type = serializers.CharField()
    product_id = serializers.IntegerField(allow_null=True)
    slug = serializers.CharField(allow_null=True)
    label = serializers.CharField()
    url_path = serializers.CharField()
    field = serializers.CharField(allow_null=True)


class SuggestedActionSerializer(serializers.Serializer):
    kind = serializers.CharField()
    label = serializers.CharField()
    product_type = serializers.CharField(allow_null=True)
    product_id = serializers.IntegerField(allow_null=True)
    slug = serializers.CharField(allow_null=True)


class AdvisorChatResponseSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    answer_markdown = serializers.CharField()
    cited_product_ids = serializers.ListField(child=serializers.IntegerField())
    citations = CitationSerializer(many=True)
    suggested_actions = SuggestedActionSerializer(many=True)
    confidence_notes = serializers.ListField(child=serializers.CharField())
    is_fallback = serializers.BooleanField()
    tool_trace = serializers.ListField(child=serializers.DictField())
