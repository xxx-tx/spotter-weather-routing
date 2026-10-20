"""Run without Django or network: python -m unittest discover -s scripts."""

from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

from smoke_live import main, SmokeError

from smoke_live import analyze_response


class SmokeContractTests(TestCase):
    def example(self):
        def route(i):
            return {"id": i, "name": f"Route {i + 1}", "distance_miles": 10,
                    "duration_minutes": 20 + i,
                    "is_recommended": i == 0,
                    "risk_summary": {"status": "eligible", "severe_miles": 0,
                                     "high_miles": 0, "coverage_percent": 100},
                    "checkpoints": [{"mile": 0, "risk": {"level": "Low"}},
                                    {"mile": 10, "risk": {"level": "Low"}}]}
        return {"routes": [route(0), route(1), route(2)],
                "recommended_route_id": 0,
                "weather_summary": {"available": 6, "total": 6},
                "heatmap": {"hour_count": 49, "samples": [{"hours": [None] * 49}]},
                "route_warning": None, "weather_warning": None}

    def test_valid_three_route_contract(self):
        errors, warnings, report = analyze_response(self.example())
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(report["recommendation_id"], 0)

    def test_legitimate_fewer_routes_is_warning_not_error(self):
        data = self.example()
        data["routes"] = data["routes"][:1]
        errors, warnings, _ = analyze_response(data)
        self.assertEqual(errors, [])
        self.assertTrue(any("Only 1" in item for item in warnings))

    def test_missing_weather_allows_no_recommendation(self):
        data = self.example()
        data["recommended_route_id"] = None
        for route in data["routes"]:
            route["is_recommended"] = False
            route["risk_summary"]["status"] = "incomplete"
        errors, _warnings, _report = analyze_response(data)
        self.assertEqual(errors, [])

    def test_recommending_incomplete_route_is_invalid(self):
        data = self.example()
        data["routes"][0]["risk_summary"]["status"] = "incomplete"
        errors, _warnings, _report = analyze_response(data)
        self.assertTrue(any("despite incomplete" in issue for issue in errors))

    def test_conflicting_recommendation_id_is_invalid(self):
        data = self.example()
        data["recommended_route_id"] = 1
        errors, _warnings, _report = analyze_response(data)
        self.assertTrue(any("disagree" in issue for issue in errors))

    def test_incorrect_heatmap_length_is_invalid(self):
        data = self.example()
        data["heatmap"]["samples"][0]["hours"] = [None] * 48
        errors, _warnings, _report = analyze_response(data)
        self.assertTrue(any("49 hourly values" in issue for issue in errors))

    def test_unsorted_checkpoints_are_invalid(self):
        data = self.example()
        data["routes"][0]["checkpoints"][1]["mile"] = 0
        errors, _warnings, _report = analyze_response(data)
        self.assertTrue(any("increasing mile order" in issue for issue in errors))

    def test_route_count_outside_contract(self):
        data = self.example()
        data["routes"].append(deepcopy(data["routes"][2]))
        errors, _warnings, _report = analyze_response(data)
        self.assertTrue(any("1–3" in issue for issue in errors))

    def test_weather_counts_cannot_exceed_total(self):
        data = self.example()
        data["weather_summary"]["available"] = 7
        errors, _warnings, _report = analyze_response(data)
        self.assertTrue(any("availability counts" in issue for issue in errors))

    def test_none_route_does_not_crash_analysis(self):
        data = self.example()
        data["routes"][1] = None
        errors, _warnings, _report = analyze_response(data)
        self.assertTrue(errors)

    def test_no_travel_route_cannot_be_recommended(self):
        data = self.example()
        data["routes"][0]["risk_summary"]["status"] = "no_travel"
        errors, _warnings, _report = analyze_response(data)
        self.assertTrue(any("despite no_travel" in issue for issue in errors))

    def test_unknown_weather_is_explicit_warning(self):
        data = self.example()
        data["weather_warning"] = "Forecast incomplete."
        _errors, warnings, _report = analyze_response(data)
        self.assertTrue(any("Forecast incomplete" in item for item in warnings))

    def test_successful_main_calls_all_three_endpoints(self):
        data = self.example()
        with patch("smoke_live.fetch_json", side_effect=[
            {"status": "ok"}, {"trip": {"origin": "A"}}, data,
        ]) as fetch, redirect_stdout(StringIO()) as stdout:
            result = main(["--origin", "A", "--destination", "B",
                           "--departure", "2026-10-22T12:00", "--load-weight", "12000",
                           "--confirm-live"])
        self.assertEqual(result, 0)
        self.assertEqual([call.args[1] for call in fetch.call_args_list],
                         ["/api/health/", "/api/trips/validate/", "/api/routes/"])
        self.assertIn("PASS", stdout.getvalue())

    def test_main_handles_provider_error_without_crashing(self):
        with patch("smoke_live.fetch_json", side_effect=SmokeError("Bad upstream")), \
                redirect_stderr(StringIO()) as stderr:
            result = main(["--origin", "A", "--destination", "B",
                           "--departure", "2026-10-22T12:00", "--load-weight", "12000",
                           "--confirm-live"])
        self.assertEqual(result, 1)
        self.assertIn("Bad upstream", stderr.getvalue())

    def test_live_confirmation_required_before_network_call(self):
        with patch("smoke_live.fetch_json") as fetch, redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                main(["--origin", "A", "--destination", "B",
                      "--departure", "2026-10-22T12:00", "--load-weight", "12000"])
        fetch.assert_not_called()
