LLM Provider test

This folder contains a small test script to exercise the `LLMProvider`.

Setup environment variables before running:

```bash
# Use Mistral for generation
export LLM_PROVIDER=mistral
export MISTRAL_API_KEY="<your_mistral_key>"
export MISTRAL_MODEL="mistral-4b"
# Optional override of API host
# export MISTRAL_API_URL="https://api.mistral.ai"

# For NVIDIA reranking (optional)
export NVIDIA_API_KEY="<your_nvidia_key>"
# or set the full header
# export NVIDIA_API_AUTH_HEADER='Bearer <token>'
```

Run the test:

```bash
python3 scripts/test_llm.py
```
