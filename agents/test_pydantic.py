import os

os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434/v1"

from pydantic_ai import Agent

agent = Agent("ollama:llama3:latest")

result = agent.run_sync("Say hello.")

print(result.output)