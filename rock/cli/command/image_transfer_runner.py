"""沙箱内执行:从 images.txt 并发 crane copy 到目标 ACR。

目标 ACR 写死(DEST_REGISTRY/DEST_NAMESPACE),改环境时改顶部常量。
凭证只走 env (DEST_USER/DEST_PASS 必填,SRC_USER/SRC_PASS 可选),永远不落盘到文件。

本文件会被 image_transfer.py 上传到沙箱 /tmp/transfer_runner.py 并执行,
所以只能使用 Python 标准库,不要 import 任何 rock.* 模块。
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# 写死的目标 ACR 与 namespace
DEST_REGISTRY = "rock-instances-registry-vpc.ap-southeast-1.cr.aliyuncs.com"
DEST_NAMESPACE = "instance"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch transfer registry images to ACR via crane.")
    parser.add_argument("--images-file", required=True)
    parser.add_argument("--dest-registry", default=DEST_REGISTRY, help=f"目标 registry (默认 {DEST_REGISTRY})")
    parser.add_argument("--dest-namespace", default=DEST_NAMESPACE, help=f"目标 namespace (默认 {DEST_NAMESPACE})")
    parser.add_argument("--src-registry", default=None, help="若不传则从 images-file 第一行自动推断")
    parser.add_argument("--concurrency", type=int, default=8, help="镜像级 ThreadPool 并发")
    parser.add_argument("--layer-jobs", type=int, default=4, help="crane --jobs (单镜像 layer 并发)")
    parser.add_argument("--target-path-segments", type=int, default=1, help="目标 repo 保留源路径的最后 N 段 (默认 1)")
    parser.add_argument("--result-file", default="/tmp/result.json")
    parser.add_argument("--timeout", type=int, default=1800, help="单次 crane copy 超时秒")
    return parser.parse_args(argv)


def read_image_list(path: str) -> list[str]:
    """读 images.txt:跳过空行和 # 开头的注释行,自动 strip。"""
    out: list[str] = []
    with open(path) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            out.append(s)
    return out


def derive_target(source: str, dest_registry: str, dest_namespace: str, path_segments: int = 1) -> str:
    """从源镜像推断目标 tag:取 source 路径的最后 N 段 + tag (默认 latest)。

    path_segments=1 (默认):
      docker.io/library/nginx:1.25 -> reg/instance/nginx:1.25
      gcr.io/foo/bar/baz:v1        -> reg/instance/baz:v1
      docker.io/library/nginx      -> reg/instance/nginx:latest

    path_segments=2:
      hub.x.com/aone-base/aone-bench/cr-XXX:tag -> reg/instance/aone-bench/cr-XXX:tag
      docker.io/library/nginx:1.25              -> reg/instance/library/nginx:1.25
    """
    if path_segments < 1:
        raise ValueError(f"path_segments 必须 >= 1, got {path_segments}")
    parts = source.split("/")
    if len(parts) < 2:
        tail = parts[0]
    else:
        repo_parts = parts[1:]
        tail = "/".join(repo_parts[-path_segments:])
    if ":" not in tail:
        tail = f"{tail}:latest"
    return f"{dest_registry}/{dest_namespace}/{tail}"


def infer_src_registry(images: list[str]) -> str:
    if not images:
        raise ValueError("无法从空镜像列表推断源 registry")
    return images[0].split("/", 1)[0]


def crane_login(registry: str, username: str, password: str) -> None:
    """向 ~/.docker/config.json 写入 registry 凭证。密码走 stdin 避免出现在 ps/argv 中。"""
    result = subprocess.run(
        ["crane", "auth", "login", registry, "-u", username, "--password-stdin"],
        input=password,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"crane auth login failed for {registry}: {result.stderr.strip()}")


def copy_one(
    source: str, dest_registry: str, dest_namespace: str, layer_jobs: int, timeout: int, path_segments: int = 1
) -> dict:
    """单镜像 crane copy;返回结构化记录,永不抛异常。"""
    target = derive_target(source, dest_registry, dest_namespace, path_segments)
    t0 = time.monotonic()
    cmd = ["crane", "copy", "--jobs", str(layer_jobs), source, target]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return {
                "source": source,
                "target": target,
                "status": "ok",
                "duration_s": round(time.monotonic() - t0, 3),
                "error": "",
            }
        err = (result.stderr or result.stdout or "").strip()
        if len(err) > 2000:
            err = err[:1000] + "\n...[truncated]...\n" + err[-1000:]
        return {
            "source": source,
            "target": target,
            "status": "fail",
            "duration_s": round(time.monotonic() - t0, 3),
            "error": err or "non-zero exit",
        }
    except subprocess.TimeoutExpired:
        return {
            "source": source,
            "target": target,
            "status": "fail",
            "duration_s": round(time.monotonic() - t0, 3),
            "error": f"timeout after {timeout}s",
        }
    except Exception as e:
        return {
            "source": source,
            "target": target,
            "status": "fail",
            "duration_s": round(time.monotonic() - t0, 3),
            "error": f"exception: {type(e).__name__}: {str(e)[-400:]}",
        }


def cleanup_docker_config(home: str | None = None) -> None:
    """删除 ~/.docker/config.json,避免 sandbox 重用时凭证残留。"""
    home_dir = home or os.path.expanduser("~")
    cfg = os.path.join(home_dir, ".docker", "config.json")
    try:
        os.remove(cfg)
    except FileNotFoundError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    dest_user = os.environ.get("DEST_USER")
    dest_pass = os.environ.get("DEST_PASS")
    if not dest_user or not dest_pass:
        print("ERROR: DEST_USER and DEST_PASS env vars are required", file=sys.stderr)
        raise SystemExit(2)

    src_user = os.environ.get("SRC_USER")
    src_pass = os.environ.get("SRC_PASS")

    images = read_image_list(args.images_file)
    if not images:
        print("ERROR: empty image list", file=sys.stderr)
        return 2

    src_registry = args.src_registry or infer_src_registry(images)

    print(
        f"=== runner start: {len(images)} images, "
        f"concurrency={args.concurrency}, layer_jobs={args.layer_jobs}, "
        f"target_path_segments={args.target_path_segments} ===",
        flush=True,
    )
    print(f"=== dest = {args.dest_registry}/{args.dest_namespace} ===", flush=True)
    print(f"=== src registry = {src_registry} (auth: {'yes' if src_user else 'anonymous'}) ===", flush=True)

    try:
        crane_login(args.dest_registry, dest_user, dest_pass)
        if src_user and src_pass:
            crane_login(src_registry, src_user, src_pass)

        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {
                pool.submit(
                    copy_one,
                    img,
                    args.dest_registry,
                    args.dest_namespace,
                    args.layer_jobs,
                    args.timeout,
                    args.target_path_segments,
                ): img
                for img in images
            }
            for fut in as_completed(futures):
                rec = fut.result()
                results.append(rec)
                marker = "OK" if rec["status"] == "ok" else "FAIL"
                print(f"[{len(results)}/{len(images)}] {marker} ({rec['duration_s']}s) {rec['source']}", flush=True)
                if rec["status"] == "fail":
                    print(f"    err: {rec['error'][:200]}", flush=True)

        with open(args.result_file, "w") as f:
            json.dump(results, f, indent=2)

        n_ok = sum(1 for r in results if r["status"] == "ok")
        n_fail = len(results) - n_ok
        print(f"=== runner done: ok={n_ok} fail={n_fail} result={args.result_file} ===", flush=True)
        return 0 if n_fail == 0 else 1
    finally:
        cleanup_docker_config()


if __name__ == "__main__":
    sys.exit(main())
