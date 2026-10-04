"""Tests for organize_media_by_camera: camera-model extraction (image EXIF and MP4/MOV
atom parsing), label building, file collection, plan building, plan execution, duplicate
suffix stripping, CLI argument parsing, and the main() entry point.
"""

from __future__ import annotations

import importlib
import logging
import struct
import sys
from pathlib import Path

import pytest
from PIL import Image

import organize_media_by_camera as om
from organize_media_by_camera import (
    DUPLICATES_SUBFOLDER,
    FALLBACK_FOLDER,
    _build_label,
    _clean_stem,
    _find_camera_atoms,
    _model_from_image,
    _model_from_video,
    _read_atoms,
    _read_string_atom,
    _resolve_keys_atom,
    _sanitize_folder_name,
    _unique_path,
    build_plan,
    collect_media,
    execute_plan,
    get_camera_model,
    strip_duplicate_suffix,
)

# ============================================================
# Test helpers: synthetic MP4/MOV atom builders
# ============================================================
#
# These build the exact byte layouts that organize_media_by_camera's atom
# parser expects, without depending on any real video file.

# 4B size + 4B name header used by every standard QuickTime/MP4 atom.
_ATOM_HEADER_SIZE = 8
# 4B size=1 + 4B name + 8B extended size, used by the 64-bit atom form.
_ATOM64_HEADER_SIZE = 16
# iTunes 'data' atom type code for a UTF-8 text payload.
_DATA_ATOM_TEXT_TYPE = 1
# iTunes 'data' atom locale/country code; unused, always zero in these tests.
_DATA_ATOM_LOCALE = 0
# 4-byte version/flags prefix shared by 'meta', 'keys', and 'auth' atoms.
_QT_METADATA_VERSION_FLAGS = 0


def atom(name: bytes, payload: bytes) -> bytes:
    """Build a standard (32-bit size) atom: 4B size + 4B name + payload."""
    size = _ATOM_HEADER_SIZE + len(payload)
    return struct.pack(">I4s", size, name) + payload


def atom64(name: bytes, payload: bytes) -> bytes:
    """Build an atom using the 64-bit extended-size form (size field == 1)."""
    size = _ATOM64_HEADER_SIZE + len(payload)
    return struct.pack(">I4s", 1, name) + struct.pack(">Q", size) + payload


def data_atom(value: str) -> bytes:
    """Build an iTunes-style 'data' child atom: 4B type + 4B locale + UTF-8 payload."""
    content = struct.pack(">II", _DATA_ATOM_TEXT_TYPE, _DATA_ATOM_LOCALE)
    content += value.encode("utf-8")
    return atom(b"data", content)


def itunes_string_atom(tag: bytes, value: str) -> bytes:
    """Build a direct udta/©tag atom containing a nested 'data' atom (e.g.
    b'\\xa9mod')."""
    return atom(tag, data_atom(value))


def keys_atom_content(keys: list[str], trailing_null: bool = False) -> bytes:
    """Build the content (data region, no atom header) of a 'keys' metadata atom."""
    content = struct.pack(">II", _QT_METADATA_VERSION_FLAGS, len(keys))
    for key in keys:
        key_bytes = key.encode("utf-8")
        if trailing_null:
            key_bytes += b"\x00"
        entry_size = _ATOM_HEADER_SIZE + len(key_bytes)
        content += struct.pack(">I4s", entry_size, b"mdta") + key_bytes
    return content


def keys_atom(keys: list[str], trailing_null: bool = False) -> bytes:
    """Build a full 'keys' atom (header + content)."""
    return atom(b"keys", keys_atom_content(keys, trailing_null=trailing_null))


def ilst_index_entry(idx: int, value: str) -> bytes:
    """Build a numeric-index ilst entry (name = big-endian uint32 of idx) wrapping
    data."""
    idx_name = struct.pack(">I", idx)
    return atom(idx_name, data_atom(value))


def ilst_string_entry(tag: bytes, value: str) -> bytes:
    """Build a literal-key ilst entry such as b'\\xa9mod' wrapping a data atom."""
    return atom(tag, data_atom(value))


def ilst_atom(*entries: bytes) -> bytes:
    """Build a full 'ilst' atom from pre-built entry bytes."""
    return atom(b"ilst", b"".join(entries))


def pack_3gpp_lang(code: str) -> bytes:
    """Pack a 3-letter ISO-639-2 language code (e.g. 'eng') into the 3GPP 2-byte
    form."""
    c1, c2, c3 = (ord(ch) - 0x60 for ch in code)
    packed = (c1 << 10) | (c2 << 5) | c3
    return struct.pack(">H", packed)


def moov_with_udta_direct(make: str, model: str) -> bytes:
    """moov -> udta -> ©mak / ©mod directly (no meta/keys/ilst nesting)."""
    udta_content = itunes_string_atom(b"\xa9mak", make)
    udta_content += itunes_string_atom(b"\xa9mod", model)
    return atom(b"moov", atom(b"udta", udta_content))


def moov_with_udta_meta_ilst(
    make: str | None,
    model: str | None,
    *,
    use_numeric_keys: bool = False,
    trailing_null: bool = False,
) -> bytes:
    """moov -> udta -> meta (4B version prefix) -> keys + ilst -> make/model."""
    entries = []
    keys: list[str] = []
    if use_numeric_keys:
        if make is not None:
            keys.append("com.apple.quicktime.make")
            entries.append(ilst_index_entry(len(keys), make))
        if model is not None:
            keys.append("com.apple.quicktime.model")
            entries.append(ilst_index_entry(len(keys), model))
        keys_bytes = keys_atom(keys, trailing_null=trailing_null)
    else:
        if make is not None:
            entries.append(ilst_string_entry(b"\xa9mak", make))
        if model is not None:
            entries.append(ilst_string_entry(b"\xa9mod", model))
        keys_bytes = b""

    meta_body = keys_bytes + ilst_atom(*entries)
    version_prefix = struct.pack(">I", _QT_METADATA_VERSION_FLAGS)
    meta_atom = atom(b"meta", version_prefix + meta_body)
    return atom(b"moov", atom(b"udta", meta_atom))


def moov_with_meta_direct(
    make: str | None,
    model: str | None,
    *,
    with_version_header: bool,
) -> bytes:
    """moov -> meta -> keys + ilst (iPhone MOV layout), with/without the 4B prefix."""
    entries = []
    keys: list[str] = []
    if make is not None:
        keys.append("com.apple.quicktime.make")
        entries.append(ilst_index_entry(len(keys), make))
    if model is not None:
        keys.append("com.apple.quicktime.model")
        entries.append(ilst_index_entry(len(keys), model))

    meta_body = keys_atom(keys) + ilst_atom(*entries)
    if with_version_header:
        meta_content = struct.pack(">I", _QT_METADATA_VERSION_FLAGS) + meta_body
    else:
        meta_content = meta_body
    return atom(b"moov", atom(b"meta", meta_content))


def moov_with_samsung_auth(device_name: str, lang: str = "eng") -> bytes:
    """moov -> udta -> auth (4B version/flags + packed 3GPP lang + device name)."""
    auth_content = struct.pack(">I", _QT_METADATA_VERSION_FLAGS)
    auth_content += pack_3gpp_lang(lang) + device_name.encode("utf-8") + b"\x00"
    return atom(b"moov", atom(b"udta", atom(b"auth", auth_content)))


def moov_with_samsung_auth_invalid_utf8() -> bytes:
    """moov -> udta -> auth whose payload is not valid UTF-8, forcing the decode-failure
    branch."""
    auth_content = struct.pack(">I", _QT_METADATA_VERSION_FLAGS)
    auth_content += pack_3gpp_lang("eng") + b"\xff\xfe\x80\x81"
    return atom(b"moov", atom(b"udta", atom(b"auth", auth_content)))


def moov_with_samsung_auth_no_lang_code(device_name: str) -> bytes:
    """Build an auth atom whose leading bytes do not form a valid packed 3GPP language
    code, so the parser must fall back to lstrip()-ing leading non-printable bytes
    instead of unconditionally skipping a fixed 2-byte language prefix."""
    auth_content = struct.pack(">I", _QT_METADATA_VERSION_FLAGS)
    auth_content += b"\x00" + device_name.encode("utf-8") + b"\x00"
    return atom(b"moov", atom(b"udta", atom(b"auth", auth_content)))


def moov_with_samsung_smta(model: str | None = None, make: str | None = None) -> bytes:
    """moov -> udta -> smta blob containing 'mdln'/'manu' key=value markers."""
    blob = b"\x00\x00\x00\x00junk"
    if model is not None:
        blob += b"mdln" + model.encode("ascii") + b"\x00junk"
    if make is not None:
        blob += b"manu" + make.encode("ascii") + b"\x00junk"
    return atom(b"moov", atom(b"udta", atom(b"smta", blob)))


def moov_empty() -> bytes:
    """A moov atom with no udta/meta children at all."""
    return atom(b"moov", b"")


def no_moov_atom() -> bytes:
    """A file containing an unrelated top-level atom but no 'moov' at all."""
    return atom(b"free", b"filler")


# ============================================================
# Test helpers: synthetic JPEG image builders
# ============================================================

# Standard EXIF tag ids for the Make and Model fields (Exif.Image.Make / Model).
_EXIF_MAKE_TAG_ID = 271
_EXIF_MODEL_TAG_ID = 272


def make_jpeg_with_exif(
    path: Path, *, make: str | None = None, model: str | None = None
) -> Path:
    """Write a tiny JPEG at *path*, optionally with EXIF Make/Model tags."""
    img = Image.new("RGB", (4, 4), color="red")
    exif = Image.Exif()
    if make is not None:
        exif[_EXIF_MAKE_TAG_ID] = make
    if model is not None:
        exif[_EXIF_MODEL_TAG_ID] = model
    img.save(path, exif=exif)
    return path


def make_jpeg_without_exif(path: Path) -> Path:
    """Write a tiny JPEG at *path* with no EXIF block at all."""
    img = Image.new("RGB", (4, 4), color="blue")
    img.save(path)
    return path


# ============================================================
# Shared test fixtures/helpers
# ============================================================


def _touch(path: Path, content: bytes = b"x") -> Path:
    """Create *path* (and its parent folders) with *content*, returning the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_atom_bytes(tmp_path: Path, content: bytes) -> Path:
    """Write raw atom *content* to a throwaway file under tmp_path."""
    path = tmp_path / "sample.bin"
    path.write_bytes(content)
    return path


def _write_and_find(tmp_path: Path, content: bytes) -> tuple[str, str]:
    """Write *content* as clip.mp4 and run the full atom-scan + camera-atom lookup."""
    path = tmp_path / "clip.mp4"
    path.write_bytes(content)
    with open(path, "rb") as fh:
        top_atoms = _read_atoms(fh, 0, len(content))
        return _find_camera_atoms(fh, top_atoms)


@pytest.fixture
def require_case_insensitive_fs(tmp_path: Path) -> None:
    """Skip the test if the filesystem backing tmp_path is case-sensitive."""
    probe = tmp_path / "A"
    probe.write_text("x")
    is_case_insensitive = (tmp_path / "a").exists()
    probe.unlink()
    if not is_case_insensitive:
        pytest.skip("This test requires a case-insensitive filesystem.")


# ============================================================
# Module import: optional pillow_heif dependency
# ============================================================


def test_module_falls_back_to_none_when_pillow_heif_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If importing pillow_heif raises ImportError, the module sets pillow_heif = None
    instead of crashing, so HEIC/HEIF support degrades gracefully. Setting
    sys.modules["pillow_heif"] = None is the standard mechanism to make any
    subsequent `import pillow_heif` raise ImportError, without patching
    builtins.__import__.
    """
    monkeypatch.setitem(sys.modules, "pillow_heif", None)
    monkeypatch.delitem(sys.modules, "organize_media_by_camera", raising=False)

    try:
        module = importlib.import_module("organize_media_by_camera")
        assert module.pillow_heif is None
    finally:
        # Restore a normal module instance in sys.modules so tests collected
        # afterwards still import organize_media_by_camera fresh.
        sys.modules.pop("organize_media_by_camera", None)
        importlib.import_module("organize_media_by_camera")


# ============================================================
# get_camera_model: extension dispatch
# ============================================================


def test_get_camera_model_dispatches_image_extension(tmp_path: Path) -> None:
    """get_camera_model routes .jpg files (case-insensitively) through the image
    metadata path."""
    path = make_jpeg_with_exif(
        tmp_path / "photo.JPG", make="Apple", model="iPhone 14 Pro"
    )
    assert get_camera_model(path) == "Apple_iPhone_14_Pro"


def test_get_camera_model_dispatches_video_extension(tmp_path: Path) -> None:
    """get_camera_model routes .mov files through the video metadata path."""
    path = tmp_path / "clip.mov"
    path.write_bytes(moov_with_udta_direct("Apple", "iPhone 14 Pro"))
    assert get_camera_model(path) == "Apple_iPhone_14_Pro"


def test_get_camera_model_unsupported_extension_returns_fallback(
    tmp_path: Path,
) -> None:
    """An unsupported extension (not image, not video) returns the fallback folder
    directly."""
    path = tmp_path / "notes.txt"
    path.write_text("not media")
    assert get_camera_model(path) == "Unknown_Device"


# ============================================================
# _model_from_image
# ============================================================


def test_model_from_image_reads_make_and_model(tmp_path: Path) -> None:
    """A JPEG with EXIF Make and Model tags yields the sanitized combined label."""
    path = make_jpeg_with_exif(
        tmp_path / "photo.jpg", make="Apple", model="iPhone 14 Pro"
    )
    assert _model_from_image(path) == "Apple_iPhone_14_Pro"


def test_model_from_image_no_exif_segment_returns_fallback(tmp_path: Path) -> None:
    """A JPEG with no EXIF segment at all falls back to Unknown_Device."""
    path = make_jpeg_without_exif(tmp_path / "photo.jpg")
    assert _model_from_image(path) == "Unknown_Device"


def test_model_from_image_only_model_no_make(tmp_path: Path) -> None:
    """A JPEG with only a Model tag (no Make) still yields a usable label."""
    path = make_jpeg_with_exif(tmp_path / "photo.jpg", model="iPhone 14 Pro")
    assert _model_from_image(path) == "iPhone_14_Pro"


def test_model_from_image_corrupt_file_returns_fallback(tmp_path: Path) -> None:
    """A file with a .jpg extension that is not actually a valid image falls back
    cleanly."""
    path = tmp_path / "corrupt.jpg"
    path.write_bytes(b"not a real jpeg")
    assert _model_from_image(path) == "Unknown_Device"


# ============================================================
# _model_from_video
# ============================================================


def test_model_from_video_builds_sanitized_label(tmp_path: Path) -> None:
    """_model_from_video combines make/model into the same sanitized label as
    _build_label."""
    path = tmp_path / "clip.mp4"
    path.write_bytes(moov_with_udta_direct("Apple", "iPhone 14 Pro"))
    assert _model_from_video(path) == "Apple_iPhone_14_Pro"


def test_model_from_video_no_metadata_returns_fallback(tmp_path: Path) -> None:
    """A video with no recognisable camera metadata falls back to Unknown_Device."""
    path = tmp_path / "clip.mp4"
    path.write_bytes(moov_empty())
    assert _model_from_video(path) == "Unknown_Device"


def test_model_from_video_unreadable_file_returns_fallback(tmp_path: Path) -> None:
    """An I/O error while reading the file is caught and falls back to
    Unknown_Device."""
    missing = tmp_path / "missing.mp4"
    assert _model_from_video(missing) == "Unknown_Device"


# ============================================================
# _read_atoms
# ============================================================


def test_read_atoms_finds_single_top_level_atom(tmp_path: Path) -> None:
    """A single well-formed atom is found with the correct data offset and size."""
    content = atom(b"free", b"hello")
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        atoms = _read_atoms(fh, 0, len(content))
    assert atoms == {"free": (8, 5)}


def test_read_atoms_finds_multiple_sibling_atoms_in_order(tmp_path: Path) -> None:
    """Two sibling atoms are both discovered, each with the correct offset."""
    content = atom(b"ftyp", b"isom") + atom(b"moov", b"xy")
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        atoms = _read_atoms(fh, 0, len(content))
    assert atoms["ftyp"] == (8, 4)
    # ftyp's atom is 12 bytes total, then moov's own 8-byte header follows.
    assert atoms["moov"] == (20, 2)


def test_read_atoms_handles_64bit_extended_size(tmp_path: Path) -> None:
    """An atom with size==1 uses the following 8-byte field as its real (64-bit)
    size."""
    content = atom64(b"mdat", b"payload-bytes")
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        atoms = _read_atoms(fh, 0, len(content))
    assert atoms == {"mdat": (16, len(b"payload-bytes"))}


def test_read_atoms_stops_on_truncated_header(tmp_path: Path) -> None:
    """A dangling partial atom header (fewer than 8 bytes left) is silently
    ignored."""
    content = atom(b"free", b"ok") + b"\x00\x00\x00"
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        atoms = _read_atoms(fh, 0, len(content))
    assert list(atoms.keys()) == ["free"]


def test_read_atoms_stops_on_size_smaller_than_header(tmp_path: Path) -> None:
    """An atom whose declared size is smaller than the header itself aborts the
    scan."""
    # size=4 is less than the minimum 8-byte header.
    content = struct.pack(">I4s", 4, b"bad!") + atom(b"free", b"never-reached")
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        atoms = _read_atoms(fh, 0, len(content))
    assert atoms == {}


def test_read_atoms_empty_range_returns_empty_dict(tmp_path: Path) -> None:
    """Scanning an empty byte range yields no atoms."""
    path = _write_atom_bytes(tmp_path, b"")
    with open(path, "rb") as fh:
        atoms = _read_atoms(fh, 0, 0)
    assert atoms == {}


def test_read_atoms_declared_end_beyond_actual_file_size_stops_cleanly(
    tmp_path: Path,
) -> None:
    """If *end* claims more bytes exist than the file actually has, the scan stops
    instead of reading a short, invalid header."""
    content = atom(b"free", b"ok")
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        # Claim the range extends 100 bytes past the real end of the file.
        atoms = _read_atoms(fh, 0, len(content) + 100)
    assert list(atoms.keys()) == ["free"]


def test_read_atoms_truncated_64bit_extended_size_field_stops_cleanly(
    tmp_path: Path,
) -> None:
    """A size==1 header whose 8-byte extended-size field is cut short is ignored,
    not crashed on."""
    # size=1 header (8 bytes) followed by only 4 bytes instead of the required 8.
    content = struct.pack(">I4s", 1, b"mdat") + b"\x00\x00\x00\x00"
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        atoms = _read_atoms(fh, 0, len(content))
    assert atoms == {}


# ============================================================
# _resolve_keys_atom
# ============================================================


def test_resolve_keys_atom_maps_indices_to_names(tmp_path: Path) -> None:
    """Each 1-based entry in a 'keys' atom resolves to its key name string."""
    content = keys_atom_content(
        ["com.apple.quicktime.make", "com.apple.quicktime.model"]
    )
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        mapping = _resolve_keys_atom(fh, (0, len(content)))
    assert mapping == {1: "com.apple.quicktime.make", 2: "com.apple.quicktime.model"}


def test_resolve_keys_atom_tolerates_trailing_null(tmp_path: Path) -> None:
    """A key string with a trailing null byte is still decoded correctly (null
    stripped)."""
    content = keys_atom_content(["com.apple.quicktime.make"], trailing_null=True)
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        mapping = _resolve_keys_atom(fh, (0, len(content)))
    assert mapping == {1: "com.apple.quicktime.make"}


def test_resolve_keys_atom_empty_count_returns_empty_mapping(tmp_path: Path) -> None:
    """A keys atom declaring zero entries resolves to an empty mapping."""
    content = keys_atom_content([])
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        mapping = _resolve_keys_atom(fh, (0, len(content)))
    assert mapping == {}


def test_resolve_keys_atom_truncated_header_returns_empty_mapping(
    tmp_path: Path,
) -> None:
    """Fewer than 8 bytes available (no room for version/flags + count) yields an
    empty mapping."""
    content = b"\x00\x00"
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        mapping = _resolve_keys_atom(fh, (0, len(content)))
    assert mapping == {}


def test_resolve_keys_atom_stops_on_entry_size_below_minimum(tmp_path: Path) -> None:
    """An entry declaring a size smaller than the 8-byte minimum (size+namespace)
    stops parsing."""
    content = struct.pack(">II", 0, 1) + struct.pack(">I4s", 4, b"mdta")
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        mapping = _resolve_keys_atom(fh, (0, len(content)))
    assert mapping == {}


def test_resolve_keys_atom_stops_on_truncated_entry(tmp_path: Path) -> None:
    """A declared entry count higher than what actually fits stops parsing early,
    without raising."""
    # Declare 2 entries but only provide bytes for one.
    content = struct.pack(">II", 0, 2) + struct.pack(">I4s", 8 + 4, b"mdta") + b"only"
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        mapping = _resolve_keys_atom(fh, (0, len(content)))
    assert mapping == {1: "only"}


# ============================================================
# _find_camera_atoms
# ============================================================


def test_udta_direct_make_and_model(tmp_path: Path) -> None:
    """Camera make/model are read directly from moov/udta/©mak and ©mod."""
    content = moov_with_udta_direct("Apple", "iPhone 14 Pro")
    make, model = _write_and_find(tmp_path, content)
    assert (make, model) == ("Apple", "iPhone 14 Pro")


def test_udta_meta_ilst_literal_keys(tmp_path: Path) -> None:
    """Literal '©mak'/'©mod' entries nested under udta/meta/ilst are found
    (Path A)."""
    content = moov_with_udta_meta_ilst("Apple", "iPhone 14 Pro", use_numeric_keys=False)
    make, model = _write_and_find(tmp_path, content)
    assert (make, model) == ("Apple", "iPhone 14 Pro")


def test_udta_meta_ilst_numeric_keys_resolved_via_keys_atom(tmp_path: Path) -> None:
    """Numeric ilst indices are resolved through the keys atom's quicktime.make/model
    names (Path B)."""
    content = moov_with_udta_meta_ilst("Apple", "iPhone 14 Pro", use_numeric_keys=True)
    make, model = _write_and_find(tmp_path, content)
    assert (make, model) == ("Apple", "iPhone 14 Pro")


def test_udta_meta_ilst_numeric_keys_with_trailing_null(tmp_path: Path) -> None:
    """Numeric-key resolution still works when the keys atom's key strings have a
    trailing null."""
    content = moov_with_udta_meta_ilst(
        "Apple", "iPhone 14 Pro", use_numeric_keys=True, trailing_null=True
    )
    make, model = _write_and_find(tmp_path, content)
    assert (make, model) == ("Apple", "iPhone 14 Pro")


def test_udta_meta_ilst_missing_model_only_make_found(tmp_path: Path) -> None:
    """When only the make is present under udta/meta/ilst, model stays empty."""
    content = moov_with_udta_meta_ilst("Apple", None, use_numeric_keys=True)
    make, model = _write_and_find(tmp_path, content)
    assert (make, model) == ("Apple", "")


def test_udta_meta_ilst_numeric_index_with_no_matching_keys_entry_is_skipped(
    tmp_path: Path,
) -> None:
    """An ilst entry whose numeric index has no corresponding name in the keys atom
    is ignored."""
    # keys atom declares only 1 entry, but the ilst has an entry at index 2 too.
    entries = ilst_index_entry(1, "Apple") + ilst_index_entry(2, "Unmapped Value")
    keys_bytes = keys_atom(["com.apple.quicktime.make"])
    meta_body = keys_bytes + ilst_atom(entries)
    meta_atom = atom(b"meta", struct.pack(">I", 0) + meta_body)
    content = atom(b"moov", atom(b"udta", meta_atom))

    make, model = _write_and_find(tmp_path, content)
    assert make == "Apple"
    assert model == ""


def test_moov_meta_direct_without_version_header(tmp_path: Path) -> None:
    """moov/meta/keys+ilst is found directly, with no 4-byte version/flags prefix on
    meta."""
    content = moov_with_meta_direct("Apple", "iPhone 14 Pro", with_version_header=False)
    make, model = _write_and_find(tmp_path, content)
    assert (make, model) == ("Apple", "iPhone 14 Pro")


def test_moov_meta_direct_with_version_header(tmp_path: Path) -> None:
    """moov/meta/keys+ilst is found after retrying with the 4-byte version/flags
    prefix skipped."""
    content = moov_with_meta_direct("Apple", "iPhone 14 Pro", with_version_header=True)
    make, model = _write_and_find(tmp_path, content)
    assert (make, model) == ("Apple", "iPhone 14 Pro")


def test_samsung_auth_with_valid_3gpp_lang_code(tmp_path: Path) -> None:
    """A well-formed 3GPP packed language code ('eng') is skipped, leaving just the
    device name."""
    content = moov_with_samsung_auth("Galaxy S25", lang="eng")
    make, model = _write_and_find(tmp_path, content)
    assert model == "Galaxy S25"
    assert make == ""


def test_samsung_auth_with_und_lang_code(tmp_path: Path) -> None:
    """The 'und' (undetermined) 3GPP language code is also recognised and
    skipped."""
    content = moov_with_samsung_auth("Galaxy S24", lang="und")
    make, model = _write_and_find(tmp_path, content)
    assert model == "Galaxy S24"


def test_samsung_auth_with_kor_lang_code(tmp_path: Path) -> None:
    """The 'kor' 3GPP language code is also recognised and skipped."""
    content = moov_with_samsung_auth("Galaxy S23", lang="kor")
    make, model = _write_and_find(tmp_path, content)
    assert model == "Galaxy S23"


def test_samsung_auth_without_valid_lang_code_uses_lstrip_fallback(
    tmp_path: Path,
) -> None:
    """When the leading 2 bytes are not a valid packed language code, lstrip()
    strips them instead."""
    content = moov_with_samsung_auth_no_lang_code("Galaxy S22")
    make, model = _write_and_find(tmp_path, content)
    assert model == "Galaxy S22"


def test_samsung_auth_invalid_utf8_payload_is_ignored(tmp_path: Path) -> None:
    """A non-UTF-8 auth payload is caught and treated as no device name found."""
    make, model = _write_and_find(tmp_path, moov_with_samsung_auth_invalid_utf8())
    assert (make, model) == ("", "")


def test_samsung_smta_supplies_model_and_make(tmp_path: Path) -> None:
    """The 'smta' atom's mdln/manu key=value markers supplement missing
    make/model."""
    content = moov_with_samsung_smta(model="SM-S931B", make="Samsung")
    make, model = _write_and_find(tmp_path, content)
    assert make == "Samsung"
    assert model == "SM-S931B"


def test_samsung_smta_does_not_override_auth_model(tmp_path: Path) -> None:
    """smta only supplements missing fields; it never overrides a model already
    found via auth."""
    # Build a single udta atom with both auth (yields a model) and a conflicting
    # smta model, so the auth-derived model must win.
    auth_content = struct.pack(">I", 0) + pack_3gpp_lang("eng") + b"Galaxy S25\x00"
    smta_blob = b"mdln" + b"OTHER-MODEL" + b"\x00"
    udta_content = atom(b"auth", auth_content) + atom(b"smta", smta_blob)
    combined = atom(b"moov", atom(b"udta", udta_content))

    make, model = _write_and_find(tmp_path, combined)
    assert model == "Galaxy S25"


def test_moov_with_no_udta_or_meta_returns_empty(tmp_path: Path) -> None:
    """A moov atom with no udta/meta children returns empty make and model."""
    make, model = _write_and_find(tmp_path, moov_empty())
    assert (make, model) == ("", "")


def test_no_moov_atom_at_all_returns_empty(tmp_path: Path) -> None:
    """A file with no moov atom at all returns empty make and model."""
    path = tmp_path / "clip.mp4"
    content = no_moov_atom()
    path.write_bytes(content)
    with open(path, "rb") as fh:
        top_atoms = _read_atoms(fh, 0, len(content))
        make, model = _find_camera_atoms(fh, top_atoms)
    assert (make, model) == ("", "")


# ============================================================
# _read_string_atom
# ============================================================


def test_read_string_atom_returns_decoded_value(tmp_path: Path) -> None:
    """A well-formed nested 'data' atom yields its UTF-8 payload, stripped."""
    content = data_atom("  Apple iPhone 14 Pro  ")
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        value = _read_string_atom(fh, (0, len(content)))
    assert value == "Apple iPhone 14 Pro"


def test_read_string_atom_no_data_child_returns_empty_string(tmp_path: Path) -> None:
    """When no 'data' child atom is present, an empty string is returned."""
    content = atom(b"xxxx", b"filler")
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        value = _read_string_atom(fh, (0, len(content)))
    assert value == ""


def test_read_string_atom_data_child_too_small_is_ignored(tmp_path: Path) -> None:
    """A 'data' child atom smaller than the required 16-byte header is skipped, not
    crashed on."""
    content = struct.pack(">I4s", 8, b"data")  # below the 16-byte minimum
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        value = _read_string_atom(fh, (0, len(content)))
    assert value == ""


def test_read_string_atom_stops_on_malformed_child_size(tmp_path: Path) -> None:
    """A malformed child header declaring a size below the minimum 8-byte header
    aborts the scan."""
    content = struct.pack(">I4s", 4, b"bad!")  # below the 8-byte header minimum
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        value = _read_string_atom(fh, (0, len(content)))
    assert value == ""


def test_read_string_atom_skips_non_data_sibling_before_finding_data(
    tmp_path: Path,
) -> None:
    """A non-'data' sibling atom preceding the real 'data' atom is skipped over
    using its own declared size (not a fixed guess), so the scan lands correctly on
    the real 'data' atom."""
    non_data_child = atom(b"name", b"xx")
    content = non_data_child + data_atom("Apple")
    path = _write_atom_bytes(tmp_path, content)
    with open(path, "rb") as fh:
        value = _read_string_atom(fh, (0, len(content)))
    assert value == "Apple"


# ============================================================
# _build_label
# ============================================================


def test_build_label_no_make_or_model_returns_fallback() -> None:
    """Empty make and model falls back to the Unknown_Device folder."""
    assert _build_label("", "") == FALLBACK_FOLDER


def test_build_label_combines_make_and_model() -> None:
    """A distinct make and model are joined with a space, then sanitized."""
    assert _build_label("Canon", "EOS R5") == "Canon_EOS_R5"


def test_build_label_drops_make_prefix_already_in_model() -> None:
    """When the model already starts with the make (e.g. 'Apple iPhone 14'), the
    make is not duplicated."""
    assert _build_label("Apple", "Apple iPhone 14") == "Apple_iPhone_14"


def test_build_label_drops_make_prefix_case_insensitively() -> None:
    """The make-prefix check is case-insensitive."""
    assert _build_label("APPLE", "apple iPhone 14") == "apple_iPhone_14"


def test_build_label_make_only() -> None:
    """Only a make (no model) is used as-is."""
    assert _build_label("Sony", "") == "Sony"


def test_build_label_model_only() -> None:
    """Only a model (no make) is used as-is."""
    assert _build_label("", "Galaxy S25") == "Galaxy_S25"


def test_build_label_strips_whitespace() -> None:
    """Leading/trailing whitespace on make and model is stripped before
    combining."""
    assert _build_label("  Canon  ", "  EOS R5  ") == "Canon_EOS_R5"


# ============================================================
# _sanitize_folder_name
# ============================================================


def test_sanitize_folder_name_replaces_unsafe_characters() -> None:
    """Characters unsafe in Windows folder names are replaced with underscores."""
    assert _sanitize_folder_name('a/b:c*d?e"f<g>h|i') == "a_b_c_d_e_f_g_h_i"


def test_sanitize_folder_name_replaces_spaces() -> None:
    """Spaces are replaced with underscores."""
    assert _sanitize_folder_name("Canon EOS R5") == "Canon_EOS_R5"


def test_sanitize_folder_name_strips_control_characters() -> None:
    """Null bytes and other control characters are stripped entirely, not
    replaced."""
    assert _sanitize_folder_name("Canon\x00 EOS\x01 R5") == "Canon_EOS_R5"


def test_sanitize_folder_name_strips_leading_trailing_underscores() -> None:
    """Underscores produced at the very start/end of the name are trimmed away."""
    assert _sanitize_folder_name("/Canon EOS R5/") == "Canon_EOS_R5"


def test_sanitize_folder_name_empty_result_falls_back() -> None:
    """A name that sanitizes down to nothing at all falls back to Unknown_Device."""
    assert _sanitize_folder_name("///") == FALLBACK_FOLDER


def test_sanitize_folder_name_only_control_characters_falls_back() -> None:
    """A name made up entirely of control characters also falls back to
    Unknown_Device."""
    assert _sanitize_folder_name("\x00\x01\x02") == FALLBACK_FOLDER


# ============================================================
# collect_media
# ============================================================


def test_collect_media_non_recursive_ignores_subfolders(tmp_path: Path) -> None:
    """Without --recursive, only top-level files are collected."""
    _touch(tmp_path / "a.jpg")
    _touch(tmp_path / "sub" / "b.jpg")

    found = collect_media(tmp_path, recursive=False)

    assert [p.name for p in found] == ["a.jpg"]


def test_collect_media_recursive_includes_subfolders(tmp_path: Path) -> None:
    """With --recursive, files in nested subfolders are also collected."""
    _touch(tmp_path / "a.jpg")
    _touch(tmp_path / "sub" / "b.mp4")

    found = collect_media(tmp_path, recursive=True)

    assert {p.name for p in found} == {"a.jpg", "b.mp4"}


def test_collect_media_filters_by_supported_extension(tmp_path: Path) -> None:
    """Files with unsupported extensions are excluded, regardless of case."""
    _touch(tmp_path / "photo.JPG")
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "archive.zip")

    found = collect_media(tmp_path, recursive=False)

    assert [p.name for p in found] == ["photo.JPG"]


def test_collect_media_ignores_directories_matching_pattern(tmp_path: Path) -> None:
    """A directory literally named like a media file (e.g. 'clip.mp4/') is not
    collected."""
    (tmp_path / "clip.mp4").mkdir()
    _touch(tmp_path / "real.mp4")

    found = collect_media(tmp_path, recursive=False)

    assert [p.name for p in found] == ["real.mp4"]


def test_collect_media_empty_folder_returns_empty_list(tmp_path: Path) -> None:
    """An empty source folder yields an empty list, not an error."""
    assert collect_media(tmp_path, recursive=False) == []


# ============================================================
# build_plan
# ============================================================


def test_build_plan_groups_files_by_camera_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each photo is grouped under the folder name returned by get_camera_model."""
    photo_a = _touch(tmp_path / "a.jpg")
    photo_b = _touch(tmp_path / "b.jpg")
    photo_c = _touch(tmp_path / "c.jpg")

    labels = {photo_a: "Apple_iPhone", photo_b: "Apple_iPhone", photo_c: "Canon_EOS"}
    monkeypatch.setattr(om, "get_camera_model", lambda p: labels[p])

    plan = build_plan([photo_a, photo_b, photo_c], tmp_path)

    assert set(plan["Apple_iPhone"]) == {photo_a, photo_b}
    assert plan["Canon_EOS"] == [photo_c]


def test_build_plan_empty_input_returns_empty_plan(tmp_path: Path) -> None:
    """No input photos produces an empty plan dict."""
    assert build_plan([], tmp_path) == {}


# ============================================================
# _clean_stem
# ============================================================


def test_clean_stem_strips_windows_style_paren_suffix() -> None:
    """A trailing ' (1)' Windows-style duplicate suffix is stripped."""
    assert _clean_stem("IMG_1234 (1)") == "IMG_1234"


def test_clean_stem_strips_numeric_underscore_suffix() -> None:
    """A trailing '_1'..'_9' unique_path-style suffix is stripped."""
    assert _clean_stem("IMG_1234_3") == "IMG_1234"


def test_clean_stem_no_suffix_returns_none() -> None:
    """A stem with no recognised duplicate suffix returns None."""
    assert _clean_stem("IMG_1234") is None


def test_clean_stem_rejects_out_of_range_numeric_suffix() -> None:
    """'_0' is not a valid single-digit 1-9 suffix, so it is left untouched (returns
    None)."""
    assert _clean_stem("IMG_1234_0") is None


# ============================================================
# execute_plan
# ============================================================


def test_execute_plan_dry_run_makes_no_filesystem_changes(tmp_path: Path) -> None:
    """In dry-run mode, no folders are created and no source files are touched,
    even when --ext-case is combined with the run (the planned rename is only
    logged, never applied)."""
    source = tmp_path / "source"
    dest = tmp_path / "source"  # same as source, matches default CLI behaviour
    photo = _touch(source / "a.JPG")
    plan = {"Apple_iPhone": [photo]}

    files_ok, files_skipped, files_duplicated = execute_plan(
        plan, dest, copy=False, dry_run=True, ext_case="lower"
    )

    assert photo.exists()
    assert not (dest / "Apple_iPhone").exists()
    names = [p.name for p in photo.parent.iterdir()]
    assert names == ["a.JPG"]
    assert (files_ok, files_skipped, files_duplicated) == (1, 0, 0)


def test_execute_plan_live_move_relocates_file(tmp_path: Path) -> None:
    """A live run with copy=False moves the file into the destination subfolder."""
    photo = _touch(tmp_path / "source" / "a.jpg")
    dest = tmp_path / "dest"
    plan = {"Apple_iPhone": [photo]}

    result = execute_plan(plan, dest, copy=False, dry_run=False)

    assert not photo.exists()
    assert (dest / "Apple_iPhone" / "a.jpg").exists()
    assert result == (1, 0, 0)


def test_execute_plan_live_copy_keeps_source_file(tmp_path: Path) -> None:
    """A live run with copy=True leaves the original file in place and creates an
    identical copy."""
    photo = _touch(tmp_path / "source" / "a.jpg", content=b"original-bytes")
    dest = tmp_path / "dest"
    plan = {"Apple_iPhone": [photo]}

    result = execute_plan(plan, dest, copy=True, dry_run=False)

    copied = dest / "Apple_iPhone" / "a.jpg"
    assert photo.exists()
    assert copied.exists()
    assert copied.read_bytes() == photo.read_bytes() == b"original-bytes"
    assert result == (1, 0, 0)


def test_execute_plan_exact_name_collision_routes_to_duplicates(tmp_path: Path) -> None:
    """A source file whose name already exists in the target folder is routed to
    duplicates/."""
    dest = tmp_path / "dest"
    _touch(dest / "Apple_iPhone" / "a.jpg", content=b"already-there")
    incoming = _touch(tmp_path / "source" / "a.jpg", content=b"incoming")
    plan = {"Apple_iPhone": [incoming]}

    result = execute_plan(plan, dest, copy=False, dry_run=False)

    assert (dest / "Apple_iPhone" / "a.jpg").read_bytes() == b"already-there"
    dup_file = dest / "Apple_iPhone" / DUPLICATES_SUBFOLDER / "a.jpg"
    assert dup_file.read_bytes() == b"incoming"
    assert result == (1, 0, 1)


def test_execute_plan_semantic_duplicate_of_clean_stem_routes_to_duplicates(
    tmp_path: Path,
) -> None:
    """A '(1)'-suffixed incoming file is recognised as a duplicate of an existing
    clean-named file."""
    dest = tmp_path / "dest"
    _touch(dest / "Apple_iPhone" / "IMG_1.jpg")
    incoming = _touch(tmp_path / "source" / "IMG_1 (1).jpg")
    plan = {"Apple_iPhone": [incoming]}

    execute_plan(plan, dest, copy=False, dry_run=False)

    dup_file = dest / "Apple_iPhone" / DUPLICATES_SUBFOLDER / "IMG_1 (1).jpg"
    assert dup_file.exists()


def test_execute_plan_processes_clean_filenames_before_suffixed_variants(
    tmp_path: Path,
) -> None:
    """A clean-named file is always processed before a '(1)'-suffixed sibling,
    regardless of the order the two appear in the plan's file list, so the
    suffixed one is correctly detected as a semantic duplicate of the clean one
    rather than being placed as if it were the original."""
    dest = tmp_path / "dest"
    suffixed = _touch(tmp_path / "source" / "photo (1).jpg", content=b"suffixed")
    clean = _touch(tmp_path / "source" / "photo.jpg", content=b"clean")
    # The suffixed file is listed first in the plan; execute_plan must still
    # process the clean-named file first internally.
    plan = {"Cam": [suffixed, clean]}

    result = execute_plan(plan, dest, copy=False, dry_run=False)

    camera_dir = dest / "Cam"
    assert camera_dir.joinpath("photo.jpg").read_bytes() == b"clean"
    dup_file = camera_dir / DUPLICATES_SUBFOLDER / "photo (1).jpg"
    assert dup_file.read_bytes() == b"suffixed"
    assert result == (2, 0, 1)


def test_execute_plan_duplicate_name_collision_inside_duplicates_gets_unique_path(
    tmp_path: Path,
) -> None:
    """Three same-named incoming files (from different source folders) all land
    safely, the second and third routed to duplicates/ with a numeric suffix to
    avoid overwriting."""
    dest = tmp_path / "dest"
    first = _touch(tmp_path / "src1" / "a.jpg", content=b"first")
    second = _touch(tmp_path / "src2" / "a.jpg", content=b"second")
    third = _touch(tmp_path / "src3" / "a.jpg", content=b"third")
    plan = {"Apple_iPhone": [first, second, third]}

    execute_plan(plan, dest, copy=False, dry_run=False)

    camera_dir = dest / "Apple_iPhone"
    assert camera_dir.joinpath("a.jpg").read_bytes() == b"first"
    dup_dir = camera_dir / DUPLICATES_SUBFOLDER
    dup_names = {p.name: p.read_bytes() for p in dup_dir.iterdir()}
    assert dup_names == {"a.jpg": b"second", "a_1.jpg": b"third"}


def test_execute_plan_idempotent_when_file_already_in_target_folder(
    tmp_path: Path,
) -> None:
    """Re-running the plan on a file that is already inside its target folder is a
    safe no-op."""
    dest = tmp_path / "dest"
    already_placed = _touch(dest / "Apple_iPhone" / "a.jpg", content=b"stays-put")
    plan = {"Apple_iPhone": [already_placed]}

    result = execute_plan(plan, dest, copy=False, dry_run=False)

    assert already_placed.exists()
    assert already_placed.read_bytes() == b"stays-put"
    assert result == (1, 0, 0)


def test_execute_plan_idempotent_dry_run_does_not_rename_extension(
    tmp_path: Path,
) -> None:
    """An already-placed file under --dry-run with --ext-case is not actually
    renamed."""
    dest = tmp_path / "dest"
    already_placed = _touch(dest / "Apple_iPhone" / "a.JPG")
    plan = {"Apple_iPhone": [already_placed]}

    execute_plan(plan, dest, copy=False, dry_run=True, ext_case="lower")

    # Windows exists() checks are case-insensitive, so inspect the raw directory
    # listing to confirm the on-disk name is still uppercase.
    names = [p.name for p in already_placed.parent.iterdir()]
    assert names == ["a.JPG"]


def test_execute_plan_idempotent_live_renames_extension_case_in_place(
    tmp_path: Path,
) -> None:
    """An already-placed file with --ext-case gets its extension case-normalised in
    place."""
    dest = tmp_path / "dest"
    already_placed = _touch(dest / "Apple_iPhone" / "a.JPG")
    plan = {"Apple_iPhone": [already_placed]}

    execute_plan(plan, dest, copy=False, dry_run=False, ext_case="lower")

    # Windows exists() checks are case-insensitive, so inspect the raw directory
    # listing to confirm the extension case was actually normalised on disk.
    names = [p.name for p in (dest / "Apple_iPhone").iterdir()]
    assert names == ["a.jpg"]


def test_execute_plan_idempotent_extcase_rename_failure_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the in-place ext-case rename raises, the file is counted as skipped, not
    ok."""
    dest = tmp_path / "dest"
    already_placed = _touch(dest / "Apple_iPhone" / "a.JPG")
    plan = {"Apple_iPhone": [already_placed]}

    def _raise_rename(self: Path, target: Path) -> Path:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(Path, "rename", _raise_rename)

    result = execute_plan(plan, dest, copy=False, dry_run=False, ext_case="lower")

    assert result == (0, 1, 0)


def test_execute_plan_ext_case_lower_after_move(tmp_path: Path) -> None:
    """--ext-case lower normalises the extension to lowercase after a live move."""
    photo = _touch(tmp_path / "source" / "a.JPG")
    dest = tmp_path / "dest"
    plan = {"Apple_iPhone": [photo]}

    execute_plan(plan, dest, copy=False, dry_run=False, ext_case="lower")

    names = [p.name for p in (dest / "Apple_iPhone").iterdir()]
    assert names == ["a.jpg"]


def test_execute_plan_ext_case_upper_after_copy(tmp_path: Path) -> None:
    """--ext-case upper normalises the extension to uppercase after a live copy."""
    photo = _touch(tmp_path / "source" / "a.jpg")
    dest = tmp_path / "dest"
    plan = {"Apple_iPhone": [photo]}

    execute_plan(plan, dest, copy=True, dry_run=False, ext_case="upper")

    names = [p.name for p in (dest / "Apple_iPhone").iterdir()]
    assert names == ["a.JPG"]


def test_execute_plan_ext_case_samefile_check_raising_oserror_is_swallowed(
    require_case_insensitive_fs: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If Path.samefile() raises OSError during the case-only-rename safety check,
    the file is left under its original name rather than crashing the run. This
    exercises the samefile() branch specifically, which is only reached on a
    case-insensitive filesystem (where the case-only-renamed target path already
    'exists' as the same file); it is skipped on a case-sensitive filesystem."""
    photo = _touch(tmp_path / "source" / "Photo.JPG")
    dest = tmp_path / "dest"
    plan = {"Apple_iPhone": [photo]}

    def _raise_samefile(self: Path, other: Path) -> bool:
        raise OSError("simulated samefile failure")

    monkeypatch.setattr(Path, "samefile", _raise_samefile)

    result = execute_plan(plan, dest, copy=False, dry_run=False, ext_case="lower")

    assert result == (1, 0, 0)
    names = [p.name for p in (dest / "Apple_iPhone").iterdir()]
    assert names == ["Photo.JPG"]  # rename skipped, original case preserved


def _simulate_case_variant_target(
    monkeypatch: pytest.MonkeyPatch, target_name: str, *, same_file: bool
) -> list[tuple[Path, Path]]:
    """Make the case-changed name *target_name* look occupied.

    Path.exists() reports True for that name and Path.samefile() returns
    *same_file*, so the collision logic can be exercised on a case-insensitive
    filesystem that cannot hold both case variants. Returns the list of
    (source, target) pairs passed to Path.rename(), which still renames for real.
    """
    real_exists = Path.exists
    real_rename = Path.rename
    renames: list[tuple[Path, Path]] = []

    def _exists(self: Path, *args: object, **kwargs: object) -> bool:
        return self.name == target_name or real_exists(self, *args, **kwargs)

    def _samefile(self: Path, other: Path) -> bool:
        return same_file

    def _rename(self: Path, target: Path) -> Path:
        renames.append((self, Path(target)))
        return real_rename(self, target)

    monkeypatch.setattr(Path, "exists", _exists)
    monkeypatch.setattr(Path, "samefile", _samefile)
    monkeypatch.setattr(Path, "rename", _rename)
    return renames


def test_execute_plan_in_place_ext_case_collision_keeps_name_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An in-place ext-case rename onto a different file's name is skipped with a
    warning; the original file is kept and nothing is overwritten."""
    dest = tmp_path / "dest"
    placed = _touch(dest / "Apple_iPhone" / "a.JPG", content=b"original")
    renames = _simulate_case_variant_target(monkeypatch, "a.jpg", same_file=False)

    with caplog.at_level(logging.WARNING, logger="organize_media_by_camera"):
        result = execute_plan(
            {"Apple_iPhone": [placed]}, dest, copy=False, dry_run=False, ext_case="lower"
        )

    assert result == (1, 0, 0)
    assert renames == []
    assert [p.name for p in placed.parent.iterdir()] == ["a.JPG"]
    assert placed.read_bytes() == b"original"
    assert "Keeping 'a.JPG'" in caplog.text
    assert "'a.jpg'" in caplog.text


def test_execute_plan_in_place_ext_case_same_file_renames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When the case-changed name resolves to the same file (case-insensitive
    filesystem), the in-place rename proceeds without a warning."""
    dest = tmp_path / "dest"
    placed = _touch(dest / "Apple_iPhone" / "a.JPG", content=b"original")
    renames = _simulate_case_variant_target(monkeypatch, "a.jpg", same_file=True)

    with caplog.at_level(logging.WARNING, logger="organize_media_by_camera"):
        result = execute_plan(
            {"Apple_iPhone": [placed]}, dest, copy=False, dry_run=False, ext_case="lower"
        )

    assert result == (1, 0, 0)
    assert [src.name for src, _ in renames] == ["a.JPG"]
    assert [p.name for p in placed.parent.iterdir()] == ["a.jpg"]
    assert (placed.parent / "a.jpg").read_bytes() == b"original"
    assert "Keeping" not in caplog.text


def test_execute_plan_moved_file_ext_case_collision_keeps_name_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """After a move, an ext-case rename onto a different file's name is skipped
    with a warning; the moved file keeps its original name and content."""
    photo = _touch(tmp_path / "source" / "a.JPG", content=b"incoming")
    dest = tmp_path / "dest"
    renames = _simulate_case_variant_target(monkeypatch, "a.jpg", same_file=False)

    with caplog.at_level(logging.WARNING, logger="organize_media_by_camera"):
        result = execute_plan(
            {"Apple_iPhone": [photo]}, dest, copy=False, dry_run=False, ext_case="lower"
        )

    assert result == (1, 0, 0)
    assert renames == []
    moved = dest / "Apple_iPhone"
    assert [p.name for p in moved.iterdir()] == ["a.JPG"]
    assert (moved / "a.JPG").read_bytes() == b"incoming"
    assert "Keeping 'a.JPG'" in caplog.text
    assert "'a.jpg'" in caplog.text


def test_execute_plan_skips_file_when_action_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If shutil.move/copy2 raises for a file, it is counted as skipped rather than
    crashing the run."""
    photo = _touch(tmp_path / "source" / "a.jpg")
    dest = tmp_path / "dest"
    plan = {"Apple_iPhone": [photo]}

    def _raise_move(*args: object, **kwargs: object) -> None:
        raise OSError("simulated move failure")

    monkeypatch.setattr(om.shutil, "move", _raise_move)

    result = execute_plan(plan, dest, copy=False, dry_run=False)

    assert result == (0, 1, 0)
    assert photo.exists()  # never removed since the move failed


def test_execute_plan_dry_run_mixed_inplace_and_new_files_ok_is_not_doubled(
    tmp_path: Path,
) -> None:
    """A dry-run folder containing one already-placed file and one new file should
    report files_ok == 2 (one per file), not 3."""
    dest = tmp_path / "dest"
    already_placed = _touch(dest / "Apple_iPhone" / "existing.jpg")
    new_file = _touch(tmp_path / "source" / "new.jpg")
    plan = {"Apple_iPhone": [already_placed, new_file]}

    result = execute_plan(plan, dest, copy=False, dry_run=True)

    assert result == (2, 0, 0)


# ============================================================
# _unique_path
# ============================================================


def test_unique_path_returns_input_unchanged_when_free(tmp_path: Path) -> None:
    """A path that does not yet exist is returned unchanged."""
    candidate = tmp_path / "a.jpg"
    assert _unique_path(candidate) == candidate


def test_unique_path_appends_incrementing_counter(tmp_path: Path) -> None:
    """An existing path gets '_1', then '_2', etc. appended until a free name is
    found."""
    _touch(tmp_path / "a.jpg")
    _touch(tmp_path / "a_1.jpg")
    assert _unique_path(tmp_path / "a.jpg") == tmp_path / "a_2.jpg"


# ============================================================
# strip_duplicate_suffix
# ============================================================


def test_strip_duplicate_suffix_renames_when_no_conflict(tmp_path: Path) -> None:
    """A suffixed file is renamed to its clean name when that name is not already
    taken."""
    _touch(tmp_path / "IMG_1 (1).jpg")
    renamed, skipped = strip_duplicate_suffix(tmp_path, dry_run=False)
    assert (renamed, skipped) == (1, 0)
    assert (tmp_path / "IMG_1.jpg").exists()
    assert not (tmp_path / "IMG_1 (1).jpg").exists()


def test_strip_duplicate_suffix_skips_on_conflict(tmp_path: Path) -> None:
    """A suffixed file is left alone when the clean name is already taken."""
    _touch(tmp_path / "photo.jpg")
    _touch(tmp_path / "photo (1).jpg")
    renamed, skipped = strip_duplicate_suffix(tmp_path, dry_run=False)
    assert (renamed, skipped) == (0, 1)
    assert (tmp_path / "photo (1).jpg").exists()


def test_strip_duplicate_suffix_dry_run_does_not_rename(tmp_path: Path) -> None:
    """--dry-run reports what would be renamed without touching the filesystem."""
    _touch(tmp_path / "IMG_1 (1).jpg")
    renamed, skipped = strip_duplicate_suffix(tmp_path, dry_run=True)
    assert (renamed, skipped) == (1, 0)
    assert (tmp_path / "IMG_1 (1).jpg").exists()
    assert not (tmp_path / "IMG_1.jpg").exists()


def test_strip_duplicate_suffix_ignores_files_without_suffix(tmp_path: Path) -> None:
    """Files with no recognised duplicate suffix are left untouched."""
    _touch(tmp_path / "photo.jpg")
    renamed, skipped = strip_duplicate_suffix(tmp_path, dry_run=False)
    assert (renamed, skipped) == (0, 0)


def test_strip_duplicate_suffix_ignores_subdirectories(tmp_path: Path) -> None:
    """A subdirectory whose name happens to look like a duplicate suffix is
    skipped, not renamed."""
    (tmp_path / "IMG_1 (1)").mkdir()
    renamed, skipped = strip_duplicate_suffix(tmp_path, dry_run=False)
    assert (renamed, skipped) == (0, 0)


def test_strip_duplicate_suffix_empty_folder_returns_zero_zero(tmp_path: Path) -> None:
    """An empty folder returns (0, 0) without any filesystem changes."""
    assert strip_duplicate_suffix(tmp_path, dry_run=False) == (0, 0)


# ============================================================
# parse_args
# ============================================================


def test_parse_args_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """With only the required source argument, every flag defaults to off/None."""
    monkeypatch.setattr("sys.argv", ["organize_media_by_camera.py", str(tmp_path)])
    args = om.parse_args()
    assert args.source == tmp_path
    assert args.destination is None
    assert args.dry_run is False
    assert args.copy is False
    assert args.recursive is False
    assert args.verbose is False
    assert args.strip_suffix is False
    assert args.ext_case is None


def test_parse_args_missing_source_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """The positional source argument is required; omitting it exits with code 2."""
    monkeypatch.setattr("sys.argv", ["organize_media_by_camera.py"])
    with pytest.raises(SystemExit) as excinfo:
        om.parse_args()
    assert excinfo.value.code == 2


def test_parse_args_rejects_invalid_ext_case_choice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An --ext-case value outside {lower, upper} exits with code 2."""
    monkeypatch.setattr(
        "sys.argv",
        ["organize_media_by_camera.py", str(tmp_path), "--ext-case", "sideways"],
    )
    with pytest.raises(SystemExit) as excinfo:
        om.parse_args()
    assert excinfo.value.code == 2


def test_parse_args_all_flags_parsed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every flag is parsed to the expected value when explicitly provided."""
    dest = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        [
            "organize_media_by_camera.py",
            str(tmp_path),
            "--destination",
            str(dest),
            "--dry-run",
            "--copy",
            "--recursive",
            "--verbose",
            "--strip-suffix",
            "--ext-case",
            "upper",
        ],
    )
    args = om.parse_args()
    assert args.destination == dest
    assert args.dry_run is True
    assert args.copy is True
    assert args.recursive is True
    assert args.verbose is True
    assert args.strip_suffix is True
    assert args.ext_case == "upper"


# ============================================================
# main
# ============================================================


def test_main_nonexistent_source_returns_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A source path that is not an existing directory returns exit code 1."""
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr("sys.argv", ["organize_media_by_camera.py", str(missing)])
    assert om.main() == 1


def test_main_no_media_files_returns_0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An existing but empty (of supported media) source folder returns exit code
    0."""
    (tmp_path / "notes.txt").write_text("not media")
    monkeypatch.setattr("sys.argv", ["organize_media_by_camera.py", str(tmp_path)])
    assert om.main() == 0


def test_main_dry_run_makes_no_changes_and_returns_0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--dry-run scans and reports but performs no filesystem changes, returning
    exit code 0."""
    photo = _touch(tmp_path / "a.jpg")
    monkeypatch.setattr(
        "sys.argv", ["organize_media_by_camera.py", str(tmp_path), "--dry-run"]
    )
    assert om.main() == 0
    assert photo.exists()  # never moved


def test_main_live_run_organises_files_and_returns_0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A normal live run organises files into subfolders and returns exit code 0."""
    _touch(tmp_path / "a.jpg")
    monkeypatch.setattr("sys.argv", ["organize_media_by_camera.py", str(tmp_path)])
    assert om.main() == 0
    assert (tmp_path / "Unknown_Device" / "a.jpg").exists()


def test_main_live_run_with_skipped_file_returns_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When at least one file fails to move/copy, main() returns exit code 2."""
    _touch(tmp_path / "a.jpg")

    def _raise_move(*args: object, **kwargs: object) -> None:
        raise OSError("simulated failure")

    monkeypatch.setattr(om.shutil, "move", _raise_move)
    monkeypatch.setattr("sys.argv", ["organize_media_by_camera.py", str(tmp_path)])
    assert om.main() == 2


def test_main_verbose_flag_sets_debug_log_level(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--verbose raises the module logger to DEBUG level."""
    monkeypatch.setattr(om.logger, "level", logging.INFO)
    monkeypatch.setattr(
        "sys.argv", ["organize_media_by_camera.py", str(tmp_path), "--verbose"]
    )
    om.main()
    assert om.logger.level == logging.DEBUG


def test_main_strip_suffix_renames_files_after_organising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--strip-suffix removes duplicate-style suffixes from filenames after
    organising."""
    _touch(tmp_path / "IMG_1 (1).jpg")
    monkeypatch.setattr(
        "sys.argv", ["organize_media_by_camera.py", str(tmp_path), "--strip-suffix"]
    )
    assert om.main() == 0
    assert (tmp_path / "Unknown_Device" / "IMG_1.jpg").exists()


def test_main_dry_run_with_strip_suffix_logs_preview_skipped_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """--dry-run combined with --strip-suffix logs that suffix stripping preview is
    skipped (destination folders do not exist yet in dry-run mode)."""
    _touch(tmp_path / "a.jpg")
    monkeypatch.setattr(
        "sys.argv",
        ["organize_media_by_camera.py", str(tmp_path), "--dry-run", "--strip-suffix"],
    )
    with caplog.at_level(logging.INFO, logger="organize_media_by_camera"):
        assert om.main() == 0
    assert any("Suffix stripping preview skipped" in r.message for r in caplog.records)


def test_main_strip_suffix_also_strips_inside_duplicates_subfolder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--strip-suffix also renames suffixed files found inside a camera folder's
    duplicates/ subfolder, not just the top-level camera folder."""
    _touch(tmp_path / "a" / "photo.jpg")
    _touch(tmp_path / "b" / "photo (1).jpg")
    monkeypatch.setattr(
        "sys.argv",
        ["organize_media_by_camera.py", str(tmp_path), "--recursive", "--strip-suffix"],
    )
    assert om.main() == 0
    assert (tmp_path / "Unknown_Device" / "photo.jpg").exists()
    assert (tmp_path / "Unknown_Device" / "duplicates" / "photo.jpg").exists()


def test_main_copy_and_ext_case_flags_both_take_effect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--copy and --ext-case combine correctly through the full CLI: the source
    file is preserved (copy, not moved) and the destination copy's extension case
    is normalised."""
    source = tmp_path / "source"
    dest = tmp_path / "out"
    photo = _touch(source / "a.JPG")
    monkeypatch.setattr(
        "sys.argv",
        [
            "organize_media_by_camera.py",
            str(source),
            "--destination",
            str(dest),
            "--copy",
            "--ext-case",
            "lower",
        ],
    )
    assert om.main() == 0
    assert photo.exists()
    names = [p.name for p in (dest / "Unknown_Device").iterdir()]
    assert names == ["a.jpg"]


def test_main_custom_destination_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--destination places organised subfolders in a separate output folder."""
    source = tmp_path / "source"
    dest = tmp_path / "out"
    _touch(source / "a.jpg")
    monkeypatch.setattr(
        "sys.argv",
        ["organize_media_by_camera.py", str(source), "--destination", str(dest)],
    )
    assert om.main() == 0
    assert (dest / "Unknown_Device" / "a.jpg").exists()
    assert not (source / "a.jpg").exists()
