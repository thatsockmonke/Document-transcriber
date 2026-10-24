from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialogButtonBox

from document_transcriber.app import MainWindow
from document_transcriber.documents import make_sample
from document_transcriber.rule_ui import RuleReviewDialog, RulesDialog
from document_transcriber.rules import default_rules, new_rule, preview_rules


def test_rule_builder_preview_does_not_mutate_original_profile(qt_app):
    rules = default_rules()
    dialog = RulesDialog(rules, 'She said "Hello."')
    dialog.show()
    dialog.enabled.setChecked(True)
    dialog.refresh_preview()
    assert dialog.result.toPlainText() == 'She said, "Hello."'
    assert not rules[0].enabled
    assert dialog.rules[0].enabled
    assert dialog.buttons.button(QDialogButtonBox.Save).isEnabled()
    assert "1 change" in dialog.preview_label.text()
    dialog.close()


def test_contextual_dictionary_in_editor_and_rules_apply_undo(qt_app, tmp_path):
    window = MainWindow(tmp_path / "data")
    sample = tmp_path / "sample.png"
    make_sample(sample)
    identity = window.store.add_document("Notes", str(sample), [sample])
    page = window.store.pages(identity)[0]
    window.load_page(page.id)
    window.editor.setPlainText("He arrived form London.")
    cursor = window.editor.textCursor()
    cursor.setPosition(11)
    cursor.select(QTextCursor.WordUnderCursor)
    window.editor.setTextCursor(cursor)
    window.lookup.setText("form")
    window.lookup_word()
    assert window.suggestions.item(0).text() == "from"
    assert "Fits" in window.suggestion_reason.text()
    assert "[form]" in window.context_hint.text()
    window.apply_suggestion()
    assert window.editor.toPlainText() == "He arrived from London."
    window.editor.setPlainText('She said "Hello." Then she said "Goodbye."')
    before = window.editor.toPlainText()
    rule = new_rule("comma_before_quote")
    rule.enabled = True
    preview = preview_rules(before, [rule])
    assert len(preview.edits) == 2
    window.apply_rule_edits(before, preview.edits)
    assert window.editor.toPlainText() == 'She said, "Hello." Then she said, "Goodbye."'
    window.editor.undo()
    assert window.editor.toPlainText() == before
    window.close()


def test_individual_rule_changes_can_be_declined(qt_app):
    rule = new_rule("comma_before_quote")
    rule.enabled = True
    preview = preview_rules('She said "Hello." He said "Goodbye."', [rule])
    dialog = RuleReviewDialog(preview)
    assert len(dialog.selected_edits()) == 2
    dialog.changes.item(1).setCheckState(Qt.Unchecked)
    assert len(dialog.selected_edits()) == 1
    assert dialog.after.toPlainText() == 'She said, "Hello." He said "Goodbye."'
    dialog.close()


def test_export_reviews_rules_on_every_page_and_restores_selection(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog, QFileDialog

    window = MainWindow(tmp_path / "data")
    sample = tmp_path / "sample.png"
    make_sample(sample)
    identity = window.store.add_document("Two pages", str(sample), [sample, sample])
    pages = window.store.pages(identity)
    for page in pages:
        window.store.save_page(page.id, 'She said "Hello."', [], "", False, "")
    rule = new_rule("comma_before_quote")
    rule.enabled = True
    window.store.save_rules([rule])
    window.load_page(pages[0].id)
    destination = tmp_path / "export.txt"
    monkeypatch.setattr(RuleReviewDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(destination), "Plain text (*.txt)")
    )
    window.export_current()
    assert destination.read_text().count('She said, "Hello."') == 2
    assert window.current_page.id == pages[0].id
    window.close()


def test_repeated_window_close_does_not_try_to_save_a_closed_database(qt_app, tmp_path):
    window = MainWindow(tmp_path / "data")
    errors = []
    window.error = lambda *args: errors.append(args)
    window.show()
    window.close()
    window.close()
    assert window._closed
    assert not errors
