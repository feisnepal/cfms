"""H2.9 / S3-10 — one hardened extractor, tested against real hostile archives.

There were four extraction sites with three levels of care. The worst,
`user_group_analysis.py`, called `extractall()` with nothing in front of it: an
uploaded shapefile ZIP containing `../../app/main.py` would have been written
over the application itself. The best still compared paths with `str.startswith`,
which treats `/tmp/out` as a prefix of `/tmp/output-elsewhere`, and none of them
refused symlinks or capped total expanded size.

Every archive below is built here rather than described, because a traversal
guard that has only ever been reasoned about is not a guard.
"""
import os
import zipfile
from pathlib import Path

import pytest

from app.utils.safe_archive import (
    MAX_ENTRIES,
    UnsafeArchiveError,
    check_archive_limits,
    safe_extract,
)


def _zip(tmp_path: Path, entries, name="archive.zip") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry_name, data in entries:
            zf.writestr(entry_name, data)
    return path


class TestZipSlip:
    @pytest.mark.parametrize("hostile_name", [
        "../escaped.txt",
        "../../escaped.txt",
        "sub/../../escaped.txt",
        "/absolute.txt",
    ])
    def test_entries_escaping_the_destination_are_refused(self, tmp_path, hostile_name):
        archive = _zip(tmp_path, [(hostile_name, "owned")])
        out = tmp_path / "out"
        with pytest.raises(UnsafeArchiveError):
            safe_extract(archive, out)

    def test_nothing_is_written_outside_the_destination(self, tmp_path):
        """The assertion that matters: the file simply is not there."""
        archive = _zip(tmp_path, [("harmless.txt", "ok"), ("../escaped.txt", "owned")])
        out = tmp_path / "out"
        with pytest.raises(UnsafeArchiveError):
            safe_extract(archive, out)
        assert not (tmp_path / "escaped.txt").exists()

    def test_a_hostile_entry_prevents_the_whole_extraction(self, tmp_path):
        """Checked up front, so a refused archive leaves no partial state."""
        archive = _zip(tmp_path, [("good.txt", "fine"), ("../bad.txt", "owned")])
        out = tmp_path / "out"
        with pytest.raises(UnsafeArchiveError):
            safe_extract(archive, out)
        assert not (out / "good.txt").exists()

    def test_a_sibling_directory_sharing_a_name_prefix_is_not_confused(self, tmp_path):
        """`str.startswith` — the old check — accepts this; `relative_to` does not."""
        out = tmp_path / "out"
        out.mkdir()
        (tmp_path / "output-elsewhere").mkdir()
        archive = _zip(tmp_path, [("../output-elsewhere/pwned.txt", "owned")])
        with pytest.raises(UnsafeArchiveError):
            safe_extract(archive, out)
        assert not (tmp_path / "output-elsewhere" / "pwned.txt").exists()


class TestSymlinks:
    def test_a_symlink_entry_is_refused(self, tmp_path):
        """A symlink to /etc/passwd, then a second entry writing through it."""
        path = tmp_path / "link.zip"
        with zipfile.ZipFile(path, "w") as zf:
            info = zipfile.ZipInfo("passwd-link")
            info.external_attr = (0xA1FF << 16)  # symlink, 0777
            zf.writestr(info, "/etc/passwd")
        with pytest.raises(UnsafeArchiveError, match="symbolic link"):
            safe_extract(path, tmp_path / "out")


class TestDecompressionBombs:
    def test_a_high_ratio_entry_is_refused(self, tmp_path):
        """Ten megabytes of zeroes compresses to almost nothing."""
        archive = _zip(tmp_path, [("bomb.bin", b"\0" * (10 * 1024 * 1024))])
        with pytest.raises(UnsafeArchiveError, match="compression ratio"):
            safe_extract(archive, tmp_path / "out")

    def test_too_many_entries_are_refused(self, tmp_path):
        """A thousand modest files still fills a disk; the ratio test misses it."""
        archive = _zip(tmp_path, [(f"f{i}.txt", f"content {i}") for i in range(MAX_ENTRIES + 1)])
        with pytest.raises(UnsafeArchiveError, match="entries"):
            safe_extract(archive, tmp_path / "out")

    def test_the_limits_apply_to_read_only_use_as_well(self, tmp_path):
        """KMZ parsing reads into memory. A bomb fills RAM instead of a disk."""
        archive = _zip(tmp_path, [("bomb.bin", b"\0" * (10 * 1024 * 1024))])
        with zipfile.ZipFile(archive) as zf:
            with pytest.raises(UnsafeArchiveError):
                check_archive_limits(zf)


class TestOrdinaryArchivesStillWork:
    def test_a_normal_shapefile_archive_extracts(self, tmp_path):
        # Pseudo-random content, so the archive resembles a real shapefile
        # rather than one that happens to compress 100x.
        archive = _zip(tmp_path, [
            ("boundary.shp", os.urandom(2048)),
            ("boundary.dbf", os.urandom(1024)),
            ("boundary.shx", os.urandom(512)),
            ("boundary.prj", "GEOGCS[...]"),
        ])
        out = safe_extract(archive, tmp_path / "out")
        assert (out / "boundary.shp").exists()
        assert (out / "boundary.prj").read_text().startswith("GEOGCS")

    def test_nested_directories_are_fine(self, tmp_path):
        """Field tools often zip a folder, not its contents."""
        archive = _zip(tmp_path, [("survey/boundary.shp", b"\x00" * 100)])
        out = safe_extract(archive, tmp_path / "out")
        assert (out / "survey" / "boundary.shp").exists()

    def test_a_small_padded_file_is_not_mistaken_for_a_bomb(self, tmp_path):
        """Shapefile components are often mostly padding. 2 KB of zeroes
        compresses far past 100x and is completely ordinary — the ratio test
        only means something once an entry is large."""
        archive = _zip(tmp_path, [("boundary.shp", bytes(2048))])
        out = safe_extract(archive, tmp_path / "out")
        assert (out / "boundary.shp").stat().st_size == 2048

    def test_the_destination_is_created_if_absent(self, tmp_path):
        archive = _zip(tmp_path, [("a.txt", "hello")])
        out = safe_extract(archive, tmp_path / "does" / "not" / "exist")
        assert (out / "a.txt").read_text() == "hello"


class TestNoSiteExtractsWithoutIt:
    """The finding was four sites with three standards. Keep it at one."""

    def test_no_service_calls_extractall_directly(self):
        app_dir = Path(__file__).resolve().parents[1] / "app"
        offenders = []
        for path in app_dir.rglob("*.py"):
            if path.name == "safe_archive.py":
                continue  # the one place allowed to, behind the checks
            for line_no, line in enumerate(path.read_text(encoding="utf-8",
                                                          errors="replace").splitlines(), 1):
                if ".extractall(" in line and not line.strip().startswith("#"):
                    offenders.append(f"{path.relative_to(app_dir)}:{line_no}")
        assert offenders == [], (
            "extractall() outside safe_archive — use safe_extract():\n"
            + "\n".join(offenders)
        )
