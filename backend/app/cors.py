"""
Which browser origins may call this API.

The frontend is served from somewhere other than the API, so every one of those
somewheres has to be named: a developer's dev server on two ports, the published
site, and - for every pull request - a preview deployment on a hostname of its
own (`pr-<number>.<project>.pages.dev`). The app is served with credentials, so
a wildcard would let any site on the internet read a signed-in user's data; the
list stays explicit.

Previews cannot be listed ahead of time - there is one per pull request and they
appear and vanish with it - so they are matched by pattern instead:

    FRONTEND_ORIGINS       exact origins, comma-separated
                           e.g. https://shareplate.pages.dev
    FRONTEND_ORIGIN_REGEX  one pattern for the ones that cannot be listed
                           e.g. https://pr-\\d+\\.shareplate\\.pages\\.dev$
                           (name the project: `[a-z0-9-]+` in that position
                           would admit every preview hosted on Pages)

The pattern is matched by Starlette against the Origin header, so it is anchored
at the start; end it with `$` (or `\\Z`) so a hostname that merely begins with
the right text is not accepted.

Nothing here reads the app or the database: both helpers are given an
environment mapping, which is what lets the tests exercise them without reloading
a module.
"""

from typing import Mapping, Optional

# The ports a developer runs the React app on (`npm start` and Vite). Always
# allowed, so a fresh clone does not need any configuration.
DEV_ORIGINS = ("http://localhost:3000", "http://localhost:5173")


def _split(value: str) -> list:
    """A comma-separated setting as a list, ignoring blanks and padding."""
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def allowed_origins(environ: Mapping[str, str]) -> list:
    """Every origin the API accepts, exactly named."""
    return list(DEV_ORIGINS) + _split(environ.get("FRONTEND_ORIGINS", ""))


def allowed_origin_regex(environ: Mapping[str, str]) -> Optional[str]:
    """The pattern for origins that cannot be named, or None if there is none."""
    pattern = (environ.get("FRONTEND_ORIGIN_REGEX") or "").strip()
    return pattern or None
