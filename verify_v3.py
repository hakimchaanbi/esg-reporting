"""Spot-check v3 output against values read by eye from the raw HTML."""
import pandas as pd

df = pd.read_csv("Combined_universities_data/combined_credit_fields.csv")

print("=== Berkeley OP-6, as extracted ===")
op6 = df[(df.institution.str.contains("Berkeley")) & (df.credit_code == "OP-6")]
for _, r in op6.head(16).iterrows():
    sec = (r.section or "")[:26]
    units = f"  [{r.units}]" if pd.notna(r.units) and r.units else ""
    val = "«not reported»" if r.value_type == "not_reported" else str(r.value)[:52]
    print(f"  ({sec:28}) {str(r.field)[:52]:54} = {val}{units}")

print("\n=== the four figures I read manually from the HTML ===")
expected = {
    "Scope 1 GHG emissions from stationary combustion": 134957.0,
    "Scope 1 GHG emissions from mobile combustion": 1676.0,
    "Scope 1 GHG fugitive emissions": 76.0,
}
for field, want in expected.items():
    hit = op6[op6.field == field]
    got = hit.value_numeric.iloc[0] if len(hit) else None
    unit = hit.units.iloc[0] if len(hit) else ""
    ok = "PASS" if got == want else "FAIL"
    print(f"  [{ok}] {field[:50]:52} want={want:>10} got={got} ({unit})")

print("\n=== units are attached, never left inside the value ===")
leaked = df[df.value.astype(str).str.contains("Metric tons|Megawatt|Cubic meters", na=False)
            & (df.value_type == "number")]
print(f"  numeric values with units leaked into the value field: {len(leaked)} (want 0)")

print("\n=== no field silently borrowed a neighbour's answer ===")
dupes = df.groupby(["institution", "credit_code"]).apply(
    lambda g: g.value.duplicated(keep=False).sum(), include_groups=False)
print(f"  credits where >2 fields share an answer: {(dupes > 2).sum()} "
      f"(expected: some — many are Yes/No)")

print("\n=== richest numeric credits (dashboard candidates) ===")
num = df[df.value_type == "number"]
top = num.groupby(["credit_code", "credit_name"]).size().sort_values(ascending=False).head(8)
for (code, name), n in top.items():
    print(f"  {code:7} {str(name)[:42]:44} {n:3} numeric fields")

print("\n=== TU Dublin PA-4 / PA-5 (CLAUDE.md 6.6: should be absent/empty) ===")
tud = df[(df.institution.str.contains("Dublin")) & (df.credit_code.isin(["PA-4", "PA-5"]))]
print(f"  rows: {len(tud)}")
for _, r in tud.head(4).iterrows():
    print(f"    {r.credit_code} {str(r.field)[:46]:48} = {str(r.value)[:30]}")
