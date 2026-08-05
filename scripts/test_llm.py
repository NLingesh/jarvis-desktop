#!/usr/bin/env python3
"""Small test runner for the LLM provider (mistral or anthropic).

Fill env vars before running, then run:

    python3 scripts/test_llm.py

"""
import asyncio
import os
import sys

# Allow running from the project root (python3 scripts/test_llm.py)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'jarvis_backend'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'jarvis_backend', '.env'))

from modules.llm_provider import LLMProvider

async def main():
    p = LLMProvider()
    print("Provider:", p.provider, "model:", getattr(p, 'model', None))

    # Test generation (chat-style)
    conv = [
        {"role": "system", "content": "You are JARVIS, a concise helpful assistant."},
        {"role": "user", "content": "Start by greeting the user briefly."}
    ]
    resp = await p.get_response("Please say hello and offer help.", conversation_history=conv)
    print("Generation result:\n", resp)

    # Test rerank (if NVIDIA creds available)
    rr = await p.rerank(
        "What is the GPU memory bandwidth of H100 SXM?",
        [
            "The Hopper GPU is paired with the Grace CPU using NVIDIA's ultra-fast chip-to-chip interconnect, delivering 900GB/s of bandwidth, 7X faster than PCIe Gen5.",
            "A100 provides up to 20X higher performance ... over 2 terabytes per second (TB/s).",
            "Accelerated servers with H100 deliver ... 3 terabytes per second (TB/s) of memory bandwidth per GPU."
        ]
    )
    print("Rerank result:\n", rr)

if __name__ == '__main__':
    asyncio.run(main())
