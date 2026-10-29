# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Transcript clean-up, event splitting and due-date words (English and Afrikaans), without a model."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------- normalise
FILLERS = re.compile(r"\b(?:uh+|um+|erm|ah+|you know|like i said|ag|nou ja|sommer)\b[,]?\s*", re.I)
UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
         "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
NUMWORD = r"(?:%s)" % "|".join(list(UNITS) + list(TENS) + list(SCALES) + ["and"])
NUMRUN = re.compile(rf"\b(?:{NUMWORD})(?:[\s-]+(?:{NUMWORD}))*\b", re.I)
UNIT_WORDS = [(re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(?:hectares?|hektaar)\b", re.I), r"\1 ha")]


def _words_to_int(words: list[str]) -> int | None:
    total, current, seen = 0, 0, False
    for w in words:
        w = w.lower()
        if w == "and":
            continue
        if w in UNITS:
            current += UNITS[w]
        elif w in TENS:
            current += TENS[w]
        elif w == "hundred":
            current = max(current, 1) * 100
        elif w in SCALES:
            total += max(current, 1) * SCALES[w]
            current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


# "no." needs its dot: "No one fed the dogs" is not unit number 1
NUMBER_ONE = re.compile(r"\b(number|nommer|no\.|nr\.?)\s+(?:one|een)\b", re.I)


def normalise(text: str) -> str:
    text = FILLERS.sub("", text or "")

    def repl(m: re.Match) -> str:
        words = re.split(r"[\s-]+", m.group(0))
        if all(w.lower() == "and" for w in words):
            return m.group(0)
        # "one of the ewes" / "and" alone stay words; only multi-word or scale numbers become digits
        if len(words) == 1 and words[0].lower() in ("one", "a"):
            return m.group(0)
        lead = "and " if words[0].lower() == "and" else ""
        n = _words_to_int(words[1:] if lead else words)
        return f"{lead}{n}" if n is not None else m.group(0)

    text = NUMBER_ONE.sub(lambda m: f"{m.group(1)} 1", text)  # "number one" names a thing: John Deere #1
    text = NUMRUN.sub(repl, text)
    for pat, rep in UNIT_WORDS:
        text = pat.sub(rep, text)
    return re.sub(r"\s{2,}", " ", text).strip()


# ---------------------------------------------------------------- split into events
SENT = re.compile(r"(?<=[.!?;])\s+|\n+")
JOIN = re.compile(r",?\s+(?:and|but|also|plus|then|while|en|maar|ook|toe|terwyl)\s+"
                  r"(?=(?:the|my|our|a|an|his|her|their|we|i|die|ons|'n|hulle|ek|jy|sy|hy)\b)", re.I)


def split_events(text: str, min_words: int = 3) -> list[str]:
    out: list[str] = []
    for sent in SENT.split(text.strip()):
        sent = sent.strip()
        if not sent:
            continue
        parts = JOIN.split(sent)
        merged: list[str] = []
        for p in parts:
            p = p.strip(" ,")
            if merged and len(p.split()) < min_words:
                merged[-1] = f"{merged[-1]} {p}"
            elif p:
                merged.append(p)
        if len(merged) > 1 and len(merged[0].split()) < min_words:
            merged[1] = f"{merged[0]} {merged[1]}"
            merged = merged[1:]
        out.extend(merged)
    return out or ([text.strip()] if text.strip() else [])


# ---------------------------------------------------------------- number ranges ("fields 704 to 708")
RANGE = re.compile(r"\b(\d{1,6})\s*(?:to|tot|until|through|thru|-|–|—)\s*(\d{1,6})\b", re.I)


def expand_ranges(event: str, known: set[str], max_span: int = 40) -> list[str]:
    """'Planted field south 704 to 708' -> one event per numbered thing the owner has (704, 705 ... 708), so each
    field gets its own note and progress. Only when both ends are numbers in the owner's node titles."""
    m = RANGE.search(event)
    if not m:
        return [event]
    a, b = m.group(1), m.group(2)
    lo, hi = int(a), int(b)
    if a not in known or b not in known or not (0 < hi - lo <= max_span):
        return [event]
    width = len(a) if a.startswith("0") else 0
    out = []
    for n in range(lo, hi + 1):
        num = str(n).zfill(width)
        if num in known:
            out.append(event[:m.start()] + num + event[m.end():])
    return out or [event]


# ---------------------------------------------------------------- due dates
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            "maandag": 0, "dinsdag": 1, "woensdag": 2, "donderdag": 3, "vrydag": 4, "saterdag": 5, "sondag": 6}


# "more" is Afrikaans môre (tomorrow) only in an Afrikaans sentence; in English it is "need more diesel"
AFRIKAANS = re.compile(r"\b(die|het|moet|nie|ons|ek|vir|van|sal|om|dis|asseblief)\b", re.I)


def parse_due(text: str, ref: datetime, tz: str = "Africa/Johannesburg") -> str | None:
    """Explicit due words only (router rule 5). Returns ISO-8601 UTC or None."""
    t = (text or "").lower()
    local = ref.astimezone(ZoneInfo(tz))
    hour = 9 if re.search(r"\b(morning|oggend)\b", t) else 17
    day = None
    if re.search(r"\b(day after tomorrow|oormôre|oormore)\b", t):
        day = local + timedelta(days=2)
    elif re.search(r"\b(tomorrow|môre)\b", t) or (re.search(r"\bmore\b", t) and AFRIKAANS.search(t)):
        day = local + timedelta(days=1)
    elif re.search(r"\b(today|tonight|vandag|vanaand|asap|immediately|dadelik|nou dadelik)\b", t):
        day = local
        hour = 20 if re.search(r"\b(tonight|vanaand)\b", t) else max(local.hour + 2, 17) if local.hour < 22 else 23
        hour = min(hour, 23)
    elif m := re.search(r"\bin (\d+) (days?|dae)\b", t):
        day = local + timedelta(days=int(m.group(1)))
    elif re.search(r"\b(next week|volgende week)\b", t):
        day = local + timedelta(days=7 - local.weekday())
        hour = 9
    elif re.search(r"\b(end of (the )?week|einde van die week)\b", t):
        day = local + timedelta(days=(4 - local.weekday()) % 7)
    else:
        for name, wd in WEEKDAYS.items():
            if re.search(rf"\b{name}\b", t):
                delta = (wd - local.weekday()) % 7 or 7
                day = local + timedelta(days=delta)
                break
    if day is None:
        return None
    due = day.replace(hour=hour, minute=0, second=0, microsecond=0)
    return due.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")


# ---------------------------------------------------------------- problem words (rules router, severity)
# "down" only as a state ("pump is down", "broke down"), never "sit down"; "brand" (Afrikaans fire) never "brand new"
CRITICAL = re.compile(r"\b(burst|broke(?:n)?|collapsed?|fire|smoke|bleeding|(?:is|are|was|were|went|goes|gone|broke|been)\s+down|dead|died|dying|stolen|flood(?:ing)?|"
                      r"leaking badly|no water|no power|unsafe|injured badly|can'?t walk|stopped|"
                      r"gebars|gebreek|dood|brand(?!\s+new)|gesteel|geen water|geen krag|lek baie erg|erg)\b", re.I)
WARNING = re.compile(r"\b(leak(?:s|ing)?|lek|injur(?:ed|y)|lame|limp(?:ing)?|sick|siek|low|laag|worn|noise|noisy|"
                     r"overdue|late|missing|weg|loose|los|crack(?:ed)?|fault|faulty|problem|probleem|broken)\b", re.I)
DONE = re.compile(r"\b(finished|completed|done|fixed|repaired|klaar|voltooi|reggemaak)\b", re.I)
TODO = re.compile(r"\b(need(?:s)? to|must|should|have to|remember to|don'?t forget|order|call|phone|book|buy|"
                  r"needs? (?:a |an |new )?(?:chang|fix|replac|repair|servic|check|clean|grease|weld)\w*|"
                  r"moet|bel|bestel|koop|onthou om)\b", re.I)
CATEGORY = [(re.compile(r"\b(leak|lek)", re.I), "leak"),
            (re.compile(r"\b(injur|broke .*leg|lame|sick|siek|bleed|vet|dead|dood)", re.I), "health"),
            (re.compile(r"\b(stolen|gesteel|break-?in|fence cut)", re.I), "security"),
            (re.compile(r"\b(fire|brand|unsafe|smoke)", re.I), "safety"),
            (re.compile(r"\b(missing|weg|lost)", re.I), "loss"),
            (re.compile(r"\b(burst|broke|broken|stopped|fault|gebars|gebreek)", re.I), "breakdown")]


def severity_of(text: str) -> str | None:
    if CRITICAL.search(text):
        return "critical"
    if WARNING.search(text):
        return "warning"
    return None


def category_of(text: str) -> str:
    for pat, cat in CATEGORY:
        if pat.search(text):
            return cat
    return "other"


# POPIA s26-33: a note that names a person together with health, disciplinary, union or religious details. Those are
# not filed on a branch everyone sees without an owner deciding (pipeline: held in the Inbox for the owners). Animals
# and machines get sick and break too: a note about them is not about a person.
SENSITIVE = {
    "health": re.compile(r"\b(sick|siek|ill|injur\w*|hurt|beseer\w*|hospital\w*|hospitaal|doctor|dokter|clinic|kliniek|"
                         r"hiv|aids|tb|tuberculosis|pregnan\w*|swanger|diabet\w*|medication|medisyne|sick ?leave|"
                         r"siekverlof|surgery|operasie)\b", re.I),
    "disciplinary": re.compile(r"\b(disciplin\w*|dissipline\w*|warning letter|written warning|final warning|dismiss\w*|"
                               r"fired|afgedank|hearing|suspend\w*|geskors\w*|drunk|dronk|theft|stole|steel|gesteel)\b",
                               re.I),
    "union": re.compile(r"\b(union|vakbond)\b", re.I),
    "religion": re.compile(r"\b(church|kerk|mosque|moskee|religio\w*|godsdiens)\b", re.I),
}
NOT_A_PERSON = re.compile(r"\b(ewes?|rams?|sheep|skape|ooie|lambs?|lammers|cows?|cattle|beeste|koeie|calf|calves|kalwers|"
                          r"bulls?|bulle|heifers?|goats?|bokke|pigs?|varke|horses?|perde|dogs?|honde|chickens?|hoenders|"
                          r"tractor|trekker|pump|pomp|engine|enjin|bakkie|truck|vehicle)\b", re.I)


def sensitive_about(event: str, names: list[str]) -> tuple[str, str] | None:
    """(the person's name, the kind of detail) when the note names a person with special personal information."""
    if NOT_A_PERSON.search(event):
        return None
    kind = next((k for k, p in SENSITIVE.items() if p.search(event)), None)
    if kind is None:
        return None
    for n in sorted({x for x in names if x and len(x) >= 3}, key=len, reverse=True):
        if re.search(rf"\b{re.escape(n)}\b", event, re.I):
            return n, kind
    return None
