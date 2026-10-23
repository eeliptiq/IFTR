"""
Community support: asking, answering, agreeing and accepting.

One database is shared by the whole suite, so every assertion is about the
question this test created rather than about the board being empty.
"""

import pytest


def ask(client, headers, question="How do I change my delivery address?", **extra):
    response = client.post(
        "/api/support/questions",
        json={"question": question, **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def answer(client, headers, question_id, text="Use the Settings page."):
    response = client.post(
        "/api/support/answers",
        json={"question_id": question_id, "answer": text},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def board(client, headers, **params):
    response = client.get("/api/support/questions", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def question_on_board(client, headers, question_id):
    for question in board(client, headers):
        if question["question_id"] == question_id:
            return question
    raise AssertionError(f"question {question_id} is not on the board")


@pytest.fixture
def conversation(client, register):
    """An asker, an answerer, the question and one answer between them."""

    asker, asker_headers = register(name="Ana Asker")
    answerer, answerer_headers = register(name="Bea Answerer")
    question = ask(client, asker_headers, category="delivery")
    reply = answer(client, answerer_headers, question["question_id"])
    return {
        "asker": asker,
        "asker_headers": asker_headers,
        "answerer": answerer,
        "answerer_headers": answerer_headers,
        "question": question,
        "answer": reply,
    }


# --------------------------------------------------------------------------
# Asking
# --------------------------------------------------------------------------


def test_a_question_comes_back_with_its_author_and_category(client, register):
    user, headers = register(name="Ana Asker", role="driver")

    posted = ask(
        client,
        headers,
        question="  Which entrance do I use at night?  ",
        category="routing",
    )

    assert posted["question"] == "Which entrance do I use at night?"
    assert posted["category"] == "routing"
    assert posted["user_name"] == "Ana Asker"
    assert posted["user_role"] == "driver"
    assert posted["is_resolved"] is False
    assert posted["is_mine"] is True
    assert posted["answers"] == []
    # Timestamps go out tagged as UTC; a browser would otherwise read the
    # board's times as local.
    assert posted["created_at"].endswith(("Z", "+00:00"))

    listed = question_on_board(client, headers, posted["question_id"])
    assert listed["question"] == posted["question"]
    assert listed["user_name"] == "Ana Asker"
    assert listed["is_mine"] is True


def test_another_person_s_question_is_not_mine(client, conversation):
    """`is_mine` is what the page uses to decide whether to offer Accept."""

    theirs = question_on_board(
        client,
        conversation["answerer_headers"],
        conversation["question"]["question_id"],
    )
    mine = question_on_board(
        client,
        conversation["asker_headers"],
        conversation["question"]["question_id"],
    )

    assert theirs["is_mine"] is False
    assert mine["is_mine"] is True


def test_the_board_needs_a_signed_in_caller(client):
    assert client.get("/api/support/questions").status_code == 401
    assert client.post(
        "/api/support/questions", json={"question": "Anyone there?"}
    ).status_code == 401


def test_a_question_must_have_words_and_a_known_category(client, register):
    _, headers = register()

    blank = client.post(
        "/api/support/questions", json={"question": "   "}, headers=headers
    )
    unknown_category = client.post(
        "/api/support/questions",
        json={"question": "Where is my order?", "category": "cooking"},
        headers=headers,
    )
    too_long = client.post(
        "/api/support/questions",
        json={"question": "x" * 1001},
        headers=headers,
    )

    assert blank.status_code == 422
    assert unknown_category.status_code == 422
    assert too_long.status_code == 422


# --------------------------------------------------------------------------
# Answering
# --------------------------------------------------------------------------


def test_an_answer_appears_under_its_question(client, conversation):
    question_id = conversation["question"]["question_id"]

    listed = question_on_board(
        client, conversation["asker_headers"], question_id
    )

    assert [a["answer_id"] for a in listed["answers"]] == [
        conversation["answer"]["answer_id"]
    ]
    assert listed["answers"][0]["answer"] == "Use the Settings page."
    assert listed["answers"][0]["user_name"] == "Bea Answerer"
    assert listed["answers"][0]["is_accepted"] is False
    assert listed["answers"][0]["upvotes"] == 0


def test_an_answer_to_a_missing_question_is_refused(client, register):
    _, headers = register()

    response = client.post(
        "/api/support/answers",
        json={"question_id": "q_does_not_exist", "answer": "Hello?"},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Question not found"


def test_an_empty_answer_is_refused(client, conversation):
    response = client.post(
        "/api/support/answers",
        json={
            "question_id": conversation["question"]["question_id"],
            "answer": "   ",
        },
        headers=conversation["answerer_headers"],
    )

    assert response.status_code == 422


# --------------------------------------------------------------------------
# Voting
# --------------------------------------------------------------------------


def test_one_person_counts_once_however_often_they_tap(client, conversation, scalar):
    answer_id = conversation["answer"]["answer_id"]

    first = client.post(
        f"/api/support/answers/{answer_id}/upvote",
        headers=conversation["asker_headers"],
    )
    again = client.post(
        f"/api/support/answers/{answer_id}/upvote",
        headers=conversation["asker_headers"],
    )

    assert first.status_code == 200, first.text
    assert first.json()["upvotes"] == 1
    # A retried tap (double click, flaky connection) is not a second vote.
    assert again.status_code == 200, again.text
    assert again.json()["upvotes"] == 1
    assert (
        scalar(
            "select count(*) from support_answer_votes where answer_id = ? and user_id = ?",
            (answer_id, conversation["asker"]["user_id"]),
        )
        == 1
    )

    other = client.post(
        f"/api/support/answers/{answer_id}/upvote",
        headers=conversation["answerer_headers"],
    )

    assert other.json()["upvotes"] == 2
    assert (
        question_on_board(
            client,
            conversation["asker_headers"],
            conversation["question"]["question_id"],
        )["answers"][0]["upvotes"]
        == 2
    )


def test_upvoting_an_answer_that_does_not_exist_is_a_404(client, register):
    _, headers = register()

    response = client.post(
        "/api/support/answers/a_does_not_exist/upvote", headers=headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Answer not found"


# --------------------------------------------------------------------------
# Accepting
# --------------------------------------------------------------------------


def test_only_the_asker_can_accept_an_answer(client, conversation, register):
    question_id = conversation["question"]["question_id"]
    answer_id = conversation["answer"]["answer_id"]

    _, outsider_headers = register(name="Cara Onlooker")

    refused = client.post(
        f"/api/support/answers/{answer_id}/accept", headers=outsider_headers
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Only the question author can accept an answer"
    assert question_on_board(client, conversation["asker_headers"], question_id)[
        "is_resolved"
    ] is False

    accepted = client.post(
        f"/api/support/answers/{answer_id}/accept",
        headers=conversation["asker_headers"],
    )

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["is_accepted"] is True
    listed = question_on_board(client, conversation["asker_headers"], question_id)
    assert listed["is_resolved"] is True
    assert listed["answers"][0]["is_accepted"] is True


def test_accepting_a_second_answer_moves_the_mark(client, conversation, scalar):
    question_id = conversation["question"]["question_id"]
    first_id = conversation["answer"]["answer_id"]
    second = answer(
        client,
        conversation["answerer_headers"],
        question_id,
        text="Or the profile page.",
    )

    client.post(
        f"/api/support/answers/{first_id}/accept",
        headers=conversation["asker_headers"],
    )
    moved = client.post(
        f"/api/support/answers/{second['answer_id']}/accept",
        headers=conversation["asker_headers"],
    )

    assert moved.status_code == 200, moved.text
    listed = question_on_board(client, conversation["asker_headers"], question_id)
    accepted = [a["answer_id"] for a in listed["answers"] if a["is_accepted"]]
    assert accepted == [second["answer_id"]]
    # A question is resolved by exactly one answer, not by a pile of them.
    assert (
        scalar(
            "select count(*) from support_answers where question_id = ? and is_accepted = 1",
            (question_id,),
        )
        == 1
    )


def test_accepting_the_same_answer_twice_is_harmless(client, conversation, scalar):
    answer_id = conversation["answer"]["answer_id"]

    first = client.post(
        f"/api/support/answers/{answer_id}/accept",
        headers=conversation["asker_headers"],
    )
    second = client.post(
        f"/api/support/answers/{answer_id}/accept",
        headers=conversation["asker_headers"],
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["is_accepted"] is True
    assert (
        scalar(
            "select count(*) from support_answers where answer_id = ? and is_accepted = 1",
            (answer_id,),
        )
        == 1
    )


def test_the_accepted_answer_sorts_first(client, conversation, register):
    """The asker's choice outranks a better-voted answer."""
    question_id = conversation["question"]["question_id"]
    other, other_headers = register(name="Cara Onlooker")
    voted = answer(client, other_headers, question_id, text="The popular reply.")

    # Two different people, so this really is a better-voted answer.
    for headers in (conversation["asker_headers"], conversation["answerer_headers"]):
        client.post(
            f"/api/support/answers/{voted['answer_id']}/upvote",
            headers=headers,
        )

    client.post(
        f"/api/support/answers/{conversation['answer']['answer_id']}/accept",
        headers=conversation["asker_headers"],
    )

    listed = question_on_board(client, conversation["asker_headers"], question_id)
    assert listed["answers"][0]["answer_id"] == conversation["answer"]["answer_id"]
    assert listed["answers"][0]["is_accepted"] is True


# --------------------------------------------------------------------------
# Filters, and the driver screen's use of the same board
# --------------------------------------------------------------------------


def test_the_board_filters_by_category_and_open_state(client, conversation, register):
    _, headers = register()
    open_tip = ask(client, headers, question="Back door on 2nd is faster.", category="routing")
    settled = ask(client, headers, question="Where do refunds go?", category="payment")
    settled_answer = answer(client, headers, settled["question_id"])
    client.post(
        f"/api/support/answers/{settled_answer['answer_id']}/accept", headers=headers
    )

    tips = board(client, headers, category="routing")
    still_open = board(client, headers, resolved="false")
    resolved = board(client, headers, resolved="true")

    assert open_tip["question_id"] in {q["question_id"] for q in tips}
    assert settled["question_id"] not in {q["question_id"] for q in tips}
    assert open_tip["question_id"] in {q["question_id"] for q in still_open}
    assert settled["question_id"] not in {q["question_id"] for q in still_open}
    assert settled["question_id"] in {q["question_id"] for q in resolved}
    assert open_tip["question_id"] not in {q["question_id"] for q in resolved}
