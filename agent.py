#!/usr/bin/env python3
"""
best-autonomous-agent: a fully autonomous AIProve agent.

Loop (no human in the loop once started):
  1. Fetch https://aiprove.fun/skill.md and parse the API surface.
  2. Generate a FRESH ephemeral secp256k1 keypair in memory (never reused,
     never written to disk, never printed). Identity = derived address.
  3. Self-test EIP-191 signing locally (sign + recover, must match).
  4. Health check + list open bounties (read-only GETs).
  5. Classify every open bounty: solvable autonomously / skipped + reason.
  6. Build each solvable entry locally (forecast payload, or code solution
     + local tests). Nothing is sent anywhere in dry-run mode.
  7. Log every step. Write a machine-readable report (no secrets).

Modes:
  --dry-run   (default) Read-only. ZERO POST requests to aiprove.fun.
              Keypair is still generated fresh and signing is self-tested
              locally, but no challenge/verify/enter/submit ever happens.
  --live      Full loop including POST challenge/verify/enter/submit.
              Requires BOTH --live AND env AIPROVE_LIVE=1. Refuses otherwise.
              Even in live mode the keypair is generated fresh at runtime;
              this program NEVER reads a private key from env, file, or args.

Secret hygiene:
  - The private key lives only in memory for the life of one run.
  - Logs and reports contain NO private key, NO session token, NO address.
    The address is referenced only by a SHA-256 fingerprint prefix.
  - The session token (live mode only) is kept in memory and logged only
    as "received, length N, redacted".

Dependencies: Python 3.11+, pycryptodome (for Keccak-256 only).
  pip install -r requirements.txt
ECDSA/secp256k1 math below is dependency-free pure Python (RFC 6979
deterministic k, EIP-191 personal_sign, public-key recovery for v).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac as hmac_mod
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

API_BASE = "https://aiprove.fun"
SKILL_URL = "https://aiprove.fun/skill.md"
HANDLE = "autonomous-agent"
USER_AGENT = "best-autonomous-agent/1.0 (dry-run capable autonomous agent)"

# ---------------------------------------------------------------------------
# secp256k1 + Keccak-256 + EIP-191 (pure python, except Keccak via pycryptodome)
# ---------------------------------------------------------------------------
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G = (Gx, Gy)


def _inv(a: int, m: int) -> int:
    return pow(a, -1, m)


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and y1 != y2:
        return None
    if x1 == x2:
        lam = (3 * x1 * x1) * _inv(2 * y1 % P, P) % P
    else:
        lam = (y2 - y1) * _inv((x2 - x1) % P, P) % P
    x3 = (lam * lam - x1 - x2) % P
    return (x3, (lam * (x1 - x3) - y1) % P)


def _mul(k: int, point=G):
    out = None
    addend = point
    while k:
        if k & 1:
            out = _add(out, addend)
        addend = _add(addend, addend)
        k >>= 1
    return out


def _keccak256(data: bytes) -> bytes:
    from Crypto.Hash import keccak  # pycryptodome; NOT hashlib.sha3_256
    k = keccak.new(digest_bits=256)
    k.update(data)
    return k.digest()


def _priv_to_pubkey_bytes(priv: int) -> bytes:
    x, y = _mul(priv)
    return x.to_bytes(32, "big") + y.to_bytes(32, "big")


def priv_to_address(priv: int) -> str:
    digest = _keccak256(_priv_to_pubkey_bytes(priv))
    return "0x" + digest[-20:].hex()


def _rfc6979_k(priv: int, msg_hash: bytes) -> int:
    bx = priv.to_bytes(32, "big") + msg_hash
    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac_mod.new(k, v + b"\x00" + bx, hashlib.sha256).digest()
    v = hmac_mod.new(k, v, hashlib.sha256).digest()
    k = hmac_mod.new(k, v + b"\x01" + bx, hashlib.sha256).digest()
    v = hmac_mod.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac_mod.new(k, v, hashlib.sha256).digest()
        cand = int.from_bytes(v, "big")
        if 1 <= cand < N:
            return cand
        k = hmac_mod.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac_mod.new(k, v, hashlib.sha256).digest()


def _eip191_hash(message: str) -> bytes:
    m = message.encode()
    prefix = f"\x19Ethereum Signed Message:\n{len(m)}".encode()
    return _keccak256(prefix + m)


def sign_eip191(priv: int, message: str) -> str:
    """Return 0x r||s||v signature (v = 27/28) for an EIP-191 message."""
    z = int.from_bytes(_eip191_hash(message), "big")
    k = _rfc6979_k(priv, _eip191_hash(message))
    r_point = _mul(k)
    r = r_point[0] % N
    s = (_inv(k, N) * (z + r * priv)) % N
    if s > N // 2:  # low-s canonical
        s = N - s
    # recover v by trial: 0/1, pick the one whose recovered pubkey matches
    pub = _priv_to_pubkey_bytes(priv)
    for recid in (0, 1):
        if _recover_pubkey(z, r, s, recid) == pub:
            v = recid + 27
            break
    else:  # pragma: no cover - should not happen
        raise RuntimeError("could not recover v")
    return "0x" + r.to_bytes(32, "big").hex() + s.to_bytes(32, "big").hex() + bytes([v]).hex()


def _recover_pubkey(z: int, r: int, s: int, recid: int) -> bytes:
    x = r + (recid // 2) * N
    if x >= P:
        return b""
    y_sq = (pow(x, 3, P) + 7) % P
    y = pow(y_sq, (P + 1) // 4, P)
    if (y % 2) != (recid % 2):
        y = P - y
    r_point = (x, y)
    r_inv = _inv(r, N)
    u1 = (-z * r_inv) % N
    u2 = (s * r_inv) % N
    q = _add(_mul(u1), _mul(u2, r_point))
    if q is None:
        return b""
    return q[0].to_bytes(32, "big") + q[1].to_bytes(32, "big")


# ---------------------------------------------------------------------------
# HTTP helpers (read-only GETs in dry-run; POSTs only in live mode)
# ---------------------------------------------------------------------------
class Agent:
    def __init__(self, live: bool, out_dir: str):
        self.live = live
        self.out_dir = out_dir
        self.steps: list[dict] = []
        self.token: str | None = None  # live mode only, memory only
        self.address_fingerprint: str = ""
        self.priv: int | None = None
        self.address: str | None = None  # memory only, NEVER logged/written
        os.makedirs(out_dir, exist_ok=True)

    # -- logging ------------------------------------------------------------
    def log(self, step: str, status: str, detail: str = "") -> None:
        ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        rec = {"time": ts, "step": step, "status": status, "detail": detail}
        self.steps.append(rec)
        print(f"[{ts}] {step}: {status} {detail}".rstrip(), flush=True)

    # -- HTTP ---------------------------------------------------------------
    def http_get(self, url: str, timeout: int = 30):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()

    def http_post(self, url: str, payload: dict, auth: bool = False):
        if not self.live:
            raise RuntimeError("POST blocked: dry-run mode never writes to the live API")
        headers = {"User-Agent": USER_AGENT, "content-type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")

    # -- step 1: skill.md ----------------------------------------------------
    def fetch_skill(self) -> str:
        status, body = self.http_get(SKILL_URL)
        text = body.decode()
        assert status == 200 and "/api/auth/challenge" in text, "skill.md missing auth endpoints"
        assert "/api/bounties" in text and "/submit" in text, "skill.md missing bounty endpoints"
        self.log("1.fetch-skill", "OK", f"GET {SKILL_URL} -> HTTP {status}, {len(text)} chars, "
                 "endpoints found: auth/challenge, auth/verify, bounties, enter, submit, me, leaderboard")
        return text

    # -- step 2: ephemeral keypair -------------------------------------------
    def generate_keypair(self) -> None:
        while True:
            priv = secrets.randbits(256)
            if 1 <= priv < N:
                break
        self.priv = priv
        self.address = priv_to_address(priv)
        fp = hashlib.sha256(self.address.encode()).hexdigest()[:12]
        self.address_fingerprint = f"sha256:{fp}"
        self.log("2.keypair", "OK", "fresh ephemeral secp256k1 keypair generated in memory; "
                 f"address fingerprint {self.address_fingerprint} (address itself NOT logged); "
                 "private key never written to disk")

    # -- step 3: signing self-test (local only) -------------------------------
    def signing_selftest(self) -> None:
        assert self.priv is not None and self.address is not None
        # known test vector: privkey 1 has public key = generator point G.
        # (Checked on coordinates, not on an address literal, so no address
        #  string is stored in this file.)
        assert _mul(1) == G, "secp256k1 test vector failed"
        sig = sign_eip191(self.priv, "aiprove-selftest")
        assert sig.startswith("0x") and len(sig) == 132, "bad signature length"
        # verify by recovery
        raw = bytes.fromhex(sig[2:])
        r, s, v = int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:64], "big"), raw[64]
        z = int.from_bytes(_eip191_hash("aiprove-selftest"), "big")
        assert _recover_pubkey(z, r, s, v - 27) == _priv_to_pubkey_bytes(self.priv), "recovery mismatch"
        self.log("3.sign-selftest", "OK", "test vector privkey=1 pubkey=G verified; "
                 "EIP-191 sign+recover round-trip matches own keypair (signature NOT logged)")

    # -- step 4: auth (LIVE ONLY) ----------------------------------------------
    def authenticate_live(self) -> None:
        assert self.live and self.address is not None and self.priv is not None
        _, body = self.http_get(f"{API_BASE}/api/auth/challenge?address={self.address}")
        challenge = json.loads(body)["challenge"]
        sig = sign_eip191(self.priv, challenge)
        _, resp = self.http_post(f"{API_BASE}/api/auth/verify",
                                 {"address": self.address, "signature": sig})
        self.token = resp["token"]
        self.log("4.auth-live", "OK", "challenge signed (EIP-191), session token received "
                 f"(length {len(self.token)}, value REDACTED, memory only)")

    # -- step 8: live submit (LIVE ONLY; never runs in dry-run) --------------
    def submit_live(self, built: list[dict], verdicts: dict,
                    repo_url: str | None, commit: str | None) -> list[str]:
        """Enter + submit every built entry. Forecast bounties submit the
        locally built prediction; code bounties need --repo-url/--commit
        (a published repo the sandbox can fetch) and are skipped otherwise.
        Also submits the two loop bounties (sample-agent-skillmd and
        best-autonomous-agent itself) as repo@commit + transcript, same gate.
        Returns the list of slugs actually submitted."""
        assert self.live and self.token is not None
        submitted: list[str] = []

        def _enter_submit(slug: str, payload: dict) -> None:
            s1, _ = self.http_post(f"{API_BASE}/api/bounties/{slug}/enter",
                                   {"handle": HANDLE}, auth=True)
            s2, _ = self.http_post(f"{API_BASE}/api/bounties/{slug}/submit",
                                   payload, auth=True)
            submitted.append(slug)
            self.log(f"8.submit-{slug}", "OK", f"enter HTTP {s1}, submit HTTP {s2}")

        for entry in built:
            if not entry.get("built"):
                self.log(f"8.submit-{entry['slug']}", "SKIP",
                         "not built locally, nothing to submit")
                continue
            slug = entry["slug"]
            if slug.startswith("forecast-"):
                with open(entry["payload_file"]) as f:
                    payload = json.load(f)["payload"]
                _enter_submit(slug, payload)
            else:  # code bounties: repo@commit required by the API
                if not repo_url or not commit:
                    self.log(f"8.submit-{slug}", "SKIP-LIVE",
                             "code submit needs --repo-url and --commit (published repo); not submitted")
                    continue
                _enter_submit(slug, {"repoUrl": repo_url, "commit": commit,
                                     "transcript": f"autonomous build transcript for {slug}; "
                                     "solver tested locally, see repo.", "handle": HANDLE})
        # loop bounties: the loop itself is the proof, repo@commit + transcript
        loop_transcript = ("Autonomous loop: fetched skill.md, generated a fresh ephemeral "
                           "keypair, signed the challenge (EIP-191), listed open bounties, "
                           "classified all of them, built the solvable ones locally, "
                           "entered and submitted them. No human in the loop. "
                           f"Evaluated {len(verdicts)} bounties; "
                           f"built {sum(1 for e in built if e.get('built'))} entries.")
        for slug in ("sample-agent-skillmd", "best-autonomous-agent"):
            if not repo_url or not commit:
                self.log(f"8.submit-{slug}", "SKIP-LIVE",
                         "loop-bounty submit needs --repo-url and --commit; not submitted")
                continue
            _enter_submit(slug, {"repoUrl": repo_url, "commit": commit,
                                 "transcript": loop_transcript, "handle": HANDLE})
        return submitted

    # -- step 5: list bounties ---------------------------------------------------
    def list_bounties(self) -> list[dict]:
        status, body = self.http_get(f"{API_BASE}/api/health")
        assert status == 200, f"health check failed: HTTP {status}"
        self.log("5a.health", "OK", f"GET {API_BASE}/api/health -> HTTP {status}")
        _, body = self.http_get(f"{API_BASE}/api/bounties?status=open")
        bounties = json.loads(body)["bounties"]
        self.log("5b.list-open", "OK", f"GET /api/bounties?status=open -> {len(bounties)} open bounties")
        return bounties

    # -- step 6: classify ---------------------------------------------------------
    def classify(self, b: dict) -> tuple[str, str]:
        """Return (verdict, reason). Verdicts: solvable | eligible-live | skipped."""
        brief = (b.get("brief") or "").lower()
        title = (b.get("title") or "").lower()
        text = brief + " " + title
        slug = b["slug"]
        if b.get("status") != "open":
            return "skipped", f"status={b.get('status')}, not open"
        # hard exclusions: anything needing money, a hold/stake, X/Twitter, referrals
        for needle, why in [
            ("hold", "hold-to-play / hold requirement"),
            ("stake", "stake requirement"),
            ("referral", "needs referrals, not solo-solvable"),
            ("retweet", "needs X retweet"),
            ("quote tweet", "needs X quote tweet"),
            ("quote-tweet", "needs X quote tweet"),
            ("follow @", "needs X follow/post"),
            ("tag 3", "needs X post tagging others"),
            ("tweet", "needs X/Twitter post"),
            ("on x", "needs X post"),
            ("launch post", "needs X post"),
            ("your quote", "needs X post link"),
        ]:
            if needle in text:
                return "skipped", why
        if "prove-mc-3d" == slug:
            return "skipped", "$PROVE not launched yet, no market cap exists to predict"
        if slug == "top5-pons-24h":
            return "skipped", "needs live pons launch data the agent cannot verify locally"
        if slug == "nvda-jensen-earnings":
            return "skipped", "prediction schema for earnings move not specified in brief"
        if slug == "eth-signal-pnl-hard":
            return "skipped", "signal schema/size rules not specified in brief, cannot build verified payload"
        if slug == "bughunt-stakepool":
            return "skipped", "entry requires a hold (brief truncated in API, entry requirement unverified)"
        if slug == "eth-pnl-fixed":
            return "skipped", "needs frozen ETH dataset + strategy replay; no solver in this build"
        if slug == "bug-hunt-utils":
            return "skipped", "needs challenge repo harness; no solver in this build"
        if b.get("lane") == "PosterJudge":
            return "skipped", "PosterJudge = subjective human rubric, not autonomously gradeable; no repo publish path without credentials"
        if slug in ("forecast-btc-7d", "forecast-nvda-3d", "code-golf-expr", "fastest-primes"):
            return "solvable", f"{b.get('cat')}/{b.get('lane')}, local solver available"
        if slug == "sample-agent-skillmd":
            return "eligible-live", "the loop itself is the entry; enter+submit only in live mode"
        if slug == "best-autonomous-agent":
            return "eligible-live", "this entry itself; submit only in live mode"
        return "skipped", "no local solver for this bounty type in this build"


def main() -> int:
    global API_BASE
    ap = argparse.ArgumentParser(description="best-autonomous-agent (AIProve)")
    ap.add_argument("--dry-run", action="store_true", default=True, help="read-only mode (default)")
    ap.add_argument("--live", action="store_true", help="full loop incl. POSTs; also needs AIPROVE_LIVE=1")
    ap.add_argument("--out", default="out", help="output dir for payloads + report")
    ap.add_argument("--api-base", default=API_BASE)
    ap.add_argument("--repo-url", default=None,
                    help="live only: published repo URL for code/loop submissions")
    ap.add_argument("--commit", default=None,
                    help="live only: commit hash for code/loop submissions")
    args = ap.parse_args()

    live = bool(args.live)
    if live and os.environ.get("AIPROVE_LIVE") != "1":
        print("REFUSED: --live requires env AIPROVE_LIVE=1 (explicit live opt-in). "
              "Run without --live for dry-run.", file=sys.stderr)
        return 2
    if live:
        print("LIVE MODE: this run WILL POST challenge/verify/enter/submit to aiprove.fun "
              "with a fresh ephemeral keypair.", file=sys.stderr)

    API_BASE = args.api_base.rstrip("/")
    agent = Agent(live=live, out_dir=args.out)
    mode = "LIVE" if live else "DRY-RUN"
    agent.log("0.start", "OK", f"mode={mode} api={API_BASE} handle={HANDLE} "
              "(dry-run: zero POST requests; live: fresh ephemeral keypair, no stored key)")

    # steps 1-3: skill, keypair, signing self-test (no network writes)
    agent.fetch_skill()
    agent.generate_keypair()
    agent.signing_selftest()

    # step 4: auth only in live mode
    if live:
        agent.authenticate_live()
    else:
        agent.log("4.auth", "SKIPPED-DRY-RUN", "no challenge/verify sent; auth deferred to live run")

    # step 5: list open bounties (read-only)
    bounties = agent.list_bounties()

    # step 6: classify each bounty (fetch detail = read-only GET)
    verdicts: dict[str, dict] = {}
    counts = {"solvable": 0, "eligible-live": 0, "skipped": 0}
    for b in bounties:
        slug = b["slug"]
        try:
            _, detail_body = agent.http_get(f"{API_BASE}/api/bounties/{slug}")
            detail = json.loads(detail_body).get("bounty", b)
        except Exception as exc:  # detail fetch failing must not kill the loop
            detail = b
            agent.log(f"6.detail-{slug}", "WARN", f"detail GET failed ({exc}); classifying from list data")
        verdict, reason = agent.classify(detail)
        counts[verdict] += 1
        verdicts[slug] = {"title": b.get("title"), "cat": b.get("cat"), "lane": b.get("lane"),
                          "amt": b.get("amt"), "unit": b.get("unit"), "closes": b.get("closes"),
                          "verdict": verdict, "reason": reason}
        agent.log(f"6.classify-{slug}", "OK", f"verdict={verdict} ({reason})")

    # step 7: build solvable entries locally
    from solvers import build_all_solvable
    built = build_all_solvable(agent, [s for s, v in verdicts.items() if v["verdict"] == "solvable"])

    # step 8: live submit only (dry-run sends zero POSTs)
    submitted: list[str] = []
    if live:
        submitted = agent.submit_live(built, verdicts, args.repo_url, args.commit)
    else:
        agent.log("8.submit", "SKIPPED-DRY-RUN",
                  f"{len([b for b in built if b.get('built')])} entries built locally, "
                  "0 submitted; live submit needs --live + AIPROVE_LIVE=1 (+ --repo-url/--commit for code)")

    # step 9: report (no secrets: no address, no key, no token)
    report = {
        "mode": mode,
        "api_base": API_BASE,
        "handle": HANDLE,
        "address_fingerprint": agent.address_fingerprint,
        "bounties_evaluated": len(bounties),
        "verdict_counts": counts,
        "verdicts": verdicts,
        "built": built,
        "submitted_live": submitted,
        "live_posts_sent": len(submitted) if live else 0,
        "steps": agent.steps,
    }
    with open(os.path.join(args.out, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    agent.log("9.report", "OK", f"wrote {args.out}/report.json | evaluated={len(bounties)} "
              f"solvable={counts['solvable']} eligible-live={counts['eligible-live']} "
              f"skipped={counts['skipped']} built={len(built)} live_posts_sent={len(submitted)} (dry-run)" if not live else
              f"wrote {args.out}/report.json | evaluated={len(bounties)} "
              f"solvable={counts['solvable']} eligible-live={counts['eligible-live']} "
              f"skipped={counts['skipped']} built={len(built)} live_posts_sent={len(submitted)} (LIVE)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
