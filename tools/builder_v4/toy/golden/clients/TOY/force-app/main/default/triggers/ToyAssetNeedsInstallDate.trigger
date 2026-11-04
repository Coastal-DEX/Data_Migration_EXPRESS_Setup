// EXPRESS enforcement T2 (AUTO_T2_Asset_Trigger). Generated from AUTO_SPEC; do not hand-edit.
// When Status = 'Installed', InstallDate must be non-blank.
trigger ToyAssetNeedsInstallDate on Asset (before insert) {
    Migration_Settings__c ms = Migration_Settings__c.getOrgDefaults();
    if (ms != null && ms.Bypass_Automation__c == true) { return; }
    for (SObject r : Trigger.new) {
        if (String.valueOf(r.get('Status')) == 'Installed'
                && String.isBlank(String.valueOf(r.get('InstallDate')))) {
            r.addError('InstallDate', 'Installed assets need an install date');
        }
    }
}
