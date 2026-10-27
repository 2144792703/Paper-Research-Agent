import sys
from importlib.metadata import version
import httpx
import openai
import langchain_openai
import langchain_core

print("Python:", sys.executable)

for package in ("httpx", "openai", "langchain-openai", "langchain-core"):
    print(f"{package} version:", version(package))

for module in (httpx, openai, langchain_openai, langchain_core):
    print(f"{module.__name__} path:", module.__file__)