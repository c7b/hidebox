# SPDX-License-Identifier: MIT
"""Rename a subset Courier Prime TTX dump (name, CFF, OS/2, head tables) to its Mutis name.

The OFL (condition 3) forbids a Modified Version from using the Reserved Font Name as its
primary name, and Chromium rejects the Debian OTFs anyway because their CFF FontName has a
space ("Courier Prime-Regular"). Python standard library only: this edits fonttools' XML dump;
fonttools itself (Debian package) does the binary work in subset-fonts.sh.

Usage: python3 -I rename-font.py <tables.ttx> "<Family>" <Regular|Bold>
"""
import sys
import xml.etree.ElementTree as ET

KEEP = {"0", "5", "8", "9", "11", "12", "13", "14"}   # copyright, version, vendor, designer, URLs, licence
WEIGHT = {"Regular": 400, "Bold": 700}


def rename(path: str, family: str, style: str) -> None:
    postscript = family.replace(" ", "") + "-" + style
    full = f"{family} {style}"
    names = {"1": family, "2": style, "3": f"{postscript};{full}", "4": full, "6": postscript,
             "16": family, "17": style}
    tree = ET.parse(path)
    root = tree.getroot()

    table = root.find("name")
    for record in list(table):
        nid = record.get("nameID")
        if nid in names:
            record.text = names[nid]
        elif nid not in KEEP:
            table.remove(record)

    cff = root.find("CFF/CFFFont")
    cff.set("name", postscript)
    for tag, value in (("FullName", full), ("FamilyName", family), ("Weight", style)):
        cff.find(tag).set("value", value)

    bold = style == "Bold"
    os2 = root.find("OS_2")
    os2.find("usWeightClass").set("value", str(WEIGHT[style]))
    # fsSelection: bit 5 BOLD, bit 6 REGULAR; bit 7 USE_TYPO_METRICS as the source has it.
    selection = int(os2.find("fsSelection").get("value").replace(" ", ""), 2)
    selection = (selection & ~0b1100000) | (0b100000 if bold else 0b1000000)
    os2.find("fsSelection").set("value", format(selection, "016b")[:8] + " " + format(selection, "016b")[8:])
    root.find("head/macStyle").set("value", "00000000 0000000" + ("1" if bold else "0"))

    tree.write(path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[3] not in WEIGHT:
        sys.exit(__doc__)
    rename(*sys.argv[1:])
