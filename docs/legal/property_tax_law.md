# Immovable Property Tax Law — Үл хөдлөх эд хөрөнгийн албан татварын тухай хууль (2000, consolidated)

*Generated from the seed on 2026-09-08 by the legal-citation pass; the quotes are verbatim from the saved copies of the texts listed in docs/legal/README.md. Regenerate rather than edit the tables by hand.*

Primary text: https://legalinfo.mn/mn/detail?lawId=39 (fetched 2026-09-08).

## Seed rows read from this law

| Article | Claim (seed key, period, value) | Verbatim quote (Mongolian) | Status | Remarks |
|---|---|---|---|---|
| 6.1 | `property_tax.rate` 2026-01-01 .. open: null (pending) | — | pending | INTENTIONALLY NULL (status pending): the engine raises PendingRuleError on any lookup that lands here instead of computing with an unstated number. CONTRADICTS the reference's fixed 0.6%: art. 6.1 sets a RANGE and delegates the rate — «6.1.Үл хөдлөх эд хөрөнгийн албан татварыг энэ хуулийн 5 дугаар зүйлд заасан үнэлгээнээс аймаг, нийслэлийн иргэдийн Төлөөлөгчдийн Хурал, улсын зэрэглэлтэй хотын Зөвлөл тухайн хөрөнгийн байршил, зориулалт, хэмжээ, зах зээлийн эрэлт, нийлүүлэлтийн байдлыг харгалзан 0.6-2.0 хувиар тооцож ногдуулна.» (as rewritten 25 Nov 2010, amended 7 Jul 2021 and 5 Jun 2024); 6.2 allows up to +1 point for properties lacking greenery/parking, 6.4 a reduction for regional-development projects. Base per 5.1: registered value, else insured value, else book value. The 0,6% in Order 116 §9.4.1.1 is the 2000 instruction's figure. For Ulaanbaatar the rate is in the annex to Нийслэлийн ИТХ resolution No. 123 of 5 Dec 2023 (in force 1 Jan 2024, https://legalinfo.mn/mn/detail?lawId=16960673679211), which was not read. Must become a per-aimag/city parameter, never a constant. DAILY USE: no — annual, and only for an entity that owns immovable property, which most micro clients do not. WHAT WOULD BE WRONG WITH TICKING IT: there is no single national rate to vouch for. The law fixes a 0.6-2.0% range and hands the choice to each aimag or city assembly, so a constant here would be wrong for every taxpayer outside the one locality it was copied from. WHAT UNBLOCKS IT: the annex to the local assembly's resolution for the property's own location (for Ulaanbaatar, Нийслэлийн ИТХ resolution No. 123 of 5 Dec 2023), encoded per locality rather than as one row. |

| Article | Claim | Verbatim quote | Status |
|---|---|---|---|
| 5.1 | Tax base: registered value, else insured value, else book value | «5.1. Газраас бусад үл хөдлөх эд хөрөнгийн албан татвар ногдуулах үнэлгээг уул хөрөнгийн үл хөдлөх эд хөрөнгийн бүртгэлд бүртгэгдсэн үнийн дүнгээр, үл хөдлөх эд хөрөнгийн бүртгэлд бүртгэгдээгүй бол хөрөнгийн даатгалд даатгуулсан үнийн дүнгээр, хөрөнгийн даатгалд даатгуулаагүй бол данс бүртгэлд бүртгэгдсэн үнийн дүнгээр тус тус тодорхойлно.» | confirmed |
| 6.1 | Rate is a 0.6–2.0% range fixed by the aimag / capital-city assembly — contradicts the reference's fixed 0.6% (which is the figure printed in Order 116 §9.4.1.1) | «6.1.Үл хөдлөх эд хөрөнгийн албан татварыг энэ хуулийн 5 дугаар зүйлд заасан үнэлгээнээс аймаг, нийслэлийн иргэдийн Төлөөлөгчдийн Хурал, улсын зэрэглэлтэй хотын Зөвлөл тухайн хөрөнгийн байршил, зориулалт, хэмжээ, зах зээлийн эрэлт, нийлүүлэлтийн байдлыг харгалзан 0.6-2.0 хувиар тооцож ногдуулна.» | contradicted → seed pending |
| 6.2 | Up to +1 point for properties lacking greenery / parking (2023) | «6.2.Хот байгуулалтын тухай хуулийн 12.6.3, 12.8-д заасан цэцэрлэг, ногоон байгууламж, авто зогсоолын шаардлага хангаагүй үл хөдлөх эд хөрөнгөд ногдуулах албан татварын хувь, хэмжээг … 1 хүртэл хувиар нэмэгдүүлэн тогтоож болно.» | confirmed |

Unconfirmed: the Ulaanbaatar rate — annex to Нийслэлийн ИТХ resolution No. 123 of
5 Dec 2023 (in force 1 Jan 2024, https://legalinfo.mn/mn/detail?lawId=16960673679211), not
in the page text. The rate must be a per-aimag/city parameter in Nyabo.
