import hashlib
import json
import threading
import zipfile

import pytest

from document_transcriber import models
from document_transcriber.documents import Cancelled


@pytest.fixture
def small_model(tmp_path, monkeypatch):
    # Small real files exercise the pack integrity/installation protocol without
    # making every test run compress hundreds of megabytes of model weights.
    directory = tmp_path / "original"
    directory.mkdir()
    data = b'{"test": "a verified model file"}'
    (directory / "config.json").write_bytes(data)
    monkeypatch.setattr(models, "EXPECTED_FILES", {"config.json": hashlib.sha256(data).hexdigest()})
    return directory


def test_model_pack_roundtrip_and_modified_payload_preserve_existing_install(tmp_path, small_model):
    pack = tmp_path / "models.zip"
    models.export_pack(small_model, pack, threading.Event())
    installed = tmp_path / "installed"
    models.install_pack(pack, installed, threading.Event())
    models.verify_model(installed)
    assert (installed / "config.json").read_bytes() == (small_model / "config.json").read_bytes()
    assert (installed / "MODEL-MANIFEST.json").is_file()
    damaged = tmp_path / "damaged.zip"
    with zipfile.ZipFile(pack) as source, zipfile.ZipFile(damaged, "w") as target:
        for item in source.infolist():
            data = (
                b"tampered"
                if item.filename.endswith("/config.json")
                else source.read(item.filename)
            )
            target.writestr(item.filename, data)
    before = (installed / "config.json").read_bytes()
    with pytest.raises(ValueError, match="verification failed"):
        models.install_pack(damaged, installed, threading.Event())
    assert (installed / "config.json").read_bytes() == before
    assert not list(tmp_path.glob("model-import-*"))


def test_model_pack_rejects_escaping_paths_and_untrusted_manifest(tmp_path, small_model):
    pack = tmp_path / "bad.zip"
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr("../escape", "bad")
    with pytest.raises(ValueError, match="unexpected paths"):
        models.install_pack(pack, tmp_path / "installed", threading.Event())
    assert not (tmp_path / "escape").exists()
    pack = tmp_path / "good.zip"
    models.export_pack(small_model, pack, threading.Event())
    wrong = tmp_path / "wrong-manifest.zip"
    with zipfile.ZipFile(pack) as source, zipfile.ZipFile(wrong, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "manifest.json":
                manifest = json.loads(data)
                manifest["revision"] = "untrusted"
                data = json.dumps(manifest).encode()
            target.writestr(item.filename, data)
    with pytest.raises(ValueError, match="supported, pinned"):
        models.install_pack(wrong, tmp_path / "installed", threading.Event())


def test_cancellation_does_not_replace_existing_pack_or_model(tmp_path, small_model):
    pack = tmp_path / "models.zip"
    pack.write_bytes(b"keep this existing file")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        models.export_pack(small_model, pack, cancel)
    assert pack.read_bytes() == b"keep this existing file"
