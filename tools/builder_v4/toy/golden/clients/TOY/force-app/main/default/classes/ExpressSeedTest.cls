@IsTest
private class ExpressSeedTest {
    static Map<String, Object> testPlan() {
        String p = '{"keys":[{"object":"Account","record_type":null,"key_field":"Name"},'
            + '{"object":"Contact","record_type":null,"key_field":"Email"}],'
            + '"steps":['
            + '{"n":1,"name":"S01_Account_insert","object":"Account","op":"insert","rows":3,"batch_size":200,"resources":["T1"],'
            + ' "columns":[{"header":"Name","kind":"FIELD","field":"Name"},{"header":"Description","kind":"FIELD","field":"Description"},'
            + '  {"header":"NumberOfEmployees","kind":"FIELD","field":"NumberOfEmployees"},{"header":"Owner.Username","kind":"OWNER","field":"OwnerId"}]},'
            + '{"n":2,"name":"S02_Account_update","object":"Account","op":"update","rows":1,"batch_size":200,"resources":["T2"],"key_headers":["Name"],'
            + ' "columns":[{"header":"Name","kind":"FIELD","field":"Name"},{"header":"Parent.Name","kind":"LOOKUP","field":"ParentId","rel":"Parent","key_field":"Name","target":"Account","self_ref":true}]},'
            + '{"n":3,"name":"S03_Contact_insert","object":"Contact","op":"insert","rows":3,"batch_size":200,"resources":["T3"],'
            + ' "columns":[{"header":"LastName","kind":"FIELD","field":"LastName"},{"header":"Email","kind":"FIELD","field":"Email"},'
            + '  {"header":"Birthdate","kind":"FIELD","field":"Birthdate"},{"header":"Account.Name","kind":"LOOKUP","field":"AccountId","rel":"Account","key_field":"Name","target":"Account"}]}'
            + '],'
            + '"requires":{"objects":["Account","Contact"],"record_types":{},"person_record_types":[],"state_country_fields":[],'
            + ' "contacts_to_multiple_accounts":false,"audit_fields":{},"repo_fields":[],'
            + ' "already_seeded":{"object":"Account","key_field":"Name","record_type":null,"keys":["Zq Test, \\"One\\""]}}}';
        return (Map<String, Object>) JSON.deserializeUntyped(p);
    }

    static void setup() {
        ExpressSeed.planOverride = testPlan();
        ExpressSeed.resourceOverride = new Map<String, String>{
            'T1' => 'Name,Description,NumberOfEmployees,Owner.Username\n'
                  + '"Zq Test, ""One""",plain,5,someone@example.invalid\n'
                  + 'Zq Two,"has, comma",,\n'
                  + 'Zq Three,x,7,',
            'T2' => 'Name,Parent.Name\nZq Two,"Zq Test, ""One"""',
            'T3' => 'LastName,Email,Birthdate,Account.Name\n'
                  + 'Alpha,alpha@example.invalid,1990-01-02,Zq Two\n'
                  + 'Beta,beta@example.invalid,,No Such Account\n'
                  + 'Gamma,gamma@example.invalid,,'
        };
        // bypass ON for fixture data, so a client's enforcement layer cannot block these tests
        insert new Migration_Settings__c(SetupOwnerId = UserInfo.getOrganizationId(), Bypass_Automation__c = true);
    }

    @IsTest static void csvParserHandlesQuotesAndCommas() {
        List<String> f = ExpressCsv.parseLine('"a, b","say ""hi""",,c');
        System.assertEquals(4, f.size());
        System.assertEquals('a, b', f[0]);
        System.assertEquals('say "hi"', f[1]);
        System.assertEquals('', f[2]);
        System.assertEquals('c', f[3]);
        System.assertEquals(3, ExpressCsv.lines('h\r\na\n\nb\n').size());
        List<String> many = new List<String>();
        for (Integer i = 0; i < 20000; i++) { many.add('x' + i + ',"y, z"'); }
        List<String> got = ExpressCsv.lines(String.join(many, '\n'));
        System.assertEquals(20000, got.size(), 'large bodies split without regex');
        System.assertEquals('x19999,"y, z"', got[19999]);
        System.assertEquals(0, ExpressCsv.lines(null).size());
    }

    @IsTest static void fullRunPassesAndCounts() {
        setup();
        ExpressSeed.checkSetup();
        Test.startTest();
        ExpressSeed.run();
        Test.stopTest();
        System.assertEquals(true, Migration_Settings__c.getOrgDefaults().Bypass_Automation__c, 'bypass held between steps');
        ExpressSeedBatch b2 = new ExpressSeedBatch(runIdOf(), 2);
        b2.execute(null, (List<String>) b2.start(null));
        b2.finish(null);
        ExpressSeedBatch b3 = new ExpressSeedBatch(runIdOf(), 3);
        b3.execute(null, (List<String>) b3.start(null));
        System.assertEquals(2, b3.succeeded);
        System.assertEquals(1, b3.missingParent);
        b3.finish(null);
        Account child = [SELECT ParentId, OwnerId FROM Account WHERE Name = 'Zq Two'];
        System.assertNotEquals(null, child.ParentId);
        System.assertEquals(UserInfo.getUserId(), child.OwnerId);
        System.assertEquals(false, Migration_Settings__c.getOrgDefaults().Bypass_Automation__c, 'bypass cleared');
        List<Seed_Step_Result__c> rs = [SELECT Step__c, Step_Name__c, Expected__c, Succeeded__c, Errors__c, Missing_Parent__c,
            Ambiguous_Parent__c, Failed_Batches__c, Owners_Remapped__c, Sample_Errors__c FROM Seed_Step_Result__c ORDER BY Step__c];
        System.assertEquals(3, rs.size());
        System.assertEquals(3, rs[0].Succeeded__c);
        System.assertEquals(1, rs[0].Owners_Remapped__c);
        System.assert(ExpressSeed.verdict(rs, 3).startsWith('SEED FAIL'), 'a missing parent must fail the run');
        Boolean threw = false;
        try { ExpressSeed.checkSetup(); } catch (ExpressSeed.SetupException e) {
            threw = e.getMessage().startsWith('ALREADY SEEDED');
        }
        System.assert(threw, 'second run must be refused');
    }

    @IsTest static void verdictPassAndAmbiguity() {
        setup();
        Seed_Step_Result__c ok = new Seed_Step_Result__c(Name = 'x', Step_Name__c = 'x', Expected__c = 2, Succeeded__c = 2,
            Errors__c = 0, Missing_Parent__c = 0, Ambiguous_Parent__c = 0, Failed_Batches__c = 0);
        System.assert(ExpressSeed.verdict(new List<Seed_Step_Result__c>{ ok }, 1).startsWith('SEED PASS'));
        System.assert(ExpressSeed.verdict(new List<Seed_Step_Result__c>{ ok }, 2).startsWith('SEED FAIL'));
        Database.DMLOptions dml = new Database.DMLOptions();
        dml.duplicateRuleHeader.allowSave = true;
        dml.optAllOrNone = true;
        Database.insert(new List<Account>{ new Account(Name = 'Zq Dup'), new Account(Name = 'Zq Dup') }, dml);
        Map<String, List<Id>> m = ExpressSeedBatch.resolveKeys('Account', 'Name', null, new Set<String>{ 'Zq Dup' });
        System.assertEquals(2, m.get('Zq Dup').size());
        System.assertEquals(Date.newInstance(2024, 1, 2), ExpressSeedBatch.typed(Schema.DisplayType.DATE, '2024-01-02'));
        System.assertEquals(true, ExpressSeedBatch.typed(Schema.DisplayType.BOOLEAN, 'TRUE'));
        System.assertEquals(3, ExpressSeedBatch.typed(Schema.DisplayType.INTEGER, '3'));
        System.assertEquals(Decimal.valueOf('1.5'), ExpressSeedBatch.typed(Schema.DisplayType.CURRENCY, '1.5'));
        System.assertNotEquals(null, ExpressSeedBatch.typed(Schema.DisplayType.DATETIME, '2024-12-03T18:06:00.000Z'));
    }

    @IsTest static void startFailureEndsRunAndClearsBypass() {
        setup();
        ((Map<String, Object>) ((List<Object>) ExpressSeed.planOverride.get('steps'))[0]).put('resources', new List<Object>{ 'NO_SUCH_RESOURCE_ZQ' });
        ExpressSeed.setBypass(true);
        ExpressSeedBatch b = new ExpressSeedBatch('zq-run', 1);
        List<String> rows = (List<String>) b.start(null);
        System.assertEquals(0, rows.size());
        System.assertNotEquals(null, b.startError);
        b.finish(null);
        System.assertEquals(false, Migration_Settings__c.getOrgDefaults().Bypass_Automation__c, 'bypass cleared after a start failure');
        Seed_Step_Result__c r = [SELECT Sample_Errors__c FROM Seed_Step_Result__c WHERE Run_Id__c = 'zq-run'];
        System.assert(r.Sample_Errors__c.contains('start failed'), r.Sample_Errors__c);
    }

    @IsTest static void setupProblemsAreNamed() {
        setup();
        Map<String, Object> req = (Map<String, Object>) ExpressSeed.planOverride.get('requires');
        req.put('objects', new List<Object>{ 'Account', 'No_Such_Object_Zq__c' });
        req.put('repo_fields', new List<Object>{ 'Account.No_Such_Field_Zq__c' });
        req.put('state_country_fields', new List<Object>{ 'Account.No_Such_CountryCode' });
        req.put('record_types', new Map<String, Object>{ 'Account' => new List<Object>{ 'No_Such_Rt_Zq' } });
        req.put('audit_fields', new Map<String, Object>{ 'Account' => new List<Object>{ 'No_Such_Date_Zq' } });
        List<String> p = ExpressSeed.setupProblems();
        System.assert(p.size() >= 5, String.join(p, '\n'));
        for (String s : p) { System.assert(s.startsWith('SETUP INCOMPLETE:'), s); }
        Boolean threw = false;
        try { ExpressSeed.checkSetup(); } catch (ExpressSeed.SetupException e) { threw = true; }
        System.assert(threw);
    }

    static String runIdOf() {
        return [SELECT Run_Id__c FROM Seed_Step_Result__c ORDER BY CreatedDate DESC LIMIT 1].Run_Id__c;
    }
}
