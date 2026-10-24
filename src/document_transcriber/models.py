"""Pinned, checksummed handwriting models and portable, verified model packs."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from .documents import check_cancel

MODEL_ID = "microsoft/trocr-small-handwritten"
MODEL_NAME = "trocr-small-handwritten"
MODEL_REVISION = "b4648cfa171985a6745f37ddd637e98c0da958ac"
# Pinned upstream files. LFS SHA256s were checked against Hugging Face metadata;
# small files were retrieved at the same immutable revision over verified HTTPS.
EXPECTED_FILES = {
    "README.md": "7e0f183a2697956065aea4e3ec9ca718967be1b7afe446cff4dcdbc8a64fa52b",
    "config.json": "2b6e06edec319984eca99c932d940bfa1f308db3f74d6279440b906c373bf727",
    "generation_config.json": "41149cdcffec4d657f32dfcddd9b208037f01286c9e07945c724908c58ed0193",
    "preprocessor_config.json": "eec0c686d2e2ea6d5887f87e1c6a34ef5bf1ba5b2ac98b8675e131da646fa1d2",
    "pytorch_model.bin": "1b83102cbc1520dee1c3937ac334da83da18cf4683d46ebd1bd4e93ebe584dd7",
    "sentencepiece.bpe.model": "6f5e2fefcf793761a76a6bfb8ad35489f9c203b25557673284b6d032f41043f4",
    "special_tokens_map.json": "58dc0a3d15e3bad4861bcf2dee770ea327344d185182d4c5d2bf253285e53a83",
    "tokenizer_config.json": "e098c98c6834fbcd3f3e75215e3e8b8868f0fe5bf07aef93d28e4f7196db293c",
}


def sha256(path, cancel=None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if cancel is not None:
                check_cancel(cancel)
            digest.update(chunk)
    return digest.hexdigest()


def manifest():
    return {
        "format": "document-transcriber-model-pack/1",
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "files": EXPECTED_FILES,
        "source": f"https://huggingface.co/{MODEL_ID}/tree/{MODEL_REVISION}",
        "notice": "Microsoft TrOCR, trained on IAM. Upstream model card and MIT "
        "repository license are included. The model card declares no separate weight license.",
    }


def available(directory):
    directory = Path(directory)
    return all((directory / name).is_file() for name in EXPECTED_FILES)


def verify_model(directory, cancel=None, progress=lambda message: None):
    directory = Path(directory)
    for name, expected in EXPECTED_FILES.items():
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(
                f"Handwriting model is incomplete: missing {name}. Open Models to install a pack or download it."
            )
        progress(f"Verifying {name}…")
        if sha256(path, cancel) != expected:
            raise ValueError(
                f"Model verification failed for {name}. Reinstall the official model; this file will not be loaded."
            )
    return directory


def write_manifest(directory):
    Path(directory, "MODEL-MANIFEST.json").write_text(
        json.dumps(manifest(), indent=2) + "\n", encoding="utf-8"
    )


def download_model(directory, cancel, progress=lambda message: None):
    directory = Path(directory)
    if available(directory):
        try:
            verify_model(directory, cancel, progress)
            write_manifest(directory)
            return directory
        except ValueError:
            progress("Existing model failed verification. Downloading a clean replacement…")
    from huggingface_hub import snapshot_download

    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="model-download-", dir=directory.parent) as temporary:
        stage = Path(temporary) / MODEL_NAME
        progress("Downloading pinned TrOCR small (~247 MB). Your documents are not uploaded.")
        snapshot_download(
            MODEL_ID,
            revision=MODEL_REVISION,
            local_dir=str(stage),
            allow_patterns=list(EXPECTED_FILES),
            max_workers=2,
        )
        check_cancel(cancel)
        verify_model(stage, cancel, progress)
        shutil.rmtree(stage / ".cache", ignore_errors=True)
        write_manifest(stage)
        check_cancel(cancel)
        _replace_directory(stage, directory)
    return directory


def _replace_directory(stage, directory):
    # Preserve an existing install until the replacement has passed verification.
    backup = directory.with_name(directory.name + ".previous")
    if backup.exists():
        raise ValueError(
            f"A previous model recovery directory exists at {backup}; preserve or move it before reinstalling."
        )
    had_previous = directory.exists()
    if had_previous:
        directory.rename(backup)
    try:
        stage.rename(directory)
    except Exception:
        if had_previous:
            backup.rename(directory)
        raise
    if had_previous:
        shutil.rmtree(backup)


def export_pack(directory, destination, cancel, progress=lambda message: None):
    directory, destination = Path(directory), Path(destination)
    verify_model(directory, cancel, progress)
    with tempfile.NamedTemporaryFile(
        prefix=".model-pack-", suffix=".zip", dir=destination.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            archive.writestr("manifest.json", json.dumps(manifest(), indent=2))
            license_path = Path(__file__).with_name("data") / "MICROSOFT-UNILM-LICENSE.txt"
            archive.write(license_path, "MICROSOFT-UNILM-LICENSE.txt")
            for name in EXPECTED_FILES:
                check_cancel(cancel)
                progress(f"Packing {name}…")
                with (
                    (directory / name).open("rb") as source,
                    archive.open(f"{MODEL_NAME}/{name}", "w", force_zip64=True) as target,
                ):
                    while chunk := source.read(1024 * 1024):
                        check_cancel(cancel)
                        target.write(chunk)
        check_cancel(cancel)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def install_pack(pack, directory, cancel, progress=lambda message: None):
    directory = Path(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(pack) as archive:
        entries = archive.infolist()
        allowed = {f"{MODEL_NAME}/{name}" for name in EXPECTED_FILES} | {
            "manifest.json",
            "MICROSOFT-UNILM-LICENSE.txt",
        }
        if (
            len(entries) != len({item.filename for item in entries})
            or any(
                item.filename not in allowed or stat.S_ISLNK(item.external_attr >> 16)
                for item in entries
            )
            or sum(item.file_size for item in entries) > 512 * 1024**2
        ):
            raise ValueError(
                "Invalid model pack: unexpected paths, duplicate entries, links, or excessive size."
            )
        if not allowed.issubset({item.filename for item in entries}):
            raise ValueError("This model pack is incomplete.")
        if archive.getinfo("manifest.json").file_size > 100_000:
            raise ValueError("Invalid model manifest size.")
        info = json.loads(archive.read("manifest.json"))
        if (
            not isinstance(info, dict)
            or info.get("format") != manifest()["format"]
            or info.get("model_id") != MODEL_ID
            or info.get("revision") != MODEL_REVISION
            or info.get("files") != EXPECTED_FILES
        ):
            raise ValueError("This pack is not the supported, pinned TrOCR small model.")
        with tempfile.TemporaryDirectory(prefix="model-import-", dir=directory.parent) as temporary:
            stage = Path(temporary) / MODEL_NAME
            stage.mkdir()
            for name in EXPECTED_FILES:
                progress(f"Installing {name}…")
                with (
                    archive.open(f"{MODEL_NAME}/{name}") as source,
                    (stage / name).open("wb") as target,
                ):
                    while chunk := source.read(1024 * 1024):
                        check_cancel(cancel)
                        target.write(chunk)
            verify_model(stage, cancel, progress)
            write_manifest(stage)
            check_cancel(cancel)
            _replace_directory(stage, directory)
    return directory
