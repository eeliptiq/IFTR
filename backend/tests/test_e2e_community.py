"""
The community screens, worked through the browser.

The API suite proves the rules - one vote per person, only the asker accepts,
earnings windows keyed to delivery time. These journeys prove the ported pages
actually reach those endpoints and render the answer:

  * a question is asked through the dialog, answered by somebody else, upvoted
    and accepted from the asker's own screen;
  * the impact page reads the real feed instead of the demo totals it used to
    fall back to, and the earnings page shows a new driver's honest zeros
    instead of invented trips and a "+12%" trend.

They share the throwaway servers and seed in `tests/ui_world.py`, so the CRA
compile is paid once for every browser module. Like the others they are opt-in:

    python -m playwright install chromium        # once per machine
    RUN_UI_E2E=1 pytest tests/test_e2e_community.py
"""

import time

import httpx
import pytest

from tests.ui_harness import (
    api_login,
    register,
    register_driver_account,
    sign_in,
)
from tests.ui_world import UiWorld, ui_world


@pytest.fixture(scope="module")
def stack(ui_world) -> UiWorld:
    """The shared stack; each journey seeds what it needs."""
    return ui_world


def _question(api: httpx.Client, headers: dict, text: str) -> dict:
    listed = api.get("/api/support/questions", headers=headers)
    assert listed.status_code == 200, listed.text
    return next(
        question for question in listed.json() if question["question"] == text
    )


def test_a_question_is_asked_answered_upvoted_and_accepted(stack: UiWorld):
    from playwright.sync_api import expect, sync_playwright

    question_text = f"How do I change my delivery address? {time.time_ns()}"
    answer_text = "Open Settings, then edit the address on your profile."

    with httpx.Client(base_url=stack.api_base, timeout=30.0) as api:
        asker = register(api, "customer", "Ana Asker")
        answerer = register(api, "customer", "Bea Answerer")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = sign_in(browser, stack.web_url, asker["email"])
            page.goto(f"{stack.web_url}/support")

            page.get_by_test_id("ask-question-button").click()
            page.get_by_test_id("question-input").fill(question_text)
            page.get_by_test_id("submit-question-button").click()

            expect(page.get_by_text("Question posted!")).to_be_visible()
            expect(page.get_by_text(question_text)).to_be_visible()

            with httpx.Client(base_url=stack.api_base, timeout=30.0) as api:
                question = _question(api, api_login(api, asker["email"]), question_text)
                posted = api.post(
                    "/api/support/answers",
                    json={
                        "question_id": question["question_id"],
                        "answer": answer_text,
                    },
                    headers=api_login(api, answerer["email"]),
                )
                assert posted.status_code == 201, posted.text
                answer_id = posted.json()["answer_id"]

            page.reload()
            expect(page.get_by_text(answer_text)).to_be_visible()

            upvote = page.get_by_test_id(f"support-upvote-{answer_id}")
            upvote.click()
            expect(upvote).to_contain_text("1")
            # A second tap is the same vote, not a second one.
            upvote.click()
            expect(upvote).to_contain_text("1")

            page.get_by_test_id(f"support-accept-{answer_id}").click()
            expect(page.get_by_text("Marked as the answer")).to_be_visible()
            expect(page.get_by_text("Accepted Answer")).to_be_visible()
            expect(page.get_by_text("Resolved")).to_be_visible()
        finally:
            browser.close()

    with httpx.Client(base_url=stack.api_base, timeout=30.0) as api:
        question = _question(api, api_login(api, asker["email"]), question_text)
        assert question["is_resolved"] is True
        assert question["is_mine"] is True
        assert question["answers"][0]["answer_id"] == answer_id
        assert question["answers"][0]["is_accepted"] is True
        assert question["answers"][0]["upvotes"] == 1


def test_impact_and_earnings_render_real_figures_not_demo_data(stack: UiWorld):
    from playwright.sync_api import expect, sync_playwright

    with httpx.Client(base_url=stack.api_base, timeout=30.0) as api:
        customer = register(api, "customer", "Iris Impact")
        driver, _ = register_driver_account(api, "Evan Earnings")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = sign_in(browser, stack.web_url, customer["email"])
            page.goto(f"{stack.web_url}/impact")

            expect(page.get_by_test_id("community-impact-page")).to_be_visible()
            # The request succeeding is what keeps both of these off the page.
            expect(
                page.get_by_text("Live impact figures are unavailable right now.")
            ).to_have_count(0)
            expect(page.get_by_text("Meals Donated")).to_be_visible()
            # The prototyped page's fallback total must never be what renders.
            expect(page.get_by_text("12,847")).to_have_count(0)
        finally:
            browser.close()

        browser = playwright.chromium.launch()
        try:
            page = sign_in(browser, stack.web_url, driver["email"])
            page.goto(f"{stack.web_url}/driver/earnings")

            expect(page.get_by_test_id("driver-earnings-page")).to_be_visible()
            expect(
                page.get_by_text("Earnings could not be loaded right now.")
            ).to_have_count(0)
            expect(page.get_by_text("No completed trips yet")).to_be_visible()
            # Demo-only artefacts: a fabricated trend and fake recent trips.
            expect(page.get_by_text("+12%")).to_have_count(0)
            expect(page.get_by_text("2 hours ago")).to_have_count(0)
        finally:
            browser.close()
