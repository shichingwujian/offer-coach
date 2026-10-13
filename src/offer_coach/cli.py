"""CLI 入口。"""

from pathlib import Path

import typer
from dotenv import load_dotenv

from offer_coach.engine import EngineConfig, OpenAIProvider, QueryEngine, QueryEngineError
from offer_coach.knowledge.db import build_db
from offer_coach.skills import diagnose

# 搭桥：把 .env 文件读进进程环境变量（不加载它，os.environ 永远看不到 .env）
load_dotenv()

app = typer.Typer(help="offer-coach：面试诊断 Agent CLI", no_args_is_help=True)


@app.callback()
def main() -> None:
    """offer-coach：面试诊断 Agent CLI。"""


@app.command()
def hello() -> None:
    """D1 冒烟命令：确认 CLI 装配正常。"""
    typer.echo("offer-coach 装配正常。下一步：Query Engine。")


@app.command()
def ingest(
    source: Path = typer.Argument(..., help="题库目录（含各分类子目录，每个里面有 index.md）"),
    db: Path = typer.Option(Path("questions.db"), help="输出的数据库文件路径"),
) -> None:
    """灌库：把 markdown 题库解析后灌进 SQLite（FTS5）。一次性动作，可重复跑。"""
    count = build_db(source, db)
    typer.echo(f"灌库完成：{count} 道题 → {db}")


def diagnose_cmd(
    transcript: Path = typer.Argument(..., help="面试稿文件（txt/md）"),
    db: Path = typer.Option(Path("questions.db"), help="题库数据库路径"),
    output: Path | None = typer.Option(None, help="报告输出路径（默认打印到屏幕）"),
) -> None:
    """诊断一份面试稿：分析回答 → 对照题库 → 生成报告。真调模型，会花几分钱。"""
    try:
        provider = OpenAIProvider.from_env()
    except QueryEngineError as e:
        typer.echo(f"环境未配置：{e}", err=True)
        raise typer.Exit(code=1) from e
    engine = QueryEngine(EngineConfig(provider=provider))
    report = diagnose(transcript, engine, db)
    if output:
        output.write_text(report, encoding="utf-8")
        typer.echo(f"报告已写入 {output}")
    else:
        typer.echo(report)
    typer.echo(f"\n本次账单：{engine.usage_summary()}")


# diagnose 作为最常用的命令，注册为 diagnose（函数名带 _cmd 避免和 skills.diagnose 撞名）
app.command(name="diagnose")(diagnose_cmd)


if __name__ == "__main__":
    app()
