from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
IMAGE_DIR = ROOT / "docker" / "gui" / "ubuntu"


def test_gui_dockerfile_exists_and_does_not_define_entrypoint():
    dockerfile = IMAGE_DIR / "Dockerfile"
    assert dockerfile.exists()
    content = dockerfile.read_text()
    assert "FROM ubuntu:22.04" in content
    assert "ENTRYPOINT" not in content
    assert "CMD " not in content


def test_gui_dockerfile_installs_required_dependencies():
    content = (IMAGE_DIR / "Dockerfile").read_text()
    for package in [
        "xvfb",
        "dbus-x11",
        "xfce4",
        "xfce4-terminal",
        "x11vnc",
        "websockify",
        "novnc",
        "scrot",
        "xdotool",
        "python3",
        "python3-tk",
        "python3-dev",
        "python3-pip",
    ]:
        assert package in content
    assert "pyautogui" in content
    assert "/usr/local/bin/rock-gui-start" in content


def test_gui_start_script_is_idempotent_and_uses_expected_defaults():
    script = IMAGE_DIR / "rock-gui-start"
    assert script.exists()
    content = script.read_text()
    assert "ROCK_GUI_DISPLAY" in content
    assert "ROCK_GUI_WIDTH" in content
    assert "ROCK_GUI_HEIGHT" in content
    assert "ROCK_GUI_ENABLE_NOVNC" in content
    assert ":99" in content
    assert "1280" in content
    assert "720" in content
    assert "8006" in content
    assert "pgrep" in content
    assert "Xvfb" in content
    assert "startxfce4" in content
    assert '"desktop": "xfce"' in content


def test_gui_start_script_prepares_xauthority_for_pyautogui():
    script = IMAGE_DIR / "rock-gui-start"
    content = script.read_text()

    assert "XAUTHORITY" in content
    assert "touch \"${XAUTHORITY}\"" in content
    assert "Xvfb \"${DISPLAY_ID}\" -ac" in content
