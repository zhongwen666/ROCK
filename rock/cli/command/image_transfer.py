"""rock image transfer - 并行起 N 个 Rock 沙箱,把镜像列表批量转储到目标 ACR。

每个沙箱:upload chunk + runner script -> execute -> read result.json -> stop。
凭证只走 env (DEST_USER/DEST_PASS 必填,SRC_USER/SRC_PASS 可选),永远不落盘。

被 ImageCommand 作为 `transfer` 子命令调用,见 rock/cli/command/image.py。
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from rock import env_vars
from rock.actions import Command as SandboxCommand
from rock.actions.sandbox.request import ReadFileRequest
from rock.logger import init_logger
from rock.sdk.sandbox.client import Sandbox
from rock.sdk.sandbox.config import SandboxConfig

logger = init_logger(__name__)


# 与本文件同级的沙箱内 runner 脚本(会上传到沙箱 /tmp/transfer_runner.py)
DEFAULT_RUNNER_SCRIPT = str(Path(__file__).parent / "image_transfer_runner.py")


def _sh_quote(s: str) -> str:
    """单引号包裹字符串供 sh export 使用;处理内嵌的单引号。"""
    return "'" + s.replace("'", "'\\''") + "'"


def split_evenly(items: list, buckets: int) -> list[list]:
    """把 items 均匀切分成 buckets 个连续子列表,元素顺序保留。

    余数被分配到前几个 bucket,例如 5/3 -> [2,2,1]。
    """
    if buckets <= 0:
        raise ValueError(f"buckets must be > 0, got {buckets}")
    base, rem = divmod(len(items), buckets)
    result: list[list] = []
    idx = 0
    for b in range(buckets):
        size = base + (1 if b < rem else 0)
        result.append(items[idx : idx + size])
        idx += size
    return result


def read_image_list(path: str) -> list[str]:
    """与 image_transfer_runner 同语义:跳过注释和空行。"""
    out: list[str] = []
    with open(path) as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                out.append(s)
    return out


async def run_one_sandbox(idx: int, chunk_file: str, args) -> dict:
    """启 1 个沙箱、上传 chunk 和 runner、execute、拉 result.json、stop。

    Returns: {"idx", "status", "sandbox_id", "result_path"|None, "log_path"|None,
              "exit_code", "error"}
    """
    cfg_kwargs = dict(
        image=args.sandbox_image,
        cluster=args.cluster,
        memory=args.memory,
        cpus=args.cpus,
        startup_timeout=args.startup_timeout,
    )
    if getattr(args, "base_url", None):
        cfg_kwargs["base_url"] = args.base_url
    if getattr(args, "auth_token", None):
        cfg_kwargs["xrl_authorization"] = args.auth_token
    # 沙箱拉 base image 需要凭证(沙箱镜像和目标 ACR 同一个 registry)
    cfg_kwargs["registry_username"] = os.environ["DEST_USER"]
    cfg_kwargs["registry_password"] = os.environ["DEST_PASS"]

    config = SandboxConfig(**cfg_kwargs)
    sandbox = Sandbox(config)
    sandbox_id = "?"
    result_path = Path(args.output_dir) / f"result_{idx}.json"

    try:
        await sandbox.start()
        sandbox_id = getattr(sandbox, "sandbox_id", "?")
        print(f"[sb-{idx}] started: {sandbox_id}", flush=True)

        # 直接写文件(HTTP POST),不走 OSS - 文件很小(chunk 几 KB、runner ~6KB)
        await sandbox.write_file_by_path(content=Path(chunk_file).read_text(), path="/tmp/images.txt")
        await sandbox.write_file_by_path(content=Path(args.runner_script).read_text(), path="/tmp/transfer_runner.py")

        # Rock agent 的 execute 有 ~85s 硬超时,长任务必须走 nohup 模式。
        # 把凭证写到 /tmp/run.sh (chmod 700),免得出现在 ps/cmdline 里。
        runner_cli = (
            "python3 /tmp/transfer_runner.py "
            "--images-file /tmp/images.txt "
            f"--dest-registry {args.dest_registry} "
            f"--dest-namespace {args.dest_namespace} "
            f"--concurrency {args.concurrency} "
            f"--layer-jobs {args.layer_jobs} "
            f"--target-path-segments {args.target_path_segments} "
            f"--timeout {args.timeout} "
            "--result-file /tmp/result.json"
        )
        if args.src_registry:
            runner_cli += f" --src-registry {args.src_registry}"

        src_user = os.environ.get("SRC_USER", "")
        src_pass = os.environ.get("SRC_PASS", "")
        # shell 脚本:set env 后 exec runner,stdout/stderr 重定向到 /tmp/runner.log
        wrapper = (
            "#!/bin/sh\n"
            "set -e\n"
            "export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'\n"
            "export HOME='/root'\n"
            "export LANG='C.UTF-8'\n"
            f"export DEST_USER={_sh_quote(os.environ['DEST_USER'])}\n"
            f"export DEST_PASS={_sh_quote(os.environ['DEST_PASS'])}\n"
        )
        if src_user and src_pass:
            wrapper += f"export SRC_USER={_sh_quote(src_user)}\nexport SRC_PASS={_sh_quote(src_pass)}\n"
        wrapper += f"exec {runner_cli} > /tmp/runner.log 2>&1\n"

        await sandbox.write_file_by_path(content=wrapper, path="/tmp/run.sh")
        await sandbox.execute(SandboxCommand(command=["chmod", "700", "/tmp/run.sh"], env={"PATH": "/usr/bin:/bin"}))
        print(f"[sb-{idx}] wrote chunk + runner + wrapper (direct, no OSS)", flush=True)

        # nohup 模式:runner 后台跑,client 每 15s 轮询,最长等 args.timeout * 2 秒
        wait_total = max(args.timeout * 2, 600)
        result = await sandbox.arun(
            cmd="sh /tmp/run.sh",
            mode="nohup",
            wait_timeout=wait_total,
            wait_interval=15,
        )
        rc = getattr(result, "exit_code", None)
        nohup_failure = getattr(result, "failure_reason", "") or ""
        # arun 的 output 是 nohup 重定向输出(我们已重定向到 /tmp/runner.log,所以这里通常为空或截断)
        # 真正的 runner 日志去 /tmp/runner.log 拉
        runner_log = ""
        try:
            log_resp = await sandbox.read_file(ReadFileRequest(path="/tmp/runner.log"))
            runner_log = log_resp.content if hasattr(log_resp, "content") else str(log_resp)
        except Exception as e:
            runner_log = f"<failed to read /tmp/runner.log: {e}>"

        print(
            f"[sb-{idx}] runner returned: exit_code={rc} log={len(runner_log)}B nohup_failure={nohup_failure!r}",
            flush=True,
        )

        # 把完整 runner.log 落盘
        log_path = Path(args.output_dir) / f"sandbox_{idx}.log"
        log_path.write_text(
            f"=== sandbox_id: {sandbox_id} ===\n"
            f"=== chunk_file: {chunk_file} ===\n"
            f"=== exit_code: {rc} ===\n"
            f"=== nohup_failure: {nohup_failure} ===\n"
            f"=== runner.log ({len(runner_log)}B) ===\n{runner_log}\n"
        )

        # 转发 runner.log 末尾到 console
        for line in runner_log.splitlines()[-80:]:
            print(f"[sb-{idx}] {line}", flush=True)

        # 拉回 result.json
        read_err: str | None = None
        try:
            resp = await sandbox.read_file(ReadFileRequest(path="/tmp/result.json"))
            if hasattr(resp, "content"):
                text = resp.content
            elif isinstance(resp, bytes | bytearray):
                text = resp.decode("utf-8")
            else:
                text = str(resp)
            result_path.write_text(text or "")
            if not text:
                read_err = "result.json empty (runner likely crashed before writing)"
        except Exception as e:
            read_err = f"read result failed: {type(e).__name__}: {e}"
            print(f"[sb-{idx}] WARN: {read_err}", flush=True)

        status = "ok" if (rc == 0 and not read_err) else "fail"
        err_msg = ""
        if status == "fail":
            parts = [f"runner exit_code={rc}"]
            if nohup_failure:
                parts.append(f"nohup: {nohup_failure}")
            if read_err:
                parts.append(read_err)
            if runner_log.strip():
                parts.append(f"log tail: {runner_log.strip().splitlines()[-1][:200]}")
            err_msg = " | ".join(parts)
        return {
            "idx": idx,
            "status": status,
            "sandbox_id": sandbox_id,
            "result_path": str(result_path) if not read_err else None,
            "log_path": str(log_path),
            "exit_code": rc,
            "error": err_msg,
        }

    except Exception as e:
        return {
            "idx": idx,
            "status": "fail",
            "sandbox_id": sandbox_id,
            "result_path": None,
            "log_path": None,
            "exit_code": None,
            "error": f"{type(e).__name__}: {str(e)[-400:]}",
        }
    finally:
        try:
            await sandbox.stop()
            print(f"[sb-{idx}] stopped", flush=True)
        except Exception as e:
            print(f"[sb-{idx}] WARN: stop failed: {e}", flush=True)


def add_transfer_subparser(image_subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """注册 `rock image transfer` 子命令的所有 flag。

    被 ImageCommand.add_parser_to 调用。base_url/auth_token/cluster 由 rock CLI 全局参数提供,
    本子命令不再重复定义。
    """
    dest_registry = env_vars.ROCK_IMAGE_TRANSFER_DEST_REGISTRY
    dest_namespace = env_vars.ROCK_IMAGE_TRANSFER_DEST_NAMESPACE
    sandbox_image = env_vars.ROCK_IMAGE_TRANSFER_SANDBOX_IMAGE

    p = image_subparsers.add_parser(
        "transfer",
        help="并行起 N 个沙箱,把镜像列表批量转储到目标 ACR",
        description=(
            "并行起 N 个 Rock 沙箱,把镜像列表转储到目标 ACR。\n"
            "需要 env (或 CLI flag):\n"
            "  ROCK_IMAGE_TRANSFER_DEST_REGISTRY   - 目标 registry 域名 (or --dest-registry)\n"
            "  ROCK_IMAGE_TRANSFER_DEST_NAMESPACE  - 目标 namespace      (or --dest-namespace)\n"
            "  ROCK_IMAGE_TRANSFER_SANDBOX_IMAGE   - 沙箱基础镜像        (or --sandbox-image)\n"
            "  DEST_USER, DEST_PASS                - 目标 registry 凭证 (必填)\n"
            "  SRC_USER, SRC_PASS                  - 源 registry 凭证   (私有源仓库时填)\n"
            "需要全局 flag: --cluster <rock-cluster> (沙箱集群标识)。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--images-file", required=True, help="每行一个镜像,# 开头为注释")
    p.add_argument(
        "--sandbox-image",
        default=sandbox_image,
        help="沙箱基础镜像 (默认读 $ROCK_IMAGE_TRANSFER_SANDBOX_IMAGE)",
    )
    p.add_argument(
        "--dest-registry",
        default=dest_registry,
        help="目标 registry (默认读 $ROCK_IMAGE_TRANSFER_DEST_REGISTRY)",
    )
    p.add_argument(
        "--dest-namespace",
        default=dest_namespace,
        help="目标 namespace (默认读 $ROCK_IMAGE_TRANSFER_DEST_NAMESPACE)",
    )
    p.add_argument("--sandboxes", type=int, default=4, help="并行沙箱数 N")
    p.add_argument("--concurrency", type=int, default=8, help="单沙箱内 ThreadPool 大小 M")
    p.add_argument("--layer-jobs", type=int, default=4, help="crane --jobs K (layer 并发)")
    p.add_argument("--target-path-segments", type=int, default=1, help="目标 repo 保留源路径的最后 N 段 (默认 1)")
    p.add_argument("--src-registry", default=None, help="不传则 runner 自动从 images.txt 推断")
    p.add_argument("--memory", default="8g")
    p.add_argument("--cpus", type=int, default=4)
    p.add_argument("--startup-timeout", type=int, default=180)
    p.add_argument("--timeout", type=int, default=1800, help="runner 内单镜像 crane copy 超时")
    p.add_argument("--output-dir", default=None, help="本地结果落地目录,默认 ./results/<timestamp>/")
    p.add_argument("--runner-script", default=DEFAULT_RUNNER_SCRIPT, help="本地 transfer_runner 脚本路径(会上传到沙箱)")
    return p


def aggregate_results(sandbox_outcomes: list[dict]) -> dict:
    """合并所有 result_*.json 并打印汇总。"""
    total = ok = fail = 0
    failed_images: list[dict] = []
    failed_sandboxes: list[dict] = []
    sandboxes_ok = sum(1 for o in sandbox_outcomes if o["status"] == "ok")
    sandboxes_fail = len(sandbox_outcomes) - sandboxes_ok

    for outcome in sandbox_outcomes:
        if outcome["status"] == "fail":
            failed_sandboxes.append(
                {
                    "idx": outcome.get("idx"),
                    "sandbox_id": outcome.get("sandbox_id"),
                    "exit_code": outcome.get("exit_code"),
                    "log_path": outcome.get("log_path"),
                    "error": outcome.get("error", ""),
                }
            )
        if not outcome.get("result_path"):
            continue
        try:
            data = json.loads(Path(outcome["result_path"]).read_text() or "[]")
        except Exception:
            continue
        for r in data:
            total += 1
            if r["status"] == "ok":
                ok += 1
            else:
                fail += 1
                failed_images.append(r)
    return {
        "total": total,
        "ok": ok,
        "fail": fail,
        "sandboxes_ok": sandboxes_ok,
        "sandboxes_fail": sandboxes_fail,
        "failed_images": failed_images,
        "failed_sandboxes": failed_sandboxes,
    }


async def run_transfer(args: argparse.Namespace) -> int:
    """`rock image transfer` 的入口,被 ImageCommand.arun 调用。"""
    # 早失败:必填 env
    if not os.environ.get("DEST_USER") or not os.environ.get("DEST_PASS"):
        print("ERROR: DEST_USER and DEST_PASS env vars are required", file=sys.stderr)
        return 2

    # 必填 cluster (由 rock CLI 全局 --cluster 或 config 提供)
    if not getattr(args, "cluster", None):
        print("ERROR: --cluster is required (Rock 沙箱集群标识,如 vpc-sg-b)", file=sys.stderr)
        return 2

    # dest registry / namespace / sandbox image:env_vars 默认空,需 env 或 CLI 显式提供
    missing = []
    if not args.dest_registry:
        missing.append("--dest-registry (or $ROCK_IMAGE_TRANSFER_DEST_REGISTRY)")
    if not args.dest_namespace:
        missing.append("--dest-namespace (or $ROCK_IMAGE_TRANSFER_DEST_NAMESPACE)")
    if not args.sandbox_image:
        missing.append("--sandbox-image (or $ROCK_IMAGE_TRANSFER_SANDBOX_IMAGE)")
    if missing:
        print("ERROR: required value(s) missing: " + ", ".join(missing), file=sys.stderr)
        return 2

    # 校验 runner 脚本存在
    if not Path(args.runner_script).is_file():
        print(f"ERROR: runner script not found: {args.runner_script}", file=sys.stderr)
        return 2

    images = read_image_list(args.images_file)
    if not images:
        print("ERROR: empty images list", file=sys.stderr)
        return 2

    # 准备 output dir
    if args.output_dir is None:
        args.output_dir = f"./results/{time.strftime('%Y%m%d-%H%M%S')}"
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 切分 + 写 chunk_i.txt
    chunks = split_evenly(images, args.sandboxes)
    chunk_files: list[str] = []
    for i, chunk in enumerate(chunks):
        cf = out_dir / f"chunk_{i}.txt"
        cf.write_text("\n".join(chunk) + ("\n" if chunk else ""))
        chunk_files.append(str(cf))

    # 跳过空 chunk (当 images 数 < sandboxes 时)
    tasks = []
    for i, cf in enumerate(chunk_files):
        if not chunks[i]:
            print(f"[sb-{i}] skipped: empty chunk", flush=True)
            continue
        tasks.append(run_one_sandbox(i, cf, args))

    print(
        f"=== orchestrator start: {len(images)} images / {len(tasks)} sandboxes (cluster={args.cluster}) ===",
        flush=True,
    )
    print(f"=== concurrency per sandbox = {args.concurrency}, layer jobs = {args.layer_jobs} ===", flush=True)

    t0 = time.monotonic()
    outcomes = await asyncio.gather(*tasks, return_exceptions=False)
    elapsed = time.monotonic() - t0

    summary = aggregate_results(outcomes)
    summary["elapsed_s"] = round(elapsed, 1)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print("", flush=True)
    print("=== orchestrator done ===", flush=True)
    print(f"  elapsed         : {elapsed:.1f}s", flush=True)
    print(f"  sandboxes ok/fail : {summary['sandboxes_ok']}/{summary['sandboxes_fail']}", flush=True)
    print(f"  images total      : {summary['total']}", flush=True)
    print(f"  images ok         : {summary['ok']}", flush=True)
    print(f"  images fail       : {summary['fail']}", flush=True)
    print(f"  output dir        : {out_dir}", flush=True)
    if summary.get("failed_sandboxes"):
        print("  --- failed sandboxes ---", flush=True)
        for s in summary["failed_sandboxes"]:
            print(f"    sb-{s['idx']} (id={s['sandbox_id']}): {s['error']}", flush=True)
            if s.get("log_path"):
                print(f"      log: {s['log_path']}", flush=True)
    if summary["failed_images"]:
        print("  --- failed images (first 10) ---", flush=True)
        for r in summary["failed_images"][:10]:
            print(f"    {r['source']}: {r['error'][:100]}", flush=True)
    print(f"  detailed summary  : {out_dir}/summary.json", flush=True)

    return 0 if (summary["fail"] == 0 and summary["sandboxes_fail"] == 0) else 1
