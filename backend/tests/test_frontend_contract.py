"""
The frontend/backend route contract.

Every API call a page makes must be a route this app serves. The frontend was
ported wholesale from the `Emergent/SharePlate-main` app while the backend was
built one slice at a time, so pages exist for endpoints that do not: the
restaurant order queue and the image upload field both got built against calls
nothing answered until the routes were added by hand. This test is the thing
that should have failed first.

How it works: the frontend's axios calls are scanned for URLs built from the
app's API base, the base names themselves are discovered from the source (so a
page using a new constant is still covered - `API_BASE` in lib/images.js is not
the `${API}` idiom most pages use), and every call is resolved against the
route table `app.main` actually serves.

It is a two-sided contract:

  * a call that is neither served nor listed in KNOWN_MISSING fails;
  * a KNOWN_MISSING entry that has since been implemented fails, so the
    inventory cannot quietly rot as slices land;
  * a KNOWN_MISSING entry no page calls any more fails, so it stays exact.

KNOWN_MISSING is the honest inventory of what the UI expects and the backend
does not yet serve. Removing entries is the point; adding them should require
building a page against an endpoint that does not exist.
"""

import re
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

import pytest

# --------------------------------------------------------------------------
# What the frontend calls
# --------------------------------------------------------------------------

# tests/ -> backend/ -> Evolved/
FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"

SOURCE_SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}

# axios.get(`${API}/restaurants`, ...) - the URL is the first argument, and it
# is often on its own line, hence DOTALL.
AXIOS_CALL = re.compile(
    r"axios\.(?P<method>get|post|put|patch|delete)\s*\(\s*[`'\"](?P<url>[^`'\"]*)[`'\"]",
    re.S,
)

# A constant built from the configured backend host, e.g.
#   const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
BASE_FROM_HOST = re.compile(
    r"(?:export\s+)?const\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*[^;\n]*REACT_APP_BACKEND_URL"
)

# ...and one derived from another base, e.g. `const API_BASE = `${BACKEND_URL}/api`;`
DERIVED_BASE = re.compile(
    r"(?:export\s+)?const\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*`\$\{(?P<parent>[A-Za-z_$][\w$]*)\}"
)

PLACEHOLDER = re.compile(r"\$\{[^}]*\}")

Call = Tuple[str, str]  # (method, normalised path)


def source_files(src: Path = FRONTEND_SRC) -> List[Path]:
    return sorted(
        path for path in src.rglob("*") if path.suffix in SOURCE_SUFFIXES and path.is_file()
    )


def api_base_names(texts: Iterable[str]) -> Set[str]:
    """
    The identifiers the frontend uses as an API base.

    Discovered rather than assumed: several pages define `API` from
    REACT_APP_BACKEND_URL, and `lib/images.js` derives `API_BASE` from its own
    `BACKEND_URL`, so both a direct and a one-step-derived constant are found.
    """
    texts = list(texts)
    names = {match.group("name") for text in texts for match in BASE_FROM_HOST.finditer(text)}

    # Follow derivations until nothing new turns up.
    added = True
    while added:
        added = False
        for text in texts:
            for match in DERIVED_BASE.finditer(text):
                if match.group("parent") in names and match.group("name") not in names:
                    names.add(match.group("name"))
                    added = True

    return names


def normalise(raw_url: str) -> str:
    """
    Turn a template URL into a comparable path.

    `${API}/orders/${orderId}/status?status=${s}` becomes `/orders/{param}/status`:
    the base and the query are dropped (neither is part of the route), and
    anything that interpolates is a path parameter, including a variable glued
    to a literal (`orders${params}` is still the `orders` segment).

    The base has to go before the split: `${API}` is itself a whole segment and
    would otherwise be mistaken for a path parameter. The rest is per segment,
    so a parameter keeps its position instead of collapsing the path.
    """
    path = raw_url.split("?", 1)[0]
    path = re.sub(r"^\s*\$\{[^}]*\}", "", path)  # the API base

    segments = []
    for segment in path.split("/"):
        if not segment:
            continue
        literal = PLACEHOLDER.sub("", segment).strip()
        segments.append(literal if literal else "{param}")

    return "/" + "/".join(segments)


# Any place a page reaches for the network. A call the scanner cannot read is a
# call it cannot check, which is how the gap this guards against comes back.
CALL_SITE = re.compile(r"(?:axios\.(?:get|post|put|patch|delete)|\bfetch)\s*\(")

# Base references that are deliberately not API calls: lib/images.js builds an
# image URL (a stored /uploads/<name> path) from BACKEND_URL. Anything else
# mentioning a base outside a call is a call this scan is blind to.
NON_API_BASE_USES = {("images.js", "${BACKEND_URL}")}


def scan_calls(sources: Dict[Path, str], bases: Set[str]) -> Dict[Call, Set[str]]:
    """{(method, path): {files that call it}} for every call built on an API base."""
    calls: Dict[Call, Set[str]] = {}
    for path, text in sources.items():
        for match in AXIOS_CALL.finditer(text):
            url = match.group("url")
            if not any(f"${{{base}}}" in url for base in bases):
                continue
            key = (match.group("method").upper(), normalise(url))
            calls.setdefault(key, set()).add(path.name)

    return calls


def line_of(text: str, position: int) -> Tuple[int, str]:
    """The line number and trimmed text containing an offset."""
    line = text.count("\n", 0, position) + 1
    start = text.rfind("\n", 0, position) + 1
    end = text.find("\n", position)
    return line, text[start:end if end != -1 else len(text)].strip()


def unread_call_sites(sources: Dict[Path, str]) -> List[Tuple[str, int, str]]:
    """Call sites whose URL is not a literal the scanner can read."""
    found: List[Tuple[str, int, str]] = []
    for path, text in sources.items():
        readable = {match.start() for match in AXIOS_CALL.finditer(text)}
        for match in CALL_SITE.finditer(text):
            if match.start() in readable:
                continue
            line, snippet = line_of(text, match.start())
            found.append((path.name, line, snippet))
    return found


def misplaced_base_uses(
    sources: Dict[Path, str], bases: Set[str]
) -> List[Tuple[str, int, str, str]]:
    """API base references that are neither a base definition nor a readable call."""
    found: List[Tuple[str, int, str, str]] = []
    for path, text in sources.items():
        readable = [match.span("url") for match in AXIOS_CALL.finditer(text)]
        for base in sorted(bases):
            token = f"${{{base}}}"
            for match in re.finditer(re.escape(token), text):
                position = match.start()
                line, snippet = line_of(text, position)
                if BASE_FROM_HOST.search(snippet) or DERIVED_BASE.search(snippet):
                    continue  # the definition of a base, not a use of one
                if any(start <= position <= end for start, end in readable):
                    continue  # inside a call the scanner read
                if (path.name, token) in NON_API_BASE_USES:
                    continue
                found.append((path.name, line, snippet, token))
    return found


# --------------------------------------------------------------------------
# What the backend serves
# --------------------------------------------------------------------------


def api_routes() -> Set[Call]:
    """
    {(METHOD, path)} for every route under /api, parameters normalised.

    Read from the OpenAPI schema rather than by walking `app.routes`: FastAPI
    keeps included routers wrapped in `fastapi.routing._IncludedRouter`, so the
    flat route list holds only the app's own routes and this would silently see
    an almost empty backend.
    """
    from app.main import app

    routes: Set[Call] = set()
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api"):
            continue
        for method in operations:
            routes.add((method.upper(), normalise(path[len("/api"):])))

    return routes


def segments(path: str) -> List[str]:
    return [segment for segment in path.split("/") if segment]


def is_served(call: Call, routes: Iterable[Call]) -> bool:
    """Whether any route matches the call, parameter against parameter."""
    method, path = call
    call_segments = segments(path)

    for route_method, route_path in routes:
        if route_method != method:
            continue
        route_segments = segments(route_path)
        if len(route_segments) != len(call_segments):
            continue

        if all(
            called.startswith("{") or served.startswith("{") or called == served
            for called, served in zip(call_segments, route_segments)
        ):
            return True

    return False


# --------------------------------------------------------------------------
# The inventory of UI calls with no route behind them yet
# --------------------------------------------------------------------------

# Grouped the way the README lists them. Each entry is a screen that will error
# until its endpoints land.
KNOWN_MISSING: Set[Call] = {
    # Auth - Google/OAuth was brokered by Emergent and is not wired up; the
    # password login that replaced it needs no session exchange.
    ("POST", "/auth/session"),
}


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sources() -> Dict[Path, str]:
    if not FRONTEND_SRC.is_dir():
        pytest.skip(f"frontend sources not present at {FRONTEND_SRC}")
    return {
        path: path.read_text(encoding="utf-8", errors="replace")
        for path in source_files()
    }


@pytest.fixture(scope="module")
def bases(sources) -> Set[str]:
    return api_base_names(sources.values())


@pytest.fixture(scope="module")
def calls(sources, bases) -> Dict[Call, Set[str]]:
    return scan_calls(sources, bases)


@pytest.fixture(scope="module")
def routes() -> Set[Call]:
    return api_routes()


# --------------------------------------------------------------------------
# The scan works at all
# --------------------------------------------------------------------------


def test_the_scan_finds_the_frontends_api_calls(calls, routes):
    """
    A guard that silently scans nothing passes everything, so the harness has to
    prove it found the calls that exist. `/uploads` is the one that used the
    derived API_BASE constant, so it is the canary for base discovery.
    """
    assert len(source_files()) > 20
    assert len(calls) > 20
    assert ("GET", "/restaurants") in calls
    assert ("POST", "/uploads") in calls, "API_BASE in lib/images.js was not discovered"
    assert ("PUT", "/orders/{param}/status") in calls

    # and the route side is real too
    assert ("GET", "/restaurants") in routes
    assert ("PUT", "/orders/{order_id}/status") in routes


def test_the_matcher_actually_discriminates(calls, routes):
    """Otherwise everything below could pass by matching anything to anything."""
    assert is_served(("GET", "/restaurants"), routes)
    assert is_served(("PUT", "/orders/anything/status"), routes)
    assert not is_served(("GET", "/surplus/anything/extra"), routes)
    assert not is_served(("DELETE", "/surplus"), routes)
    assert not is_served(("POST", "/restaurants/anything/orders"), routes)
    assert not is_served(("GET", "/restaurants/anything/orders/extra"), routes)


def test_the_scan_can_read_every_call_site(sources, bases):
    """
    A call whose URL the scanner cannot read is a call it cannot check - exactly
    the silent gap this file exists to prevent. Every network call site in the
    frontend must be one the scanner understands.
    """
    unread = unread_call_sites(sources)

    assert not unread, (
        "network calls this scan cannot read (it reads axios.<method>(`<url>`); "
        "convert the call, extend the scanner, or list it in NON_API_BASE_USES if "
        "it is not a backend API call):\n"
        + "\n".join(f"  {name}:{line}  {snippet}" for name, line, snippet in unread)
    )
    assert bases, "no API base constants were discovered, so nothing was scanned"


def test_every_api_base_reference_is_a_call_the_scan_read(sources, bases):
    """
    The other half of the same idea: a base used somewhere the scanner does not
    parse (assigned to a variable, hidden in a helper, used by fetch) would hide
    its endpoint from the contract check.
    """
    misplaced = misplaced_base_uses(sources, bases)

    assert not misplaced, (
        "API base used outside any call the scan could read:\n"
        + "\n".join(
            f"  {name}:{line}  {token}  ->  {snippet}"
            for name, line, snippet, token in misplaced
        )
    )


def test_query_strings_are_not_part_of_the_route():
    assert normalise("${API}/orders/${id}/status?status=${next}") == "/orders/{param}/status"
    assert normalise("${API}/support/questions?${params}") == "/support/questions"
    assert normalise("${API}/restaurants/${restaurant.restaurant_id}/orders${statusParam}") == (
        "/restaurants/{param}/orders"
    )


# --------------------------------------------------------------------------
# The vocabulary the screens use has to exist in the models
# --------------------------------------------------------------------------

# The driver form's vehicle picker. The page has exactly one Select; a second
# one means these options are no longer all vehicles, and this test will say so.
DRIVER_PAGE = FRONTEND_SRC / "pages" / "DriverDeliveries.js"
SELECT_ITEM = re.compile(r"SelectItem value=\"([^\"]+)\"")


def test_the_vehicles_the_driver_form_offers_are_real_vehicle_types():
    """
    The form offered "walk" while VehicleType did not define it, so the page's
    own choice was rejected by the API. Options and model have to agree.
    """
    from app.models.general import VehicleType

    if not DRIVER_PAGE.is_file():
        pytest.skip(f"frontend sources not present at {DRIVER_PAGE}")

    offered = set(SELECT_ITEM.findall(DRIVER_PAGE.read_text(encoding="utf-8")))
    assert offered, "no SelectItem values found - the page was restructured"

    unknown = offered - {vehicle.value for vehicle in VehicleType}
    assert not unknown, (
        f"the driver form offers values VehicleType does not define: {sorted(unknown)}. "
        "Add them to VehicleType, or take them off the form."
    )


# --------------------------------------------------------------------------
# Money on the screens has to be the money the API charged
# --------------------------------------------------------------------------

# `total_amount` is the whole bill - subtotal plus delivery fee plus tip, priced
# in app/pricing.py - while `delivery_fee` is one slice of it. Two screens were
# written against the Emergent API, where the total left the fee out, and added
# the two together: an $8.99 order read as $11.98 on the list and in tracking,
# while checkout had charged $8.99. Any line that recombines them fails here.
DOUBLE_CHARGED = re.compile(r"total_amount[^;\n]*\+[^;\n]*delivery_fee")


def test_no_screen_adds_the_delivery_fee_to_the_total_again():
    offenders = []
    for path in sorted(FRONTEND_SRC.rglob("*.js")):
        if "node_modules" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            if DOUBLE_CHARGED.search(line):
                offenders.append(
                    f"  {path.relative_to(FRONTEND_SRC)}:{number}  {line.strip()}"
                )

    assert not offenders, (
        "total_amount already includes the delivery fee; these lines add it a "
        "second time:\n" + "\n".join(offenders)
    )


# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------


def test_every_frontend_call_is_served(calls, routes):
    """The guard: a page calling an endpoint that does not exist fails here."""
    unserved = {
        call: sorted(where)
        for call, where in calls.items()
        if not is_served(call, routes) and call not in KNOWN_MISSING
    }

    assert not unserved, (
        "frontend calls the backend does not serve:\n"
        + "\n".join(
            f"  {method:6} {path:52} called by {', '.join(where)}"
            for (method, path), where in sorted(unserved.items())
        )
        + "\n\nImplement the route, or add it to KNOWN_MISSING with the screen it blocks."
    )


def test_the_known_missing_list_has_not_gone_stale(routes):
    """An entry that has since been implemented must be deleted from the list."""
    now_served = sorted(call for call in KNOWN_MISSING if is_served(call, routes))

    assert not now_served, (
        "these are listed as missing but the backend now serves them - remove them "
        "from KNOWN_MISSING:\n"
        + "\n".join(f"  {method:6} {path}" for method, path in now_served)
    )


def test_the_known_missing_list_holds_nothing_unused(calls):
    """An entry no screen calls any more is dead weight hiding a real gap."""
    unused = sorted(call for call in KNOWN_MISSING if call not in calls)

    assert not unused, (
        "listed as missing but nothing calls them - remove them from KNOWN_MISSING:\n"
        + "\n".join(f"  {method:6} {path}" for method, path in unused)
    )


def test_the_inventory_is_complete(calls, routes):
    """Every call is exactly one of: served, or listed as missing."""
    served = {call for call in calls if is_served(call, routes)}
    missing = {call for call in calls if not is_served(call, routes)}

    assert served | missing == set(calls)
    assert not (served & missing)
    assert missing <= KNOWN_MISSING
