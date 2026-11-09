from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import TripPlanRequestSerializer
from .services.errors import ServiceError
from .services.planner import TripPlanner
from .services.providers import build_default_providers


class HealthView(APIView):
    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class TripPlanView(APIView):
    """POST /api/plan/: validate, run the planner, map service errors to HTTP status codes.

    400 invalid input (from the serializer), 422 unknown place or no route, 502 upstream failure.
    """

    def post(self, request: Request) -> Response:
        serializer = TripPlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trip_request = serializer.to_trip_request()

        planner = TripPlanner(build_default_providers())
        try:
            plan = planner.plan(trip_request)
        except ServiceError as error:
            return Response({"detail": str(error), "code": error.code}, status=error.status_code)
        return Response(plan.to_dict())
