"""
Security Audit T4 — Secret rotation helper.

Dry-run (default): prints a freshly generated SECRET_KEY without touching files.
Apply mode (--apply): backs up .env to .env.bak.<timestamp> and writes the new key.

All existing JWTs become invalid once the backend restarts with the new key
(users must re-authenticate). See docs/SECRETS.md.
"""
import argparse
import os
import secrets
import shutil
from datetime import datetime, timezone


def generate_secret_key() -> str:
    """64-byte URL-safe token (>= 32 chars as required by core/config.py)."""
    return secrets.token_urlsafe(64)


def _find_env_path() -> str:
    # scripts/ lives in backend/; .env is one level up
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(os.path.dirname(here), ".env")
    return candidate if os.path.exists(candidate) else os.path.join(here, ".env")


def apply(new_key: str, env_path: str) -> None:
    backup = f"{env_path}.bak.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    shutil.copyfile(env_path, backup)
    print(f"[rotate_secret] Backed up current .env -> {backup}")

    lines = []
    replaced = False
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("SECRET_KEY="):
                lines.append(f"SECRET_KEY={new_key}\n")
                replaced = True
            else:
                lines.append(line)
    if not replaced:
        lines.append(f"SECRET_KEY={new_key}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"[rotate_secret] Wrote new SECRET_KEY into {env_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate JWT SECRET_KEY")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the new key into .env (backs up the old one). Dry-run if omitted.",
    )
    args = parser.parse_args()

    new_key = generate_secret_key()
    print("New SECRET_KEY:")
    print(new_key)

    if args.apply:
        apply(new_key, _find_env_path())
        print("\n[rotate_secret] DONE. Restart the backend to invalidate old JWTs.")
    else:
        print("\n[rotate_secret] Dry-run only. Re-run with --apply to write to .env.")


if __name__ == "__main__":
    main()
