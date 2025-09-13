# 性能基准测试

此目录包含用于对 gcli2api 服务进行性能基准测试的脚本。

## benchmark.py

这是一个 Python 脚本，用于测试 gcli2api 服务在不同场景下的性能表现。

### 依赖

- Python 3.7+
- httpx
- numpy

安装依赖：
```bash
pip install -r requirements.txt
```

### 使用方法

```bash
python benchmark.py [选项]
```

### 命令行选项

- `--url`: 目标 URL (默认: http://localhost:8000)
- `--api-key`: API 密钥 (必需)
- `--concurrency`: 并发数 (默认: 10)
- `--requests`: 总请求数 (默认: 100)

### 环境变量

也可以通过环境变量配置：

- `BENCHMARK_URL`: 目标 URL
- `BENCHMARK_API_KEY`: API 密钥
- `BENCHMARK_CONCURRENCY`: 并发数
- `BENCHMARK_REQUESTS`: 总请求数

### 示例

```bash
# 使用命令行参数
python benchmark.py --url http://localhost:8000 --api-key your-api-key --concurrency 20 --requests 200

# 使用环境变量
export BENCHMARK_URL=http://localhost:8000
export BENCHMARK_API_KEY=your-api-key
export BENCHMARK_CONCURRENCY=20
export BENCHMARK_REQUESTS=200
python benchmark.py
```

### 测试场景

1. **OpenAI 非流式聊天**: 测试 `/v1/chat/completions` 端点的非流式请求性能
2. **OpenAI 流式聊天**: 测试 `/v1/chat/completions` 端点的流式请求性能
3. **Gemini 非流式生成**: 测试 `/v1beta/models/gemini-pro:generateContent` 端点的性能

### 输出指标

- 总耗时
- 每秒请求数 (RPS)
- 成功率 (%)
- 平均延迟 (ms)
- 中位数延迟 (P50 in ms)
- P95 延迟 (ms)
- P99 延迟 (ms)