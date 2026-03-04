"""Common view mixins for reusable patterns"""

from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import NotFound


class PaginatedResponseMixin:
    """
    Mixin for paginated responses

    Usage:
        class MyView(PaginatedResponseMixin, APIView):
            pagination_class = PageNumberPagination

            def get(self, request):
                queryset = Model.objects.all()
                return self.get_paginated_response(queryset, request, serializer_class)
    """

    def get_paginated_response(self, queryset, request, serializer_class, many=True):
        """
        Get paginated response for queryset

        Args:
            queryset: QuerySet to paginate
            request: Request object
            serializer_class: Serializer class to use
            many: Whether to serialize as list

        Returns:
            Response: Paginated response or simple response
        """
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)

        if page is not None:
            serializer = serializer_class(page, many=many, context={"request": request})
            return paginator.get_paginated_response(serializer.data)

        # Fallback if pagination is not used
        serializer = serializer_class(queryset, many=many, context={"request": request})
        return Response(serializer.data)


class ObjectLookupMixin:
    """
    Mixin for object lookup with Q object support

    Usage:
        class MyView(ObjectLookupMixin, APIView):
            model = MyModel
            lookup_fields = ['id', 'id_number']  # Fields to search

            def get(self, request, id):
                obj = self.get_object(id)
                # ...
    """

    model = None
    lookup_fields = ["id"]
    queryset = None

    def get_queryset(self):
        """Get base queryset"""
        if self.queryset is not None:
            return self.queryset
        if self.model is not None:
            return self.model.objects.all()
        elif self.model is None and self.queryset is None:
            raise AttributeError(
                f"{self.__class__.__name__} must have either 'model' or 'queryset' attribute"
            )

    def get_object(self, lookup_value):
        """
        Get object by lookup value using Q objects

        Args:
            lookup_value: Value to search for

        Returns:
            Model instance

        Raises:
            NotFound: If object not found
        """
        from django.db.models import Q

        queryset = self.get_queryset()

        # Build Q object from lookup fields
        q_objects = Q()
        for field in self.lookup_fields:
            q_objects |= Q(**{field: lookup_value})

        try:
            return queryset.get(q_objects)
        except self.model.DoesNotExist:
            model_name = self.model.__name__ if self.model else "Object"
            raise NotFound(f"{model_name} does not exist with this id")
