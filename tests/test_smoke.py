"""D1 冒烟测试：CLI 装配正常。"""

from typer.testing import CliRunner

from offer_coach.cli import app

runner = CliRunner()


def test_hello() -> None:
    result = runner.invoke(app, ["hello"])
    assert result.exit_code == 0
    assert "装配正常" in result.output
