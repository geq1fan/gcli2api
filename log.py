"""
日志模块 - 使用环境变量配置和 loguru 异步日志系统
"""
import os
import sys
import asyncio
import threading
from datetime import datetime
from loguru import logger
from typing import Optional


class AsyncLogWriter:
    """异步日志写入器，使用 asyncio.Queue 作为缓冲区"""
    
    def __init__(self, file_path: str, batch_size: int = 10, timeout: float = 1.0):
        """
        初始化异步日志写入器
        
        Args:
            file_path: 日志文件路径
            batch_size: 批量写入的最大消息数量
            timeout: 从队列获取消息的超时时间（秒）
        """
        self.file_path = file_path
        self.batch_size = batch_size
        self.timeout = timeout
        
        # 创建异步队列作为缓冲区
        self.queue = asyncio.Queue()
        
        # 后台写入任务引用
        self._writer_task: Optional[asyncio.Task] = None
        
        # 运行标志
        self._running = False
        
        # 哨兵值，用于通知后台任务停止
        self._sentinel = object()
        
        # 线程安全锁，用于 write 方法
        self._lock = threading.Lock()
        
        # 文件写入状态标志
        self._file_writing_disabled = False
        self._disable_reason = None
    
    def write(self, message: str):
        """
        同步方法，将日志消息放入队列
        这个方法会被 loguru 在单独的线程中调用，所以需要线程安全
        """
        with self._lock:
            if not self._running:
                # 如果后台任务没有运行，直接写入文件
                self._write_to_file_direct(message)
                return
            
            try:
                # 线程安全地将消息放入队列
                self.queue.put_nowait(message)
            except asyncio.QueueFull:
                # 如果队列满了，直接写入文件
                self._write_to_file_direct(message)
    
    def _write_to_file_direct(self, message: str):
        """直接写入文件的方法"""
        global _file_writing_disabled, _disable_reason
        
        # 如果文件写入已被禁用，直接返回
        if self._file_writing_disabled:
            return
        
        try:
            with open(self.file_path, 'a', encoding='utf-8') as f:
                f.write(message + '\n')
                f.flush()  # 强制刷新到磁盘，确保实时写入
        except (PermissionError, OSError, IOError) as e:
            # 检测只读文件系统或权限问题，禁用文件写入
            self._file_writing_disabled = True
            self._disable_reason = str(e)
            print(f"Warning: File system appears to be read-only or permission denied. Disabling log file writing: {e}", file=sys.stderr)
            print(f"Log messages will continue to display in console only.", file=sys.stderr)
        except Exception as e:
            # 其他异常仍然输出警告但不禁用写入（可能是临时问题）
            print(f"Warning: Failed to write to log file: {e}", file=sys.stderr)
    
    async def _run_writer(self):
        """异步后台写入任务"""
        self._running = True
        batch = []
        
        while self._running:
            try:
                # 尝试从队列中获取消息
                message = await asyncio.wait_for(self.queue.get(), timeout=self.timeout)
                
                # 如果收到哨兵值，表示要停止
                if message is self._sentinel:
                    # 处理队列中剩余的所有消息
                    while not self.queue.empty():
                        remaining_message = self.queue.get_nowait()
                        if remaining_message is not self._sentinel:
                            batch.append(remaining_message)
                    
                    # 写入剩余的批次
                    if batch:
                        self._write_batch(batch)
                        batch.clear()
                    
                    # 退出循环
                    break
                
                # 添加消息到批次
                batch.append(message)
                
                # 如果批次已满，写入批次
                if len(batch) >= self.batch_size:
                    self._write_batch(batch)
                    batch.clear()
                    
            except asyncio.TimeoutError:
                # 超时后，如果有消息在批次中，写入它们
                if batch:
                    self._write_batch(batch)
                    batch.clear()
                
                # 短暂休眠以避免CPU空转
                await asyncio.sleep(0.01)
            except Exception as e:
                print(f"Error in log writer: {e}", file=sys.stderr)
        
        self._running = False
    
    def _write_batch(self, messages):
        """将一批消息写入文件"""
        if self._file_writing_disabled:
            return
        
        try:
            with open(self.file_path, 'a', encoding='utf-8') as f:
                for message in messages:
                    f.write(message + '\n')
                f.flush()  # 强制刷新到磁盘
        except (PermissionError, OSError, IOError) as e:
            # 检测只读文件系统或权限问题，禁用文件写入
            self._file_writing_disabled = True
            self._disable_reason = str(e)
            print(f"Warning: File system appears to be read-only or permission denied. Disabling log file writing: {e}", file=sys.stderr)
            print(f"Log messages will continue to display in console only.", file=sys.stderr)
        except Exception as e:
            # 其他异常仍然输出警告但不禁用写入（可能是临时问题）
            print(f"Warning: Failed to write batch to log file: {e}", file=sys.stderr)
    
    def start(self):
        """启动后台写入任务"""
        if not self._running and (self._writer_task is None or self._writer_task.done()):
            # 创建新的事件循环（如果需要）
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
            
            # 创建并启动后台任务
            self._writer_task = loop.create_task(self._run_writer())
    
    async def stop(self):
        """停止后台写入任务"""
        if self._running and self._writer_task:
            # 向队列发送哨兵值
            try:
                self.queue.put_nowait(self._sentinel)
            except asyncio.QueueFull:
                pass  # 如果队列满了，就让它在下一次循环中处理
            
            # 等待后台任务完成
            try:
                await asyncio.wait_for(self._writer_task, timeout=5.0)
            except asyncio.TimeoutError:
                print("Warning: Log writer task did not finish in time", file=sys.stderr)
                self._writer_task.cancel()
                try:
                    await self._writer_task
                except asyncio.CancelledError:
                    pass


def _get_current_log_level():
    """获取当前日志级别"""
    level = os.getenv('LOG_LEVEL', 'INFO').upper()
    return level


def _get_log_file_path():
    """获取日志文件路径"""
    return os.getenv('LOG_FILE', 'log.txt')


# 全局异步日志写入器实例
_async_log_writer: Optional[AsyncLogWriter] = None


def setup_logging():
    """设置 loguru 日志系统"""
    global _async_log_writer
    
    # 移除默认的日志处理器
    logger.remove()
    
    # 获取日志级别和文件路径
    level = _get_current_log_level()
    log_file = _get_log_file_path()
    
    # 创建异步日志写入器实例
    _async_log_writer = AsyncLogWriter(log_file)
    
    # 启动异步日志写入器
    _async_log_writer.start()
    
    # 添加文件日志处理器
    # enqueue=True 表示在单独的线程中调用 sink
    # 这样 write 方法可以是同步的，但不会阻塞主程序
    logger.add(
        _async_log_writer.write,  # 使用自定义的异步写入器
        level=level,
        format="{message}",  # 保持简单的格式，因为我们自己格式化消息
        enqueue=True,  # 在单独的线程中调用 sink
        backtrace=True,  # 启用回溯
        diagnose=True,  # 启用诊断
        rotation="10 MB",  # 日志文件轮转
        retention="10 days",  # 保留10天的日志
        compression="zip"  # 压缩旧的日志文件
    )
    
    # 添加控制台日志处理器
    logger.add(
        sys.stderr if level in ['ERROR', 'CRITICAL'] else sys.stdout,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        backtrace=True,
        diagnose=True
    )
    
    return logger


def get_async_log_writer():
    """获取全局异步日志写入器实例"""
    return _async_log_writer


class LogAdapter:
    """适配器类，使 loguru 与旧的 log 接口兼容"""
    
    def __getattr__(self, name):
        """将调用转发到 logger 实例"""
        return getattr(logger, name)
    
    def __call__(self, level: str, message: str):
        """支持 log('info', 'message') 调用方式"""
        logger.log(level.upper(), message)
    
    def debug(self, message: str):
        """记录调试信息"""
        logger.debug(message)
    
    def info(self, message: str):
        """记录一般信息"""
        logger.info(message)
    
    def warning(self, message: str):
        """记录警告信息"""
        logger.warning(message)
    
    def error(self, message: str):
        """记录错误信息"""
        logger.error(message)
    
    def critical(self, message: str):
        """记录严重错误信息"""
        logger.critical(message)


# 创建全局日志实例
log = LogAdapter()

# 导出 logger 实例和 setup_logging 函数
__all__ = ['logger', 'setup_logging', 'get_async_log_writer', 'log']