"""Subtitle Nexus API client.

All endpoints are authenticated with an X-API-Key header unless noted otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

APPLICATION_TYPE = "kodi"
PIPELINE_VERSION = 2
DEFAULT_TIMEOUT = 30


class NexusError(Exception):
    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class NexusClient:
    api_key: str
    domain: str = "api.subtitlenexus.com"
    timeout: int = DEFAULT_TIMEOUT

    def _url(self, path: str) -> str:
        return f"https://{self.domain}{path}"

    def _headers(self, skip_auth: bool = False) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if not skip_auth:
            h["X-API-Key"] = self.api_key
        return h

    def _request(self, method: str, path: str, *, json_body: Any = None,
                 skip_auth: bool = False) -> Any:
        resp = requests.request(
            method, self._url(path),
            headers=self._headers(skip_auth),
            json=json_body,
            timeout=self.timeout,
        )
        if not resp.ok:
            code = f"http_{resp.status_code}"
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text
            raise NexusError(f"{method} {path} -> {resp.status_code}: {detail}",
                             status=resp.status_code, code=code)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def health(self) -> dict:
        return self._request("GET", "/v1/health/", skip_auth=True)

    def validate_key(self) -> dict:
        return self._request("GET", "/v1/user/validate/")

    def user_info(self) -> dict:
        return self._request("GET", "/v1/user/info/")

    def versions(self) -> list[dict]:
        return self._request("GET", "/v1/ai/versions/") or []

    def cost(self, version: str, subtitle_language: str,
             duration_seconds: int | None = None) -> dict:
        params = f"?version={version}&subtitle_language={subtitle_language}"
        if duration_seconds is not None:
            params += f"&duration_seconds={int(duration_seconds)}"
        return self._request("GET", "/v1/ai/subtitle-request/cost/" + params)

    def search(self, file_hash: str, version: str, language: str,
               scope: str = "all") -> dict:
        path = (
            f"/v1/subtitle/search/?file_hash={file_hash}"
            f"&version={version}&language={language}&scope={scope}"
        )
        return self._request("GET", path)

    def upload_start(self, file_name: str, content_type: str, file_size: int,
                     duration_seconds: int, audio_language: str) -> dict:
        return self._request("POST", "/v1/async-upload/av/start/", json_body={
            "file_name": file_name,
            "content_type": content_type,
            "file_size": file_size,
            "duration_seconds": int(duration_seconds),
            "upload_type": "simple",
            "audio_language": audio_language,
            "application_type": APPLICATION_TYPE,
        })

    def upload_to_s3(self, presigned_url: str, file_path: str,
                     content_type: str) -> None:
        with open(file_path, "rb") as f:
            resp = requests.put(presigned_url, data=f,
                                headers={"Content-Type": content_type},
                                timeout=self.timeout * 20)
        if not resp.ok:
            raise NexusError(f"S3 PUT failed: {resp.status_code} {resp.text[:200]}",
                             status=resp.status_code, code=f"s3_{resp.status_code}")

    def upload_finish(self, upload_id: str) -> dict:
        return self._request("POST", "/v1/async-upload/av/finish/", json_body={
            "upload_id": upload_id,
            "upload_type": "simple",
        })

    def submit_subtitle_request(self, *, upload_id: str, file_hash: str,
                                file_hash_sha256: str, audio_language: str,
                                subtitle_language: str, version: str,
                                visibility: str = "PUBLIC") -> dict:
        return self._request("POST", "/v1/ai/subtitle-request/", json_body={
            "upload_id": upload_id,
            "file_hash": file_hash,
            "file_hash_sha256": file_hash_sha256,
            "audio_language": audio_language,
            "subtitle_language": subtitle_language,
            "version": version,
            "pipeline_version": PIPELINE_VERSION,
            "application_type": APPLICATION_TYPE,
            "visibility": visibility,
            "auto_route": True,
        })

    def poll_status(self, subtitle_id: str) -> dict:
        return self._request("GET",
                             f"/v1/ai/subtitle-request/?subtitle_id={subtitle_id}")

    def download_link(self, subtitle_id: str, expiration_s: int = 3600) -> dict:
        return self._request("GET",
            f"/v1/subtitle/download/?subtitle_id={subtitle_id}"
            f"&expiration_s={expiration_s}")

    def purchase(self, subtitle_id: str) -> dict:
        return self._request("POST", "/v1/subtitle/purchase/",
                             json_body={"subtitle_id": subtitle_id})


def download_file(url: str, dest_path: str, timeout: int = 300) -> None:
    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
