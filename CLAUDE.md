# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

gcli2api 是一个将 GeminiCLI 转换为 OpenAI 和 Gemini API 接口的 Python FastAPI 应用。项目提供了多种 AI 模型的 API 端点，支持多种认证方式，具备完整的凭证管理系统和 Web 管理控制台。

## 常用开发命令

### 环境管理和依赖安装
```bash
# 同步依赖包
uv sync

# 激活虚拟环境 (Linux/Mac)
source .venv/bin/activate

# 激活虚拟环境 (Windows)
call .venv\Scripts\activate.bat
```

### 启动服务
```bash
# Linux/Mac
bash start.sh

# Windows
start.bat

# 直接运行
python web.py
```

### 性能测试
```bash
# 运行性能基准测试
python tests/performance/benchmark.py
```

## 核心架构

### 主要模块结构

**认证和凭证管理**
- `src/auth.py` - OAuth 2.0 认证流程
- `src/credential_manager.py` - 多凭证文件状态管理和轮换
- `src/google_oauth_api.py` - Google OAuth API 集成

**API 路由和转换**
- `src/openai_router.py` - OpenAI 兼容端点
- `src/gemini_router.py` - Gemini 原生端点
- `src/openai_transfer.py` - OpenAI 和 Gemini 格式转换
- `src/format_detector.py` - 自动格式检测

**网络和客户端**
- `src/httpx_client.py` - 统一 HTTP 客户端管理
- `src/google_chat_api.py` - Google Chat API 集成

**状态和存储管理**
- `src/state_manager.py` - 原子化状态操作
- `src/storage_adapter.py` - 存储适配器
- `src/storage/` - 多种存储后端支持 (Redis, PostgreSQL, MongoDB, 本地文件)
- `src/usage_stats.py` - 使用统计和配额管理

**Web 管理界面**
- `src/web_routes.py` - RESTful API 端点和 WebSocket 通信
- `front/` - 前端静态文件

**高级功能**
- `src/anti_truncation.py` - 流式抗截断机制
- `src/task_manager.py` - 全局异步任务生命周期管理

### 配置管理

项目支持多层次配置：
- 环境变量配置（优先级最高）
- TOML 配置文件
- 默认配置值

主要配置文件：
- `.env` - 环境变量配置（从 `.env.example` 复制）
- `config.py` - 配置常量和辅助函数

### 存储后端优先级

系统按以下优先级自动选择存储后端：
1. Redis (设置 `REDIS_URI` 时)
2. PostgreSQL (设置 `POSTGRES_DSN` 时)
3. MongoDB (设置 `MONGODB_URI` 时)
4. 本地文件存储（默认）

### API 端点架构

**OpenAI 兼容端点**
- `/v1/chat/completions` - 聊天完成
- `/v1/models` - 模型列表

**Gemini 原生端点**
- `/v1/models/{model}:generateContent` - 非流式生成
- `/v1/models/{model}:streamGenerateContent` - 流式生成

**Web 管理端点**
- `/auth/*` - 认证相关
- `/creds/*` - 凭证管理
- `/config/*` - 配置管理
- `/usage/*` - 使用统计

### 模型功能特性

**基础模型**
- `gemini-2.5-pro`
- `gemini-2.5-pro-preview-*`

**思维模型**
- `gemini-2.5-pro-maxthinking` - 最大思考预算模式
- `gemini-2.5-pro-nothinking` - 无思考模式

**特殊功能变体**
- 添加 `-假流式` 后缀 - 假流式模式
- 添加 `流式抗截断/` 前缀 - 流式抗截断模式

## 开发注意事项

### 认证系统
- 支持分离密码（API密码和控制面板密码）
- 支持多种认证方式：Bearer Token、x-goog-api-key 头部、URL 参数
- OAuth 验证流程仅支持本地主机访问

### 网络配置
- 支持 HTTP/HTTPS 代理配置
- 可配置超时和重试策略
- 支持 429 错误自动重试

### 日志系统
- 多级日志系统（DEBUG、INFO、WARNING、ERROR）
- 支持实时日志流（WebSocket）
- 可配置日志文件路径

### 安全注意事项
- 所有 API 密钥和凭证信息存储在 `creds/` 目录
- 支持环境变量方式导入凭证（`GCLI_CREDS_*` 格式）
- 自动凭证轮换和故障检测机制

### 开发工具
- 使用 uv 作为包管理器
- FastAPI 作为 Web 框架
- httpx 用于异步 HTTP 请求
- 支持多种异步存储后端