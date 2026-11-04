"""Builds the toy third client's inputs (spec v1.0.4 section 10.2): a hand-built File 1,
File 3 and describe fixture that share no object, field or value with any real client.

Shape under test: three objects (Account, Asset, Case) plus a polymorphic Task; one
self-lookup (Account.Parent); one polymorphic lookup (Task.What over all three);
an object with two key rows by record type; a value with a comma and a quote; a
standard-picklist extension; LEARNER, LOADER and SEED repo fields; v1 and v1.1 AUTO_SPEC rows.

Usage: python3 make_toy_inputs.py --out <dir>
"""
import argparse
import json
import os

import openpyxl

DESCRIBE = {
    "_meta": {"org": "toy-fixture", "api": "v66.0", "rule": "hand-built fixture"},
    "_shared": {"COUNTRY_CODES": ["US", "CA"], "STATE_CODES": ["WA", "OR", "BC"]},
    "Account": {"label": "Account", "createable": True,
                "recordTypes": [{"dn": "Org_Unit", "name": "Org Unit", "person": False, "avail": True, "dflt": True},
                                {"dn": "Branch", "name": "Branch", "person": False, "avail": True, "dflt": False}],
                "fields": [{"n": "Id", "t": "id"}, {"n": "Name", "t": "string", "len": 255},
                           {"n": "AccountNumber", "t": "string", "len": 40},
                           {"n": "ParentId", "t": "reference", "ref": "Account"},
                           {"n": "RecordTypeId", "t": "reference", "ref": "RecordType"},
                           {"n": "OwnerId", "t": "reference", "ref": "User"},
                           {"n": "BillingCountryCode", "t": "picklist", "pl": "@COUNTRY_CODES", "restr": True},
                           {"n": "Industry", "t": "picklist", "pl": ["Energy", "Retail"]},
                           {"n": "Description", "t": "textarea", "len": 32000}]},
    "Asset": {"label": "Asset", "createable": True, "recordTypes": [],
              "fields": [{"n": "Id", "t": "id"}, {"n": "Name", "t": "string", "len": 255, "req": True},
                         {"n": "SerialNumber", "t": "string", "len": 80},
                         {"n": "AccountId", "t": "reference", "ref": "Account"},
                         {"n": "OwnerId", "t": "reference", "ref": "User"},
                         {"n": "InstallDate", "t": "date"}, {"n": "Price", "t": "currency"},
                         {"n": "Status", "t": "picklist", "pl": ["Installed", "Obsolete"]}]},
    "Case": {"label": "Case", "createable": True, "recordTypes": [],
             "fields": [{"n": "Id", "t": "id"}, {"n": "Subject", "t": "string", "len": 255},
                        {"n": "AccountId", "t": "reference", "ref": "Account"},
                        {"n": "AssetId", "t": "reference", "ref": "Asset"},
                        {"n": "Status", "t": "picklist", "pl": ["New", "Closed"]},
                        {"n": "Reason", "t": "picklist", "pl": ["Other"]},
                        {"n": "OwnerId", "t": "reference", "ref": ["Group", "User"]}]},
    "Task": {"label": "Task", "createable": True, "recordTypes": [],
             "fields": [{"n": "Id", "t": "id"}, {"n": "Subject", "t": "combobox", "len": 255, "pl": ["Call"]},
                        {"n": "WhatId", "t": "reference", "ref": ["Account", "Asset", "Case", "Opportunity"]},
                        {"n": "ActivityDate", "t": "date"},
                        {"n": "Status", "t": "picklist", "pl": ["Not Started", "Completed"]},
                        {"n": "OwnerId", "t": "reference", "ref": ["Group", "User"]}]},
}

ACCOUNT = [
    ["RecordType.DeveloperName", "Name", "AccountNumber", "Parent.Name", "Owner.Username", "BillingCountryCode", "Industry", "Tier__c", "Description"],
    ["Org_Unit", "North Works", "", "", "a.one@toy.example", "US", "Energy", "Gold", 'Has a comma, and a "quote"'],
    ["Org_Unit", "South Works", "", "North Works", "a.two@toy.example", "CA", "Retail", "Silver", ""],
    ["Org_Unit", "East Works", "", "North Works", "a.one@toy.example", "US", "", "Gold", ""],
    ["Branch", "", "BR-001", "", "a.two@toy.example", "US", "Energy", "Bronze", ""],
    ["Branch", "", "BR-002", "", "a.one@toy.example", "CA", "Retail", "Silver", ""],
]
ASSET = [
    ["Name", "SerialNumber", "Account.Name", "Account.AccountNumber", "InstallDate", "Price", "Status", "Owner.Username"],
    ["Pump 1", "SN-100", "North Works", "", "2024-03-01", 1200.5, "Installed", "a.one@toy.example"],
    ["Pump 2", "SN-101", "", "BR-001", "2024-04-15", 990, "Installed", "a.two@toy.example"],
    ["Valve 1", "SN-200", "South Works", "", "2023-12-31", 45, "Obsolete", "a.one@toy.example"],
]
CASE = [
    ["Subject", "Account.Name", "Asset.SerialNumber", "Status", "Reason", "Owner.Username", "CreatedDate"],
    ["Pump 1 noisy", "North Works", "SN-100", "Closed", "Other", "a.one@toy.example", "2024-05-01T10:00:00.000Z"],
    ["Valve leak", "South Works", "SN-200", "New", "", "a.two@toy.example", "2024-06-02T11:30:00.000Z"],
]
TASK = [
    ["Subject", "What.Type", "What.Key", "ActivityDate", "Status", "Owner.Username"],
    ["Call", "Account", "North Works", "2024-07-01", "Completed", "a.one@toy.example"],
    ["Follow up", "Account", "BR-002", "2024-07-02", "Not Started", "a.two@toy.example"],
    ["Inspect", "Asset", "SN-101", "2024-07-03", "Not Started", "a.one@toy.example"],
    ["Close out", "Case", "Pump 1 noisy", "2024-07-04", "Completed", "a.two@toy.example"],
    ["Note", "", "", "2024-07-05", "Completed", "a.one@toy.example"],
]
KEYS = [["Object", "RecordType", "KeyField", "Unique"],
        ["Account", "Org_Unit", "Name", "Y"],
        ["Account", "Branch", "AccountNumber", "Y"],
        ["Asset", "", "SerialNumber", "Y"],
        ["Case", "", "Subject", "Y"]]
RF = [["Object", "Field", "Type", "Length", "Precision", "Scale", "Values", "Restricted", "ExternalId", "Unique", "Populated", "Note"],
      ["Account", "Tier__c", "Picklist", "", "", "", "Gold;Silver;Bronze", "Y", "N", "N", "SEED", "toy client field"],
      ["Account", "Old_System_Key__c", "Text", "30", "", "", "", "N", "Y", "N", "LEARNER", "lineage"],
      ["Account", "Seed_Owner_Username__c", "Text", "80", "", "", "", "N", "N", "N", "LOADER", "D3a"],
      ["Asset", "Seed_Owner_Username__c", "Text", "80", "", "", "", "N", "N", "N", "LOADER", "D3a"],
      ["Case", "Seed_Owner_Username__c", "Text", "80", "", "", "", "N", "N", "N", "LOADER", "D3a"],
      ["Task", "Seed_Owner_Username__c", "Text", "80", "", "", "", "N", "N", "N", "LOADER", "D3a; on Activity"],
      ["Case", "Reason", "Picklist", "", "", "", "Wear", "N", "N", "N", "SEED", "standard picklist: add only"]]
AUTO = [["Id", "Tab", "Release", "Object", "Kind", "Name", "Timing", "Condition", "WhenField", "WhenValue",
         "RequiredField", "ErrorField", "Message", "Bypassable"],
        ["T1", "AUTO_T1_Case_Rule", "v1", "Case", "VALIDATION_RULE", "Toy_Closed_Needs_Reason", "",
         'AND(ISPICKVAL(Status, "Closed"), ISBLANK(TEXT(Reason)))', "", "", "", "Reason", "Closed needs a reason", "Y"],
        ["T2", "AUTO_T2_Asset_Trigger", "v1", "Asset", "TRIGGER_REQUIRED", "ToyAssetNeedsInstallDate", "before insert", "",
         "Status", "Installed", "InstallDate", "InstallDate", "Installed assets need an install date", "Y"],
        ["T3", "AUTO_T3_Later", "v1.1", "Account", "DUPLICATE_RULE", "Toy_Dup", "", "", "Name", "", "", "Name", "DUPLICATES_DETECTED", "N"]]


def sheet(wb, name, rows):
    ws = wb.create_sheet(name)
    for r in rows:
        ws.append(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    wb = openpyxl.Workbook()
    wb.active.title = "README"
    wb.active.append(["Toy client File 1 (hand-built test fixture)"])
    for n, rows in (("Account", ACCOUNT), ("Asset", ASSET), ("Case", CASE), ("Task", TASK),
                    ("_KEYS", KEYS), ("_REPO_FIELDS", RF)):
        sheet(wb, n, rows)
    wb.save(os.path.join(a.out, "file1.xlsx"))
    wb3 = openpyxl.Workbook()
    wb3.active.title = "README"
    sheet(wb3, "AUTO_T1_Case_Rule", [["Subject", "Status"], ["x", "Closed"]])
    sheet(wb3, "AUTO_T2_Asset_Trigger", [["Name", "Status"], ["y", "Installed"]])
    sheet(wb3, "AUTO_T3_Later", [["Name"], ["z"]])
    sheet(wb3, "AUTO_SPEC", AUTO)
    wb3.save(os.path.join(a.out, "file3.xlsx"))
    with open(os.path.join(a.out, "describe.json"), "w") as fh:
        json.dump(DESCRIBE, fh, indent=1, sort_keys=True)
    with open(os.path.join(a.out, "client.json"), "w") as fh:
        json.dump({"code": "TOY", "display_name": "Toy Third Client (test fixture)", "seed": 1,
                   "target_platform": "any org", "source_database": "n/a", "batch_size": 200}, fh, indent=1)
    print("toy inputs written to", a.out)


if __name__ == "__main__":
    main()
