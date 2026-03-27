# app/__init__.py intentionally left minimal.
# No event loop policy is needed — streaming uses subprocess.Popen which is
# compatible with both Windows SelectorEventLoop and Linux EpollEventLoop.
