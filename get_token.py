#!/usr/bin/env python3
"""
Pixiv refresh_token 获取工具（手动OAuth流程）。

运行后会：
1. 生成一个授权URL，在浏览器中打开
2. 你登录Pixiv后，浏览器会跳转到 pixiv://...?code=xxx
3. 复制那个URL粘贴回来
4. 自动换取refresh_token并保存到config.json
"""

import hashlib
import json
import secrets
import sys
import time
import base64
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

CONFIG_FILE = Path(__file__).parent / "config.json"

# Pixiv Android app 的公开凭据
CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"


def generate_pkce():
    """生成PKCE code_verifier 和 code_challenge"""
    code_verifier = secrets.token_urlsafe(32)
    # S256: SHA256 hash, base64url encode
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def get_auth_url(code_challenge):
    """构建Pixiv OAuth授权URL"""
    return (
        f"https://app-api.pixiv.net/web/v1/login"
        f"?code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&client=pixiv-android"
    )


def exchange_code_for_token(auth_code, code_verifier):
    """用authorization code换取refresh_token"""
    headers = {
        "User-Agent": "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": auth_code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "include_policy": "true",
        "redirect_uri": "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback",
    }
    resp = requests.post(
        "https://oauth.secure.pixiv.net/auth/token",
        headers=headers,
        data=data,
    )
    return resp


def save_config(refresh_token):
    """保存refresh_token到config.json"""
    config = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

    config["refresh_token"] = refresh_token

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def verify_token(refresh_token):
    """验证token是否可用"""
    from pixivpy3 import AppPixivAPI

    api = AppPixivAPI()
    api.auth(refresh_token=refresh_token)
    my_info = api.user_detail(api.user_id)
    user_name = my_info.get("user", {}).get("name", "unknown")
    return user_name, api.user_id


def main():
    print("=" * 55)
    print("  Pixiv Refresh Token 获取工具")
    print("=" * 55)

    # 1. 生成PKCE
    code_verifier, code_challenge = generate_pkce()

    # 2. 生成授权URL
    auth_url = get_auth_url(code_challenge)

    print()
    print("[步骤1] 请在浏览器中打开以下URL并登录Pixiv：")
    print()
    print(f"  {auth_url}")
    print()

    # 尝试自动打开浏览器
    import webbrowser
    try:
        webbrowser.open(auth_url)
        print("  (已尝试自动打开浏览器)")
    except Exception:
        print("  (请手动复制URL到浏览器)")

    print()
    print("[步骤2] 登录成功后，浏览器会跳转到一个 pixiv://... 开头的URL")
    print("        请复制完整的URL并粘贴到这里。")
    print()

    redirect_url = input("粘贴URL: ").strip()

    if not redirect_url:
        print("[!] URL为空，退出。")
        sys.exit(1)

    # 3. 提取auth_code
    # URL格式: pixiv://account/login?code=xxx&...
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)
    auth_code = params.get("code", [None])[0]

    if not auth_code:
        # 有些情况下code可能在fragment中
        fragment = parsed.fragment
        if fragment:
            frag_params = parse_qs(fragment)
            auth_code = frag_params.get("code", [None])[0]

    if not auth_code:
        print(f"[!] 无法从URL中提取code。")
        print(f"    解析结果: scheme={parsed.scheme}, query={parsed.query}, fragment={parsed.fragment}")
        sys.exit(1)

    print(f"[+] 提取到code: {auth_code[:10]}...")

    # 4. 换取token
    print("[*] 正在换取refresh_token...")
    resp = exchange_code_for_token(auth_code, code_verifier)

    if resp.status_code != 200:
        print(f"[!] 换取token失败: HTTP {resp.status_code}")
        print(f"    {resp.text}")
        sys.exit(1)

    token_data = resp.json()
    refresh_token = token_data.get("refresh_token")

    if not refresh_token:
        print(f"[!] 响应中没有refresh_token:")
        print(f"    {json.dumps(token_data, indent=2)}")
        sys.exit(1)

    print(f"[+] 获取到refresh_token: {refresh_token[:20]}...")

    # 5. 验证
    print("[*] 正在验证token...")
    try:
        user_name, user_id = verify_token(refresh_token)
        print(f"[+] 验证成功! 用户: {user_name} (ID: {user_id})")
    except Exception as e:
        print(f"[!] 验证失败: {e}")
        print("[*] token可能仍然有效，继续保存。")

    # 6. 保存
    save_config(refresh_token)
    print(f"[+] 已保存到 {CONFIG_FILE}")
    print()
    print("现在可以运行: python pixiv_backup.py")


if __name__ == "__main__":
    main()
