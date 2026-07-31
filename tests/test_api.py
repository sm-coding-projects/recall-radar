"""API route tests.

The database layer is stubbed so these run without Postgres. That keeps the
suite hermetic and fast; the real SQL is exercised against Neon in Step 9.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api import db as api_db
from api import main as api_main
from api.main import app

ROW = {
    "id": 1,
    "agency": "FDA",
    "source_id": "H-1166-2026",
    "product": "Ice Pop, 1 Bar (81.7 g)",
    "brand": "D'Dioses Fruit Pops, Inc.",
    "category": "Food",
    "hazard": "May contain undeclared milk.",
    "classification": "Class I",
    "recall_date": date(2026, 5, 4),
    "published_at": datetime(2026, 7, 22, tzinfo=timezone.utc),
    "url": "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts",
    "ingested_at": datetime(2026, 7, 31, tzinfo=timezone.utc),
}


@pytest.fixture
def stub_db(monkeypatch):
    """Record every query the routes issue, and serve canned rows."""
    calls: list[tuple[str, object]] = []

    def fetch_all(sql, params=None):
        calls.append((sql, params))
        return [ROW]

    def fetch_one(sql, params=None):
        calls.append((sql, params))
        return ROW

    def fetch_value(sql, params=None):
        calls.append((sql, params))
        return 1

    monkeypatch.setattr(api_db, "fetch_all", fetch_all)
    monkeypatch.setattr(api_db, "fetch_one", fetch_one)
    monkeypatch.setattr(api_db, "fetch_value", fetch_value)
    return calls


@pytest.fixture
def client(stub_db, monkeypatch):
    monkeypatch.delenv("RAPIDAPI_PROXY_SECRET", raising=False)
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------------------------------
# /health
# --------------------------------------------------------------------------

class TestHealth:
    def test_reports_ok_when_the_database_answers(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"
        assert body["recalls"] == 1

    def test_degrades_rather_than_500s_when_the_database_is_down(self, client, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(api_db, "fetch_value", boom)
        response = client.get("/health")
        # Render's health check must not flap the service when Neon is asleep.
        assert response.status_code == 200
        assert response.json()["status"] == "degraded"
        assert response.json()["database"] == "unavailable"


# --------------------------------------------------------------------------
# /recalls
# --------------------------------------------------------------------------

class TestListRecalls:
    def test_returns_the_standard_envelope(self, client):
        body = client.get("/recalls").json()
        assert set(body) == {"data", "pagination", "meta"}
        assert body["data"][0]["source_id"] == "H-1166-2026"
        assert body["pagination"]["per_page"] == 25

    def test_rejects_per_page_above_the_cap(self, client):
        response = client.get("/recalls", params={"per_page": 101})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_parameters"

    def test_accepts_per_page_at_the_cap(self, client):
        assert client.get("/recalls", params={"per_page": 100}).status_code == 200

    def test_rejects_an_inverted_date_range(self, client):
        response = client.get("/recalls", params={"since": "2026-07-01", "until": "2026-06-01"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "bad_request"

    def test_rejects_a_malformed_date(self, client):
        assert client.get("/recalls", params={"since": "not-a-date"}).status_code == 422

    def test_agency_filter_is_case_insensitive(self, client, stub_db):
        client.get("/recalls", params={"agency": "fda"})
        assert any((p or {}).get("agency") == "FDA" for _, p in stub_db)

    def test_applies_every_filter(self, client, stub_db):
        client.get("/recalls", params={
            "agency": "CPSC", "category": "toy", "since": "2026-01-01", "until": "2026-07-31",
        })
        sql, params = stub_db[-1]
        for fragment in ("agency = ", "category ILIKE", "recall_date >=", "recall_date <="):
            assert fragment in sql
        assert params["category"] == "%toy%"
        assert params["since"] == date(2026, 1, 1)

    def test_sorts_newest_first(self, client, stub_db):
        client.get("/recalls")
        assert "ORDER BY recall_date DESC NULLS LAST" in stub_db[-1][0]

    def test_offset_follows_the_page_number(self, client, stub_db):
        client.get("/recalls", params={"page": 3, "per_page": 10})
        assert stub_db[-1][1]["offset"] == 20

    def test_pagination_flags(self, client, monkeypatch):
        monkeypatch.setattr(api_db, "fetch_value", lambda *a, **k: 250)
        page = client.get("/recalls", params={"page": 2, "per_page": 100}).json()["pagination"]
        assert page == {"page": 2, "per_page": 100, "total": 250,
                        "total_pages": 3, "has_next": True, "has_prev": True}


# --------------------------------------------------------------------------
# /recalls/latest
# --------------------------------------------------------------------------

class TestLatest:
    def test_requests_exactly_fifty(self, client, stub_db):
        body = client.get("/recalls/latest").json()
        assert body["meta"]["limit"] == 50
        assert stub_db[-1][1]["limit"] == 50

    def test_is_not_shadowed_by_the_detail_route(self, client):
        # /recalls/latest must not be parsed as agency="latest".
        assert "limit" in client.get("/recalls/latest").json()["meta"]


# --------------------------------------------------------------------------
# /recalls/search
# --------------------------------------------------------------------------

class TestSearch:
    def test_uses_the_generated_tsvector_column(self, client, stub_db):
        client.get("/recalls/search", params={"q": "listeria"})
        sql = stub_db[-1][0]
        # Querying search_tsv directly is what lets the GIN index be used.
        assert "search_tsv @@ websearch_to_tsquery" in sql
        assert "ts_rank_cd" in sql

    def test_requires_a_query(self, client):
        assert client.get("/recalls/search").status_code == 422

    def test_rejects_a_single_character_query(self, client):
        assert client.get("/recalls/search", params={"q": "a"}).status_code == 422

    def test_survives_punctuation_that_would_break_to_tsquery(self, client):
        # websearch_to_tsquery degrades gracefully where to_tsquery raises.
        assert client.get("/recalls/search", params={"q": "chicken & | ! foo'"}).status_code == 200

    def test_echoes_the_query_in_meta(self, client):
        assert client.get("/recalls/search", params={"q": "salmonella"}).json()["meta"]["query"] == "salmonella"


# --------------------------------------------------------------------------
# /recalls/{agency}/{source_id}
# --------------------------------------------------------------------------

class TestGetRecall:
    def test_returns_a_single_item_envelope(self, client):
        body = client.get("/recalls/FDA/H-1166-2026").json()
        assert set(body) == {"data", "meta"}
        assert body["data"]["source_id"] == "H-1166-2026"

    def test_uppercases_the_agency(self, client, stub_db):
        client.get("/recalls/fda/H-1166-2026")
        assert stub_db[-1][1]["agency"] == "FDA"

    def test_404s_with_a_clean_envelope(self, client, monkeypatch):
        monkeypatch.setattr(api_db, "fetch_one", lambda *a, **k: None)
        response = client.get("/recalls/FDA/does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_handles_source_ids_containing_slashes(self, client, stub_db):
        client.get("/recalls/FSIS/011/2026")
        assert stub_db[-1][1]["source_id"] == "011/2026"


# --------------------------------------------------------------------------
# Auth middleware
# --------------------------------------------------------------------------

class TestProxySecret:
    @pytest.fixture
    def secured(self, stub_db, monkeypatch):
        monkeypatch.setenv("RAPIDAPI_PROXY_SECRET", "s3cret-value")
        with TestClient(app) as test_client:
            yield test_client

    def test_health_stays_open(self, secured):
        assert secured.get("/health").status_code == 200

    def test_rejects_a_missing_header(self, secured):
        response = secured.get("/recalls")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"

    def test_rejects_a_wrong_header(self, secured):
        assert secured.get("/recalls", headers={"X-RapidAPI-Proxy-Secret": "nope"}).status_code == 401

    def test_accepts_the_correct_header(self, secured):
        response = secured.get("/recalls", headers={"X-RapidAPI-Proxy-Secret": "s3cret-value"})
        assert response.status_code == 200

    def test_header_name_is_case_insensitive(self, secured):
        # HTTP header names are case-insensitive; RapidAPI's casing varies.
        assert secured.get("/recalls", headers={"x-rapidapi-proxy-secret": "s3cret-value"}).status_code == 200

    def test_protects_every_data_route(self, secured):
        for path in ("/recalls", "/recalls/latest", "/recalls/search?q=test", "/recalls/FDA/H-1"):
            assert secured.get(path).status_code == 401, path

    def test_open_when_the_secret_is_unset(self, client):
        assert client.get("/recalls").status_code == 200


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------

class TestBlankQueryParams:
    """API gateways send unset optional params as empty strings.

    RapidAPI's playground issues `?agency=&category=&since=&until=&page=&per_page=`
    for a call with no filters. Before this was handled, every one of those
    requests 422'd on the date and int params, making the playground -- the
    first thing a prospective buyer touches -- look broken.

    A blank value must mean "not supplied". A wrong value must still be an error.
    """

    RAPIDAPI_STYLE = "/recalls?agency=&category=&since=&until=&page=&per_page="

    def test_all_params_blank_succeeds(self, client):
        assert client.get(self.RAPIDAPI_STYLE).status_code == 200

    def test_all_params_blank_matches_no_params_at_all(self, client):
        blank = client.get(self.RAPIDAPI_STYLE).json()
        bare = client.get("/recalls").json()
        assert blank["pagination"] == bare["pagination"]
        assert blank["meta"] == bare["meta"]

    @pytest.mark.parametrize("param", ["agency", "category", "since", "until", "page", "per_page"])
    def test_each_param_individually_blank(self, client, param):
        assert client.get(f"/recalls?{param}=").status_code == 200

    def test_blank_filters_are_not_applied(self, client, stub_db):
        client.get(self.RAPIDAPI_STYLE)
        sql, params = stub_db[-1]
        for fragment in ("agency = ", "category ILIKE", "recall_date >=", "recall_date <="):
            assert fragment not in sql, f"blank param produced a {fragment!r} filter"

    def test_blank_filters_absent_from_meta(self, client):
        assert client.get(self.RAPIDAPI_STYLE).json()["meta"]["filters"] == {}

    def test_blank_pagination_falls_back_to_defaults(self, client):
        page = client.get("/recalls?page=&per_page=").json()["pagination"]
        assert page["page"] == 1
        assert page["per_page"] == 25

    def test_whitespace_only_is_treated_as_blank(self, client):
        assert client.get("/recalls?since=%20&until=%20&page=%20").status_code == 200

    def test_search_accepts_blank_optional_params(self, client):
        assert client.get("/recalls/search?q=listeria&agency=&page=&per_page=").status_code == 200

    # ---- blanks are forgiven; wrong values are not -------------------------

    @pytest.mark.parametrize(
        "url",
        [
            "/recalls?since=banana",
            "/recalls?until=2026-13-45",
            "/recalls?page=abc",
            "/recalls?page=0",
            "/recalls?page=-1",
            "/recalls?per_page=0",
            "/recalls?per_page=101",
            "/recalls/search?q=listeria&per_page=101",
        ],
    )
    def test_genuinely_invalid_values_still_422(self, client, url):
        response = client.get(url)
        assert response.status_code == 422, url
        assert response.json()["error"]["code"] == "invalid_parameters"

    def test_invalid_value_names_the_offending_field(self, client):
        detail = client.get("/recalls?per_page=101").json()["error"]["detail"]
        assert detail[0]["field"] == "per_page"
        assert "100" in detail[0]["reason"]

    def test_blank_required_query_is_still_rejected(self, client):
        # q is required and meaningless when empty -- unlike the optional filters.
        assert client.get("/recalls/search?q=").status_code == 422

    def test_bounds_are_enforced_without_500ing(self, client):
        """Regression guard.

        Declaring ge/le on the outer `int | None` made Pydantic try to apply
        the constraint to None, raising TypeError -> HTTP 500. The bound has to
        live on the int member of the union.
        """
        for url in ("/recalls?page=", "/recalls?per_page=", "/recalls?page=0"):
            assert client.get(url).status_code != 500, url


class TestOpenAPI:
    """The spec is the product surface on RapidAPI, so it is tested like one."""

    @pytest.fixture
    def spec(self):
        app.openapi_schema = None  # rebuild rather than reuse a cached schema
        return app.openapi()

    def test_declares_the_production_server(self, spec):
        assert spec["servers"] == [
            {"url": "https://recall-radar.onrender.com", "description": "Production"}
        ]

    def test_every_route_sets_an_explicit_summary(self):
        """Checked on the route objects, not the spec.

        FastAPI synthesizes a summary from the function name ("List Recalls")
        when none is given, so asserting the spec has *a* summary passes even
        when nothing was written. `route.summary` is None unless set.
        """
        from fastapi.routing import APIRoute

        for route in app.routes:
            if not isinstance(route, APIRoute) or route.path in {
                "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect",
            }:
                continue
            assert route.summary, f"{route.path} has no explicit summary="
            # A hand-written summary should not just be the function name.
            assert route.summary.lower() != route.name.replace("_", " ").lower(), (
                f"{route.path} summary merely restates the function name"
            )

    def test_every_route_has_a_meaningful_description(self, spec):
        for path, operations in spec["paths"].items():
            for method, op in operations.items():
                assert len((op.get("description") or "").strip()) > 50, (
                    f"{method.upper()} {path} has no meaningful description"
                )

    def test_every_route_has_a_200_example(self, spec):
        for path, operations in spec["paths"].items():
            for method, op in operations.items():
                example = (
                    op["responses"]["200"].get("content", {})
                    .get("application/json", {}).get("example")
                )
                assert example is not None, f"{method.upper()} {path} has no 200 example"

    def test_authenticated_routes_document_401(self, spec):
        for path, operations in spec["paths"].items():
            if path == "/health":
                continue  # deliberately public
            for method, op in operations.items():
                assert "401" in op["responses"], f"{method.upper()} {path} does not document 401"

    def test_error_examples_use_the_error_envelope(self, spec):
        for path, operations in spec["paths"].items():
            for op in operations.values():
                for status, response in op["responses"].items():
                    if not status.startswith(("4", "5")):
                        continue
                    example = response.get("content", {}).get("application/json", {}).get("example")
                    if example is None:
                        continue
                    assert set(example) == {"error"}, f"{path} {status} is not an error envelope"
                    assert {"code", "message"} <= set(example["error"])

    def test_documented_route_set_is_exactly_the_five_public_endpoints(self, spec):
        assert set(spec["paths"]) == {
            "/health", "/recalls", "/recalls/latest", "/recalls/search",
            "/recalls/{agency}/{source_id}",
        }

    def test_spec_is_served(self, client):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        assert response.json()["info"]["title"] == "recall-radar"

    def test_operation_ids_are_clean_camel_case(self, spec):
        """RapidAPI shows operationId as the endpoint name.

        FastAPI's default is the mangled `list_recalls_recalls_get`, which
        looks unprofessional on a paid listing.
        """
        found = {
            op["operationId"]
            for operations in spec["paths"].values()
            for op in operations.values()
        }
        assert found == {
            "getHealth", "listRecalls", "getLatestRecalls",
            "searchRecalls", "getRecallById",
        }
        for operation_id in found:
            assert "_" not in operation_id, f"{operation_id} is not camelCase"
            assert not operation_id.endswith("_get")

    def test_optional_query_params_are_documented_as_not_required(self, spec):
        # Scoped to `in: query` -- `agency` is also a path param on the detail
        # route, where being required is correct.
        optional = {"agency", "category", "since", "until", "page", "per_page"}
        checked = 0
        for path, operations in spec["paths"].items():
            for op in operations.values():
                for param in op.get("parameters", []):
                    if param["in"] == "query" and param["name"] in optional:
                        assert param["required"] is False, f"{path}:{param['name']}"
                        checked += 1
        assert checked >= 9, f"expected to check ~10 optional query params, saw {checked}"

    def test_every_parameter_has_a_top_level_example(self, spec):
        """API consoles prefill from parameter-level `example`, not schema.examples.

        FastAPI nests examples inside the parameter schema, which RapidAPI's
        playground ignores -- so it submitted blanks and made working
        endpoints return 422 and 404 on the listing.
        """
        for path, operations in spec["paths"].items():
            for op in operations.values():
                for param in op.get("parameters", []):
                    assert "example" in param, (
                        f"{path}:{param['name']} has no parameter-level example, "
                        "so a console will submit it blank"
                    )

    def test_requests_built_from_the_spec_examples_succeed(self, client, spec):
        """The playground scenario, end to end.

        Fills every parameter with the example the spec advertises and calls
        the endpoint. This is what a buyer's first click does, so it must not
        return 4xx.
        """
        for path, operations in spec["paths"].items():
            for op in operations.values():
                url = path
                query = {}
                for param in op.get("parameters", []):
                    value = param["example"]
                    if param["in"] == "path":
                        url = url.replace("{" + param["name"] + "}", str(value))
                    else:
                        query[param["name"]] = value
                response = client.get(url, params=query)
                assert response.status_code == 200, (
                    f"{op['operationId']} -> {response.status_code} "
                    f"for {url} {query}"
                )

    def test_pagination_bounds_survive_in_the_schema(self, spec):
        """The ge/le bounds moved inside the union; they must still be published."""
        params = {
            p["name"]: p
            for p in spec["paths"]["/recalls"]["get"]["parameters"]
        }
        per_page = json.dumps(params["per_page"]["schema"])
        assert "100" in per_page and "maximum" in per_page
        assert "minimum" in json.dumps(params["page"]["schema"])


class TestErrors:
    def test_unhandled_errors_do_not_leak_internals(self, client, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("postgresql://user:hunter2@host/db")

        monkeypatch.setattr(api_db, "fetch_value", boom)
        client_no_raise = TestClient(app, raise_server_exceptions=False)
        response = client_no_raise.get("/recalls")

        assert response.status_code == 500
        body = response.text
        assert "hunter2" not in body and "postgresql://" not in body
        assert response.json()["error"]["code"] == "internal_error"

    def test_unknown_route_404s(self, client):
        assert client.get("/nope").status_code == 404
