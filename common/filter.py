from django.db.models import Q


def get_student_queryparams(query_params, other_parms: None):
    params: dict[str, str] = query_params
    f = Q()
    if len(params):
        for k, v in params.items():
            if k == "status":
                values = v.split(",")
                v = [value.strip() for value in values if value.strip()]
                print(f"Filtering by status: {v}")
                if v:
                    f.add(Q(**{f"status__in": v}), Q.AND)
            if k == "enrollment_status":
                values = v.split(",")
                v = [value.strip() for value in values if value.strip()]
                f.add(Q(**{f"enrollments__status__in": v}), Q.AND)
            if k == "start_date_enrolled":
                f.add(Q(**{f"start_date__gte": v}), Q.AND)
            elif k == "end_date_enrolled":
                f.add(Q(**{f"end_date__lte": v}), Q.AND)
            elif k == "section":
                f.add(Q(**{f"enrollments__section__name": v}), Q.AND)
            elif k == "academic_year":
                f.add(Q(**{f"enrollments__academic_year__name": v}), Q.AND)
            elif k in ["year", "month", "day"]:
                f.add(Q(**{f"start_date__{k}": v}), Q.AND)
            elif k == "search":
                if v.isdigit():
                    f.add(
                        Q(**{"id_number__startswith": v})
                        | Q(**{"phone_number__icontains": v}),
                        Q.AND,
                    )
                elif "@" in v:
                    f.add(Q(**{"email__icontains": v}), Q.AND)
                else:
                    f.add(
                        Q(**{"first_name__icontains": v})
                        | Q(**{"middle_name__icontains": v})
                        | Q(**{"last_name__icontains": v})
                        | Q(**{"prev_id_number__icontains": v}),
                        Q.AND,
                    )
            else:
                if k in other_parms or []:
                    f.add(Q(**{k: v}), Q.AND)
    return f


def get_transaction_queryparams(query_params, other_params=None):
    """
    Filter function specifically for Transaction model.
    Handles transaction-specific filtering based on query parameters.
    """
    params: dict[str, str] = query_params
    f = Q()

    if len(params):
        for k, v in params.items():
            if k == "status":
                values = v.split(",")
                s = [value.strip() for value in values if value.strip()]
                if s:
                    f.add(Q(**{f"status__in": s}), Q.AND)
            elif k == "transaction_type":
                f.add(Q(**{f"type__id": v}), Q.AND)
            if k == "account":
                f.add(Q(**{f"account__number": v}), Q.AND)
            elif k == "student_id":
                f.add(Q(**{f"student__id_number": v}), Q.AND)
            elif k == "payment_method":
                if v == "all":
                    continue
                f.add(Q(**{f"payment_method__name__iexact": v}), Q.AND)
            # elif k == "currency":
            #     f.add(Q(**{f"currency__code": v}), Q.AND)
            elif k == "date_from":
                f.add(Q(**{f"date__gte": v}), Q.AND)
            elif k == "date_to":
                f.add(Q(**{f"date__lte": v}), Q.AND)
            elif k in ["year", "month", "day"]:
                f.add(Q(**{f"date__{k}": v}), Q.AND)
            elif k == "amount_min":
                f.add(Q(**{f"amount__gte": v}), Q.AND)
            elif k == "amount_max":
                f.add(Q(**{f"amount__lte": v}), Q.AND)
            elif k == "amount":
                f.add(Q(**{f"amount": v}), Q.AND)
            elif k == "reference":
                f.add(Q(**{f"reference__icontains": v}), Q.AND)
            elif k == "transaction_id":
                f.add(Q(**{f"transaction_id__icontains": v}), Q.AND)
            elif k == "target":
                if v == "student":
                    f.add(~Q(student__isnull=True), Q.AND)
                else:
                    f.add(Q(student__isnull=True), Q.AND)
            elif k == "grade_level":
                f.add(Q(**{f"student__enrollments__grade_level__id": v}), Q.AND)
            elif k == "section":
                f.add(Q(**{f"student__enrollments__section__id": v}), Q.AND)
            elif k == "academic_year":
                f.add(Q(**{f"student__enrollments__academic_year__id": v}), Q.AND)
            elif k == "enrolled_as":
                values = v.split(",")
                s = [value.strip() for value in values if value.strip()]
                f.add(Q(**{f"student__enrollments__enrolled_as__in": s}), Q.AND)

            # General search across multiple fields
            elif k == "query":
                search_query = (
                    Q(description__icontains=v)
                    | Q(transaction_id__icontains=v)
                    | Q(reference__icontains=v)
                    | Q(notes__icontains=v)
                    | Q(student__first_name__icontains=v)
                    | Q(student__last_name__icontains=v)
                    | Q(student__id_number__icontains=v)
                )
                f.add(search_query, Q.AND)

            else:
                if other_params and k in other_params:
                    f.add(Q(**{k: v}), Q.AND)

    return f
