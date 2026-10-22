import json
import socket
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from conftest import Serving

from secondchair.cli import main


def _non_loopback_address() -> str | None:
    """An address of this machine on a real interface, if it has one."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: no packet is sent for UDP connect
        except OSError:
            return None
        address = s.getsockname()[0]
    return None if address.startswith("127.") else address


@pytest.fixture
def served(tmp_path: Path, machine_config: dict[str, str], serving: Serving) -> Iterator[int]:
    ws = tmp_path / "campaign"
    main(["init", str(ws), "--language", "fr", "--calendar", "absalom"])
    with serving(ws, machine_config) as line:
        assert line.startswith("Serving "), line
        yield int(line.rsplit(":", 1)[1])


def test_serve_answers_on_loopback(served: int) -> None:
    with urllib.request.urlopen(f"http://127.0.0.1:{served}/", timeout=5) as response:
        assert json.load(response) == {
            "service": "secondchair",
            "campaign_language": "fr",
            "protocol_version": "0.1.0",
        }


def test_serve_shows_the_review_page_to_a_browser(served: int) -> None:
    request = urllib.request.Request(f"http://127.0.0.1:{served}/", headers={"Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=5) as response:
        assert "SecondChair review" in response.read().decode()
    with urllib.request.urlopen(f"http://127.0.0.1:{served}/api/overview", timeout=5) as response:
        assert json.load(response)["moment"] == "prep"


def test_the_mcp_endpoint_refuses_a_foreign_host_header(served: int) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{served}/mcp",
        data=b"{}",
        headers={"Host": "attacker.example", "Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=5)
    assert refused.value.code == 421


def test_serve_does_not_answer_on_other_interfaces(served: int) -> None:
    address = _non_loopback_address()
    if address is None:
        pytest.skip("this machine has no non-loopback IPv4 interface")
    with pytest.raises(OSError), socket.create_connection((address, served), timeout=2):
        pass


def test_serve_uses_the_port_from_the_machine_configuration(
    tmp_path: Path, machine_config: dict[str, str], serving: Serving
) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = Path(machine_config["XDG_CONFIG_HOME"]) / "secondchair" / "config.yaml"
    config.write_text(f"port: {port}\n")
    ws = tmp_path / "campaign"
    main(["init", str(ws), "--language", "fr", "--calendar", "absalom"])
    with serving(ws, machine_config) as line:
        assert line.endswith(f"http://127.0.0.1:{port}")


@pytest.mark.parametrize(
    ("version", "message"),
    [(2, "newer than the 1 this SecondChair supports"), (0, "secondchair upgrade")],
)
def test_serve_refuses_a_workspace_with_another_schema_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], version: int, message: str
) -> None:
    main(["init", str(tmp_path), "--language", "fr", "--calendar", "absalom"])
    config = tmp_path / "workspace.yaml"
    config.write_text(yaml.safe_dump({"schema_version": version, "campaign_language": "fr"}))

    assert main(["serve", str(tmp_path)]) == 1
    assert message in capsys.readouterr().err


def test_serve_refuses_a_directory_that_is_not_a_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["serve", str(tmp_path)]) == 1
    assert "not a campaign workspace" in capsys.readouterr().err


def test_serve_refuses_an_invalid_port_in_the_machine_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_home = tmp_path / "config"
    (config_home / "secondchair").mkdir(parents=True)
    (config_home / "secondchair" / "config.yaml").write_text("port: 70000\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    ws = tmp_path / "campaign"
    main(["init", str(ws), "--language", "fr", "--calendar", "absalom"])

    assert main(["serve", str(ws)]) == 1
    assert "port must be an integer" in capsys.readouterr().err


@pytest.fixture
def ran(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Path]:
    roots: list[Path] = []
    monkeypatch.setattr("secondchair.cli.serve", lambda ws, *a: roots.append(ws.root.resolve()))
    main(["init", str(tmp_path / "c"), "--language", "en", "--calendar", "absalom"])
    return roots


def test_serve_takes_w(tmp_path: Path, ran: list[Path]) -> None:
    assert main(["serve", "-w", str(tmp_path / "c")]) == 0
    assert ran == [(tmp_path / "c").resolve()]


def test_serve_still_takes_the_positional(tmp_path: Path, ran: list[Path]) -> None:
    assert main(["serve", str(tmp_path / "c")]) == 0
    assert ran == [(tmp_path / "c").resolve()]


def test_serve_accepts_the_same_workspace_twice(tmp_path: Path, ran: list[Path]) -> None:
    c = str(tmp_path / "c")
    assert main(["serve", c, "-w", c]) == 0
    assert len(ran) == 1


def test_serve_defaults_to_the_current_directory(
    tmp_path: Path, ran: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path / "c")
    assert main(["serve"]) == 0
    assert ran == [(tmp_path / "c").resolve()]


def test_serve_refuses_two_different_workspaces(
    tmp_path: Path, ran: list[Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["serve", str(tmp_path), "-w", str(tmp_path / "c")]) == 1
    assert "two different workspaces" in capsys.readouterr().err
    assert ran == []


def test_serve_in_a_non_workspace_cwd_points_to_w(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["serve"]) == 1
    assert "(current directory; use -w DIR)" in capsys.readouterr().err
