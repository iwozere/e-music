import multiprocessing
import sys
import asyncio

if __name__ == "__main__":
    # Force ProactorEventLoop on Windows for subprocess support
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
