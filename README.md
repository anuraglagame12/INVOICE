# GST Invoice Generator

Generates realistic GST tax invoices as PDFs, each paired with a ground-truth
JSON file describing exactly what an extraction pipeline should read from it —
including the Tally voucher the invoice should post as.

Built for testing the Procount invoice → Tally posting flow.

## Quick start

```bash
python -m invoicegen.web
```

Opens a page at <http://127.0.0.1:8000>. Tick the situations you want, set a
count, click **Generate**, download the ZIP.

Or from the command line:

```bash
python -m invoicegen --list                    # show every option id
python -m invoicegen -n 50 -s 42               # 50 invoices, seed 42
python -m invoicegen --all -n 20               # every option enabled
python -m invoicegen --opts intra,mix_12_18,freight,tds -n 30
```

## What comes out

```
out/
  pdf/
    AE_SI_26-27_26401.pdf     the invoices
    AE_SI_26-27_26402.pdf
    ...
  json/
    AE_SI_26-27_26401.json    ground truth, same filename
    AE_SI_26-27_26402.json
    ...
  manifest.csv                one row per invoice
```

PDFs and ground truth sit in separate folders sharing a filename, so you can
point a parser at `pdf/` without it seeing the answers, then match results back
by name.

The JSON is the point. For each invoice it records every field of the Procount
minimum dataset — invoice number and date, both parties with GSTIN/PAN/state,
place of supply, every line with HSN/SAC, qty, UOM, rate, discount, taxable
value and tax split, other charges with their own ledgers, the HSN-wise tax
summary, TDS, bill-wise refs, and all totals — plus `expected_voucher`, the
balanced Dr/Cr entry the invoice should produce in Tally.

Point your parser at the PDF, then diff its output against the JSON.

## The options

| Panel | Options |
|---|---|
| Supply type | `intra` `inter` |
| Tax rates | `rate18` `rate_other` `mix_12_18` `mix_all` `exempt` `cess` `rcm` |
| Content | `goods` `services` `both` |
| Other charges | `freight` `packing` `insurance` `loading` `advance` `roundoff` |
| Party | `registered` `unregistered` `name_variant` `eway` `irn` |
| Layers | `tds` `tcs` `billwise` `godown` `batch` |
| Volume / shape | `many_items` `long_desc` `large_amount` `odd_paise` |

Leaving a panel empty means "vary freely". Ticking several options in one panel
spreads them across the batch rather than forcing all of them onto every
invoice.

Two worth calling out:

- **`name_variant`** prints the buyer's name differently from their Tally ledger
  (`SHIV SHAMBHO ELECT.` vs `Shiv Shambho Electrical`). The JSON carries both,
  so you can check the parser matches on GSTIN and does *not* create a new
  ledger.
- **`rcm`** (reverse charge) shows tax on the invoice for reporting but excludes
  both tax and cess from the amount payable.

## Reproducibility

Same seed, same batch — byte for byte. When a parser fails on invoice 37,
regenerate that exact batch to debug it.

## Verifying

```bash
python verify.py out
```

Re-derives every figure independently and checks: line arithmetic, the
CGST/SGST/IGST split against the supply type, line sums against totals, the
HSN summary, the grand total, round-off bounds, that every voucher balances
(Dr = Cr), and that the PDF text layer carries the invoice number, total and
GSTIN.

## Checking the checkboxes work

```bash
python check_options.py            # test all 32
python check_options.py tds cess   # test just these
```

For each option it generates one batch with the box ticked and one without,
then counts how many invoices actually show the feature. A row passes only if
the feature appears with the box on **and** appears less often with it off —
so a checkbox that is wired to nothing fails loudly.

```
option             ON    OFF   result
tds               7/14   0/14   ok
cess             14/14   0/14   ok
freight           9/14   0/14   ok
```

Counts below 14/14 are expected: several options apply to a random share of
the batch rather than every invoice, which is what spreads coverage.

## Editing the data

- [`invoicegen/data/items.json`](invoicegen/data/items.json) — ~100 electrical
  goods with HSN codes and GST slabs, 12 services with SAC codes, and
  nil-rated items.
- [`invoicegen/data/parties.json`](invoicegen/data/parties.json) — seller, 20
  registered buyers across 7 states, unregistered buyers, ledger names,
  godowns, TDS sections.

Both are plain JSON. Replace them with a real item master and party list and
the generator picks it up — no code changes.

## Please note

**The GSTINs are fake.** They carry a valid GSTN check digit and a real state
code so a validator accepts them, but they belong to no registered business.
Fine for testing; do not issue real documents with them.

**All generated invoices are valid** and expected to clear the posting gate
(`expected_post_ready: true`). The tool tests that your parser reads good
invoices correctly — not that it rejects bad ones. Deliberately-broken invoices
would be a separate feature.

**The layout is a rebuild**, not a byte-identical copy of any particular
accounting package's output.

## Requirements

Python 3.8+ and `reportlab`. The web UI uses only the standard library.
`verify.py` uses `pdftotext` (poppler) for the PDF checks and skips them if it
isn't installed.
