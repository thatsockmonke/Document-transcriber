import json

import pytest

from document_transcriber.context import ContextModel
from document_transcriber.dictionary import Dictionary
from document_transcriber.rules import (
    WritingRule,
    default_rules,
    new_rule,
    preview_rules,
    validate_rules,
)
from document_transcriber.storage import ProjectStore


@pytest.fixture(scope="module")
def dictionary():
    return Dictionary()


@pytest.mark.parametrize(
    "word,before,after,expected",
    [
        ("reed", "I want to ", " a book.", "read"),
        ("form", "He arrived ", " London.", "from"),
        ("peace", "A ", " of cake.", "piece"),
    ],
)
def test_similar_words_are_ranked_with_actual_bundled_context(
    dictionary, word, before, after, expected
):
    suggestions = dictionary.rank(word, before, after)
    assert suggestions[0].word == expected
    assert suggestions[0].context_evidence >= 2
    assert "Fits" in suggestions[0].reason
    assert suggestions[0].similarity > 0
    assert all(item.word != word for item in suggestions)


def test_context_can_be_disabled_and_does_not_override_approved_corrections(dictionary):
    ranked = dictionary.rank("peace", "A ", " of cake.", use_context=False)
    assert all(not item.context_evidence for item in ranked)
    assert all("Fits" not in item.reason for item in ranked)
    assert dictionary.correction("peace") is None
    dictionary.learned["form"] = "from"
    assert dictionary.correction("form") is None


def test_reviewed_project_text_adapts_context_and_can_be_forgotten():
    context = ContextModel()
    assert context.fit("crostini", "launch ", " now").evidence == 0
    context.update("page-1", "Launch Crostini now.", reviewed=True)
    assert context.fit("crostini", "launch ", " now").evidence >= 25
    context.update("page-1", "Launch Crostini now.", reviewed=False)
    assert context.fit("crostini", "launch ", " now").evidence == 0


@pytest.mark.parametrize(
    "kind,before,after",
    [
        ("comma_before_quote", 'She said "Hello."', 'She said, "Hello."'),
        ("comma_before_quote", 'She said, "Hello."', 'She said, "Hello."'),
        ("comma_before_quote", '"Start of line"\n"Next line"', '"Start of line"\n"Next line"'),
        ("comma_inside_quote", '"Hello", she said.', '"Hello," she said.'),
        ("comma_inside_quote", "“Hello”, she said.", "“Hello,” she said."),
        ("dialogue_comma", '"Hello" she said.', '"Hello," she said.'),
        ("dialogue_comma", '"Hello" Alice said.', '"Hello," Alice said.'),
        ("dialogue_comma", '"Really?" she asked.', '"Really?" she asked.'),
        ("dialogue_comma", 'The word "orange" is a colour.', 'The word "orange" is a colour.'),
        (
            "smart_quotes",
            'She said "Hello." Don\'t change apostrophes.',
            "She said “Hello.” Don't change apostrophes.",
        ),
        ("straight_quotes", "She said “Hello.”", 'She said "Hello."'),
        (
            "single_spaces",
            "  Keep   this\n\tindentation  intact",
            "  Keep this\n\tindentation intact",
        ),
        ("trim_trailing", "Keep\t\nthese spaces   \n", "Keep\nthese spaces\n"),
    ],
)
def test_punctuation_rules_are_predictable_and_idempotent(kind, before, after):
    rule = new_rule(kind)
    rule.enabled = True
    preview = preview_rules(before, [rule])
    assert preview.after == after
    assert preview_rules(after, [rule]).after == after
    reconstructed = before
    for edit in reversed(preview.edits):
        reconstructed = reconstructed[: edit.start] + edit.replacement + reconstructed[edit.end :]
    assert reconstructed == after


def test_literal_replacement_word_boundaries_and_validation():
    rule = WritingRule("replace-1", "British spelling", "replace", True, "color", "colour")
    assert preview_rules("Color, colorful color.", [rule]).after == "colour, colorful colour."
    rule.case_sensitive = True
    assert preview_rules("Color color", [rule]).after == "Color colour"
    rule.find, rule.replacement = "$1", "literal \\1"
    rule.whole_word = False
    assert preview_rules("cost $1", [rule]).after == "cost literal \\1"
    with pytest.raises(ValueError):
        validate_rules([new_rule("replace").to_dict()])
    curly, straight = new_rule("smart_quotes"), new_rule("straight_quotes")
    curly.enabled = straight.enabled = True
    with pytest.raises(ValueError, match="either curly or straight"):
        validate_rules([curly.to_dict(), straight.to_dict()])


def test_saved_project_rules_survive_reopening_without_reappearing_if_deleted(tmp_path):
    store = ProjectStore(tmp_path / "project")
    assert all(not rule.enabled for rule in store.writing_rules())
    rules = default_rules()
    rules[0].enabled = True
    store.save_rules(rules)
    store.close()
    store = ProjectStore(tmp_path / "project")
    assert store.writing_rules()[0].enabled
    assert store.preference("writing_rules")[0]["kind"] == "comma_before_quote"
    store.save_rules([])
    store.close()
    store = ProjectStore(tmp_path / "project")
    assert store.writing_rules() == []
    store.close()


def test_profile_parser_rejects_executable_rules_and_oversized_profiles():
    rule = new_rule("single_spaces").to_dict()
    rule["kind"] = "python"
    with pytest.raises(ValueError):
        validate_rules([rule])
    with pytest.raises(ValueError):
        validate_rules([new_rule("single_spaces").to_dict() for _ in range(101)])
    assert json.loads(json.dumps(default_rules()[0].to_dict()))["enabled"] is False
