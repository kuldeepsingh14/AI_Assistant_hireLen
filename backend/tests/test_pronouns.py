"""Tests for deterministic pronoun enforcement."""
from __future__ import annotations

import pytest

from app.services.pronouns import normalize


# ---------- rewriting to they/them ----------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("She led the migration.", "They led the migration."),
        ("He led the migration.", "They led the migration."),
        ("Her role was Senior Engineer.", "Their role was Senior Engineer."),
        ("His role was Senior Engineer.", "Their role was Senior Engineer."),
        ("The team reported to him.", "The team reported to them."),
        ("The choice was hers.", "The choice was theirs."),
        ("She built it herself.", "They built it themselves."),
    ],
)
def test_rewrites_to_they(text: str, expected: str) -> None:
    assert normalize(text) == expected


def test_her_as_object_vs_determiner() -> None:
    """"her" is both an object and a possessive determiner; they map differently."""
    assert normalize("Recruiters contacted her.") == "Recruiters contacted them."
    assert normalize("her leadership shows") == "their leadership shows"
    # Followed by a function word, so it is an object rather than a determiner.
    assert normalize("gave it to her and the team") == "gave it to them and the team"


def test_his_as_determiner_vs_standalone() -> None:
    assert normalize("his project shipped") == "their project shipped"
    assert normalize("The idea was his.") == "The idea was theirs."


# ---------- verb agreement ----------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("She is a backend engineer.", "They are a backend engineer."),
        ("He was promoted.", "They were promoted."),
        ("She has four years of experience.", "They have four years of experience."),
        ("He doesn't use Rust.", "They don't use Rust."),
        ("She isn't available.", "They aren't available."),
        ("He leads the platform team.", "They lead the platform team."),
        ("She works on payments.", "They work on payments."),
    ],
)
def test_verb_agreement_repaired(text: str, expected: str) -> None:
    assert normalize(text) == expected


def test_plural_nouns_are_not_corrupted() -> None:
    """A blanket "strip the -s after they" rule would break these."""
    assert normalize("Her skills are strong.") == "Their skills are strong."
    assert "their projects" in normalize("His projects are impressive.").lower()
    assert normalize("They ship features.") == "They ship features."


# ---------- capitalization & safety ----------
def test_capitalization_preserved() -> None:
    assert normalize("She is here.").startswith("They")
    assert normalize("Ask her.") == "Ask them."


def test_unrelated_words_untouched() -> None:
    # "The" contains "he" but is not a pronoun; word boundaries must hold.
    assert normalize("The theatre here shone.") == "The theatre here shone."
    assert normalize("Chelsea shipped it.") == "Chelsea shipped it."


def test_other_pronoun_sets() -> None:
    """Gendered pronouns map onto the declared set in either direction."""
    assert normalize("He led it.", "she/her") == "She led it."
    assert normalize("She led it.", "he/him") == "He led it."
    assert normalize("his role", "she/her") == "her role"
    assert normalize("her role", "she/her") == "her role"


def test_plural_they_is_never_made_gendered() -> None:
    """Deliberate limit: "they" is left alone even when the owner uses she/her.

    "they" is frequently plural in a resume answer ("40 microservices ... they
    were migrated"). Rewriting it to a singular gendered pronoun would corrupt
    those sentences, which is worse than leaving a neutral pronoun in place.
    """
    text = "They migrated 40 microservices and they were all containerized."
    assert normalize(text, "she/her") == text
    assert normalize(text, "he/him") == text


def test_unknown_set_is_a_noop() -> None:
    assert normalize("She led it.", "xe/xem") == "She led it."


def test_already_neutral_text_is_stable() -> None:
    text = "They rebuilt the settlement API and cut latency to 120 ms."
    assert normalize(text) == text


def test_agreement_survives_an_intervening_adverb() -> None:
    """Real model output: "She consistently delivers ..." """
    assert (
        normalize("She consistently delivers results.")
        == "They consistently deliver results."
    )
    assert normalize("He clearly is the lead.") == "They clearly are the lead."


def test_agreement_not_applied_across_a_second_word() -> None:
    """Two words out, the -s verb may belong to a different clause - leave it."""
    text = "They, with the team, builds pipelines."
    assert normalize(text) == text


# ---------- contractions ----------
def test_straight_apostrophe_contractions() -> None:
    assert normalize("He's interested in backend work.") == "They're interested in backend work."
    assert normalize("She's built three pipelines.") == "They've built three pipelines."
    assert normalize("He'll join in June.") == "They'll join in June."
    assert normalize("She'd prefer remote work.") == "They'd prefer remote work."


def test_curly_apostrophe_contractions() -> None:
    """The model emits U+2019, not U+0027 - this is the case that shipped broken."""
    assert normalize("positions he\u2019s interested in") == "positions they're interested in"
    assert normalize("she\u2019s led two teams") == "they've led two teams"


def test_contraction_case_preserved() -> None:
    assert normalize("He's here.").startswith("They're")


def test_possessive_of_a_name_is_untouched() -> None:
    """"Jane's" must survive - only pronouns are rewritten."""
    assert normalize("Jane\u2019s leadership is clear.") == "Jane\u2019s leadership is clear."


# ---------- coordinated clauses ----------
def test_second_verb_sharing_the_subject_is_repaired() -> None:
    """Real output: "They specialize in X, Y, and has hands-on experience"."""
    assert (
        normalize("She specializes in APIs, JPA, and has hands-on experience.")
        == "They specialize in APIs, JPA, and have hands-on experience."
    )
    assert (
        normalize("He builds services and is comfortable with CI/CD.")
        == "They build services and are comfortable with CI/CD."
    )


def test_conjunction_fix_requires_the_verb_immediately_after() -> None:
    """"and the team has" - the verb belongs to the team, not to them."""
    text = "They joined Accenture and the team has grown since."
    assert normalize(text) == text
    assert normalize("They led it and it has shipped.") == "They led it and it has shipped."


def test_conjunction_fix_skips_sentences_not_starting_with_they() -> None:
    """Here "has" belongs to "The system", so it must be left alone."""
    text = "The system they built is fast and has five modules."
    assert normalize(text) == text


def test_conjunction_fix_does_not_leak_across_sentences() -> None:
    result = normalize("They ship often. The platform is old and has debt.")
    assert result == "They ship often. The platform is old and has debt."


def test_non_ly_adverbs_are_handled() -> None:
    """Real output: "They also excels in Flutter development"."""
    assert normalize("She also excels in Flutter.") == "They also excel in Flutter."
    assert normalize("He still works on payments.") == "They still work on payments."
    assert normalize("She currently leads the team.") == "They currently lead the team."


def test_intervening_word_is_not_a_free_pass() -> None:
    """"works" belongs to Bob here, so it must survive untouched."""
    text = "They think Bob works here."
    assert normalize(text) == text
