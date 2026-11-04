"""Offline tests for the client-agnostic builders (spec v1.0.4 section 10.2, D.11 golden file).

  1. Golden file: the toy client regenerates byte-identical to toy/golden/clients/TOY.
  2. Plan order: the toy plan is exactly the expected step list.
  3. Negative cases: each contract defect fails validation with its own message
     (a check that cannot fail proves nothing, standing rule 9).
  4. Agnostic grep (done-test T2) over the builder sources.

Usage:
    python3 test_builders.py            # run all tests, exit 0 on pass
    python3 test_builders.py --update   # rewrite the golden tree (review the diff first)
"""
import filecmp
import os
import re
import shutil
import subprocess
import sys
import tempfile

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
GOLDEN = os.path.join(HERE, "golden", "clients", "TOY")
sys.path.insert(0, SRC)
import contract as C  # noqa: E402

EXPECTED_STEPS = ["S01_Account_insert", "S02_Account_update", "S03_Asset_insert",
                  "S04_Case_insert", "S05_Task_insert"]
AGNOSTIC = re.compile(r"npc|fins|coastie|cfg|harbor|gift|deliverable|financialaccount", re.I)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def make_inputs(d):
    rc, out = run([sys.executable, os.path.join(HERE, "make_toy_inputs.py"), "--out", d])
    assert rc == 0, out


def build(inp, out):
    for b in ("build_setup_seed.py", "build_setup_meta.py"):
        rc, log = run([sys.executable, os.path.join(SRC, b), "--file1", f"{inp}/file1.xlsx",
                       "--file3", f"{inp}/file3.xlsx", "--describe", f"{inp}/describe.json",
                       "--client", f"{inp}/client.json", "--out", out])
        if rc != 0:
            return rc, log
    return 0, ""


def tree_diff(a, b):
    diffs = []
    cmp = filecmp.dircmp(a, b)

    def walk(c, rel):
        diffs.extend(f"only in generated: {rel}{x}" for x in c.left_only)
        diffs.extend(f"only in golden: {rel}{x}" for x in c.right_only)
        for f in c.common_files:
            if not filecmp.cmp(os.path.join(c.left, f), os.path.join(c.right, f), shallow=False):
                diffs.append(f"differs: {rel}{f}")
        for n, sub in c.subdirs.items():
            walk(sub, f"{rel}{n}/")
    walk(cmp, "")
    return diffs


def mutate(inp, sheet, fn):
    p = f"{inp}/file1.xlsx" if sheet != "AUTO_SPEC" else f"{inp}/file3.xlsx"
    wb = openpyxl.load_workbook(p)
    fn(wb[sheet])
    wb.save(p)


def setv(ws, r, c, v):
    ws.cell(r, c).value = v      # ws.cell(r, c, None) would leave the old value in place


NEGATIVE = [
    ("missing parent", "Asset", lambda ws: ws.cell(2, 3, "No Such Works"), "MISSING_PARENT"),
    ("duplicate key", "Asset", lambda ws: ws.cell(3, 2, "SN-100"), "duplicate key SerialNumber"),
    ("unlisted picklist value", "Account", lambda ws: ws.cell(2, 8, "Platinum"), "value 'Platinum' not in"),
    ("column ending in Id", "Case", lambda ws: ws.cell(1, 7, "AssetId"), "no column may end in Id"),
    ("SEED field with no column", "_REPO_FIELDS", lambda ws: setv(ws, 3, 11, "SEED"),
     "Populated=SEED but File 1 has no column"),
    ("polymorphic as plain lookup", "Task", lambda ws: (ws.cell(1, 2, "What.Name"), ws.cell(1, 3, "Other")),
     "is polymorphic"),
    ("polymorphic type not a target", "Task", lambda ws: ws.cell(2, 2, "Lead"), "is not a target"),
    ("two keys filled on one lookup", "Asset", lambda ws: ws.cell(2, 4, "BR-001"), "fill exactly one"),
    ("required field blank", "Asset", lambda ws: setv(ws, 2, 1, None), "required Name is blank"),
    ("bad date", "Asset", lambda ws: ws.cell(2, 5, "03/01/2024"), "is not YYYY-MM-DD"),
    ("unknown record type", "Account", lambda ws: ws.cell(2, 1, "Nope"), "record type 'Nope' not in"),
    ("LOADER row missing", "_REPO_FIELDS", lambda ws: ws.delete_rows(5), "needs exactly one LOADER field"),
    ("seed violates v1 trigger", "Asset", lambda ws: setv(ws, 2, 5, None), "violates T2"),
    ("unknown AUTO kind", "AUTO_SPEC", lambda ws: ws.cell(2, 5, "MAGIC"), "Kind 'MAGIC' unknown"),
    ("AUTO tab named by no row", "AUTO_SPEC", lambda ws: ws.delete_rows(4), "is named by no row"),
]


def main():
    update = "--update" in sys.argv
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        inp, out = f"{tmp}/in", f"{tmp}/out/clients/TOY"
        make_inputs(inp)
        rc, log = build(inp, out)
        if rc != 0:
            print(log)
            print("FAIL: builders did not exit 0 on the toy client")
            return 1
        # 2. plan order
        d = C.load_describe(f"{inp}/describe.json")
        w1 = C.load_file1(f"{inp}/file1.xlsx", d)
        plan = C.build_plan(w1, d)
        names = [s["name"] for s in plan["steps"]]
        rows = [s["rows"] for s in plan["steps"]]
        if names != EXPECTED_STEPS or rows != [5, 2, 3, 2, 5]:
            fails.append(f"plan order {names} rows {rows}")
        # determinism: a second build into a fresh tree is identical
        out2 = f"{tmp}/out2/clients/TOY"
        build(inp, out2)
        dd = tree_diff(out, out2)
        if dd:
            fails.append("non-deterministic output: " + "; ".join(dd[:5]))
        # 1. golden
        if update:
            if os.path.exists(GOLDEN):
                shutil.rmtree(GOLDEN)
            shutil.copytree(out, GOLDEN)
            print(f"golden rewritten: {GOLDEN}")
        elif not os.path.isdir(GOLDEN):
            fails.append("no golden tree; run with --update once and review it")
        else:
            gd = tree_diff(out, GOLDEN)
            if gd:
                fails.append("golden mismatch: " + "; ".join(gd[:10]))
        # 3. negative cases
        for label, sheet, fn, expect in NEGATIVE:
            ninp = f"{tmp}/neg"
            if os.path.exists(ninp):
                shutil.rmtree(ninp)
            shutil.copytree(inp, ninp)
            mutate(ninp, sheet, fn)
            rc, log = build(ninp, f"{tmp}/negout")
            if rc == 0 or expect not in log:
                fails.append(f"negative '{label}': rc={rc}, expected {expect!r} in output; got: {log.strip()[-300:]}")
            else:
                print(f"  negative OK: {label}")
    # 5. Apex lint over the golden tree (reserved identifiers, balance). Not a compiler.
    import glob
    apex = (glob.glob(f"{GOLDEN}/force-app/main/default/classes/*.cls")
            + glob.glob(f"{GOLDEN}/force-app/main/default/triggers/*.trigger") + glob.glob(f"{GOLDEN}/scripts/*.apex"))
    rc, log = run([sys.executable, os.path.join(SRC, "apex_lint.py")] + apex)
    if rc != 0:
        fails.append("apex lint: " + log.strip())
    # 4. agnostic grep
    for f in ("contract.py", "build_setup_seed.py", "build_setup_meta.py", "apex_templates.py"):
        for i, line in enumerate(open(os.path.join(SRC, f), encoding="utf-8"), start=1):
            if AGNOSTIC.search(line):
                fails.append(f"agnostic grep hit {f}:{i}: {line.strip()}")
    if fails:
        print("TESTS FAILED")
        for x in fails:
            print("  " + x)
        return 1
    print(f"TESTS PASSED: golden, plan order {len(EXPECTED_STEPS)} steps, determinism, "
          f"{len(NEGATIVE)} negative cases, apex lint clean, agnostic grep 0 lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
