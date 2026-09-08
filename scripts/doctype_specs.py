"""Single source of truth for Nyabo DocTypes.

`python scripts/gen_doctypes.py` turns this into the Frappe DocType JSON files under
nyabo_mn/nyabo/doctype/. Edit here, regenerate, commit both. The test stub reads the
generated JSON, so a field used in code that is not declared here fails the tests.

Conventions: labels are Mongolian (the desk is used by Mongolian accountants), fieldnames
are English, every DocType tracks changes, naming as documented in docs/ARCHITECTURE.md.
"""

from __future__ import annotations

from typing import Any

MODULE = "Nyabo"

ROLE_ADMIN = "Nyabo Admin"
ROLE_ACCOUNTANT = "Nyabo Accountant"
ROLE_OWNER = "Nyabo Owner"
ROLE_SYSTEM = "System Manager"


def F(fieldname: str, fieldtype: str, label: str = "", **kw: Any) -> dict[str, Any]:
	field: dict[str, Any] = {"fieldname": fieldname, "fieldtype": fieldtype}
	if label:
		field["label"] = label
	field.update({k: v for k, v in kw.items() if v is not None})
	return field


def SB(fieldname: str, label: str = "", **kw: Any) -> dict[str, Any]:
	return F(fieldname, "Section Break", label, **kw)


def CB(fieldname: str) -> dict[str, Any]:
	return F(fieldname, "Column Break")


def P(role: str, *, read=1, write=0, create=0, delete=0, submit=0, cancel=0, amend=0, **kw) -> dict[str, Any]:
	perm = {
		"role": role,
		"read": read,
		"write": write,
		"create": create,
		"delete": delete,
		"submit": submit,
		"cancel": cancel,
		"amend": amend,
		"email": 1,
		"export": 1,
		"print": 1,
		"report": 1,
		"share": 1,
	}
	perm.update(kw)
	return perm


FULL = dict(read=1, write=1, create=1, delete=1)
RW = dict(read=1, write=1, create=1, delete=0)
RO = dict(read=1)

ADMIN_ONLY = [P(ROLE_SYSTEM, **FULL), P(ROLE_ADMIN, **FULL)]
ADMIN_ACCOUNTANT = [P(ROLE_SYSTEM, **FULL), P(ROLE_ADMIN, **FULL), P(ROLE_ACCOUNTANT, **RW)]
ALL_ROLES = [P(ROLE_SYSTEM, **FULL), P(ROLE_ADMIN, **FULL), P(ROLE_ACCOUNTANT, **RW), P(ROLE_OWNER, **RO)]
APPEND_ONLY = [
	P(ROLE_SYSTEM, read=1, write=0, create=1),
	P(ROLE_ADMIN, read=1, create=1),
	P(ROLE_ACCOUNTANT, read=1, create=1),
]

BANKS = "Khan Bank\nTDB\nGolomt Bank\nTrans Bank\nXacBank"
REGIMES = "vat_payer\nsimplified_1pct"

DOCTYPES: dict[str, dict[str, Any]] = {}


def doctype(name: str, *, fields: list[dict], permissions: list[dict] | None = None, **kw: Any) -> None:
	spec: dict[str, Any] = {"fields": fields, "permissions": permissions or [], "track_changes": 1}
	spec.update(kw)
	DOCTYPES[name] = spec


# --- child tables --------------------------------------------------------------------

doctype(
	"Nyabo Tax Regime Period",
	istable=1,
	fields=[
		F("regime", "Select", "Татварын горим", options=REGIMES, reqd=1, in_list_view=1),
		F("effective_from", "Date", "Эхлэх огноо", reqd=1, in_list_view=1),
		F("effective_to", "Date", "Дуусах огноо", in_list_view=1),
		F("note", "Data", "Тэмдэглэл", in_list_view=1),
	],
)

doctype(
	"Nyabo Bank Account Row",
	istable=1,
	fields=[
		F("bank", "Select", "Банк", options=BANKS, reqd=1, in_list_view=1),
		F("currency", "Link", "Валют", options="Currency", reqd=1, default="MNT", in_list_view=1),
		F("account_number", "Data", "Дансны дугаар", in_list_view=1),
		F("gl_account", "Link", "Ерөнхий дэвтрийн данс", options="Account", read_only=1, in_list_view=1),
		F("erpnext_bank_account", "Link", "ERPNext банкны данс", options="Bank Account", read_only=1),
	],
)

doctype(
	"Nyabo User Company",
	istable=1,
	fields=[F("company", "Link", "Компани", options="Company", reqd=1, in_list_view=1)],
)

doctype(
	"Nyabo Posting Pattern Line",
	istable=1,
	fields=[
		F("side", "Select", "Тал", options="debit\ncredit", reqd=1, in_list_view=1),
		F("account_class", "Data", "Дансны анги", reqd=1, in_list_view=1),
		F("class_name_mn", "Data", "Ангийн нэр", in_list_view=1),
		F("sub_account_mn", "Data", "Дэд данс", in_list_view=1),
		F("amount_kind", "Data", "Дүнгийн төрөл", reqd=1, in_list_view=1, description="net, vat, gross, ..."),
		F("optional", "Check", "Заавал биш", default="0"),
		F("alternatives_json", "JSON", "Хувилбарууд"),
	],
)

doctype(
	"Nyabo Inventory Intake Item",
	istable=1,
	fields=[
		F("item_name", "Data", "Барааны нэр", reqd=1, in_list_view=1),
		F("qty", "Float", "Тоо", reqd=1, in_list_view=1),
		F("uom", "Data", "Хэмжих нэгж", default="ш", in_list_view=1),
		F("rate", "Currency", "Нэгж үнэ", reqd=1, in_list_view=1),
		F("amount", "Currency", "Дүн", read_only=1, in_list_view=1),
		F("item_code", "Link", "Бараа (ERPNext)", options="Item", read_only=1),
		F("warehouse", "Link", "Агуулах", options="Warehouse"),
	],
)

# --- settings and users ----------------------------------------------------------------

doctype(
	"Nyabo Company Settings",
	autoname="field:company",
	naming_rule="By fieldname",
	permissions=ADMIN_ACCOUNTANT,
	fields=[
		F("company", "Link", "Компани", options="Company", reqd=1, unique=1),
		F("chart_scheme", "Select", "Дансны кодын схем", options="v1\nv03\naccountant", default="v03"),
		F("default_expense_code", "Data", "Үндсэн зардлын данс (код)", default="7009"),
		F("onboarding_completed", "Check", "Тохиргоо дууссан", default="0"),
		F("onboarding_state", "Data", "Тохиргооны алхам", read_only=1),
		CB("cb_people"),
		F("owner_telegram_id", "Data", "Эзэмшигчийн Telegram ID"),
		F("accountant_telegram_id", "Data", "Нягтлангийн Telegram ID"),
		F("accountant_user", "Link", "Нягтлан (хэрэглэгч)", options="User"),
		F("accountant_of_record_name", "Data", "Нягтлан бодогчийн нэр"),
		F("accountant_micpa_permit", "Data", "МНБИ-ийн зөвшөөрлийн дугаар"),
		SB("sb_regime", "Татварын горим"),
		F("regimes", "Table", "Горимын түүх", options="Nyabo Tax Regime Period"),
		F("expects_under_400m_2027", "Check", "2027 онд 400 сая₮-с доош орлоготой байх", default="0"),
		SB("sb_approval", "Батлах бодлого"),
		F("auto_approve_policy", "Select", "Автомат батлах", options="none\nowner_simple", default="none"),
		F("auto_approve_max_amount", "Currency", "Автомат батлах дээд дүн"),
		F("auto_approve_accounts", "Small Text", "Зөвшөөрөгдсөн дансны кодууд (таслалаар)"),
		SB("sb_banks", "Банкны дансууд"),
		F("bank_accounts", "Table", "Банкны дансууд", options="Nyabo Bank Account Row"),
		SB("sb_policy", "НББ-ийн бодлого"),
		F("has_inventory", "Check", "Бараа материалтай", default="0"),
		F(
			"inventory_method",
			"Select",
			"Бараа материалын үнэлгээ",
			options="FIFO\nWeighted Average",
			default="FIFO",
		),
		F(
			"depreciation_method",
			"Select",
			"Элэгдлийн арга",
			options="Straight Line\nDouble Declining Balance",
			default="Straight Line",
		),
		F("fx_policy", "Data", "Валютын бодлого", default="Монголбанкны албан ханш, гүйлгээний өдрөөр"),
		F("retention_years", "Int", "Баримт хадгалах жил", default="10", read_only=1),
		SB("sb_meta", "Систем"),
		F("few_shot_refreshed_at", "Datetime", "Жишээ шинэчилсэн", read_only=1),
	],
)

doctype(
	"Nyabo User Link",
	autoname="field:telegram_id",
	naming_rule="By fieldname",
	permissions=ADMIN_ONLY,
	fields=[
		F("telegram_id", "Data", "Telegram ID", reqd=1, unique=1),
		F("telegram_username", "Data", "Telegram нэр"),
		F("first_name", "Data", "Нэр"),
		F("user", "Link", "Хэрэглэгч", options="User", reqd=1),
		F("role", "Select", "Үүрэг", options="Owner\nAccountant\nAdmin", reqd=1),
		F("status", "Select", "Төлөв", options="active\nblocked", default="active"),
		F("linked_at", "Datetime", "Холбогдсон"),
		F("active_company", "Link", "Идэвхтэй компани", options="Company"),
		F("companies", "Table", "Компаниуд", options="Nyabo User Company"),
	],
)

doctype(
	"Nyabo Link Code",
	autoname="field:code",
	naming_rule="By fieldname",
	permissions=ADMIN_ONLY,
	fields=[
		F("code", "Data", "Код", reqd=1, unique=1),
		F("role", "Select", "Үүрэг", options="Owner\nAccountant\nAdmin", reqd=1),
		F("company", "Link", "Компани", options="Company"),
		F("issued_by", "Link", "Олгосон", options="User"),
		F("expires_at", "Datetime", "Дуусах хугацаа", reqd=1),
		F("status", "Select", "Төлөв", options="open\nused\nexpired", default="open"),
		F("used_by_telegram_id", "Data", "Ашигласан Telegram ID"),
		F("used_at", "Datetime", "Ашигласан"),
	],
)

doctype(
	"Nyabo Chat State",
	autoname="field:chat_id",
	naming_rule="By fieldname",
	permissions=ADMIN_ONLY,
	track_changes=0,
	fields=[
		F("chat_id", "Data", "Chat ID", reqd=1, unique=1),
		F("telegram_id", "Data", "Telegram ID"),
		F("state", "Data", "Төлөв"),
		F("payload_json", "JSON", "Өгөгдөл"),
		F("last_update_id", "Int", "Сүүлийн update_id"),
		F("updated_at", "Datetime", "Шинэчилсэн"),
	],
)

# --- documents and proposals --------------------------------------------------------------

DOC_TYPES = "receipt\nsales_ebarimt\nbank_statement\ninventory\nother"
DOC_STATUS = "received\nextracted\nproposed\napproved\nrejected\nposted\nfailed"

doctype(
	"Nyabo Document",
	autoname="NYD-.#####",
	naming_rule="Expression (old style)",
	permissions=ALL_ROLES,
	fields=[
		F("company", "Link", "Компани", options="Company", reqd=1, in_list_view=1, in_standard_filter=1),
		F(
			"doc_type",
			"Select",
			"Баримтын төрөл",
			options=DOC_TYPES,
			reqd=1,
			in_list_view=1,
			in_standard_filter=1,
		),
		F(
			"status",
			"Select",
			"Төлөв",
			options=DOC_STATUS,
			default="received",
			in_list_view=1,
			in_standard_filter=1,
		),
		F("file", "Attach", "Файл", reqd=1),
		F("file_hash", "Data", "Файлын хэш (SHA-256)", read_only=1, search_index=1),
		F("mime_type", "Data", "MIME төрөл", read_only=1),
		F("size_bytes", "Int", "Хэмжээ (байт)", read_only=1),
		CB("cb_sender"),
		F("sender_telegram_id", "Data", "Илгээгчийн Telegram ID"),
		F("sender_user", "Link", "Илгээгч (хэрэглэгч)", options="User"),
		F("telegram_file_id", "Data", "Telegram file_id", read_only=1),
		F("telegram_chat_id", "Data", "Telegram chat_id", read_only=1),
		F("telegram_message_id", "Data", "Telegram message_id", read_only=1),
		F("received_at", "Datetime", "Хүлээн авсан"),
		SB("sb_result", "Үр дүн"),
		F("posted_doctype", "Link", "Бүртгэсэн баримтын төрөл", options="DocType", read_only=1),
		F("posted_name", "Dynamic Link", "Бүртгэсэн баримт", options="posted_doctype", read_only=1),
		F(
			"retain_until",
			"Date",
			"Хадгалах хугацаа (хүртэл)",
			read_only=1,
			description="Нягтлан бодох бүртгэлийн тухай хууль 11.1: 10 жил",
		),
		F("error", "Small Text", "Алдаа", read_only=1),
	],
)

PROPOSAL_STATUS = "proposed\napproved\nrejected\nposted\nfailed"
VAT_TREATMENTS = "withheld\nin_expense\nexempt\nzero\nnone"

doctype(
	"Nyabo Proposal",
	autoname="NYP-.#####",
	naming_rule="Expression (old style)",
	permissions=ALL_ROLES,
	fields=[
		F("document", "Link", "Эх баримт", options="Nyabo Document", in_list_view=1),
		F("company", "Link", "Компани", options="Company", reqd=1, in_list_view=1, in_standard_filter=1),
		F(
			"kind",
			"Select",
			"Төрөл",
			options="receipt\nbank_line\ninventory\ncorrection",
			default="receipt",
			in_standard_filter=1,
		),
		F(
			"status",
			"Select",
			"Төлөв",
			options=PROPOSAL_STATUS,
			default="proposed",
			in_list_view=1,
			in_standard_filter=1,
		),
		F("needs_accountant", "Check", "Зөвхөн нягтлан батлана", default="0"),
		CB("cb_head"),
		F("supplier", "Link", "Харилцагч", options="Supplier"),
		F("supplier_is_new", "Check", "Шинэ харилцагч", default="0"),
		F("posting_date", "Date", "Огноо"),
		F("total", "Currency", "Нийт дүн"),
		F("vat_amount", "Currency", "НӨАТ"),
		F("vat_treatment", "Select", "НӨАТ-ын бүртгэл", options=VAT_TREATMENTS, default="none"),
		SB("sb_entry", "Санал болгосон бичилт"),
		F("account_code", "Data", "Дансны код"),
		F("account", "Link", "Данс", options="Account"),
		F("posting_pattern", "Link", "Бичилтийн загвар", options="Nyabo Posting Pattern"),
		F("rule_applied", "Link", "Хэрэглэсэн дүрэм", options="Nyabo Rule"),
		F("explanation", "Small Text", "Тайлбар", length=300),
		F("citation", "Data", "Иш татсан заалт"),
		F("entry_json", "JSON", "Бичилт (JSON)"),
		F("extracted_json", "JSON", "Танисан өгөгдөл (JSON)"),
		F("verification_json", "JSON", "Баталгаажуулалт (JSON)"),
		F("confidence_json", "JSON", "Итгэлийн түвшин (JSON)"),
		F("warnings_json", "JSON", "Анхааруулга (JSON)"),
		SB("sb_llm", "Модель"),
		F("prompt_version", "Data", "Промптын хувилбар", read_only=1),
		F("model", "Data", "Модель", read_only=1),
		F("tokens_in", "Int", "Оролтын токен", read_only=1),
		F("tokens_out", "Int", "Гаралтын токен", read_only=1),
		F("latency_ms", "Int", "Хугацаа (мс)", read_only=1),
		SB("sb_decision", "Шийдвэр"),
		F("approved_by", "Link", "Баталсан", options="User", read_only=1),
		F("approved_telegram_id", "Data", "Баталсан Telegram ID", read_only=1),
		F("approved_at", "Datetime", "Баталсан огноо", read_only=1),
		F("rejection_reason", "Data", "Татгалзсан шалтгаан", read_only=1),
		F("posted_doctype", "Link", "Бүртгэсэн баримтын төрөл", options="DocType", read_only=1),
		F("posted_name", "Dynamic Link", "Бүртгэсэн баримт", options="posted_doctype", read_only=1),
		F("bank_transaction", "Link", "Банкны гүйлгээ", options="Bank Transaction"),
		F("card_chat_id", "Data", "Картын chat_id", read_only=1),
		F("card_message_id", "Data", "Картын message_id", read_only=1),
	],
)

doctype(
	"Nyabo Correction",
	autoname="NYC-.#####",
	naming_rule="Expression (old style)",
	permissions=ADMIN_ACCOUNTANT,
	fields=[
		F("proposal", "Link", "Санал", options="Nyabo Proposal", in_list_view=1),
		F("company", "Link", "Компани", options="Company", reqd=1, in_standard_filter=1),
		F(
			"field",
			"Select",
			"Талбар",
			options="account_code\nvat_treatment\nsupplier\ntotal\nposting_date\nrejected\nreversed",
			reqd=1,
			in_list_view=1,
		),
		F("proposed_value", "Data", "Санал болгосон утга", in_list_view=1),
		F("corrected_value", "Data", "Зассан утга", in_list_view=1),
		F("source", "Select", "Эх сурвалж", options="edit\nreversal\nrejection", default="edit"),
		CB("cb_who"),
		F("corrected_by", "Link", "Зассан", options="User"),
		F("corrected_telegram_id", "Data", "Зассан Telegram ID"),
		F("reason", "Data", "Шалтгаан"),
		F("reason_text", "Small Text", "Шалтгааны тайлбар"),
		F("posted_doctype", "Link", "Баримтын төрөл", options="DocType"),
		F("posted_name", "Dynamic Link", "Баримт", options="posted_doctype"),
		F("reversal_name", "Data", "Буцаалтын баримт"),
		F("supplier", "Link", "Харилцагч", options="Supplier"),
	],
)

doctype(
	"Nyabo Rule",
	autoname="NYR-.#####",
	naming_rule="Expression (old style)",
	permissions=ADMIN_ACCOUNTANT,
	fields=[
		F("company", "Link", "Компани", options="Company", reqd=1, in_list_view=1, in_standard_filter=1),
		F(
			"match_type",
			"Select",
			"Тааруулах төрөл",
			options="supplier_register_no\nsupplier_name_pattern\ndescription_pattern\namount_band\nbank_fee",
			reqd=1,
			in_list_view=1,
		),
		F("match_value", "Data", "Тааруулах утга", in_list_view=1),
		F("amount_min", "Currency", "Доод дүн"),
		F("amount_max", "Currency", "Дээд дүн"),
		F(
			"status",
			"Select",
			"Төлөв",
			options="active\npending_confirmation\ndisabled",
			default="active",
			in_list_view=1,
			in_standard_filter=1,
		),
		CB("cb_target"),
		F("target_account_code", "Data", "Зорилтот дансны код", reqd=1, in_list_view=1),
		F("vat_treatment", "Select", "НӨАТ-ын бүртгэл", options=VAT_TREATMENTS, default="none"),
		F("posting_pattern", "Link", "Бичилтийн загвар", options="Nyabo Posting Pattern"),
		F("source", "Select", "Эх сурвалж", options="accountant\nlearned\nseed", default="accountant"),
		F("hit_count", "Int", "Хэрэглэсэн тоо", default="0", read_only=1),
		F("last_hit", "Datetime", "Сүүлд хэрэглэсэн", read_only=1),
		F("created_from_corrections", "Small Text", "Үүсгэсэн залруулгууд", read_only=1),
	],
)

doctype(
	"Nyabo LLM Call",
	autoname="NYL-.######",
	naming_rule="Expression (old style)",
	permissions=ADMIN_ONLY,
	track_changes=0,
	fields=[
		F(
			"purpose",
			"Select",
			"Зорилго",
			options="extract\nclassify\nquestion\neval\nother",
			reqd=1,
			in_list_view=1,
		),
		F("provider", "Data", "Үйлчилгээ", in_list_view=1),
		F("model", "Data", "Модель", in_list_view=1),
		F("prompt_version", "Data", "Промптын хувилбар"),
		F("ok", "Check", "Амжилттай", default="1", in_list_view=1),
		F("error_class", "Data", "Алдааны төрөл"),
		CB("cb_usage"),
		F("tokens_in", "Int", "Оролтын токен"),
		F("tokens_out", "Int", "Гаралтын токен"),
		F("latency_ms", "Int", "Хугацаа (мс)"),
		F("cost_usd", "Float", "Зардал (USD)", precision="6"),
		F("company", "Link", "Компани", options="Company"),
		F("proposal", "Link", "Санал", options="Nyabo Proposal"),
	],
)

doctype(
	"Nyabo Eval Case",
	autoname="NYE-.#####",
	naming_rule="Expression (old style)",
	permissions=ADMIN_ONLY,
	fields=[
		F(
			"kind",
			"Select",
			"Төрөл",
			options="extraction\nclassification\nvat\nmatching\nrules\ninjection\ncorrection\nperiod_lock\nfx\ndocument_required",
			reqd=1,
			in_list_view=1,
			in_standard_filter=1,
		),
		F(
			"source",
			"Select",
			"Эх сурвалж",
			options="golden\ncorrection\nsynthetic",
			default="golden",
			in_list_view=1,
		),
		F("company", "Link", "Компани", options="Company"),
		F("regime", "Select", "Горим", options="\n" + REGIMES),
		F("on_date", "Date", "Гүйлгээний огноо"),
		F("input_document", "Link", "Оролтын баримт", options="Nyabo Document"),
		F("input_json", "JSON", "Оролт (JSON)"),
		F("expected_json", "JSON", "Хүлээгдэж буй үр дүн (JSON)"),
		F("notes", "Small Text", "Тэмдэглэл"),
	],
)

# --- rules as data --------------------------------------------------------------------

doctype(
	"Nyabo Tax Parameter",
	autoname="format:{key}:{effective_from}",
	naming_rule="Expression",
	permissions=ADMIN_ONLY,
	fields=[
		F("key", "Data", "Түлхүүр", reqd=1, in_list_view=1, in_standard_filter=1),
		F("effective_from", "Date", "Эхлэх огноо", reqd=1, in_list_view=1),
		F("effective_to", "Date", "Дуусах огноо", in_list_view=1),
		F("status", "Select", "Төлөв", options="active\npending", default="active", in_list_view=1),
		F("verified", "Check", "Баталгаажсан", default="0", in_list_view=1, in_standard_filter=1),
		CB("cb_value"),
		F("value_json", "JSON", "Утга (JSON)"),
		F(
			"unit",
			"Select",
			"Нэгж",
			options="fraction\nMNT\nyears\nschedule\nrule\ndeadline",
			default="fraction",
		),
		SB("sb_source", "Эх сурвалж"),
		F("source_text", "Data", "Хууль, заалт"),
		F("source_url", "Data", "URL"),
		F("article", "Data", "Зүйл, заалт"),
		F("quote_mn", "Small Text", "Иш татсан текст"),
		F("note", "Small Text", "Тэмдэглэл"),
	],
)

doctype(
	"Nyabo Posting Pattern",
	autoname="field:pattern_id",
	naming_rule="By fieldname",
	permissions=ADMIN_ONLY,
	fields=[
		F("pattern_id", "Data", "Загварын код", reqd=1, unique=1),
		F("name_mn", "Data", "Нэр", reqd=1, in_list_view=1),
		F("document_types", "Small Text", "Баримтын төрлүүд (таслалаар)", reqd=1),
		F(
			"applies_to_vat",
			"Select",
			"НӨАТ-ын төлөв",
			options="any\nvat_payer\nnon_vat",
			default="any",
			in_list_view=1,
		),
		F(
			"applies_to_cit",
			"Select",
			"ААНОАТ-ын горим",
			options="any\nregular\nsimplified_1pct",
			default="any",
		),
		F("conditions", "Small Text", "Нөхцөл"),
		F("verified", "Check", "Баталгаажсан", default="0", in_list_view=1, in_standard_filter=1),
		F("enabled", "Check", "Идэвхтэй", default="1"),
		SB("sb_lines", "Бичилт"),
		F("lines", "Table", "Мөрүүд", options="Nyabo Posting Pattern Line", reqd=1),
		F("primary_document_mn", "Data", "Анхан шатны баримт"),
		SB("sb_citation", "Иш татах заалт"),
		F(
			"citation_instrument",
			"Data",
			"Эрх зүйн акт",
			default="Сангийн сайдын 2000 оны 116 дугаар тушаал (Заавар 116)",
		),
		F("citation_section", "Data", "Заалт"),
		F("citation_quote", "Small Text", "Иш татсан текст"),
		F("citation_url", "Data", "URL"),
		F("notes", "Small Text", "Тэмдэглэл"),
	],
)

doctype(
	"Nyabo Account Alias",
	autoname="format:{company}:{scheme}:{alias_code}",
	naming_rule="Expression",
	permissions=ADMIN_ACCOUNTANT,
	fields=[
		F("company", "Link", "Компани", options="Company", reqd=1, in_list_view=1, in_standard_filter=1),
		F("scheme", "Select", "Схем", options="v1\naccountant\nmof", reqd=1, in_list_view=1),
		F("alias_code", "Data", "Код (хуучин)", reqd=1, in_list_view=1),
		F("target_code", "Data", "Код (загвар)", reqd=1, in_list_view=1),
		F("target_account", "Link", "Данс", options="Account"),
		F("note", "Data", "Тэмдэглэл"),
	],
)

doctype(
	"Nyabo Bank Layout",
	autoname="field:layout_id",
	naming_rule="By fieldname",
	permissions=ADMIN_ACCOUNTANT,
	fields=[
		F("layout_id", "Data", "Загварын код", reqd=1, unique=1),
		F("bank", "Select", "Банк", options=BANKS + "\nOther", reqd=1, in_list_view=1),
		F("verified", "Check", "Баталгаажсан", default="0", in_list_view=1),
		F(
			"amount_style",
			"Select",
			"Дүнгийн хэлбэр",
			options="separate_debit_credit\nsigned_amount",
			default="separate_debit_credit",
		),
		F("header_row_hint", "Int", "Толгой мөрийн байрлал"),
		F(
			"date_formats",
			"Small Text",
			"Огнооны форматууд (мөр тус бүр)",
			default="%Y-%m-%d\n%Y.%m.%d\n%d.%m.%Y",
		),
		F("header_signature_json", "JSON", "Толгойн гарын үсэг (JSON)"),
		F("column_map_json", "JSON", "Баганын зураглал (JSON)"),
		F("sample_file", "Attach", "Жишээ файл"),
		F("notes", "Small Text", "Тэмдэглэл"),
	],
)

doctype(
	"Nyabo Event",
	autoname="NYEV-.######",
	naming_rule="Expression (old style)",
	permissions=APPEND_ONLY,
	track_changes=0,
	fields=[
		F("event_type", "Data", "Үйл явдал", reqd=1, in_list_view=1, in_standard_filter=1),
		F("company", "Link", "Компани", options="Company", in_list_view=1, in_standard_filter=1),
		F("actor_user", "Link", "Хэрэглэгч", options="User", in_list_view=1),
		F("actor_telegram_id", "Data", "Telegram ID"),
		F("ref_doctype", "Link", "Баримтын төрөл", options="DocType"),
		F("ref_name", "Dynamic Link", "Баримт", options="ref_doctype", in_list_view=1),
		F("reason", "Small Text", "Шалтгаан"),
		F("payload_json", "JSON", "Өгөгдөл (JSON)"),
	],
)

doctype(
	"Nyabo Inventory Intake",
	autoname="NYI-.#####",
	naming_rule="Expression (old style)",
	permissions=ADMIN_ACCOUNTANT,
	fields=[
		F("company", "Link", "Компани", options="Company", reqd=1, in_list_view=1),
		F("source", "Select", "Эх сурвалж", options="excel\ntext", default="excel"),
		F("file", "Attach", "Файл"),
		F("posting_date", "Date", "Огноо", reqd=1),
		F(
			"status",
			"Select",
			"Төлөв",
			options="draft\nconfirmed\nposted\nfailed",
			default="draft",
			in_list_view=1,
		),
		F("items", "Table", "Бараа", options="Nyabo Inventory Intake Item"),
		F("total_amount", "Currency", "Нийт дүн", read_only=1),
		F("confirmed_by", "Link", "Баталсан", options="User", read_only=1),
		F("created_docs_json", "JSON", "Үүсгэсэн баримтууд (JSON)", read_only=1),
		F("error", "Small Text", "Алдаа", read_only=1),
	],
)
