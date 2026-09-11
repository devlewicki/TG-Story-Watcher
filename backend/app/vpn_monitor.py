"""VPN IP change monitor.

Periodically checks the external IP address through the SOCKS5 proxy.  When the
IP changes (e.g. VPN reconnected to a different country), proactively
disconnects all Telegram clients *before* they hit ``AuthKeyDuplicatedError``.

The monitor runs as an async coroutine inside the combined worker process.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("storywatcher.vpn_monitor")

# Plain-HTTP service that returns the caller's public IP as JSON.
_IP_CHECK_HOST = "httpbin.org"
_IP_CHECK_PORT = 80
_IP_CHECK_PATH = "/ip"

# How often (seconds) to probe the external IP.  Short enough to catch VPN
# switches quickly, long enough to be negligible overhead.
DEFAULT_CHECK_INTERVAL = 30

# How long (seconds) to wait for the IP check to complete.
_CHECK_TIMEOUT = 10


class VpnMonitor:
    """Tracks the external IP and fires a callback when it changes."""

    def __init__(
        self,
        proxy_host: str,
        proxy_port: int,
        *,
        check_interval: float = DEFAULT_CHECK_INTERVAL,
    ) -> None:
        self._proxy_host = proxy_host
        self._proxy_port = proxy_port
        self._check_interval = check_interval
        self._last_ip: str | None = None
        self._last_check: float = 0.0

    async def check_ip(self) -> str | None:
        """Return the current external IP seen through the SOCKS5 proxy, or
        ``None`` if the check fails."""
        reader = writer = None
        try:
            from python_socks import ProxyType
            from python_socks.async_.asyncio.v2 import Proxy

            proxy = Proxy(
                proxy_type=ProxyType.SOCKS5,
                host=self._proxy_host,
                port=self._proxy_port,
                rdns=True,
            )
            stream = await asyncio.wait_for(
                proxy.connect(dest_host=_IP_CHECK_HOST, dest_port=_IP_CHECK_PORT),
                timeout=_CHECK_TIMEOUT,
            )

            # Plain HTTP GET — no TLS needed.
            request = (
                f"GET {_IP_CHECK_PATH} HTTP/1.1\r\n"
                f"Host: {_IP_CHECK_HOST}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            )
            await stream.write(request.encode())

            data = await asyncio.wait_for(stream.read(1024), timeout=_CHECK_TIMEOUT)
            text = data.decode("utf-8", errors="replace")

            # Parse: skip headers, body is JSON like {"origin": "1.2.3.4"}.
            if "\r\n\r\n" in text:
                body = text.split("\r\n\r\n", 1)[1].strip()
            else:
                body = text.strip()

            # Try JSON parse first.
            import json
            try:
                ip = json.loads(body).get("origin", "")
            except (json.JSONDecodeError, AttributeError):
                # Fallback: raw text body.
                ip = body.split("\n")[0].strip()

            await stream.close()
            if ip:
                return ip
            return None
        except Exception as exc:
            logger.debug("VPN IP check failed: %s", exc)
            return None

    async def tick(self, on_ip_change: "asyncio.coroutine") -> bool:
        """Call from the main loop.  Returns ``True`` if the IP changed.

        ``on_ip_change`` is an async callable invoked (once) when the IP
        changes — it should disconnect Telegram clients.
        """
        now = time.monotonic()
        if now - self._last_check < self._check_interval:
            return False
        self._last_check = now

        ip = await self.check_ip()
        if ip is None:
            # Check failed — could be the tunnel is already down.  Don't
            # treat this as an IP change to avoid false positives.
            return False

        if self._last_ip is None:
            # First successful check — just record it.
            logger.info("VPN IP monitor: initial IP %s", ip)
            self._last_ip = ip
            return False

        if ip != self._last_ip:
            logger.warning(
                "VPN IP changed: %s → %s — disconnecting Telegram clients",
                self._last_ip,
                ip,
            )
            self._last_ip = ip
            await on_ip_change()
            return True

        return False
