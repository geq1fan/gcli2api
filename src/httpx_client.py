"""
通用的HTTP客户端模块
为所有需要使用httpx的模块提供统一的客户端配置和方法
保持通用性，不与特定业务逻辑耦合
"""
import httpx
import time
import threading
from typing import Optional, Dict, Any, AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from config import get_proxy_config
from log import log


@dataclass
class ConnectionPoolStats:
    """连接池统计信息"""
    total_requests: int = 0
    active_connections: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_response_time: float = 0.0
    last_reset_time: float = 0.0

    @property
    def average_response_time(self) -> float:
        """平均响应时间（毫秒）"""
        if self.successful_requests > 0:
            return (self.total_response_time / self.successful_requests) * 1000
        return 0.0

    @property
    def success_rate(self) -> float:
        """成功率百分比"""
        if self.total_requests > 0:
            return (self.successful_requests / self.total_requests) * 100
        return 0.0

    def reset(self):
        """重置统计信息"""
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_response_time = 0.0
        self.last_reset_time = time.time()


class HttpxClientManager:
    """通用HTTP客户端管理器，支持全局连接池"""

    # 健康检查配置参数
    HEALTHY_SUCCESS_RATE_THRESHOLD = 95.0    # 健康状态成功率阈值
    WARNING_SUCCESS_RATE_THRESHOLD = 80.0    # 警告状态成功率阈值
    WARNING_ACTIVE_CONNECTIONS_THRESHOLD = 150  # 活跃连接数警告阈值

    def __init__(self):
        self._global_client: Optional[httpx.AsyncClient] = None
        self._stats = ConnectionPoolStats()
        self._stats_lock = threading.Lock()
        self._stats.last_reset_time = time.time()
    
    async def initialize(self, **kwargs) -> None:
        """初始化全局HTTP客户端连接池"""
        if self._global_client is None:
            client_kwargs = await self.get_client_kwargs(**kwargs)
            self._global_client = httpx.AsyncClient(**client_kwargs)
            log.info("全局HTTP客户端连接池已初始化")
    
    async def close(self) -> None:
        """关闭全局HTTP客户端连接池"""
        if self._global_client:
            await self._global_client.aclose()
            self._global_client = None
            log.info("全局HTTP客户端连接池已关闭")
    
    async def get_client_kwargs(self, timeout: float = 30.0, **kwargs) -> Dict[str, Any]:
        """获取httpx客户端的通用配置参数"""
        # 配置连接池限制
        limits = httpx.Limits(
            max_keepalive_connections=100,  # 最大保持连接数
            max_connections=200,           # 最大总连接数
            keepalive_expiry=30.0          # 保持连接过期时间（秒）
        )

        # 配置超时策略
        timeout_config = httpx.Timeout(
            connect=10.0,    # 连接超时
            read=timeout,    # 读取超时
            write=10.0,      # 写入超时
            pool=5.0         # 连接池获取连接超时
        )

        # 配置重试策略
        transport = httpx.AsyncHTTPTransport(
            limits=limits,
            retries=3,       # 重试次数
        )

        client_kwargs = {
            "timeout": timeout_config,
            "limits": limits,
            "transport": transport,
            "follow_redirects": True,  # 自动跟随重定向
            **kwargs
        }

        # 动态读取代理配置，支持热更新
        current_proxy_config = await get_proxy_config()
        if current_proxy_config:
            client_kwargs["proxy"] = current_proxy_config

        return client_kwargs
    
    def _record_request_start(self):
        """记录请求开始"""
        with self._stats_lock:
            self._stats.total_requests += 1

    def _record_request_end(self, start_time: float, success: bool):
        """记录请求结束"""
        with self._stats_lock:
            end_time = time.time()
            response_time = end_time - start_time
            self._stats.total_response_time += response_time
            if success:
                self._stats.successful_requests += 1
            else:
                self._stats.failed_requests += 1

    @asynccontextmanager
    async def get_client(self, **kwargs) -> AsyncGenerator[httpx.AsyncClient, None]:
        """获取配置好的异步HTTP客户端（复用全局连接池）"""
        if self._global_client is None:
            raise RuntimeError("全局HTTP客户端未初始化，请先调用 initialize() 方法")

        # 记录活跃连接数
        with self._stats_lock:
            self._stats.active_connections += 1

        try:
            yield self._global_client
        finally:
            with self._stats_lock:
                self._stats.active_connections -= 1

    def get_stats(self) -> Dict[str, Any]:
        """获取连接池统计信息"""
        with self._stats_lock:
            uptime = time.time() - self._stats.last_reset_time
            return {
                "total_requests": self._stats.total_requests,
                "active_connections": self._stats.active_connections,
                "successful_requests": self._stats.successful_requests,
                "failed_requests": self._stats.failed_requests,
                "average_response_time_ms": round(self._stats.average_response_time, 2),
                "success_rate_percent": round(self._stats.success_rate, 2),
                "uptime_seconds": round(uptime, 2),
                "requests_per_second": round(self._stats.total_requests / uptime if uptime > 0 else 0, 2)
            }

    def reset_stats(self):
        """重置统计信息"""
        with self._stats_lock:
            self._stats.reset()
            log.info("连接池统计信息已重置")

    async def health_check(self) -> Dict[str, Any]:
        """连接池健康检查"""
        health_status = {
            "status": "unknown",
            "details": {},
            "timestamp": time.time()
        }

        try:
            if self._global_client is None:
                health_status["status"] = "unhealthy"
                health_status["details"]["error"] = "全局HTTP客户端未初始化"
                return health_status

            stats = self.get_stats()
            health_status["details"].update(stats)

            # 判断健康状态
            if stats["success_rate_percent"] >= self.HEALTHY_SUCCESS_RATE_THRESHOLD:
                health_status["status"] = "healthy"
            elif stats["success_rate_percent"] >= self.WARNING_SUCCESS_RATE_THRESHOLD:
                health_status["status"] = "warning"
            else:
                health_status["status"] = "unhealthy"

            # 检查是否有过多的活跃连接
            if stats["active_connections"] > self.WARNING_ACTIVE_CONNECTIONS_THRESHOLD:
                health_status["status"] = "warning"
                health_status["details"]["warning"] = "活跃连接数过多"

        except Exception as e:
            health_status["status"] = "error"
            health_status["details"]["error"] = str(e)
            log.error(f"连接池健康检查失败: {e}")

        return health_status
    


# 全局HTTP客户端管理器实例
http_client = HttpxClientManager()


# 通用的异步方法（包含统计记录）
async def get_async(url: str, headers: Optional[Dict[str, str]] = None,
                   timeout: float = 30.0, **kwargs) -> httpx.Response:
    """通用异步GET请求"""
    start_time = time.time()
    http_client._record_request_start()

    try:
        async with http_client.get_client(**kwargs) as client:
            response = await client.get(url, headers=headers, timeout=timeout)
            http_client._record_request_end(start_time, True)
            return response
    except Exception as e:
        http_client._record_request_end(start_time, False)
        raise


async def post_async(url: str, data: Any = None, json: Any = None,
                    headers: Optional[Dict[str, str]] = None,
                    timeout: float = 30.0, **kwargs) -> httpx.Response:
    """通用异步POST请求"""
    start_time = time.time()
    http_client._record_request_start()

    try:
        async with http_client.get_client(**kwargs) as client:
            response = await client.post(url, data=data, json=json, headers=headers, timeout=timeout)
            http_client._record_request_end(start_time, True)
            return response
    except Exception as e:
        http_client._record_request_end(start_time, False)
        raise


async def put_async(url: str, data: Any = None, json: Any = None,
                   headers: Optional[Dict[str, str]] = None,
                   timeout: float = 30.0, **kwargs) -> httpx.Response:
    """通用异步PUT请求"""
    start_time = time.time()
    http_client._record_request_start()

    try:
        async with http_client.get_client(**kwargs) as client:
            response = await client.put(url, data=data, json=json, headers=headers, timeout=timeout)
            http_client._record_request_end(start_time, True)
            return response
    except Exception as e:
        http_client._record_request_end(start_time, False)
        raise


async def delete_async(url: str, headers: Optional[Dict[str, str]] = None,
                      timeout: float = 30.0, **kwargs) -> httpx.Response:
    """通用异步DELETE请求"""
    start_time = time.time()
    http_client._record_request_start()

    try:
        async with http_client.get_client(**kwargs) as client:
            response = await client.delete(url, headers=headers, timeout=timeout)
            http_client._record_request_end(start_time, True)
            return response
    except Exception as e:
        http_client._record_request_end(start_time, False)
        raise


# 错误处理装饰器
def handle_http_errors(func):
    """HTTP错误处理装饰器"""
    async def wrapper(*args, **kwargs):
        try:
            response = await func(*args, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            log.error(f"HTTP错误: {e.response.status_code} - {e.response.text}")
            raise
        except httpx.RequestError as e:
            log.error(f"请求错误: {e}")
            raise
        except Exception as e:
            log.error(f"未知错误: {e}")
            raise
    return wrapper


# 应用错误处理的安全方法
@handle_http_errors
async def safe_get_async(url: str, headers: Optional[Dict[str, str]] = None,
                        timeout: float = 30.0, **kwargs) -> httpx.Response:
    """安全的异步GET请求（自动错误处理）"""
    return await get_async(url, headers=headers, timeout=timeout, **kwargs)


@handle_http_errors
async def safe_post_async(url: str, data: Any = None, json: Any = None,
                         headers: Optional[Dict[str, str]] = None,
                         timeout: float = 30.0, **kwargs) -> httpx.Response:
    """安全的异步POST请求（自动错误处理）"""
    return await post_async(url, data=data, json=json, headers=headers, timeout=timeout, **kwargs)


@handle_http_errors
async def safe_put_async(url: str, data: Any = None, json: Any = None,
                        headers: Optional[Dict[str, str]] = None,
                        timeout: float = 30.0, **kwargs) -> httpx.Response:
    """安全的异步PUT请求（自动错误处理）"""
    return await put_async(url, data=data, json=json, headers=headers, timeout=timeout, **kwargs)


@handle_http_errors
async def safe_delete_async(url: str, headers: Optional[Dict[str, str]] = None,
                           timeout: float = 30.0, **kwargs) -> httpx.Response:
    """安全的异步DELETE请求（自动错误处理）"""
    return await delete_async(url, headers=headers, timeout=timeout, **kwargs)


# 流式请求支持
class StreamingContext:
    """流式请求上下文管理器 - 复用全局连接池，不关闭client"""

    def __init__(self, stream_context, is_global_client: bool = True):
        self.stream_context = stream_context
        self.response = None
        self.is_global_client = is_global_client  # 标记是否使用全局客户端

    async def __aenter__(self):
        self.response = await self.stream_context.__aenter__()
        return self.response

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.stream_context:
                await self.stream_context.__aexit__(exc_type, exc_val, exc_tb)
        finally:
            # 只有在使用非全局客户端时才关闭连接
            # 全局客户端由HttpxClientManager管理，不应在这里关闭
            pass


@asynccontextmanager
async def get_streaming_post_context(url: str, data: Any = None, json: Any = None,
                                   headers: Optional[Dict[str, str]] = None,
                                   timeout: float = None, **kwargs) -> AsyncGenerator[StreamingContext, None]:
    """获取流式POST请求的上下文管理器"""
    async with http_client.get_client(**kwargs) as client:
        stream_ctx = client.stream("POST", url, data=data, json=json, headers=headers, timeout=timeout)
        streaming_context = StreamingContext(stream_ctx, is_global_client=True)
        yield streaming_context

