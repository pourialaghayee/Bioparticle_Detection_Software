"""Create or repair the local Python environment using only the standard library."""
from pathlib import Path
import json
import os
import subprocess
import sys
import venv


def pinned_requirements(path):
    required = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.count("==") != 1:
            raise ValueError(f"Expected a pinned package version in requirements.txt: {line}")
        name, version = line.split("==")
        required[name.strip()] = version.strip()
    return required


def dependencies_ready(python, required):
    check = (
        "import importlib.metadata as m,json,sys; "
        "required=json.loads(sys.argv[1]); "
        "sys.exit(0 if all(m.version(k)==v for k,v in required.items()) else 1)"
    )
    return subprocess.run([str(python), "-c", check, json.dumps(required)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


# Characters below .venv taken by the deepest file of the pinned PySide6 wheel on
# Windows: \Lib\site-packages\ (19) + 151, plus a small margin.
WINDOWS_PACKAGE_DEPTH = 175
WINDOWS_MAX_PATH = 259


def windows_long_paths_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except OSError:
        return False


def check_windows_path_length(environment):
    """Fail before installing, not halfway through, if Qt files would exceed MAX_PATH."""
    if os.name != "nt" or windows_long_paths_enabled():
        return
    if len(str(environment)) + WINDOWS_PACKAGE_DEPTH > WINDOWS_MAX_PATH:
        raise RuntimeError(
            f"This folder path is too long for Windows:\n  {environment.parent}\n"
            "Move the bead-counter folder to a short location such as C:\\Polimi\\bead-counter, "
            "delete any partly created .venv folder there, and run run_windows.bat again.")


def main():
    if sys.version_info < (3, 12):
        raise RuntimeError("Use Python 3.12 or later. Python 3.12 is the tested version.")
    root = Path(__file__).resolve().parent
    environment = root/".venv"
    python = environment/("Scripts/python.exe" if os.name == "nt" else "bin/python")
    required = pinned_requirements(root/"requirements.txt")
    if python.is_file() and dependencies_ready(python, required):
        return 0
    check_windows_path_length(environment)
    if not python.is_file():
        print("Creating the local Python environment…", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    if not dependencies_ready(python, required):
        print("Installing the required packages; first setup needs internet access…", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                        "--no-cache-dir", "-r", str(root/"requirements.txt")], check=True)
        if not dependencies_ready(python, required):
            raise RuntimeError("Dependency verification failed. Run the launcher again to retry setup.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        sys.exit(1)
