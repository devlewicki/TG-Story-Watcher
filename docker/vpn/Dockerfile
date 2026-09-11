FROM alpine:3.19

RUN apk add --no-cache curl python3 py3-requests bash jq

ARG XRAY_VERSION=26.3.27
RUN ARCH=$(uname -m) && \
    case "$ARCH" in \
      x86_64)  XARCH="64" ;; \
      aarch64) XARCH="arm64-v8a" ;; \
      armv7l)  XARCH="arm32-v7a" ;; \
      *) echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/Xray-linux-${XARCH}.zip" -o /tmp/xray.zip && \
    unzip /tmp/xray.zip -d /usr/local/bin && \
    rm /tmp/xray.zip && \
    chmod +x /usr/local/bin/xray

RUN mkdir -p /etc/xray /var/log/xray

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV VPN_SUBSCRIPTION_URL=""

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -x socks5://127.0.0.1:1080 -sf https://ifconfig.me || exit 1

ENTRYPOINT ["/entrypoint.sh"]
