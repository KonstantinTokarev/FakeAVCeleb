"""
SSRF-safe URL validation. Rejects private/local/internal IPs and invalid schemes.
"""
from urllib.parse import urlparse
import ipaddress
import socket


class ValidationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),      # private
    ipaddress.ip_network("172.16.0.0/12"),  # private
    ipaddress.ip_network("192.168.0.0/16"), # private
    ipaddress.ip_network("127.0.0.0/8"),    # loopback
    ipaddress.ip_network("169.254.0.0/16"), # link-local
    ipaddress.ip_network("::1/128"),        # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),       # IPv6 private
    ipaddress.ip_network("fe80::/10"),      # IPv6 link-local
]


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
        raise ValidationError("URL_INVALID", "Only http and https URLs are allowed")
    host = (parsed.netloc or "").split(":")[0]
    if not host:
        raise ValidationError("URL_INVALID", "Invalid host")

    # Resolve host to IP and check against blocked ranges (DNS rebinding mitigation)
    try:
        for info in socket.getaddrinfo(host, None):
            addr = info[4][0]
            if _is_blocked_ip(addr):
                raise ValidationError("URL_BLOCKED_SSRF", "Host resolves to a disallowed address")
    except socket.gaierror:
        pass  # allow if we can't resolve (e.g. dev)
    except ValidationError:
        raise

    # Also block if host is already an IP in blocked range
    if _is_blocked_ip(host):
        raise ValidationError("URL_BLOCKED_SSRF", "Host is a disallowed address")
