"""Limit expensive route requests by client IP."""

from rest_framework.throttling import SimpleRateThrottle


class _RouteThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class RouteMinuteThrottle(_RouteThrottle):
    scope = "routes_minute"


class RouteDailyThrottle(_RouteThrottle):
    scope = "routes_daily"
