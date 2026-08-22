"""Deleting the data folder erases every transaction, budget and saved bank login, and
there is no undo. Both uninstallers must therefore erase it ONLY on an exact, deliberate
"DELETE" — never on y/yes/Enter, and never on a lowercase near-miss."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_only_an_exact_delete_word_erases_data():
    sh = (ROOT / "uninstall.command").read_text(encoding="utf-8")
    ps = (ROOT / "scripts" / "uninstall.ps1").read_text(encoding="utf-8-sig")

    # bash: a plain string comparison against the literal, not a pattern that could
    # widen (`==` on an unquoted glob, or a case-insensitive shopt) — and the removal
    # must live inside that branch, never before it.
    assert '[ "$answer" = "DELETE" ]' in sh
    keep, _, erase = sh.partition('[ "$answer" = "DELETE" ]')
    assert 'rm -rf "$DATA"' in erase, "the delete must be inside the DELETE branch"
    assert 'rm -rf "$DATA"' not in keep, "the data folder is removed before it is confirmed"

    # PowerShell: -ceq is the case-SENSITIVE comparison. Plain -eq would accept "delete".
    assert '-ceq "DELETE"' in ps
    assert "-eq \"DELETE\"" not in ps.replace('-ceq "DELETE"', ""), "case-insensitive compare"
    keep, _, erase = ps.partition('-ceq "DELETE"')
    assert "Remove-Item -Recurse -Force $data" in erase
    assert "Remove-Item -Recurse -Force $data" not in keep


def test_the_prompt_defaults_to_keeping_the_data():
    """Someone hitting Enter to get through a dialog must keep their data, so the prompt
    has to say so — an unlabelled prompt invites a reflexive y."""
    for text in ((ROOT / "uninstall.command").read_text(encoding="utf-8"),
                 (ROOT / "scripts" / "uninstall.ps1").read_text(encoding="utf-8-sig")):
        assert "press Enter to KEEP it" in text
        assert "CANNOT be undone" in text


def test_the_handler_is_unregistered_before_the_folder_goes():
    """A kaspion:// entry left pointing at a deleted folder is a dead button."""
    sh = (ROOT / "uninstall.command").read_text(encoding="utf-8")
    ps = (ROOT / "scripts" / "uninstall.ps1").read_text(encoding="utf-8-sig")
    assert "lsregister" in sh and "-u " in sh
    assert r'"HKCU:\Software\Classes\kaspion"' in ps
