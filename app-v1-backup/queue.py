import asyncio

from .models import ScrapingTask


class TaskQueue:
    def __init__(self, max_size: int):
        self.queue: asyncio.Queue[ScrapingTask] = asyncio.Queue(
            maxsize=max_size
        )

    async def put(self, task: ScrapingTask) -> None:
        await self.queue.put(task)

    async def get(self) -> ScrapingTask:
        return await self.queue.get()

    def task_done(self) -> None:
        self.queue.task_done()

    def size(self) -> int:
        return self.queue.qsize()

    async def wait_until_empty(self) -> None:
        await self.queue.join()