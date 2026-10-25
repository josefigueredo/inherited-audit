# Rewrites a draft PR body prepared by inherited-audit into a fix PR body; everything else is kept as it is.
#   -v draft=<the draft note line>  replaced by -v note=<the fix note>; prepended when the body no longer has it
#   -v fixed="C-26 C-27"            the findings whose `Refs #N.` becomes `Closes #N.`
#   -v all=1                        every `Refs #N.` becomes `Closes #N.` (every finding of the PR is fixed or moot)
# The Nth `Refs #N.` line belongs to the Nth id of the `Findings:` line (publish writes them in that order); when the
# two counts differ the mapping is unknown, and with all=0 every Refs line is kept.
{ sub(/\r$/, ""); line[NR] = $0 }
END {
  nids = 0; nrefs = 0; noted = 0
  for (i = 1; i <= NR; i++) {
    if (nids == 0 && line[i] ~ /^Findings: /) {
      s = line[i]; sub(/^Findings: /, "", s); sub(/\.$/, "", s); nids = split(s, ids, /, /)
    }
    if (line[i] ~ /^Refs #[0-9]+\.?$/) nrefs++
    if (line[i] == draft) noted = 1
  }
  if (!noted) { print note; print "" }
  k = 0
  for (i = 1; i <= NR; i++) {
    l = line[i]
    if (l == draft) {
      l = note
    } else if (l ~ /^Refs #[0-9]+\.?$/) {
      k++
      if (all == 1 || (nrefs == nids && index(" " fixed " ", " " ids[k] " ") > 0)) sub(/^Refs/, "Closes", l)
    }
    print l
  }
}
