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

    @IsTest static void expressaccountcpuburn_a01() {
        bypass(false);
        System.assert(Database.insert(make('Account', new Map<String, String>{'AML_Review_Date__c' => '2026-05-23', 'AccountSource' => 'Trade Show', 'AnnualRevenue' => '1360000', 'BillingCity' => 'Portland', 'BillingCountryCode' => 'US', 'BillingPostalCode' => '04191', 'BillingStateCode' => 'ME', 'BillingStreet' => '2325 Magnolia Way', 'Industry' => 'Consulting', 'KYC_Status__c' => 'Verified', 'Name' => 'Tradewind Consulting Co.', 'NumberOfEmployees' => '25', 'Phone' => '(504) 555-3746', 'Risk_Weighted_Assets__c' => '100776.55', 'Segment__c' => 'SME', 'SourceSystemIdentifier' => 'C61700', 'Tax_ID__c' => '27-5048972', 'Type' => 'Customer', 'Website' => 'https://www.tradewindconsulting.example'}, 'Business_Account'), dml()).isSuccess(), 'one record stays under the limit');
        bypass(true);
        System.assert(Database.insert(make('Account', new Map<String, String>{'AML_Review_Date__c' => '2026-05-23', 'AccountSource' => 'Trade Show', 'AnnualRevenue' => '1360000', 'BillingCity' => 'Portland', 'BillingCountryCode' => 'US', 'BillingPostalCode' => '04191', 'BillingStateCode' => 'ME', 'BillingStreet' => '2325 Magnolia Way', 'Industry' => 'Consulting', 'KYC_Status__c' => 'Verified', 'Name' => 'Tradewind Consulting Co.', 'NumberOfEmployees' => '25', 'Phone' => '(504) 555-3746', 'Risk_Weighted_Assets__c' => '100776.55', 'Segment__c' => 'SME', 'SourceSystemIdentifier' => 'C61700', 'Tax_ID__c' => '27-5048972', 'Type' => 'Customer', 'Website' => 'https://www.tradewindconsulting.example'}, 'Business_Account'), dml()).isSuccess());
    }
    @IsTest static void expressaccountrequiretaxid_a05() {
        SObject r = make('Account', new Map<String, String>{'AML_Review_Date__c' => '2025-01-23', 'AccountSource' => 'Web', 'AnnualRevenue' => '130687000', 'BillingCity' => 'Portland', 'BillingCountryCode' => 'US', 'BillingPostalCode' => '04131', 'BillingStateCode' => 'ME', 'BillingStreet' => '6841 Palmetto Way', 'Industry' => 'Transportation', 'KYC_Status__c' => 'Verified', 'Name' => 'Lighthouse Southern Freight Inc.', 'NumberOfEmployees' => '2206', 'Phone' => '(617) 555-2999', 'Risk_Weighted_Assets__c' => '73601.11', 'Segment__c' => 'Corporate', 'SourceSystemIdentifier' => 'C53111', 'Type' => 'Customer'}, 'Business_Account');
        bypass(false);
        Database.SaveResult sr = Database.insert(r, dml());
        System.assert(!sr.isSuccess(), 'A05 must block');
        System.assert(sr.getErrors()[0].getMessage().contains('Tax ID is required for Corporate segment'), sr.getErrors()[0].getMessage());
        bypass(true);
        System.assert(Database.insert(make('Account', new Map<String, String>{'AML_Review_Date__c' => '2025-01-23', 'AccountSource' => 'Web', 'AnnualRevenue' => '130687000', 'BillingCity' => 'Portland', 'BillingCountryCode' => 'US', 'BillingPostalCode' => '04131', 'BillingStateCode' => 'ME', 'BillingStreet' => '6841 Palmetto Way', 'Industry' => 'Transportation', 'KYC_Status__c' => 'Verified', 'Name' => 'Lighthouse Southern Freight Inc.', 'NumberOfEmployees' => '2206', 'Phone' => '(617) 555-2999', 'Risk_Weighted_Assets__c' => '73601.11', 'Segment__c' => 'Corporate', 'SourceSystemIdentifier' => 'C53111', 'Type' => 'Customer'}, 'Business_Account'), dml()).isSuccess(), 'bypass must allow');
    }
}
