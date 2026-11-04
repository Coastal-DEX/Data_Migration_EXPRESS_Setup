"""Crude Apex sanity check (no compiler reachable from the build machine): balanced (), {}, []
outside literals and comments, and no Apex reserved word used as an identifier (Apex is
case-insensitive, so ORDER is order). The first deploy remains the real compiler."""
import re
import sys

RESERVED = set("""abstract activate and any array as asc autonomous begin bigdecimal blob break bulk by byte
case cast catch char class collect commit const continue convertcurrency decimal default delete desc do
else end enum exception exit export extends false final finally float for from future global goto group
having hint if implements import in inner insert instanceof interface into int join like limit list long
loop map merge new not null nulls number object of offset on or order outer override package parallel pragma private
protected public retrieve return returning rollback savepoint search select set short sort stat static
super switch synchronized system testmethod then this throw tolabel transaction trigger true try type
undelete update upsert using virtual webservice when where while""".split())
DECL = re.compile(r"\b(?:String|Integer|Boolean|Decimal|Id|Long|Object|Date|Datetime|SObject|"
                  r"List<[^;()]*?>|Map<[^;()]*?>|Set<[^;()]*?>|Schema\.\w+|Database\.\w+|"
                  r"[A-Z]\w*__c|[A-Z]\w+)\s+(\w+)\s*(?=[=;,):])")


def strip(src):
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i)
            i = n if j < 0 else j + 2
            continue
        if src[i] == "'":
            j = i + 1
            while j < n and src[j] != "'":
                j += 2 if src[j] == "\\" else 1
            out.append("''")
            i = j + 1
            continue
        out.append(src[i])
        i += 1
    return "".join(out)


def main(files):
    bad = 0
    for f in files:
        s = strip(open(f, encoding="utf-8").read())
        s = re.sub(r"\[\s*SELECT\b[^\]]*\]", "[]", s, flags=re.I)     # inline SOQL is not Apex identifiers
        st = []
        for k, ch in enumerate(s):
            if ch in "({[":
                st.append(ch)
            elif ch in ")}]":
                if not st or "({["[")}]".index(ch)] != st[-1]:
                    print("UNBALANCED", f, "line", s[:k].count("\n") + 1)
                    bad += 1
                    break
                st.pop()
        else:
            if st:
                print("UNCLOSED", f)
                bad += 1
        for m in DECL.finditer(s):
            name = m.group(1)
            if name.lower() in RESERVED:
                print("RESERVED identifier", f, "line", s[:m.start()].count("\n") + 1, name)
                bad += 1
            if name.endswith("_") or name.startswith("_") or "__" in name:
                print("INVALID identifier (underscore rule)", f, "line", s[:m.start()].count("\n") + 1, name)
                bad += 1
        for m in re.finditer(r"\b(?:static|public|private|global)\s+[\w<>, .]+?\s+(\w+)\s*\(", s):
            if m.group(1).lower() in RESERVED:
                print("RESERVED method", f, m.group(1))
                bad += 1
    print("apex_lint:", len(files), "files,", bad, "problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
