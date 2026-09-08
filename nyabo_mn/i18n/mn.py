"""Every user-facing string in one place (Mongolian Cyrillic, polite form).

Edit wording here; code refers to names, never to literal text. Strings with {placeholders}
are used with str.format(**kwargs). Sections are delimited so parallel work merges cleanly;
add new strings inside the section of the module that uses them.
"""

from __future__ import annotations

# --- product ---------------------------------------------------------------------------
PRODUCT_NAME = "Нябо"
BRAND_LINE = "Нябо · Таны нягтлангийн туслах"

# --- buttons (state changes; the LLM never generates these) ---------------------------
BTN_APPROVE = "Батлах"
BTN_CHANGE_ACCOUNT = "Данс солих"
BTN_REJECT = "Татгалзах"
BTN_LATER = "Дараа"
BTN_FIND_DOCUMENT = "Баримт хайх"
BTN_RECORD_EXPENSE = "Зардал бүртгэх"
BTN_CONFIRM = "Баталгаажуулах"
BTN_CANCEL = "Цуцлах"
BTN_BACK = "Буцах"
BTN_YES = "Тийм"
BTN_NO = "Үгүй"
BTN_DONE = "Дууссан"
BTN_SKIP = "Алгасах"
BTN_EDIT = "Засах"
BTN_CLOSE_PERIOD = "Хаах"
BTN_SEARCH = "Хайх"
BTN_OTHER = "Бусад"
BTN_MENU = "Цэс"
BTN_HELP = "Тусламж"
BTN_MORE_ACCOUNTS = "Өөр данс…"
BTN_SHOW_ENTRY = "Бичилт харах"
BTN_REVERSE = "Буцаах"
BTN_NEW_ENTRY = "Шинэ бичилт"

# --- rejection reasons (one tap) -------------------------------------------------------
REJECT_PERSONAL = "Хувийн зардал"
REJECT_DUPLICATE = "Давхардсан"
REJECT_WRONG_COMPANY = "Буруу компани"
REJECT_OTHER = "Бусад"
REJECT_REASONS = {
	"personal": REJECT_PERSONAL,
	"dup": REJECT_DUPLICATE,
	"company": REJECT_WRONG_COMPANY,
	"other": REJECT_OTHER,
}

# --- correction reasons (Law on Accounting art. 15: reason and method recorded) ---------
CORRECT_WRONG_ACCOUNT = "Буруу данс"
CORRECT_WRONG_AMOUNT = "Буруу дүн"
CORRECT_DUPLICATE = "Давхардсан"
CORRECT_OTHER = "Бусад"
CORRECT_REASONS = {
	"account": CORRECT_WRONG_ACCOUNT,
	"amount": CORRECT_WRONG_AMOUNT,
	"dup": CORRECT_DUPLICATE,
	"other": CORRECT_OTHER,
}
MSG_CORRECTION_ASK_REASON = "Залруулгын шалтгааныг сонгоно уу:"
MSG_CORRECTION_ASK_TEXT = "Шалтгааныг нэг өгүүлбэрээр бичнэ үү:"
MSG_CORRECTION_DONE = "↩️ Буцаалт бүртгэлээ: {reversal}\nШалтгаан: {reason} · Баталсан: {approver}"
MSG_CORRECTION_PERIOD_CLOSED = "⚠️ Анхны бичилтийн сар ({period}) хаагдсан тул буцаалтыг өнөөдрийн огноогоор бүртгэлээ. Нягтлан анхаарна уу."
MSG_CORRECTION_NEW_ENTRY_HINT = "Одоо зөв утгаар шинэ бичилтийн саналыг илгээж байна."
MSG_CORRECTION_ALREADY_REVERSED = "Энэ бичилт аль хэдийн буцаагдсан байна."

# --- generic messages ------------------------------------------------------------------
MSG_WELCOME = "Сайн байна уу! Би Нябо — таны нягтлангийн туслах. Баримтын зургаа илгээвэл бүртгэлийн саналыг танд илгээнэ."
MSG_NOT_LINKED = (
	"Таны Telegram хаяг Нябо-д холбогдоогүй байна. Админаас 6 оронтой холболтын код авч энд бичнэ үү."
)
MSG_LINKED = "✅ Холбогдлоо. Үүрэг: {role}. Компани: {company}."
MSG_LINK_CODE_INVALID = "Код буруу эсвэл хугацаа нь дууссан байна."
MSG_LINK_CODE_ISSUED = "Холболтын код: {code}\nҮүрэг: {role} · Компани: {company}\nХүчинтэй: {minutes} минут. Хэрэглэгч энэ кодыг Нябо-д бичнэ."
MSG_YOUR_TELEGRAM_ID = "Таны Telegram ID: {telegram_id}"
MSG_DUPLICATE_DOCUMENT = "Энэ баримт өмнө нь илгээгдсэн."
MSG_RECEIVED_PROCESSING = "🧾 Хүлээн авлаа, шалгаж байна…"
MSG_POSTED = "✅ Бүртгэлээ: {doc_name}"
MSG_REJECTED = "❌ Татгалзлаа: {reason}"
MSG_ERROR_GENERIC = "Уучлаарай, алдаа гарлаа. Дахин оролдоно уу."
MSG_ERROR_ADMIN_NOTIFIED = "Уучлаарай, алдаа гарлаа. Админд мэдэгдлээ."
MSG_ACCOUNTANT_ONLY = "Энэ саналыг зөвхөн нягтлан батлах боломжтой (⚠️ тэмдэглэгээтэй)."
MSG_NO_PERMISSION = "Танд энэ үйлдлийг хийх эрх байхгүй."
MSG_UNKNOWN_COMMAND = "Ойлгосонгүй. /тусламж гэж бичнэ үү."
MSG_CHOOSE_COMPANY = "Компаниа сонгоно уу:"
MSG_ACTIVE_COMPANY = "Идэвхтэй компани: {company}"
MSG_NO_COMPANY = "Танд холбогдсон компани алга. Админд хандана уу."
MSG_PROPOSAL_NOT_FOUND = "Санал олдсонгүй эсвэл аль хэдийн шийдвэрлэгдсэн."
MSG_PROPOSAL_ALREADY_DECIDED = "Энэ санал аль хэдийн {status} төлөвтэй."
MSG_PROCESSING_TAKES_LONG = "Боловсруулалт удаж байна, түр хүлээнэ үү…"
MSG_SEND_PHOTO_HINT = "Баримтын зургаа шууд илгээнэ үү. Банкны хуулгыг Excel файлаар илгээнэ."
MSG_FILE_TOO_LARGE = "Файл хэт том байна (дээд хэмжээ {mb} МБ)."
MSG_UNSUPPORTED_FILE = "Энэ төрлийн файлыг дэмжихгүй. Зураг, PDF, Excel эсвэл CSV илгээнэ үү."

# --- menu and help -----------------------------------------------------------------------
MSG_MENU = (
	"🏠 Цэс\n"
	"📷 Зураг илгээх — баримт бүртгэх\n"
	"📎 Excel илгээх — банкны хуулга\n"
	"/данс — банкны тулгалт\n"
	"/хаалт — сарын хаалт\n"
	"/чанар — чанарын үзүүлэлт\n"
	"/бодлого — НББ-ийн бодлогын баримт бичиг\n"
	"/эхлэх — компанийн тохиргоо\n"
	"/тусламж — тусламж"
)
MSG_HELP = (
	"Нябо хэрхэн ажилладаг вэ?\n"
	"1. Баримтын зургаа илгээнэ — Нябо таньж, дансны саналыг картаар илгээнэ.\n"
	"2. Нягтлан (эсвэл эзэмшигч) Батлах товч дарна — бичилт ERPNext-д бүртгэгдэнэ.\n"
	"3. Банкны хуулгаа Excel-ээр илгээнэ — Нябо бичилттэй тулгаж, тулгагдаагүйг картаар асууна.\n"
	"4. Сарын эцэст /хаалт — үлдсэн ажил, гүйлгээ баланс, НӨАТ-ын тойм.\n"
	"Асуултаа энгийн текстээр бичиж болно."
)
MSG_ADMIN_HELP = (
	"Админ командууд:\n"
	"/link <нягтлан|эзэмшигч> <компани> — холболтын код олгох\n"
	"/whoami — Telegram ID харах\n"
	"/status — системийн төлөв"
)

# --- onboarding ------------------------------------------------------------------------
ONB_START = "Компанийн тохиргоог эхлүүлье. {company}"
ONB_ASK_VAT = "Танай компани НӨАТ төлөгч үү?"
ONB_VAT_YES_NOTE = "НӨАТ төлөгч: худалдан авалтын НӨАТ-ыг 1810 (татан суутгах НӨАТ) дансанд, борлуулалтын НӨАТ-ыг өглөгт бүртгэнэ."
ONB_VAT_NO_NOTE = "НӨАТ төлөгч бус (хялбаршуулсан 1%): НӨАТ-ын данс хөндөхгүй, худалдан авалтын НӨАТ өртөгт орно (Заавар 116)."
ONB_ASK_UNDER_400M = "2027 онд жилийн орлого 400 сая₮-с доош байх уу? (Хялбаршуулсан горимын босго)"
ONB_ASK_BANKS = "Компанийн дансуудыг сонгоно уу (хэд хэдийг сонгож болно):"
ONB_ASK_CURRENCIES = "{bank}: ямар валютын данстай вэ?"
ONB_ASK_ACCOUNT_NUMBER = "{bank} ({currency}) дансны дугаараа бичнэ үү (эсвэл Алгасах):"
ONB_ASK_INVENTORY = "Бараа материалын үлдэгдэл бий юу?"
ONB_INVENTORY_HOW = (
	"Бараа материалын жагсаалтаа илгээнэ үү:\n"
	"• Excel/CSV файл (баганууд: нэр, тоо, нэгж үнэ), эсвэл\n"
	"• мөр бүрт `нэр, тоо, үнэ` гэж бичнэ. Жишээ: `Принтерийн хор, 5, 45000`"
)
ONB_INVENTORY_PARSED = "📦 {count} бараа · нийт {total}₮. Зөв үү?"
ONB_INVENTORY_POSTED = "✅ Бараа материалын үлдэгдлийг бүртгэлээ: {docs}"
ONB_INVENTORY_PARSE_ERROR = "Жагсаалтыг уншиж чадсангүй: {error}"
ONB_ASK_ACCOUNTANT_NAME = "Нягтлан бодогчийн овог нэр:"
ONB_ASK_MICPA = "МНБИ-ийн зөвшөөрлийн дугаар (байхгүй бол Алгасах):"
ONB_DONE = (
	"✅ Тохиргоо дууслаа.\n"
	"Компани: {company}\nГорим: {regime}\nБанк: {banks}\nБараа материал: {inventory}\nНягтлан: {accountant}"
)
ONB_SUMMARY_REGIME_VAT = "НӨАТ төлөгч"
ONB_SUMMARY_REGIME_SIMPLIFIED = "НӨАТ төлөгч бус, хялбаршуулсан 1%"
ONB_BANK_LIST = "Khan Bank\nTDB\nGolomt Bank\nTrans Bank\nXacBank"
BANK_NAMES_MN = {
	"Khan Bank": "Хаан банк",
	"TDB": "Худалдаа хөгжлийн банк",
	"Golomt Bank": "Голомт банк",
	"Trans Bank": "Тээвэр хөгжлийн банк",
	"XacBank": "Хас банк",
}

# --- receipt cards -----------------------------------------------------------------------
CARD_RECEIPT_TITLE = "🧾 {seller} · {date} ({weekday})"
CARD_MONEY_LINE = "💵 {total}₮ · НӨАТ {vat}₮ ({rate}%, {treatment}) · {verification}"
CARD_MONEY_LINE_NO_VAT = "💵 {total}₮ · НӨАТ-гүй · {verification}"
CARD_ACCOUNT_LINE = "📒 {code} {account} · {reason}"
CARD_EXPLANATION_LINE = "«{explanation}»"
CARD_WARNING_LINE = "⚠️ {warning}"
CARD_PATTERN_LINE = "📜 {pattern}"
CARD_REASON_RULE = "дүрэм: {rule}"
CARD_REASON_MODEL = "санал"
CARD_REASON_HISTORY = "өмнөх бүртгэлээр"
VAT_TREATMENT_LABELS = {
	"withheld": "суутгана",
	"in_expense": "зардалд орно",
	"exempt": "чөлөөлөгдсөн",
	"zero": "тэг хувь",
	"none": "тооцохгүй",
}
VERIFICATION_SELLER_OK = "Худалдагч ✓ (ТТД)"
VERIFICATION_SELLER_NOT_FOUND = "Худалдагч бүртгэлд алга"
VERIFICATION_RECEIPT_UNCHECKED = "Баримт шалгагдаагүй"
VERIFICATION_QR_FOUND = "QR уншсан"
VERIFICATION_QR_MISSING = "QR олдсонгүй"
WARN_LOW_CONFIDENCE = "{field} тодорхойгүй ({confidence}%)"
WARN_QR_VISION_MISMATCH = "QR ба зургийн дүн зөрүүтэй"
WARN_NEW_SUPPLIER = "Шинэ харилцагч, нягтлан баталгаажуулна"
WARN_UNVERIFIED_RULE = "Дүрэм баталгаажаагүй (админ шалгана)"
WARN_SELLER_NOT_VAT_PAYER = "Худалдагч НӨАТ төлөгч бус, НӨАТ суутгахгүй"
WARN_DATE_IN_CLOSED_PERIOD = "Огноо хаагдсан сард байна"
WARN_INJECTION_SUSPECTED = "Баримт дээр гадны заавар илэрсэн, үл тоов"
FIELD_LABELS = {
	"total": "нийт дүн",
	"vat_amount": "НӨАТ",
	"date": "огноо",
	"seller_name": "худалдагч",
	"seller_tin": "ТТД",
	"lines": "мөрүүд",
}
MSG_CHOOSE_ACCOUNT = "Дансаа сонгоно уу (хамгийн их хэрэглэдэг 6):"
MSG_SEARCH_ACCOUNT = "Дансны нэр эсвэл кодоо бичнэ үү:"
MSG_ACCOUNT_NOT_FOUND = "Ийм данс олдсонгүй: {query}"
MSG_ACCOUNT_CHANGED = "Данс солигдлоо: {code} {account}"
MSG_APPROVED_POSTING = "Батлагдлаа, бүртгэж байна…"
MSG_ASK_REJECT_REASON = "Татгалзсан шалтгаанаа сонгоно уу:"
MSG_SUPPLIER_CREATED = "Шинэ харилцагч үүсгэлээ: {supplier}"
MSG_EXTRACTION_FAILED = "Баримтыг уншиж чадсангүй. Илүү тод зураг илгээнэ үү."

# --- bank statements and reconciliation --------------------------------------------------
MSG_STATEMENT_RECEIVED = "🏦 Хуулга хүлээн авлаа, уншиж байна…"
MSG_STATEMENT_IMPORTED = "🏦 {bank} · {count} гүйлгээ импортлолоо ({new} шинэ, {dup} давхардсан)\nАвтомат тулгасан: {matched} · Тулгаагүй: {unmatched}"
MSG_STATEMENT_LAYOUT_UNKNOWN = (
	"Энэ хуулгын форматыг танихгүй байна. Эхний мөрүүд:\n{preview}\nБаганы утгыг зааж өгнө үү."
)
MSG_STATEMENT_LAYOUT_ASK_COLUMN = "«{header}» багана юу вэ?"
MSG_STATEMENT_LAYOUT_SAVED = "Форматыг хадгаллаа ({layout}). Админ баталгаажуулсны дараа автоматаар ашиглана."
MSG_STATEMENT_LAYOUT_UNVERIFIED = "Энэ банкны формат баталгаажаагүй тул импорт хийхгүй. Админд мэдэгдлээ."
MSG_STATEMENT_NO_BANK_ACCOUNT = "{bank} банкны данс компанийн тохиргоонд алга. /эхлэх командаар нэмнэ үү."
COLUMN_ROLES = {
	"date": "Огноо",
	"description": "Гүйлгээний утга",
	"debit": "Зарлага (дебит)",
	"credit": "Орлого (кредит)",
	"amount": "Дүн (тэмдэгтэй)",
	"balance": "Үлдэгдэл",
	"reference": "Лавлах дугаар",
	"currency": "Валют",
	"ignore": "Ашиглахгүй",
}
CARD_BANK_LINE = "🏦 {bank} · {date} · {amount}₮ · «{description}»"
CARD_BANK_MATCHED = "🔗 Тулгав: {voucher}"
CARD_BANK_PROPOSAL = "📒 Санал: {code} {account} · {reason}"
MSG_BANK_FIND_ASK = "Аль баримттай тулгах вэ? Дугаар эсвэл харилцагчийн нэрийг бичнэ үү:"
MSG_BANK_FIND_CANDIDATES = "Тохирох баримтууд:"
MSG_BANK_FIND_NONE = "Тохирох баримт олдсонгүй."
MSG_BANK_MATCHED = "🔗 Тулгалаа: {voucher}"
MSG_BANK_LATER = "Дараа руу шилжүүллээ."
MSG_RECON_STATUS_HEADER = "🏦 Банкны тулгалт · {company}"
MSG_RECON_STATUS_LINE = (
	"{bank} {currency}: хуулга {statement}₮ · дэвтэр {ledger}₮ · зөрүү {diff}₮ · тулгаагүй {unmatched}"
)
MSG_RECON_NONE = "Банкны данс тохируулаагүй байна."

# --- month-end ---------------------------------------------------------------------------
MSG_CLOSE_USAGE = "Хэрэглээ: /хаалт 2026-08"
MSG_CLOSE_HEADER = "📅 Сарын хаалт · {company} · {period}"
MSG_CLOSE_OPEN_ITEMS = (
	"Хүлээгдэж буй:\n"
	"• Шийдвэрлээгүй санал: {proposals}\n"
	"• Тулгаагүй банкны гүйлгээ: {unmatched}\n"
	"• Худалдагч шалгагдаагүй баримт: {unverified_docs}\n"
	"• Баталгаажуулах харилцагч: {pending_suppliers}\n"
	"• Баталгаажаагүй дүрэм ашигласан: {unverified_rules}"
)
MSG_CLOSE_INVENTORY_COUNT = "• Жилийн эцсийн тооллого хийсэн эсэх (Хууль 12.2.1)"
MSG_CLOSE_TRIAL_BALANCE = "Гүйлгээ баланс: дебет {debit}₮ · кредит {credit}₮"
MSG_CLOSE_VAT_SUMMARY = "НӨАТ: борлуулалтын {output}₮ · татан суутгах {input}₮ · төлөх {net}₮"
MSG_CLOSE_SIMPLIFIED_SUMMARY = "Хялбаршуулсан горим: улирлын орлого {revenue}₮ · 1% татвар {tax}₮ ({quarter})"
MSG_CLOSE_CONFIRM = "Сарыг хаах уу? Хаасны дараа энэ сард бичилт хийх боломжгүй."
MSG_CLOSE_DONE = "🔒 {period} сар хаагдлаа ({name})."
MSG_CLOSE_BLOCKED = "Хаах боломжгүй: {reason}"
MSG_PERIOD_NOT_ENDED = "Сар дуусаагүй байна ({end_date} хүртэл)."
MSG_PERIOD_ALREADY_CLOSED = "Энэ сар аль хэдийн хаагдсан ({name})."
MSG_PERIOD_UNVERIFIED_RULES = (
	"Баталгаажаагүй дүрмээр хийсэн бичилт байна; админ дүрмийг баталгаажуулах шаардлагатай."
)
MSG_PERIOD_REOPENED = "🔓 {period} сарыг дахин нээлээ. Шалтгаан: {reason}"
MSG_POSTING_IN_CLOSED_PERIOD = "{date} огноо хаагдсан {period} сард байна. Бичилт хийх боломжгүй."

# --- compliance (Law on Accounting) -------------------------------------------------------
MSG_PRIMARY_DOCUMENT_REQUIRED = (
	"Анхан шатны баримтгүйгээр гүйлгээ бүртгэхийг хориглоно (Нягтлан бодох бүртгэлийн тухай хууль 13.7). "
	"Баримт хавсаргах эсвэл эх баримтыг холбоно уу."
)
MSG_NO_EDIT_AFTER_SUBMIT = (
	"Бүртгэгдсэн баримтыг засварлахгүй; залруулгыг буцаалтын бичилтээр хийнэ (Хууль 15.1)."
)
MSG_RETAINED_FILE_DELETE_BLOCKED = (
	"Энэ файл нягтлан бодох бүртгэлийн баримт тул {retain_until} хүртэл устгахгүй (Хууль 11.1)."
)
MSG_RETAINED_DOCUMENT_DELETE_BLOCKED = (
	"Нябо баримтыг устгахгүй; хадгалах хугацаа {retain_until} (Хууль 11.1)."
)
MSG_POSTED_DELETE_BLOCKED = "Бүртгэгдсэн баримтыг устгахгүй; залруулгыг буцаалтаар хийнэ (Хууль 15)."
MSG_EVENT_APPEND_ONLY = "Үйл явдлын бүртгэлийг өөрчлөх, устгах боломжгүй."
MSG_UNVERIFIED_RULE_BLOCKED = (
	"Баталгаажаагүй дүрэм ({rule}) ашиглан бодит бичилт хийх боломжгүй. "
	"Админ эрх зүйн эх сурвалжтай тулгаж «Баталгаажсан» гэж тэмдэглэнэ."
)
MSG_ENTRY_UNBALANCED = "Бичилт тэнцэхгүй байна: дебет {debit}₮, кредит {credit}₮."
MSG_ACCOUNT_IS_GROUP = "{account} нь бүлэг данс тул бичилт хийхгүй."
MSG_VAT_MATH_INCONSISTENT = "НӨАТ-ын дүн {vat}₮ нь {rate}% хувьтай тохирохгүй."
MSG_ACCOUNTANT_OF_RECORD_MISSING = "Нягтлан бодогчийн нэр тохируулаагүй. /эхлэх командаар оруулна уу."

# --- quality (/чанар) -------------------------------------------------------------------
MSG_QUALITY_HEADER = "📊 Чанар · {company} · сүүлийн {days} хоног"
MSG_QUALITY_BODY = (
	"Танилт (дүн/огноо/НӨАТ): {extraction}%\n"
	"Данс өөрчлөлгүй батлагдсан: {classification}%\n"
	"НӨАТ-ын бүртгэл зөв: {vat}%\n"
	"Банк автомат тулгалт: {automatch}% (буруу тулгалт {false_match}%)\n"
	"Дундаж хугацаа: {latency}с · Нэг баримтын зардал: ${cost}"
)
MSG_QUALITY_NO_DATA = "Одоогоор хангалттай өгөгдөл алга."

# --- policy document (/бодлого) ---------------------------------------------------------
MSG_POLICY_GENERATED = "📄 НББ-ийн бодлогын баримт бичгийн төслийг илгээлээ. [ ] хэсгүүдийг нягтлан бөглөнө."
POLICY_TITLE = "НЯГТЛАН БОДОХ БҮРТГЭЛИЙН БОДЛОГЫН БАРИМТ БИЧИГ"
POLICY_DRAFT_WATERMARK = "ТӨСӨЛ"

# --- questions ---------------------------------------------------------------------------
MSG_QUESTION_THINKING = "Шалгаж байна…"
MSG_QUESTION_CANNOT = "Энэ асуултад дэвтрээс хариулж чадсангүй."
MSG_ESCALATED = "Асуултыг админд дамжууллаа."
MSG_BALANCE_ANSWER = "{account}: {date} өдрийн үлдэгдэл {balance}₮"
MSG_SPEND_ANSWER = "{period}: {account} {amount}₮"
MSG_LAST_ENTRIES_ANSWER = "{supplier} сүүлийн бүртгэлүүд:\n{entries}"

# --- reports (labels; report names stay ASCII) --------------------------------------------
REPORT_GENERAL_JOURNAL = "Ерөнхий журнал"
REPORT_CASH_JOURNAL = "Мөнгөн гүйлгээний журнал"
REPORT_GENERAL_LEDGER = "Ерөнхий дэвтэр"
REPORT_TRIAL_BALANCE = "Гүйлгээ баланс"
REPORT_VAT_SUMMARY = "НӨАТ-ын тойм"
REPORT_SIMPLIFIED_SUMMARY = "Хялбаршуулсан горимын тойм (1%)"
REPORT_BALANCE_SHEET = "Санхүүгийн байдлын тайлан"
REPORT_INCOME_STATEMENT = "Орлогын дэлгэрэнгүй тайлан"
REPORT_EQUITY_STATEMENT = "Өмчийн өөрчлөлтийн тайлан"
REPORT_CASH_FLOW = "Мөнгөн гүйлгээний тайлан"
REPORT_PROVISIONAL = "ТҮР ЗАГВАР"
COL_DATE = "Огноо"
COL_VOUCHER_TYPE = "Баримтын төрөл"
COL_VOUCHER_NO = "Баримтын дугаар"
COL_DESCRIPTION = "Гүйлгээний утга"
COL_ACCOUNT = "Данс"
COL_ACCOUNT_CODE = "Дансны код"
COL_DEBIT = "Дебет"
COL_CREDIT = "Кредит"
COL_BALANCE = "Үлдэгдэл"
COL_PARTY = "Харилцагч"
COL_PREPARED_BY = "Бэлтгэсэн"
COL_APPROVED_BY = "Баталсан"
COL_PRIMARY_DOCUMENT = "Анхан шатны баримт"
COL_OPENING = "Эхний үлдэгдэл"
COL_CLOSING = "Эцсийн үлдэгдэл"
COL_AMOUNT = "Дүн"
COL_CURRENCY = "Валют"
LBL_COMPANY = "Байгууллага"
LBL_PERIOD = "Тайлант үе"
LBL_CHIEF_ACCOUNTANT = "Ерөнхий нягтлан бодогч"
LBL_DIRECTOR = "Захирал"
LBL_SIGNATURE = "Гарын үсэг"
LBL_TOTAL = "Нийт"

# --- primary document print forms ------------------------------------------------------------
# Names per Сангийн сайдын 2017 оны 347 дугаар тушаал (primary document forms).
FORM_CASH_RECEIPT_VOUCHER = "Бэлэн мөнгөний орлогын баримт (НХМаягт МХ-1)"
FORM_CASH_PAYMENT_VOUCHER = "Бэлэн мөнгөний зарлагын баримт (НХМаягт МХ-2)"
FORM_INVOICE = "Нэхэмжлэх (НХМаягт ТМ-1)"
FORM_PAYMENT_RECEIPT = "Төлбөрийн баримт (НХМаягт ТМ-5)"
FORM_PAYMENT_ORDER_LIST = "Төлбөрийн даалгаврын жагсаалт (банкны маягт)"
FORM_PROVISIONAL_WATERMARK = "ТҮР МАЯГТ — Сангийн яамны баталсан маягтын дагуу шалгана"
FORM_SOURCE_ORDER_347 = "Сангийн сайдын 2017 оны 347 дугаар тушаал"
FORM_SOURCE_ORDER_100 = "Сангийн сайдын 2018 оны 100 дугаар тушаал"
JOURNAL_KEPT_BY = "Хөтөлсөн нягтлан бодогч"
JOURNAL_CHECKED_BY = "Хянасан ерөнхий (ахлах) нягтлан бодогч"
JOURNAL_TYPE_GENERAL = "ЕЖ"
JOURNAL_TYPE_CASH_MNT = "МГ-1"
JOURNAL_TYPE_CASH_FX = "МГ-2"
COL_DOC_DATE = "Баримтын сар, өдөр"
COL_DOC_NO = "Баримтын дугаар"
COL_ACCOUNT_NAME_CODE = "Дансны нэр, код"
COL_RATE = "Ханш"
COL_AMOUNT_FX = "Гүйлгээний дүн гадаад валютаар"
COL_AMOUNT_MNT = "Гүйлгээний дүн төгрөгөөр"
COL_FX_DIFF = "Ханшийн зөрүүний ашиг/алдагдал"

# --- readiness checklist (certification) ----------------------------------------------------
READINESS_TITLE = "Нягтлан бодох бүртгэлийн программ хангамжийн бэлэн байдал"
READINESS_PASS = "ТЭНЦСЭН"
READINESS_FAIL = "ДУТУУ"
READINESS_ITEMS = {
	"general_journal": "Ерөнхий журнал",
	"cash_journal": "Мөнгөн гүйлгээний журнал",
	"general_ledger": "Ерөнхий дэвтэр, дэлгэрэнгүй дэвтэр",
	"trial_balance": "Гүйлгээ баланс",
	"statements": "Санхүүгийн 4 тайлан + тодруулга",
	"primary_forms": "Анхан шатны баримтын маягтууд",
	"audit_trail": "Хяналтын мөр (өөрчлөлтийн түүх, үйл явдлын бүртгэл)",
	"retention": "10 жил хадгалалт, устгалтын хамгаалалт",
	"corrections": "Залруулга буцаалтаар, шалтгаан, баталсан этгээд",
	"period_lock": "Тайлант үеийн хаалт",
	"primary_document_required": "Анхан шатны баримтгүй бичилт хориглосон",
	"e_signature": "Цахим гарын үсэг",
	"accountant_of_record": "Нягтлан бодогчийн нэр, зөвшөөрөл",
	"policy_document": "НББ-ийн бодлогын баримт бичиг",
	"rules_verified": "Татварын дүрэм эх сурвалжтай, баталгаажсан",
}

# --- accounting vocabulary (glossary) --------------------------------------------------------
VAT = "НӨАТ"
VAT_PAYER = "НӨАТ төлөгч"
VAT_NON_PAYER = "НӨАТ төлөгч бус"
VAT_WITHHELD = "суутгана"
VAT_IN_EXPENSE = "зардалд орно"
EBARIMT = "И-баримт"
TRIAL_BALANCE = "Гүйлгээ баланс"
CHART_OF_ACCOUNTS = "Дансны төлөвлөгөө"
ACCOUNT = "Данс"
SUPPLIER = "Харилцагч"
AMOUNT = "Дүн"
DATE = "Огноо"
RULE = "дүрэм"
EXPLANATION = "Тайлбар"
DEBIT_SHORT = "Дт"
CREDIT_SHORT = "Кт"
WEEKDAYS_SHORT = ["Да", "Мя", "Лх", "Пү", "Ба", "Бя", "Ня"]
MONTHS = [
	"1-р сар",
	"2-р сар",
	"3-р сар",
	"4-р сар",
	"5-р сар",
	"6-р сар",
	"7-р сар",
	"8-р сар",
	"9-р сар",
	"10-р сар",
	"11-р сар",
	"12-р сар",
]

# --- custom field labels on ERPNext documents ------------------------------------------------
LBL_SECTION_EBARIMT = "Нябо · И-баримт"
LBL_SECTION_AUDIT = "Нябо · Хяналтын мөр"
LBL_EBARIMT_RECEIPT_ID = "И-баримтын дугаар (ДДТД)"
LBL_EBARIMT_LOTTERY_NO = "Сугалааны дугаар"
LBL_EBARIMT_DATETIME = "И-баримтын огноо, цаг"
LBL_EBARIMT_VERIFIED = "Худалдагч бүртгэлд шалгагдсан"
LBL_EBARIMT_QR_DATA = "QR өгөгдөл"
LBL_EBARIMT_CUSTOMER_TIN = "Худалдан авагчийн ТТД / РД"
LBL_SOURCE_DOCUMENT = "Эх баримт (Нябо)"
LBL_NYABO_PROPOSAL = "Нябо санал"
LBL_NYABO_EXPLANATION = "Тайлбар (Нябо)"
LBL_NYABO_PROMPT_VERSION = "Промптын хувилбар"
LBL_NYABO_CORRECTION_REASON = "Залруулгын шалтгаан"
LBL_NYABO_CORRECTS = "Залруулж буй баримт"
LBL_NYABO_APPROVED_BY = "Баталсан (Нябо)"
LBL_NYABO_PRIMARY_DOCUMENT_REF = "Анхан шатны баримтын лавлагаа"
LBL_NYABO_RETAIN_UNTIL = "Хадгалах хугацаа (хүртэл)"
LBL_REGISTER_NO = "Регистрийн дугаар"
LBL_TIN = "ТТД (TIN)"
LBL_EBARIMT_VAT_PAYER = "НӨАТ төлөгч (ebarimt бүртгэл)"
LBL_EBARIMT_CHECKED_AT = "ebarimt бүртгэлд шалгасан огноо"
LBL_SUPPLIER_PENDING = "Нягтлан баталгаажуулах"

# --- tax template titles (used by nyabo_mn.setup.taxes) ----------------------------------------
TAX_SALES_VAT_10 = "НӨАТ 10%"
TAX_PURCHASE_VAT_10 = "Татан суутгах НӨАТ 10%"
TAX_ITEM_EXEMPT = "НӨАТ-аас чөлөөлөгдсөн"
TAX_ITEM_ZERO = "Тэг хувийн НӨАТ"

# --- agent (classification fallbacks and question answering; code writes these, never the model) --
AGENT_REASON_CODE_NOT_IN_CHART = "Санал болгосон данс төлөвлөгөөнд байхгүй тул үндсэн зардлын дансыг сонгов."
AGENT_REASON_VAT_NOT_PAYER = "Компани НӨАТ төлөгч бус тул НӨАТ зардалд орно."
AGENT_REASON_UNAVAILABLE = "Тайлбар боловсруулж чадсангүй; нягтлан шалгана уу."
AGENT_ANSWER_INJECTION_REFUSED = (
	"Уучлаарай, энэ асуултад хариулах боломжгүй. Нягтлан эсвэл админд хандана уу."
)
AGENT_ANSWER_TOOL_ERROR = "Дэвтрээс мэдээлэл авахад алдаа гарлаа. Дахин оролдоно уу."

# --- pipeline, posting, supplier, ebarimt (receipt flow on the Frappe side) ------------------------
SUPPLIER_GROUP_DEFAULT = "Нийлүүлэгч"
SUPPLIER_NAME_UNKNOWN = "Тодорхойгүй худалдагч"
MSG_RECEIPT_AMOUNT_MISSING = "Баримтын нийт дүнг уншиж чадсангүй; нягтлан гараар шалгана уу."
MSG_DATE_DEFAULTED_TODAY = "Огноо уншигдаагүй тул өнөөдрийн огноог ашиглав"
WARN_ENTRY_INVALID = "Бичилт шалгалтад тэнцсэнгүй: {problem}"
WARN_ACCOUNT_ROLE_MISSING = "«{role}» үүрэгтэй данс энэ дансны төлөвлөгөөнд алга; нягтлан данс сонгоно"
MSG_PROPOSAL_NOT_POSTABLE = "Санал {status} төлөвтэй тул бүртгэх боломжгүй."
MSG_SUPPLIER_REQUIRED_FOR_INVOICE = "Худалдан авалтын нэхэмжлэхэд харилцагч заавал хэрэгтэй."
MSG_ACCOUNT_CODE_INVALID = "{code} код дансны төлөвлөгөөний бичилт хийх данс биш."
MSG_CORRECTION_ORIGINAL_NOT_NYABO = "{name} баримт Нябо саналгүй тул залруулгын санал үүсгэх боломжгүй."
MSG_RULE_CONFIRMED = "Дүрэм {rule} идэвхжлээ."
MSG_RULE_LEARNED = "Хоёр ижил залруулгаас шинэ дүрэм үүсгэлээ; нягтлан баталгаажуулна: {rule}"
EXPL_RULE_APPLIED = "«{rule}» дүрмээр {code} данс сонгов."
EXPL_CORRECTION_PREFIX = "Залруулга ({reason}): "
FAQ_NOT_FOUND = "Энэ асуултад тохирох тайлбар олдсонгүй."
LAST_ENTRY_LINE = "{date} · {doctype} {name} · {amount}₮"
LAST_ENTRIES_NONE = "{supplier} харилцагчийн бүртгэл олдсонгүй."
UNMATCHED_ANSWER = "Тулгагдаагүй банкны гүйлгээ: {count}"
SUPPLIER_NOT_FOUND_ANSWER = "{supplier} нэртэй харилцагч олдсонгүй."

# --- explanation templates (LLM fills only the bracketed part) -----------------------------------
EXPL_EXPENSE = "{what} тул {debit_code} дебетлэж, {credit_name} кредитлэв."
EXPL_SUFFIX_CITATION = " — {instrument}, {section}"
EXPL_NO_VAT_NON_PAYER = "Компани НӨАТ төлөгч бус тул НӨАТ өртөгт орлоо."
EXPL_VAT_WITHHELD = "И-баримтын НӨАТ {vat}₮-г татан суутгах НӨАТ-д бүртгэв."

# --- core (money, dates, validate, rules_engine, statements, matching) --------------------------
PERIOD_LABEL = "{year} оны {month}"
QUARTER_LABEL = "{year} оны {quarter}-р улирал"
CITATION_SECTION_PENDING = "заалт тодруулах"
MSG_ENTRY_TOO_FEW_LINES = "Бичилт дор хаяж хоёр мөртэй байх ёстой."
MSG_ENTRY_ZERO_LINE = "{account} дансны мөрийн дүн тэг байна."
MSG_ENTRY_LINE_BOTH_SIDES = "{account} дансны мөр дебет, кредит хоёуланд нь дүнтэй байна."
MSG_ENTRY_NEGATIVE_AMOUNT = "{account} дансны мөрийн дүн сөрөг байна."
MSG_ACCOUNT_UNKNOWN = "{account} данс дансны төлөвлөгөөнд алга."
MSG_RULE_MISSING = "«{key}» дүрэм {date} огноонд тодорхойлогдоогүй байна; нягтлан шалгана уу."
MSG_RULE_PENDING = "«{key}» дүрэм {date} огноонд хараахан баталгаажаагүй (хүлээгдэж буй) тул тооцоолохгүй; нягтлан шалгана уу."
MSG_RULE_AMBIGUOUS = "«{key}» дүрэм {date} огноонд давхардсан байна; админ шалгана уу."
MSG_REGIME_MISSING = (
	"{date} огноонд компанийн татварын горим тохируулаагүй байна. /эхлэх командаар тохируулна уу."
)
MSG_PATTERN_NOT_FOUND = "{document} баримтад тохирох бичилтийн загвар олдсонгүй."
MSG_PATTERN_AMOUNT_MISSING = "«{pattern}» загварын «{amount_kind}» дүн өгөгдөөгүй байна."
MSG_MONEY_UNPARSEABLE = "«{text}» дүнг уншиж чадсангүй."
MATCH_REASON_EXACT = "дүн таарч, огноо {days} хоногийн зөрүүтэй"
MATCH_REASON_NAME = "харилцагчийн нэр таарсан ({similarity}%)"
MATCH_REASON_REFERENCE = "лавлах дугаар таарсан"
MATCH_REASON_FEE = "банкны хураамж"
MATCH_REASON_TRANSFER = "өөрийн дансууд хоорондын шилжүүлэг"
MATCH_REASON_NONE = "тохирох баримт олдсонгүй"
MATCH_REASON_AMBIGUOUS = "хэд хэдэн баримт адилхан тохирч байна; нягтлан сонгоно"
MATCH_REASON_LOW_SCORE = "хамгийн ойрын баримт {score}% тохирч байна (босго {threshold}%)"
