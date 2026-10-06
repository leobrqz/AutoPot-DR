"""Print the maximum Energy value (the game's mana-like resource)."""
import sys

from common import attach_and_resolve, read_double


def main():
    process = None
    try:
        process, targets = attach_and_resolve()
        value = read_double(process, targets["max_energy"])
        print(f"[RESULT] Player Max Energy/Mana: {value}")
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)
    finally:
        if process is not None:
            process.close_process()


if __name__ == "__main__":
    main()
