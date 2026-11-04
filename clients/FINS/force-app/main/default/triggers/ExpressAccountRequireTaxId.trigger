// EXPRESS enforcement A05 (AUTO05_Trigger_Required_TaxID). Generated from AUTO_SPEC; do not hand-edit.
// When Segment__c = 'Corporate', Tax_ID__c must be non-blank.
trigger ExpressAccountRequireTaxId on Account (before insert) {
    Migration_Settings__c ms = Migration_Settings__c.getOrgDefaults();
    if (ms != null && ms.Bypass_Automation__c == true) { return; }
    for (SObject r : Trigger.new) {
        if (String.valueOf(r.get('Segment__c')) == 'Corporate'
                && String.isBlank(String.valueOf(r.get('Tax_ID__c')))) {
            r.addError('Tax_ID__c', 'Tax ID is required for Corporate segment');
        }
    }
}
