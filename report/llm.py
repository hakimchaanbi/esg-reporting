"""
Phase 5b — the narrative writer backends
========================================

WHAT THIS IS FOR

    This is the ONLY place in the project where a language model produces text
    that ends up in the report. Everything else — the scraped figures, the
    mapping, the content index — is mechanical. Keeping the model behind one
    small, swappable interface is what makes that claim checkable: if you want
    to know where the LLM touches the report, it is this file and nothing else.

WHAT THE MODEL IS AND IS NOT ALLOWED TO DO

    Allowed:     choose the sentences, the order, the emphasis, the register.
    Not allowed: emit a single figure.

    The model writes `{{ scope1_total }}` and code substitutes 6,215.78 later
    (CLAUDE.md §3, "non-hallucinable by construction"). This file only enforces
    the rule in the prompt; build_narrative.py enforces it mechanically after
    the fact, which is the half that actually counts.

THE BACKENDS

    gemini  (preferred)  Google Gemini via the google-genai SDK. Chosen because
                         Google AI Studio issues free API keys with no card —
                         which matters for a student project — and because
                         freellm.net, the free-API directory Hakim's supervisor
                         recommended, lists Gemini among its providers.

    stub    (fallback)   Deterministic canned prose, no network, no key. It
                         emits real `{{ tokens }}`, so the substitution and the
                         number-safety checks are exercised end to end without
                         anyone having an API key. The whole pipeline is
                         testable offline.

    rogue   (test only)  Deliberately writes a bare number instead of a token.
                         Exists so tests/test_narrative_safety.py can PROVE the
                         safety check fires, the same way
                         test_validator_catches_fabrication.py proves the
                         mapping validator fires. A guarantee nobody has tried
                         to break is not a guarantee.

WHY models.generate_content AND NOT interactions.create

    The SDK now offers both. `client.interactions.create(...)` is the newer
    surface, but Google's published Python reference documents
    `system_instruction` and `temperature` against `models.generate_content`,
    and this job needs both: a hard system rule about numbers, and a low
    temperature so a report regenerates roughly the same way twice. Verified
    against googleapis.github.io/python-genai on 2026-08-21 rather than
    recalled — CLAUDE.md §12.
"""

from __future__ import annotations

import logging
import os
import pathlib
import random
import re
import time

# The key lives in .env, which is gitignored (§6.1: secrets go in the
# environment, never in a tracked file). Nothing else in the project reads .env,
# so load it here rather than making every caller remember to export the
# variable first. An absent .env is normal — the stub backend needs no key.
try:
    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")
except ImportError:                                      # pragma: no cover
    pass

# Gemini's free tier covers the Flash models; Pro sits behind billing.
#
# ⚠️ THE FREE DAILY QUOTA IS PER MODEL AND IS SMALL. gemini-3.7-flash allows 20
# requests/day, and a full run of three institutions needs 21. Google no longer
# publishes per-model free limits in the docs — read yours at
# https://aistudio.google.com/rate-limit — so the model is settable from the
# environment, because finding a workable one is trial and error and should not
# require a code edit:
#
#     GEMINI_MODEL=gemini-2.5-flash python -m report.build_narrative
#
# Newer models tend to have the tightest allowances; an older Flash or a
# Flash-Lite usually has more room.
DEFAULT_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")

# Low but not zero. Zero makes the prose mechanical and repetitive across the
# eight sections; this keeps it readable while staying close to reproducible.
TEMPERATURE = 0.3

# The free tier is rate-limited per minute, and Flash models return 503 when
# Google is busy — which on a free key is often. A whole report is ~7 calls per
# institution, 21 in total, so both limits are reachable in one run and a bare
# failure would throw away the sections already generated.
MAX_ATTEMPTS = 5
BASE_BACKOFF = 4.0        # seconds; doubles each attempt, plus jitter
PACE_SECONDS = 6.0        # between successful calls: free tier allows ~10/min
# Google states a retryDelay on quota errors. Anything up to this we wait out;
# beyond it the allowance is genuinely gone and the run should stop.
MAX_QUOTA_WAIT = 120      # seconds

# The SDK logs an automatic-function-calling advisory on every generate_content
# call. We pass no tools, so it does not apply, and it buries the real output.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

_RETRYABLE = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED",
              "overloaded", "high demand", "deadline", "timeout")


class WriterError(RuntimeError):
    """Raised when a backend cannot produce text. Never returns empty prose."""


class QuotaExhausted(WriterError):
    """The daily free-tier allowance is gone. Distinct from a WriterError
    because it is not worth retrying and not worth trying the next section
    either — every remaining call would fail the same way. The caller stops the
    whole run on this and keeps what it already has."""


class StubWriter:
    """Canned prose that still exercises the token machinery.

    Deliberately terse and obviously synthetic — nobody should mistake stub
    output for a finished report — but it emits the first few tokens it was
    handed, so substitution, StrictUndefined and the digit scan all run.
    """

    name = "stub"
    needs_key = False

    def write(self, system: str, prompt: str, tokens: list[str]) -> str:
        preamble = ("This section was generated by the offline stub backend, "
                    "so its wording carries no meaning; only the substitution "
                    "path is being exercised.")
        if not tokens:
            return preamble
        # Two things this deliberately avoids, both learned by getting them
        # wrong. Do not wrap the lines: a wrap can split `{{ token }}` across a
        # newline, which Jinja tolerates but a real model would not produce.
        # And do not print the token NAME in the prose: names like
        # `op6_annual_scope_1_ghg_emissions` carry digits, which the number
        # audit then correctly reports as unaccounted-for text.
        lines = [f"A reported value here was {{{{ {t} }}}}." for t in tokens[:4]]
        return preamble + "\n" + "\n".join(lines)


class RogueWriter:
    """A backend that breaks the rule on purpose. Used only by the tests."""

    name = "rogue"
    needs_key = False

    def write(self, system: str, prompt: str, tokens: list[str]) -> str:
        return ("The university reduced its emissions by 42,000 metric tons "
                "last year, a fall of 17 percent.")


class GeminiWriter:
    """Google Gemini through the official google-genai SDK."""

    name = "gemini"
    needs_key = True

    def __init__(self, model: str = DEFAULT_GEMINI_MODEL):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:                       # pragma: no cover
            raise WriterError(
                "google-genai is not installed. Run: pip install google-genai"
            ) from exc

        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise WriterError(
                "No API key. Get a free one at https://aistudio.google.com/apikey "
                "then add it to the project's .env file as:\n"
                "    GEMINI_API_KEY=your-key-here")

        self._genai = genai
        self._types = types
        self._client = genai.Client(api_key=key)
        self.model = model
        self._last_call = 0.0

    def available_models(self) -> list[str]:
        """What this key can actually reach. Used to explain a bad model ID."""
        try:
            return sorted(m.name.removeprefix("models/")
                          for m in self._client.models.list())
        except Exception:                                # pragma: no cover
            return []

    def write(self, system: str, prompt: str, tokens: list[str]) -> str:
        config = self._types.GenerateContentConfig(
            system_instruction=system, temperature=TEMPERATURE)

        # Pace ourselves rather than discovering the per-minute limit by
        # tripping it: a 429 partway through costs more time than the waits.
        gap = time.monotonic() - self._last_call
        if self._last_call and gap < PACE_SECONDS:
            time.sleep(PACE_SECONDS - gap)

        last_error = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.model, contents=prompt, config=config)
                self._last_call = time.monotonic()
                break
            except Exception as exc:
                last_error, message = exc, str(exc)

                # A PER-DAY quota is not a transient rate limit and retrying it
                # is actively harmful: every retry is another request counted
                # against the very allowance that just ran out. The first run
                # burned roughly 28 requests from a 20/day budget discovering
                # this. Fail immediately and let the caller resume tomorrow.
                # ⚠️ A `PerDay` quota error is NOT automatically terminal, and
                # treating it as one cost a whole run. Google returns
                # `retryDelay` alongside it, and on the free tier that delay is
                # often SECONDS — it is throttling the rate at which the daily
                # bucket is drawn down, not reporting the bucket empty. A run
                # stopped at 18 of a 20/day allowance while the response said
                # `retryDelay: 17s`, and two further calls succeeded minutes
                # later. Honour the delay Google actually states: wait it out
                # when it is short, give up only when it is long.
                delay_match = re.search(r"'retryDelay':\s*'(\d+)s'", message)
                stated_delay = int(delay_match.group(1)) if delay_match else None
                if stated_delay is not None and stated_delay <= MAX_QUOTA_WAIT \
                        and attempt < MAX_ATTEMPTS:
                    wait = stated_delay + 2
                    print(f"       daily-quota throttle, Google says retry in "
                          f"{stated_delay}s — waiting "
                          f"(attempt {attempt}/{MAX_ATTEMPTS})")
                    time.sleep(wait)
                    continue

                if "PerDay" in message or "per day" in message.lower():
                    # KEEP THE RAW ERROR. An earlier version of this raised a
                    # hand-written message only, and the logs then could not
                    # answer why a run stopped at 18 generations when the limit
                    # is 20 and two more succeeded minutes later. Google's
                    # response carries quotaId, quotaValue and retryDelay —
                    # exactly the fields needed — and they were being discarded.
                    # An error handler that destroys the evidence is worse than
                    # no handler.
                    raise QuotaExhausted(
                        f"Daily free-tier quota exhausted for {self.model!r}.\n"
                        "  Options: wait for the reset (midnight Pacific), set "
                        "GEMINI_MODEL to a different model (the quota is per "
                        "model, so another one has its own allowance), or check "
                        "your real limits at "
                        "https://aistudio.google.com/rate-limit\n"
                        "  Sections already written are cached — re-running "
                        f"resumes rather than starting over.\n"
                        f"  Raw response: {message}") from exc

                if "not found" in message.lower() or "404" in message:
                    seen = self.available_models()
                    flash = [m for m in seen if "flash" in m]
                    raise WriterError(
                        f"Model {self.model!r} was rejected. Models this key "
                        "can see:\n  " + "\n  ".join(flash or seen[:20]) +
                        "\n\nSet a working one in report/llm.py "
                        "(DEFAULT_GEMINI_MODEL).") from exc

                if not any(s in message for s in _RETRYABLE) \
                        or attempt == MAX_ATTEMPTS:
                    raise WriterError(f"Gemini call failed: {exc}") from exc

                wait = BASE_BACKOFF * (2 ** (attempt - 1)) + random.uniform(0, 2)
                reason = "rate limit" if "429" in message else "model busy"
                print(f"       {reason}, retrying in {wait:.0f}s "
                      f"(attempt {attempt}/{MAX_ATTEMPTS})")
                time.sleep(wait)
        else:                                            # pragma: no cover
            raise WriterError(f"Gemini call failed: {last_error}")

        text = (response.text or "").strip()
        if not text:
            raise WriterError(
                "Gemini returned empty text. This usually means the response "
                "was blocked by a safety filter or the token budget was hit.")
        return text


BACKENDS = {"gemini": GeminiWriter, "stub": StubWriter, "rogue": RogueWriter}


def get_writer(name: str | None = None):
    """Pick a backend, announcing the choice.

    With no argument: Gemini when a key is present, stub otherwise. A missing
    key is a normal state here, not an error — the pipeline is designed to run
    and be tested without one.
    """
    if name:
        if name not in BACKENDS:
            raise WriterError(f"Unknown backend {name!r}. "
                              f"Choose from {sorted(BACKENDS)}.")
        writer = BACKENDS[name]()
        print(f"[llm] backend: {writer.name}")
        return writer

    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        writer = GeminiWriter()
        print(f"[llm] backend: gemini ({writer.model})")
        return writer

    print("[llm] backend: stub — no GEMINI_API_KEY set, so no real prose will "
          "be written.\n"
          "      Get a free key at https://aistudio.google.com/apikey and put "
          "it in .env to generate for real.")
    return StubWriter()
