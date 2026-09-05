import secrets


def generate_request_id():
    """Generate a readable, non-sequential identifier with about 60 bits of entropy."""
    return f"EZY-{secrets.token_hex(3).upper()}-{secrets.token_hex(3).upper()}"
