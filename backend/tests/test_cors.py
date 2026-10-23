"""
What the API lets a browser call it from.

A preview deployment lives on a hostname nobody can know in advance
(`pr-<number>.<project>.pages.dev`), so it can only be admitted by pattern - and
a pattern is exactly the kind of setting that ends up too wide. These tests pin
both halves: the settings are read the way the README says, and the middleware
actually refuses an origin the pattern does not cover.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.cors import allowed_origin_regex, allowed_origins

# The project is named on purpose: a pattern that accepts any `*.pages.dev`
# would open the API to every site hosted on Pages, not just this one's previews.
PREVIEW = "https://pr-42.shareplate.pages.dev"
PREVIEW_PATTERN = r"https://pr-\d+\.shareplate\.pages\.dev$"


def _app(environ: dict) -> FastAPI:
    """The app's CORS wiring, on an app small enough to answer one request."""
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(environ),
        allow_origin_regex=allowed_origin_regex(environ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    return app


def _allowed_origin(environ: dict, origin: str):
    response = TestClient(_app(environ)).get("/api/ping", headers={"Origin": origin})
    return response.headers.get("access-control-allow-origin")


# --------------------------------------------------------------------------
# Reading the settings
# --------------------------------------------------------------------------


def test_the_dev_servers_need_no_configuration():
    origins = allowed_origins({})
    assert "http://localhost:3000" in origins
    assert "http://localhost:5173" in origins


def test_extra_origins_are_split_and_trimmed():
    origins = allowed_origins({"FRONTEND_ORIGINS": " https://a.example , ,https://b.example ,"})
    assert "https://a.example" in origins
    assert "https://b.example" in origins
    assert "" not in origins
    assert len(origins) == 4  # the two dev ports and the two named ones


def test_there_is_no_pattern_unless_one_is_set():
    assert allowed_origin_regex({}) is None
    assert allowed_origin_regex({"FRONTEND_ORIGIN_REGEX": "   "}) is None
    assert allowed_origin_regex({"FRONTEND_ORIGIN_REGEX": PREVIEW_PATTERN}) == PREVIEW_PATTERN


# --------------------------------------------------------------------------
# What the middleware does with them
# --------------------------------------------------------------------------


def test_a_preview_is_refused_until_a_pattern_names_it():
    """The regression this file is for: previews pointing at a real API."""
    assert _allowed_origin({}, PREVIEW) is None

    admitted = _allowed_origin({"FRONTEND_ORIGIN_REGEX": PREVIEW_PATTERN}, PREVIEW)
    assert admitted == PREVIEW


def test_a_named_origin_is_still_admitted():
    environ = {"FRONTEND_ORIGINS": "https://shareplate.pages.dev"}
    assert _allowed_origin(environ, "https://shareplate.pages.dev") == (
        "https://shareplate.pages.dev"
    )


def test_a_preflight_from_a_preview_succeeds():
    response = TestClient(_app({"FRONTEND_ORIGIN_REGEX": PREVIEW_PATTERN})).options(
        "/api/ping",
        headers={
            "Origin": PREVIEW,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PREVIEW
    assert "authorization" in response.headers["access-control-allow-headers"]


def test_an_origin_that_only_looks_right_is_refused():
    """The reason the pattern is documented to end in `$`."""
    lookalike = "https://pr-42.shareplate.pages.dev.evil.example"
    assert _allowed_origin({"FRONTEND_ORIGIN_REGEX": PREVIEW_PATTERN}, lookalike) is None


def test_a_preview_of_another_project_is_refused():
    """One Pages project's previews must not open the API to another's."""
    other = "https://pr-42.somebody-else.pages.dev"
    assert _allowed_origin({"FRONTEND_ORIGIN_REGEX": PREVIEW_PATTERN}, other) is None


def test_the_test_suites_own_server_origin_is_allowed():
    """How the browser end-to-end test runs the dev server on an ephemeral port."""
    origin = "http://127.0.0.1:54321"
    assert _allowed_origin({"FRONTEND_ORIGINS": origin}, origin) == origin
