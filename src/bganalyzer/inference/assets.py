"""Bounded, checksum-verified model downloads. No patient data leaves the machine."""

import hashlib
import shutil
import httpx
from bganalyzer.inference import catalog


class LocalAIError(Exception):
    pass


def check_cancel(cancelled):
    if cancelled():
        raise LocalAIError("Local AI operation cancelled.")


def verify(path, size, digest, cancelled=lambda: False):
    if not path.is_file() or path.stat().st_size != size:
        return False
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            check_cancel(cancelled)
            h.update(block)
    return h.hexdigest() == digest


def download(url, path, size, digest, progress, cancelled):
    if verify(path, size, digest, cancelled):
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if shutil.disk_usage(path.parent).free < size + 512 * 1024 * 1024:
        raise LocalAIError("Not enough free space for the verified local model.")
    partial = path.with_suffix(path.suffix + ".partial")
    count = 0
    try:
        with httpx.Client(follow_redirects=True, trust_env=False, timeout=30) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with partial.open("wb") as stream:
                    partial.chmod(0o600)
                    for block in response.iter_bytes(1024 * 1024):
                        check_cancel(cancelled)
                        count += len(block)
                        if count > size:
                            raise LocalAIError("Download exceeds the catalog size.")
                        stream.write(block)
                        progress(f"Downloading {path.name}: {100*count/size:.1f}%")
        progress(f"Verifying {path.name}…")
        if not verify(partial, size, digest, cancelled):
            raise LocalAIError("Downloaded file failed integrity verification.")
        partial.replace(path)
    except httpx.HTTPError:
        raise LocalAIError(
            "Download failed. Check your connection and retry installation."
        ) from None
    finally:
        partial.unlink(missing_ok=True)


def paths(config):
    root = config.cache_dir / "local-ai"
    return root / "runtime-b10900.tar.gz", root / catalog.MODEL_FILE


def install(config, progress, cancelled):
    runtime, model = paths(config)
    download(
        catalog.RUNTIME_URL,
        runtime,
        catalog.RUNTIME_SIZE,
        catalog.RUNTIME_SHA256,
        progress,
        cancelled,
    )
    download(
        catalog.MODEL_URL, model, catalog.MODEL_SIZE, catalog.MODEL_SHA256, progress, cancelled
    )
    progress("Local AI installed and verified.")
