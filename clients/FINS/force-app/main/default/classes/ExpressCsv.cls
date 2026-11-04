/**
 * RFC 4180 line parser for EXPRESS seed resources. A record never spans lines (contract:
 * values carry no line break), so a line is a record. Fields may hold commas and quotes.
 */
public without sharing class ExpressCsv {
    /** Lines by indexOf, never String.split: a regex split of a large resource throws
     *  "Regex too complicated" (measured on a 650 KB resource, rehearsal 2026-11-04). */
    public static List<String> lines(String body) {
        List<String> out = new List<String>();
        if (body == null) { return out; }
        String b = body.replace('\r\n', '\n').replace('\r', '\n');
        Integer n = b.length();
        Integer pos = 0;
        while (pos < n) {
            Integer nl = b.indexOf('\n', pos);
            if (nl < 0) { nl = n; }
            if (nl > pos) { out.add(b.substring(pos, nl)); }
            pos = nl + 1;
        }
        return out;
    }

    public static List<String> parseLine(String line) {
        if (!line.contains('"')) { return line.split(',', -1); }
        List<String> out = new List<String>();
        String cur = '';
        Boolean quoted = false;
        Integer n = line.length();
        Integer i = 0;
        while (i < n) {
            String ch = line.substring(i, i + 1);
            if (quoted) {
                if (ch == '"') {
                    if (i + 1 < n && line.substring(i + 1, i + 2) == '"') { cur += '"'; i++; }
                    else { quoted = false; }
                } else { cur += ch; }
            } else if (ch == '"') {
                quoted = true;
            } else if (ch == ',') {
                out.add(cur);
                cur = '';
            } else { cur += ch; }
            i++;
        }
        out.add(cur);
        return out;
    }
}
