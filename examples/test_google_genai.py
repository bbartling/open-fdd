"""
Quick test of Google GenAI API (raw SDK, no Instructor).

Verifies API key and model work before running the full agent.

Usage:
    $env:GOOGLE_API_KEY = "your-key"   # PowerShell
    python examples/test_google_genai.py
"""
import os
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

def main():
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        print("GOOGLE_API_KEY not set. Set it first:")
        print("  PowerShell: $env:GOOGLE_API_KEY = \"your-key\"")
        print("  Bash: export GOOGLE_API_KEY=your-key")
        return 1

    try:
        from google import genai
        client = genai.Client(api_key=key)
    except ImportError:
        print("Install: pip install google-genai")
        return 1

    model = "gemini-2.5-flash"
    print(f"Testing {model}...")
    try:
        response = client.models.generate_content(
            model=model,
            contents="Explain how AI works in a few words",
        )
        print(f"Response: {response.text}")
        print("OK")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
