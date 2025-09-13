"""
Global task lifecycle management module
管理应用程序中所有异步任务的生命周期，确保正确清理
"""
import asyncio
from typing import Set, Dict, Any, Optional, Callable
from log import log


class TaskManager:
    """全局异步任务管理器 - 支持并发控制"""
    
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls, max_concurrent_tasks: int = 10):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, max_concurrent_tasks: int = 10):
        if self._initialized:
            return
        
        self._max_concurrent_tasks = max_concurrent_tasks
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self._tasks: Set[asyncio.Task] = set()
        self._shutdown_event = asyncio.Event()
        self._initialized = True
        log.debug(f"TaskManager initialized with max_concurrent_tasks={max_concurrent_tasks}")
    
    def _task_done_callback(self, task: asyncio.Task):
        """任务完成回调"""
        self._tasks.discard(task)
        log.debug(f"Task {task.get_name() or 'unnamed'} finished")
    
    async def _run_with_semaphore(self, coro, task_name: str = None):
        """使用信号量运行协程"""
        async with self._semaphore:
            log.debug(f"Acquired semaphore for task: {task_name or 'unnamed'}")
            try:
                return await coro
            finally:
                log.debug(f"Released semaphore for task: {task_name or 'unnamed'}")
    
    def create_managed_task(self, coro, name: str = None) -> asyncio.Task:
        """创建一个受管理的异步任务，支持并发控制"""
        if self.is_shutdown:
            raise RuntimeError("TaskManager is shutdown, cannot create new tasks")
        
        # 创建包装协程，用于信号量控制
        wrapped_coro = self._run_with_semaphore(coro, name)
        
        # 创建任务
        task = asyncio.create_task(wrapped_coro, name=name)
        task.add_done_callback(self._task_done_callback)
        
        # 添加到任务集合
        self._tasks.add(task)
        
        log.debug(f"Created managed task: {name or 'unnamed'}")
        return task
    
    async def shutdown(self, timeout: float = 30.0):
        """关闭所有任务"""
        log.info("TaskManager shutdown initiated")
        
        # 设置关闭标志
        self._shutdown_event.set()
        
        # 取消所有未完成的任务
        cancelled_count = 0
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
                cancelled_count += 1
        
        if cancelled_count > 0:
            log.info(f"Cancelled {cancelled_count} pending tasks")
        
        # 等待所有任务完成（包括取消）
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                log.warning(f"Some tasks did not complete within {timeout}s timeout")
        
        self._tasks.clear()
        log.info("TaskManager shutdown completed")
    
    @property
    def is_shutdown(self) -> bool:
        """检查是否已经开始关闭"""
        return self._shutdown_event.is_set()
    
    def get_stats(self) -> Dict[str, int]:
        """获取任务管理统计信息"""
        return {
            'active_tasks': len(self._tasks),
            'max_concurrent_tasks': self._max_concurrent_tasks,
            'available_semaphore_slots': self._semaphore._value,  # 注意：这是内部属性，仅用于调试
            'is_shutdown': self.is_shutdown
        }


# 全局任务管理器实例
task_manager = TaskManager()


def create_managed_task(coro, *, name: str = None) -> asyncio.Task:
    """创建一个被管理的异步任务的便捷函数"""
    return task_manager.create_managed_task(coro, name=name)


async def shutdown_all_tasks(timeout: float = 30.0):
    """关闭所有任务的便捷函数"""
    await task_manager.shutdown(timeout)