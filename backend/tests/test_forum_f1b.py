"""Forum F1b gate: screenshots (validated, re-encoded, hidden until approved) and what search engines see."""
import io
import json
import re
import uuid

import pytest
from PIL import Image

from app.core import forum_rules as rules
from app.core.config import settings
from app.models.forum import ForumAttachment
from app.models.user import User, UserRole
from app.services.forum import ledger
from app.utils.auth import create_access_token

SEED_TAGS = ("map", "user-group", "fieldbook", "sampling", "field-inventory", "biodiversity", "household", "sfm", "cost-benefit",
             "operational-plan", "yearly-plan", "ntfp", "hazard", "mobile", "account")
BODY = "I drew the boundary but the print map shows no labels. What should I check first?"
API = "/api/v1/forum"


@pytest.fixture(autouse=True)
def _empty_forum(db, tmp_path, monkeypatch):
    from sqlalchemy import text

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://forum.example.org")
    monkeypatch.setattr(settings, "FORUM_SPA_INDEX_PATH", str(tmp_path / "no-such-index.html"))
    db.execute(text("TRUNCATE forum_posts, forum_profiles, forum_actions, forum_reputation_events, forum_flags, forum_subscriptions, forum_notification_prefs, "
                    "forum_tag_marks, forum_tag_synonyms, forum_post_tags, forum_post_revisions, forum_attachments CASCADE"))
    db.execute(text("DELETE FROM forum_tags WHERE name <> ALL(:seed)"), {"seed": list(SEED_TAGS)})
    db.execute(text("UPDATE forum_tags SET used_count = 0"))
    db.commit()
    yield


def _member(db, reputation=rules.FORUM_REP_NO_REVIEW, role=UserRole.USER):
    user = User(email=f"f{uuid.uuid4().hex[:10]}@test.com", full_name="Forum Member", role=role, hashed_password="x")
    db.add(user)
    db.flush()
    if reputation:
        ledger.apply_reputation(db, user.id, reputation, None)
    db.commit()
    return user


def _h(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'email': user.email})}"}


def _ask(client, user, **over):
    body = {"title": "How do I print the boundary map?", "body": BODY, "tags": ["map"], **over}
    r = client.post(f"{API}/questions", json=body, headers=_h(user))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _png(size=(40, 30), color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _jpeg_with_exif():
    img = Image.new("RGB", (60, 40), (10, 120, 10))
    exif = Image.Exif()
    exif[0x010F] = "SecretPhoneMaker"   # Make
    exif[0x8825] = {1: "N", 2: (27.0, 40.0, 0.0), 3: "E", 4: (85.0, 20.0, 0.0)}  # GPS block
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _upload(client, user, post_id, data, name="shot.png", ctype="image/png"):
    return client.post(f"{API}/posts/{post_id}/attachments", files={"file": (name, data, ctype)}, headers=_h(user))


# ── screenshots ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_trusted_member_attaches_a_screenshot_everyone_can_then_see(client, db):
    user = _member(db, reputation=rules.FORUM_REP_UPLOAD)
    qid = _ask(client, user)
    r = _upload(client, user, qid, _png())
    assert r.status_code == 201
    att = r.json()["attachments"][0]
    assert att["approved"] is True and (att["width"], att["height"]) == (40, 30)
    file = client.get(f"{API}/attachments/{att['id']}")  # anonymous
    assert file.status_code == 200 and file.headers["content-type"] == "image/png"
    assert "public" in file.headers["cache-control"] and file.headers["x-content-type-options"] == "nosniff"
    assert Image.open(io.BytesIO(file.content)).size == (40, 30)
    assert client.get(f"{API}/questions/{qid}").json()["question"]["attachments"][0]["id"] == att["id"]


def test_a_new_members_picture_is_hidden_until_a_moderator_approves_it(client, db):
    user = _member(db, reputation=rules.FORUM_REP_NO_REVIEW)  # enough to post openly, not enough to upload openly
    qid = _ask(client, user)
    att = _upload(client, user, qid, _png()).json()["attachments"][0]
    assert att["approved"] is False
    assert client.get(f"{API}/attachments/{att['id']}").status_code == 404                       # anonymous
    assert client.get(f"{API}/attachments/{att['id']}", headers=_h(_member(db))).status_code == 404  # another member
    assert client.get(f"{API}/attachments/{att['id']}", headers=_h(user)).status_code == 200      # the uploader
    assert client.get(f"{API}/questions/{qid}").json()["question"]["attachments"] == []
    admin = _member(db, role=UserRole.SUPER_ADMIN)
    assert client.post(f"{API}/attachments/{att['id']}/approve", headers=_h(user)).status_code == 403
    assert client.post(f"{API}/attachments/{att['id']}/approve", headers=_h(admin)).status_code == 200
    assert client.get(f"{API}/attachments/{att['id']}").status_code == 200


def test_approving_a_held_post_approves_its_pictures(client, db):
    newcomer = _member(db, reputation=0)
    qid = _ask(client, newcomer)
    aid = _upload(client, newcomer, qid, _png()).json()["attachments"][0]["id"]
    admin = _member(db, role=UserRole.SUPER_ADMIN)
    client.post(f"{API}/posts/{qid}/approve", headers=_h(admin))
    assert client.get(f"{API}/attachments/{aid}").status_code == 200


def test_only_real_images_are_taken(client, db):
    user = _member(db, reputation=rules.FORUM_REP_UPLOAD)
    qid = _ask(client, user)
    assert _upload(client, user, qid, b"<html><script>alert(1)</script></html>", "x.png", "image/png").status_code == 422
    assert _upload(client, user, qid, b"%PDF-1.4 fake", "x.png", "image/png").status_code == 422
    gif = io.BytesIO()
    Image.new("P", (5, 5)).save(gif, "GIF")
    assert _upload(client, user, qid, gif.getvalue(), "x.gif", "image/gif").status_code == 422
    assert _upload(client, user, qid, b"", "x.png").status_code == 422
    assert db.query(ForumAttachment).count() == 0


def test_a_picture_is_written_again_without_its_metadata(client, db):
    user = _member(db, reputation=rules.FORUM_REP_UPLOAD)
    qid = _ask(client, user)
    original = _jpeg_with_exif()
    assert b"SecretPhoneMaker" in original
    att = _upload(client, user, qid, original, "photo.jpg", "image/jpeg").json()["attachments"][0]
    stored = client.get(f"{API}/attachments/{att['id']}").content
    assert b"SecretPhoneMaker" not in stored and b"Exif" not in stored
    assert not Image.open(io.BytesIO(stored)).getexif()


def test_a_big_picture_is_shrunk(client, db):
    user = _member(db, reputation=rules.FORUM_REP_UPLOAD)
    qid = _ask(client, user)
    att = _upload(client, user, qid, _png((3000, 1500))).json()["attachments"][0]
    assert max(att["width"], att["height"]) == rules.FORUM_IMAGE_MAX_SIDE_PX


def test_the_limits(client, db, monkeypatch):
    user = _member(db, reputation=rules.FORUM_REP_UPLOAD)
    qid = _ask(client, user)
    for _ in range(rules.FORUM_MAX_ATTACHMENTS_PER_POST):
        assert _upload(client, user, qid, _png()).status_code == 201
    assert _upload(client, user, qid, _png()).status_code == 422          # per post
    monkeypatch.setattr(rules, "FORUM_MAX_UPLOAD_BYTES", 100)
    other = _ask(client, user, title="A different question about printing")
    assert _upload(client, user, other, _png((200, 200))).status_code == 422  # too big
    monkeypatch.setattr(rules, "FORUM_MAX_UPLOAD_BYTES", 5 * 1024 * 1024)
    monkeypatch.setattr(rules, "FORUM_MAX_ATTACHMENTS_PER_DAY", 4)
    assert _upload(client, user, other, _png()).status_code == 422        # per day


def test_only_the_author_or_a_moderator_can_add_or_delete(client, db):
    author = _member(db, reputation=rules.FORUM_REP_UPLOAD)
    qid = _ask(client, author)
    assert _upload(client, _member(db, reputation=rules.FORUM_REP_UPLOAD), qid, _png()).status_code == 403
    aid = _upload(client, author, qid, _png()).json()["attachments"][0]["id"]
    assert client.delete(f"{API}/attachments/{aid}", headers=_h(_member(db))).status_code == 403
    assert client.delete(f"{API}/attachments/{aid}", headers=_h(author)).status_code == 200
    assert client.get(f"{API}/attachments/{aid}").status_code == 404


def test_a_picture_of_a_deleted_post_is_not_served(client, db):
    author = _member(db, reputation=rules.FORUM_REP_UPLOAD)
    qid = _ask(client, author)
    aid = _upload(client, author, qid, _png()).json()["attachments"][0]["id"]
    client.delete(f"{API}/posts/{qid}", headers=_h(author))
    assert client.get(f"{API}/attachments/{aid}").status_code == 404


# ── what search engines see ─────────────────────────────────────────────────────────────────────────────────────

def test_the_question_page_carries_the_text_and_the_metadata(client, db):
    user = _member(db)
    qid = _ask(client, user, title="Why is the <b>label</b> missing? \"quoted\"", body=BODY + "\n\n<script>alert(1)</script>")
    r = client.get(f"{API}/pages/q/{qid}")
    assert r.status_code == 200 and "public" in r.headers["cache-control"]
    page = r.text
    assert f'<link rel="canonical" href="https://forum.example.org/forum/q/{qid}">' in page
    assert "<h1>Why is the &lt;b&gt;label&lt;/b&gt; missing?" in page
    assert "print map shows no labels" in page and 'name="description"' in page
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
    assert ld["@type"] == "QAPage" and ld["mainEntity"]["answerCount"] == 0


def test_answers_appear_and_the_accepted_one_is_marked_in_the_data(client, db):
    asker, answerer = _member(db), _member(db)
    qid = _ask(client, asker)
    a = client.post(f"{API}/questions/{qid}/answers", json={"body": "Tick the label option on the map variables page."}, headers=_h(answerer)).json()
    client.post(f"{API}/answers/{a['id']}/accept", headers=_h(asker))
    page = client.get(f"{API}/pages/q/{qid}").text
    assert "Tick the label option" in page and "(accepted answer)" in page
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
    assert ld["mainEntity"]["acceptedAnswer"]["text"].startswith("Tick the label")
    assert "suggestedAnswer" not in ld["mainEntity"]


def test_a_script_end_tag_in_a_post_cannot_break_out_of_the_data_block(client, db):
    qid = _ask(client, _member(db), body=BODY + "\n\n</script><img src=x onerror=alert(1)>")
    page = client.get(f"{API}/pages/q/{qid}").text
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1)
    assert "</script" not in block and "<img" not in page


def test_the_question_is_written_into_the_apps_own_page(client, db, tmp_path, monkeypatch):
    shell = tmp_path / "index.html"
    shell.write_text('<!doctype html><html lang="en"><head><title>App</title></head><body><div id="root"></div><script src="/assets/app.js"></script></body></html>', encoding="utf-8")
    monkeypatch.setattr(settings, "FORUM_SPA_INDEX_PATH", str(shell))
    qid = _ask(client, _member(db), title="समुदायिक वनको नक्सा कसरी छाप्ने", body="नक्सा छाप्दा सिमाना देखिँदैन, के गर्ने होला? कृपया सहयोग गर्नुहोस्।")
    page = client.get(f"{API}/pages/q/{qid}").text
    assert '<script src="/assets/app.js"></script>' in page            # a person still gets the app
    assert '<html lang="ne">' in page and "<title>समुदायिक वनको नक्सा कसरी छाप्ने - Community Forum</title>" in page
    root = page.split('<div id="root">', 1)[1].split('<script src="/assets/app.js">', 1)[0]
    assert page.count("<title>") == 1 and "नक्सा छाप्दा सिमाना" in root  # the text is inside the element React replaces


def test_held_and_deleted_questions_are_not_rendered_or_listed(client, db):
    visible = _ask(client, _member(db))
    held = _ask(client, _member(db, reputation=0))
    gone_author = _member(db)
    gone = _ask(client, gone_author, title="A question that will be deleted soon")
    client.delete(f"{API}/posts/{gone}", headers=_h(gone_author))
    assert client.get(f"{API}/pages/q/{held}").status_code == 404
    assert client.get(f"{API}/pages/q/{gone}").status_code == 404
    xml = client.get(f"{API}/sitemap.xml")
    assert xml.status_code == 200 and "xml" in xml.headers["content-type"]
    assert f"https://forum.example.org/forum/q/{visible}" in xml.text
    assert held not in xml.text and gone not in xml.text
    assert "<loc>https://forum.example.org/forum</loc>" in xml.text


def test_robots_points_at_the_sitemap(client):
    r = client.get(f"{API}/robots.txt")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "Sitemap: https://forum.example.org/sitemap.xml" in r.text and "Disallow: /api/" in r.text and "Allow: /forum" in r.text
