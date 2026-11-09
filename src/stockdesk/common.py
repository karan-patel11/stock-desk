"""Shared helpers for every Stock Desk tool.

Contents: config and paths, the evidence ledger, cached HTTP with retries and
pacing, price download, and the CLI contract (one JSON object on stdout, exit
non-zero on failure). Nothing in here talks to an LLM.
"""
from __future__ import annotations

import argparse
import errno
import json
import math
import os
import re
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from urllib.parse import urlencode, urlparse

import requests

try:  # POSIX file locks keep request pacing correct across separate tool processes
    import fcntl
except ImportError:  # pragma: no cover - Windows: pacing falls back to this process only
    fcntl = None  # type: ignore[assignment]

ERROR_CODES = ("no_data", "source_unavailable", "bad_input", "rate_limited")
EVIDENCE_FIELDS = (
    "id", "run", "tool", "fact", "value", "unit", "period",
    "derived_from", "source", "source_tier", "url", "locator", "retrieved_at",
)
# Source tiers, strongest first. T1 = regulatory filings (SEC), T2 = market data (yfinance), T3/T4 = news
# outlets (see config/source_tiers.json). The rest are weaker than any T tier and never count as support.
SOURCE_TIERS = ("T1", "T2", "T3", "T4", "company_statement", "unrated", "excluded")
_TIER_RANK = {tier: rank for rank, tier in enumerate(SOURCE_TIERS)}
RUN_RE = re.compile(r"^r-\d{8}-\d{2,}$")
EVIDENCE_ID_RE = re.compile(r"^E(\d+)$")
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GENERIC_UA = "stock-desk/0.1 (research tool)"
DEFAULT_CACHE_TTL = 12 * 3600.0

_sleep: Callable[[float], None] = time.sleep
_requests_get: Callable[..., Any] = requests.get
_last_request: dict[str, float] = {}


class ToolError(Exception):
    """A failure that maps to one of the contract error codes."""

    def __init__(self, code: str, detail: str):
        if code not in ERROR_CODES:
            raise ValueError(f"unknown error code {code!r}")
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def log(message: str) -> None:
    """Logs go to stderr so stdout stays a single JSON object."""
    print(message, file=sys.stderr)


# --------------------------------------------------------------------------
# Time and small validators
# --------------------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(moment: datetime | None = None) -> str:
    moment = moment or utc_now()
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_ticker(raw: str) -> str:
    ticker = (raw or "").strip().upper()
    if not TICKER_RE.match(ticker):
        raise ToolError("bad_input", f"invalid ticker {raw!r}")
    return ticker


def parse_date(raw: str) -> str:
    text = (raw or "").strip()
    if not DATE_RE.match(text):
        raise ToolError("bad_input", f"date must be YYYY-MM-DD, got {raw!r}")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ToolError("bad_input", f"invalid date {raw!r}: {exc}") from exc
    return text


def plain(value: Any) -> Any:
    """Convert numpy scalars to Python and refuse NaN/inf."""
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        raise ToolError("no_data", "refusing to record a non-finite number")
    return value


# --------------------------------------------------------------------------
# Config and paths
# --------------------------------------------------------------------------

CONFIG_FILE = "config.env"
HOME_ENV = "STOCKDESK_HOME"
SEC_UA_ENV = "SEC_USER_AGENT"
INIT_HINT = "run `stockdesk init`"


def bundled(*parts: str):
    """A file shipped inside the package under stockdesk/data/ (importlib.resources, never a cwd path)."""
    node = resources.files(__package__).joinpath("data")
    for part in parts:
        node = node.joinpath(part)
    return node


def default_home() -> Path:
    return Path.home() / ".stockdesk"


def read_config_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines (stdlib only). Blank lines and # comments are skipped; one pair of quotes is stripped."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values


def _absolute_home(raw: str, where: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ToolError("bad_input", f"{HOME_ENV} must be an absolute path ({where}), got {raw!r}")
    return path


def home_source() -> tuple[Path, str]:
    """The data home and where it came from, in order of precedence:
    1. the STOCKDESK_HOME environment variable (absolute path),
    2. STOCKDESK_HOME in ~/.stockdesk/config.env,
    3. ~/.stockdesk.
    """
    raw = os.environ.get(HOME_ENV, "").strip()
    if raw:
        return _absolute_home(raw, "environment variable"), "environment variable STOCKDESK_HOME"
    pointer = default_home() / CONFIG_FILE
    raw = read_config_env(pointer).get(HOME_ENV, "").strip()
    if raw:
        return _absolute_home(raw, str(pointer)), f"STOCKDESK_HOME in {pointer}"
    return default_home(), "default"


def home() -> Path:
    return home_source()[0]


def config_files() -> list[Path]:
    """Config files read by env(), first wins: <home>/config.env, then ~/.stockdesk/config.env if different."""
    files = [home() / CONFIG_FILE]
    pointer = default_home() / CONFIG_FILE
    if pointer != files[0]:
        files.append(pointer)
    return files


def env(name: str, default: str | None = None) -> str | None:
    """Environment variable first, then the config files. Empty strings count as unset."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    for path in config_files():
        value = read_config_env(path).get(name, "").strip()
        if value:
            return value
    return default


def evidence_root() -> Path:
    return home() / "evidence"


def cache_root() -> Path:
    return home() / "cache"


def config_path(name: str) -> Path:
    return home() / "config" / name


def load_config(name: str) -> dict[str, Any]:
    """<home>/config/<name> if it exists (a user override, used whole), else the copy bundled in the package.
    The two are never merged. Which one was used goes to stderr."""
    path = config_path(name)
    if path.is_file():
        log(f"config {name}: using override {path}")
    else:
        path = bundled("config", name)
        if not path.is_file():
            raise ToolError("no_data", f"missing config file config/{name}")
        log(f"config {name}: using bundled default")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError("bad_input", f"config/{name} is not valid JSON: {exc}") from exc


def user_agent(required: bool = False) -> str:
    """SEC calls need a real contact in the UA. Every other host gets a generic UA
    so a personal email is never sent to a service that did not ask for it."""
    if not required:
        return GENERIC_UA
    ua = env(SEC_UA_ENV) or ""
    if not ua:
        raise ToolError("bad_input", f"SEC_USER_AGENT is not set; {INIT_HINT} (SEC fair-access policy needs a contact email)")
    if not sec_user_agent_ok(ua):
        raise ToolError("bad_input", f"SEC_USER_AGENT has no real contact email; {INIT_HINT} (SEC fair-access policy)")
    return ua


EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")


def sec_user_agent_ok(ua: str) -> bool:
    """A contact email is present and it is not the documented placeholder. Never filled in by default."""
    lowered = ua.lower()
    return bool(EMAIL_RE.search(ua)) and "your-email" not in lowered and "example.com" not in lowered


# --------------------------------------------------------------------------
# Atomic files
# --------------------------------------------------------------------------

def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


# --------------------------------------------------------------------------
# Runs and the evidence ledger
# --------------------------------------------------------------------------

def new_run_id(now: datetime | None = None) -> str:
    """Allocate r-YYYYMMDD-NN. mkdir is atomic, so concurrent starts never collide."""
    day = (now or utc_now()).strftime("%Y%m%d")
    root = evidence_root()
    root.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        run_id = f"r-{day}-{number:02d}"
        try:
            (root / run_id).mkdir()
            return run_id
        except FileExistsError:
            number += 1


def set_current_run(run_id: str) -> None:
    write_atomic(evidence_root() / "current_run.txt", run_id + "\n")


def resolve_run(arg: str | None) -> str:
    run_id = (arg or "").strip()
    if not run_id:
        pointer = evidence_root() / "current_run.txt"
        if pointer.is_file():
            run_id = pointer.read_text(encoding="utf-8").strip()
    if not run_id:
        raise ToolError("bad_input", "no run: pass --run or start one with round.py start TICKER")
    if not RUN_RE.match(run_id):
        raise ToolError("bad_input", f"malformed run id {run_id!r}")
    if not (evidence_root() / run_id).is_dir():
        raise ToolError("bad_input", f"run {run_id} not found under evidence/")
    return run_id


def _next_candidate(run_dir: Path) -> int:
    numbers = []
    for path in run_dir.glob("E*.json"):
        match = re.fullmatch(r"E(\d+)\.json", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def write_evidence(
    run: str,
    *,
    tool: str,
    fact: str,
    value: Any,
    unit: str,
    period: str,
    source: str,
    url: str,
    locator: str,
    derived_from: Iterable[str] | None = None,
    retrieved_at: str | None = None,
    source_tier: str | None = None,
) -> dict[str, Any]:
    """Write one entry with the next free sequential ID.

    source_tier is required for a primary entry. A derived entry (derived_from given) always takes the
    WEAKEST tier among its inputs, whatever the caller passes, so a derived figure never looks stronger
    than what it was computed from. An input with no tier (an old ledger) counts as unrated.

    IDs are claimed with os.link (fails if the target exists), so analysts running
    tools at the same moment never overwrite each other and never read a half-written file.
    """
    run_dir = evidence_root() / run
    if not run_dir.is_dir():
        raise ToolError("bad_input", f"run {run} not found under evidence/")
    value = plain(value)
    parents = list(derived_from or [])
    if parents:
        tiers = []
        for parent in parents:
            parent_entry = read_evidence(run, parent)
            if parent_entry is None:
                raise ToolError("bad_input", f"derived_from {parent} not found in run {run}")
            tiers.append(parent_entry.get("source_tier") or "unrated")
        source_tier = weakest_tier(tiers)
    elif source_tier not in _TIER_RANK:
        raise ToolError("bad_input", f"source_tier must be one of {', '.join(SOURCE_TIERS)}, got {source_tier!r}")
    number = _next_candidate(run_dir)
    while True:
        evidence_id = f"E{number}"
        entry = {
            "id": evidence_id,
            "run": run,
            "tool": tool,
            "fact": fact,
            "value": value,
            "unit": unit,
            "period": period,
            "derived_from": parents,
            "source": source,
            "source_tier": source_tier,
            "url": url,
            "locator": locator,
            "retrieved_at": retrieved_at or utc_iso(),
        }
        payload = json.dumps(entry, indent=2) + "\n"
        fd, tmp = tempfile.mkstemp(dir=run_dir, prefix=".tmp-E", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        target = run_dir / f"{evidence_id}.json"
        try:
            os.link(tmp, target)
        except FileExistsError:
            number = max(number + 1, _next_candidate(run_dir))
            continue
        except OSError as exc:
            if exc.errno not in (errno.EPERM, errno.ENOTSUP, errno.EXDEV, errno.EMLINK):
                raise
            # Filesystem without hard links: fall back to exclusive create.
            try:
                fd2 = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                number = max(number + 1, _next_candidate(run_dir))
                continue
            with os.fdopen(fd2, "w", encoding="utf-8") as handle:
                handle.write(payload)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        return entry


def weakest_tier(tiers: Iterable[str]) -> str:
    """The weakest of the given tiers (T1 > T2 > T3 > T4 > the rest). Unknown values count as unrated."""
    ranked = [tier if tier in _TIER_RANK else "unrated" for tier in tiers]
    if not ranked:
        raise ToolError("bad_input", "weakest_tier needs at least one tier")
    return max(ranked, key=_TIER_RANK.__getitem__)


def read_evidence(run: str, evidence_id: str) -> dict[str, Any] | None:
    if not EVIDENCE_ID_RE.match(evidence_id or ""):
        return None
    path = evidence_root() / run / f"{evidence_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_evidence(run: str) -> list[dict[str, Any]]:
    run_dir = evidence_root() / run
    entries = []
    for path in run_dir.glob("E*.json"):
        match = re.fullmatch(r"E(\d+)\.json", path.name)
        if match:
            entries.append((int(match.group(1)), json.loads(path.read_text(encoding="utf-8"))))
    return [entry for _, entry in sorted(entries, key=lambda pair: pair[0])]


# --------------------------------------------------------------------------
# Verification log: evidence/<run>/verifications.jsonl (append-only; entries are never edited)
# --------------------------------------------------------------------------

VERIFY_RESULTS = ("PASS", "FAIL", "WITHDRAWN")
VERIFICATIONS_FILE = "verifications.jsonl"
ADVICE_ID = "ADVICE"  # verify.py's advice-word scan; logged here but never part of the citation pass rate


def _log_id_ok(log_id: str) -> bool:
    return log_id == ADVICE_ID or bool(EVIDENCE_ID_RE.match(log_id or ""))


def append_verification(run: str, evidence_id: str, claimed: Any, result: str, detail: str) -> dict[str, Any]:
    """Append one check to the run's log. One write of one line, under an exclusive lock, then fsync."""
    if result not in VERIFY_RESULTS:
        raise ToolError("bad_input", f"result must be one of {VERIFY_RESULTS}")
    if not _log_id_ok(evidence_id):
        raise ToolError("bad_input", f"not an evidence ID: {evidence_id!r}")
    run_dir = evidence_root() / run
    if not run_dir.is_dir():
        raise ToolError("bad_input", f"run {run} not found under evidence/")
    record = {"id": evidence_id, "claimed": plain(claimed), "result": result, "detail": detail,
              "checked_at": utc_iso()}
    line = (json.dumps(record, sort_keys=False) + "\n").encode("utf-8")
    fd = os.open(run_dir / VERIFICATIONS_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line)
        os.fsync(fd)
    finally:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    return record


def read_verifications(run: str) -> list[dict[str, Any]]:
    """Every check in log order. A torn or unreadable line is an error, not skipped silently."""
    path = evidence_root() / run / VERIFICATIONS_FILE
    if not path.is_file():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ToolError("source_unavailable", f"{VERIFICATIONS_FILE} line {number} is not JSON") from exc
        if record.get("result") not in VERIFY_RESULTS or not _log_id_ok(str(record.get("id", ""))):
            raise ToolError("source_unavailable", f"{VERIFICATIONS_FILE} line {number} has no valid id/result")
        records.append(record)
    return records


def latest_verifications(run: str) -> dict[str, dict[str, Any]]:
    """The latest record per evidence ID (later lines win)."""
    latest: dict[str, dict[str, Any]] = {}
    for record in read_verifications(run):
        latest[record["id"]] = record
    return latest


def _id_number(evidence_id: str) -> int:
    match = EVIDENCE_ID_RE.match(evidence_id)
    return int(match.group(1)) if match else 0


def citation_summary(run: str) -> dict[str, Any]:
    """Citation pass rate: among IDs with at least one check, minus those whose latest result is WITHDRAWN,
    the share whose latest result is PASS. An uncorrected failure is an ID whose latest result is FAIL;
    a FAIL followed by a PASS or WITHDRAWN counts as corrected."""
    latest = {i: r for i, r in latest_verifications(run).items() if i != ADVICE_ID}
    ever_failed = {r["id"] for r in read_verifications(run) if r["result"] == "FAIL" and r["id"] != ADVICE_ID}
    order = sorted(latest, key=_id_number)
    counted = [i for i in order if latest[i]["result"] != "WITHDRAWN"]
    passed = [i for i in counted if latest[i]["result"] == "PASS"]
    uncorrected = [i for i in counted if latest[i]["result"] == "FAIL"]
    return {
        "checked": len(counted), "passed": len(passed), "display": f"{len(passed)}/{len(counted)}",
        "uncorrected": uncorrected,
        "corrected": [i for i in order if i in ever_failed and latest[i]["result"] != "FAIL"],
        "withdrawn": [i for i in order if latest[i]["result"] == "WITHDRAWN"],
        "all_pass": bool(counted) and len(passed) == len(counted),
    }


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

def cache_ttl() -> float:
    raw = env("STOCKDESK_CACHE_TTL")
    try:
        return float(raw) if raw else DEFAULT_CACHE_TTL
    except ValueError:
        return DEFAULT_CACHE_TTL


def _cache_file(key: str) -> Path:
    return cache_root() / f"{sha256(key.encode('utf-8')).hexdigest()[:40]}.json"


def cache_get(key: str, ttl: float | None = None) -> dict[str, Any] | None:
    path = _cache_file(key)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.strptime(record["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, KeyError, json.JSONDecodeError):
        return None
    limit = cache_ttl() if ttl is None else ttl
    if (utc_now() - fetched).total_seconds() > limit:
        return None
    return record


def cache_put(key: str, value: Any) -> str:
    fetched_at = utc_iso()
    write_atomic(_cache_file(key), json.dumps({"key": key, "fetched_at": fetched_at, "value": value}))
    return fetched_at


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

@dataclass
class HttpResult:
    text: str
    fetched_at: str
    from_cache: bool
    url: str


def _pace(host: str, interval: float) -> None:
    """Wait until `interval` seconds have passed since the last request to `host`.

    The last request time is kept in cache/pace/<host> under a file lock, so two tool processes started
    back to back (for example two news.py calls) are spaced too, not only requests inside one process.
    """
    if interval <= 0:
        return
    pace_dir = cache_root() / "pace"
    try:
        pace_dir.mkdir(parents=True, exist_ok=True)
        handle = open(pace_dir / re.sub(r"[^A-Za-z0-9.\-]", "_", host), "a+", encoding="utf-8")
    except OSError:
        handle = None
    if handle is None or fcntl is None:
        if handle is not None:
            handle.close()
        last = _last_request.get(host)
        if last is not None:
            wait = interval - (time.time() - last)
            if wait > 0:
                _sleep(wait)
        _last_request[host] = time.time()
        return
    with handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            try:
                last = float(handle.read().strip() or "nan")
            except ValueError:
                last = math.nan
            in_process = _last_request.get(host)
            if in_process is not None and not (last >= in_process):
                last = in_process
            if math.isfinite(last):
                wait = interval - (time.time() - last)
                if wait > 0:
                    _sleep(min(wait, interval))
            now = time.time()
            _last_request[host] = now
            handle.seek(0)
            handle.truncate()
            handle.write(repr(now))
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def http_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    sec: bool = False,
    ttl: float | None = None,
    min_interval: float = 0.0,
    attempts: int = 3,
    timeout: float = 30.0,
    rate_limit_wait: float = 10.0,
    retry_rate_limited: bool = True,
    validate: Callable[[str], None] | None = None,
) -> HttpResult:
    """GET with disk cache, host pacing and retries. Fails closed: no stale fallback.

    `validate` runs on the body before it is cached, so a 200 that actually carries an
    error message (GDELT does this) is never cached.
    With retry_rate_limited=False an HTTP 429 (or a body the validator flags as a rate limit) fails at once
    with rate_limited: GDELT restarts its block on every refused request, so retrying only makes it longer.
    """
    full_url = url
    if params:
        full_url = f"{url}?{urlencode(sorted((k, str(v)) for k, v in params.items()))}"
    key = f"GET {full_url}"
    cached = cache_get(key, ttl)
    if cached is not None:
        return HttpResult(cached["value"], cached["fetched_at"], True, full_url)

    headers = {"User-Agent": user_agent(required=sec), "Accept-Encoding": "gzip, deflate"}
    host = urlparse(full_url).netloc
    last_problem = "no attempt made"
    for attempt in range(1, attempts + 1):
        _pace(host, min_interval)
        try:
            response = _requests_get(full_url, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            last_problem = f"network error: {type(exc).__name__}"
            if attempt < attempts:
                _sleep(1.5 ** attempt)
                continue
            raise ToolError("source_unavailable", f"{host}: {last_problem}") from exc
        status = response.status_code
        if status == 200:
            text = response.text
            if validate is not None:
                try:
                    validate(text)
                except ToolError as ve:
                    if ve.code == "rate_limited":
                        last_problem = f"body indicates rate limit: {ve.detail}"
                        if not retry_rate_limited:
                            raise ToolError("rate_limited", f"{host}: {ve.detail}; not retried") from ve
                        if attempt < attempts:
                            # A rejected request seems to restart GDELT's penalty window, so back off linearly.
                            _sleep(rate_limit_wait * attempt)
                            continue
                        raise ToolError("rate_limited", f"{host}: still rate limited after {attempts} attempts") from ve
                    raise
            fetched_at = cache_put(key, text)
            return HttpResult(text, fetched_at, False, full_url)
        if status == 404:
            raise ToolError("no_data", f"{host}: not found (404) for {full_url}")
        if status == 429:
            last_problem = "429 too many requests"
            if not retry_rate_limited:
                raise ToolError("rate_limited", f"{host}: HTTP 429 too many requests; not retried")
            if attempt < attempts:
                retry_after = response.headers.get("Retry-After", "")
                try:
                    wait = min(float(retry_after), 60.0)
                except ValueError:
                    wait = rate_limit_wait
                _sleep(wait)
                continue
            raise ToolError("rate_limited", f"{host}: still rate limited after {attempts} attempts")
        if status >= 500:
            last_problem = f"server error {status}"
            if attempt < attempts:
                _sleep(1.5 ** attempt)
                continue
            raise ToolError("source_unavailable", f"{host}: {last_problem}")
        if status == 403 and sec:
            raise ToolError("source_unavailable", f"{host}: 403 forbidden; check SEC_USER_AGENT")
        raise ToolError("source_unavailable", f"{host}: unexpected HTTP {status}")
    raise ToolError("source_unavailable", f"{host}: {last_problem}")


# --------------------------------------------------------------------------
# Prices (unofficial Yahoo access via yfinance; disclosed in the README)
# --------------------------------------------------------------------------

PRICE_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


def fetch_prices(
    ticker: str,
    *,
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
    auto_adjust: bool = False,
    ttl: float | None = None,
):
    """Daily bars as a DataFrame indexed by 'YYYY-MM-DD' strings, plus retrieved_at.

    auto_adjust=False gives the prices people actually see quoted. Use True only for
    total-return comparisons (precedent.py).
    """
    import pandas as pd

    if not period and not start:
        raise ToolError("bad_input", "fetch_prices needs period or start")
    key = f"prices|{ticker}|{period}|{start}|{end}|{auto_adjust}"
    cached = cache_get(key, ttl)
    if cached is not None:
        frame = pd.DataFrame(cached["value"]).set_index("date")
        return frame, cached["fetched_at"]
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ToolError("source_unavailable", "yfinance is not installed (pip install -r requirements.txt)") from exc
    kwargs: dict[str, Any] = {"auto_adjust": auto_adjust, "actions": False}
    if period:
        kwargs["period"] = period
    else:
        kwargs["start"] = start
        if end:
            kwargs["end"] = end
    try:
        raw = yf.Ticker(ticker).history(**kwargs)
    except Exception as exc:  # yfinance raises assorted exception types
        name = type(exc).__name__
        if "RateLimit" in name or "Too Many Requests" in str(exc):
            raise ToolError("rate_limited", "Yahoo rate limit; wait and retry, or use cached data") from exc
        raise ToolError("source_unavailable", f"yfinance failed: {name}") from exc
    if raw is None or raw.empty:
        raise ToolError("no_data", f"no daily price data returned for {ticker}")
    frame = raw[list(PRICE_COLUMNS)].copy()
    frame.index = [stamp.strftime("%Y-%m-%d") for stamp in frame.index]
    frame.index.name = "date"
    frame = frame.dropna(subset=["Close"]).sort_index()
    if frame.empty:
        raise ToolError("no_data", f"no usable daily price data for {ticker}")
    records = frame.reset_index().to_dict("records")
    fetched_at = cache_put(key, records)
    return frame, fetched_at


# --------------------------------------------------------------------------
# CLI contract
# --------------------------------------------------------------------------

class ContractParser(argparse.ArgumentParser):
    """argparse that reports usage problems as contract errors instead of exit code 2."""

    def error(self, message: str):  # type: ignore[override]
        raise ToolError("bad_input", message)

    def exit(self, status: int = 0, message: str | None = None):  # type: ignore[override]
        if status:
            raise ToolError("bad_input", (message or "invalid arguments").strip())
        raise SystemExit(0)


def add_run_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run", default=None, help="run id (default: current run from round.py)")


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "item"):
        return obj.item()
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


def emit_ok(run: str | None, evidence: Sequence[str], data: dict[str, Any]) -> None:
    payload = {"ok": True, "run": run, "evidence": list(evidence), "data": data}
    sys.stdout.write(json.dumps(payload, default=_json_default) + "\n")
    sys.stdout.flush()


def emit_error(code: str, detail: str) -> None:
    sys.stdout.write(json.dumps({"ok": False, "error": code, "detail": detail}) + "\n")
    sys.stdout.flush()


def run_cli(func: Callable[[Sequence[str]], tuple[str | None, list[str], dict[str, Any]]],
            argv: Sequence[str] | None = None) -> int:
    """Run a tool's main(argv) -> (run, evidence_ids, data) under the CLI contract."""
    try:
        run, evidence, data = func(list(sys.argv[1:] if argv is None else argv))
    except ToolError as exc:
        emit_error(exc.code, exc.detail)
        return 1
    except Exception as exc:  # never return partial data as if complete
        log(traceback.format_exc())
        emit_error("source_unavailable", f"internal error: {type(exc).__name__}: {exc}")
        return 1
    emit_ok(run, evidence, data)
    return 0
