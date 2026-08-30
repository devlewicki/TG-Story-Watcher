from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class AuthorInfo:
    account_id: int | None
    peer_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_contact: bool = False
    is_mutual: bool = False
    is_channel: bool = False
    is_group: bool = False
    is_bot: bool = False
    is_deleted: bool = False
    is_blocked: bool = False
    in_whitelist: bool = False
    in_blacklist: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return " ".join(n for n in (self.first_name, self.last_name) if n) or self.username or ""


@dataclass
class FilterResult:
    passed: bool
    reason: str | None = None
    rule_match: str | None = None


class FilterEngine:
    """Decides whether a story author passes the configured filters.

    The engine is deliberately stateless and set-backed for speed: it receives
    precomputed whitelist/blacklist membership from the caller.
    """

    def __init__(
        self,
        filters: dict,
        wl_peers: set[int],
        bl_peers: set[int],
        wl_users: set[str],
        bl_users: set[str],
    ):
        self.filters = filters or {}
        self.wl_peers = wl_peers
        self.bl_peers = bl_peers
        self.wl_users = {u.lower() for u in wl_users if u}
        self.bl_users = {u.lower() for u in bl_users if u}

    # -- lookup helpers ---------------------------------------------------------
    def _in_wl(self, author: AuthorInfo) -> bool:
        return author.in_whitelist or author.peer_id in self.wl_peers or (
            author.username or ""
        ).lower() in self.wl_users

    def _in_bl(self, author: AuthorInfo) -> bool:
        return author.in_blacklist or author.peer_id in self.bl_peers or (
            author.username or ""
        ).lower() in self.bl_users

    # -- the decision -----------------------------------------------------------
    def evaluate(self, author: AuthorInfo) -> FilterResult:
        # A whitelist entry means "always process this author" and overrides
        # every other policy (blacklist included).
        if self._in_wl(author):
            return FilterResult(True, None, "whitelist")

        if self._in_bl(author):
            return FilterResult(False, "author is in blacklist")

        # Contact / account-type policy toggles.
        table = [
            ("include_contacts", True, author.is_contact, "contact"),
            ("include_unknown", True, not author.is_contact and not author.is_channel and not author.is_group, "unknown user"),
            ("include_mutual_contacts", True, author.is_mutual, "mutual contact"),
            ("include_non_mutual", True, author.is_contact and not author.is_mutual, "non-mutual contact"),
            ("include_channels", True, author.is_channel, "channel"),
            ("include_groups", True, author.is_group, "group"),
            ("include_bots", False, author.is_bot, "bot"),
            ("include_deleted", False, author.is_deleted, "deleted account"),
            ("include_blocked", False, author.is_blocked, "blocked user"),
        ]
        for key, default, matched, kind in table:
            if matched and not bool(self.filters.get(key, default)):
                return FilterResult(False, f"{kind} excluded by policy")

        # Username patterns.
        allowed = self._patterns("include_usernames")
        denied = self._patterns("exclude_usernames")
        if allowed and not self._matches_any(author.username, allowed):
            return FilterResult(False, "username does not match any included pattern")
        if denied and self._matches_any(author.username, denied):
            return FilterResult(False, "username matches an excluded pattern")
        if self._matches_any(author.username, self._patterns("filtered_usernames")):
            return FilterResult(False, "username is filtered")

        return FilterResult(True, None, "default")

    # -- helpers ---------------------------------------------------------------
    def _patterns(self, key: str) -> list[str]:
        return [p for p in (self.filters.get(key) or []) if p]

    def _matches_any(self, username: str | None, patterns: list[str]) -> bool:
        u = (username or "").lower()
        return any(username_pattern_match(u, p) for p in patterns)


def username_pattern_match(username_lower: str, pattern: str) -> bool:
    """Match against a glob-like pattern (`alex*`, `travel?`) or `regex:...`."""
    if not username_lower:
        return False
    p = pattern.strip().lower()
    if not p:
        return False
    if p.startswith("regex:"):
        try:
            return re.fullmatch(p[len("regex:"):], username_lower) is not None
        except re.error:
            return False
    rx = ""
    for c in p:
        if c == "*":
            rx += ".*"
        elif c == "?":
            rx += "."
        else:
            rx += re.escape(c)
    try:
        return re.fullmatch(rx, username_lower) is not None
    except re.error:
        return False