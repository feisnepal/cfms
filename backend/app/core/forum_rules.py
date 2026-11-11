"""Community Q&A forum: the numbers that decide who may do what and what it earns (see ``FORUM_SPEC.md`` sections 2-3).

Reputation points and thresholds live here so they can be tuned in one place. Nothing in the services hard-codes them.
"""
from __future__ import annotations

# post kinds
KIND_QUESTION = "question"
KIND_ANSWER = "answer"
KIND_COMMENT = "comment"
POST_KINDS = (KIND_QUESTION, KIND_ANSWER, KIND_COMMENT)

# ledger action types
ACTION_VOTE_UP = "vote_up"
ACTION_VOTE_DOWN = "vote_down"
ACTION_ACCEPT = "accept"
ACTION_FLAG = "flag"
ACTION_FAVORITE = "favorite"
ACTION_CLOSE = "close"
ACTION_DELETE = "delete"
ACTION_TYPES = (ACTION_VOTE_UP, ACTION_VOTE_DOWN, ACTION_ACCEPT, ACTION_FLAG, ACTION_FAVORITE, ACTION_CLOSE, ACTION_DELETE)
# an action of these types is held once per (user, post) while it is live
SINGLE_PER_USER_ACTIONS = (ACTION_VOTE_UP, ACTION_VOTE_DOWN, ACTION_FLAG, ACTION_FAVORITE)

CLOSE_REASONS = ("duplicate", "off_topic", "resolved")
FLAG_RESOLUTIONS = ("dismissed", "hidden", "deleted", "user_warned")
TAG_MARK_REASONS = ("interesting", "ignored")

# negative reputation is not allowed: a balance is clamped at 0 (OSQA ALLOW_NEGATIVE_REPUTATION = False)
ALLOW_NEGATIVE_REPUTATION = False

# reputation earned / lost. Initial values from the spec; tune later.
REP_QUESTION_UPVOTED = 5
REP_ANSWER_UPVOTED = 10
REP_ANSWER_ACCEPTED = 15       # to the answer's author
REP_ACCEPTING_ASKER = 2        # to the asker who accepts
REP_DOWNVOTED_AUTHOR = -2      # to the post's author
REP_DOWNVOTING_VOTER = -1      # to the person who casts a downvote
REP_FLAG_UPHELD = -10          # to the author of a post whose flag a moderator upholds

# reputation needed for each privilege. A moderator (profile.is_moderator) or super admin bypasses all of them.
FORUM_REP_VOTE_UP = 15
FORUM_REP_VOTE_DOWN = 100
FORUM_REP_FLAG = 15
FORUM_REP_COMMENT = 50
FORUM_REP_CREATE_TAG = 150
FORUM_REP_EDIT_OTHERS = 200
FORUM_REP_CLOSE_OTHERS = 500
FORUM_REP_UPLOAD = 30
# an author below this reputation starts with the post held for a moderator ("pending review")
FORUM_REP_NO_REVIEW = 10
FORUM_MAX_VOTES_PER_DAY = 30
FORUM_MAX_FLAGS_PER_DAY = 10

# which reputation a vote on a post of this kind earns its author
_UPVOTE_REP = {KIND_QUESTION: REP_QUESTION_UPVOTED, KIND_ANSWER: REP_ANSWER_UPVOTED, KIND_COMMENT: 0}


def upvote_reputation(kind: str) -> int:
    """What an upvote on a post of this kind earns the post's author."""
    return _UPVOTE_REP.get(kind, 0)

# screenshots (FORUM_SPEC.md decision 6): re-encoded on upload, which also strips EXIF (location, device)
FORUM_MAX_ATTACHMENTS_PER_POST = 4
FORUM_MAX_ATTACHMENTS_PER_DAY = 20
FORUM_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
FORUM_IMAGE_MAX_SIDE_PX = 2000
FORUM_IMAGE_MAX_PIXELS = 40_000_000
ATTACHMENT_TYPES = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg"), "WEBP": ("image/webp", "webp")}
