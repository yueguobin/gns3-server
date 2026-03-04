#!/usr/bin/env python3
"""
Reference tool for LLM model context limits.

This script provides reference context limit values for common LLM models.
It helps users find the correct context_limit value when creating LLM model configurations.

IMPORTANT:
- context_limit unit is K tokens (1 K = 1000 tokens)
- This tool only displays reference values. You MUST manually configure
  context_limit when creating or updating LLM model configurations via API.

Usage:
    python scripts/show_model_context_limits.py

For official documentation, always check:
- OpenAI: https://platform.openai.com/docs/models
- Anthropic: https://docs.anthropic.com/claude/docs/models-overview
- Google: https://ai.google.dev/gemini-api/docs/models
- DeepSeek: https://platform.deepseek.com/api-docs/
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# Reference context limits (as of 2025)
# Displayed in K tokens for easier configuration
# Users should verify from official provider documentation
MODEL_CONTEXT_LIMITS_K = {
    # OpenAI Models
    "gpt-4o": 128,
    "gpt-4o-mini": 128,
    "gpt-4-turbo": 128,
    "gpt-4": 8,
    "gpt-4-32k": 33,
    "gpt-3.5-turbo": 17,
    "gpt-3.5-turbo-16k": 17,

    # Anthropic Models
    "claude-3-5-sonnet-20241022": 200,
    "claude-3-5-sonnet-20240620": 200,
    "claude-3-opus-20240229": 200,
    "claude-3-sonnet-20240229": 200,
    "claude-3-haiku-20240307": 200,

    # Google Models
    "gemini-2.0-flash-exp": 1000,
    "gemini-1.5-pro": 2800,
    "gemini-1.5-flash": 2800,
    "gemini-pro": 92,

    # DeepSeek Models
    "deepseek-chat": 128,
    "deepseek-coder": 128,

    # xAI Models
    "grok-beta": 128,
}


def find_context_limit_for_model(model_name: str) -> int | None:
    """Find the context limit for a given model name (in K tokens)."""
    model_lower = model_name.lower().strip()

    # Try exact match
    if model_lower in MODEL_CONTEXT_LIMITS_K:
        return MODEL_CONTEXT_LIMITS_K[model_lower]

    # Try prefix match
    for key, limit in MODEL_CONTEXT_LIMITS_K.items():
        if model_lower.startswith(key.lower()):
            return limit

    return None


def main():
    print("=" * 70)
    print("LLM Model Context Limits Reference Tool")
    print("=" * 70)
    print()
    print("This tool displays reference context limit values for common LLM models.")
    print("Please verify from official provider documentation before configuring.")
    print()
    print("IMPORTANT: context_limit unit is K tokens (1 K = 1,000 tokens)")
    print()
    print("Official Documentation:")
    print("  - OpenAI: https://platform.openai.com/docs/models")
    print("  - Anthropic: https://docs.anthropic.com/claude/docs/models-overview")
    print("  - Google: https://ai.google.dev/gemini-api/docs/models")
    print("  - DeepSeek: https://platform.deepseek.com/api-docs/")
    print()

    # Display all reference values
    print("=" * 70)
    print("Reference Context Limits (in K tokens)")
    print("=" * 70)
    print()

    # Group by provider
    providers = {
        "OpenAI": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-4-32k", "gpt-3.5-turbo", "gpt-3.5-turbo-16k"],
        "Anthropic": ["claude-3-5-sonnet-20241022", "claude-3-5-sonnet-20240620", "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"],
        "Google": ["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-pro"],
        "DeepSeek": ["deepseek-chat", "deepseek-coder"],
        "xAI": ["grok-beta"],
    }

    for provider, models in providers.items():
        print(f"\n{provider}:")
        for model in models:
            if model in MODEL_CONTEXT_LIMITS_K:
                limit_k = MODEL_CONTEXT_LIMITS_K[model]
                limit_actual = limit_k * 1000
                print(f"  {model:40s} → {limit_k:4d}K (= {limit_actual:,} tokens)")

    print()
    print("=" * 70)
    print()
    print("Conversion Examples:")
    print()
    print("  Official Documentation: 128,000 tokens")
    print("  ↓")
    print("  API Configuration: \"context_limit\": 128")
    print()
    print("  Official Documentation: 200,000 tokens")
    print("  ↓")
    print("  API Configuration: \"context_limit\": 200")
    print()
    print("  Official Documentation: 2,800,000 tokens")
    print("  ↓")
    print("  API Configuration: \"context_limit\": 2800")
    print()
    print("=" * 70)
    print()
    print("Usage Example:")
    print()
    print("When creating a model configuration, specify context_limit in K:")
    print()
    print('  POST /v3/users/{user_id}/llm-model-configs')
    print('  {')
    print('    "name": "GPT-4o Configuration",')
    print('    "provider": "openai",')
    print('    "model": "gpt-4o",')
    print('    "context_limit": 128,  // ← Required: 128K = 128,000 tokens')
    print('    "context_strategy": "balanced"')
    print('  }')
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
