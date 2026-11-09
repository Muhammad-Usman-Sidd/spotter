class ServiceError(Exception):
    """Base class for failures the API reports to the client with a stable code."""

    status_code: int = 502
    code: str = "service_error"


class GeocodingError(ServiceError):
    status_code = 422
    code = "geocoding_failed"


class RoutingError(ServiceError):
    code = "routing_failed"


class NoRouteError(RoutingError):
    status_code = 422
    code = "no_route"


class WeatherError(ServiceError):
    code = "weather_failed"


class PlanningError(ServiceError):
    status_code = 422
    code = "planning_failed"
