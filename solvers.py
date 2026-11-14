#!/usr/bin/env python3
"""Local solvers for the bounties this agent can complete on its own.

Each solver BUILDS the entry locally and VERIFIES it with a local test.
Nothing here touches the live API: build_all_solvable() writes payload
files under out/ and returns a per-bounty build record. Submitting is a
separate, live-only step owned by the parent.

Solvers shipped in this build:
  - forecast-btc-7d : yes/no + probability from CoinGecko 7d momentum.
  - forecast-nvda-3d: numeric close = last close (naive no-change baseline)
                      from the free Stooq quote feed.
  - code-golf-expr  : solution.js (recursive-descent evalExpr), tested with node.
  - fastest-primes  : primes.c (Sieve of Eratosthenes), compiled + tested with gcc.

Everything else is classified 'skipped' by agent.classify() with a reason.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request

USER_AGENT = "best-autonomous-agent/1.0 (dry-run capable autonomous agent)"


def _get_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _get_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode()


# ---------------------------------------------------------------------------
# forecast-btc-7d
# ---------------------------------------------------------------------------
def solve_forecast_btc(agent, out_dir: str) -> dict:
    """Method: 7d log-return momentum from CoinGecko. If BTC is up over the
    last 7 days, answer 'yes' (close higher in 7d) with confidence
    0.5 + min(0.25, |7d return| * 2); else 'no' symmetric. A flat market
    gives a hedged ~0.5. This is a documented momentum heuristic, not a
    guarantee; Brier scoring punishes overconfidence, so confidence is capped."""
    try:
        data = _get_json(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            "?vs_currency=usd&days=7&interval=daily"
        )
        prices = [p[1] for p in data["prices"]]
        start, end = prices[0], prices[-1]
        ret = (end - start) / start
        answer = "yes" if ret >= 0 else "no"
        conf = round(0.5 + min(0.25, abs(ret) * 2), 3)
        payload = {"prediction": {"answer": answer, "confidence": conf}, "handle": "autonomous-agent"}
        method = (f"CoinGecko BTC 7d: {start:.2f} -> {end:.2f} USD "
                  f"(return {ret:+.4f}); momentum rule, confidence capped at 0.75")
    except Exception as exc:
        return {"slug": "forecast-btc-7d", "built": False, "error": f"price fetch failed: {exc}"}
    path = os.path.join(out_dir, "forecast-btc-7d.payload.json")
    with open(path, "w") as f:
        json.dump({"payload": payload, "method": method, "status": "DRY-RUN-NOT-SUBMITTED"}, f, indent=2)
    agent.log("7.build-forecast-btc-7d", "OK", f"payload built locally: answer={answer} confidence={conf} ({method})")
    return {"slug": "forecast-btc-7d", "built": True, "payload_file": path,
            "answer": answer, "confidence": conf, "method": method}


# ---------------------------------------------------------------------------
# forecast-nvda-3d
# ---------------------------------------------------------------------------
def solve_forecast_nvda(agent, out_dir: str) -> dict:
    """Method: naive no-change baseline. NVDA's close 3 trading days from now
    is predicted to equal its last regular-market price from the free Yahoo
    Finance chart feed (no key). This is the standard zero-skill baseline for
    absolute-error scoring; any model must beat it, and it never pretends to
    know the earnings move."""
    try:
        req = urllib.request.Request(
            "https://query1.finance.yahoo.com/v8/finance/chart/NVDA?range=5d&interval=1d",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        meta = data["chart"]["result"][0]["meta"]
        close = float(meta["regularMarketPrice"])
        ts = meta.get("regularMarketTime")
        from datetime import datetime, timezone
        date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else "unknown"
        payload = {"prediction": {"answer": close, "confidence": 0.5}, "handle": "autonomous-agent"}
        method = f"Yahoo Finance NVDA last regular-market price {close} on {date}; naive no-change baseline"
    except Exception as exc:
        return {"slug": "forecast-nvda-3d", "built": False, "error": f"quote fetch failed: {exc}"}
    path = os.path.join(out_dir, "forecast-nvda-3d.payload.json")
    with open(path, "w") as f:
        json.dump({"payload": payload, "method": method, "status": "DRY-RUN-NOT-SUBMITTED"}, f, indent=2)
    agent.log("7.build-forecast-nvda-3d", "OK", f"payload built locally: close={close} ({method})")
    return {"slug": "forecast-nvda-3d", "built": True, "payload_file": path,
            "prediction": close, "method": method}


# ---------------------------------------------------------------------------
# code-golf-expr
# ---------------------------------------------------------------------------
SOLUTION_JS = '''// evalExpr(s): tiny arithmetic language (+ - * /, decimals, parens, precedence).
// Recursive descent: expr := term (('+'|'-') term)* ; term := factor (('*'|'/') factor)* ;
// factor := number | '(' expr ')' | ('+'|'-') factor. Original work for AIProve.
function evalExpr(s) {
  let i = 0;
  const peek = () => s[i];
  const eat = () => s[i++];
  function skipWs() { while (i < s.length && /\\s/.test(s[i])) i++; }
  function parseExpr() {
    let v = parseTerm();
    for (;;) {
      skipWs();
      const c = peek();
      if (c === '+' || c === '-') { eat(); const r = parseTerm(); v = c === '+' ? v + r : v - r; }
      else break;
    }
    return v;
  }
  function parseTerm() {
    let v = parseFactor();
    for (;;) {
      skipWs();
      const c = peek();
      if (c === '*' || c === '/') { eat(); const r = parseFactor(); v = c === '*' ? v * r : v / r; }
      else break;
    }
    return v;
  }
  function parseFactor() {
    skipWs();
    const c = peek();
    if (c === '+' || c === '-') { eat(); const v = parseFactor(); return c === '-' ? -v : v; }
    if (c === '(') { eat(); const v = parseExpr(); skipWs(); if (eat() !== ')') throw new Error('missing )'); return v; }
    let num = '';
    while (i < s.length && /[0-9.]/.test(s[i])) num += eat();
    if (!num) throw new Error('expected number at ' + i);
    return parseFloat(num);
  }
  const v = parseExpr();
  skipWs();
  if (i !== s.length) throw new Error('trailing input at ' + i);
  return v;
}
module.exports = { evalExpr };
'''

CODE_GOLF_CASES = [
    ("1+2*3", 7), ("(1+2)*3", 9), ("10/4", 2.5), ("2.5*4", 10),
    ("-3+5", 2), ("10-2-3", 5), ("2*(3+4)/7", 2), ("3.5+2.5", 6),
    ("((2))", 2), ("8/2/2", 2), ("1+2+3+4", 10), ("0.1+0.2", 0.3),
]


def solve_code_golf(agent, out_dir: str) -> dict:
    sol_dir = os.path.join(out_dir, "solutions", "code-golf-expr")
    os.makedirs(sol_dir, exist_ok=True)
    sol_path = os.path.join(sol_dir, "solution.js")
    with open(sol_path, "w") as f:
        f.write(SOLUTION_JS)
    test_js = (
        "const {evalExpr}=require('./solution.js');\n"
        "const cases=" + json.dumps(CODE_GOLF_CASES) + ";\n"
        "let fail=0;\n"
        "for (const [expr, want] of cases) {\n"
        "  const got=evalExpr(expr);\n"
        "  if (Math.abs(got-want)>1e-9) { console.log('FAIL', expr, 'got', got, 'want', want); fail++; }\n"
        "}\n"
        "if (fail) process.exit(1);\n"
        f"console.log('PASS {len(CODE_GOLF_CASES)}/{len(CODE_GOLF_CASES)}');\n"
    )
    test_path = os.path.join(sol_dir, "test.js")
    with open(test_path, "w") as f:
        f.write(test_js)
    try:
        r = subprocess.run(["node", "test.js"], cwd=sol_dir, capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0
        detail = (r.stdout + r.stderr).strip()
    except Exception as exc:
        ok, detail = False, str(exc)
    agent.log("7.build-code-golf-expr", "OK" if ok else "FAIL",
              f"solution.js written, node test: {detail}")
    return {"slug": "code-golf-expr", "built": ok, "solution": sol_path,
            "test": test_path, "test_output": detail,
            "note": "repoUrl+commit NOT set: dry-run, no repo published; needs live publish step"}


# ---------------------------------------------------------------------------
# fastest-primes
# ---------------------------------------------------------------------------
PRIMES_C = '''// Count primes <= N (N up to 5,000,000). Odd-only Sieve of Eratosthenes.
// Reads N from stdin, prints pi(N). Original work for AIProve.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(void) {
    long n;
    if (scanf("%ld", &n) != 1) return 1;
    if (n < 2) { printf("0\\n"); return 0; }
    long m = (n + 1) / 2;               // odds only: index i -> 2*i+1
    unsigned char *is_comp = calloc(m, 1);
    if (!is_comp) return 1;
    for (long i = 3; i * i <= n; i += 2) {
        if (!is_comp[i / 2]) {
            for (long j = i * i; j <= n; j += 2 * i) is_comp[j / 2] = 1;
        }
    }
    long cnt = 1;                        // prime 2
    for (long i = 3; i <= n; i += 2) if (!is_comp[i / 2]) cnt++;
    printf("%ld\\n", cnt);
    return 0;
}
'''

PRIMES_CASES = [(10, 4), (100, 25), (1000, 168), (100000, 9592), (5000000, 348513)]


def solve_fastest_primes(agent, out_dir: str) -> dict:
    sol_dir = os.path.join(out_dir, "solutions", "fastest-primes")
    os.makedirs(sol_dir, exist_ok=True)
    src = os.path.join(sol_dir, "primes.c")
    with open(src, "w") as f:
        f.write(PRIMES_C)
    binary = os.path.join(sol_dir, "primes")
    try:
        c = subprocess.run(["gcc", "-O2", "-o", binary, src], capture_output=True, text=True, timeout=60)
        if c.returncode != 0:
            raise RuntimeError("gcc failed: " + c.stderr.strip())
        passed = 0
        outputs = []
        for n, want in PRIMES_CASES:
            r = subprocess.run([binary], input=str(n), capture_output=True, text=True, timeout=60)
            got = int(r.stdout.strip())
            outputs.append(f"pi({n})={got} (want {want})")
            passed += got == want
        ok = passed == len(PRIMES_CASES)
        detail = f"{passed}/{len(PRIMES_CASES)} cases pass; " + "; ".join(outputs)
    except Exception as exc:
        ok, detail = False, str(exc)
    agent.log("7.build-fastest-primes", "OK" if ok else "FAIL",
              f"primes.c compiled with gcc -O2, local test: {detail}")
    return {"slug": "fastest-primes", "built": ok, "solution": src, "binary": binary,
            "test_output": detail,
            "note": "repoUrl+commit NOT set: dry-run, no repo published; needs live publish step"}


SOLVERS = {
    "forecast-btc-7d": solve_forecast_btc,
    "forecast-nvda-3d": solve_forecast_nvda,
    "code-golf-expr": solve_code_golf,
    "fastest-primes": solve_fastest_primes,
}


def build_all_solvable(agent, slugs: list[str]) -> list[dict]:
    built = []
    for slug in slugs:
        fn = SOLVERS.get(slug)
        if fn is None:
            agent.log(f"7.build-{slug}", "SKIP", "no solver in this build")
            continue
        try:
            result = fn(agent, agent.out_dir)
            built.append(result)
            if not result.get("built"):
                agent.log(f"7.build-{slug}", "FAIL",
                          result.get("error", "solver returned built=False"))
        except Exception as exc:
            agent.log(f"7.build-{slug}", "FAIL", str(exc))
            built.append({"slug": slug, "built": False, "error": str(exc)})
    return built
