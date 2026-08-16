from primary import extract_primary
from secondary import extract_secondary

# ─────────────────────────────────────────────
#  HELPER: normalise model string for matching
#  Strips spaces/hyphens/dots so that
#  "DIESEL ENGINE-87.5 U"  ≈  "PS-D.E.-87.5U CONV"
#  at least share the numeric core "875"
# ─────────────────────────────────────────────
def normalise(text: str) -> str:
    import re
    # keep only alphanumeric chars, uppercase
    return re.sub(r'[^A-Z0-9]', '', text.upper())


def model_match(prim: str, sec: str) -> bool:
    """
    Two models match if their normalised forms are equal,
    OR if one is a substring of the other (handles label format differences).
    """
    np = normalise(prim)
    ns = normalise(sec)
    if not np or not ns:
        return False
    return np == ns or np in ns or ns in np


# ─────────────────────────────────────────────
#  MAIN AUTO PACKING LOOP
# ─────────────────────────────────────────────
def start_packing():

    box_no = 0   # counts secondary boxes used

    while True:

        box_no += 1
        print("\n" + "═" * 50)
        print(f"  📦  SCAN SECONDARY BOX  #{box_no}")
        print("═" * 50)
        sec_img = input("  Enter secondary image path: ").strip()

        model_sec, qty_str = extract_secondary(sec_img)

        # ── validate qty ──────────────────────────────
        try:
            qty = int(qty_str)
            if qty <= 0:
                raise ValueError
        except (ValueError, TypeError):
            print(f"  ❌  Invalid QTY '{qty_str}' — try again.\n")
            box_no -= 1
            continue

        print(f"\n  ✅  Secondary Model : {model_sec}")
        print(f"  📦  Capacity        : {qty} primary boxes")

        count   = 0          # primary boxes packed so far
        skipped = 0          # mismatch count (optional info)

        # ── inner packing loop ────────────────────────
        while count < qty:

            remaining = qty - count
            print(f"\n  ─── Scan PRIMARY BOX  [{count + 1}/{qty}]  "
                  f"({remaining} remaining) ───")
            prim_img = input("  Enter primary image path: ").strip()

            model_prim, part_no = extract_primary(prim_img)

            print(f"  Primary Model  : {model_prim}")
            if part_no:
                print(f"  Part No        : {part_no}")

            # ── match check ───────────────────────────
            if model_match(model_prim, model_sec):
                count += 1
                bar = "█" * count + "░" * (qty - count)
                print(f"  ✅  MATCHED  →  Packed {count}/{qty}  [{bar}]")
            else:
                skipped += 1
                print(f"  ❌  MODEL NOT MATCHED")
                print(f"      Expected : {model_sec}")
                print(f"      Got      : {model_prim}")
                print(f"  ⚠️   Box NOT packed. Scan the correct primary box.\n")
                # DO NOT break — keep looping so operator can retry

        # ── secondary box full alert ──────────────────
        print("\n" + "🚨" * 20)
        print(f"\n  🚨  SECONDARY BOX #{box_no} IS FULL  🚨")
        print(f"  ✅  {count} primary boxes packed  |  {skipped} rejected")
        print(f"\n  👉  PLEASE CHANGE THE SECONDARY BOX")
        print(f"      → Seal box #{box_no} and place a NEW secondary box")
        print("\n" + "🚨" * 20)

        cont = input("\n  Press ENTER to scan next secondary box  "
                     "(or type 'q' to quit): ").strip().lower()
        if cont == 'q':
            print(f"\n  📊  SESSION SUMMARY")
            print(f"      Total secondary boxes used : {box_no}")
            print(f"      Total primary boxes packed : {box_no * qty}")
            print("  👋  Packing session ended.\n")
            break


# ─────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    start_packing()