# Ionity NoteCad - Companion | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Small text helpers that run without any model: tokens, language, style features, redaction."""
from __future__ import annotations

import re
from dataclasses import dataclass

WORD = re.compile(r"[A-Za-zÀ-ÿ'’]+|\d+(?:[.,]\d+)?")
SENT = re.compile(r"[^.!?\n]+[.!?]?")

EN_STOP = set(
    """a an the and or but if then so to of in on at by for with from up down out over under is are was were be been
    being have has had do does did i me my mine we us our you your he him his she her it its they them their this that
    these those there here what which who whom when where why how all any both each few more most other some such no
    not only own same than too very can will just should now am im i'm it's dont don't yes ok okay please thanks thank
    get got go going went make made also about into would could like just really time check need needs today still
    want thing things doing done day week hello hey something anything everything know think tell said say again
    morning evening afternoon tonight low high new old near far""".split()
)
AF_STOP = set(
    """die 'n n en of maar as dan om te van in op by vir met uit is was word het ek my ons jy jou hy sy hom haar dit
    hulle hul hierdie daardie daar hier wat wie wanneer waar hoekom hoe al alle nie ook net baie kan sal moet nou ja
    nee asseblief dankie dis gaan gaan het gehad sou wil weet sê se toe al reeds nog tyd vandag nodig dag week iets weer oggend aand
    middag hou kort lank meer minder naby""".split()
)
# words that are strong language signals on their own
AF_MARKERS = {"die", "nie", "ek", "het", "jy", "ons", "baie", "asseblief", "dankie", "hulle", "wat", "hoe", "dit", "is'n", "'n"}
EN_MARKERS = {"the", "and", "not", "you", "have", "please", "thanks", "what", "how", "it", "is", "of"}

FORMAL = {"regards", "kindly", "sincerely", "therefore", "furthermore", "please", "appreciate", "vriendelike", "groete"}
CASUAL = {"hey", "hi", "yo", "lol", "cool", "nice", "awesome", "yeah", "nah", "ok", "okay", "haha", "boet", "bru", "lekker", "ja", "howzit"}


def tokens(text: str) -> list[str]:
    return [t.lower() for t in WORD.findall(text or "")]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT.findall(text or "") if s.strip()]


def guess_language(text: str) -> str:
    """Return 'af', 'en' or 'mixed' using marker-word counts (good enough to pick the reply language)."""
    toks = tokens(text)
    if not toks:
        return "en"
    af = sum(1 for t in toks if t in AF_MARKERS or t in AF_STOP)
    en = sum(1 for t in toks if t in EN_MARKERS or t in EN_STOP)
    if af == 0 and en == 0:
        return "en"
    if af >= 2 * max(en, 1) or (af > 0 and en == 0):
        return "af"
    if en >= 2 * max(af, 1) or (en > 0 and af == 0):
        return "en"
    return "mixed"


@dataclass
class StyleFeatures:
    words_per_message: float
    words_per_sentence: float
    formality: float  # -1 casual .. +1 formal
    emoji_rate: float  # emojis per message
    bullet_use: float  # 1 if the message uses list markers


EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def style_features(text: str) -> StyleFeatures:
    toks = tokens(text)
    sents = sentences(text) or [text]
    formal = sum(1 for t in toks if t in FORMAL)
    casual = sum(1 for t in toks if t in CASUAL)
    total = formal + casual
    formality = 0.0 if total == 0 else (formal - casual) / total
    bullets = 1.0 if re.search(r"^\s*([-*•]|\d+[.)])\s+", text or "", re.M) else 0.0
    return StyleFeatures(
        words_per_message=float(len(toks)),
        words_per_sentence=len(toks) / max(len(sents), 1),
        formality=formality,
        emoji_rate=float(len(EMOJI.findall(text or ""))),
        bullet_use=bullets,
    )


def content_terms(text: str) -> list[str]:
    """Words worth remembering as owner vocabulary: not stop words, len >= 3, not pure numbers."""
    out = []
    for t in tokens(text):
        if len(t) < 3 or t.isdigit() or t in EN_STOP or t in AF_STOP:
            continue
        out.append(t.strip("'’"))
    return out


def bigrams(terms: list[str]) -> list[str]:
    return [f"{a} {b}" for a, b in zip(terms, terms[1:])]


# ---------------------------------------------------------------- redaction (POPIA)
SA_ID = re.compile(r"\b\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{4}[01]\d{2}\b")
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def redact(text: str) -> str:
    """Mask SA ID numbers and payment card numbers before anything is stored."""
    text = SA_ID.sub("[id-number]", text or "")

    def card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        return "[card-number]" if 13 <= len(digits) <= 19 and _luhn_ok(digits) else m.group(0)

    return CARD.sub(card, text)
