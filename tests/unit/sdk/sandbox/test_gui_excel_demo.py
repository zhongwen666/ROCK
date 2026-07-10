from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DEMO_PATH = ROOT / "tmp" / "gui_excel_demo.py"


def test_excel_demo_uses_gui_actions_instead_of_uno_workbook_creation():
    content = DEMO_PATH.read_text()

    assert "import uno" not in content
    assert "private:factory/scalc" not in content
    assert "storeAsURL" not in content
    assert "Calc MS Excel 2007 XML" not in content
    assert "--accept='socket" not in content
    assert "python3-uno" not in content

    assert "setsid -f libreoffice --calc" in content
    assert "await sandbox.gui.screenshot" in content
    assert "await sandbox.gui.click" in content
    assert "await sandbox.gui.typewrite" in content
    assert 'await sandbox.gui.hotkey("ctrl", "shift", "s")' in content
    assert "SANDBOX_SPREADSHEET_PATH" in content
