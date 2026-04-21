from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import NotFound

from common.utils import update_model_fields
from grading.utils import paginate_qs
from grading.models import HonorCategory
from grading.serializers import HonorCategoryOut


FIELD_LABELS = {
    "label": "Label",
    "min_average": "Min average",
    "max_average": "Max average",
    "color": "Color",
    "icon": "Icon",
    "order": "Order",
    "active": "Active",
    "__all__": "Honor category",
}


def _format_validation_error(exc):
    """Turn a Django ValidationError into a human-readable message."""
    if hasattr(exc, "message_dict"):
        parts = []
        for field, messages in exc.message_dict.items():
            label = FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
            for msg in messages:
                parts.append(f"{label}: {msg}")
        return " ".join(parts) or "Invalid data."
    if hasattr(exc, "messages"):
        return " ".join(str(m) for m in exc.messages) or "Invalid data."
    return str(exc)


class HonorCategoryListCreateView(APIView):
    """List and create honor categories (e.g., Principal's List, Honor Roll)."""

    def get(self, request):
        qs = HonorCategory.objects.only(
            "id", "active", "label", "min_average", "max_average",
            "color", "icon", "order", "created_at", "updated_at"
        ).order_by("order", "-max_average")

        page, meta = paginate_qs(qs, request)
        return Response({"meta": meta, "results": HonorCategoryOut(page, many=True).data})

    @transaction.atomic
    def post(self, request):
        label = request.data.get("label")
        min_average = request.data.get("min_average")
        max_average = request.data.get("max_average")
        order = request.data.get("order", 0)
        color = request.data.get("color", "") or ""
        icon = request.data.get("icon", "") or ""

        if not label:
            return Response({"detail": "label is required."}, status=400)
        if min_average is None:
            return Response({"detail": "min_average is required."}, status=400)
        if max_average is None:
            return Response({"detail": "max_average is required."}, status=400)

        try:
            obj = HonorCategory.objects.create(
                label=label,
                min_average=min_average,
                max_average=max_average,
                color=color,
                icon=icon,
                order=order,
                created_by=request.user,
                updated_by=request.user,
            )
            return Response(HonorCategoryOut(obj).data, status=201)
        except DjangoValidationError as e:
            return Response({"detail": _format_validation_error(e)}, status=400)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)


class HonorCategoryDetailView(APIView):
    def get_object(self, pk):
        try:
            return HonorCategory.objects.get(pk=pk)
        except HonorCategory.DoesNotExist:
            raise NotFound("This honor category does not exist.")

    def get(self, request, pk):
        obj = self.get_object(pk)
        return Response(HonorCategoryOut(obj).data)

    @transaction.atomic
    def patch(self, request, pk):
        obj = self.get_object(pk)
        allowed_fields = [
            "label",
            "min_average",
            "max_average",
            "color",
            "icon",
            "order",
            "active",
        ]
        try:
            serializer = update_model_fields(request, obj, allowed_fields, HonorCategoryOut)
        except DjangoValidationError as e:
            return Response({"detail": _format_validation_error(e)}, status=400)
        return Response(serializer.data)

    @transaction.atomic
    def delete(self, request, pk):
        obj = self.get_object(pk)
        obj.delete()
        return Response(status=204)
