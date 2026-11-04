import json
import pytest
from app.storage import LocalObjectStore, ProjectRepository, StorageError

def test_local_store_round_trip_and_path_safety(tmp_path):
    store = LocalObjectStore(tmp_path)
    key = "owners/owner/media/source.bin"
    store.put(key, b"media")
    assert store.get(key) == b"media"
    assert store.exists(key)
    with pytest.raises(ValueError):
        store.put("../escape", b"x")
    with pytest.raises(StorageError):
        store.get("owners/owner/missing")

def test_project_create_and_reload(tmp_path):
    repo = ProjectRepository(LocalObjectStore(tmp_path))
    project = repo.create("Science short", "mind-of-ak", {"aspect_ratio": "9:16"})
    loaded = repo.get(project["id"])
    assert loaded["title"] == "Science short"
    assert loaded["channel"] == "mind-of-ak"
    assert loaded["timeline"] == {"tracks": []}
    manifest = tmp_path / "owners/owner/projects" / project["id"] / "manifest.json"
    assert json.loads(manifest.read_text())["id"] == project["id"]

def test_owner_namespace_and_channel_validation(tmp_path):
    repo = ProjectRepository(LocalObjectStore(tmp_path), owner_id="primary-owner")
    with pytest.raises(ValueError):
        repo.create("Unknown", "other")
    project = repo.create("Kids episode", "kids-stories")
    project["owner_id"] = "someone-else"
    with pytest.raises(ValueError):
        repo.save(project)
    with pytest.raises(ValueError):
        repo.get("../not-a-project")

def test_project_manifest_rejects_invalid_shapes(tmp_path):
    repo = ProjectRepository(LocalObjectStore(tmp_path))
    project = repo.create("Relax", "mind-relax-bgm")
    project["timeline"] = []
    with pytest.raises(ValueError):
        repo.save(project)
