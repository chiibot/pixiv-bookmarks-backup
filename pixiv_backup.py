#!/usr/bin/env python3
"""
Pixiv收藏夹增量下载工具
基于 pixivpy3 库，支持断点续传和增量更新。

使用方法：
1. 先运行 get_token.py 获取 refresh_token
2. 编辑 config.json 填入你的配置
3. 运行: python pixiv_backup.py

首次运行会全量下载收藏夹，之后每次运行只下载新增的收藏。
"""

import json
import os
import sys
import time
import hashlib
from pathlib import Path
from datetime import datetime

try:
    from pixivpy3 import AppPixivAPI
except ImportError:
    print("请先安装 pixivpy3: pip install pixivpy3")
    sys.exit(1)


# ── 配置 ──────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "config.json"
DEFAULT_CONFIG = {
    "refresh_token": "",
    "output_dir": os.path.expanduser("~/Pictures/pixiv_bookmarks"),
    "download_private": False,
    "delay_between_downloads": 0.5,
    "max_pages_per_run": 0,  # 0=不限制，下载全部
    "filename_pattern": "{id}_p{page}.{ext}",
    "skip_ai_generated": False,
}


def load_config():
    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        print(f"[!] 已生成配置文件: {CONFIG_FILE}")
        print(f"    请编辑 config.json 填入 refresh_token 后重新运行。")
        sys.exit(0)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    if not cfg.get("refresh_token"):
        print("[!] config.json 中 refresh_token 为空。")
        print("    请先运行 python get_token.py 获取 token。")
        sys.exit(1)

    return cfg


def get_state_file(output_dir):
    return Path(output_dir) / "state.json"


def load_state(state_file):
    if state_file.exists():
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"downloaded_ids": [], "last_bookmark_id": None, "run_count": 0}


def save_state(state_file, state):
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ── API ────────────────────────────────────────────────

def create_api():
    api = AppPixivAPI()
    api.set_accept_language("zh-CN")
    # 使用国内可用的图片代理（如果需要可取消注释）
    # api.set_api_proxy("https://pixiv.rmb521.com")
    return api


def authenticate(api, refresh_token):
    print("[*] 正在认证...")
    api.auth(refresh_token=refresh_token)
    print("[+] 认证成功")


def fetch_all_bookmarks(api, downloaded_ids, user_id="me", restrict="public", max_pages=0):
    """分页获取所有收藏的作品ID和元数据"""
    bookmarks = []
    max_bookmark_id = None
    page = 0

    while True:
        page += 1
        if max_pages and page > max_pages:
            print(f"[*] 达到页数上限 ({max_pages})，停止获取。")
            break

        print(f"[*] 正在获取第 {page} 页收藏...")
        result = api.user_bookmarks_illust(
            user_id=user_id,
            restrict=restrict,
            max_bookmark_id=max_bookmark_id,
        )

        if not result or not result.get("illusts"):
            print(f"[*] 没有更多收藏了（共 {len(bookmarks)} 个作品）。")
            break

        hit_existing = False
        for illust in result["illusts"]:
            if illust["id"] in downloaded_ids:
                hit_existing = True
            bookmarks.append({
                "id": illust["id"],
                "title": illust.get("title", ""),
                "user_name": illust.get("user", {}).get("name", ""),
                "user_id": illust.get("user", {}).get("id", ""),
                "page_count": illust.get("page_count", 1),
                "meta_pages": illust.get("meta_pages", []),
                "image_urls": illust.get("image_urls", {}),
                "create_date": illust.get("create_date", ""),
                "type": illust.get("type", ""),
                "tags": [t.get("name", "") for t in illust.get("tags", [])],
            })

        if hit_existing:
            print("[*] 本页命中已下载作品，停止继续翻页。")
            break

        # 下一页
        next_max = result.get("next_url")
        if not next_max:
            print(f"[*] 获取完毕（共 {len(bookmarks)} 个作品）。")
            break

        # 从 next_url 解析 max_bookmark_id
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(next_max)
        params = parse_qs(parsed.query)
        max_bookmark_id = params.get("max_bookmark_id", [None])[0]
        if not max_bookmark_id:
            break

        time.sleep(0.3)

    return bookmarks


def _safe_name(name):
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name)


def get_artist_dir(output_dir, user_id, user_name):
    output_dir = Path(output_dir)
    matches = sorted(output_dir.glob(f"{user_id}-*"))
    if matches:
        return matches[0]
    return output_dir / f"{user_id}-{_safe_name(user_name)}"


def download_illust(api, illust, output_dir, filename_pattern, delay):
    """下载单个作品的所有图片"""
    illust_id = illust["id"]
    user_name = illust["user_name"]
    page_count = illust["page_count"]

    # 创建画师目录
    artist_dir = get_artist_dir(output_dir, illust["user_id"], user_name)
    artist_dir.mkdir(parents=True, exist_ok=True)

    downloaded_files = []
    detail = None
    try:
        detail = api.illust_detail(illust_id)
    except Exception:
        detail = None

    if page_count == 1:
        # 单图：优先下载原图
        urls = []
        if detail and detail.get("illust"):
            original = (
                detail["illust"].get("meta_single_page", {}).get("original_image_url")
            )
            if original:
                urls.append(original)

        # 回退：从列表数据获取（可能不是原图）
        if not urls and illust["meta_pages"]:
            for page in illust["meta_pages"]:
                if page.get("image_urls", {}).get("large"):
                    urls.append(page["image_urls"]["large"])

        if urls:
            url = urls[0]
            ext = url.split(".")[-1].split("?")[0]
            if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                ext = "jpg"
            fname = filename_pattern.format(
                id=illust_id, page=0, ext=ext,
                title=illust["title"], user=user_name
            )
            fpath = artist_dir / fname
            if not fpath.exists():
                api.download(url, path=str(artist_dir), fname=fname)
                downloaded_files.append(str(fpath))
                time.sleep(delay)
    else:
        # 多图：优先下载原图
        pages = []
        if detail and detail.get("illust", {}).get("meta_pages"):
            pages = detail["illust"]["meta_pages"]
        if not pages:
            pages = illust["meta_pages"]

        for i, page in enumerate(pages):
            url = page.get("image_urls", {}).get("original")
            if not url:
                url = page.get("image_urls", {}).get("large")
            if not url:
                url = page.get("image_urls", {}).get("medium")
            if not url:
                continue

            ext = url.split(".")[-1].split("?")[0]
            if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                ext = "jpg"
            fname = f"{illust_id}_p{i}.{ext}"
            fpath = artist_dir / fname
            if not fpath.exists():
                api.download(url, path=str(artist_dir), fname=fname)
                downloaded_files.append(str(fpath))
                time.sleep(delay)

    return downloaded_files


# ── 主流程 ─────────────────────────────────────────────

def main():
    print("=" * 50)
    print("  Pixiv 收藏夹增量下载工具")
    print("=" * 50)

    cfg = load_config()
    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    state_file = get_state_file(output_dir)
    state = load_state(state_file)
    api = create_api()

    try:
        authenticate(api, cfg["refresh_token"])
    except Exception as e:
        print(f"[!] 认证失败: {e}")
        print("    请检查 refresh_token 是否正确，或重新获取。")
        sys.exit(1)

    # 获取用户ID
    try:
        my_info = api.user_detail(api.user_id)
        user_name = my_info.get("user", {}).get("name", "unknown")
        print(f"[+] 当前用户: {user_name} (ID: {api.user_id})")
    except Exception:
        print(f"[!] 无法获取用户信息，使用 user_id={api.user_id}")

    # 获取收藏列表
    restrict = "private" if cfg.get("download_private") else "public"
    downloaded_ids = set(state.get("downloaded_ids", []))
    bookmarks = fetch_all_bookmarks(
        api,
        downloaded_ids=downloaded_ids,
        user_id=str(api.user_id),
        restrict=restrict,
        max_pages=cfg.get("max_pages_per_run", 0),
    )

    if not bookmarks:
        print("[*] 没有找到收藏的作品。")
        return

    # 增量过滤：跳过已下载的
    new_bookmarks = [b for b in bookmarks if b["id"] not in downloaded_ids]

    print(f"\n[*] 收藏总数: {len(bookmarks)}")
    print(f"[*] 已下载: {len(downloaded_ids)}")
    print(f"[*] 新增: {len(new_bookmarks)}")

    if not new_bookmarks:
        print("[*] 没有新的收藏需要下载。")
        state["run_count"] = state.get("run_count", 0) + 1
        save_state(state_file, state)
        return

    # 下载
    output_dir = cfg["output_dir"]
    pattern = cfg.get("filename_pattern", DEFAULT_CONFIG["filename_pattern"])
    delay = cfg.get("delay_between_downloads", 0.5)

    total_downloaded = 0
    failed = []

    for i, bookmark in enumerate(new_bookmarks, 1):
        print(f"\n[{i}/{len(new_bookmarks)}] {bookmark['title']} (ID: {bookmark['id']})")
        try:
            files = download_illust(api, bookmark, output_dir, pattern, delay)
            if files:
                total_downloaded += len(files)
                state["downloaded_ids"].append(bookmark["id"])
                downloaded_ids.add(bookmark["id"])
                save_state(state_file, state)
                print(f"  -> 下载了 {len(files)} 个文件")
            else:
                print(f"  -> 未能获取下载链接")
        except Exception as e:
            print(f"  -> 下载失败: {e}")
            failed.append({"id": bookmark["id"], "error": str(e)})

    # 最终保存
    state["last_bookmark_id"] = bookmarks[-1]["id"] if bookmarks else None
    state["run_count"] = state.get("run_count", 0) + 1
    state["last_run"] = datetime.now().isoformat()
    save_state(state_file, state)

    # 报告
    print("\n" + "=" * 50)
    print(f"  下载完成")
    print(f"  新下载: {total_downloaded} 个文件")
    print(f"  失败: {len(failed)} 个")
    if failed:
        print(f"  失败列表:")
        for f in failed:
            print(f"    - ID {f['id']}: {f['error']}")
    print(f"  输出目录: {output_dir}")
    print("=" * 50)


if __name__ == "__main__":
    main()
