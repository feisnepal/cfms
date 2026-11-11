"""One hardened ZIP extractor, used everywhere an upload is unpacked.

H2.9 / S3-10. There were four extraction sites with three different levels of
care: one checked compression ratios and path traversal, one checked traversal
only, one checked both but never extracted, and `user_group_analysis.py` called
`extractall()` with no checks at all — a shapefile ZIP containing
`../../app/main.py` would have been written straight over the application.

Uploads here are shapefile and KMZ archives from field workers, so the archive
is untrusted input by definition. What this guards against:

* **Zip slip** — entries whose path escapes the destination, via `..`, an
  absolute path, or a drive letter. Checked with `Path.relative_to`, not
  `str.startswith`: `/tmp/out` is a string prefix of `/tmp/output-elsewhere`.
* **Symlinks** — an entry can be a symlink to `/etc/passwd`, after which a
  second entry writes *through* it. Refused outright; no legitimate shapefile
  needs one.
* **ZIP bombs** — by total uncompressed size, by per-entry compression ratio,
  and by entry count. The ratio test alone is not enough: a thousand modestly
  compressed files still fills a disk.

The limits are deliberately generous. A large shapefile archive is ordinary
here; a gigabyte of it is not.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Iterable, Optional

# A shapefile set with a big .dbf can legitimately run to tens of megabytes.
MAX_TOTAL_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_ENTRY_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ENTRIES = 1000
# Below this ratio an entry is compressed more than ~100x, which is a bomb
# signature rather than a real dataset — but only once the entry is big enough
# for the ratio to mean anything. A 2 KB shapefile of mostly-zero padding
# compresses 100x and is entirely ordinary; the test caught exactly that.
# Bombs that stay under the floor are still caught by the absolute caps below.
MIN_COMPRESSION_RATIO = 0.01
RATIO_CHECK_APPLIES_ABOVE_BYTES = 1024 * 1024

# Unix mode bits: file type is the top four bits of external_attr >> 16.
_S_IFLNK = 0xA000
_S_IFMT = 0xF000


class UnsafeArchiveError(ValueError):
    """The archive is malformed or hostile. Message is safe to show a user."""


def _is_symlink(member: zipfile.ZipInfo) -> bool:
    return (member.external_attr >> 16) & _S_IFMT == _S_IFLNK


def _resolved_target(destination: Path, name: str) -> Path:
    """Where `name` would land, refusing anything outside `destination`."""
    # A member name is always POSIX-ish inside the archive, but may carry a
    # Windows drive letter or a leading slash if it was written maliciously.
    candidate = (destination / name).resolve()
    try:
        candidate.relative_to(destination.resolve())
    except ValueError:
        raise UnsafeArchiveError(
            f"Archive entry escapes the extraction directory: {name!r}"
        )
    return candidate


def check_archive_limits(zf: zipfile.ZipFile) -> None:
    """Refuse a decompression bomb. No path checks — for read-into-memory use.

    Reading a bomb entry with `ZipFile.read()` never touches the filesystem and
    is no safer for it: the expansion happens in RAM instead of on disk.
    """
    members = zf.infolist()

    if len(members) > MAX_ENTRIES:
        raise UnsafeArchiveError(
            f"Archive has {len(members)} entries, more than the {MAX_ENTRIES} allowed"
        )

    total = 0
    for member in members:
        if member.file_size > MAX_ENTRY_UNCOMPRESSED_BYTES:
            raise UnsafeArchiveError(
                f"Archive entry {member.filename!r} expands to "
                f"{member.file_size} bytes, over the per-entry limit"
            )

        total += member.file_size
        if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise UnsafeArchiveError(
                "Archive expands to more than the permitted total size"
            )

        if member.file_size > RATIO_CHECK_APPLIES_ABOVE_BYTES:
            ratio = member.compress_size / member.file_size
            if ratio < MIN_COMPRESSION_RATIO:
                raise UnsafeArchiveError(
                    f"Archive entry {member.filename!r} has a compression ratio "
                    f"consistent with a decompression bomb"
                )


def inspect_archive(zf: zipfile.ZipFile, destination: Path) -> None:
    """Refuse the archive if any member is unsafe to write. Extracts nothing."""
    check_archive_limits(zf)
    for member in zf.infolist():
        if _is_symlink(member):
            raise UnsafeArchiveError(
                f"Archive contains a symbolic link, which is not permitted: "
                f"{member.filename!r}"
            )
        _resolved_target(destination, member.filename)


def safe_extract(
    archive: zipfile.ZipFile | str | Path,
    destination: str | Path,
    members: Optional[Iterable[str]] = None,
) -> Path:
    """Extract `archive` into `destination`, or refuse it.

    Every member is checked before anything is written, so a hostile archive
    cannot leave a half-extracted mess behind — the alternative, checking as we
    go, means the malicious entry may already be on disk.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    if isinstance(archive, zipfile.ZipFile):
        inspect_archive(archive, destination)
        archive.extractall(destination, members=members)
        return destination

    with zipfile.ZipFile(archive, "r") as zf:
        inspect_archive(zf, destination)
        zf.extractall(destination, members=members)
    return destination
