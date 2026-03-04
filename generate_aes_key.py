#!/usr/bin/env python3
"""
Generate a secure AES key for production use.
Usage: python generate_aes_key.py
"""
import base64
import os

# Generate a 32-byte (256-bit) key for AES-256
key = os.urandom(32)

# Encode it as base64
b64_key = base64.b64encode(key).decode('ascii')

print("=" * 60)
print("Generated AES-256 Key")
print("=" * 60)
print(f"\nBase64 encoded key (add to .env):\n{b64_key}")
print(f"\nKey length: {len(key)} bytes ({len(key)*8} bits)")
print("\nAdd this to your .env file:")
print(f"SECRET_AES_KEY={b64_key}")
print("\n⚠️  Keep this key secret! Never commit it to version control.")
print("=" * 60)
