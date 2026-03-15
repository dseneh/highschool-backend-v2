import copy

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from ..access_policies import AcademicsAccessPolicy
from ..models import Section
from ..serializers import SectionTimeSlotSerializer
from business.core.adapters.section_adapter import (
    initialize_section_time_slots,
    regenerate_section_time_slots_from_template,
)


class SectionTimeSlotListView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get_section(self, section_id: str) -> Section:
        try:
            return Section.objects.get(id=section_id)
        except Section.DoesNotExist as exc:
            raise NotFound("Section does not exist with this id") from exc

    def get(self, request, section_id):
        section = self.get_section(section_id)
        slots = section.time_slots.filter(active=True).select_related("period")
        serializer = SectionTimeSlotSerializer(slots, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, section_id):
        section = self.get_section(section_id)
        payload = copy.deepcopy(request.data)
        payload["section"] = str(section.id)

        serializer = SectionTimeSlotSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        slot = serializer.save(created_by=request.user, updated_by=request.user)
        return Response(
            SectionTimeSlotSerializer(slot, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class SectionTimeSlotDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get_object(self, slot_id):
        slot = (
            Section.objects.filter(time_slots__id=slot_id)
            .prefetch_related("time_slots")
            .first()
        )
        if not slot:
            raise NotFound("Section time slot does not exist with this id")
        return slot.time_slots.get(id=slot_id)

    def get(self, request, id):
        slot = self.get_object(id)
        serializer = SectionTimeSlotSerializer(slot)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        slot = self.get_object(id)
        payload = copy.deepcopy(request.data)
        payload["section"] = str(slot.section_id)

        serializer = SectionTimeSlotSerializer(
            slot,
            data=payload,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        slot = self.get_object(id)
        slot.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SectionTimeSlotCopyView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get_section(self, section_id: str) -> Section:
        try:
            return Section.objects.select_related("grade_level").get(id=section_id)
        except Section.DoesNotExist as exc:
            raise NotFound("Section does not exist with this id") from exc

    def post(self, request, section_id):
        target_section = self.get_section(section_id)
        source_section_id = request.data.get("source_section_id")

        seeded_count, source = initialize_section_time_slots(
            section=target_section,
            source_section_id=source_section_id,
            user=request.user,
            replace_existing=True,
        )

        return Response(
            {
                "detail": "Section timetable copied successfully.",
                "seeded_count": seeded_count,
                "source": source,
            },
            status=status.HTTP_200_OK,
        )


class SectionTimeSlotGenerateView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get_section(self, section_id: str) -> Section:
        try:
            return Section.objects.select_related("grade_level").get(id=section_id)
        except Section.DoesNotExist as exc:
            raise NotFound("Section does not exist with this id") from exc

    def post(self, request, section_id):
        section = self.get_section(section_id)

        seeded_count, source = regenerate_section_time_slots_from_template(
            section=section,
            user=request.user,
        )

        return Response(
            {
                "detail": "Section timetable generated successfully.",
                "seeded_count": seeded_count,
                "source": source,
            },
            status=status.HTTP_200_OK,
        )
