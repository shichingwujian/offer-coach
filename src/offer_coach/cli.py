"""CLI 入口。"""

import re
from pathlib import Path

import typer
from dotenv import load_dotenv

from offer_coach.context import ContextManager
from offer_coach.engine import EngineConfig, Message, OpenAIProvider, QueryEngine, QueryEngineError
from offer_coach.evaluation import format_report, load_eval_set, run_recall
from offer_coach.hooks import HookPipeline, truncate_hook
from offer_coach.knowledge.db import build_db, build_vectors, search_hybrid, search_questions, search_smart
from offer_coach.memory import MemoryStore, make_memory_hook, recall_block
from offer_coach.permission import PermissionGate
from offer_coach.skills import diagnose
from offer_coach.tools import ToolRegistry, default_registry, run_loop

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
    vectors: bool = typer.Option(False, "--vectors", help="同时建向量索引（D13 混合召回用；首次运行下载约 100MB 模型）"),
) -> None:
    """灌库：把 markdown 题库解析后灌进 SQLite（FTS5）。一次性动作，可重复跑。"""
    count = build_db(source, db)
    typer.echo(f"灌库完成：{count} 道题 → {db}")
    if vectors:
        from offer_coach.knowledge.embedder import FastEmbedder  # 懒加载：要了才下载模型

        n = build_vectors(db, FastEmbedder())
        typer.echo(f"向量索引完成：{n} 道题的语义坐标已入库")


def diagnose_cmd(
    transcript: Path = typer.Argument(..., help="面试稿文件（txt/md）；--resume 时忽略"),
    db: Path = typer.Option(Path("questions.db"), help="题库数据库路径"),
    output: Path | None = typer.Option(None, help="报告输出路径（默认打印到屏幕）"),
    session: str | None = typer.Option(None, help="存档名：跑完存到 sessions/<名字>.json"),
    resume: bool = typer.Option(False, "--resume", help="从存档续跑（需配合 --session）"),
    memory: Path = typer.Option(Path("memory.db"), "--memory", help="记忆库路径：跨次诊断记住候选人弱点"),
) -> None:
    """诊断一份面试稿：分析回答 → 对照题库 → 生成报告。真调模型，会花几分钱。"""
    if resume and not session:
        typer.echo("--resume 需要配合 --session <存档名>", err=True)
        raise typer.Exit(code=1)
    try:
        provider = OpenAIProvider.from_env()
    except QueryEngineError as e:
        typer.echo(f"环境未配置：{e}", err=True)
        raise typer.Exit(code=1) from e
    engine = QueryEngine(EngineConfig(provider=provider))
    # 权限闸（D8）：注入"真问用户"的函数——人在环中
    gate = PermissionGate(ask=lambda q: input(q).strip().lower() in ("y", "yes"))
    store = MemoryStore(memory)  # 档案柜（D10）：不存在会自动建
    session_path = Path("sessions") / f"{session}.json" if session else None
    report = diagnose(
        transcript, engine, db, gate=gate, session_path=session_path, resume=resume,
        memory=store,
    )
    if output:
        output.write_text(report, encoding="utf-8")
        typer.echo(f"报告已写入 {output}")
    else:
        typer.echo(report)
    if session_path:
        typer.echo(f"存档：{session_path}（--resume 可续跑）")
    stats = store.stats()
    typer.echo(f"档案柜：{stats['total']} 条记忆（{memory}）")
    typer.echo(f"\n本次账单：{engine.usage_summary()}")


# diagnose 作为最常用的命令，注册为 diagnose（函数名带 _cmd 避免和 skills.diagnose 撞名）
app.command(name="diagnose")(diagnose_cmd)


@app.command(name="eval")
def eval_cmd(
    eval_set: Path = typer.Option(Path("eval/recall_set.jsonl"), "--set", help="评估集路径（JSONL）"),
    db: Path = typer.Option(Path("questions.db"), help="题库数据库路径"),
    k: int = typer.Option(5, help="recall@k 的 k（前 k 个结果里命中即算中）"),
    mode: str = typer.Option("phrase", help="检索模式：phrase=整句短语（基线）/ terms=拆词OR（D12）/ hybrid=混合召回（D13）"),
) -> None:
    """召回评估：跑评估集出 recall@k。纯本地检索，零模型调用、零成本。"""
    cases = load_eval_set(eval_set)
    # 注入被测的检索函数（同一接口换内脏：基线短语 vs D12 拆词 vs D13 混合召回）
    if mode == "phrase":
        search = lambda q: search_questions(db, q, limit=k)
    elif mode == "terms":
        search = lambda q: search_smart(db, q, limit=k)
    elif mode == "hybrid":
        from offer_coach.knowledge.embedder import FastEmbedder  # 懒加载：只有真跑混合才下载模型

        embedder = FastEmbedder()
        search = lambda q: search_hybrid(db, q, limit=k, embedder=embedder)
    else:
        typer.echo(f"未知模式 {mode}，可选：phrase / terms / hybrid", err=True)
        raise typer.Exit(code=1)
    report = run_recall(cases, search, k=k)
    typer.echo(f"检索模式：{mode}")
    typer.echo(format_report(report))


_PROFILE_KEYS = {"岗位": "target_role", "技术栈": "tech_stack"}


def _handle_profile(cmd: str, store: MemoryStore) -> str:
    """/profile 看画像；/profile 岗位=后端开发 写画像。死规则写入，不让模型猜。"""
    rest = cmd.removeprefix("/profile").strip()
    if not rest:
        profile = store.get_profile()
        if not profile:
            return "（暂无画像。用 /profile 岗位=xxx 或 /profile 技术栈=A,B 写入）"
        return "当前画像：\n" + "\n".join(f"- {k}：{v}" for k, v in profile.items())
    if "=" not in rest:
        return "用法：/profile 岗位=后端开发 或 /profile 技术栈=Python,Go"
    key, value = (s.strip() for s in rest.split("=", 1))
    if key not in _PROFILE_KEYS:
        return f"不认识字段 '{key}'。可写：{'、'.join(_PROFILE_KEYS)}"
    if key == "技术栈":
        store.update_profile({"tech_stack": [s for s in re.split(r"[,，、]", value) if s]})
    else:
        store.update_profile({"target_role": value})
    return f"已记住：{key} = {value}"


def handle_command(
    cmd: str,
    engine: QueryEngine,
    registry: ToolRegistry,
    store: MemoryStore | None = None,  # 可选：档案柜（D10），没装就禁用 /profile /memory
) -> str | None:
    """斜杠命令直达电梯：绕过模型，确定性执行。返回 None 表示退出对话。"""
    if cmd == "/exit":
        return None
    if cmd == "/cost":
        return f"账单：{engine.usage_summary()}"
    if cmd == "/tools":
        lines = [f"- {s['name']}：{s['description']}" for s in registry.schemas()]
        return "可用工具：\n" + "\n".join(lines)
    if cmd.startswith("/profile"):
        if store is None:
            return "（未装配记忆库，/profile 不可用）"
        return _handle_profile(cmd, store)
    if cmd == "/memory":
        if store is None:
            return "（未装配记忆库，/memory 不可用）"
        stats = store.stats()
        lines = [f"记忆总数：{stats['total']}（{stats['by_type']}）"]
        weaks = store.retrieve(type="weak_point", limit=5)
        lines += [f"- {w.key} 坐实度 {w.confidence:.1f}" for w in weaks]
        return "\n".join(lines)
    return f"未知命令 {cmd}。可用：/cost（账单）/tools（工具清单）/profile（画像）/memory（记忆）/exit（退出）"


def chat_cmd(
    db: Path = typer.Option(Path("questions.db"), help="题库数据库路径"),
    memory: Path = typer.Option(Path("memory.db"), "--memory", help="记忆库路径"),
) -> None:
    """对话模式：和面试教练多轮聊天。斜杠命令：/cost /tools /profile /memory /exit。"""
    try:
        provider = OpenAIProvider.from_env()
    except QueryEngineError as e:
        typer.echo(f"环境未配置：{e}", err=True)
        raise typer.Exit(code=1) from e
    engine = QueryEngine(EngineConfig(provider=provider))
    registry = default_registry(engine, db)
    gate = PermissionGate(ask=lambda q: input(q).strip().lower() in ("y", "yes"))
    store = MemoryStore(memory)  # 档案柜（D10）
    pipeline = HookPipeline()
    pipeline.add_pre(gate.as_hook())
    pipeline.add_post(make_memory_hook(store))
    pipeline.add_post(truncate_hook(2000))
    # 开局召回：老用户的历史档案注入 system prompt
    system_text = "你是一位资深技术面试官和面试教练，回答简洁、直接给建议。"
    block = recall_block(store)
    if block:
        system_text += f"\n\n这位用户的历史档案：\n{block}"
    history = [Message(role="system", content=system_text)]

    typer.echo("进入对话模式。直接打字聊天；斜杠命令：/cost /tools /profile /memory /exit")
    while True:
        user_input = input("\n你：").strip()
        if not user_input:
            continue
        if user_input.startswith("/"):
            output = handle_command(user_input, engine, registry, store)
            if output is None:
                typer.echo("已退出对话模式。")
                break
            typer.echo(output)
            continue
        history.append(Message(role="user", content=user_input))
        result = run_loop(engine, registry, history, context=ContextManager(), hooks=pipeline)
        history = result.messages
        if result.status == "completed":
            typer.echo(f"\n教练：{result.final_text}")
        else:
            typer.echo(f"\n（对话中断：{result.status}，请换个问法重试）")


app.command(name="chat")(chat_cmd)


if __name__ == "__main__":
    app()
