"""
SSRF-safe URL validation and safe download with size and redirect limits.
"""
from urllib.parse import urlparse
import ipaddress
import socket
import httpx

BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class DownloadError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _is_blocked_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        for net in BLOCKED_NETWORKS:
            if ip in net:
                return True
        return False
    except ValueError:
        return False


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise DownloadError("URL_INVALID", "Only http and https URLs are allowed")
    host = (parsed.netloc or "").split(":")[0]
    if not host:
        raise DownloadError("URL_INVALID", "Invalid host")
    try:
        for info in socket.getaddrinfo(host, None):
            addr = info[4][0]
            if _is_blocked_ip(addr):
                raise DownloadError("URL_BLOCKED_SSRF", "Host resolves to a disallowed address")
    except socket.gaierror:
        pass
    except DownloadError:
        raise
    if _is_blocked_ip(host):
        raise DownloadError("URL_BLOCKED_SSRF", "Host is a disallowed address")


async def download_video(url: str, dest_path: str, max_bytes: int, timeout: float = 60.0) -> None:
    validate_url(url)
    async with httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=5,
        timeout=timeout,
    ) as client:
        total = 0
        with open(dest_path, "wb") as f:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise DownloadError("DOWNLOAD_FAILED", f"HTTP {resp.status_code}")
                ct = (resp.headers.get("content-type") or "").lower()
                if "video" not in ct and "octet-stream" not in ct:
                    raise DownloadError("FORMAT_UNSUPPORTED", f"Unexpected content-type: {ct}")
                async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        f.close()
                        import os
                        os.remove(dest_path)
                        raise DownloadError("TOO_LARGE", "File exceeds max size")
                    f.write(chunk)
