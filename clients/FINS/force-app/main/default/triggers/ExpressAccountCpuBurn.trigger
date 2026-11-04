// EXPRESS enforcement A01 (AUTO01_CPU_Timeout). Generated from AUTO_SPEC; do not hand-edit.
// Deliberate per-record CPU cost of 75 ms. A 200-record chunk needs about
// 15,000 ms, over the 10,000 ms synchronous limit. Expected: System.LimitException: Apex CPU time limit exceeded (at batch size 200)
trigger ExpressAccountCpuBurn on Account (after insert) {
    Migration_Settings__c ms = Migration_Settings__c.getOrgDefaults();
    if (ms != null && ms.Bypass_Automation__c == true) { return; }
    Integer sink = 0;
    for (SObject r : Trigger.new) {
        Integer stopAt = Limits.getCpuTime() + 75;
        while (Limits.getCpuTime() < stopAt) {
            for (Integer i = 0; i < 200; i++) { sink += Math.mod(i * 7, 13); }
        }
    }
}
