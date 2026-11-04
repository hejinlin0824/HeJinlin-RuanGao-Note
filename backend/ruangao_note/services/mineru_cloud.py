"""MinerU v4 cloud batch parser with phase-aware network diagnostics."""

from __future__ import annotations

import io
import json
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True)
class MinerUSettings:
    token: str
    api_base_url: str = "https://mineru.net"
    model_version: str = "vlm"
    language: str = "ch"
    poll_interval_seconds: float = 5.0
    max_wait_seconds: int = 1500


class MinerUError(RuntimeError):
    """Raised when MinerU rejects, fails, or times out a parsing task."""


class MinerUCloudParser:
    """Submit one PDF through MinerU v4 and return its extracted artifacts."""

    def __init__(
        self,
        settings: MinerUSettings,
        *,
        client_factory: type[httpx.Client] = httpx.Client,
        sleep=time.sleep,
    ) -> None:
        if not settings.token.strip():
            raise ValueError("MinerU API token is not configured.")
        self.settings = settings
        self.client_factory = client_factory
        self.sleep = sleep

    def parse_pdf(
        self,
        pdf_bytes: bytes,
        filename: str,
        *,
        on_batch_created: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if not pdf_bytes:
            raise ValueError("PDF payload is empty.")
        base = self.settings.api_base_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.settings.token}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(60.0, connect=20.0)
        with self.client_factory(timeout=timeout, follow_redirects=True) as client:
            try:
                response = client.post(
                    f"{base}/api/v4/file-urls/batch",
                    headers=headers,
                    json={
                        "enable_formula": True,
                        "enable_table": True,
                        "language": self.settings.language,
                        "model_version": self.settings.model_version,
                        "files": [{"name": filename}],
                    },
                )
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPError as exc:
                raise self._network_error("requesting a batch upload URL", exc) from exc
            self._ensure_success(payload, "request upload URL")
            data = payload.get("data") or {}
            batch_id = data.get("batch_id")
            urls = data.get("file_urls") or []
            if not batch_id or not urls or not urls[0]:
                raise MinerUError("MinerU response omitted batch_id or upload URL.")

            # Persist the provider task ID before any subsequent network operation.
            if on_batch_created is not None:
                on_batch_created(str(batch_id))

            # This is a pre-signed object-storage URL. Do not send MinerU auth.
            try:
                upload = client.put(urls[0], content=pdf_bytes)
                upload.raise_for_status()
            except httpx.HTTPError as exc:
                raise self._network_error(
                    f"uploading the PDF for MinerU batch {batch_id}", exc
                ) from exc

            result_item = self._poll_result(client, base, headers, str(batch_id))
            zip_url = result_item.get("full_zip_url")
            if not zip_url:
                raise MinerUError(
                    f"MinerU batch {batch_id} completed without a result ZIP URL."
                )

            artifacts = self._download_result_zip(str(zip_url), str(batch_id))

        return {
            "batch_id": str(batch_id),
            "state": "done",
            "model_version": self.settings.model_version,
            "language": self.settings.language,
            "artifacts": artifacts,
        }

    def resume_batch(self, batch_id: str) -> dict[str, Any]:
        """Fetch an existing batch's latest result without uploading or resubmitting."""
        if not batch_id.strip():
            raise ValueError("MinerU batch_id is required.")
        base = self.settings.api_base_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.settings.token}",
            "Content-Type": "application/json",
        }
        with self.client_factory(
            timeout=httpx.Timeout(60.0, connect=20.0),
            follow_redirects=True,
        ) as client:
            result_item = self._poll_result(client, base, headers, batch_id)
        zip_url = result_item.get("full_zip_url")
        if not zip_url:
            raise MinerUError(
                f"MinerU batch {batch_id} completed without a result ZIP URL. "
                "The provider may have expired the result."
            )
        return {
            "batch_id": batch_id,
            "state": "done",
            "model_version": self.settings.model_version,
            "language": self.settings.language,
            "artifacts": self._download_result_zip(str(zip_url), batch_id),
        }

    def _download_result_zip(self, zip_url: str, batch_id: str) -> dict[str, Any]:
        """Download a pre-signed result URL with fresh unauthenticated connections."""
        archive_response = None
        last_error: httpx.HTTPError | None = None
        download_host = urlsplit(zip_url).hostname or "unknown host"
        for attempt in range(1, 4):
            try:
                with self.client_factory(
                    timeout=httpx.Timeout(300.0, connect=30.0),
                    follow_redirects=True,
                ) as download_client:
                    archive_response = download_client.get(zip_url)
                    archive_response.raise_for_status()
                last_error = None
                break
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < 3:
                    self.sleep(float(attempt * 3))
        if last_error is not None:
            raise self._network_error(
                f"downloading the result ZIP for MinerU batch {batch_id} "
                f"from storage host {download_host} after 3 attempts",
                last_error,
            ) from last_error
        assert archive_response is not None
        return self._read_result_zip(archive_response.content)

    def _poll_result(
        self,
        client: httpx.Client,
        base: str,
        headers: dict[str, str],
        batch_id: str,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.settings.max_wait_seconds
        consecutive_errors = 0
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            self.sleep(self.settings.poll_interval_seconds)
            try:
                response = client.get(
                    f"{base}/api/v4/extract-results/batch/{batch_id}",
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
                self._ensure_success(payload, "poll batch result")
                data = payload.get("data") or {}
                items = data.get("extract_result") or []
                item = next(
                    (entry for entry in items if entry.get("state") in {"done", "failed"}),
                    items[0] if items else {},
                )
                state = item.get("state")
                if state == "done":
                    return item
                if state == "failed":
                    reason = item.get("err_msg") or item.get("error") or "unknown error"
                    raise MinerUError(f"MinerU parsing failed: {reason}")
                consecutive_errors = 0
                last_error = None
            except MinerUError:
                raise
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                consecutive_errors += 1
                last_error = exc
                if consecutive_errors > 20:
                    raise MinerUError(
                        f"Polling MinerU batch {batch_id} failed 21 consecutive times; "
                        f"last error: {type(exc).__name__}: {exc}"
                    ) from exc
        if last_error is not None:
            raise MinerUError(
                f"Polling MinerU batch {batch_id} timed out after "
                f"{self.settings.max_wait_seconds} seconds; last network/data error: "
                f"{type(last_error).__name__}: {last_error}"
            ) from last_error
        raise TimeoutError(
            f"MinerU batch {batch_id} did not finish within "
            f"{self.settings.max_wait_seconds} seconds."
        )

    @staticmethod
    def _network_error(operation: str, exc: httpx.HTTPError) -> MinerUError:
        # Include the transport exception but never print auth headers or signed URLs.
        return MinerUError(
            f"Network error while {operation}: {type(exc).__name__}: {exc}"
        )

    @staticmethod
    def _ensure_success(payload: dict[str, Any], operation: str) -> None:
        code = payload.get("code")
        if code not in (0, "0", None):
            message = payload.get("msg") or payload.get("message") or "unknown error"
            raise MinerUError(f"MinerU failed to {operation}: {message}")

    @staticmethod
    def _read_result_zip(content: bytes) -> dict[str, Any]:
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise MinerUError("MinerU returned an invalid ZIP archive.") from exc

        artifacts: dict[str, Any] = {"markdown": {}, "json": {}, "files": []}
        with archive:
            total_uncompressed = sum(info.file_size for info in archive.infolist())
            if total_uncompressed > 1024 * 1024 * 1024:
                raise MinerUError("MinerU ZIP exceeds the 1 GiB extraction limit.")
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                path = PurePosixPath(name)
                is_symlink = ((info.external_attr >> 16) & 0o170000) == 0o120000
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in name
                    or (path.parts and ":" in path.parts[0])
                    or is_symlink
                ):
                    raise MinerUError("MinerU ZIP contains an unsafe file path.")
                raw = archive.read(info)
                artifacts["files"].append(name)
                suffix = path.suffix.lower()
                if suffix == ".md":
                    artifacts["markdown"][name] = raw.decode("utf-8-sig", errors="replace")
                elif suffix == ".json":
                    try:
                        artifacts["json"][name] = json.loads(raw.decode("utf-8-sig"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        artifacts["json"][name] = {
                            "decode_error": True,
                            "text": raw.decode("utf-8", errors="replace"),
                        }
        if not artifacts["markdown"] and not artifacts["json"]:
            raise MinerUError("MinerU ZIP contains neither Markdown nor JSON results.")
        return artifacts
