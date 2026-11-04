"""EXPRESS setup-repo builders: the File 1 / File 3 contract, coded once.

Implements BUILDER_DESIGN_SPEC v1.0.4 sections 4 and 5 (stages 1 to 3) against
BUILD_PROMPT_V4_FILE_CONTRACT v1.0.1 (frozen). Shared by build_setup_seed.py and
build_setup_meta.py. Contains no client literal: every object, field and value enters
through the inputs (spec section 9 agnostic check).

Public entry points:
    load_describe(path)              -> Describe
    load_file1(path, describe)       -> Workbook1 (validated; raises ContractError)
    load_auto_spec(path, wb1, d)     -> list of AUTO_SPEC rows (validated)
    build_plan(wb1, describe)        -> plan dict (ordered steps, expected counts)
    write_resources(plan, wb1, dir)  -> list of (resource name, path, bytes)

Every check fails with the tab, row and column at fault. All errors are collected and
raised together, so one run lists every defect.
"""
import csv
import datetime as _dt
import hashlib
import io
import json
import re

CONTRACT_VERSION = "1.0.1"
API_VERSION = "66.0"           # single constant for both builders (finding #65)
DEFAULT_BATCH_SIZE = 200
RESOURCE_SPLIT_BYTES = 4_500_000   # platform limit is 5 MB per static resource [Likely]

# Platform audit fields: createable only with "Set Audit Fields upon Record Creation"
# enabled and granted. The describe omits them because they are not createable without it.
AUDIT_FIELDS = {"CreatedDate", "CreatedById", "LastModifiedDate", "LastModifiedById", "ClosedDate"}

# Standard picklist fields whose values live in a StandardValueSet (platform knowledge,
# not client data). A _REPO_FIELDS row extending a standard picklist that is not listed
# here fails the build rather than guessing a name.
STANDARD_VALUE_SETS = {
    ("Account", "Industry"): "Industry",
    ("Account", "Type"): "AccountType",
    ("Account", "AccountSource"): "AccountSource",
    ("Account", "Salutation"): "Salutation",
    ("Contact", "LeadSource"): "LeadSource",
    ("Lead", "LeadSource"): "LeadSource",
    ("Lead", "Status"): "LeadStatus",
    ("Lead", "Industry"): "Industry",
    ("Lead", "Rating"): "AccountRating",
    ("Opportunity", "StageName"): "OpportunityStage",
    ("Opportunity", "Type"): "OpportunityType",
    ("Opportunity", "LeadSource"): "LeadSource",
    ("Case", "Status"): "CaseStatus",
    ("Case", "Reason"): "CaseReason",
    ("Case", "Origin"): "CaseOrigin",
    ("Case", "Priority"): "CasePriority",
    ("Case", "Type"): "CaseType",
    ("Task", "Status"): "TaskStatus",
    ("Task", "Priority"): "TaskPriority",
    ("Product2", "Family"): "Product2Family",
    ("AccountContactRelation", "Roles"): "AccountContactMultiRoles",
}

# Records the platform creates as a side effect of a seeded insert. The census and the
# teardown exclude them so a delta equals File 1. Platform behaviour, not client data.
#   Contact: a Person Account insert creates its own Contact (IsPersonAccount = true).
#   AccountContactRelation: a Contact insert with an Account creates a direct relation.
CENSUS_FILTERS = {
    "Contact": "IsPersonAccount = false",
    "AccountContactRelation": "IsDirect = false",
}

ACTIVITY_OBJECTS = {"Task", "Event"}
REPO_TYPES = {"Text", "TextArea", "Email", "Number", "Currency", "Date", "DateTime",
              "Checkbox", "Picklist", "MultiPicklist"}
POPULATED = {"SEED", "LEARNER", "LOADER"}
AUTO_KINDS_V1 = {"VALIDATION_RULE", "TRIGGER_REQUIRED", "TRIGGER_CPU", "FLOW_CUSTOM_ERROR"}
AUTO_KINDS_V11 = {"DUPLICATE_RULE", "TRIGGER_ROLLUP_LOCK", "FLOW_FIELD_REWRITE"}
SUPPORTED_RELEASES = {"v1"}

KEYS_HEAD = ["Object", "RecordType", "KeyField", "Unique"]
RF_HEAD = ["Object", "Field", "Type", "Length", "Precision", "Scale", "Values",
           "Restricted", "ExternalId", "Unique", "Populated", "Note"]
AUTO_HEAD = ["Id", "Tab", "Release", "Object", "Kind", "Name", "Timing", "Condition",
             "WhenField", "WhenValue", "RequiredField", "ErrorField", "Message", "Bypassable"]

RT_HEADER = "RecordType.DeveloperName"
OWNER_HEADER = "Owner.Username"
API_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?(Z|[+-]\d{2}:?\d{2})$")


class ContractError(Exception):
    """Raised with every collected defect, one per line."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__(f"{len(self.errors)} contract error(s):\n" + "\n".join(self.errors))


class _Errors:
    def __init__(self):
        self.items = []

    def add(self, where, msg):
        self.items.append(f"[{where}] {msg}")

    def raise_if_any(self):
        if self.items:
            raise ContractError(self.items)


# ---------------------------------------------------------------- canonical values
def canon(v):
    """One deterministic text form per cell value, so resources and goldens are stable."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    if isinstance(v, _dt.datetime):
        if v.tzinfo is None:
            return v.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return v.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if isinstance(v, _dt.date):
        return v.isoformat()
    return str(v).strip()


# ---------------------------------------------------------------- describe
class Describe:
    """Target schema describe JSON (format of describe v2: objects with recordTypes and
    createable fields; shared State/Country code lists under _shared)."""

    def __init__(self, data):
        self.meta = data.get("_meta", {})
        self.shared = data.get("_shared", {})
        self.objects = {k: v for k, v in data.items() if not k.startswith("_")}
        self.fields = {o: {f["n"]: f for f in v.get("fields", [])} for o, v in self.objects.items()}

    def has_object(self, o):
        return o in self.objects

    def field(self, o, f):
        return self.fields.get(o, {}).get(f)

    def picklist(self, o, f):
        fd = self.field(o, f)
        if not fd or "pl" not in fd:
            return None
        pl = fd["pl"]
        if isinstance(pl, str) and pl.startswith("@"):
            return list(self.shared.get(pl[1:], []))
        return list(pl)

    def record_types(self, o):
        return {rt["dn"]: rt for rt in self.objects.get(o, {}).get("recordTypes", [])}

    def ref_targets(self, o, f):
        fd = self.field(o, f)
        if not fd or fd.get("t") != "reference":
            return None
        r = fd.get("ref")
        return [r] if isinstance(r, str) else list(r or [])

    def lookup_field(self, o, rel):
        """Map a relationship name to its lookup field. Uses the describe's relationship
        name ("rn") when the describe carries one; otherwise the platform naming rule
        (standard: <Rel>Id; custom: <X>__r -> <X>__c). The result must be a reference
        field in the describe, so a wrong guess fails validation, never mis-links."""
        for fd in self.fields.get(o, {}).values():
            if fd.get("rn") == rel and fd.get("t") == "reference":
                return fd["n"]
        cand = rel[:-3] + "__c" if rel.endswith("__r") else rel + "Id"
        fd = self.field(o, cand)
        if fd and fd.get("t") == "reference":
            return cand
        return None


def load_describe(path):
    with open(path, encoding="utf-8") as fh:
        return Describe(json.load(fh))


# ---------------------------------------------------------------- File 1 model
class Column:
    """One data-tab header, classified per contract section 4.1."""

    def __init__(self, header, kind, **kw):
        self.header = header
        self.kind = kind            # FIELD | RECORDTYPE | OWNER | LOOKUP | POLY_TYPE | POLY_KEY | AUDIT
        self.field = kw.get("field")        # target field API name on the object
        self.rel = kw.get("rel")
        self.key_field = kw.get("key_field")
        self.target = kw.get("target")      # LOOKUP: parent object
        self.self_ref = kw.get("self_ref", False)

    def as_plan(self):
        d = {"header": self.header, "kind": self.kind}
        for k in ("field", "rel", "key_field", "target"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        if self.self_ref:
            d["self_ref"] = True
        return d


class Tab:
    def __init__(self, name, index, headers, rows):
        self.name = name
        self.index = index
        self.headers = headers
        self.rows = rows            # list of lists of canonical strings
        self.columns = []

    def col(self, header):
        return self.headers.index(header)

    def values(self, header):
        i = self.col(header)
        return [r[i] for r in self.rows]


class Workbook1:
    def __init__(self):
        self.tabs = {}              # object -> Tab (data tabs only, in workbook order)
        self.keys = []              # list of dicts from _KEYS
        self.repo_fields = []       # list of dicts from _REPO_FIELDS
        self.key_sets = {}          # (object, recordType or '') -> set of key values
        self.md5 = None
        self.content_md5 = None

    def key_rows(self, obj):
        return [k for k in self.keys if k["Object"] == obj]

    def repo_field(self, obj, field):
        for r in self.repo_fields:
            if r["Object"] == obj and r["Field"] == field:
                return r
        return None


def _read_sheet(ws):
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    while rows and all(v is None for v in rows[-1]):
        rows.pop()
    if not rows:
        return [], []
    head = [canon(h) for h in rows[0]]
    while head and head[-1] == "":
        head.pop()
    body = [[canon(v) for v in r[:len(head)]] + [""] * max(0, len(head) - len(r)) for r in rows[1:]]
    body = [r for r in body if any(c != "" for c in r)]
    return head, body


def _manifest(ws, expected_head, err, where):
    head, body = _read_sheet(ws)
    if head[:len(expected_head)] != expected_head:
        err.add(where, f"header must be {expected_head}, found {head}")
        return []
    return [dict(zip(expected_head, r[:len(expected_head)])) for r in body]


def _md5(path):
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def load_file1(path, d):
    """Read and validate File 1 (spec section 5, stage 1). Returns Workbook1."""
    import openpyxl
    err = _Errors()
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    w1 = Workbook1()
    w1.md5 = _md5(path)                 # file bytes: provenance only (xlsx bytes carry save timestamps)
    content = hashlib.md5()
    names = wb.sheetnames
    for req in ("_KEYS", "_REPO_FIELDS"):
        if req not in names:
            err.add(req, "manifest tab missing")
    err.raise_if_any()
    w1.keys = _manifest(wb["_KEYS"], KEYS_HEAD, err, "_KEYS")
    w1.repo_fields = _manifest(wb["_REPO_FIELDS"], RF_HEAD, err, "_REPO_FIELDS")
    idx = 0
    for n in names:
        if n.startswith("_") or n.upper() == "README":
            continue
        head, body = _read_sheet(wb[n])
        content.update(repr((n, head, body)).encode())
        w1.tabs[n] = Tab(n, idx, head, body)
        idx += 1
    content.update(repr((w1.keys, w1.repo_fields)).encode())
    w1.content_md5 = content.hexdigest()
    wb.close()
    err.raise_if_any()
    _validate_manifests(w1, d, err)
    err.raise_if_any()
    for t in w1.tabs.values():
        _classify(t, w1, d, err)
    err.raise_if_any()
    _validate_keys(w1, err)
    err.raise_if_any()
    for t in w1.tabs.values():
        _validate_rows(t, w1, d, err)
    _validate_repo_coverage(w1, err)
    err.raise_if_any()
    return w1


def _validate_manifests(w1, d, err):
    for i, k in enumerate(w1.keys, start=2):
        where = f"_KEYS row {i}"
        if not d.has_object(k["Object"]):
            err.add(where, f"object {k['Object']} not in the describe")
            continue
        if k["Object"] not in w1.tabs:
            err.add(where, f"object {k['Object']} has no data tab")
        if k["Unique"] != "Y":
            err.add(where, "Unique must be Y")
        if k["RecordType"] and k["RecordType"] not in d.record_types(k["Object"]):
            err.add(where, f"record type {k['RecordType']} not in the describe for {k['Object']}")
        kf = k["KeyField"]
        if not d.field(k["Object"], kf) and not w1.repo_field(k["Object"], kf):
            err.add(where, f"key field {k['Object']}.{kf} not in the describe or _REPO_FIELDS")
    seen = set()
    for k in w1.keys:
        sig = (k["Object"], k["RecordType"])
        if sig in seen:
            err.add("_KEYS", f"duplicate key row for {sig}")
        seen.add(sig)
    for i, r in enumerate(w1.repo_fields, start=2):
        where = f"_REPO_FIELDS row {i} ({r['Object']}.{r['Field']})"
        if not d.has_object(r["Object"]):
            err.add(where, "object not in the describe")
        if r["Type"] not in REPO_TYPES:
            err.add(where, f"Type {r['Type']!r} not one of {sorted(REPO_TYPES)}")
        if r["Populated"] not in POPULATED:
            err.add(where, f"Populated {r['Populated']!r} not one of {sorted(POPULATED)}")
        for flag in ("Restricted", "ExternalId", "Unique"):
            if r[flag] not in ("Y", "N"):
                err.add(where, f"{flag} must be Y or N")
        std = d.field(r["Object"], r["Field"])
        if r["Field"].endswith("__c"):
            if std:
                err.add(where, "custom field already exists in the describe; remove the row")
            if r["Type"] == "Text" and not r["Length"]:
                err.add(where, "Text needs a Length")
            if r["Type"] in ("Picklist", "MultiPicklist") and not r["Values"]:
                err.add(where, "picklist needs Values")
            if not API_NAME.match(r["Field"].replace("__c", "")) or "__" in r["Field"][:-3]:
                err.add(where, "invalid custom field API name")
        else:
            if not std:
                err.add(where, "standard field not in the describe")
            elif r["Type"] not in ("Picklist", "MultiPicklist"):
                err.add(where, "a standard field row may only extend a standard picklist")
            elif (r["Object"], r["Field"]) not in STANDARD_VALUE_SETS:
                err.add(where, "no StandardValueSet name known for this standard picklist")
    sigs = [(r["Object"], r["Field"]) for r in w1.repo_fields]
    for s in sorted({s for s in sigs if sigs.count(s) > 1}):
        err.add("_REPO_FIELDS", f"duplicate row for {s[0]}.{s[1]}")


def _classify(t, w1, d, err):
    o = t.name
    if not d.has_object(o):
        err.add(o, "tab name is not an object in the describe")
        return
    seen = set()
    for c, h in enumerate(t.headers, start=1):
        where = f"{o} col {c} '{h}'"
        if h == "":
            err.add(where, "blank header")
            continue
        if h in seen:
            err.add(where, "duplicate header")
        seen.add(h)
        if "." not in h and h.endswith("Id"):
            err.add(where, "no column may end in Id (contract 4.1)")
            continue
        if h == RT_HEADER:
            if not d.record_types(o):
                err.add(where, "object has no record types in the describe")
            t.columns.append(Column(h, "RECORDTYPE", field="RecordTypeId"))
            continue
        if h == OWNER_HEADER:
            t.columns.append(Column(h, "OWNER", field="OwnerId"))
            continue
        if "." in h:
            rel, key = h.split(".", 1)
            fld = d.lookup_field(o, rel)
            if not fld:
                err.add(where, f"relationship {rel} is not a lookup on {o} in the describe")
                continue
            targets = d.ref_targets(o, fld)
            if key in ("Type", "Key"):
                other = f"{rel}.{'Key' if key == 'Type' else 'Type'}"
                if other not in t.headers:
                    err.add(where, f"polymorphic pair needs {other}")
                    continue
                t.columns.append(Column(h, "POLY_TYPE" if key == "Type" else "POLY_KEY",
                                        field=fld, rel=rel, self_ref=o in targets))
                continue
            if len(targets) != 1:
                err.add(where, f"{fld} is polymorphic ({len(targets)} types); use {rel}.Type + {rel}.Key")
                continue
            tgt = targets[0]
            krows = [k for k in w1.key_rows(tgt) if k["KeyField"] == key]
            if not krows:
                err.add(where, f"{tgt}.{key} is not a _KEYS key field")
                continue
            t.columns.append(Column(h, "LOOKUP", field=fld, rel=rel, key_field=key,
                                    target=tgt, self_ref=(tgt == o)))
            continue
        if h in AUDIT_FIELDS:
            t.columns.append(Column(h, "AUDIT", field=h))
            continue
        if not API_NAME.match(h):
            err.add(where, "not a valid header form")
            continue
        if not d.field(o, h) and not w1.repo_field(o, h):
            err.add(where, "field not createable in the describe and not in _REPO_FIELDS")
            continue
        fd = d.field(o, h)
        if fd and fd.get("t") == "reference":
            err.add(where, "a lookup must be written <Rel>.<KeyField>, not as a field")
            continue
        t.columns.append(Column(h, "FIELD", field=h))


def _row_key(t, row, krow):
    """The row's key value under one _KEYS row, or None if that row does not apply."""
    rt = krow["RecordType"]
    if rt:
        if RT_HEADER not in t.headers or row[t.col(RT_HEADER)] != rt:
            return None
    if krow["KeyField"] not in t.headers:
        return None
    return row[t.col(krow["KeyField"])]


def _validate_keys(w1, err):
    for k in w1.keys:
        t = w1.tabs.get(k["Object"])
        if not t:
            continue
        where = f"_KEYS {k['Object']}/{k['RecordType'] or '-'}/{k['KeyField']}"
        if k["KeyField"] not in t.headers:
            err.add(where, f"key field has no column in tab {t.name}")
            continue
        vals = {}
        for i, r in enumerate(t.rows, start=2):
            v = _row_key(t, r, k)
            if v is None:
                continue
            if v == "":
                err.add(f"{t.name} row {i}", f"blank key {k['KeyField']}")
                continue
            if v in vals:
                err.add(f"{t.name} row {i}", f"duplicate key {k['KeyField']}={v!r} (first at row {vals[v]})")
            vals.setdefault(v, i)
        w1.key_sets[(k["Object"], k["RecordType"])] = set(vals)
    # An object with two key rows: one value may not identify two records.
    for o in {k["Object"] for k in w1.keys}:
        rows = w1.key_rows(o)
        for a in range(len(rows)):
            for b in range(a + 1, len(rows)):
                sa = w1.key_sets.get((o, rows[a]["RecordType"]), set())
                sb = w1.key_sets.get((o, rows[b]["RecordType"]), set())
                for v in sorted(sa & sb)[:5]:
                    err.add(f"_KEYS {o}", f"key {v!r} matches under two key rows (AMBIGUOUS_PARENT)")


def _parent_hits(w1, obj, key_field, value):
    hits = 0
    for k in w1.key_rows(obj):
        if key_field is not None and k["KeyField"] != key_field:
            continue
        if value in w1.key_sets.get((obj, k["RecordType"]), set()):
            hits += 1
    return hits


def _type_of(w1, d, o, f):
    fd = d.field(o, f)
    if fd:
        return {"string": "Text", "textarea": "TextArea", "email": "Email", "phone": "Text",
                "url": "Text", "combobox": "Text", "picklist": "Picklist",
                "multipicklist": "MultiPicklist", "date": "Date", "datetime": "DateTime",
                "boolean": "Checkbox", "currency": "Currency", "double": "Number",
                "percent": "Number", "int": "Integer"}.get(fd.get("t"), "Text"), fd.get("len")
    r = w1.repo_field(o, f)
    if r:
        ln = int(r["Length"]) if r["Length"] else ({"Email": 80, "TextArea": 255}.get(r["Type"]))
        return r["Type"], ln
    return "Text", None


def _allowed_values(w1, d, o, f):
    fd = d.field(o, f)
    if fd and fd.get("t") == "combobox":
        return None             # a combobox accepts free text
    vals = d.picklist(o, f)
    r = w1.repo_field(o, f)
    extra = [v for v in (r["Values"].split(";") if r and r["Values"] else []) if v]
    if vals is None and not extra:
        return None
    return set(vals or []) | set(extra)


def _validate_rows(t, w1, d, err):
    o = t.name
    cols = {c.header: c for c in t.columns}
    # required fields present
    for fd in d.fields.get(o, {}).values():
        if not fd.get("req"):
            continue
        src = [c for c in t.columns if c.field == fd["n"]]
        if not src:
            err.add(o, f"required field {fd['n']} has no column")
    # lookup groups: several key columns on one lookup field, fill exactly one
    groups = {}
    for c in t.columns:
        if c.kind == "LOOKUP":
            groups.setdefault(c.field, []).append(c)
    checks = []
    for c in t.columns:
        i = t.col(c.header)
        if c.kind == "FIELD":
            typ, ln = _type_of(w1, d, o, c.field)
            checks.append((i, c, typ, ln, _allowed_values(w1, d, o, c.field)))
        elif c.kind == "AUDIT":
            checks.append((i, c, "DateTime", None, None))
    rts = d.record_types(o)
    for rn, row in enumerate(t.rows, start=2):
        where = f"{o} row {rn}"
        for i, c, typ, ln, allowed in checks:
            v = row[i]
            if v == "":
                continue
            if "\n" in v or "\r" in v:
                err.add(f"{where} '{c.header}'", "line break in value")
            if typ in ("Text", "TextArea", "Email") and ln and len(v) > int(ln):
                err.add(f"{where} '{c.header}'", f"length {len(v)} exceeds {ln}")
            elif typ == "Date" and not DATE_RE.match(v):
                err.add(f"{where} '{c.header}'", f"date {v!r} is not YYYY-MM-DD")
            elif typ == "DateTime" and not DATETIME_RE.match(v):
                err.add(f"{where} '{c.header}'", f"datetime {v!r} is not ISO 8601 with zone")
            elif typ in ("Currency", "Number", "Integer"):
                try:
                    float(v)
                except ValueError:
                    err.add(f"{where} '{c.header}'", f"{v!r} is not a number")
            elif typ == "Checkbox" and v.lower() not in ("true", "false"):
                err.add(f"{where} '{c.header}'", f"{v!r} is not true/false")
            if allowed is not None:
                parts = v.split(";") if typ == "MultiPicklist" else [v]
                for p in parts:
                    if p not in allowed:
                        err.add(f"{where} '{c.header}'", f"value {p!r} not in the describe or _REPO_FIELDS Values")
        for fd in d.fields.get(o, {}).values():
            if fd.get("req"):
                src = [c for c in t.columns if c.field == fd["n"]]
                if src and all(row[t.col(c.header)] == "" for c in src):
                    err.add(where, f"required {fd['n']} is blank")
        if RT_HEADER in cols:
            v = row[t.col(RT_HEADER)]
            if v and v not in rts:
                err.add(f"{where} '{RT_HEADER}'", f"record type {v!r} not in the describe")
        for fld, gcols in groups.items():
            filled = [c for c in gcols if row[t.col(c.header)] != ""]
            if len(filled) > 1:
                err.add(where, f"{fld}: fill exactly one of {[c.header for c in gcols]}")
            for c in filled:
                v = row[t.col(c.header)]
                hits = _parent_hits(w1, c.target, c.key_field, v)
                if hits == 0:
                    err.add(f"{where} '{c.header}'", f"{v!r} matches no {c.target} row in File 1 (MISSING_PARENT)")
        for c in t.columns:
            if c.kind != "POLY_TYPE":
                continue
            ty = row[t.col(c.header)]
            kv = row[t.col(f"{c.rel}.Key")]
            if (ty == "") != (kv == ""):
                err.add(where, f"{c.rel}.Type and {c.rel}.Key must both be filled or both blank")
                continue
            if ty == "":
                continue
            if ty not in d.ref_targets(o, c.field):
                err.add(f"{where} '{c.header}'", f"{ty!r} is not a target of {o}.{c.field}")
                continue
            if not w1.key_rows(ty):
                err.add(f"{where} '{c.header}'", f"{ty} has no _KEYS row")
                continue
            hits = _parent_hits(w1, ty, None, kv)
            if hits != 1:
                err.add(f"{where} '{c.rel}.Key'", f"{kv!r} matches {hits} {ty} rows in File 1 "
                        f"({'MISSING' if hits == 0 else 'AMBIGUOUS'}_PARENT)")


def _validate_repo_coverage(w1, err):
    """Standing rule 10: both directions."""
    for r in w1.repo_fields:
        t = w1.tabs.get(r["Object"])
        where = f"_REPO_FIELDS {r['Object']}.{r['Field']}"
        has_col = bool(t and r["Field"] in t.headers)
        if r["Populated"] == "SEED" and not has_col:
            err.add(where, "Populated=SEED but File 1 has no column")
        if r["Populated"] in ("LEARNER", "LOADER") and has_col:
            err.add(where, f"Populated={r['Populated']} but File 1 has a column")
        if r["Populated"] == "LOADER":
            if r["Type"] != "Text":
                err.add(where, "a LOADER owner lineage field must be Text")
            if not t or OWNER_HEADER not in t.headers:
                err.add(where, f"LOADER field on an object with no {OWNER_HEADER} column")
    for o, t in w1.tabs.items():
        if OWNER_HEADER in t.headers:
            n = [r for r in w1.repo_fields if r["Object"] == o and r["Populated"] == "LOADER"]
            if len(n) != 1:
                err.add(f"{o} '{OWNER_HEADER}'", f"needs exactly one LOADER field in _REPO_FIELDS, found {len(n)}")


def owner_field(w1, obj):
    for r in w1.repo_fields:
        if r["Object"] == obj and r["Populated"] == "LOADER":
            return r["Field"]
    return None


# ---------------------------------------------------------------- File 3 AUTO_SPEC
def load_auto_spec(path, w1, d):
    import openpyxl
    err = _Errors()
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if "AUTO_SPEC" not in wb.sheetnames:
        raise ContractError(["[AUTO_SPEC] tab missing in File 3"])
    rows = _manifest(wb["AUTO_SPEC"], AUTO_HEAD, err, "AUTO_SPEC")
    tabs = [n for n in wb.sheetnames if n not in ("AUTO_SPEC",) and not n.startswith("_")
            and n.upper() not in ("README", "TEARDOWN")]
    wb.close()
    err.raise_if_any()
    ids = set()
    for i, a in enumerate(rows, start=2):
        where = f"AUTO_SPEC row {i} ({a['Id']})"
        if a["Id"] in ids:
            err.add(where, "duplicate Id")
        ids.add(a["Id"])
        if a["Tab"] not in tabs:
            err.add(where, f"Tab {a['Tab']!r} not in File 3")
        if a["Release"] not in ("v1", "v1.1"):
            err.add(where, "Release must be v1 or v1.1")
        if a["Kind"] not in AUTO_KINDS_V1 | AUTO_KINDS_V11:
            err.add(where, f"Kind {a['Kind']!r} unknown")
        if a["Release"] == "v1" and a["Kind"] not in AUTO_KINDS_V1:
            err.add(where, f"Kind {a['Kind']} has no v1 template")
        if not d.has_object(a["Object"]):
            err.add(where, f"object {a['Object']} not in the describe")
        if not API_NAME.match(a["Name"] or "") or "__" in a["Name"]:
            err.add(where, "Name must be an API name")
        if a["Bypassable"] not in ("Y", "N"):
            err.add(where, "Bypassable must be Y or N")
        if a["Release"] != "v1":
            continue
        k = a["Kind"]
        if k in ("VALIDATION_RULE", "FLOW_CUSTOM_ERROR") and not a["Condition"]:
            err.add(where, "Condition required")
        if k == "TRIGGER_REQUIRED":
            for f in ("WhenField", "WhenValue", "RequiredField"):
                if not a[f]:
                    err.add(where, f"{f} required")
        if k in ("TRIGGER_REQUIRED", "TRIGGER_CPU"):
            if a["Timing"] not in ("before insert", "after insert", "before update", "after update"):
                err.add(where, "Timing must be a trigger event")
        if k in ("VALIDATION_RULE", "TRIGGER_REQUIRED", "FLOW_CUSTOM_ERROR") and not a["Message"]:
            err.add(where, "Message required")
        for f in ("ErrorField", "WhenField", "RequiredField"):
            fv = a[f]
            if fv and not d.field(a["Object"], fv) and not w1.repo_field(a["Object"], fv):
                err.add(where, f"{f} {a['Object']}.{fv} not in the describe or _REPO_FIELDS")
    for t in tabs:
        if t.upper().startswith("AUTO") and not any(a["Tab"] == t for a in rows):
            err.add("AUTO_SPEC", f"record-set tab {t} is named by no row")
    err.raise_if_any()
    return rows


def v1_rows(auto):
    return [a for a in auto if a["Release"] in SUPPORTED_RELEASES]


def check_seed_against_v1(w1, auto):
    """Contract: the clean File 1 must not violate any v1 TRIGGER_REQUIRED row.
    (Formula kinds are checked by the first deploy and done-test T6, not here.)"""
    bad = []
    for a in v1_rows(auto):
        if a["Kind"] != "TRIGGER_REQUIRED":
            continue
        t = w1.tabs.get(a["Object"])
        if not t or a["WhenField"] not in t.headers:
            continue
        req = t.col(a["RequiredField"]) if a["RequiredField"] in t.headers else None
        for i, r in enumerate(t.rows, start=2):
            if r[t.col(a["WhenField"])] == a["WhenValue"] and (req is None or r[req] == ""):
                bad.append(f"[{t.name} row {i}] violates {a['Id']} {a['Name']}")
    if bad:
        raise ContractError(bad)


# ---------------------------------------------------------------- plan (stage 2)
def build_plan(w1, d, batch_size=DEFAULT_BATCH_SIZE):
    err = _Errors()
    deps = {}
    for o, t in w1.tabs.items():
        ds = set()
        for c in t.columns:
            if c.kind == "LOOKUP" and not c.self_ref:
                ds.add(c.target)
            if c.kind == "POLY_TYPE":
                ds |= {v for v in t.values(c.header) if v and v != o}
        missing = sorted(x for x in ds if x not in w1.tabs)
        for m in missing:
            err.add(o, f"depends on {m}, which has no data tab")
        deps[o] = ds & set(w1.tabs)
    err.raise_if_any()
    order, done = [], set()
    pending = sorted(w1.tabs, key=lambda o: w1.tabs[o].index)
    while pending:
        ready = [o for o in pending if deps[o] <= done]
        if not ready:
            raise ContractError([f"[plan] lookup cycle among {pending} (only self-lookups may cycle)"])
        o = ready[0]
        order.append(o)
        done.add(o)
        pending.remove(o)
    steps = []
    for o in order:
        t = w1.tabs[o]
        self_cols = [c for c in t.columns if c.self_ref and c.kind in ("LOOKUP", "POLY_TYPE", "POLY_KEY")]
        ins_cols = [c for c in t.columns if c not in self_cols]
        steps.append(_step(len(steps) + 1, o, "insert", ins_cols, t.rows, t, w1, d, batch_size))
        if self_cols:
            if not w1.key_rows(o):
                raise ContractError([f"[{o}] self-lookup needs a _KEYS row to find the child"])
            key_heads = [RT_HEADER] if RT_HEADER in t.headers else []
            key_heads += sorted({k["KeyField"] for k in w1.key_rows(o)}, key=t.headers.index)
            idx = [t.headers.index(c.header) for c in self_cols]
            rows = [r for r in t.rows if any(r[i] != "" for i in idx)]
            kcols = [next(c for c in t.columns if c.header == h) for h in key_heads]
            steps.append(_step(len(steps) + 1, o, "update", kcols + self_cols, rows, t, w1, d,
                               batch_size, key_headers=key_heads))
    owners = sorted({u for t in w1.tabs.values() if OWNER_HEADER in t.headers
                     for u in t.values(OWNER_HEADER) if u})
    plan = {
        "contract_version": CONTRACT_VERSION,
        "api_version": API_VERSION,
        "file1_content_md5": w1.content_md5,
        "keys": [{"object": k["Object"], "record_type": k["RecordType"] or None,
                  "key_field": k["KeyField"]} for k in w1.keys],
        "steps": steps,
        "objects": order,
        "owner_usernames": len(owners),
        "repo_fields": [{"object": r["Object"], "field": r["Field"], "populated": r["Populated"]}
                        for r in w1.repo_fields if r["Field"].endswith("__c")],
        "census": census_rows(w1, d, order),
    }
    plan["requires"] = _requirements(plan, w1, d)
    return plan


def _step(n, o, op, cols, rows, t, w1, d, batch_size, key_headers=None):
    s = {
        "n": n,
        "name": f"S{n:02d}_{o}_{op}",
        "object": o,
        "op": op,
        "rows": len(rows),
        "batch_size": batch_size,
        "columns": [c.as_plan() for c in cols],
        "resources": [],
    }
    if key_headers:
        s["key_headers"] = key_headers
    if any(c.kind == "OWNER" for c in cols):
        s["owner_field"] = owner_field(w1, o)
    s["_rows"] = rows
    s["_cols"] = cols
    s["_tab"] = t
    return s


def census_rows(w1, d, order):
    """Expected AFTER minus BEFORE per object, computed from File 1, never typed."""
    out = []
    for o in order:
        t = w1.tabs[o]
        row = {"object": o, "expected": len(t.rows), "filter": CENSUS_FILTERS.get(o)}
        out.append(row)
        if RT_HEADER in t.headers:
            counts = {}
            for v in t.values(RT_HEADER):
                counts[v] = counts.get(v, 0) + 1
            for rt in sorted(counts):
                out.append({"object": o, "record_type": rt, "expected": counts[rt],
                            "filter": CENSUS_FILTERS.get(o)})
    return out


def _requirements(plan, w1, d):
    """Prechecks derived from the plan (spec 7.2), in the fixed order."""
    objects = plan["objects"]
    rts, person_rts, codes, audit = {}, set(), set(), {}
    for o in objects:
        t = w1.tabs[o]
        if RT_HEADER in t.headers:
            used = sorted({v for v in t.values(RT_HEADER) if v})
            rts[o] = used
            for v in used:
                if d.record_types(o).get(v, {}).get("person"):
                    person_rts.add(f"{o}.{v}")
        for c in t.columns:
            if c.kind == "FIELD" and (c.field.endswith("StateCode") or c.field.endswith("CountryCode")):
                codes.add(f"{o}.{c.field}")
            if c.kind == "AUDIT":
                audit.setdefault(o, []).append(c.field)
    first_keyed = None
    for s in plan["steps"]:
        if s["op"] == "insert" and w1.key_rows(s["object"]):
            k = w1.key_rows(s["object"])[0]
            vals = [v for v in (_row_key(s["_tab"], r, k) for r in s["_rows"]) if v][:10]
            first_keyed = {"object": s["object"], "key_field": k["KeyField"],
                           "record_type": k["RecordType"] or None, "keys": vals}
            break
    return {
        "objects": objects,
        "record_types": rts,
        "person_record_types": sorted(person_rts),
        "state_country_fields": sorted(codes),
        "contacts_to_multiple_accounts": "AccountContactRelation" in objects,
        "audit_fields": {k: sorted(v) for k, v in audit.items()},
        "repo_fields": [f"{r['Object']}.{r['Field']}" for r in w1.repo_fields if r["Field"].endswith("__c")],
        "already_seeded": first_keyed,
    }


def public_plan(plan):
    """The plan without private build state, as written to SEED_PLAN.json."""
    p = dict(plan)
    p["steps"] = [{k: v for k, v in s.items() if not k.startswith("_")} for s in plan["steps"]]
    return p


# ---------------------------------------------------------------- resources (stage 3)
def _csv_text(headers, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(headers)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def resource_texts(plan):
    """Per step, one or more RFC 4180 CSV parts, each under the split size, header repeated."""
    out = []
    for s in plan["steps"]:
        t = s["_tab"]
        heads = [c.header for c in s["_cols"]]
        idx = [t.headers.index(h) for h in heads]
        rows = [[r[i] for i in idx] for r in s["_rows"]]
        parts, cur = [], []
        head_txt = _csv_text(heads, [])
        size = len(head_txt.encode())
        for r in rows:
            line = len(_csv_text([], [r]).encode()) - len(_csv_text([], []).encode())
            if cur and size + line > RESOURCE_SPLIT_BYTES:
                parts.append(cur)
                cur, size = [], len(head_txt.encode())
            cur.append(r)
            size += line
        parts.append(cur)
        names = []
        for p_i, p in enumerate(parts, start=1):
            name = f"SEED_{s['n']:02d}" if len(parts) == 1 else f"SEED_{s['n']:02d}_{p_i}"
            names.append(name)
            out.append((name, _csv_text(heads, p)))
        s["resources"] = names
    return out
