# Ionity Business Mind Map (IBMM) - Companion | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""How the companion learns its owner from what they say, write and correct."""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

from .llm import LLM, parse_json
from .store import Store
from .textutil import content_terms, guess_language, redact, style_features, tokens

# Reply-style dimensions the companion adapts. Each option is a Beta-Bernoulli arm.
DIMS: dict[str, list[str]] = {
    "length": ["short", "medium", "detailed"],
    "tone": ["casual", "neutral", "formal"],
    "format": ["prose", "bullets"],
    "proactivity": ["answer_only", "suggest_next"],
}
DECAY = 0.985  # old evidence fades so the companion follows the owner as they change
EXPLICIT_WIN, EXPLICIT_LOSS = 6.0, 3.0
KEY_OK = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+){1,3}$")

# ---------------------------------------------------------------- explicit style instructions (en + af)
EXPLICIT_STYLE: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\b(keep it (short|brief)|shorter|too long|be brief|less detail|hou dit kort|korter|te lank|long explanations?|lang verduidelikings?)\b", re.I), "length", "short"),
    (re.compile(r"\b(just (give me )?the steps|step by step list|net die stappe)\b", re.I), "format", "bullets"),
    (re.compile(r"\b(more detail|explain more|too short|in depth|elaborate|meer detail|verduidelik meer|te kort)\b", re.I), "length", "detailed"),
    (re.compile(r"\b(no bullets?|no lists?|in sentences|plain text|geen lys(te)?|sonder punte)\b", re.I), "format", "prose"),
    (re.compile(r"\b(bullet points?|bullets|as a list|use a list|in punte|as 'n lys)\b", re.I), "format", "bullets"),
    (re.compile(r"\b(be (more )?formal|be professional|more professional|formeel)\b", re.I), "tone", "formal"),
    (re.compile(r"\b(less formal|be casual|relax|chill|informeel|ontspan)\b", re.I), "tone", "casual"),
    (re.compile(r"\b(just answer|don'?t suggest|no suggestions|net antwoord)\b", re.I), "proactivity", "answer_only"),
    (re.compile(r"\b(what should i do next|suggest|any ideas|wat moet ek volgende doen|voorstelle)\b", re.I), "proactivity", "suggest_next"),
]
LANG_PREF = [
    (re.compile(r"\b(reply|answer|speak|talk|respond)\s+(in|to me in)\s+afrikaans\b|\b(antwoord|praat)\s+(asseblief\s+)?(in\s+)?afrikaans\b", re.I), "af"),
    (re.compile(r"\b(reply|answer|speak|talk|respond)\s+(in|to me in)\s+english\b|\b(antwoord|praat)\s+(asseblief\s+)?(in\s+)?engels\b|\bin english please\b", re.I), "en"),
]

# ---------------------------------------------------------------- rule-based fact patterns (en + af)
# names and places must start with a capital even though the trigger words are matched case-insensitively
NAME = r"((?-i:[A-Z][a-zÀ-ÿ'-]+(?:\s[A-Z][a-zÀ-ÿ'-]+)?))"
PLACE = r"((?-i:[A-Z][\wÀ-ÿ'-]+(?:,?\s[A-Z][\wÀ-ÿ'-]+){0,3}))"
FILLER = re.compile(r"\s+(?:any ?more|at all|so much|very much|a lot|anymore|meer|nie)$", re.I)
FACT_RULES: list[tuple[re.Pattern, Any]] = [
    (re.compile(rf"\b(?:my name is|call me|i'?m called|my naam is|noem my)\s+{NAME}", re.I), lambda m: [("owner.name", m.group(1))]),
    (re.compile(rf"\b(?:farm(?:er|ing)?|based|living|boer|woon)\s+(?:near|outside|close to|naby|buite)\s+{PLACE}", re.I),
     lambda m: [("owner.location", "near " + m.group(1).strip(" ,"))]),
    (re.compile(rf"\b(?:i live in|i'?m based in|i stay in|ek bly in|ek woon in)\s+{PLACE}", re.I), lambda m: [("owner.location", m.group(1).strip(" ,"))]),
    (re.compile(r"\b(?:i work as an?|my job is an?|ek werk as 'n)\s+([a-zÀ-ÿ -]{3,40}?)(?:\s+(?:at|in|for|by|op|vir)\b|[.,!]|$)", re.I),
     lambda m: [("owner.role", m.group(1).strip())]),
    # "I'm a farmer" / "ek is 'n boer": only when the last word looks like a job, not "I'm a bit tired"
    (re.compile(r"\b(?:i'?m an?|i am an?|ek is 'n)\s+((?:[a-zÀ-ÿ-]+\s){0,2}[a-zÀ-ÿ-]*(?:er|or|ist|ian|ant|ent|man|boer|eur|ess|tect|wright))\b", re.I),
     lambda m: [("owner.role", m.group(1).strip())]),
    # "the vet, Dr Botha" / "ons veearts, Dr Botha"
    (re.compile(rf"\b(?:the|my|our|die|ons|my)\s+(vet|mechanic|electrician|plumber|accountant|lawyer|doctor|foreman|manager|veearts|werktuigkundige|elektrisiën|rekenmeester|dokter|voorman|bestuurder)\s*,?\s+((?-i:(?:Dr|Mr|Mrs|Ms|Oom|Tannie)\.?\s+)?){NAME}", re.I),
     lambda m: [(f"people.{_slug(m.group(1))}", (m.group(2) or "") + m.group(3))]),
    (re.compile(rf"\bmy (wife|husband|partner|son|daughter|manager|boss|foreman|vet|mechanic|vrou|man|seun|dogter|bestuurder|voorman)(?:'s name)? is\s+{NAME}", re.I),
     lambda m: [(f"people.{_slug(m.group(1))}", m.group(2))]),
    (re.compile(r"\b(?:i have|i own|we have|we own|we run|we keep|ek het|ons het|ons hou)\s+([^.!?\n]{3,120})", re.I),
     lambda m: _owned(m.group(1))),
    (re.compile(r"\b(?:i (?:really )?(?:like|love|prefer|enjoy)|ek hou van|ek verkies)\s+([^.,!?]{3,40})", re.I),
     lambda m: [("likes", FILLER.sub("", m.group(1).strip()))]),
    (re.compile(r"\b(?:i (?:don'?t|do not) like|i hate|i dislike|ek hou nie van)\s+([^.,!?]{3,40})", re.I),
     lambda m: [("dislikes", FILLER.sub("", m.group(1).strip()))]),
]
REMEMBER = re.compile(r"\b(?:remember(?: that)?|don'?t forget(?: that)?|onthou(?: dat)?|moenie vergeet(?: dat)? nie)\s+(.{4,})", re.I)

FACT_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array", "maxItems": 5,
            "items": {"type": "object",
                      "properties": {"key": {"type": "string"}, "value": {"type": "string"},
                                     "confidence": {"type": "number"}},
                      "required": ["key", "value", "confidence"]},
        }
    },
    "required": ["facts"],
}
FACT_PROMPT = (
    "You extract durable facts that the OWNER states about themselves: who they are, their work, the people "
    "around them, things they own or look after, routines and preferences. Use short dotted lowercase keys such "
    "as owner.name, owner.role, owner.location, people.manager, owns.cattle, work.farm.crop, routine.dipping, "
    "prefers.units. Only facts that are stated, never guesses, never one-off events. Skip ID numbers, bank or card "
    "numbers. Return JSON {\"facts\": [...]} with confidence 0-1. Return {\"facts\": []} if there are none."
)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:30] or "x"


def normalise_key(key: str) -> str:
    """Small models often answer owner_name or number_of_cattle; map those onto the dotted key scheme."""
    k = re.sub(r"[^a-z0-9_.]+", "_", key.strip().lower()).strip("_.")
    if "." in k:
        return k
    for prefix, ns in (("owner_", "owner."), ("my_", "owner."), ("number_of_", "owns."), ("num_", "owns."),
                       ("preferred_", "prefers."), ("favourite_", "prefers."), ("favorite_", "prefers.")):
        if k.startswith(prefix) and len(k) > len(prefix):
            return ns + k[len(prefix):]
    if k in ("name", "role", "location", "job", "occupation", "language"):
        return "owner." + ("role" if k in ("job", "occupation") else k)
    return f"about.{k}" if k else ""


OWNED_PAIR = re.compile(r"(?:about |around |roughly |ongeveer |sowat )?(\d[\d ,.]*\d|\d)\s+(?:ha |hectares? of |hektaar |head of |stuks )?([a-zÀ-ÿ][a-zÀ-ÿ-]{2,30})", re.I)


def _owned(clause: str) -> list[tuple[str, Any]]:
    """'120 sheep and 300 cattle' -> owns.sheep=120, owns.cattle=300"""
    return [(f"owns.{_slug(m.group(2))}", _num(m.group(1))) for m in OWNED_PAIR.finditer(clause)]


def _num(s: str) -> float | int | str:
    """"300" -> 300, "1,5" -> 15 (thousands); text that is not one number ("1.2.3") stays text, not a count."""
    t = s.replace(" ", "").replace(",", "")
    try:
        f = float(t)
        return int(f) if f.is_integer() else f
    except ValueError:
        return s


def slot_of(ts: float) -> int:
    d = datetime.fromtimestamp(ts)
    return d.weekday() * 24 + d.hour


class Learner:
    def __init__(self, store: Store, llm: LLM | None = None, use_llm_facts: bool = True):
        self.store = store
        self.llm = llm
        self.use_llm_facts = use_llm_facts and llm is not None

    # ================================================================ facts
    def put_fact(self, key: str, value: Any, confidence: float, source: str) -> dict:
        """Merge one fact into the owner model. Returns what happened, for the reply metadata."""
        if key in ("likes", "dislikes"):
            return self._put_list_fact(key, str(value), confidence, source)
        old = self.store.get_fact(key)
        if old is None:
            self.store.put_fact(key, value, confidence, source, [])
            return {"key": key, "value": value, "change": "new"}
        if str(old["value"]).strip().lower() == str(value).strip().lower():
            conf = 1 - (1 - old["confidence"]) * (1 - confidence)
            self.store.put_fact(key, old["value"], min(conf, 0.99), old["source"], old["history"])
            return {"key": key, "value": old["value"], "change": "confirmed"}
        explicit = source.startswith("explicit") or source.startswith("user")
        guessed = source.startswith("llm")
        if guessed and isinstance(old["value"], (int, float)) and not isinstance(value, (int, float)):
            # a count never becomes a word ("300" cattle -> "rams" was a real small-model mistake)
            return {"key": key, "value": old["value"], "change": "rejected"}
        if guessed and not old["source"].startswith("llm"):
            # a model guess may not overwrite what the owner said or a rule matched, unless it repeats
            seen = sum(1 for h in old["history"] if str(h.get("candidate", "")).lower() == str(value).lower())
            if seen < 1:
                self.store.put_fact(key, old["value"], old["confidence"], old["source"],
                                    old["history"] + [{"candidate": value, "at": time.time(), "source": source}])
                return {"key": key, "value": old["value"], "change": "contested"}
        if explicit or confidence >= old["confidence"] * 0.8:
            hist = old["history"] + [{"value": old["value"], "until": time.time(), "source": old["source"]}]
            self.store.put_fact(key, value, confidence, source, hist)
            return {"key": key, "value": value, "change": "updated", "previous": old["value"]}
        self.store.put_fact(key, old["value"], old["confidence"] * 0.9, old["source"],
                            old["history"] + [{"candidate": value, "at": time.time(), "source": source}])
        return {"key": key, "value": old["value"], "change": "contested"}

    def _put_list_fact(self, key: str, item: str, confidence: float, source: str) -> dict:
        other = "dislikes" if key == "likes" else "likes"
        cur = self.store.get_fact(key)
        items = list(cur["value"]) if cur else []
        if item.lower() not in [i.lower() for i in items]:
            items.append(item)
        self.store.put_fact(key, items[-30:], max(confidence, cur["confidence"] if cur else 0), source,
                            cur["history"] if cur else [])
        opp = self.store.get_fact(other)
        if opp and item.lower() in [i.lower() for i in opp["value"]]:
            self.store.put_fact(other, [i for i in opp["value"] if i.lower() != item.lower()],
                                opp["confidence"], opp["source"], opp["history"])
        return {"key": key, "value": item, "change": "added"}

    def rule_facts(self, text: str) -> list[tuple[str, Any]]:
        found: list[tuple[str, Any]] = []
        for pat, fn in FACT_RULES:
            for m in pat.finditer(text):
                found.extend(fn(m))
        return found

    def llm_facts(self, text: str) -> list[tuple[str, Any, float]]:
        if not self.use_llm_facts or len(content_terms(text)) < 3:
            return []
        msgs = [{"role": "system", "content": FACT_PROMPT},
                {"role": "user", "content": f"Owner said: \"{text}\""}]
        try:
            data = parse_json(self.llm.chat(msgs, max_tokens=220, temperature=0.0, schema=FACT_SCHEMA))
        except Exception:  # a learning step must never break the reply
            return []
        out = []
        for f in (data or {}).get("facts", []) if isinstance(data, dict) else []:
            key = normalise_key(str(f.get("key", "")))
            raw = f.get("value", "")
            val = redact(str(raw).strip())
            if re.fullmatch(r"\d[\d ,]*(\.\d+)?", val):
                val = _num(val)  # "300" -> 300 so it merges with the rule-based fact
            if not KEY_OK.match(key) or val in ("", None) or "[id-number]" in str(val) or "[card-number]" in str(val):
                continue
            out.append((key, val, min(float(f.get("confidence", 0.5)), 0.8)))
        return out

    # ================================================================ style, vocabulary, rhythm
    def learn_style(self, text: str) -> None:
        feats = style_features(text).__dict__
        cur = self.store.style()
        for k, v in feats.items():
            val, n = cur.get(k, (v, 0))
            alpha = max(0.1, 1.0 / (n + 1))  # running mean at first, then EMA with alpha 0.1
            self.store.set_style(k, val + alpha * (v - val) if n else v, n + 1)
        lang = guess_language(text)
        for opt in ("en", "af", "mixed"):
            val, n = cur.get(f"lang_{opt}", (0.0, 0))
            alpha = max(0.1, 1.0 / (n + 1))
            target = 1.0 if lang == opt else 0.0
            self.store.set_style(f"lang_{opt}", val + alpha * (target - val), n + 1)

    def learn_vocab_and_rhythm(self, text: str, ts: float, weight: float = 1.0) -> None:
        terms = content_terms(text)
        if not terms:
            return
        self.store.bump_vocab(terms, weight, ts)
        self.store.bump_rhythm(slot_of(ts), terms)

    # ================================================================ explicit instructions
    def explicit_preferences(self, text: str) -> list[dict]:
        changes = []
        for pat, dim, opt in EXPLICIT_STYLE:
            if pat.search(text):
                self.reward(dim, opt, EXPLICIT_WIN, others_loss=EXPLICIT_LOSS)
                changes.append({"dim": dim, "option": opt})
        for pat, lang in LANG_PREF:
            if pat.search(text):
                self.put_fact("prefers.language", lang, 0.99, "explicit")
                changes.append({"dim": "language", "option": lang})
        return changes

    # ================================================================ Thompson-sampling arms
    def _decay_dim(self, dim: str) -> None:
        for opt in DIMS[dim]:
            a, b = self.store.arm(dim, opt)
            self.store.set_arm(dim, opt, 1 + (a - 1) * DECAY, 1 + (b - 1) * DECAY)

    def reward(self, dim: str, option: str, win: float = 1.0, others_loss: float = 0.0) -> None:
        self._decay_dim(dim)
        a, b = self.store.arm(dim, option)
        self.store.set_arm(dim, option, a + win, b)
        if others_loss:
            for opt in DIMS[dim]:
                if opt != option:
                    a2, b2 = self.store.arm(dim, opt)
                    self.store.set_arm(dim, opt, a2, b2 + others_loss)

    def penalise(self, dim: str, option: str, loss: float = 1.0) -> None:
        self._decay_dim(dim)
        a, b = self.store.arm(dim, option)
        self.store.set_arm(dim, option, a, b + loss)

    def learn_from_feedback(self, style: dict, rating: int | None, original: str, edited: str | None) -> list[dict]:
        """rating +1 / -1 on a reply, and/or the owner's own edit of it."""
        changes = []
        if rating:
            for dim, opt in style.items():
                if dim not in DIMS:
                    continue
                (self.reward(dim, opt) if rating > 0 else self.penalise(dim, opt))
                changes.append({"dim": dim, "option": opt, "signal": "up" if rating > 0 else "down"})
        if edited:
            n0, n1 = len(tokens(original)), len(tokens(edited))
            chosen = style.get("length", "medium")
            order = DIMS["length"]
            i = order.index(chosen) if chosen in order else 1
            if n0 and n1 / n0 < 0.7:
                self.penalise("length", chosen, 2.0)
                self.reward("length", order[max(i - 1, 0)], 2.0)
                changes.append({"dim": "length", "option": order[max(i - 1, 0)], "signal": "edited_shorter"})
            elif n0 and n1 / n0 > 1.4:
                self.penalise("length", chosen, 2.0)
                self.reward("length", order[min(i + 1, 2)], 2.0)
                changes.append({"dim": "length", "option": order[min(i + 1, 2)], "signal": "edited_longer"})
            had = style_features(original).bullet_use
            has = style_features(edited).bullet_use
            if had != has:
                opt = "bullets" if has else "prose"
                self.reward("format", opt, 2.0, others_loss=1.0)
                changes.append({"dim": "format", "option": opt, "signal": "edited_format"})
            self.learn_style(edited)
        return changes

    # ================================================================ one owner message
    def observe(self, text: str, ts: float | None = None, source: str = "chat") -> dict:
        """Learn everything that can be learned from one piece of owner text."""
        ts = ts or time.time()
        clean = redact(text)
        learned: list[dict] = []
        for key, val in self.rule_facts(clean):
            learned.append(self.put_fact(key, val, 0.75, f"rule:{source}"))
        rule_keys = {f["key"] for f in learned}
        rule_vals = {str(f["value"]).lower() for f in learned}
        # model extraction only on what the owner says to the companion; voice notes are events, not
        # statements about themselves, and a 2B model over-reads them
        for key, val, conf in (self.llm_facts(clean) if source == "chat" else []):
            # skip a model fact that repeats a rule fact's value under another key (vet filed as manager)
            if key not in rule_keys and str(val).lower() not in rule_vals:
                learned.append(self.put_fact(key, val, conf, f"llm:{source}"))
        style_changes = self.explicit_preferences(clean) if source == "chat" else []
        if source == "chat":
            self.learn_style(clean)
        self.learn_vocab_and_rhythm(clean, ts, 1.0 if source == "chat" else 1.5)
        remember = REMEMBER.search(clean)
        return {"facts": learned, "style": style_changes, "remember": remember.group(1).strip() if remember else None,
                "clean_text": clean}
