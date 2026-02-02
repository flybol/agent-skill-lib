"""
微信 JS-SDK 服务
处理 access_token、jsapi_ticket 获取和签名生成
"""

import os
import time
import hashlib
import json
import logging
import httpx
from typing import Optional
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# 微信公众号配置
WECHAT_APP_ID = "wx0d8129746049f58a"
WECHAT_APP_SECRET = "213c4d4c98d15d985437921b849b316e"

# API 端点
ACCESS_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
JSAPI_TICKET_URL = "https://api.weixin.qq.com/cgi-bin/ticket/getticket"

# 缓存文件路径
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "wechat_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

TOKEN_CACHE_FILE = CACHE_DIR / "access_token.json"
TICKET_CACHE_FILE = CACHE_DIR / "jsapi_ticket.json"


class WeChatJSSDK:
    """微信 JS-SDK 签名服务"""

    def __init__(self, app_id: str = None, app_secret: str = None):
        self.app_id = app_id or WECHAT_APP_ID
        self.app_secret = app_secret or WECHAT_APP_SECRET

    def _load_cache(self, cache_file: Path) -> Optional[dict]:
        """从文件加载缓存"""
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 检查是否过期（提前 5 分钟刷新）
                if data.get("expires_at", 0) > time.time() + 300:
                    return data
            except Exception as e:
                logger.warning(f"加载缓存文件失败: {e}")
        return None

    def _save_cache(self, cache_file: Path, data: dict, expires_in: int):
        """保存缓存到文件"""
        data["expires_at"] = time.time() + expires_in
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存缓存文件失败: {e}")

    async def get_access_token(self) -> str:
        """获取 access_token（带缓存）"""
        # 先尝试从缓存加载
        cached = self._load_cache(TOKEN_CACHE_FILE)
        if cached and cached.get("access_token"):
            return cached["access_token"]

        # 缓存未命中，请求微信 API
        params = {
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret,
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(ACCESS_TOKEN_URL, params=params, timeout=10.0)
                response.raise_for_status()
                data = response.json()

                if "access_token" in data:
                    token = data["access_token"]
                    expires_in = data.get("expires_in", 7200)
                    # 保存缓存
                    self._save_cache(TOKEN_CACHE_FILE, {"access_token": token}, expires_in)
                    logger.info("成功获取 access_token")
                    return token
                else:
                    error_msg = data.get("errmsg", "未知错误")
                    error_code = data.get("errcode", "unknown")
                    raise Exception(f"获取 access_token 失败: {error_code} - {error_msg}")

            except httpx.HTTPError as e:
                logger.error(f"请求 access_token 网络错误: {e}")
                raise Exception(f"网络请求失败: {str(e)}")

    async def get_jsapi_ticket(self) -> str:
        """获取 jsapi_ticket（带缓存）"""
        # 先尝试从缓存加载
        cached = self._load_cache(TICKET_CACHE_FILE)
        if cached and cached.get("ticket"):
            return cached["ticket"]

        # 缓存未命中，先获取 access_token，再获取 ticket
        access_token = await self.get_access_token()

        params = {
            "access_token": access_token,
            "type": "jsapi",
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(JSAPI_TICKET_URL, params=params, timeout=10.0)
                response.raise_for_status()
                data = response.json()

                if data.get("errcode") == 0 and "ticket" in data:
                    ticket = data["ticket"]
                    expires_in = data.get("expires_in", 7200)
                    # 保存缓存
                    self._save_cache(TICKET_CACHE_FILE, {"ticket": ticket}, expires_in)
                    logger.info("成功获取 jsapi_ticket")
                    return ticket
                else:
                    error_msg = data.get("errmsg", "未知错误")
                    error_code = data.get("errcode", "unknown")
                    raise Exception(f"获取 jsapi_ticket 失败: {error_code} - {error_msg}")

            except httpx.HTTPError as e:
                logger.error(f"请求 jsapi_ticket 网络错误: {e}")
                raise Exception(f"网络请求失败: {str(e)}")

    def generate_nonce_str(self) -> str:
        """生成随机字符串"""
        import uuid
        return uuid.uuid4().hex[:16]

    def generate_signature(self, ticket: str, nonce_str: str, timestamp: int, url: str) -> str:
        """生成签名

        签名算法：
        1. 将 jsapi_ticket、noncestr、timestamp、url 按字典序排序
        2. 拼接成字符串 string1 = "jsapi_ticket=TICKET&noncestr=NONCE&timestamp=TIMESTAMP&url=URL"
        3. 对 string1 做 sha1 加密
        """
        # 按字典序排序参数
        params = {
            "jsapi_ticket": ticket,
            "noncestr": nonce_str,
            "timestamp": str(timestamp),
            "url": url,
        }

        # 排序并拼接
        sorted_params = sorted(params.items())
        string1 = "&".join([f"{k}={v}" for k, v in sorted_params])

        # SHA1 加密
        signature = hashlib.sha1(string1.encode("utf-8")).hexdigest()
        return signature

    async def get_jsdk_config(self, url: str) -> dict:
        """获取 JS-SDK 配置

        Args:
            url: 当前页面 URL（不含 #hash 部分）

        Returns:
            {
                "appId": "wx...",
                "timestamp": 1700000000,
                "nonceStr": "随机串",
                "signature": "sha1结果"
            }
        """
        try:
            # 获取 jsapi_ticket
            ticket = await self.get_jsapi_ticket()

            # 生成随机串和时间戳
            nonce_str = self.generate_nonce_str()
            timestamp = int(time.time())

            # 生成签名
            signature = self.generate_signature(ticket, nonce_str, timestamp, url)

            return {
                "appId": self.app_id,
                "timestamp": timestamp,
                "nonceStr": nonce_str,
                "signature": signature,
            }
        except Exception as e:
            logger.error(f"获取 JS-SDK 配置失败: {e}")
            raise


# 全局实例
wechat_jsdk = WeChatJSSDK()
