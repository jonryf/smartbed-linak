"""Random helpers and util."""

import asyncio


def make_iter():
    loop = asyncio.get_event_loop()
    queue = asyncio.Queue()

    def put(*args):
        loop.call_soon_threadsafe(queue.put_nowait, args)

    async def get():
        while True:
            yield await queue.get()

    return get(), put
