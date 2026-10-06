import sys

from common import attach_and_resolve, read_int


def main():
    process = None
    try:
        process, targets = attach_and_resolve()
        current = read_int(process, targets["current_potions"])
        maximum = read_int(process, targets["max_potions"])
        print(f"[RESULT] Player Potions: {current} | {maximum}")
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)
    finally:
        if process is not None:
            process.close_process()


if __name__ == "__main__":
    main()
