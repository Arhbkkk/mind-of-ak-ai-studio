import pytest

from app.storage import LocalObjectStore, ProjectRepository, StorageError


def test_local_store_round_trip_and_path_safety(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put("owners/owner/media/source.bin", b"media")
    assert store.get("owners/owner/media/source.bin") == b"media"
    assert store.exists("owners/owner/media/source.bin")
    assert store.list("owners/owner/media") == ["owners/owner/media/source.bin"]
    with pytest.raises(ValueError):
        store.put("../escape", b"x")
    with pytest.raises(StorageError):
        store.get("owners/owner/missing")


def test_project_create_update_list_and_delete(tmp_path):
    repo = ProjectRepository(LocalObjectStore(tmp_path))
    project = repo.create("Science short", "mind-of-ak", {"aspect_ratio": "9:16"})
    loaded = repo.get(project["id"])
    assert loaded["title"] == "Science short"
    assert loaded["channel"] == "mind-of-ak"
    assert loaded["timeline"] == {"tracks": []}
    assert loaded["source_media"] == []
    loaded["script"] = "A sample script"
    repo.save(loaded)
    assert repo.list()[0]["script"] == "A sample script"
    repo.delete(project["id"])
    assert repo.list() == []


def test_project_rejects_unknown_channel_and_wrong_owner(tmp_path):
    repo = ProjectRepository(LocalObjectStore(tmp_path))
    with pytest.raises(ValueError):
        repo.create("Bad channel", "unknown")
    project = repo.create("Valid", "kids-stories")
    project["owner_id"] = "another-owner"
    with pytest.raises(ValueError):
        repo.save(project)
