"""Enforce the owner's declared pronouns in model output.

A language model will happily infer gender from a first name, and it does so
inconsistently - the same resume produced "they" for one question and "she" for
the next. For a tool that speaks to recruiters on someone's behalf, guessing is
not acceptable, and a prompt rule alone demonstrably does not hold.

So the owner declares their pronouns in config and this module rewrites any
*gendered* third-person singular pronoun in the answer to match. Verb agreement is
repaired when rewriting to "they", using an explicit whitelist - a general "strip
the -s" rule would corrupt plural nouns ("their skills" -> "their skill").

Deliberate limit: "they/them" is never rewritten *into* a gendered pronoun, even
when the owner uses she/her or he/him. "they" is often genuinely plural in these
answers ("40 microservices ... they were migrated"), and mangling those sentences
would be worse than leaving one neutral pronoun standing.
"""
from __future__ import annotations

import re

# subject, object, possessive determiner, possessive pronoun, reflexive
SETS: dict[str, tuple[str, str, str, str, str]] = {
    "they/them": ("they", "them", "their", "theirs", "themselves"),
    "she/her": ("she", "her", "her", "hers", "herself"),
    "he/him": ("he", "him", "his", "his", "himself"),
}

# Words that, following "her"/"his", mean it was an object or standalone
# possessive rather than a possessive determiner.
_NOT_A_NOUN_NEXT = {
    "the", "a", "an", "to", "for", "with", "and", "or", "but", "in", "on", "at",
    "by", "from", "that", "this", "these", "those", "as", "if", "when", "while",
    "so", "then", "than", "because", "after", "before", "into", "about",
}

# Auxiliaries needing repair after "they".
_AUX = {
    "is": "are", "isn't": "aren't", "was": "were", "wasn't": "weren't",
    "has": "have", "hasn't": "haven't", "does": "do", "doesn't": "don't",
    "'s": "'re",
}

# Present-tense verbs common in resume answers. Only these get de-pluralized,
# so nouns are never touched.
_VERBS = {
    "leads", "works", "builds", "brings", "delivers", "manages", "owns", "writes",
    "designs", "develops", "creates", "maintains", "handles", "focuses", "holds",
    "combines", "demonstrates", "shows", "makes", "takes", "uses", "provides",
    "offers", "specializes", "specialises", "excels", "understands", "knows",
    "continues", "operates", "supports", "runs", "drives", "helps", "adds",
    "applies", "approaches", "seems", "appears", "remains", "stands", "comes",
    "goes", "gets", "keeps", "needs", "wants", "prefers", "enjoys", "plans",
    "aims", "seeks", "contributes", "collaborates", "mentors", "reports",
}

# Past participles that make a following "'s" mean "has", not "is".
_PARTICIPLES = {
    "built", "done", "been", "made", "led", "written", "taken", "seen", "gone",
    "worked", "shipped", "delivered", "grown", "run", "become", "had", "given",
    "spent", "held", "kept", "brought", "driven", "managed", "owned", "moved",
}

# Adverbs that commonly sit between the subject and its verb. Deliberately a
# fixed set rather than "any single word": "they think Bob works here" must not
# have "works" rewritten, since that verb belongs to Bob.
_ADVERBS = (
    "also|still|often|always|never|now|then|currently|previously|recently|"
    "already|generally|typically|further|additionally|similarly|likewise|too|"
    "again|sometimes|usually|consistently|regularly|actively|primarily|mainly|"
    r"[A-Za-z]+ly"
)

# Longest alternatives first, and both straight and curly apostrophes, because
# the model emits U+2019 far more often than U+0027.
_PRONOUN_RE = re.compile(
    r"\b(himself|herself|hers|him|her|his|she|he)(['’](?:s|d|ll|ve|re))?\b(\s*)",
    re.IGNORECASE,
)


def _match_case(source: str, replacement: str) -> str:
    if source.isupper() and len(source) > 1:
        return replacement.upper()
    if source[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def normalize(text: str, pronouns: str = "they/them") -> str:
    """Rewrite third-person singular pronouns in `text` to the given set."""
    target = SETS.get(pronouns.strip().lower())
    if not target:
        return text
    subject, obj, poss_det, poss_pron, reflexive = target

    def replace(m: re.Match) -> str:
        word, contraction, space = m.group(1), m.group(2), m.group(3)
        lower = word.lower()
        rest = m.string[m.end() :]
        next_word = re.match(r"([A-Za-z']+)", rest)
        following = next_word.group(1).lower() if next_word else ""
        # No following word (end of sentence/clause) means it can't be a determiner.
        determiner_position = bool(following) and following not in _NOT_A_NOUN_NEXT

        if contraction:
            # "he's built" -> has; "he's interested" -> is.
            out = subject
            suffix = contraction[1:].lower()
            if subject == "they" and suffix == "s":
                suffix = "ve" if following in _PARTICIPLES else "re"
            return _match_case(word, out) + "'" + suffix + space

        if lower in ("he", "she"):
            out = subject
        elif lower == "him":
            out = obj
        elif lower == "hers":
            out = poss_pron
        elif lower in ("himself", "herself"):
            out = reflexive
        elif lower == "her":
            # "her role" -> determiner; "gave it to her" -> object.
            out = poss_det if determiner_position else obj
        elif lower == "his":
            out = poss_det if determiner_position else poss_pron
        else:
            out = word

        return _match_case(word, out) + space

    result = _PRONOUN_RE.sub(replace, text)
    return _fix_agreement(result) if subject == "they" else result


def _fix_agreement(text: str) -> str:
    """Repair singular verbs left stranded after rewriting to "they"."""

    def repair(m: re.Match) -> str:
        pronoun, gap, adverb, verb = m.group(1), m.group(2), m.group(3), m.group(4)
        lower = verb.lower()
        if lower in _AUX:
            return pronoun + gap + adverb + _match_case(verb, _AUX[lower])
        if lower in _VERBS:
            return pronoun + gap + adverb + _match_case(verb, lower[:-1])
        return m.group(0)

    # Allow one intervening adverb ("they consistently delivers", "they also
    # excels"), but nothing more - past that, the next verb is too likely to
    # belong to another clause.
    text = re.sub(
        rf"\b(they)(\s+)((?:(?:{_ADVERBS})\s+)?)([A-Za-z']+)\b",
        repair,
        text,
        flags=re.IGNORECASE,
    )
    return _fix_coordinated_clauses(text)


# Sentences are split on terminal punctuation; good enough for model prose.
_SENTENCE_RE = re.compile(r"[^.!?]*(?:[.!?]+|$)")

# "..., and has ..." - a second verb sharing the sentence's subject.
_CONJUNCTION_RE = re.compile(
    r"\b(and|or|but)(\s+)(is|was|has|does|isn't|wasn't|hasn't|doesn't)\b",
    re.IGNORECASE,
)


def _fix_coordinated_clauses(text: str) -> str:
    """Repair a second verb that shares the subject: "They design ... and has ...".

    Scoped to sentences that *begin* with "They", where the elided subject is
    unambiguous. In "The system they built is fast and has 5 modules" the "has"
    belongs to "the system", so sentences like that are deliberately left alone -
    and the conjunction must be followed immediately by the verb, so "and the
    team has" never matches either.
    """

    def fix_sentence(m: re.Match) -> str:
        sentence = m.group(0)
        if not re.match(r"\s*they\b", sentence, re.IGNORECASE):
            return sentence
        return _CONJUNCTION_RE.sub(
            lambda c: c.group(1) + c.group(2) + _match_case(c.group(3), _AUX[c.group(3).lower()]),
            sentence,
        )

    return _SENTENCE_RE.sub(fix_sentence, text)
