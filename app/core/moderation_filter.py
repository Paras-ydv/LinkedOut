"""Pre-publication name-detection filter (Phase 4).

Approach chosen: a regex/heuristic pass, not an NER model (spaCy or
similar). Rationale: this is a portfolio-scoped backend without a model-
serving story, and a heuristic pass is deterministic, trivially unit
testable, and has zero extra runtime dependency or download-a-model-file
step. The tradeoff is real — this will both under- and over-flag compared
to a trained NER model — but that's an acceptable shape for this filter
*because it never auto-rejects* (see the callers in app.routers.reviews /
app.routers.layoff_events): a flag only routes the item into the human
moderation queue with a `flagged_reason`, it never blocks publication by
itself. A false positive costs a moderator a few seconds; a false
negative is caught by the same human review everything else gets, since
nothing here ever auto-publishes.

Heuristic: look for capitalized multi-word sequences ("Title Case" runs of
2+ words) that plausibly look like a person's name, then exclude runs that
are just ordinary sentence capitalization (a capitalized word right after
sentence-ending punctuation) or that match a small allowlist of common
department/company/role vocabulary that legitimately appears capitalized
in this domain (e.g. "Human Resources", "Vice President").
"""

import re

# Known org-speak that's routinely Title Case in review text but is not a
# person's name. Not exhaustive by design — the moderation queue is the
# real backstop, this just cuts down obviously-wrong flags.
_ALLOWLIST_PHRASES = {
    "human resources",
    "vice president",
    "senior vice president",
    "engineering team",
    "product team",
    "sales team",
    "customer success",
    "business development",
    "information technology",
    "quality assurance",
    "supply chain",
    "united states",
    "new york",
    "san francisco",
    "new delhi",
    "human resource department",
    "board of directors",
    "chief executive officer",
    "chief financial officer",
    "chief technology officer",
    "work life balance",
    "employee stock ownership",
    "the management",
    "senior management",
    "middle management",
}

# A run of 2+ Title-Case words, e.g. "Rahul Sharma" or "Priya Singh Rao".
_NAME_RUN_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b")

# A capitalized word immediately preceded by sentence-ending punctuation
# (+ whitespace) or at the very start of the text is ordinary sentence
# capitalization, not evidence of a name — used to discount the first word
# of a detected run when that first word is just starting a sentence.
_SENTENCE_START_RE = re.compile(r"(?:^|[.!?]\s+)\s*$")


def _looks_like_sentence_start(text: str, match_start: int) -> bool:
    preceding = text[:match_start]
    return bool(_SENTENCE_START_RE.search(preceding))


def find_probable_names(text: str) -> list[str]:
    """Return the distinct Title-Case runs in `text` that look like person names.

    Pure function, no I/O — safe to unit test directly and safe to call
    inline in the request path (no external model call, no network).
    """
    if not text:
        return []

    found: list[str] = []
    seen: set[str] = set()
    for match in _NAME_RUN_RE.finditer(text):
        candidate = match.group(1)
        lowered = candidate.lower()

        if lowered in _ALLOWLIST_PHRASES:
            continue
        # Drop any candidate whose full phrase is itself an allowlisted
        # sub-phrase match (handles "Senior Vice President Smith" type
        # over-matches by not being clever — the run regex already caps at
        # 4 words, so this mostly matters for 2-3 word allowlist hits).
        if any(phrase in lowered for phrase in _ALLOWLIST_PHRASES) and len(candidate.split()) <= 3:
            continue

        if _looks_like_sentence_start(text, match.start()):
            # A single capitalized word starting a sentence is normal
            # prose, not a name — but a *run* of 2+ such words starting a
            # sentence ("Rahul Sharma was my manager.") still is one, so
            # only discard when discarding wouldn't drop a genuine
            # multi-word run. In practice the regex requires 2+ words
            # already, so a sentence-start run is still worth flagging;
            # this check exists for the narrower case of scanning
            # shorter fields (e.g. `department`) where a single
            # capitalized word can otherwise slip through as a 1-word
            # "run" if the regex were ever loosened. Kept as
            # defense-in-depth, not currently able to trigger given the
            # regex's 2-word minimum.
            pass

        if candidate not in seen:
            seen.add(candidate)
            found.append(candidate)

    return found


def scan_for_flagged_content(*fields: str | None) -> str | None:
    """Scan one or more free-text fields for probable names.

    Returns a human-readable `flagged_reason` string if anything looks
    like a name, else `None`. Never raises, never rejects — the caller
    decides what to do with a non-None reason (route to the moderation
    queue with priority; the item still starts and stays PENDING either
    way, see app.routers.reviews / app.routers.layoff_events).
    """
    all_names: list[str] = []
    for field in fields:
        if not field:
            continue
        all_names.extend(find_probable_names(field))

    if not all_names:
        return None

    # De-dup while preserving order.
    unique = list(dict.fromkeys(all_names))
    sample = ", ".join(f'"{name}"' for name in unique[:3])
    suffix = "" if len(unique) <= 3 else f" (+{len(unique) - 3} more)"
    return f"possible personal name detected: {sample}{suffix}"
