"""Statutory documents are hashed, bound to their inputs, and verifiable (H7.4 · S1-54).

An operational plan carries statutory weight -- that is the system's reason to
exist. A search for `sha256`, `hashlib`, `signature` or `checksum` across the
document services returned one hit, and it was image caching. So the artifact
had no content hash, no record that it had been issued, and nothing tying its
figures to the geometry and inventory that produced them. If a plan's numbers
were disputed, the inputs could not be established.

The ordering test is the one that matters most. The verification code is
stamped INSIDE the document, so it must exist before the bytes are final and
the hash must be taken after. Get that backwards and the recorded hash belongs
to a document nobody ever received: verification then fails for every genuine
copy, which is worse than having none.
"""
from __future__ import annotations

import hashlib
import re
import uuid

import pytest
from sqlalchemy import text

from app.core.request_context import RequestIdentity, reset_identity, set_identity
from app.services.document_integrity import (
    CODE_GROUPS,
    CODE_GROUP_LEN,
    collect_provenance,
    lookup,
    mint_verification_code,
    record_issuance,
    sha256_of,
)

DOC = b"PK\x03\x04 pretend this is a .docx payload " * 50


@pytest.fixture()
def owner(db):
    from app.models.user import User

    user = User(
        email=f"docint-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Doc Integrity Fixture",
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def calc(db, owner):
    from app.models.calculation import Calculation

    c = Calculation(user_id=owner.id, forest_name=f"DocInt CF {uuid.uuid4().hex[:6]}",
                    geometry_version=7)
    db.add(c)
    db.commit()
    return c


@pytest.fixture()
def issued(db, calc, owner):
    """One recorded issuance, cleaned up around the append-only rules."""
    code = mint_verification_code()
    token = set_identity(RequestIdentity(
        user_id=str(owner.id), ip_address="10.2.3.4", client_type="web"))
    try:
        digest = record_issuance(
            db, document_bytes=DOC, verification_code=code,
            document_type="operational_plan", calculation_id=calc.id,
            filename="plan.docx",
        )
    finally:
        reset_identity(token)
    yield code, digest
    # DELETE is refused by the append-only rule, so the rule comes off and goes
    # straight back. Doing this in teardown rather than leaving rows behind:
    # a test that pollutes an append-only table pollutes it permanently.
    db.execute(text("DROP RULE IF EXISTS document_issuances_no_delete ON public.document_issuances"))
    db.execute(text("DELETE FROM public.document_issuances WHERE verification_code = :c"),
               {"c": code})
    db.execute(text("""CREATE RULE document_issuances_no_delete AS
                       ON DELETE TO public.document_issuances DO INSTEAD NOTHING"""))
    db.commit()


class TestTheCode:
    def test_it_is_readable_aloud(self):
        """Somebody reads this down a telephone from a paper copy.

        The alphabet excludes I, L, O and U, so a code cannot be misheard or
        mistyped into a different valid one.
        """
        code = mint_verification_code()
        assert re.fullmatch(r"[0-9A-HJ-KM-NP-TV-Z]{4}(-[0-9A-HJ-KM-NP-TV-Z]{4}){2}", code), code
        assert not set("ILOU") & set(code)

    def test_codes_do_not_repeat(self):
        assert len({mint_verification_code() for _ in range(500)}) == 500

    def test_it_is_not_derived_from_the_content(self):
        """A code recomputable from a document is just another hash.

        It has to be a reference to a RECORD, mintable before the document it
        will be stamped into exists.
        """
        assert mint_verification_code() != mint_verification_code()


class TestTheHash:
    def test_it_is_the_sha256_of_the_bytes(self, issued):
        _code, digest = issued
        assert digest == hashlib.sha256(DOC).hexdigest()

    def test_a_single_changed_byte_is_detectable(self, issued):
        """The whole point: an edited plan no longer matches its record."""
        _code, digest = issued
        tampered = bytearray(DOC)
        tampered[10] ^= 0x01
        assert sha256_of(bytes(tampered)) != digest


class TestProvenance:
    def test_the_geometry_version_is_bound(self, db, issued, calc):
        """S1-54: nothing tied a plan to the inputs that produced its numbers,
        even though `geometry_version` was already in the schema."""
        code, _ = issued
        record = lookup(db, code)
        assert record["geometry_version"] == calc.geometry_version == 7

    def test_the_forest_is_named(self, db, issued, calc):
        record = lookup(db, issued[0])
        assert record["forest_name"] == calc.forest_name

    def test_the_correlation_id_is_recorded(self, db, issued):
        """Ties issuance to its request's logs (H3.9). Before 3.9 the
        correlation id reached a response header and nothing else, so this
        column could not have been filled."""
        row = db.execute(text(
            "SELECT correlation_id FROM public.document_issuances WHERE verification_code = :c"),
            {"c": issued[0]}).first()
        assert row[0]


class TestLookup:
    def test_a_code_resolves_to_its_record(self, db, issued):
        code, digest = issued
        record = lookup(db, code)
        assert record is not None
        assert record["sha256"] == digest
        assert record["byte_size"] == len(DOC)

    def test_it_is_case_and_space_insensitive(self, db, issued):
        """People type what is printed, in whatever case, with a stray space."""
        code, _ = issued
        assert lookup(db, code.lower()) is not None
        assert lookup(db, f"  {code}  ") is not None

    def test_an_unknown_code_is_a_miss_not_an_error(self, db):
        assert lookup(db, "ZZZZ-ZZZZ-ZZZZ") is None


class TestAppendOnly:
    def test_an_update_does_nothing(self, db, issued):
        """The rule defends against the application, a mistaken migration and a
        careless script. NOT against a superuser, who can drop it -- that limit
        is stated in migration 059 rather than implied."""
        code, digest = issued
        db.execute(text(
            "UPDATE public.document_issuances SET sha256 = 'tampered' WHERE verification_code = :c"),
            {"c": code})
        db.commit()
        assert lookup(db, code)["sha256"] == digest

    def test_a_delete_does_nothing(self, db, issued):
        code, _ = issued
        db.execute(text("DELETE FROM public.document_issuances WHERE verification_code = :c"),
                   {"c": code})
        db.commit()
        assert lookup(db, code) is not None


class TestTheOrderOfOperations:
    """The property most likely to break silently.

    The code is stamped inside the document, so it must exist before the bytes
    are final and the hash must be taken after. Reversed, the recorded hash
    belongs to a document that was never issued.
    """

    def test_the_endpoint_mints_before_it_builds(self):
        import inspect

        from app.api import operational_plans

        src = inspect.getsource(operational_plans)
        mint = src.index("verification_code = mint_verification_code()")
        build = src.index("build_op_document,")
        hashed = src.index("document_bytes = buffer.getvalue()")
        assert mint < build, "the code must be minted before the document is built"
        assert build < hashed, "the hash must be taken after the document is built"

    def test_the_code_is_minted_exactly_once(self):
        """Minting twice would stamp one code and record another."""
        import inspect

        from app.api import operational_plans

        src = inspect.getsource(operational_plans)
        assert src.count("mint_verification_code()") == 1

    def test_the_builder_stamps_before_saving(self):
        """Anything added after `doc.save()` is not covered by the hash that
        references it."""
        import inspect

        from app.services.operational_plan import op_docx_builder

        src = inspect.getsource(op_docx_builder.build_op_document)
        stamp = src.index("_stamp_verification_footer")
        save = src.index("doc.save(buffer)")
        assert stamp < save


class TestProvenanceEdgePaths:
    """The cheap branches of `collect_provenance` the main fixtures skip.

    The `issued` fixture records a successful issuance (so provenance *succeeds*
    and lines 81-104 run) -- which leaves the two cheap guards uncovered. They
    are the changes this session added, and a gate that does not exercise them
    cannot see a regression in them."""

    def test_no_calculation_id_returns_an_empty_dict(self, db):
        assert collect_provenance(db, None) == {}

    def test_a_failed_provenance_read_does_not_raise(self, calc):
        """S1-54: a document must still be issuable if its provenance cannot be
        read. `collect_provenance` catches and logs, never raises."""
        class _Hostile:
            def execute(self, *_a, **_k):
                raise RuntimeError("provenance query unavailable")

            def rollback(self):
                pass

        assert collect_provenance(_Hostile(), calc.id) == {}


class TestItNeverBreaksTheExport:
    def test_a_failed_recording_returns_none_rather_than_raising(self, db, calc, monkeypatch):
        """A user entitled to their plan must still receive it.

        The failure is logged at ERROR -- an unrecorded issuance is the gap this
        task closes and must not pass quietly -- but it does not deny the
        document.
        """
        from app.services import document_integrity

        def _boom(*_a, **_k):
            raise RuntimeError("issuance table unavailable")

        monkeypatch.setattr(document_integrity, "collect_provenance", _boom)
        result = record_issuance(
            db, document_bytes=DOC, verification_code=mint_verification_code(),
            document_type="operational_plan", calculation_id=calc.id,
        )
        assert result is None

    def test_a_failed_footer_stamp_does_not_stop_the_document(self):
        from app.services.operational_plan.op_docx_builder import _stamp_verification_footer

        class _Hostile:
            @property
            def sections(self):
                raise RuntimeError("no sections")

        _stamp_verification_footer(_Hostile(), "ABCD-EFGH-JKMN")   # must not raise

    def test_extra_provenance_is_merged_into_the_record(self, db, calc):
        """Recording may carry the caller's own context (e.g. which plan) on
        top of what the provenance query returns (H7.4)."""
        code = mint_verification_code()
        token = set_identity(RequestIdentity(user_id=str(calc.user_id), ip_address="10.0.0.2"))
        try:
            digest = record_issuance(
                db, document_bytes=DOC, verification_code=code,
                document_type="operational_plan", calculation_id=calc.id,
                extra_provenance={"drawn_by": "ranger-anita"},
            )
        finally:
            reset_identity(token)
        assert digest
        record = lookup(db, code)
        assert record["provenance"]["drawn_by"] == "ranger-anita"
        # mirror the `issued` fixture's cleanup: the append-only rule refuses
        # DELETE, so it comes off, the row goes, and it goes back.
        db.execute(text("DROP RULE IF EXISTS document_issuances_no_delete ON public.document_issuances"))
        db.execute(text("DELETE FROM public.document_issuances WHERE verification_code = :c"),
                   {"c": code})
        db.execute(text("""CREATE RULE document_issuances_no_delete AS
                           ON DELETE TO public.document_issuances DO INSTEAD NOTHING"""))
        db.commit()

    def test_a_failed_rollback_does_not_mask_the_failure(self, db, calc, monkeypatch):
        """The design tolerates a failure to record, and it must also tolerate a
        failure to roll back the failed insert -- one must not hide the other."""
        from app.services import document_integrity

        def _boom(*_a, **_k):
            raise RuntimeError("issuance table unavailable")

        def _boom_rollback(*_a, **_k):
            raise RuntimeError("rollback failed too")

        monkeypatch.setattr(document_integrity, "collect_provenance", _boom)
        monkeypatch.setattr(db, "rollback", _boom_rollback)
        result = record_issuance(
            db, document_bytes=DOC, verification_code=mint_verification_code(),
            document_type="operational_plan", calculation_id=calc.id,
        )
        assert result is None


class TestTheVerifyEndpointOverHttp:
    """Drive the real `/verify/{code}` route so the H7.4 endpoint lines run
    (the source-ordering tests above prove the ordering; these prove the
    two response branches both execute and return the same shape for a miss
    and a hit)."""

    def test_a_valid_code_resolves_found_true(self, client, issued):
        code, _digest = issued
        resp = client.get(f"/api/operational-plans/verify/{code}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["found"] is True
        assert body["sha256"] == _digest

    def test_an_unknown_code_is_a_miss_not_an_error(self, client):
        resp = client.get(f"/api/operational-plans/verify/{'ABCD-EFGH-JKLM-NPQR'}")
        assert resp.status_code == 200
        assert resp.json()["found"] is False
