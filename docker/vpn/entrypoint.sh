#!/usr/bin/env python3
"""
VPN container entrypoint.
Fetches V2Ray subscription, parses server links, generates Xray config, runs Xray.
"""
import base64
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vpn")

XRAY_CONFIG_PATH = "/etc/xray/config.json"
SUB_URL = os.environ.get("VPN_SUBSCRIPTION_URL", "")
REFRESH_INTERVAL = int(os.environ.get("VPN_REFRESH_INTERVAL", "3600"))
SOCKS_PORT = int(os.environ.get("VPN_SOCKS_PORT", "1080"))
LOG_LEVEL = os.environ.get("VPN_LOG_LEVEL", "warning")
TEST_URL = os.environ.get("VPN_TEST_URL", "https://www.gstatic.com/generate_204")
TEST_TIMEOUT = int(os.environ.get("VPN_TEST_TIMEOUT", "8"))
PROBE_INTERVAL = int(os.environ.get("VPN_PROBE_INTERVAL", "10"))
FAIL_THRESHOLD = int(os.environ.get("VPN_FAIL_THRESHOLD", "3"))
SCAN_PORT = int(os.environ.get("VPN_SCAN_PORT", str(SOCKS_PORT + 1)))
SCAN_SLEEP = float(os.environ.get("VPN_SCAN_SLEEP", "1.0"))
SCAN_ATTEMPTS = int(os.environ.get("VPN_SCAN_ATTEMPTS", "1"))
# After a failover scan finds nothing, don't re-scan for a while — the current
# server keeps serving (degraded) instead of dropping the SOCKS port for
# minutes while the whole list is re-probed each probe window.
FAILOVER_COOLDOWN = int(os.environ.get("VPN_FAILOVER_COOLDOWN", "120"))
# Optional server name filter (case-insensitive substring of the server label
# from the subscription, e.g. "netherlands"). Servers whose label contains
# "test" are always excluded. If set, the VPN only ever uses matching servers.
SERVER_FILTER = os.environ.get("VPN_SERVER_FILTER", "").strip().lower()

xray_proc: subprocess.Popen | None = None


def fetch_subscription(url: str) -> list[str]:
    """Fetch subscription URL and return list of proxy links."""
    log.info("Fetching subscription from %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "V2RayN/6.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except Exception as exc:
        log.error("Failed to fetch subscription: %s", exc)
        return []

    text = raw.decode("utf-8", errors="ignore").strip()

    # Try base64 decode
    try:
        decoded = base64.b64decode(text).decode("utf-8", errors="ignore")
        if "://" in decoded:
            text = decoded
    except Exception:
        pass

    links = []
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^(vmess|vless|ss|trojan)://", line):
            links.append(line)

    log.info("Found %d proxy links", len(links))
    return links


def parse_vmess(link: str) -> dict[str, Any] | None:
    """Parse vmess:// link (base64 JSON)."""
    try:
        raw = link[len("vmess://"):]
        data = json.loads(base64.b64decode(raw + "==").decode())
        return {
            "protocol": "vmess",
            "address": data.get("add", ""),
            "port": int(data.get("port", 443)),
            "uuid": data.get("id", ""),
            "alter_id": int(data.get("aid", 0)),
            "security": data.get("scy", "auto"),
            "network": data.get("net", "tcp"),
            "tls": data.get("tls", ""),
            "host": data.get("host", ""),
            "path": data.get("path", ""),
            "name": data.get("ps", "vmess"),
        }
    except Exception as exc:
        log.warning("Failed to parse vmess link: %s", exc)
        return None


def parse_vless(link: str) -> dict[str, Any] | None:
    """Parse vless:// link (URI format)."""
    try:
        # vless://uuid@host:port?params#name
        # The fragment (#name) must NOT bleed into the query params.
        match = re.match(
            r"vless://([^@]+)@([^:]+):(\d+)\?([^#]*)(?:#(.*))?",
            link,
        )
        if not match:
            return None
        uuid, host, port, query_str, name = match.groups()

        def _q(v: str) -> str:
            return urllib.parse.unquote(v) if v else v

        params = {k: _q(v) for k, v in re.findall(r"([a-z_]+)=([^&]*)", query_str or "")}
        return {
            "protocol": "vless",
            "address": host,
            "port": int(port),
            "uuid": uuid,
            "security": params.get("security", "none"),
            "network": params.get("type", "tcp"),
            "tls": params.get("security", "none"),
            "flow": params.get("flow", ""),
            "host": params.get("host", ""),
            "path": params.get("path", params.get("wsPath", "")),
            "sni": params.get("sni", params.get("peer", "")),
            "fp": params.get("fp", ""),
            "pbk": params.get("pbk", ""),
            "sid": params.get("sid", ""),
            "alpn": params.get("alpn", ""),
            "mode": params.get("mode", ""),
            "extra": params.get("extra", ""),
            "name": urllib.parse.unquote(name or "vless"),
        }
    except Exception as exc:
        log.warning("Failed to parse vless link: %s", exc)
        return None


def parse_shadowsocks(link: str) -> dict[str, Any] | None:
    """Parse ss:// link (SIP002 or legacy format)."""
    try:
        raw = link[len("ss://"):]
        name = ""
        if "#" in raw:
            raw, frag = raw.split("#", 1)
            name = frag
        raw = raw.replace("/", "")

        if "@" in raw:
            b64_part, host_port = raw.split("@", 1)
            if ":" in b64_part and not b64_part.endswith("=") and b64_part.count(":") == 0:
                method, password = b64_part.split(":", 1)
            else:
                decoded = base64.b64decode(b64_part + "==").decode()
                method, password = decoded.split(":", 1)
            host, port = host_port.rsplit(":", 1)
        else:
            decoded = base64.b64decode(raw + "==").decode()
            method_pass, host_port = decoded.rsplit("@", 1)
            method, password = method_pass.split(":", 1)
            host, port = host_port.rsplit(":", 1)

        return {
            "protocol": "shadowsocks",
            "address": host,
            "port": int(port),
            "method": method,
            "password": password,
            "name": name or "ss",
        }
    except Exception as exc:
        log.warning("Failed to parse ss link: %s", exc)
        return None


def parse_trojan(link: str) -> dict[str, Any] | None:
    """Parse trojan:// link."""
    try:
        match = re.match(
            r"trojan://([^@]+)@([^:]+):(\d+)\?([^#]*)(?:#(.*))?",
            link,
        )
        if not match:
            return None
        password, host, port, query_str, name = match.groups()
        params = dict(re.findall(r"([a-z_]+)=([^&]*)", query_str or ""))
        return {
            "protocol": "trojan",
            "address": host,
            "port": int(port),
            "password": password,
            "security": params.get("security", "tls"),
            "sni": params.get("sni", ""),
            "name": name or "trojan",
        }
    except Exception as exc:
        log.warning("Failed to parse trojan link: %s", exc)
        return None


def parse_link(link: str) -> dict[str, Any] | None:
    if link.startswith("vmess://"):
        return parse_vmess(link)
    elif link.startswith("vless://"):
        return parse_vless(link)
    elif link.startswith("ss://"):
        return parse_shadowsocks(link)
    elif link.startswith("trojan://"):
        return parse_trojan(link)
    return None


def server_label(server: dict[str, Any] | None) -> str:
    """Human-readable label for a parsed server (for logs)."""
    if not server:
        return "?"
    name = server.get("name", "") or ""
    name = urllib.parse.unquote(name).strip()
    return f"{name} ({server['address']})".strip()


def filter_links(links: list[str]) -> list[str]:
    """Keep only links matching the optional VPN_SERVER_FILTER.

    ``test`` servers are always excluded so they can never be picked as a
    primary exit (they are probes/mirrors, not stable egress nodes).
    """
    if not SERVER_FILTER:
        return [lnk for lnk in links if "test" not in lnk.lower()]

    kept = []
    for lnk in links:
        server = parse_link(lnk)
        if server is None:
            continue
        label = (server.get("name") or "").lower()
        if "test" in label or "test" in lnk.lower():
            continue
        if SERVER_FILTER not in label:
            continue
        kept.append(lnk)
    return kept


def build_xray_outbound(server: dict) -> dict:
    """Build Xray outbound config from parsed server dict."""
    proto = server["protocol"]
    address = server["address"]
    port = server["port"]

    if proto == "vmess":
        stream_settings: dict[str, Any] = {"network": server.get("network", "tcp")}
        security = server.get("tls", "")
        if security == "tls":
            stream_settings["security"] = "tls"
            if server.get("host"):
                stream_settings["tlsSettings"] = {"serverName": server["host"]}
        net = server.get("network", "tcp")
        if net == "ws":
            ws_opts: dict[str, Any] = {}
            if server.get("path"):
                ws_opts["path"] = server["path"]
            if server.get("host"):
                ws_opts["headers"] = {"Host": server["host"]}
            stream_settings["wsSettings"] = ws_opts
        elif net == "grpc":
            if server.get("path"):
                stream_settings["grpcSettings"] = {"serviceName": server["path"]}

        return {
            "tag": "proxy",
            "protocol": "vmess",
            "settings": {
                "vnext": [
                    {
                        "address": address,
                        "port": port,
                        "users": [
                            {
                                "id": server["uuid"],
                                "alterId": server.get("alter_id", 0),
                                "security": server.get("security", "auto"),
                            }
                        ],
                    }
                ]
            },
            "streamSettings": stream_settings,
        }

    elif proto == "vless":
        net = server.get("network", "tcp")
        stream_settings = {"network": net}
        security = server.get("tls", "none")
        if security in ("tls", "reality"):
            stream_settings["security"] = security
            sec_opts: dict[str, Any] = {}
            if server.get("sni"):
                sec_opts["serverName"] = server["sni"]
            if server.get("fp"):
                sec_opts["fingerprint"] = server["fp"]
            if server.get("alpn"):
                sec_opts["alpn"] = [a for a in (server["alpn"].split(",")) if a]
            if security == "reality":
                if server.get("pbk"):
                    sec_opts["publicKey"] = server["pbk"]
                if server.get("sid"):
                    sec_opts["shortId"] = server["sid"]
                sec_opts["spiderX"] = "/"
            if sec_opts:
                stream_settings[f"{security}Settings"] = sec_opts

        if net == "ws":
            ws_opts = {}
            if server.get("path"):
                ws_opts["path"] = server["path"]
            if server.get("host"):
                ws_opts["headers"] = {"Host": server["host"]}
            stream_settings["wsSettings"] = ws_opts
        elif net == "grpc":
            if server.get("path"):
                stream_settings["grpcSettings"] = {"serviceName": server["path"]}
        elif net == "xhttp":
            xhttp_opts: dict[str, Any] = {}
            if server.get("path"):
                xhttp_opts["path"] = server["path"]
            if server.get("mode"):
                xhttp_opts["mode"] = server["mode"]
            if server.get("extra"):
                try:
                    xhttp_opts["extra"] = json.loads(server["extra"])
                except Exception:
                    pass
            if xhttp_opts:
                stream_settings["xhttpSettings"] = xhttp_opts

        user: dict[str, Any] = {"id": server["uuid"], "encryption": "none"}
        if server.get("flow"):
            user["flow"] = server["flow"]

        return {
            "tag": "proxy",
            "protocol": "vless",
            "settings": {
                "vnext": [
                    {
                        "address": address,
                        "port": port,
                        "users": [user],
                    }
                ]
            },
            "streamSettings": stream_settings,
        }

    elif proto == "shadowsocks":
        return {
            "tag": "proxy",
            "protocol": "shadowsocks",
            "settings": {
                "servers": [
                    {
                        "address": address,
                        "port": port,
                        "method": server.get("method", "aes-128-gcm"),
                        "password": server.get("password", ""),
                    }
                ]
            },
        }

    elif proto == "trojan":
        stream_settings = {"security": "tls", "network": "tcp"}
        if server.get("sni"):
            stream_settings["tlsSettings"] = {"serverName": server["sni"]}
        return {
            "tag": "proxy",
            "protocol": "trojan",
            "settings": {
                "servers": [
                    {
                        "address": address,
                        "port": port,
                        "password": server.get("password", ""),
                    }
                ]
            },
            "streamSettings": stream_settings,
        }

    raise ValueError(f"Unknown protocol: {proto}")


def build_xray_config(server: dict) -> dict:
    """Build full Xray config with SOCKS5 inbound and given outbound."""
    return {
        "log": {"loglevel": LOG_LEVEL, "access": "/var/log/xray/access.log", "error": "/var/log/xray/error.log"},
        "inbounds": [
            {
                "tag": "socks-in",
                "port": SOCKS_PORT,
                "listen": "0.0.0.0",
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
            }
        ],
        "outbounds": [
            build_xray_outbound(server),
            {"protocol": "freedom", "tag": "direct"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {
                    "type": "field",
                    "outboundTag": "direct",
                    "ip": ["geoip:private"],
                },
                {
                    "type": "field",
                    "outboundTag": "direct",
                    "domain": ["geosite:category-ru"],
                },
            ],
        },
    }


def start_xray(config: dict) -> subprocess.Popen:
    """Write config and start Xray process."""
    os.makedirs(os.path.dirname(XRAY_CONFIG_PATH), exist_ok=True)
    os.makedirs("/var/log/xray", exist_ok=True)
    with open(XRAY_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    outbound = config["outbounds"][0]
    settings = outbound.get("settings", {})
    servers = settings.get("servers") or settings.get("vnext")
    if servers:
        target = servers[0].get("address", "?")
        port = servers[0].get("port", "?")
    else:
        target, port = "?", "?"
    log.info("Starting Xray with outbound: %s -> %s:%s", outbound.get("protocol", "?"), target, port)
    with open("/var/log/xray/xray.out", "ab") as out:
        return subprocess.Popen(
            ["xray", "run", "-c", XRAY_CONFIG_PATH],
            stdout=out,
            stderr=subprocess.STDOUT,
        )


def stop_xray(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        log.info("Stopping Xray (pid=%d)", proc.pid)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def probe_tunnel(port: int) -> tuple[bool, float]:
    """Probe the SOCKS proxy on `port` and return (worked, RTT seconds or inf)."""
    cmd = [
        "curl", "-sS", "-o", "/dev/null", "-x",
        f"socks5://127.0.0.1:{port}",
        "--max-time", str(TEST_TIMEOUT),
        "-w", "%{http_code} %{time_total}",
        TEST_URL,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TEST_TIMEOUT + 5)
        parts = result.stdout.strip().split()
        code = parts[0] if parts else ""
        rtt = float(parts[1]) if len(parts) > 1 else float("inf")
        return code == "204", rtt
    except Exception as exc:
        log.warning("Proxy connectivity test failed: %s", exc)
        return False, float("inf")


def test_proxy() -> bool:
    """Verify the local SOCKS proxy actually tunnels traffic to the internet.

    A single flaky probe (e.g. a gstatic hiccup) must not be enough to trigger
    a failover — the check is retried once before counting as a failure.
    """
    for _ in range(2):
        ok, _ = probe_tunnel(SOCKS_PORT)
        if ok:
            return True
    return False


def probe_server(server: dict, port: int) -> tuple[bool, float]:
    """Start Xray for `server` on `port` and time a real proxied request.

    Returns (worked, best_RTT). Xray is stopped before returning so the port
    can be used for the next candidate.
    """
    try:
        config = build_xray_config(server)
    except Exception as exc:
        log.warning("Failed to build config for %s: %s", server["address"], exc)
        return False, float("inf")
    config["inbounds"][0]["port"] = port
    path = "/tmp/xray_scan.json"
    with open(path, "w") as f:
        json.dump(config, f)
    proc = subprocess.Popen(
        ["xray", "run", "-c", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        time.sleep(SCAN_SLEEP)
        if proc.poll() is not None:
            return False, float("inf")
        ok, best = False, float("inf")
        for _ in range(SCAN_ATTEMPTS):
            passed, rtt = probe_tunnel(port)
            if passed:
                ok = True
                best = min(best, rtt)
            time.sleep(0.3)
        return ok, best
    finally:
        stop_xray(proc)


def scan_candidates(links: list[str], start: int = 0) -> list[tuple[float, int, dict]]:
    """Probe every candidate on the scan port, sorted by RTT (fastest first).

    The live proxy on SOCKS_PORT is never touched — if nothing works we can
    keep the current server running instead of dropping the port for minutes.
    """
    n = len(links)
    candidates: list[tuple[float, int, dict]] = []
    for offset in range(n):
        i = (start + offset) % n
        link = links[i]
        server = parse_link(link)
        if not server:
            continue
        log.info("Testing server %d/%d: %s (%s)", i + 1, n, server.get("name", "?"), server["address"])
        ok, rtt = probe_server(server, SCAN_PORT)
        if ok:
            log.info("  %s works, RTT=%.2fs", server["address"], rtt)
            candidates.append((rtt, i, server))
        else:
            log.info("  %s failed, skipping", server["address"])
    candidates.sort(key=lambda c: c[0])
    return candidates


def find_next_candidate(
    links: list[str],
    start: int,
    count: int,
) -> tuple[int, dict] | None:
    """Return the first working server after ``start`` in list order.

    Unlike ``scan_candidates`` (which re-ranks everything by RTT and can thus
    bounce the exit IP between countries/cities on every failover), this walks
    the filtered list sequentially and returns the first healthy server. The
    exit IP only changes when a failover actually happens, and it stays within
    the configured VPN_SERVER_FILTER set.
    """
    n = len(links)
    for offset in range(1, min(count, n) + 1):
        i = (start + offset) % n
        link = links[i]
        server = parse_link(link)
        if not server:
            continue
        log.info("Testing next candidate %d/%d: %s", offset, count, server_label(server))
        ok, rtt = probe_server(server, SCAN_PORT)
        if ok:
            log.info("  %s works, RTT=%.2fs", server["address"], rtt)
            return i, server
        log.info("  %s failed, skipping", server["address"])
    return None


def launch_on_socks(server: dict) -> tuple[dict | None, subprocess.Popen | None]:
    """Start Xray for ``server`` on the live SOCKS port and verify the tunnel.

    Returns (config, process) or (None, None) if it fails to start/verify.
    """
    try:
        config = build_xray_config(server)
    except Exception as exc:
        log.warning("Failed to build config for %s: %s", server["address"], exc)
        return None, None
    proc = start_xray(config)
    time.sleep(3)
    if proc.poll() is not None:
        log.warning("Xray exited immediately for %s", server["address"])
        stop_xray(proc)
        return None, None
    if test_proxy():
        log.info("Server %s works (tunnel verified)", server["address"])
        return config, proc
    log.warning("Tunnel not working through %s", server["address"])
    stop_xray(proc)
    return None, None


def try_links(links: list[str], start: int = 0) -> tuple[dict | None, subprocess.Popen | None, int]:
    """Pick the fastest working server and run Xray for it on the SOCKS port.

    Every candidate is tested on a dedicated scan port (so the live proxy keeps
    working), its tunnel RTT is measured, and candidates are started on the
    SOCKS port one by one until the tunnel verifies.
    Returns (config, process, index), or (None, None, -1) if none work.
    """
    candidates = scan_candidates(links, start)
    if not candidates:
        log.warning("No working servers found")
        return None, None, -1

    for rtt, i, server in candidates:
        log.info("Starting best server: %s (RTT=%.2fs) on :%d", server["address"], rtt, SOCKS_PORT)
        config, proc = launch_on_socks(server)
        if proc is not None:
            return config, proc, i
        log.warning("Tunnel not working through %s, trying next", server["address"])
    return None, None, -1


def main():
    global xray_proc

    if not SUB_URL:
        log.error("VPN_SUBSCRIPTION_URL is not set")
        sys.exit(1)

    links = fetch_subscription(SUB_URL)
    if not links:
        log.error("No proxy links found in subscription")
        sys.exit(1)

    links = filter_links(links)
    if not links:
        log.error(
            "VPN_SERVER_FILTER=%r matched no servers in subscription. Available servers:",
            SERVER_FILTER,
        )
        for lnk in fetch_subscription(SUB_URL):
            server = parse_link(lnk)
            if server:
                log.error("  - %s", server_label(server))
        sys.exit(1)
    log.info("Subscription filtered to %d server(s)", len(links))

    config, xray_proc, current_index = try_links(links)
    if config is None:
        log.error("All servers failed")
        sys.exit(1)

    def handle_signal(sig, frame):
        log.info("Received signal %s, shutting down", sig)
        stop_xray(xray_proc)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    last_refresh = time.time()
    last_probe = time.time()
    last_failover_scan = 0.0
    fail_count = 0
    backoff = 10

    while True:
        if xray_proc is None:
            # Previous failover exhausted the list; back off then retry.
            log.warning("No working server, retrying in %ds", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
            fresh = filter_links(fetch_subscription(SUB_URL))
            if not fresh:
                log.warning("Refetch produced no matching servers; retrying with previous list")
                fresh = links
            links = fresh
            config, xray_proc, current_index = try_links(links)
            if config:
                fail_count = 0
                backoff = 10
            continue

        if xray_proc.poll() is not None:
            log.warning("Xray crashed, restarting with same config")
            xray_proc = start_xray(config)
            fail_count = 0

        now = time.time()

        if now - last_probe >= PROBE_INTERVAL:
            last_probe = now
            if test_proxy():
                fail_count = 0
            else:
                fail_count += 1
                log.warning("Tunnel check failed (%d/%d)", fail_count, FAIL_THRESHOLD)
                if fail_count >= FAIL_THRESHOLD:
                    fail_count = 0
                    if now - last_failover_scan < FAILOVER_COOLDOWN:
                        # A recent scan already found nothing — keep the
                        # (degraded) current server instead of re-scanning and
                        # dropping the SOCKS port again.
                        log.warning("Failover scan on cooldown — keeping current server")
                    else:
                        log.warning("Failing over (current server stays live while scanning)")
                        hit = find_next_candidate(links, current_index, count=len(links) - 1)
                        last_failover_scan = now
                        if hit is None:
                            log.warning("No working candidates found — keeping current server")
                        else:
                            _, server = hit
                            # Stop the old proxy only once a replacement has been
                            # verified on the scan port, so the outage window is
                            # just the swap itself (seconds), not the whole scan.
                            stop_xray(xray_proc)
                            xray_proc = None
                            cfg2, proc2 = launch_on_socks(server)
                            if proc2 is not None:
                                config, xray_proc, current_index = cfg2, proc2, hit[0]
                                log.info("Failover complete: %s", server_label(server))
                            else:
                                log.warning("Tunnel not working through %s, trying next", server["address"])
                                config = None  # next iteration's backoff block retries the list

        if now - last_refresh >= REFRESH_INTERVAL:
            log.info("Refreshing subscription...")
            last_refresh = now
            fresh = filter_links(fetch_subscription(SUB_URL))
            if not fresh:
                log.warning("Refresh produced no matching servers — keeping current config")
                continue
            links = fresh
            # Never switch away from a healthy tunnel just because the list
            # changed — only fail over on a real connection loss.
            if test_proxy():
                log.info("Refresh: current tunnel healthy — keeping %s", server_label(parse_link(links[current_index % len(links)])))
                continue
            log.warning("Refresh: current tunnel unhealthy — failing over")
            hit = find_next_candidate(links, current_index, count=len(links) - 1)
            if hit is None:
                log.warning("Refresh found no working servers — keeping current config")
            else:
                _, server = hit
                stop_xray(xray_proc)
                xray_proc = None
                cfg2, proc2 = launch_on_socks(server)
                if proc2 is not None:
                    config, xray_proc, current_index = cfg2, proc2, hit[0]
                    log.info("Refresh complete: now on %s", server_label(server))
                else:
                    log.warning("Tunnel not working through %s, trying next", server["address"])
                    config = None

        time.sleep(2)


if __name__ == "__main__":
    main()
