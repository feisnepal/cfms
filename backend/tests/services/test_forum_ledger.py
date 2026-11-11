"""Forum F0 gate: the action ledger (votes, accepted answers, reputation) is reversible and never lets reputation go below zero.

The tables come from migration 143 (applied by the conftest harness's ``alembic upgrade head``).
"""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core import forum_rules as rules
from app.models.forum import ForumAction, ForumPost, ForumPostRevision
from app.models.user import User, UserRole
from app.services.forum import ledger


def _user(db, role=UserRole.USER, reputation=0):
    user = User(
        email=f"forum{uuid.uuid4().hex[:10]}@test.com", full_name="Forum Tester", role=role, hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    if reputation:  # through the ledger, so the balance always equals the sum of its events
        ledger.apply_reputation(db, user.id, reputation, None)
    return user


def _rep(db, user):
    return ledger.get_profile(db, user.id).reputation


def _post(db, author, kind=rules.KIND_QUESTION, root=None):
    post = ForumPost(
        kind=kind, author_id=author.id, body_md="body text for the forum test",
        title="a question title long enough" if kind == rules.KIND_QUESTION else None,
        parent_id=root.id if root else None, root_id=root.id if root else None,
    )
    db.add(post)
    db.flush()
    db.refresh(post)
    return post


def _question_with_answer(db):
    asker, answerer = _user(db), _user(db)
    question = _post(db, asker)
    answer = _post(db, answerer, rules.KIND_ANSWER, question)
    return asker, answerer, question, answer


def test_upvote_earns_the_author_reputation_and_raises_the_score(db):
    author = _user(db)
    voter = _user(db, reputation=rules.FORUM_REP_VOTE_UP)
    answer = _post(db, author, rules.KIND_ANSWER, _post(db, _user(db)))
    ledger.cast_vote(db, voter, answer, rules.ACTION_VOTE_UP)
    assert _rep(db, author) == rules.REP_ANSWER_UPVOTED
    assert answer.score == 1


def test_cancelling_a_vote_reverses_score_and_reputation_exactly(db):
    author = _user(db)
    voter = _user(db, reputation=rules.FORUM_REP_VOTE_UP)
    question = _post(db, author)
    action = ledger.cast_vote(db, voter, question, rules.ACTION_VOTE_UP)
    ledger.cancel_action(db, action, voter.id)
    db.refresh(question)
    assert question.score == 0
    assert _rep(db, author) == 0
    assert ledger.reputation_from_events(db, author.id) == _rep(db, author)


def test_cancelling_twice_changes_nothing(db):
    author = _user(db)
    voter = _user(db, reputation=rules.FORUM_REP_VOTE_UP)
    question = _post(db, author)
    action = ledger.cast_vote(db, voter, question, rules.ACTION_VOTE_UP)
    ledger.cancel_action(db, action, voter.id)
    ledger.cancel_action(db, action, voter.id)
    db.refresh(question)
    assert question.score == 0
    assert ledger.reputation_from_events(db, author.id) == _rep(db, author) == 0


def test_reputation_is_clamped_at_zero_and_the_applied_amount_is_recorded(db):
    author = _user(db, reputation=1)
    voter = _user(db, reputation=rules.FORUM_REP_VOTE_DOWN)
    question = _post(db, author)
    action = ledger.cast_vote(db, voter, question, rules.ACTION_VOTE_DOWN)
    assert _rep(db, author) == 0  # 1 - 2 would be -1
    # cancelling reverses what was applied (-1), not what was asked (-2)
    ledger.cancel_action(db, action, voter.id)
    assert _rep(db, author) == 1
    assert ledger.reputation_from_events(db, author.id) == _rep(db, author)


def test_a_downvote_costs_the_voter_one_and_the_author_two(db):
    author = _user(db, reputation=20)
    voter = _user(db, reputation=rules.FORUM_REP_VOTE_DOWN)
    ledger.cast_vote(db, voter, _post(db, author), rules.ACTION_VOTE_DOWN)
    assert _rep(db, author) == 20 + rules.REP_DOWNVOTED_AUTHOR
    assert _rep(db, voter) == rules.FORUM_REP_VOTE_DOWN + rules.REP_DOWNVOTING_VOTER


def test_a_second_vote_in_the_same_direction_is_refused(db):
    voter = _user(db, reputation=rules.FORUM_REP_VOTE_UP)
    question = _post(db, _user(db))
    ledger.cast_vote(db, voter, question, rules.ACTION_VOTE_UP)
    with pytest.raises(ledger.ForumRuleError):
        ledger.cast_vote(db, voter, question, rules.ACTION_VOTE_UP)


def test_voting_the_other_way_replaces_the_first_vote(db):
    author = _user(db, reputation=50)
    voter = _user(db, reputation=rules.FORUM_REP_VOTE_DOWN)
    question = _post(db, author)
    ledger.cast_vote(db, voter, question, rules.ACTION_VOTE_UP)
    ledger.cast_vote(db, voter, question, rules.ACTION_VOTE_DOWN)
    db.refresh(question)
    assert question.score == -1
    live = db.query(ForumAction).filter(ForumAction.post_id == question.id, ForumAction.canceled_at.is_(None)).count()
    assert live == 1
    assert ledger.reputation_from_events(db, author.id) == _rep(db, author)


def test_the_database_allows_only_one_live_vote_per_user_and_post(db):
    voter, author = _user(db), _user(db)
    question = _post(db, author)
    db.add(ForumAction(user_id=voter.id, post_id=question.id, action_type=rules.ACTION_VOTE_UP))
    db.flush()
    db.add(ForumAction(user_id=voter.id, post_id=question.id, action_type=rules.ACTION_VOTE_UP))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_you_cannot_vote_on_your_own_post(db):
    author = _user(db, reputation=1000)
    with pytest.raises(ledger.ForumRuleError):
        ledger.cast_vote(db, author, _post(db, author), rules.ACTION_VOTE_UP)


def test_voting_needs_the_reputation_but_a_moderator_does_not(db):
    question = _post(db, _user(db))
    newcomer = _user(db, reputation=0)
    with pytest.raises(ledger.ForumPermissionError):
        ledger.cast_vote(db, newcomer, question, rules.ACTION_VOTE_UP)
    admin = _user(db, role=UserRole.SUPER_ADMIN)
    ledger.cast_vote(db, admin, question, rules.ACTION_VOTE_UP)
    flagged_mod = _user(db)
    ledger.get_profile(db, flagged_mod.id).is_moderator = True
    db.flush()
    ledger.cast_vote(db, flagged_mod, _post(db, _user(db)), rules.ACTION_VOTE_UP)


def test_the_daily_vote_cap(db, monkeypatch):
    monkeypatch.setattr(rules, "FORUM_MAX_VOTES_PER_DAY", 2)
    voter = _user(db, reputation=rules.FORUM_REP_VOTE_UP)
    author = _user(db)
    ledger.cast_vote(db, voter, _post(db, author), rules.ACTION_VOTE_UP)
    ledger.cast_vote(db, voter, _post(db, author), rules.ACTION_VOTE_UP)
    with pytest.raises(ledger.ForumRuleError):
        ledger.cast_vote(db, voter, _post(db, author), rules.ACTION_VOTE_UP)


def test_accepting_an_answer_pays_the_answerer_and_the_asker(db):
    asker, answerer, _question, answer = _question_with_answer(db)
    ledger.accept_answer(db, asker, answer)
    assert answer.accepted_at is not None
    assert _rep(db, answerer) == rules.REP_ANSWER_ACCEPTED
    assert _rep(db, asker) == rules.REP_ACCEPTING_ASKER


def test_only_the_asker_or_a_moderator_can_accept(db):
    _asker, _answerer, _question, answer = _question_with_answer(db)
    with pytest.raises(ledger.ForumPermissionError):
        ledger.accept_answer(db, _user(db), answer)
    ledger.accept_answer(db, _user(db, role=UserRole.SUPER_ADMIN), answer)


def test_accepting_another_answer_moves_the_mark_and_the_reputation(db):
    asker, first_author, question, first = _question_with_answer(db)
    second_author = _user(db)
    second = _post(db, second_author, rules.KIND_ANSWER, question)
    ledger.accept_answer(db, asker, first)
    ledger.accept_answer(db, asker, second)
    db.refresh(first)
    assert first.accepted_at is None and second.accepted_at is not None
    assert _rep(db, first_author) == 0
    assert _rep(db, second_author) == rules.REP_ANSWER_ACCEPTED
    assert _rep(db, asker) == rules.REP_ACCEPTING_ASKER  # not paid twice
    for user in (asker, first_author, second_author):
        assert ledger.reputation_from_events(db, user.id) == _rep(db, user)


def test_the_asker_answering_themselves_earns_nothing_on_accept(db):
    asker = _user(db)
    question = _post(db, asker)
    own = _post(db, asker, rules.KIND_ANSWER, question)
    ledger.accept_answer(db, asker, own)
    assert _rep(db, asker) == 0


def test_the_database_allows_one_accepted_answer_per_question(db):
    asker, _answerer, question, first = _question_with_answer(db)
    second = _post(db, _user(db), rules.KIND_ANSWER, question)
    db.execute(text("UPDATE forum_posts SET accepted_at = now() WHERE id = :i"), {"i": first.id})
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE forum_posts SET accepted_at = now() WHERE id = :i"), {"i": second.id})
    db.rollback()


def test_a_deleted_or_held_post_cannot_be_voted_on(db):
    voter = _user(db, reputation=rules.FORUM_REP_VOTE_UP)
    held = _post(db, _user(db))
    held.pending_review = True
    db.flush()
    with pytest.raises(ledger.ForumRuleError):
        ledger.cast_vote(db, voter, held, rules.ACTION_VOTE_UP)


def test_revision_numbers_are_unique_per_post(db):
    post = _post(db, _user(db))
    db.add(ForumPostRevision(post_id=post.id, revision=1, body_md="first"))
    db.flush()
    db.add(ForumPostRevision(post_id=post.id, revision=1, body_md="again"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_deleting_a_question_removes_its_answers_actions_and_revisions(db):
    asker, _answerer, question, answer = _question_with_answer(db)
    ledger.accept_answer(db, asker, answer)
    db.add(ForumPostRevision(post_id=question.id, revision=1, body_md="v1"))
    db.flush()
    db.execute(text("DELETE FROM forum_posts WHERE id = :i"), {"i": question.id})
    for table, col in (("forum_posts", "root_id"), ("forum_actions", "post_id"), ("forum_post_revisions", "post_id")):
        left = db.execute(text(f"SELECT count(*) FROM {table} WHERE {col} = :i"), {"i": question.id}).scalar()
        assert left == 0, table


def test_a_post_outlives_its_deleted_author(db):
    author = _user(db)
    question = _post(db, author)
    db.execute(text("DELETE FROM users WHERE id = :i"), {"i": author.id})
    db.expire_all()
    assert db.get(ForumPost, question.id).author_id is None
