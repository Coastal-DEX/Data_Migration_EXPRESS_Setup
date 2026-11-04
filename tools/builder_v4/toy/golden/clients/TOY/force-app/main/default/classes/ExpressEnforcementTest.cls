@IsTest
private class ExpressEnforcementTest {
    // Generated from AUTO_SPEC by build_setup_meta.py. Fixtures are File 1 rows (plain fields only).
    static void bypass(Boolean enabled) {
        Migration_Settings__c ms = Migration_Settings__c.getOrgDefaults();
        ms.Bypass_Automation__c = enabled;
        upsert ms;
    }

    static Database.DMLOptions dml() {
        Database.DMLOptions o = new Database.DMLOptions();
        o.duplicateRuleHeader.allowSave = true;
        o.optAllOrNone = false;
        return o;
    }

    static SObject make(String obj, Map<String, String> vals, String rt) {
        Schema.SObjectType t = Schema.getGlobalDescribe().get(obj.toLowerCase());
        Map<String, Schema.SObjectField> fm = t.getDescribe().fields.getMap();
        SObject r = t.newSObject();
        if (rt != null) { r.put('RecordTypeId', t.getDescribe().getRecordTypeInfosByDeveloperName().get(rt).getRecordTypeId()); }
        for (String f : vals.keySet()) {
            r.put(f, ExpressSeedBatch.typed(fm.get(f.toLowerCase()).getDescribe().getType(), vals.get(f)));
        }
        return r;
    }

    @IsTest static void toyassetneedsinstalldate_t2() {
        SObject r = make('Asset', new Map<String, String>{'Name' => 'Pump 1', 'Price' => '1200.5', 'SerialNumber' => 'SN-100', 'Status' => 'Installed'}, null);
        bypass(false);
        Database.SaveResult sr = Database.insert(r, dml());
        System.assert(!sr.isSuccess(), 'T2 must block');
        System.assert(sr.getErrors()[0].getMessage().contains('Installed assets need an install date'), sr.getErrors()[0].getMessage());
        bypass(true);
        System.assert(Database.insert(make('Asset', new Map<String, String>{'Name' => 'Pump 1', 'Price' => '1200.5', 'SerialNumber' => 'SN-100', 'Status' => 'Installed'}, null), dml()).isSuccess(), 'bypass must allow');
    }
}
