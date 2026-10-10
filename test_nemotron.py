
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("NVIDIA_API_KEY")
if not api_key:
    raise RuntimeError("NVIDIA_API_KEY was not found in .env")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=api_key,
)

try:
    response = client.chat.completions.create(
        model="nvidia/nemotron-3-super-120b-a12b",
        messages=[
            {"role": "user", "content": "Which number is larger, 9.11 or 9.8? Explain briefly."}
        ],
        temperature=1,
        top_p=0.95,
        max_tokens=256,
        stream=False,
    )
    print("SUCCESS: NVIDIA inference works!")
    print(response.choices[0].message.content)

except Exception as exc:
    print("NVIDIA inference failed:")
    print(type(exc).__name__, str(exc))
