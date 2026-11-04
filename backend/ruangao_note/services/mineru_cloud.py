"""MinerU v4 cloud batch parser.

The implementation intentionally submits one multi-page PDF per chapter,
rather than one request per uploaded page. The pre-signed upload URL must not
receive the Bearer token or any other authorization header.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

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

    def parse_pdf(self, pdf_bytes: bytes, filename: str) -> dict[str, Any]:
        if not pdf_bytes:
            raise ValueError("PDF payload is empty.")
        base = self.settings.api_base_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.settings.token}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(60.0, connect=15.0)
        with self.client_factory(timeout=timeout, follow_redirects=True) as client:
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
            self._ensure_success(payload, "request upload URL")
            data = payload.get("data") or {}
            batch_id = data.get("batch_id")
            urls = data.get("file_urls") or []
            if not batch_id or not urls or not urls[0]:
                raise MinerUError("MinerU response omitted batch_id or upload URL.")

            # This is a pre-signed object-storage URL. Do not send MinerU auth.
            upload = client.put(urls[0], content=pdf_bytes)
            if upload.status_code not in (200, 201):
                raise MinerUError(f"MinerU file upload failed: HTTP {upload.status_code}.")

            result_item = self._poll_result(client, base, headers, str(batch_id))
            zip_url = result_item.get("full_zip_url")
            if not zip_url:
                raise MinerUError("MinerU completed without a result ZIP URL.")

            # The ZIP URL is pre-signed too; no Bearer token is forwarded.
            archive_response = client.get(str(zip_url), timeout=300.0)
            archive_response.raise_for_status()
            artifacts = self._read_result_zip(archive_response.content)

        return {
            "batch_id": str(batch_id),
            "state": "done",
            "model_version": self.settings.model_version,
            "language": self.settings.language,
            "artifacts": artifacts,
        }

    def _poll_result(
        self,
        client: httpx.Client,
        base: str,
        headers: dict[str, str],
        batch_id: str,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.settings.max_wait_seconds
        consecutive_errors = 0
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
            except MinerUError:
                raise
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                consecutive_errors += 1
                if consecutive_errors > 20:
                    raise MinerUError(
                        "MinerU polling repeatedly failed due to network errors."
                    ) from exc
        raise TimeoutError(
            f"MinerU parsing timed out after {self.settings.max_wait_seconds} seconds."
        )

    @staticmethod
    def _ensure_success(payload: dict[str, Any], operation: str) -> None:
        code = payload.get("code")
        if code not in (0, "0", None):
            # Never include request headers or token-bearing data in exceptions.
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
