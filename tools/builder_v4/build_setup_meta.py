"""EXPRESS setup-repo builder, metadata half (spec v1.0.4 sections 6, 8 and 9).

Reads the same inputs as build_setup_seed.py and writes, under clients/<Code>/:
  sfdx-project.json, .forceignore
  custom fields from _REPO_FIELDS (Task/Event fields on Activity)
  StandardValueSets as the UNION of the org's values (describe) and the added values
  Seed_Step_Result__c, Migration_Settings__c + Bypass_Automation__c
  permission set EXPRESS_Seed_Admin (FLS, object CRUD, class access, Set Audit Fields)
  the enforcement layer from File 3 AUTO_SPEC (v1 kinds only; a kind with no template fails)
  README.md generated from the plan

Client-free: everything client-specific arrives through the arguments.

Usage:
    python3 build_setup_meta.py --file1 F1.xlsx --file3 F3.xlsx --describe d.json \
        --client client.json --out <repo>/clients/<Code>
"""
import argparse
import json
import os
import re
import sys
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract as C                     # noqa: E402

NS = 'xmlns="http://soap.sforce.com/2006/04/metadata"'
XML = '<?xml version="1.0" encoding="UTF-8"?>\n'
FA = "force-app/main/default"
PERMSET = "EXPRESS_Seed_Admin"
SEED_CLASSES = ["ExpressCsv", "ExpressSeed", "ExpressSeedBatch"]
# Objects whose access comes from parent objects or user permissions, so a permission set
# may not carry objectPermissions for them (platform rule).
NO_OBJECT_PERMS = {"Task", "Event", "AccountContactRelation"}
CPU_MS_PER_RECORD = 75     # 200 records x 75 ms = 15,000 ms, over the 10,000 ms sync limit


def write(root, rel, text, written):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    written.append(rel)


def label_of(api):
    return api[:-3].replace("_", " ") if api.endswith("__c") else api


def field_home(obj):
    return "Activity" if obj in C.ACTIVITY_OBJECTS else obj


# ---------------------------------------------------------------- custom fields
def field_xml(r):
    name, typ = r["Field"], r["Type"]
    parts = [f"    <fullName>{name}</fullName>"]
    note = r.get("Note") or ""
    if note:
        parts.append(f"    <description>{escape(note)}</description>")
    if r["ExternalId"] == "Y":
        parts.append("    <externalId>true</externalId>")
    parts.append(f"    <label>{escape(label_of(name))}</label>")
    if typ == "Text":
        parts.append(f"    <length>{int(r['Length'])}</length>")
    if typ in ("Number", "Currency"):
        parts.append(f"    <precision>{int(r['Precision'] or 18)}</precision>")
    if typ == "Checkbox":
        parts.insert(1, "    <defaultValue>false</defaultValue>")
    else:
        parts.append("    <required>false</required>")
    if typ in ("Number", "Currency"):
        parts.append(f"    <scale>{int(r['Scale'] or (2 if typ == 'Currency' else 0))}</scale>")
    if typ == "TextArea":
        pass
    parts.append(f"    <type>{typ}</type>")
    if typ in ("Text", "Email") and r["Unique"] == "Y":
        parts.append("    <unique>true</unique>")
    if typ in ("Picklist", "MultiPicklist"):
        vals = [v for v in r["Values"].split(";") if v]
        vs = "\n".join(f"            <value>\n                <fullName>{escape(v)}</fullName>\n"
                       f"                <default>false</default>\n                <label>{escape(v)}</label>\n"
                       f"            </value>" for v in vals)
        parts.append(f"    <valueSet>\n        <restricted>{'true' if r['Restricted'] == 'Y' else 'false'}</restricted>\n"
                     f"        <valueSetDefinition>\n            <sorted>false</sorted>\n{vs}\n"
                     f"        </valueSetDefinition>\n    </valueSet>")
        if typ == "MultiPicklist":
            parts.append("    <visibleLines>4</visibleLines>")
    return f"{XML}<CustomField {NS}>\n" + "\n".join(parts) + "\n</CustomField>\n"


def standard_value_set(name, values):
    body = "\n".join(f"    <standardValue>\n        <fullName>{escape(v)}</fullName>\n"
                     f"        <default>false</default>\n        <label>{escape(v)}</label>\n"
                     f"    </standardValue>" for v in values)
    return f"{XML}<StandardValueSet {NS}>\n    <sorted>false</sorted>\n{body}\n</StandardValueSet>\n"


# ---------------------------------------------------------------- fixed objects
RESULT_FIELDS = [  # (api, type, extra)
    ("Run_Id__c", "Text", "<length>40</length>"),
    ("Step__c", "Number", "<precision>4</precision><scale>0</scale>"),
    ("Step_Name__c", "Text", "<length>80</length>"),
    ("Object__c", "Text", "<length>80</length>"),
    ("Operation__c", "Text", "<length>10</length>"),
    ("Expected__c", "Number", "<precision>9</precision><scale>0</scale>"),
    ("Succeeded__c", "Number", "<precision>9</precision><scale>0</scale>"),
    ("Errors__c", "Number", "<precision>9</precision><scale>0</scale>"),
    ("Missing_Parent__c", "Number", "<precision>9</precision><scale>0</scale>"),
    ("Ambiguous_Parent__c", "Number", "<precision>9</precision><scale>0</scale>"),
    ("Failed_Batches__c", "Number", "<precision>9</precision><scale>0</scale>"),
    ("Owners_Remapped__c", "Number", "<precision>9</precision><scale>0</scale>"),
    ("Sample_Errors__c", "LongTextArea", "<length>32768</length><visibleLines>5</visibleLines>"),
]


def fixed_metadata(out, written):
    write(out, f"{FA}/objects/Seed_Step_Result__c/Seed_Step_Result__c.object-meta.xml",
          f"""{XML}<CustomObject {NS}>
    <deploymentStatus>Deployed</deploymentStatus>
    <description>One row per EXPRESS seed step: expected, succeeded and every error counter. Written by ExpressSeedBatch.finish().</description>
    <enableActivities>false</enableActivities>
    <enableReports>true</enableReports>
    <enableSearch>false</enableSearch>
    <label>Seed Step Result</label>
    <nameField>
        <label>Seed Step Result Name</label>
        <type>Text</type>
    </nameField>
    <pluralLabel>Seed Step Results</pluralLabel>
    <sharingModel>ReadWrite</sharingModel>
</CustomObject>
""", written)
    for api, typ, extra in RESULT_FIELDS:
        req = "" if typ == "LongTextArea" else "\n    <required>false</required>"
        write(out, f"{FA}/objects/Seed_Step_Result__c/fields/{api}.field-meta.xml",
              f"{XML}<CustomField {NS}>\n    <fullName>{api}</fullName>\n    {extra}\n"
              f"    <label>{label_of(api)}</label>{req}\n    <type>{typ}</type>\n</CustomField>\n", written)
    write(out, f"{FA}/objects/Migration_Settings__c/Migration_Settings__c.object-meta.xml",
          f"""{XML}<CustomObject {NS}>
    <customSettingsType>Hierarchy</customSettingsType>
    <description>Bypass_Automation__c is set true by ExpressSeed.run() while the seed loads, so the enforcement layer stays dormant for clean seed data, then false again so learner loads hit it.</description>
    <label>Migration Settings</label>
    <visibility>Public</visibility>
</CustomObject>
""", written)
    write(out, f"{FA}/objects/Migration_Settings__c/fields/Bypass_Automation__c.field-meta.xml",
          f"""{XML}<CustomField {NS}>
    <fullName>Bypass_Automation__c</fullName>
    <defaultValue>false</defaultValue>
    <description>When true, every EXPRESS enforcement rule, trigger and flow skips. Set by the seed loader only.</description>
    <label>Bypass Automation</label>
    <type>Checkbox</type>
</CustomField>
""", written)


# ---------------------------------------------------------------- permission set
def permission_set(w1, plan):
    fps = []
    for r in w1.repo_fields:
        if not r["Field"].endswith("__c"):
            continue
        if r["Object"] in C.ACTIVITY_OBJECTS:
            # Field lives on Activity, but FLS is granted per Task and Event. Measured in
            # coastal-a 2026-11-04: "Activity.<Field>" deployed without error and granted nothing.
            fps += [f"Task.{r['Field']}", f"Event.{r['Field']}"]
        else:
            fps.append(f"{r['Object']}.{r['Field']}")
    fps += [f"Seed_Step_Result__c.{a}" for a, _, _ in RESULT_FIELDS]
    fps = sorted(set(fps))
    objs = sorted({s["object"] for s in plan["steps"]} - NO_OBJECT_PERMS) + ["Seed_Step_Result__c"]
    parts = [f"    <classAccesses>\n        <apexClass>{c}</apexClass>\n        <enabled>true</enabled>\n    </classAccesses>"
             for c in SEED_CLASSES]
    parts += [f"    <fieldPermissions>\n        <editable>true</editable>\n        <field>{f}</field>\n"
              f"        <readable>true</readable>\n    </fieldPermissions>" for f in fps]
    parts += [f"    <objectPermissions>\n        <allowCreate>true</allowCreate>\n        <allowDelete>true</allowDelete>\n"
              f"        <allowEdit>true</allowEdit>\n        <allowRead>true</allowRead>\n"
              f"        <modifyAllRecords>false</modifyAllRecords>\n        <object>{o}</object>\n"
              f"        <viewAllRecords>false</viewAllRecords>\n    </objectPermissions>" for o in objs]
    if plan["requires"]["audit_fields"]:
        parts.append("    <userPermissions>\n        <enabled>true</enabled>\n        <name>CreateAuditFields</name>\n    </userPermissions>")
    body = "\n".join(parts)
    return (f"{XML}<PermissionSet {NS}>\n    <description>EXPRESS seed loader: FLS on every repo field, CRUD on every seeded object, "
            f"loader class access{', Set Audit Fields' if plan['requires']['audit_fields'] else ''}. Generated.</description>\n"
            f"    <hasActivationRequired>false</hasActivationRequired>\n    <label>EXPRESS Seed Admin</label>\n{body}\n</PermissionSet>\n")


# ---------------------------------------------------------------- enforcement (spec 8)
def _bypass_formula(a, cond, flow=False):
    if a["Bypassable"] != "Y":
        return cond
    ref = "{!$Setup.Migration_Settings__c.Bypass_Automation__c}" if flow else "$Setup.Migration_Settings__c.Bypass_Automation__c"
    return f"AND(NOT({ref}), {cond})"


def render_validation_rule(a):
    f = _bypass_formula(a, a["Condition"])
    return (f"{XML}<ValidationRule {NS}>\n    <fullName>{a['Name']}</fullName>\n    <active>true</active>\n"
            f"    <description>EXPRESS enforcement {a['Id']} ({escape(a['Tab'])}). Generated from AUTO_SPEC.</description>\n"
            f"    <errorConditionFormula>{escape(f)}</errorConditionFormula>\n"
            + (f"    <errorDisplayField>{a['ErrorField']}</errorDisplayField>\n" if a["ErrorField"] else "")
            + f"    <errorMessage>{escape(a['Message'])}</errorMessage>\n</ValidationRule>\n")


def _events(timing):
    return timing.strip().lower()            # validated by contract: 'before insert' etc.


def _bypass_apex(a):
    if a["Bypassable"] != "Y":
        return ""
    return ("    Migration_Settings__c ms = Migration_Settings__c.getOrgDefaults();\n"
            "    if (ms != null && ms.Bypass_Automation__c == true) { return; }\n")


def _apex_lit(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def render_trigger_required(a):
    err = (f"r.addError({_apex_lit(a['ErrorField'])}, {_apex_lit(a['Message'])});" if a["ErrorField"]
           else f"r.addError({_apex_lit(a['Message'])});")
    return f"""// EXPRESS enforcement {a['Id']} ({a['Tab']}). Generated from AUTO_SPEC; do not hand-edit.
// When {a['WhenField']} = '{a['WhenValue']}', {a['RequiredField']} must be non-blank.
trigger {a['Name']} on {a['Object']} ({_events(a['Timing'])}) {{
{_bypass_apex(a)}    for (SObject r : Trigger.new) {{
        if (String.valueOf(r.get({_apex_lit(a['WhenField'])})) == {_apex_lit(a['WhenValue'])}
                && String.isBlank(String.valueOf(r.get({_apex_lit(a['RequiredField'])})))) {{
            {err}
        }}
    }}
}}
"""


def render_trigger_cpu(a):
    return f"""// EXPRESS enforcement {a['Id']} ({a['Tab']}). Generated from AUTO_SPEC; do not hand-edit.
// Deliberate per-record CPU cost of {CPU_MS_PER_RECORD} ms. A 200-record chunk needs about
// {CPU_MS_PER_RECORD * 200:,} ms, over the 10,000 ms synchronous limit. Expected: {a['Message']}
trigger {a['Name']} on {a['Object']} ({_events(a['Timing'])}) {{
{_bypass_apex(a)}    Integer sink = 0;
    for (SObject r : Trigger.new) {{
        Integer stopAt = Limits.getCpuTime() + {CPU_MS_PER_RECORD};
        while (Limits.getCpuTime() < stopAt) {{
            for (Integer i = 0; i < 200; i++) {{ sink += Math.mod(i * 7, 13); }}
        }}
    }}
}}
"""


def render_flow_custom_error(a):
    cond = _bypass_formula(a, a["Condition"], flow=True)
    fld = (f"            <fieldSelection>{a['ErrorField']}</fieldSelection>\n            <isFieldError>true</isFieldError>\n"
           if a["ErrorField"] else "            <isFieldError>false</isFieldError>\n")
    pmv = "".join(f"""    <processMetadataValues>
        <name>{n}</name>
        <value>
            <stringValue>{v}</stringValue>
        </value>
    </processMetadataValues>
""" for n, v in (("BuilderType", "LightningFlowBuilder"), ("CanvasMode", "AUTO_LAYOUT_CANVAS"),
                 ("OriginBuilderType", "LightningFlowBuilder")))
    return f"""{XML}<Flow {NS}>
    <apiVersion>{C.API_VERSION}</apiVersion>
    <customErrors>
        <name>Raise_Error</name>
        <label>Raise Error</label>
        <locationX>50</locationX>
        <locationY>431</locationY>
        <customErrorMessages>
            <errorMessage>{escape(a['Message'])}</errorMessage>
{fld}        </customErrorMessages>
    </customErrors>
    <decisions>
        <name>Should_Block</name>
        <label>Should Block</label>
        <locationX>182</locationX>
        <locationY>323</locationY>
        <defaultConnectorLabel>No</defaultConnectorLabel>
        <rules>
            <name>Block</name>
            <conditionLogic>and</conditionLogic>
            <conditions>
                <leftValueReference>fmlBlock</leftValueReference>
                <operator>EqualTo</operator>
                <rightValue>
                    <booleanValue>true</booleanValue>
                </rightValue>
            </conditions>
            <connector>
                <targetReference>Raise_Error</targetReference>
            </connector>
            <label>Block</label>
        </rules>
    </decisions>
    <description>EXPRESS enforcement {a['Id']} ({escape(a['Tab'])}). Generated from AUTO_SPEC; do not hand-edit.</description>
    <environments>Default</environments>
    <formulas>
        <name>fmlBlock</name>
        <dataType>Boolean</dataType>
        <expression>{escape(cond)}</expression>
    </formulas>
    <interviewLabel>{a['Name']} {{!$Flow.CurrentDateTime}}</interviewLabel>
    <label>{a['Name']}</label>
{pmv}    <processType>AutoLaunchedFlow</processType>
    <start>
        <locationX>56</locationX>
        <locationY>0</locationY>
        <connector>
            <targetReference>Should_Block</targetReference>
        </connector>
        <object>{a['Object']}</object>
        <recordTriggerType>CreateAndUpdate</recordTriggerType>
        <triggerType>RecordBeforeSave</triggerType>
    </start>
    <status>Active</status>
</Flow>
"""


TEMPLATES = {
    "VALIDATION_RULE": ("validationRule", render_validation_rule),
    "TRIGGER_REQUIRED": ("trigger", render_trigger_required),
    "TRIGGER_CPU": ("trigger", render_trigger_cpu),
    "FLOW_CUSTOM_ERROR": ("flow", render_flow_custom_error),
}


def fixture(w1, a, prefer=None):
    """Field values for one test record of a.Object, taken from File 1's first suitable row:
    plain FIELD columns and the record type only, so the fixture never needs a parent."""
    t = w1.tabs.get(a["Object"])
    if not t:
        return None, None
    rows = t.rows
    if prefer:
        f, v = prefer
        if f in t.headers:
            m = [r for r in rows if r[t.col(f)] == v]
            rows = m or rows
    rts = [r for r in rows if C.RT_HEADER not in t.headers or not r[t.col(C.RT_HEADER)]
           or not r[t.col(C.RT_HEADER)].lower().startswith("person")]
    row = (rts or rows)[0]
    vals = {}
    for c in t.columns:
        if c.kind == "FIELD" and row[t.col(c.header)] != "":
            vals[c.field] = row[t.col(c.header)]
    rt = row[t.col(C.RT_HEADER)] if C.RT_HEADER in t.headers else None
    return vals, rt


def enforcement_test(w1, rows):
    methods = []
    for a in rows:
        if a["Kind"] not in ("TRIGGER_REQUIRED", "TRIGGER_CPU"):
            continue
        prefer = (a["WhenField"], a["WhenValue"]) if a["Kind"] == "TRIGGER_REQUIRED" else None
        vals, rt = fixture(w1, a, prefer)
        if vals is None:
            raise C.ContractError([f"[AUTO_SPEC {a['Id']}] no File 1 tab for {a['Object']}; cannot build a test fixture"])
        if a["Kind"] == "TRIGGER_REQUIRED":
            vals[a["WhenField"]] = a["WhenValue"]
            vals.pop(a["RequiredField"], None)
        m = "new Map<String, String>{" + ", ".join(f"{_apex_lit(k)} => {_apex_lit(v)}" for k, v in sorted(vals.items())) + "}"
        rtl = _apex_lit(rt) if rt else "null"
        if a["Kind"] == "TRIGGER_REQUIRED":
            body = f"""        SObject r = make({_apex_lit(a['Object'])}, {m}, {rtl});
        bypass(false);
        Database.SaveResult sr = Database.insert(r, dml());
        System.assert(!sr.isSuccess(), '{a['Id']} must block');
        System.assert(sr.getErrors()[0].getMessage().contains({_apex_lit(a['Message'])}), sr.getErrors()[0].getMessage());
        bypass(true);
        System.assert(Database.insert(make({_apex_lit(a['Object'])}, {m}, {rtl}), dml()).isSuccess(), 'bypass must allow');"""
        else:
            body = f"""        bypass(false);
        System.assert(Database.insert(make({_apex_lit(a['Object'])}, {m}, {rtl}), dml()).isSuccess(), 'one record stays under the limit');
        bypass(true);
        System.assert(Database.insert(make({_apex_lit(a['Object'])}, {m}, {rtl}), dml()).isSuccess());"""
        methods.append(f"    @IsTest static void {a['Name'].lower()}_{a['Id'].lower()}() {{\n{body}\n    }}")
    return f"""@IsTest
private class ExpressEnforcementTest {{
    // Generated from AUTO_SPEC by build_setup_meta.py. Fixtures are File 1 rows (plain fields only).
    static void bypass(Boolean enabled) {{
        Migration_Settings__c ms = Migration_Settings__c.getOrgDefaults();
        ms.Bypass_Automation__c = enabled;
        upsert ms;
    }}

    static Database.DMLOptions dml() {{
        Database.DMLOptions o = new Database.DMLOptions();
        o.duplicateRuleHeader.allowSave = true;
        o.optAllOrNone = false;
        return o;
    }}

    static SObject make(String obj, Map<String, String> vals, String rt) {{
        Schema.SObjectType t = Schema.getGlobalDescribe().get(obj.toLowerCase());
        Map<String, Schema.SObjectField> fm = t.getDescribe().fields.getMap();
        SObject r = t.newSObject();
        if (rt != null) {{ r.put('RecordTypeId', t.getDescribe().getRecordTypeInfosByDeveloperName().get(rt).getRecordTypeId()); }}
        for (String f : vals.keySet()) {{
            r.put(f, ExpressSeedBatch.typed(fm.get(f.toLowerCase()).getDescribe().getType(), vals.get(f)));
        }}
        return r;
    }}

{chr(10).join(methods) if methods else '    @IsTest static void noApexEnforcement() { System.assert(true); }'}
}}
"""


def render_enforcement(w1, auto, out, written):
    rows = C.v1_rows(auto)
    rendered = []
    for a in rows:
        if a["Kind"] not in TEMPLATES:
            raise C.ContractError([f"[AUTO_SPEC {a['Id']}] Kind {a['Kind']} has no template; refusing to ship without it"])
        kind, fn = TEMPLATES[a["Kind"]]
        if kind == "validationRule":
            rel = f"{FA}/objects/{a['Object']}/validationRules/{a['Name']}.validationRule-meta.xml"
        elif kind == "trigger":
            rel = f"{FA}/triggers/{a['Name']}.trigger"
            write(out, rel + "-meta.xml",
                  f"{XML}<ApexTrigger {NS}>\n    <apiVersion>{C.API_VERSION}</apiVersion>\n    <status>Active</status>\n</ApexTrigger>\n",
                  written)
        else:
            rel = f"{FA}/flows/{a['Name']}.flow-meta.xml"
        write(out, rel, fn(a), written)
        rendered.append(a)
    write(out, f"{FA}/classes/ExpressEnforcementTest.cls", enforcement_test(w1, rows), written)
    write(out, f"{FA}/classes/ExpressEnforcementTest.cls-meta.xml",
          f"{XML}<ApexClass {NS}>\n    <apiVersion>{C.API_VERSION}</apiVersion>\n    <status>Active</status>\n</ApexClass>\n", written)
    skipped = [a for a in auto if a not in rows]
    return rendered, skipped


# ---------------------------------------------------------------- README (spec 9)
def readme(client, plan, rendered, skipped):
    req = plan["requires"]
    code = client["code"]
    pre = []
    if req["person_record_types"]:
        pre.append("Person Accounts enabled (record types " + ", ".join(f"`{x}`" for x in req["person_record_types"]) + ")")
    if req["state_country_fields"]:
        pre.append("State and Country/Territory Picklists enabled")
    if req["contacts_to_multiple_accounts"]:
        pre.append("Contacts to Multiple Accounts enabled")
    if req["audit_fields"]:
        pre.append("Set Audit Fields upon Record Creation enabled (Setup > User Interface). Audit columns: "
                   + ", ".join(f"`{o}.{f}`" for o, fs in sorted(req["audit_fields"].items()) for f in fs))
    for o, rts in sorted(req["record_types"].items()):
        pre.append(f"`{o}` record types active and available: " + ", ".join(f"`{r}`" for r in rts))
    census = "\n".join(f"| {r['object']}{' / ' + r['record_type'] if r.get('record_type') else ''} | "
                       f"{r['expected']:,} | {r.get('filter') or 'n/a'} |" for r in plan["census"])
    steps = "\n".join(f"| {s['n']} | {s['object']} | {s['op']} | {s['rows']:,} | `{', '.join(s['resources'])}` |"
                      for s in plan["steps"])
    enf = "\n".join(f"| {a['Id']} | {a['Kind']} | `{a['Object']}` | `{a['Name']}` | {a['Message']} |" for a in rendered)
    later = ", ".join(f"{a['Id']} ({a['Kind']})" for a in skipped) or "none"
    return f"""# {client['display_name']}: EXPRESS setup ({code})

Generated by `build_setup_meta.py` from the client inputs. Do not hand-edit; regenerate.
Plan from File 1 content md5 `{plan['file1_content_md5']}`, contract v{plan['contract_version']}, API {plan['api_version']}.

## 1. Before you deploy

Work in this folder only. Every command below runs from `clients/{code}`:

```
cd clients/{code}
```

The repo root holds a different client. A deploy from the root does not reach this one.

These org settings are prerequisites. They are org settings, not metadata, so this repo cannot deploy them:

{chr(10).join(f'{i}. {p}' for i, p in enumerate(pre, start=1)) if pre else 'None.'}

## 2. Deploy and assign

```
sf project deploy start --test-level RunLocalTests
sf org assign permset --name {PERMSET}
```

## 3. Check, census, seed, census

1. Run `scripts/check-setup.apex` as Anonymous Apex. It prints `SETUP OK`, or throws `SETUP INCOMPLETE` / `ALREADY SEEDED` naming the first gap. Fix that gap and run it again.
2. Run `scripts/census.apex` with `MODE = 'BEFORE'`. Copy the line it prints.
3. Run `scripts/run-seed.apex`. It runs {len(plan['steps'])} Batch jobs, one per step, chained.
4. Wait for the email, or query `Seed_Step_Result__c`. The run passes only on `SEED PASS`. A Completed job is not proof of success.
5. Run `scripts/census.apex` with `MODE = 'AFTER'` and the BEFORE line pasted in. Every row must say PASS.

Every seeded record is owned by the user who ran the seed. The original owner username is kept in the owner lineage field on each object.

## 4. Steps

| Step | Object | Operation | Rows | Resource |
| :-- | :-- | :-- | --: | :-- |
{steps}

## 5. Expected census deltas

| Object | Expected delta | Platform filter |
| :-- | --: | :-- |
{census}

## 6. Enforcement layer

Active for learner loads. The seed turns it off while it loads and back on when it ends (`Migration_Settings__c.Bypass_Automation__c`).

| Id | Kind | Object | Component | Expected error |
| :-- | :-- | :-- | :-- | :-- |
{enf}

Not in this release: {later}.

If a run stops before its last step (Setup > Apex Jobs shows a failed or aborted ExpressSeedBatch and no verdict arrives), run `scripts/reset-bypass.apex` so the enforcement layer is active again.

## 7. Reset

Run `scripts/reset-data.apex` with `MODE = 'REPORT'` first. Set `MODE = 'DELETE'` and rerun until every count is 0. Then verify with `scripts/census.apex`.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for a in ("--file1", "--file3", "--describe", "--client", "--out"):
        ap.add_argument(a, required=True)
    args = ap.parse_args(argv)
    with open(args.client, encoding="utf-8") as fh:
        client = json.load(fh)
    d = C.load_describe(args.describe)
    out = os.path.abspath(args.out)
    written = []
    try:
        w1 = C.load_file1(args.file1, d)
        auto = C.load_auto_spec(args.file3, w1, d)
        C.check_seed_against_v1(w1, auto)
        plan = C.build_plan(w1, d, batch_size=int(client.get("batch_size", C.DEFAULT_BATCH_SIZE)))
        C.resource_texts(plan)       # fills step resource names for the README
        if not re.match(r"^[A-Za-z][A-Za-z0-9]*$", client["code"]):
            raise C.ContractError([f"[client.json] code {client['code']!r} must be alphanumeric"])
        write(out, "sfdx-project.json", json.dumps({
            "packageDirectories": [{"path": "force-app", "default": True}],
            "name": f"EXPRESS_Setup_{client['code']}",
            "namespace": "",
            "sfdcLoginUrl": "https://login.salesforce.com",
            "sourceApiVersion": C.API_VERSION,
        }, indent=2) + "\n", written)
        write(out, ".forceignore", "**/.DS_Store\n**/jsconfig.json\n**/.eslintrc.json\n", written)
        # custom fields
        homes = {}
        for r in w1.repo_fields:
            if not r["Field"].endswith("__c"):
                continue
            key = (field_home(r["Object"]), r["Field"])
            if key in homes and homes[key] != r["Type"]:
                raise C.ContractError([f"[_REPO_FIELDS] {r['Field']} declared twice on Activity with different types"])
            homes[key] = r["Type"]
            write(out, f"{FA}/objects/{key[0]}/fields/{r['Field']}.field-meta.xml", field_xml(r), written)
        # standard value sets: union of org values and added values (whole-set replace on deploy)
        svs = {}
        for r in w1.repo_fields:
            if r["Field"].endswith("__c"):
                continue
            name = C.STANDARD_VALUE_SETS[(r["Object"], r["Field"])]
            org = d.picklist(r["Object"], r["Field"]) or []
            add = [v for v in r["Values"].split(";") if v]
            merged = svs.get(name, list(org))
            merged += [v for v in add if v not in merged]
            svs[name] = merged
        for name, vals in sorted(svs.items()):
            write(out, f"{FA}/standardValueSets/{name}.standardValueSet-meta.xml", standard_value_set(name, vals), written)
        fixed_metadata(out, written)
        write(out, f"{FA}/permissionsets/{PERMSET}.permissionset-meta.xml", permission_set(w1, plan), written)
        rendered, skipped = render_enforcement(w1, auto, out, written)
        write(out, "README.md", readme(client, plan, rendered, skipped), written)
    except C.ContractError as e:
        print("BUILD FAILED", file=sys.stderr)
        for x in e.errors:
            print("  " + x, file=sys.stderr)
        return 2
    print(f"METADATA OK: {len(written)} files under {out}")
    print(f"  custom fields {len(homes)}, standard value sets {len(svs)} {sorted(svs)}")
    print(f"  enforcement rendered {len(rendered)} ({', '.join(a['Id'] for a in rendered)}); "
          f"not this release {len(skipped)} ({', '.join(a['Id'] for a in skipped) or 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
