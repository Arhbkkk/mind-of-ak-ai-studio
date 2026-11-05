import pytest

from app import r2_storage


def test_r2_rejects_invalid_object_keys():
    for key in ("saved/video.mp4", "../temporary/a.mp4", "temporary/not-a-uuid.mp4", "temporary/" + "a" * 32 + ".exe"):
        with pytest.raises(ValueError):
            r2_storage._validate_key(key)


def test_r2_upload_rejects_invalid_size_before_network(monkeypatch):
    def no_network():
        raise AssertionError("R2 client must not be created for invalid upload metadata.")
    monkeypatch.setattr(r2_storage, "client", no_network)
    with pytest.raises(ValueError):
        r2_storage.begin_upload("clip.mp4", "video/mp4", 0)
    with pytest.raises(ValueError):
        r2_storage.begin_upload("clip.mp4", "video/mp4", r2_storage.MAX_DIRECT_UPLOAD_BYTES + 1)


def test_r2_upload_rejects_unsupported_file_type_before_network(monkeypatch):
    def no_network():
        raise AssertionError("R2 client must not be created for unsupported file types.")
    monkeypatch.setattr(r2_storage, "client", no_network)
    with pytest.raises(ValueError):
        r2_storage.begin_upload("archive.zip", "application/zip", 1024)
