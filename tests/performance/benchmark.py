#!/usr/bin/env python3
"""
性能基准测试脚本
用于对 gcli2api 服务进行性能基准测试，以量化优化措施的效果
"""

import argparse
import asyncio
import httpx
import numpy as np
import os
import statistics
import sys
import time
from typing import Dict, List, Any, Tuple


class BenchmarkResult:
    """存储单个测试结果"""
    def __init__(self, name: str):
        self.name = name
        self.start_time = 0.0
        self.end_time = 0.0
        self.request_times: List[float] = []
        self.success_count = 0
        self.failure_count = 0
        self.total_requests = 0

    @property
    def total_time(self) -> float:
        return self.end_time - self.start_time

    @property
    def rps(self) -> float:
        if self.total_time > 0:
            return self.total_requests / self.total_time
        return 0.0

    @property
    def success_rate(self) -> float:
        if self.total_requests > 0:
            return (self.success_count / self.total_requests) * 100
        return 0.0

    @property
    def avg_latency(self) -> float:
        if self.request_times:
            return statistics.mean(self.request_times) * 1000  # 转换为毫秒
        return 0.0

    @property
    def median_latency(self) -> float:
        if self.request_times:
            return np.percentile(self.request_times, 50) * 1000  # 转换为毫秒
        return 0.0

    @property
    def p95_latency(self) -> float:
        if self.request_times:
            return np.percentile(self.request_times, 95) * 1000  # 转换为毫秒
        return 0.0

    @property
    def p99_latency(self) -> float:
        if self.request_times:
            return np.percentile(self.request_times, 99) * 1000  # 转换为毫秒
        return 0.0

    def print_report(self):
        """打印测试报告"""
        print(f"\n=== {self.name} 性能测试报告 ===")
        print(f"总耗时: {self.total_time:.2f} 秒")
        print(f"总请求数: {self.total_requests}")
        print(f"成功请求数: {self.success_count}")
        print(f"失败请求数: {self.failure_count}")
        print(f"每秒请求数 (RPS): {self.rps:.2f}")
        print(f"成功率: {self.success_rate:.2f}%")
        print(f"平均延迟: {self.avg_latency:.2f} ms")
        print(f"中位数延迟 (P50): {self.median_latency:.2f} ms")
        print(f"P95 延迟: {self.p95_latency:.2f} ms")
        print(f"P99 延迟: {self.p99_latency:.2f} ms")


async def make_request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> Tuple[bool, float]:
    """
    发送单个 HTTP 请求并返回结果和耗时
    
    Args:
        client: httpx 异步客户端
        method: HTTP 方法
        url: 请求 URL
        **kwargs: 其他请求参数
        
    Returns:
        Tuple[bool, float]: (是否成功, 耗时)
    """
    start_time = time.perf_counter()
    try:
        response = await client.request(method, url, **kwargs)
        # 对于流式响应，需要读取完整内容
        if response.headers.get('content-type', '').startswith('text/event-stream'):
            async for _ in response.aiter_lines():
                pass  # 读取所有流数据直到结束
        else:
            await response.aread()
        return True, time.perf_counter() - start_time
    except Exception:
        return False, time.perf_counter() - start_time


async def run_benchmark(
    test_name: str,
    endpoint: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    num_requests: int,
    concurrency: int
) -> BenchmarkResult:
    """
    运行性能基准测试
    
    Args:
        test_name: 测试名称
        endpoint: 目标端点 URL
        payload: 请求载荷
        headers: 请求头
        num_requests: 总请求数
        concurrency: 并发数
        
    Returns:
        BenchmarkResult: 测试结果
    """
    result = BenchmarkResult(test_name)
    result.total_requests = num_requests
    
    # 创建信号量控制并发
    semaphore = asyncio.Semaphore(concurrency)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        async def limited_request():
            async with semaphore:
                return await make_request(client, "POST", endpoint, json=payload, headers=headers)
        
        print(f"开始运行 {test_name} 测试...")
        result.start_time = time.perf_counter()
        
        # 并发执行所有请求
        tasks = [limited_request() for _ in range(num_requests)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        result.end_time = time.perf_counter()
        
        # 处理结果
        for response in responses:
            if isinstance(response, Exception):
                result.failure_count += 1
                continue
                
            success, duration = response
            result.request_times.append(duration)
            if success:
                result.success_count += 1
            else:
                result.failure_count += 1
    
    return result


async def openai_chat_non_streaming_test(base_url: str, api_key: str, num_requests: int, concurrency: int) -> BenchmarkResult:
    """OpenAI 非流式聊天测试"""
    endpoint = f"{base_url}/v1/chat/completions"
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "user", "content": "Hello, how are you?"}
        ],
        "stream": False
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    return await run_benchmark(
        "OpenAI 非流式聊天",
        endpoint,
        payload,
        headers,
        num_requests,
        concurrency
    )


async def openai_chat_streaming_test(base_url: str, api_key: str, num_requests: int, concurrency: int) -> BenchmarkResult:
    """OpenAI 流式聊天测试"""
    endpoint = f"{base_url}/v1/chat/completions"
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "user", "content": "Hello, how are you?"}
        ],
        "stream": True
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    return await run_benchmark(
        "OpenAI 流式聊天",
        endpoint,
        payload,
        headers,
        num_requests,
        concurrency
    )


async def gemini_generate_content_test(base_url: str, api_key: str, num_requests: int, concurrency: int) -> BenchmarkResult:
    """Gemini 非流式生成测试"""
    endpoint = f"{base_url}/v1beta/models/gemini-pro:generateContent"
    payload = {
        "contents": {
            "role": "user",
            "parts": {
                "text": "Hello, how are you?"
            }
        }
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    return await run_benchmark(
        "Gemini 非流式生成",
        endpoint,
        payload,
        headers,
        num_requests,
        concurrency
    )


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="gcli2api 性能基准测试")
    parser.add_argument("--url", default=os.getenv("BENCHMARK_URL", "http://localhost:8000"),
                        help="目标 URL (默认: http://localhost:8000)")
    parser.add_argument("--api-key", default=os.getenv("BENCHMARK_API_KEY", ""),
                        help="API 密钥")
    parser.add_argument("--concurrency", type=int, default=int(os.getenv("BENCHMARK_CONCURRENCY", "10")),
                        help="并发数 (默认: 10)")
    parser.add_argument("--requests", type=int, default=int(os.getenv("BENCHMARK_REQUESTS", "100")),
                        help="总请求数 (默认: 100)")
    return parser.parse_args()


async def main():
    """主函数"""
    args = parse_args()
    
    if not args.api_key:
        print("错误: 必须提供 API 密钥", file=sys.stderr)
        sys.exit(1)
    
    print(f"开始性能基准测试...")
    print(f"目标 URL: {args.url}")
    print(f"并发数: {args.concurrency}")
    print(f"总请求数: {args.requests}")
    
    # 运行所有测试
    tests = [
        openai_chat_non_streaming_test,
        openai_chat_streaming_test,
        gemini_generate_content_test
    ]
    
    results = []
    for test_func in tests:
        try:
            result = await test_func(args.url, args.api_key, args.requests, args.concurrency)
            result.print_report()
            results.append(result)
        except Exception as e:
            print(f"运行测试时出错: {e}")
    
    # 打印汇总报告
    print("\n=== 性能测试汇总 ===")
    for result in results:
        print(f"{result.name}: RPS={result.rps:.2f}, 成功率={result.success_rate:.2f}%, 平均延迟={result.avg_latency:.2f}ms")


if __name__ == "__main__":
    asyncio.run(main())