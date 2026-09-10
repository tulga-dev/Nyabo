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
BTN_RECORD_PAYMENT = "Төлбөр бүртгэх"
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

# --- question follow-ups (the next read the accountant would ask for; §5.7) -------------
# The arrows carry the direction so the month name alone can be the label; a Telegram
# button is one short line and «Өмнөх сарын дүнг харах» wraps on a narrow phone.
BTN_Q_PREV_PERIOD = "← {period}"
BTN_Q_NEXT_PERIOD = "{period} →"
BTN_Q_EXPLAIN = "Юунаас бүрдэв?"
# The same read under a *balance*, where «Юунаас бүрдэв?» would be a promise the query cannot
# keep: a balance as of a date is not the sum of one month's entries. The month it will show is
# named instead, and it leads with the noun so the two buttons on that card do not both start
# with a date.
BTN_Q_PERIOD_ENTRIES = "Бичилтүүд · {period}"
BTN_Q_ACCOUNT_TOTAL = "Сарын нийт дүн"
BTN_Q_SUPPLIER_ENTRIES = "Сүүлийн бичилтүүд"
BTN_Q_SUPPLIER_TOTAL = "Харилцагчийн нийт дүн"
BTN_Q_TOP_ACCOUNTS = "Хамгийн их зардал"
BTN_Q_UNMATCHED_LINES = "Аль гүйлгээ вэ?"
BTN_Q_UNMATCHED_COUNT = "Хэд байна?"
BTN_Q_ASK_ADMIN = "Админаас асуух"

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
# {period} is always a period label from core.dates.period_label ("2026 оны 8-р сар"),
# which already ends in «сар» — no message may add the word again (UX-04).
MSG_CORRECTION_PERIOD_CLOSED = "⚠️ Анхны бичилт хамаарах {period} хаагдсан тул буцаалтыг өнөөдрийн огноогоор бүртгэлээ. Нягтлан анхаарна уу."
MSG_CORRECTION_NEW_ENTRY_HINT = "Одоо зөв утгаар шинэ бичилтийн саналыг илгээж байна."
MSG_CORRECTION_ALREADY_REVERSED = "Энэ бичилт аль хэдийн буцаагдсан байна."
MSG_CORRECTION_IS_REVERSAL = (
	"Энэ нь өөрөө буцаалтын бичилт тул дахин буцаахгүй; шаардлагатай бол шинэ бичилт хийнэ (Хууль 15.1)."
)

# --- generic messages ------------------------------------------------------------------
MSG_WELCOME = "Сайн байна уу! Би Нябо — таны нягтлангийн туслах. Баримтын зургаа илгээвэл бүртгэлийн саналыг танд илгээнэ."
MSG_NOT_LINKED = (
	"Таны Telegram хаяг Нябо-д холбогдоогүй байна. Админаас 6 оронтой холболтын код авч энд бичнэ үү."
)
MSG_LINKED = "✅ Холбогдлоо. Үүрэг: {role}. Компани: {company}."
MSG_LINK_CODE_INVALID = "Код буруу эсвэл хугацаа нь дууссан байна."
MSG_LINK_CODE_TOO_MANY = (
	"Буруу код хэт олон удаа оруулсан тул түр хаалаа. {minutes} минутын дараа дахин оролдоно уу."
)
MSG_LINK_CODE_ISSUED = "Холболтын код: {code}\nҮүрэг: {role} · Компани: {company}\nХүчинтэй: {minutes} минут. Хэрэглэгч энэ кодыг Нябо-д бичнэ."
MSG_YOUR_TELEGRAM_ID = "Таны Telegram ID: {telegram_id}"
MSG_DUPLICATE_DOCUMENT = "Энэ баримт өмнө нь илгээгдсэн."
MSG_RECEIVED_PROCESSING = "🧾 Хүлээн авлаа, шалгаж байна…"
MSG_POSTED = "✅ Бүртгэлээ: {doc_name}"
MSG_REJECTED = "❌ Татгалзлаа: {reason}"
MSG_ERROR_GENERIC = "Уучлаарай, алдаа гарлаа. Дахин оролдоно уу."
# UX-13: the old wording was «Уучлаарай, алдаа гарлаа. Админд мэдэгдлээ.», and the founder
# read «Админд мэдэгдлээ» as "an administrator has to approve your entry". It must say a
# technical fault happened, promise no approval step, and name the way out.
#
# Two of them, because only one caller can keep both promises. ``telegram.router`` draws the
# [Цэс] button beside the text and calls ``notify_admins``; everything else (the failed
# receipt card, the statement worker) has no keyboard and sends nothing, so it names /меню as
# a command to type and does not claim a notification that was never sent.
MSG_ERROR_ADMIN_NOTIFIED = (
	"Уучлаарай, техникийн алдаа гарлаа. Энэ нь таны бичилтийг хэн нэгэн зөвшөөрөх гэж "
	"хүлээж байна гэсэн үг биш — алдааг Нябо-г хөгжүүлэгч рүү илгээлээ, шалгаж засна. "
	"Та дахин оролдож болно, эсвэл доорх «Цэс» товч (/меню) дээр дарж эхнээс нь эхэлнэ үү."
)
MSG_ERROR_NO_BUTTON = (
	"Уучлаарай, техникийн алдаа гарлаа. Энэ нь таны бичилтийг хэн нэгэн зөвшөөрөх гэж "
	"хүлээж байна гэсэн үг биш. Та дахин оролдож болно, эсвэл «/меню» гэж бичээд "
	"эхнээс нь эхэлнэ үү."
)
MSG_ACCOUNTANT_ONLY = "Энэ саналыг зөвхөн нягтлан батлах боломжтой (⚠️ тэмдэглэгээтэй)."
MSG_NO_PERMISSION = "Танд энэ үйлдлийг хийх эрх байхгүй."
MSG_UNKNOWN_COMMAND = "Ойлгосонгүй. /тусламж гэж бичнэ үү."
MSG_CHOOSE_COMPANY = "Компаниа сонгоно уу:"
MSG_ACTIVE_COMPANY = "Идэвхтэй компани: {company}"
# On an intake path (a photo or a statement arrives before any company is linked). Linking a
# person to a company really is an admin action — `/link` issues the code — so the sentence
# names that person and the command they run, instead of «ask an admin» and a dead end.
MSG_NO_COMPANY = (
	"Танд холбогдсон компани алга тул баримт бүртгэх боломжгүй. Нябог тохируулсан хүнээс "
	"«/link нягтлан <компанийн нэр>» командаар холболтын код авч, энд бичнэ үү."
)
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
	"/компани — идэвхтэй компани солих\n"
	"/эхлэх — компанийн тохиргоо\n"
	"/дүрэм — баталгаажаагүй дүрмийг харах, хүлээн зөвшөөрөх\n"
	"/меню (эсвэл /цэс) — энэ цэс\n"
	"/цуцлах — эхлүүлсэн ажлыг болих\n"
	"/тусламж — тусламж\n"
	"Telegram-ын команд цэс (☰) кирилл нэр дэмждэггүй тул тэнд латинаар харагдана."
)
# Descriptions for Telegram's own command menu (setMyCommands). The command names must be
# Latin (see nyabo_mn.telegram.commands); the description the user reads is Mongolian and
# is capped by Telegram at 256 characters.
BOT_COMMAND_DESCRIPTIONS = {
	"start": "Эхлэх / холбогдох",
	"menu": "Цэс",
	"help": "Тусламж",
	"bank": "Банкны тулгалт (/данс)",
	"close": "Сарын хаалт (/хаалт)",
	"quality": "Чанарын үзүүлэлт (/чанар)",
	"policy": "НББ-ийн бодлогын баримт бичиг (/бодлого)",
	"company": "Идэвхтэй компани солих (/компани)",
	"setup": "Компанийн тохиргоо (/эхлэх)",
	"cancel": "Эхлүүлсэн ажлыг цуцлах (/цуцлах)",
	"rules": "Баталгаажаагүй дүрэм (/дүрэм)",
}
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
	"/status — системийн төлөв\n"
	"/дүрэм (/rules) — баталгаажаагүй дүрмийг харах, сайтын хэмжээнд баталгаажуулах"
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
# Принцип 5: once the opening stock is in the ledger the Тийм/Үгүй question can no longer be
# re-answered — «Үгүй» would tell the summary the company holds no stock while the opening
# entry stands. Only a reversal takes it back, and that is a separate, deliberate job.
ONB_INVENTORY_ALREADY_POSTED = (
	"Бараа материалын эхний үлдэгдэл аль хэдийн бүртгэгдсэн тул энэ хариултыг өөрчлөх "
	"боломжгүй. Буруу бол зөвхөн буцаалт (сторно) хийж залруулна. Тохиргоог үргэлжлүүлье."
)
# SEC-09: the reader never sees a raw exception. {error} takes a Mongolian sentence Nyabo
# itself wrote; a parser or library message goes to the log instead (ONB_INVENTORY_PARSE_FAILED).
ONB_INVENTORY_PARSE_ERROR = "Жагсаалтыг уншиж чадсангүй: {error}"
ONB_INVENTORY_PARSE_FAILED = (
	"Жагсаалтыг уншиж чадсангүй. Excel/CSV файлын баганууд (нэр, тоо, нэгж үнэ) эсвэл "
	"мөр бүрт `нэр, тоо, үнэ` хэлбэртэй эсэхийг шалгаад дахин илгээнэ үү."
)
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
# The money line and the verification line are separate so neither wraps on a phone
# (UX-10: a card line stays under ~60 characters).
CARD_MONEY_LINE = "💵 {total}₮ · НӨАТ {vat}₮ ({rate}%, {treatment})"
CARD_MONEY_LINE_TREATMENT = "💵 {total}₮ · НӨАТ {treatment}"
CARD_MONEY_LINE_NO_VAT = "💵 {total}₮ · НӨАТ-гүй"
CARD_VERIFICATION_LINE = "🔎 {verification}"
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
WARN_UNVERIFIED_RULE = "Дүрэм баталгаажаагүй (нягтлан хүлээн зөвшөөрнө)"
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
	"Энэ хуулгын форматыг танихгүй байна. Эхний мөрүүд:\n{preview}\nБаганын утгыг зааж өгнө үү."
)
MSG_STATEMENT_LAYOUT_ASK_COLUMN = "«{header}» багана юу вэ?"
# The accountant who read the statement and mapped its columns is the person who knows whether
# the mapping is right, so they confirm it for their own company (DECISIONS ACC-02) — nobody is
# asked to wait for an admin who never saw the file.
MSG_STATEMENT_LAYOUT_SAVED = (
	"Форматыг хадгаллаа ({layout}). Доорх зураглалыг шалгаад баталгаажуулснаар "
	"энэ банкны хуулга автоматаар уншигдана."
)
MSG_STATEMENT_LAYOUT_UNVERIFIED = (
	"Энэ банкны форматыг өмнө нь зурагласан ч баталгаажуулаагүй тул импорт хийсэнгүй ({layout}). "
	"Доорх зураглалыг шалгаад баталгаажуулна уу."
)
MSG_STATEMENT_LAYOUT_CONFIRM_ASK = (
	"«{layout}» формат {company}-ийн хуулгыг зөв уншиж байна уу?\n{mapping}\n"
	"Баталгаажуулбал хэн, хэзээ баталгаажуулсан нь бүртгэгдэнэ."
)
MSG_STATEMENT_LAYOUT_ACCEPTED = (
	"✅ «{layout}» форматыг баталгаажууллаа. Дараагийн хуулгыг дахин илгээхэд автоматаар уншина."
)
MSG_STATEMENT_LAYOUT_ACCEPTED_RESEND = "Энэ хуулгаа дахин илгээнэ үү — одоо уншигдана."
# The usual case: the file that was refused is already stored, so it is re-read on the spot.
# Asking for it again would meet the sha256 dedup and be answered «this document is already here».
MSG_STATEMENT_LAYOUT_REIMPORTING = "Хүлээгдэж байсан хуулгыг дахин уншиж байна…"
MSG_STATEMENT_LAYOUT_LEFT = "Форматыг баталгаажуулаагүй үлдээлээ; энэ форматаар хуулга уншихгүй."
MSG_STATEMENT_LAYOUT_ACCOUNTANT_ONLY = "Хуулгын форматыг зөвхөн тухайн компанийн нягтлан баталгаажуулна."
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
MSG_CLOSE_DONE = "🔒 {period} хаагдлаа ({name})."
MSG_CLOSE_BLOCKED = "Хаах боломжгүй: {reason}"
MSG_PERIOD_NOT_ENDED = "Сар дуусаагүй байна ({end_date} хүртэл)."
MSG_PERIOD_ALREADY_CLOSED = "Энэ сар аль хэдийн хаагдсан ({name})."
MSG_PERIOD_UNVERIFIED_RULES = (
	"Баталгаажаагүй дүрмээр хийсэн бичилт байна. /дүрэм командаар тэдгээр дүрмийг үзэж, "
	"компанидаа хамаарна гэж хүлээн зөвшөөрсний дараа сарыг хаана."
)
MSG_PERIOD_REOPENED = "🔓 {period} үеийг дахин нээлээ. Шалтгаан: {reason}"
MSG_PERIOD_DELETE_BLOCKED = "Нябо-гоор хаасан тайлант үеийг ({name}) устгахгүй; шаардлагатай бол дахин нээнэ."
# WHY no template ever writes «{placeholder}-<суффикс>»: the correct case ending depends on the
# last sound of the word the placeholder renders, and a placeholder renders a *formatted* value —
# a month label («2027 оны 1-р сар» wants «сард», not «сар-д»), a numeral («5» wants «-аас», «2»
# wants «-оос»), an ISO date («…-05» wants «-нд», «…-08» wants «-д»). One spelling in the source
# can only ever be right for some of the values, so the suffix attaches to a fixed noun the
# sentence supplies instead («тайлант үед ({period})», «{date} өдрийн»), or the label is set off
# with a colon or brackets. The one exception is a proper name or an abbreviation — «ХХК-ийн» IS
# the written form — which is why «{company}-ийн» stays. tests/unit/test_i18n_no_hardcoded_mongolian.py
# sweeps this module for the shape.
MSG_POSTING_IN_CLOSED_PERIOD = (
	"{date} огноо хаагдсан тайлант үед ({period}) багтаж байна. Бичилт хийх боломжгүй."
)
MSG_CLOSE_SIMPLIFIED_MONTH_LINE = "• {month}: орлого {revenue}₮"
MSG_SIMPLIFIED_NOT_ELIGIBLE_VAT = (
	"Хялбаршуулсан 1%-ийн горим НӨАТ-ын суутган төлөгчид хамаарахгүй (ААНОАТ-ын тухай хууль 29.3.1); "
	"улирлын тооцоог хийхгүй."
)
WARN_SIMPLIFIED_OVER_THRESHOLD = (
	"⚠️ Өмнөх жилийн бүртгэлийн орлого {revenue}₮ нь хялбаршуулсан горимын босго {threshold}₮-өөс давсан "
	"байна (ААНОАТ 29.1); горимд хамаарах эсэхийг нягтлан баталгаажуулна уу."
)
# The 1% base is operating (sales) revenue only — ААНОАТ 29.1 with 29.9. What was left out
# is named, never dropped in silence.
WARN_SIMPLIFIED_NON_OPERATING_EXCLUDED = (
	"⚠️ Үндсэн бус үйл ажиллагааны орлого, олз {amount}₮-г 1%-ийн татварын суурьт оруулаагүй "
	"(ААНОАТ 29.1, 29.9); нягтлан бодогч шалгаж баталгаажуулна уу."
)
WARN_SIMPLIFIED_REVENUE_ROLES_UNKNOWN = (
	"⚠️ Борлуулалтын орлогын дансдыг тодорхойлж чадсангүй тул орлогын бүх данс 1%-ийн суурьт орлоо "
	"(ААНОАТ 29.1); нягтлан бодогч суурийг шалгана уу."
)
MSG_CLOSE_TRIAL_BALANCE_SOURCE_FALLBACK = (
	"Гүйлгээ балансыг ерөнхий дэвтрийн бичилтээс шууд тооцов (ERPNext тайлан ашиглах боломжгүй)."
)
MSG_QUARTER_USAGE = "Улирлыг 2026-Q3 хэлбэрээр бичнэ үү."

# --- compliance (Law on Accounting) -------------------------------------------------------
MSG_PRIMARY_DOCUMENT_REQUIRED = (
	"Анхан шатны баримтгүйгээр гүйлгээ бүртгэхийг хориглоно (Нягтлан бодох бүртгэлийн тухай хууль 13.7). "
	"Баримт хавсаргах эсвэл эх баримтыг холбоно уу."
)
MSG_PRIMARY_DOCUMENT_SYSTEM_GENERATED = "Системээс үүсгэсэн бичилт: {source} (ERPNext-ийн тооцоо)"
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
# The accountant is the professional who signs these books, so the refusal names what THEY can
# do now (DECISIONS ACC-01) instead of sending them to wait for an admin. The wording stays true
# wherever the guard raises — a report, a desk call — because reading the rule and accepting it
# for one's own company is the step in every one of those places.
MSG_UNVERIFIED_RULE_BLOCKED = (
	"Баталгаажаагүй дүрэм ({rule}) ашиглан бодит бичилт хийх боломжгүй. "
	"Нягтлан дүрмийн агуулгыг уншиж, өөрийн компанийн бүртгэлд хамаарна гэж "
	"хүлээн зөвшөөрснөөр бичилт үргэлжилнэ."
)
MSG_ENTRY_UNBALANCED = "Бичилт тэнцэхгүй байна: дебет {debit}₮, кредит {credit}₮."
MSG_ACCOUNT_IS_GROUP = "{account} нь бүлэг данс тул бичилт хийхгүй."
MSG_VAT_MATH_INCONSISTENT = "НӨАТ-ын дүн {vat}₮ нь {rate}% хувьтай тохирохгүй."
MSG_ACCOUNTANT_OF_RECORD_MISSING = "Нягтлан бодогчийн нэр тохируулаагүй. /эхлэх командаар оруулна уу."
MSG_EXPLANATION_TOO_LONG = "Тайлбар {max} тэмдэгтээс урт байна ({length})."
MSG_PROPOSAL_MISSING_ON_DOCUMENT = "Холбосон Нябо санал ({proposal}) олдсонгүй."
MSG_PROPOSAL_COMPANY_MISMATCH = (
	"Нябо санал ({proposal}) өөр компанийнх ({proposal_company}); баримт {company}-ийнх."
)
MSG_CORRECTION_REASON_UNKNOWN = "Залруулгын шалтгааны код танигдсангүй: {code}."
MSG_CORRECTION_NOT_SUBMITTED = "Зөвхөн бүртгэгдсэн (батлагдсан) баримтыг буцаах боломжтой: {name}."
MSG_CORRECTION_UNSUPPORTED_DOCTYPE = "{doctype} төрлийн баримтыг буцаах боломжгүй."
EXPL_REVERSAL = "{original} баримтын буцаалт. Шалтгаан: {reason}. — Нягтлан бодох бүртгэлийн тухай хууль 15.1"
EVENT_PERIOD_LOCKED = "period_locked"
EVENT_PERIOD_REOPENED = "period_reopened"
EVENT_PERIOD_CHANGED = "period_changed"
EVENT_PERIOD_DELETED = "period_deleted"
EVENT_ENTRY_REVERSED = "entry_reversed"
EVENT_POLICY_GENERATED = "policy_generated"
EVENT_FX_RATES_IMPORTED = "fx_rates_imported"
# Marking a rule verified is a human taking responsibility for a legal reading (§1.2), so it
# is an audit row like a period lock, not a settings edit. The request event is written when
# somebody who may not verify hits the refusal, so «the request has been recorded» is true.
EVENT_RULE_VERIFIED = "rule_verified"
EVENT_RULE_VERIFY_REQUESTED = "rule_verification_requested"
# The accountant of one company saying an uncited rule applies to *their* client's books
# (DECISIONS ACC-01). A different claim from EVENT_RULE_VERIFIED — it never speaks for another
# company — so it is a different event, and the two are counted apart everywhere they are shown.
EVENT_RULE_ACCEPTED = "rule_accepted_for_company"
# Every [Батлах] the guard refused: which rule stopped which document, for whom. It is what lets
# the accountant's acceptance finish the approval they already asked for, and it is the honest
# answer to «which rules are actually holding up work».
EVENT_RULE_BLOCKED = "rule_blocked_posting"
# A deploy added the repository's citation to a row a *person* had already ticked (VER-06). The
# row then reads «verified by Ганбат» next to a quote Ганбат never saw, and only this event says
# so: it is the difference between what the human took responsibility for and what is on the row
# now. A seeded flag needs no such row — the repository's own history is git.
EVENT_RULE_CITATION_FILLED = "rule_citation_filled"
MSG_FX_RATES_IMPORTED = "Монголбанкны ханш: {count} мөр импортлолоо ({skipped} давхардсан)."
MSG_FX_FETCH_DISABLED = "Монголбанкны ханш татах тохиргоо идэвхгүй (MONGOLBANK_FETCH_ENABLED)."

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
POLICY_UNKNOWN = "[ ]"
POLICY_INTRO = (
	"Энэхүү баримт бичгийг Нягтлан бодох бүртгэлийн тухай хуулийн 18.2, 20.2.2 дахь заалт, "
	"Санхүү, эдийн засгийн сайдын 2000 оны 116 дугаар тушаалаар баталсан дансны үлгэрчилсэн зааврыг "
	"үндэслэн {company}-ийн нягтлан бодох бүртгэлийн тохиргооноос Нябо автоматаар боловсруулав. "
	"[ ] тэмдэглэгээтэй хэсгийг нягтлан бодогч бөглөж, удирдлага баталгаажуулна."
)
POLICY_FIELD_LABELS = {
	"company": "Байгууллагын нэр",
	"tax_id": "Регистрийн дугаар / ТТД",
	"regime": "Татварын горим",
	"chart_scheme": "Дансны төлөвлөгөөний бүтэц",
	"inventory_method": "Бараа материалын өртгийн арга",
	"depreciation_method": "Элэгдэл тооцох арга",
	"fx_policy": "Валютын ханшийн бодлого",
	"retention_years": "Баримт хадгалах хугацаа (жил)",
	"accountant": "Нягтлан бодогч",
	"micpa_permit": "МНБИ-ийн зөвшөөрлийн дугаар",
	"generated_at": "Боловсруулсан огноо",
	"fiscal_year": "Санхүүгийн жил",
}
POLICY_CHART_SCHEME_LABELS = {
	"v1": "Нябо-гийн хялбаршуулсан төлөвлөгөө (40 данс)",
	"v03": "Сангийн яамны үлгэрчилсэн дансны төлөвлөгөө (Тушаал 116/2000) дээр суурилсан бүтэц",
	"accountant": "Нягтлан бодогчийн өөрийн дансны төлөвлөгөө (Нябо-гийн зүйлчлэлтэй)",
}
# Keyed by the regime name in nyabo_mn.rules.regime, which builds the mapping (F-12): this
# module holds the wording, never the rule keys.
POLICY_REGIME_VAT_PAYER = "НӨАТ төлөгч; НӨАТ-ын тайланг сар бүр гаргана"
POLICY_REGIME_SIMPLIFIED = "НӨАТ төлөгч бус; хялбаршуулсан 1%-ийн горим (улирал бүр)"
POLICY_INVENTORY_LABELS = {
	"FIFO": "Эхэлж авснаа эхэлж зарлагадах (FIFO)",
	"Weighted Average": "Жигнэсэн дундаж өртөг",
}
POLICY_DEPRECIATION_LABELS = {
	"Straight Line": "Шулуун шугамын арга",
	"Double Declining Balance": "Давхар бууруулах үлдэгдлийн арга",
}
POLICY_FISCAL_YEAR = "Хуанлийн жил (1 дүгээр сарын 1-нээс 12 дугаар сарын 31)"
# Sections: title + paragraphs. {placeholders} come from policy_doc.context(); "[ ]" stays for the accountant.
POLICY_SECTIONS = [
	{
		"key": "general",
		"title": "1. Ерөнхий зүйл",
		"paragraphs": [
			"{company} (цаашид «Байгууллага» гэх) нь нягтлан бодох бүртгэлээ Нягтлан бодох бүртгэлийн тухай хууль, "
			"Жижиг, дунд үйлдвэрийн СТОУС (IFRS for SMEs) болон Сангийн яамны баталсан заавар, журмын дагуу хөтөлнө.",
			"Бүртгэлийг монгол хэлээр, төгрөгөөр хөтөлнө (Хууль 7.1). Санхүүгийн жил: {fiscal_year}.",
			"Байгууллагын удирдлага: [ ]. Бүртгэлийн программ хангамж: ERPNext (Frappe) + Нябо туслах.",
		],
	},
	{
		"key": "basis",
		"title": "2. Бүртгэлийн үндэс",
		"paragraphs": [
			"Бүртгэлийг аккруэл сууриар хөтөлнө (Хууль 6.1): орлого, зардлыг мөнгө хүлээн авсан, төлсөн эсэхээс "
			"үл хамааран үүссэн тайлант үед нь хүлээн зөвшөөрнө.",
			"Давхар бичилтийн зарчмыг мөрдөнө (Хууль 14.2). Боловсруулалтын дараалал: анхан шатны баримт → журнал → "
			"дэлгэрэнгүй ба ерөнхий дэвтэр → тайлан (Хууль 14.3).",
		],
	},
	{
		"key": "chart",
		"title": "3. Дансны төлөвлөгөө",
		"paragraphs": [
			"Байгууллага Сангийн яамны 116/2000 дугаар тушаалын үлгэрчилсэн дансны төлөвлөгөөнд үндэслэн өөрийн "
			"дансны төлөвлөгөөг боловсруулж мөрдөнө. Хэрэглэж буй бүтэц: {chart_scheme}.",
			"Дансны төлөвлөгөөнд данс нэмэх, өөрчлөхийг ерөнхий нягтлан бодогч зөвшөөрнө. Дансны кодын жагсаалт хавсралтаар.",
		],
	},
	{
		"key": "inventory",
		"title": "4. Бараа материал",
		"paragraphs": [
			"Бараа материалыг өртгөөр бүртгэж, зарлагадах өртгийг {inventory_method} аргаар тооцно. "
			"Бараа материал бүртгэх эсэх: {has_inventory}.",
			"Жилийн эцэст болон Хуулийн 12.2-т заасан тохиолдолд тооллого хийж, зөрүүг залруулгын бичилтээр тусгана.",
		],
	},
	{
		"key": "fixed_assets",
		"title": "5. Үндсэн хөрөнгө ба элэгдэл",
		"paragraphs": [
			"Үндсэн хөрөнгийг анхны өртгөөр бүртгэж, {depreciation_method} аргаар элэгдэл тооцно. "
			"Хөрөнгийг үндсэн хөрөнгөд тооцох доод үнэлгээ: [ ] төгрөг.",
			"Ашиглалтын хугацааг хөрөнгийн төрөл тус бүрээр тогтооно: барилга [ ] жил, машин, тоног төхөөрөмж [ ] жил, "
			"тээврийн хэрэгсэл [ ] жил, компьютер, программ хангамж [ ] жил.",
		],
	},
	{
		"key": "fx",
		"title": "6. Гадаад валют",
		"paragraphs": [
			"Гадаад валютын гүйлгээг гүйлгээний өдрийн ханшаар ({fx_policy}) төгрөгт хөрвүүлж бүртгэнэ. Валютын үлдэгдлийг "
			"тайлант үеийн эцэст дахин үнэлж, ханшийн зөрүүг олз, гарзаар хүлээн зөвшөөрнө.",
		],
	},
	{
		"key": "revenue",
		"title": "7. Орлого хүлээн зөвшөөрөх",
		"paragraphs": [
			"Бараа борлуулалтын орлогыг бараа хүлээлгэн өгсөн, үйлчилгээний орлогыг үйлчилгээ үзүүлсэн үед хүлээн "
			"зөвшөөрнө. Урьдчилгаа төлбөрийг өр төлбөрт бүртгэнэ.",
			"Борлуулалт бүрт и-баримт (НӨАТ-ын баримт) үүсгэнэ.",
		],
	},
	{
		"key": "tax",
		"title": "8. НӨАТ болон бусад татвар",
		"paragraphs": [
			"Татварын горим: {regime}.",
			"НӨАТ төлөгч бус тохиолдолд худалдан авалтын НӨАТ-ыг бараа, ажил, үйлчилгээний өртөгт оруулна; НӨАТ төлөгч "
			"тохиолдолд суутган тооцох НӨАТ-ыг тусад нь бүртгэнэ (Заавар 116). Татварын хувь хэмжээг Нябо-гийн татварын "
			"параметрээс хууль тогтоомжийн эх сурвалжтай тулган хэрэглэнэ.",
		],
	},
	{
		"key": "documents",
		"title": "9. Анхан шатны баримт ба хадгалалт",
		"paragraphs": [
			"Анхан шатны баримтгүйгээр ажил гүйлгээг бүртгэхийг хориглоно (Хууль 13.7). Баримтын маягтыг Сангийн сайдын "
			"2017 оны 347 дугаар тушаалын дагуу хэрэглэнэ; баримт нь гарын үсэг, тамгаар эсхүл цахим гарын үсгээр "
			"баталгаажна (Хууль 13.5).",
			"Нягтлан бодох бүртгэлийн баримт, тайланг хамгийн багадаа {retention_years} жил хадгална (Хууль 11.1). Нябо-д "
			"илгээсэн баримтын зураг, файл болон бүртгэлийн бичилтийг устгахыг систем хориглоно.",
		],
	},
	{
		"key": "corrections",
		"title": "10. Залруулга",
		"paragraphs": [
			"Бүртгэгдсэн бичилтийг засварлахгүй; алдааг шалтгаан, аргыг заасан баримтыг үндэслэн буцаалтын (залруулгын) "
			"бичилтээр залруулж, баталсан этгээдийг бүртгэнэ (Хууль 15.1). Залруулгыг алдаа гарсан тайлант үед нь "
			"тусгана (Хууль 15.2).",
		],
	},
	{
		"key": "period",
		"title": "11. Тайлант үе ба хаалт",
		"paragraphs": [
			"Сар бүрийн эцэст гүйлгээ баланс, НӨАТ/хялбаршуулсан горимын тоймыг гаргаж, нягтлан бодогч сарыг хаана. "
			"Хаагдсан сард бичилт хийхийг систем хориглоно; дахин нээх шийдвэрийг шалтгааны хамт бүртгэнэ.",
			"Санхүүгийн тайланг (санхүүгийн байдал, орлогын дэлгэрэнгүй, өмчийн өөрчлөлт, мөнгөн гүйлгээний тайлан, "
			"тодруулга) жил бүрийн 2 дугаар сарын 10-ны дотор цахимаар тушаана (Хууль 8.1, 10).",
		],
	},
	{
		"key": "responsibility",
		"title": "12. Хариуцлага ба гарын үсэг",
		"paragraphs": [
			"Бүртгэл хөтлөх нягтлан бодогч: {accountant} (МНБИ-ийн зөвшөөрөл: {micpa_permit}). Ерөнхий нягтлан бодогч "
			"Хуулийн 20.2-т заасан үүргийг хэрэгжүүлж, энэхүү бодлогын баримт бичгийг хадгална (Хууль 18.2, 20.2.2).",
			"Бодлогын баримт бичгийг байгууллагын удирдлага баталж, өөрчлөлт бүрийг огноо, гарын үсгээр баталгаажуулна.",
		],
	},
]
POLICY_SIGN_DIRECTOR = "Батлав: Захирал ______________________ ( [ ] )"
POLICY_SIGN_ACCOUNTANT = "Боловсруулав: Нягтлан бодогч ______________________ ( {accountant} )"
POLICY_FILE_NAME = "НББ-ийн бодлого — {company}.pdf"
POLICY_SOURCES_FOOTER = "Эх сурвалж: Нягтлан бодох бүртгэлийн тухай хууль (2015); Сангийн сайдын 116/2000, 347/2017, 100/2018 дугаар тушаал."

# --- questions ---------------------------------------------------------------------------
MSG_QUESTION_THINKING = "Шалгаж байна…"
MSG_QUESTION_CANNOT = "Энэ асуултад дэвтрээс хариулж чадсангүй."
MSG_ESCALATED = "Асуултыг админд дамжууллаа."
MSG_BALANCE_ANSWER = "{account}: {date} өдрийн үлдэгдэл {balance}₮"
# A bare «2026 оны 9-р сар: 6210 - Шатахуун - TST 77 272.73₮» never says what the figure is,
# and it is what the user reads whenever the model writes no sentence or an unverifiable one.
# The noun is the one the button that runs this query already uses (BTN_Q_ACCOUNT_TOTAL), and
# it stays true for any account: this is the month's net turnover, not only an expense.
MSG_SPEND_ANSWER = "{period}: {account} — нийт дүн {amount}₮"
MSG_LAST_ENTRIES_ANSWER = "{supplier} сүүлийн бүртгэлүүд:\n{entries}"
# The line under an answer that names what was actually read, so a follow-up that carried the
# wrong month forward is visible instead of silent.
MSG_QUESTION_SUBJECT = "📒 {subject}"
MSG_QUESTION_TRY_REPHRASE = "Асуултаа өөрөөр бичиж үзнэ үү, эсвэл админаас асууна уу."
# The whole dead end, in one string, because a typed question and a tapped button must reach
# the same one. The tapped path always offered the next step; the typed path sent
# MSG_QUESTION_CANNOT on its own, so the same failure read as a bare refusal in the shape of
# question an accountant actually types. Composed here rather than at the two call sites so
# the two can never drift apart again.
MSG_QUESTION_CANNOT_FULL = f"{MSG_QUESTION_CANNOT}\n{MSG_QUESTION_TRY_REPHRASE}"
MSG_QUESTION_CONTEXT_GONE = "Энэ хариулт хуучирсан байна. Асуултаа дахин бичнэ үү."
MSG_QUESTION_ESCALATE_SUMMARY = "Хэрэглэгч хариултын дор «{button}» товч дарлаа: {question}"

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
LBL_ACCOUNT_NAME = "Дансны нэр"
LBL_ACCOUNT_NO = "Дансны дугаар"
LBL_JOURNAL_TYPE = "Журналын төрөл"
LBL_PREPARED_ON = "Бэлтгэсэн"
LBL_REPORT_SOURCE = "Эх сурвалж"
LBL_FROM_DATE = "Эхлэх огноо"
LBL_TO_DATE = "Дуусах огноо"
LBL_REGIME = "Горим"
LBL_MONTH = "Сар"
LBL_REVENUE = "Орлого"
LBL_RATE_PCT = "Хувь"
LBL_TAX = "Татвар"
LBL_OUTPUT_VAT = "Борлуулалтын НӨАТ"
LBL_INPUT_VAT = "Татан суутгах НӨАТ"
LBL_NET_VAT = "Төлөх (буцаан авах) НӨАТ"
LBL_COUNTER_ACCOUNT = "Харьцсан данс"
LBL_REFERENCE = "Лавлах"
LBL_CASH_RECEIPT = "Орлого"
LBL_CASH_PAYMENT = "Зарлага"
LBL_ROW_NO = "№"
LBL_TAX_PARAMETER_ROW = "Татварын параметр"
LBL_REGIME_CONDITION = "Горимын нөхцөл"
LBL_VERIFIED = "Баталгаажсан"
LBL_UNVERIFIED = "Баталгаажаагүй"
LBL_SIMULATION = "Симуляц (баталгаажаагүй дүрэм)"
REPORT_PDF_FOOTER = "Нябо · ERPNext. Маягтын эх сурвалж: {source}."

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
FORM_LBL_ORG = "Байгууллагын нэр"
FORM_LBL_REG_NO = "Регистрийн дугаар"
FORM_LBL_TIN = "ТТД"
FORM_LBL_DOC_NO = "Дугаар"
FORM_LBL_DATE = "Огноо"
FORM_LBL_RECEIVED_FROM = "Хэнээс"
FORM_LBL_PAID_TO = "Хэнд"
FORM_LBL_BASIS = "Үндэслэл"
FORM_LBL_AMOUNT = "Дүн"
FORM_LBL_AMOUNT_IN_WORDS = "Дүн үсгээр"
FORM_LBL_ACCOUNT_DEBIT = "Дебет данс"
FORM_LBL_ACCOUNT_CREDIT = "Кредит данс"
FORM_LBL_DIRECTOR = "Захирал"
FORM_LBL_CHIEF_ACCOUNTANT = "Ерөнхий нягтлан бодогч"
FORM_LBL_CASHIER = "Нярав"
FORM_LBL_RECEIVED_BY = "Хүлээн авсан"
FORM_LBL_PAID_BY = "Тушаасан"
FORM_LBL_SIGNATURE = "гарын үсэг"
FORM_LBL_COPY_1 = "1-р хувь (нярав)"
FORM_LBL_COPY_2 = "2-р хувь (тушаагч / хүлээн авагч)"
FORM_LBL_SELLER = "Нэхэмжлэгч (борлуулагч)"
FORM_LBL_BUYER = "Төлөгч (худалдан авагч)"
FORM_LBL_ITEM = "Бараа, ажил, үйлчилгээний нэр"
FORM_LBL_QTY = "Тоо хэмжээ"
FORM_LBL_UNIT = "Нэгж"
FORM_LBL_UNIT_PRICE = "Нэгж үнэ"
FORM_LBL_LINE_TOTAL = "Дүн"
FORM_LBL_SUBTOTAL = "Хэсгийн дүн"
FORM_LBL_VAT = "НӨАТ"
FORM_LBL_GRAND_TOTAL = "Нийт дүн"
FORM_LBL_DUE_DATE = "Төлбөр төлөх хугацаа"
FORM_LBL_BANK_DETAILS = "Банкны данс"
FORM_LBL_EBARIMT = "И-баримтын дугаар"
FORM_LBL_PAYEE = "Хүлээн авагч"
FORM_LBL_PAYEE_BANK = "Хүлээн авагчийн банк, данс"
FORM_LBL_PAYER_ACCOUNT = "Төлөгчийн данс"
FORM_LBL_PURPOSE = "Гүйлгээний утга"
FORM_LBL_STATUS = "Төлөв"
FORM_LBL_PREPARED_BY = "Бэлтгэсэн"
FORM_PAYMENT_ORDER_NOTE = (
	"Төлбөрийн даалгавар нь банкны маягт тул энэ жагсаалт зөвхөн урьдчилсан бүртгэл болно; "
	"банкны системд баталгаажуулна."
)

# --- readiness checklist (certification) ----------------------------------------------------
READINESS_TITLE = "Нягтлан бодох бүртгэлийн программ хангамжийн бэлэн байдал"
READINESS_PASS = "ТЭНЦСЭН"
READINESS_FAIL = "ДУТУУ"
READINESS_COL_ITEM = "Шалгуур"
READINESS_COL_STATUS = "Төлөв"
READINESS_COL_DETAIL = "Тайлбар"
READINESS_E_SIGNATURE_PENDING = (
	"Хэрэгжээгүй; Сангийн яамны цахим гарын үсгийн техникийн шаардлага хүлээгдэж байна."
)
READINESS_SITE_LINE = "Сайт: {site}"
# The checklist is Nyabo's own: the MoF certification procedure has not been obtained, so no
# requirement numbering is claimed (docs/mn-rules-reference.md §6.1, docs/legal/README.md).
READINESS_SOURCE_PENDING = (
	"Энэ бол Нябо-гийн дотоод бэлэн байдлын жагсаалт. Сангийн яамны «Нягтлан бодох бүртгэлийн "
	"программ хангамжид хяналт тавих журам»-ын эх бичвэрийг хараахан аваагүй тул албан ёсны "
	"шаардлагын дугаарлалтыг заагаагүй; журмыг авсны дараа мөр бүрийг түүнтэй тулгана."
)
READINESS_DETAIL_OK = "Байна"
READINESS_DETAIL_MISSING = "Алга: {what}"
READINESS_DETAIL_COUNT = "{count} мөр"
# The certification reader must not be able to read "35 rows verified" as 35 human decisions.
# ...and it must not read an accountant's acceptance as either of the other two: it clears the
# rule for one company's books, not for the site, and no citation stands behind it (ACC-01).
READINESS_DETAIL_RULES_VERIFIED = (
	"{count} мөр: {by_seed} нь Нябогийн эх сурвалжийн ишлэлээр, "
	"{by_person} нь нэрлэсэн хүний баталгаажуулалтаар; "
	"нэмж {accepted} дүрмийг {companies} компанийн нягтлан өөрийн бүртгэлдээ хамааруулсан"
)
READINESS_DETAIL_ERPNEXT_REPORT = "ERPNext-ийн стандарт тайлан ({report})"
READINESS_DETAIL_HOOK = "Хук: {handler}"
READINESS_DETAIL_COMPANIES = "Компани: {ok}/{total} тохируулсан"
READINESS_DETAIL_STATEMENTS = "Загвар: {present}; дутуу: {missing}"
# Reports with no MoF form behind them (VAT and 1% summaries, the readiness table) say so
# instead of naming an instrument nobody has read.
FORM_SOURCE_INTERNAL = "Нябо-гийн дотоод загвар (батлагдсан маягтын эх сурвалж тодорхойгүй)"
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
# Transaction dates read as dd.mm plus the weekday: "09.03 (Мя)" (core.dates.short_date_mn).
SHORT_DATE_WEEKDAY = "{date} ({weekday})"
VALUE_UNKNOWN = "—"  # the em dash a card prints where a field could not be read
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
LBL_NYABO_TEMPLATE_CHECKSUM = "Нябо-гийн үлгэрийн хяналтын нийлбэр"
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
# The ERPNext doctypes an answer names out loud. Their names are English and they arrive as
# *data* — a ``voucher_type`` off a GL row, a proposal's ``posted_doctype`` — so the i18n walk
# cannot see them, and «Purchase Invoice ACC-PINV-2026-00001» reached a Mongolian card that
# way. Anything unlisted keeps its raw name: an English label the reader can look the document
# up by beats a Mongolian one Nyabo guessed.
DOCTYPE_LABELS: dict[str, str] = {
	"Purchase Invoice": "Худалдан авалтын нэхэмжлэх",
	"Journal Entry": "Журналын бичилт",
	"Payment Entry": "Төлбөрийн баримт",
}


def doctype_label(doctype: str | None) -> str:
	"""The Mongolian name of an ERPNext doctype, or the raw name when there is none."""
	name = str(doctype or "").strip()
	return DOCTYPE_LABELS.get(name, name)


def account_label(account: str | None, abbr: str | None = None) -> str:
	"""An ERPNext account name as a card prints it: «6610 - Зар сурталчилгаа».

	WHY: the stored name is «6610 - Зар сурталчилгаа - TST» — code, name, and the company
	abbreviation ERPNext appends so names stay unique ACROSS companies. Every question is
	answered about one company, so that suffix is noise on the card, and it is the reader's
	own company abbreviation that is stripped rather than "whatever follows the last dash":
	an account name may contain a dash of its own, and guessing would eat part of it.

	The code stays, because it is what an accountant looks the account up by — and it is why
	no caller prints the code beside this: the name already opens with it.
	"""
	name = str(account or "").strip()
	suffix = f" - {str(abbr or '').strip()}"
	if suffix.strip(" -") and name.endswith(suffix):
		return name[: -len(suffix)].rstrip()
	return name


LAST_ENTRY_LINE = "{date} · {doctype} {name} · {amount}₮"
# A debit note is this app's own correction (§1.5) and it DEBITS the payable, exactly as a
# payment does, so the larger side of its GL row is the amount of the purchase it reverses. Read
# as a bare magnitude the correction printed a second, identical purchase beside the one it
# cancelled — while the supplier total card next to it said «худалдан авалт 0₮». The row is named
# for what it is and shown negative, the way ``_supplier_total`` nets it out.
LAST_ENTRY_LINE_RETURN = "{date} · {doctype} {name} · {amount}₮ (буцаалт/залруулга)"
# Two different answers that both used to end «олдсонгүй»: this one is "the supplier is in the
# register and has nothing posted", the one below is "there is no supplier by that name". An
# accountant chasing a missing document has to be able to tell a typo in the name from a
# supplier with an empty period, so the first says the supplier IS registered and the second
# keeps «олдсонгүй» for the name that is not.
LAST_ENTRIES_NONE = "{supplier} харилцагч бүртгэлтэй боловч гүйлгээ алга."
UNMATCHED_ANSWER = "Тулгагдаагүй банкны гүйлгээ: {count}"
SUPPLIER_NOT_FOUND_ANSWER = "{supplier} нэртэй харилцагч олдсонгүй."
# The wider read-only answers (§5.7). Every figure in them is computed by the handler.
ACCOUNT_ENTRY_LINE = "{date} · {voucher} · {amount}₮"
MSG_ACCOUNT_ENTRIES_ANSWER = "{period}: {account} дансны бичилтүүд:\n{entries}"
ACCOUNT_ENTRIES_NONE = "{period}: {account} дансанд бичилт алга."
MSG_SUPPLIER_TOTAL_ANSWER = "{period}: {supplier} — худалдан авалт {purchases}₮, төлсөн {payments}₮"
# Appended when a debit note nets out of the purchases: «худалдан авалт 0₮» after an invoice
# was corrected reads like a lost document unless the correction is named beside it. The gross
# is named because the line above already reports the purchases NET of the returns, so
# «Үүнээс … 85 000₮» under «худалдан авалт 0₮» said "of that zero, 85 000" — the arithmetic has
# to close on the card an accountant reads first after every correction.
SUPPLIER_TOTAL_RETURNS = "\nХудалдан авалт {gross}₮-өөс {returns}₮ буцаалт/залруулга хасагдсан."
SUPPLIER_TOTAL_NONE = "{period}: {supplier} харилцагчтай холбоотой гүйлгээ алга."
MSG_VAT_POSITION_ANSWER = (
	"{period}: борлуулалтын НӨАТ {output}₮, худалдан авалтын НӨАТ {input}₮, төлөх НӨАТ {net}₮"
)
# The other side of the same figure. «төлөх НӨАТ -7 727.27₮» says the company owes minus seven
# thousand, which is not a sentence: it is owed that money. VAT is the number an accountant
# scrutinises hardest, so the credit case is named as a credit and the amount is positive.
MSG_VAT_POSITION_CREDIT_ANSWER = (
	"{period}: борлуулалтын НӨАТ {output}₮, худалдан авалтын НӨАТ {input}₮, буцаан авах НӨАТ {credit}₮"
)
MSG_VAT_NOT_PAYER_ANSWER = "{period}: компани НӨАТ төлөгч бус тул НӨАТ-ын мэдээлэл байхгүй."
# ``{account}`` is rendered by ``account_label``, which already begins with the account code,
# so the code is not printed beside it: «6610 6610 - Зар сурталчилгаа - TST» was one row
# naming one account three times.
TOP_ACCOUNT_LINE = "{account} · {amount}₮"
MSG_TOP_ACCOUNTS_ANSWER = "{period}: хамгийн их зардалтай данснууд:\n{accounts}"
TOP_ACCOUNTS_NONE = "{period}: бүртгэсэн зардал алга."
UNMATCHED_LINE = "{date} · {amount}₮ · {description}"
MSG_UNMATCHED_LINES_ANSWER = "Тулгагдаагүй банкны гүйлгээ:\n{lines}"
UNMATCHED_LINES_NONE = "Тулгагдаагүй банкны гүйлгээ алга."
MSG_ENTRY_EXPLAIN_ANSWER = "{doctype} {name} · {date} · {amount}₮\n{explanation}"
ENTRY_EXPLAIN_NO_PROPOSAL = "Энэ бичилтийг Нябо санал болгоогүй тул тайлбар алга."
# The day the photograph arrived, not the Nyabo Document's own name: «Эх баримт: NYD-00002» is
# an internal id an accountant has never seen, while the date is how they find that receipt.
ENTRY_EXPLAIN_SOURCE = "🧾 Эх баримт: {date} өдөр хүлээн авсан"
ENTRY_NOT_FOUND_ANSWER = "«{name}» нэртэй бүртгэл энэ компанид олдсонгүй."
# Every list answer shows at most a handful of rows. Saying so is not a nicety: an accountant
# reading five of forty unmatched lines with no sign of the cut acts on a false picture of the
# books, so the full count is computed and the cut is named beside the rows.
#
# Two notes, because the two kinds of list are cut at different ends. The row lists are ordered
# newest-first, so what is shown is the MOST RECENT rows and what is hidden is the older ones;
# «эхний {shown}» said "the first N", which named the wrong end and contradicted the supplier
# card's own «сүүлийн бүртгэлүүд» heading. The account list is ordered by amount, so its note
# says "the largest N" instead — "most recent" would be a lie about a ranking.
#
# WHY the numeral is never given a case suffix: the correct accusative depends on the numeral
# («тав» -> «тавыг», «найм» -> «наймыг»), and these are formatted with whatever the limit
# happens to be, so «{shown}-г» could only ever be wrong for some of them. The suffix therefore
# attaches to the noun that follows the numeral, which does not change.
ANSWER_TRUNCATED = "\n… нийт {total} мөрөөс хамгийн сүүлийн {shown} мөрийг харууллаа."
ANSWER_TRUNCATED_TOP = "\n… нийт {total} данснаас хамгийн их дүнтэй {shown} дансыг харууллаа."

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
# Two rows of one tax parameter in force on the same day is a site-wide data fault, not a
# reading the accountant can accept for their own company: whichever row wins would win for
# every client. So this is one of the few places an admin genuinely is needed, and it says
# which one and what they have to do.
MSG_RULE_AMBIGUOUS = (
	"«{key}» дүрэм {date} огноонд хоёр мөрөөр давхардсан байна. Энэ нь сайт даяарх өгөгдлийн "
	"алдаа тул нэг компанийн хэмжээнд засах боломжгүй. Нябог тохируулсан хүнд хандаж, ERPNext "
	"дэск дэх «Nyabo Tax Parameter» бичлэгүүдийн хүчинтэй хугацааг залруулуулна уу."
)
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
MATCH_REASON_SETTLED = "{name} баримтын төлбөрөөр бүртгэв"

# --- rules (Frappe side: params, regime, patterns, guard, seed, aliases) --------------------------
MSG_ROLE_UNRESOLVED = "«{role}» дансны үүрэгт {scheme} схемд данс байхгүй тул нягтлан данс сонгоно уу."
MSG_ALIAS_TARGET_MISSING = "«{code}» код {company} компанийн дансны төлөвлөгөөнд алга."
MSG_TAX_PARAM_DATES = "Дуусах огноо ({effective_to}) эхлэх огноо ({effective_from})-оос өмнө байж болохгүй."
MSG_TAX_PARAM_OVERLAP = "«{key}» дүрмийн хугацаа {other} бичлэгтэй давхцаж байна."
MSG_TAX_PARAM_JSON_INVALID = "Утга (JSON) буруу байна: {error}"
MSG_TAX_PARAM_VALUE_REQUIRED = (
	"Идэвхтэй дүрэмд утга заавал хэрэгтэй; утга тодорхойгүй бол төлөвийг «pending» болгоно уу."
)
MSG_PATTERN_NEEDS_BOTH_SIDES = "Бичилтийн загварт дор хаяж нэг дебет, нэг кредит мөр хэрэгтэй."
MSG_PATTERN_NEEDS_DOCUMENT_TYPES = "Загварын баримтын төрлүүдийг заана уу (жишээ нь: Journal Entry)."
MSG_REGIME_OVERLAP = "Татварын горимын хугацаанууд давхцаж байна: {first} ба {second}."
MSG_REGIME_GAP = "Татварын горимын хугацаанд завсар байна: {previous_end} → {next_start}."
MSG_REGIME_OPEN_NOT_LAST = (
	"Зөвхөн сүүлийн горимын дуусах огноо хоосон байж болно ({regime}, {effective_from})."
)
MSG_REGIME_UNKNOWN = "«{regime}» гэдэг татварын горим байхгүй."
MSG_DEFAULT_EXPENSE_CODE_MISSING = "Үндсэн зардлын данс «{code}» дансны төлөвлөгөөнд алга."
MSG_SEED_ROWS_MISSING = "«{doctype}» дүрмийн өгөгдөл ачаалагдаагүй байна; bench migrate ажиллуулна уу."

# --- setup (provisioning, bank sub-accounts, chart import, inventory intake) ---------------------
ITEM_GROUP_INVENTORY = "Бараа материал"
UOM_PIECE = "ш"
MSG_INTAKE_LINE_UNREADABLE = "{line}-р мөрийг уншиж чадсангүй: «{text}». Хэлбэр: нэр, тоо, үнэ"
MSG_INTAKE_EMPTY = "Бараа материалын жагсаалт хоосон байна."
MSG_INTAKE_HEADER_NOT_FOUND = "Хүснэгтэд нэр, тоо, үнэ баганууд олдсонгүй."
MSG_INTAKE_NOT_CONFIRMED = "Бараа материалын жагсаалт ({name}) баталгаажаагүй тул бүртгэхгүй."
MSG_INTAKE_ALREADY_POSTED = "Бараа материалын жагсаалт ({name}) аль хэдийн бүртгэгдсэн."
MSG_INTAKE_CANCELLED = "Бараа материалын жагсаалтыг ({name}) цуцалсан тул бүртгэхгүй."
MSG_INTAKE_NO_SETTINGS = (
	"{company} компанийн Нябо тохиргоо байхгүй тул бараа материал бүртгэхгүй. /эхлэх командаар тохируулна уу."
)
MSG_INTAKE_QTY_RATE_POSITIVE = "{item}: тоо ба нэгж үнэ эерэг байх ёстой."
EXPL_INVENTORY_OPENING = (
	"Бараа материалын эхний үлдэгдэл ({intake}): Дт Бараа материал — Кт Түр нээлтийн данс."
)
MSG_CHART_CSV_COLUMNS = "CSV файлд code, name, parent_code, root_type, account_type баганууд хэрэгтэй."
MSG_CHART_CSV_PARENT_MISSING = "«{code}» дансны эцэг данс «{parent}» файлд алга."
MSG_CHART_CSV_ROOT_TYPE = "«{code}» язгуур дансны root_type буруу байна: {root_type}."
MSG_CHART_CSV_REQUIRED = "Нягтлангийн дансны төлөвлөгөө (chart_csv) өгөгдөөгүй байна."
# The chart's own title, shown wherever ERPNext names the chart of accounts.
CHART_CSV_NAME = "Нягтлангийн дансны төлөвлөгөө"
MSG_BANK_UNKNOWN = "«{bank}» банк жагсаалтад алга."

# --- matching (parsers, bank import, rules, cards, status) ----------------------------------------
MSG_STATEMENT_FILE_XLS_UNSUPPORTED = (
	"Хуучин .xls форматыг уншиж чадахгүй. Excel-д нээж .xlsx болгон хадгалаад дахин илгээнэ үү."
)
MSG_STATEMENT_FILE_UNREADABLE = "«{filename}» файлыг уншиж чадсангүй. .xlsx эсвэл .csv файл илгээнэ үү."
MSG_STATEMENT_NOT_A_STATEMENT = "Энэ баримт банкны хуулга биш байна."
MSG_STATEMENT_NO_LINES = "Хуулгаас гүйлгээ олдсонгүй."
MSG_STATEMENT_BANK_UNKNOWN = "Хуулгын банк тодорхойгүй байна; форматыг зааж өгнө үү."
MSG_LAYOUT_BAD_JSON = "«{field}» талбар зөв JSON биш байна."
MSG_LAYOUT_ROLE_UNKNOWN = "«{role}» баганын үүрэг танигдахгүй байна. Зөвшөөрөгдөх: {roles}"
MSG_LAYOUT_NEEDS_DATE_DESCRIPTION = "Баганын зураглалд огноо болон гүйлгээний утгын багана заавал байна."
MSG_LAYOUT_AMOUNT_STYLE_MISMATCH = "Дүнгийн хэлбэр «{style}» баганын зураглалтай тохирохгүй байна."
MSG_LAYOUT_VERIFY_NEEDS_COLUMNS = (
	"Толгойн гарын үсэг болон баганын зураглалгүй загварыг баталгаажуулж болохгүй."
)
MSG_LAYOUT_BAD_DATE_FORMAT = "Огнооны формат «{fmt}» буруу байна."
MSG_LAYOUT_LEARNED_NOTE = "{company} компанийн {document} хуулгаас нягтлангийн зааснаар сурсан формат."
MSG_BANK_LINE_ALREADY_RECONCILED = "Энэ гүйлгээ аль хэдийн тулгагдсан байна."
MSG_BANK_LINE_NOT_ACTIVE = (
	"Энэ банкны гүйлгээ идэвхгүй (цуцлагдсан эсвэл ноорог) тул төлбөр бүртгэх боломжгүй. "
	"Хуулгыг дахин оруулна уу."
)
MSG_BANK_VOUCHER_NOT_FOUND = "{doctype} {name} олдсонгүй."
MSG_BANK_VOUCHER_NOT_ALLOWED = "{doctype} төрлийн баримтыг банкны гүйлгээтэй тулгах боломжгүй."
MSG_BANK_NEEDS_PAYMENT_ENTRY = (
	"{doctype} {name} нэхэмжлэх төлөгдөөгүй байна: өглөг хаагдаагүй тул шууд тулгаж болохгүй. "
	"«Төлбөр бүртгэх» товчийг дарж төлбөрийн баримт үүсгэсний дараа гүйлгээ тулгагдана."
)
MSG_BANK_SETTLE_NOT_NEEDED = "{doctype} {name} нэхэмжлэхэд төлөх үлдэгдэл алга; төлбөр бүртгэх шаардлагагүй."
MSG_BANK_SETTLE_OVER_ALLOCATION = (
	"Гүйлгээний дүн {amount}₮ нь {name} нэхэмжлэхийн үлдэгдэл {outstanding}₮-оос их байна. "
	"Өөр баримт сонгох эсвэл нягтлан гараар хуваан бүртгэнэ үү."
)
# A genuinely administrative gap, and a rare one: TG-05 grants the ERPNext roles at link
# time, so this only reaches somebody linked before that existed. Re-linking is the fix they
# can ask for, and it names who can give it.
MSG_BANK_SETTLE_ERPNEXT_PERMISSION = (
	"Төлбөрийн баримт үүсгэх ERPNext эрх (Accounts User) таны хэрэглэгчид олгогдоогүй байна. "
	"Нябог тохируулсан хүнээс шинэ холболтын код авч дахин холбогдоно уу; эрх автоматаар олгогдоно."
)
MSG_BANK_SETTLE_WRONG_DIRECTION = (
	"Зарлагын гүйлгээгээр зөвхөн худалдан авалтын нэхэмжлэх, орлогын гүйлгээгээр зөвхөн "
	"борлуулалтын нэхэмжлэх төлөгдөнө. {doctype} {name} энэ гүйлгээний чиглэлд тохирохгүй."
)
MSG_BANK_SETTLE_CURRENCY_MISMATCH = (
	"Валют таарахгүй байна: гүйлгээ {bank}, нэхэмжлэх {invoice}, харилцагчийн данс {party}. "
	"Нягтлан гараар бүртгэнэ үү."
)
MSG_BANK_SETTLE_ALREADY_PROPOSED = (
	"Энэ гүйлгээнд аль хэдийн бичилтийн санал ({proposal}) байна; банкны данс дахин кредитлэгдэхгүй."
)
# The accountant configures the bank accounts themselves in `/эхлэх`, so the step is named
# rather than handed to somebody else.
MSG_BANK_SETTLE_NO_BANK_ACCOUNT = (
	"Энэ гүйлгээний банкны дансанд ерөнхий дэвтрийн данс тохируулаагүй байна. "
	"/эхлэх командаар банкны дансаа тохируулаад дахин оролдоно уу."
)
MSG_BANK_SETTLE_REVERSED = "{doctype} {name} буцаагдсан/залруулагдсан тул төлбөр бүртгэх боломжгүй."
MSG_BANK_SETTLED = "💸 Төлбөр бүртгэлээ: {payment} · {voucher}"
CARD_BANK_SETTLE_HINT = "💸 Төлөгдөөгүй баримт: {voucher} · {party} · {amount}₮"
EXPL_BANK_SETTLE = (
	"«{description}» гүйлгээгээр {voucher} нэхэмжлэхийн өглөгийг хааж, банкны данс {credit_code} кредитлэв."
)
EXPL_BANK_SETTLE_RECEIVE = (
	"«{description}» гүйлгээгээр {voucher} нэхэмжлэхийн авлагыг хааж, банкны данс {debit_code} дебетлэв."
)
EXPL_BANK_FEE = "Банкны хураамж тул {debit_code} дебетлэж, банкны данс {credit_code} кредитлэв."
EXPL_BANK_LINE_EXPENSE = (
	"«{description}» гүйлгээг {debit_code} дансанд бүртгэж, банкны данс {credit_code} кредитлэв."
)
EXPL_BANK_LINE_INCOME = "«{description}» орлогыг банкны данс {debit_code} дебетлэж, {credit_code} кредитлэв."
EXPL_BANK_TRANSFER = "Өөрийн дансууд хоорондын шилжүүлэг: {debit_code} дебет, {credit_code} кредит."
WARN_BANK_LINE_LLM_UNAVAILABLE = "Ангилал хийх боломжгүй тул үндсэн зардлын дансыг санал болгов."
WARN_BANK_LINE_INCOME_UNCLASSIFIED = "Орлогын гүйлгээ тул нягтлан дансыг сонгоно."
CARD_BANK_UNMATCHED = "❔ Тулгаагүй"
CARD_BANK_TRANSFER = "🔁 Шилжүүлэг: {from_account} → {to_account}"
CARD_BANK_REASON = "Шалтгаан: {reason}"
MSG_RECON_AS_OF = "{date} өдрийн байдлаар"

# --- telegram (router, handlers, cards) ---------------------------------------------------------
ROLE_LABELS = {"Owner": "Эзэмшигч", "Accountant": "Нягтлан", "Admin": "Админ"}
MSG_LINK_USAGE = "Хэрэглээ: /link <нягтлан|эзэмшигч> <компанийн нэр>"
MSG_LINK_ROLE_UNKNOWN = "Үүрэг буруу байна: «нягтлан» эсвэл «эзэмшигч» гэж бичнэ үү."
MSG_LINK_COMPANY_NOT_FOUND = "Компани олдсонгүй: {company}"
MSG_ADMIN_ONLY = "Энэ команд зөвхөн админд зориулагдсан."
MSG_ADMIN_ERROR_NOTICE = "⚠️ Нябо алдаа: {event} · chat {chat_id} · {error}"
MSG_ADMIN_LINK_GUESSING = "🔒 Холбох кодыг олон удаа буруу оруулсан тул {chat_id} дугаартай чатыг түр хаалаа."
# What an admin actually receives when a question is handed to a human. The user has already
# been told «Асуултыг админд дамжууллаа», so this message is the promise being kept: without
# it the escalation is only a Nyabo Event nobody reads.
MSG_ADMIN_QUESTION_ESCALATED = "❓ {company}: хэрэглэгчийн асуултыг админд дамжуулав.\n{summary}"
# Same reading risk as MSG_ERROR_ADMIN_NOTIFIED (UX-13): nobody is approving anything. And
# the same pair, for the same reason — only the router draws the button and notifies.
MSG_FEATURE_UNAVAILABLE = (
	"Энэ боломж одоогоор бэлэн болоогүй байна. Энэ нь таны бичилтийг хэн нэгэн зөвшөөрөх гэж "
	"хүлээж байна гэсэн үг биш — Нябо-г хөгжүүлэгч рүү мэдэгдэл очлоо, шалгаж засна. "
	"Та өөр үйлдэл хийж болно — доорх «Цэс» товч (/меню)."
)
MSG_FEATURE_UNAVAILABLE_NO_BUTTON = (
	"Энэ боломж одоогоор бэлэн болоогүй байна. Энэ нь таны бичилтийг хэн нэгэн зөвшөөрөх "
	"гэж хүлээж байна гэсэн үг биш. Та «/меню» гэж бичээд өөр үйлдэл хийж болно."
)
MSG_CANCELLED = "Цуцаллаа."

# --- escape hatches: no waiting step may be a dead end (UX-13) --------------------------------
# Every state that waits for the user carries Цуцлах, plus Буцах where a previous step exists
# and Алгасах where the step is genuinely optional; the same words typed by hand mean the same
# thing (nyabo_mn.telegram.handlers.escape).
MSG_FLOW_CANCELLED = "Болилоо. Эхлүүлсэн ажлыг хаалаа. Хүссэн үедээ дахин эхлүүлж болно (/меню)."
MSG_FLOW_NOTHING_TO_CANCEL = "Одоогоор үргэлжилж байгаа ажил алга. /меню — үндсэн цэс."
MSG_FLOW_LEFT_FOR_COMMAND = "Эхлүүлсэн ажлыг хаалаа."
# [Цэс] closes whatever was open, so it says what that was: an accountant who tapped it on an
# error card from this morning is entitled to know which conversation went with it. The keys
# are the conversation state prefixes (nyabo_mn.telegram.keyboards SCOPE_*).
MSG_FLOW_LEFT_NAMED = "«{flow}» ажлыг хаалаа."
FLOW_NAMES = {
	"onb": "Тохиргоо",
	"layout": "Хуулгын багана тохируулах",
	"acc_search": "Данс хайх",
	"reject_text": "Татгалзсан шалтгаан бичих",
	"correct": "Залруулга",
	"bank_find": "Банкны гүйлгээнд баримт хайх",
}
# ``escape.refuse`` sends both of these with ``ctx.reply(text)`` and no markup — the buttons
# they mean are the open prompt's own, which sits *above* (a typed escape never touched it; a
# tapped one has its keyboard put back by ``_revive_prompt``). So neither may say «доорх»:
# the first said «Доорх товчнуудаас сонгоно уу» and pointed at an empty space under itself.
MSG_STEP_CANNOT_SKIP = (
	"Энэ алхмыг алгасах боломжгүй. Дээрх асуултад хариулна уу, эсвэл «Цуцлах» дарж энэ ажлаас гарна уу."
)
MSG_STEP_NO_BACK = (
	"Энэ бол эхний алхам тул буцах алхам алга. Дээрх асуултад хариулна уу, эсвэл «Цуцлах» "
	"дарж энэ ажлаас гарна уу."
)
MSG_ESCAPE_STALE = "Энэ асуулт аль хэдийн хаагдсан байна. /меню — үндсэн цэс."
# A mapping with no date column, or none of the money columns, reads zero lines out of every
# statement in that bank's format for ever after (the row is keyed on the header signature),
# so it is refused before it is written and the accountant is told what is still missing.
# …and a file that has fewer than two columns to give roles to can never satisfy that: a column
# carries one role, and an import needs a date column *and* a money column. The mapping
# conversation is not started for it at all — every answer would come back to the same refusal,
# on a first column that is not even drawn with Буцах.
MSG_STATEMENT_LAYOUT_TOO_FEW_COLUMNS = (
	"Энэ файлд хуулга оруулахад шаардлагатай багана алга: огнооны багана, мөн «Дүн» эсвэл "
	"«Зарлага/Орлого» багана хэрэгтэй. Банкнаасаа бүтэн хуулгыг (Excel/CSV) татаж дахин "
	"илгээнэ үү."
)
MSG_STATEMENT_LAYOUT_NEEDS_DATE = "«Огноо» багана"
MSG_STATEMENT_LAYOUT_NEEDS_AMOUNT = "«Дүн», «Зарлага (дебит)» эсвэл «Орлого (кредит)» багана"
# The refusal fires on the *last* column, so the role that is missing is almost always an
# earlier one: «Буцах» is the action that reaches it, and it is named first. «Цуцлах» throws the
# whole statement away and is what is left when nothing else fits.
MSG_STATEMENT_LAYOUT_INCOMPLETE = (
	"Ийм тохиргоогоор хуулгын мөрүүд уншигдахгүй: {missing} дутуу байна. "
	"«Буцах» дарж тухайн утга байгаа багана руу очиж үүргийг нь зааж өгнө үү. "
	"Энэ багана тохирох бол доорх үүргээс сонгож болно. "
	"Өөр арга байхгүй бол «Цуцлах» дарж хуулгыг дахин илгээнэ үү."
)
MSG_STATEMENT_LAYOUT_CANCELLED = (
	"Баганын тохиргоог зогсоолоо. Хуулга бүртгэгдээгүй тул шаардлагатай бол дахин илгээнэ үү."
)
ONB_INVENTORY_SKIPPED = (
	"Бараа материалын жагсаалтыг алгаслаа. Дараа нь «/эхлэх дахин» гэж бичээд бүртгэж болно."
)
MSG_STATUS = (
	"🛠 Нябо төлөв\n"
	"Компани: {companies} · Холбогдсон хэрэглэгч: {users}\n"
	"Шийдвэрлээгүй санал: {proposals} · Тулгаагүй банкны гүйлгээ: {unmatched}\n"
	"Тохиргоо: {config}"
)
MSG_STATUS_CONFIG_OK = "бүрэн"
MSG_STATUS_CONFIG_MISSING = "дутуу: {keys}"
MSG_ACCOUNT_SEARCH_RESULTS = "Олдсон данс:"
MSG_REJECT_TEXT_ASK = "Татгалзсан шалтгаанаа нэг өгүүлбэрээр бичнэ үү:"
MSG_ONBOARDING_APPLY_PENDING = "Хариултуудыг хадгаллаа; дансны бүртгэлийг админ дуусгасны дараа мэдэгдэнэ."
MSG_ONBOARDING_ALREADY_DONE = "Тохиргоо аль хэдийн хийгдсэн. Дахин хийх бол «/эхлэх дахин» гэж бичнэ үү."
MSG_ONBOARDING_INVENTORY_NEED_FILE = "Excel/CSV файл эсвэл мөр бүрт `нэр, тоо, үнэ` гэсэн текст илгээнэ үү."
ONB_SUMMARY_INVENTORY_NONE = "байхгүй"
ONB_SUMMARY_INVENTORY_COUNT = "{count} бараа"
# The company holds stock but gave no list. Saying "0 бараа" here told the accountant the
# count came out empty, which is a different (and false) statement about the books.
ONB_SUMMARY_INVENTORY_SKIPPED = "байгаа, жагсаалт оруулаагүй — дараа бүртгэнэ"
ONB_SUMMARY_BANKS_NONE = "сонгоогүй"
ONB_SUMMARY_ACCOUNTANT_NONE = "тохируулаагүй"
ONB_BANK_TOGGLE_ON = "✅ {bank}"
ONB_BANK_TOGGLE_OFF = "☐ {bank}"
ONB_CURRENCY_OTHER = "Бусад валют"
ONB_ASK_CURRENCY_CODE = "Валютын кодоо бичнэ үү (жишээ: CNY, EUR):"
ONB_CURRENCY_ADDED = "✅ {currency} валютыг нэмлээ. Хасах бол доорх товчийг дахин дарна уу."
ONB_CURRENCY_CODE_INVALID = "Валютын код гурван латин үсэг байна (жишээ: CNY, EUR). Дахин оролдоно уу."
ONB_CONFIRM_SUMMARY = "Дээрх мэдээлэл зөв үү?"
CARD_BANK_CANDIDATE = "{index}. {voucher} · {date} · {amount}₮ · {party}"
MSG_BANK_EXPENSE_CHOOSE_ACCOUNT = "Энэ гүйлгээг аль дансанд бүртгэх вэ?"
MSG_BANK_TRANSACTION_NOT_FOUND = "Банкны гүйлгээ олдсонгүй: {name}"
MSG_STATEMENT_LAYOUT_DONE = "Баганын тохиргоо: {mapping}"
# Nothing waits on this notice any more: the accountant who mapped the columns confirms them for
# their own company. It exists so a site admin can still see a new format appear and, if they want
# it used by every client on the site, tick the global row in the desk.
MSG_STATEMENT_ADMIN_VERIFY = (
	"🆕 {company}: шинэ банкны формат хадгалагдлаа ({layout}). Нягтлан өөрийн компанидаа "
	"баталгаажуулна; сайт даяар ашиглах бол ERPNext дэсктээс «Баталгаажсан» гэж тэмдэглэнэ."
)
MSG_CLOSE_PDF_CAPTION = "{title} · {period}"
MSG_CLOSE_CANCELLED = "Сарын хаалтыг цуцаллаа."
MSG_POSTED_CARD_FOOTER = "✅ Бүртгэлээ: {doc_name} · Баталсан: {approver}"
MSG_REJECTED_CARD_FOOTER = "❌ Татгалзлаа: {reason}"
MSG_CORRECTION_STARTED = "Залруулга: {doctype} {name}"

# --- rule verification from the chat (/дүрэм) ---------------------------------------------------
# MSG_UNVERIFIED_RULE_BLOCKED promises that an admin checks the rule against the primary text.
# These are the door that promise points at: the list of what is blocking work, the evidence
# behind one rule, and the two answers an admin may give it.
BTN_RULE_LEAVE = "Одоохондоо үлдээх"
BTN_RULE_ACCEPT = "Манай компанид хамаарна"
# The site admin's button on the same card. «Баталгаажуулах» alone beside the accountant's
# button would read as the same act one notch stronger; it is a different act — it speaks for
# every company on the site (VER-08) — so the word says so.
BTN_RULE_VERIFY_SITE = "Сайт даяар баталгаажуулах"
BTN_RULE_ROW = "{index}. {label}"
MSG_RULES_TITLE = "📋 Баталгаажаагүй дүрэм: {count}"
MSG_RULES_INTRO = (
	"Эдгээр дүрмээр бодит бичилт хийгдэхгүй. Дүрэм бүрийг уншиж, өөрийн компанийн "
	"бүртгэлд хамаарах эсэхийг шийднэ үү."
)
MSG_RULES_MORE = "…бас {count} дүрэм байна; бүгдийг ERPNext дэсктээс харна."
MSG_RULES_NONE = "✅ Баталгаажаагүй дүрэм алга байна."
# `/дүрэм` is the accountant's command now (DECISIONS ACC-01): they are the person the refusal
# stops, and they are the person who decides whether an uncited rule applies to the books they
# sign. An owner may not — the tap is a professional judgement, not an approval of one document.
MSG_RULES_ACCOUNTANT_ONLY = (
	"Дүрмийг тухайн компанийн нягтлан хүлээн зөвшөөрнө. Танай нягтлан /дүрэм командаар "
	"дүрмийг үзэж, хамаарах эсэхийг шийднэ."
)
# Keyed by ``rules.verify`` kinds ("p", "t"), which are also what the callback datum carries.
# A posting pattern and a tax parameter are one row for the whole site, so verifying one is a
# decision for every company on it — not a decision an admin of a single company may take
# (DECISIONS VER-08). They still see the list and the evidence: it is their work being blocked.
MSG_RULES_SITE_ADMIN_ONLY = (
	"Энэ дүрэм сайт дээрх бүх компанид нэгэн адил хамаарна. Тиймээс нэг компанийн "
	"админ биш, зөвхөн сайтын админ баталгаажуулна. Сайтын админд хандана уу — "
	"баталгаажаагүй дүрмээс болж бичилт зогсвол түүнд мэдэгдэл очно."
)
RULE_KIND_LABELS = {"p": "бичилтийн загвар", "t": "татварын үзүүлэлт", "b": "хуулгын формат"}
# Keyed in ``rules.verify`` (F-12: the regime name itself is spelled only in rules/regime.py).
RULE_VAT_SCOPE_ANY = "бүх горим"
RULE_VAT_SCOPE_VAT_PAYER = "НӨАТ төлөгч"
RULE_VAT_SCOPE_NON_VAT = "НӨАТ төлөгч бус"
RULE_STATUS_LABELS = {"active": "хүчинтэй", "pending": "хүлээгдэж буй"}
# What one row is *for*, in the list and at the top of its own card: a pattern by the primary
# document it books and the regime it applies to, a parameter by its status and the law it was
# read from. The parameter's status comes first because the line is clipped to one card width
# (rules.verify.PURPOSE_MAX_CHARS) and every seeded law title is longer than that on its own —
# «хүлээгдэж буй» is the half that changes what the admin is looking at, so it must not be the
# half that is cut off.
RULE_PURPOSE_PATTERN = "{document} · {scope}"
RULE_PURPOSE_PARAMETER = "{status} · {source}"
RULE_PURPOSE_LAYOUT = "{bank} · {columns} багана"
CARD_RULE_ROW = "{index}. {label}\n     {purpose}"
CARD_RULE_ROW_USES = "{index}. {label}\n     {purpose} · {uses} удаа хэрэглэсэн"
CARD_RULE_TITLE = "📜 {label}"
CARD_RULE_CODE = "Код: {rule} · {kind}"
# Keyed by ``rules.verify`` kinds, like RULE_KIND_LABELS: the line under the title says what a
# pattern is *for* (a document and a regime), and what state a parameter is *in* — calling a law
# title and «хүлээгдэж буй» a «хамрах хүрээ» told the reader the wrong thing about both.
CARD_RULE_PURPOSE_LABELS = {"p": "Хамрах хүрээ: {purpose}", "t": "Төлөв: {purpose}", "b": "Банк: {purpose}"}
CARD_RULE_PURPOSE = CARD_RULE_PURPOSE_LABELS["p"]
CARD_RULE_USES = "Энэ дүрмээр {uses} санал үүссэн."
CARD_RULE_ENTRY_TITLE = "Бичилт:"
CARD_RULE_ENTRY_LINE = "{side} {account} · {amount}"
CARD_RULE_SIDE_LABELS = {"debit": "Дт", "credit": "Кт"}
CARD_RULE_AMOUNT_LABELS = {
	"gross": "нийт дүн",
	"net": "НӨАТ-гүй дүн",
	"vat": "НӨАТ-ын дүн",
	"": "дүн",
}
CARD_RULE_LINE_OPTIONAL = "заавал биш"
CARD_RULE_VALUE = "Утга: {value} · {unit}"
CARD_RULE_EFFECTIVE = "Хүчинтэй хугацаа: {effective_from} — {effective_to}"
CARD_RULE_OPEN_ENDED = "хязгааргүй"
CARD_RULE_CITATION = "📜 Эх сурвалж: {instrument}, {section}"
CARD_RULE_CITATION_NO_SECTION = "📜 Эх сурвалж: {instrument}"
CARD_RULE_QUOTE = "«{quote}»"
# A quote too long for one bubble. The ellipsis sits inside the guillemets so the fragment can
# never be read as the whole provision, and the line under it says where the rest is.
CARD_RULE_QUOTE_CUT = "«{quote}…»"
CARD_RULE_QUOTE_CUT_NOTE = (
	"✂️ Ишлэл бүтэн багтсангүй. Бүрэн эхийг эх сурвалжийн холбоосоор, "
	"эсвэл ERPNext дэск дэх дүрмийн бичлэгээс уншина уу."
)
CARD_RULE_SOURCE_URL = "🔗 {url}"
# The seed's own briefing for whoever is at the verify button (DECISIONS CORE-18, CORE-19).
# Only the heading is translated: the body is the seed note verbatim, and the seed writes its
# notes in English for the repository's readers. Paraphrasing it here would put a second,
# unreviewed wording of a legal caveat in front of the person taking responsibility for it.
CARD_RULE_BRIEFING_TITLE = "📝 Баталгаажуулбал юуг хүлээн зөвшөөрөх вэ:"
# ...and the card says so, in Mongolian, before the English begins (DECISIONS VER-10). Everything
# else on this card is Mongolian; a reader who meets a paragraph they cannot read on the screen
# where they take responsibility either taps blindly or gives up, and both are worse than being
# told plainly what the paragraph is and what to do instead.
CARD_RULE_BRIEFING_LANGUAGE = (
	"(Тайлбарыг эх сурвалж судалсан хүн англиар бичсэн. Орчуулбал хуулийн агуулга гуйвах "
	"эрсдэлтэй тул хэвээр нь тавив. Уншиж ойлгохгүй бол битгий баталгаажуулаарай — "
	"ERPNext дэск дэх дүрмийн бичлэгээс, эсвэл эх сурвалжийг нь мэддэг хүнээр шалгуулна уу.)"
)
# The same two lines on a rule that is already verified, where nothing is being decided: the
# heading no longer asks what the reader would be accepting, and the note drops the «do not
# verify» advice, which would be an instruction about a decision that has already been taken.
CARD_RULE_BRIEFING_TITLE_VERIFIED = "📝 Энэ дүрмийн тайлбар, ишлэлийн хамрах хүрээ:"
CARD_RULE_BRIEFING_LANGUAGE_VERIFIED = (
	"(Тайлбарыг эх сурвалж судалсан хүн англиар бичсэн; орчуулбал хуулийн агуулга гуйвах "
	"эрсдэлтэй тул хэвээр нь тавив. Бүрэн эхийг ERPNext дэск дэх дүрмийн бичлэгээс уншина уу.)"
)
CARD_RULE_NOTE_CUT = "✂️ Тайлбар бүтэн багтсангүй; бүрэн эхийг ERPNext дэск дэх дүрмийн бичлэгээс уншина уу."
CARD_RULE_NO_CITATION = (
	"⚠️ Хуулийн тодорхой заалт, ишлэл энэ дүрэмд алга. Хүлээн зөвшөөрнө гэдэг нь дээрх агуулгыг "
	"эх сурвалжтай нь өөрөө тулгаж, хариуцлагыг нь хүлээж байгаа хэрэг."
)
# A bank layout has no legal source and never will: what it is read against is the spreadsheet
# the accountant uploaded. Printing «no citation» there would ask them to look for a provision
# that does not exist for a column mapping.
CARD_RULE_LAYOUT_SOURCE = (
	"📄 Энэ бол таны илгээсэн хуулгаас сурсан баганын зураглал; эрх зүйн эх сурвалж байхгүй."
)
CARD_RULE_RESPONSIBILITY = "Баталгаажуулсан хүн, огноо бүртгэгдэж, аудитын мөр үлдэнэ."
CARD_RULE_ASK = "Баталгаажуулах уу?"
# The accountant's own question (DECISIONS ACC-01): not «is this the law», which is the site
# admin's question, but «do these books work this way» — and the answer binds this company only.
CARD_RULE_ACCEPT_RESPONSIBILITY = (
	"Хүлээн зөвшөөрвөл зөвхөн {company}-д хамаарна; бусад компанид хамаарахгүй. "
	"Хэн, хэзээ хүлээн зөвшөөрсөн нь бүртгэгдэж, аудитын мөр үлдэнэ."
)
CARD_RULE_ACCEPT_ASK = "Энэ дүрэм {company}-ийн бүртгэлд хамаарах уу?"
CARD_RULE_ACCEPTED_BY = "✅ {company}-д хамаарна гэж хүлээн зөвшөөрсөн: {user} · {when}"
# The same card for a rule that is already verified: it asks nothing, and it says who vouched
# for it (cards.rule_verified_source) — the seed's citation and a person's tap are not the same
# claim (VER-07). This is the only place in the chat where a verified rule can be read at all.
CARD_RULE_VERIFIED_BY = "✅ Баталгаажсан: {source}"
MSG_RULE_NOT_FOUND = "Дүрэм олдсонгүй: {rule}"
# The write itself failed (verified_by is a Link to User: a session user with no User row stops
# the save). Nothing was verified, so say that, and name the door that still works.
MSG_RULE_VERIFY_FAILED = (
	"«{rule}» дүрмийг баталгаажуулах үед алдаа гарлаа. Дүрэм баталгаажаагүй хэвээр байна. "
	"ERPNext дэсктээс баталгаажуулж үзнэ үү; дахин давтагдвал сайтын админд хандана уу."
)
# Two things wear verified = 1 and they are not the same claim (DECISIONS VER-07): the seed's
# own citation, which no person on this site signed, and a named human's tap. Never print the
# first as if it were the second — an accountant reads a name as somebody having taken the
# responsibility, and there is nobody there.
RULE_VERIFIED_SOURCE_SEED = "Нябогийн эх сурвалжийн ишлэлээр (энэ сайт дээр хүн баталгаажуулаагүй)"
RULE_VERIFIED_SOURCE_PERSON = "{user} · {when}"
MSG_RULE_ALREADY_VERIFIED = "Энэ дүрэм аль хэдийн баталгаажсан: {rule}\nБаталгаажуулсан: {source}"
MSG_RULE_VERIFIED = "✅ Баталгаажлаа: {rule}\nБаталгаажуулсан: {user} · {when}"
MSG_RULE_VERIFIED_RETRY = (
	"Энэ дүрмээр бичилт хийх боломжтой боллоо. Хүлээж байсан баримтын карт дээрх «Батлах» "
	"товчийг дахин дарна уу; зургийг дахин илгээх шаардлагагүй."
)
# The same news, sent to the person whose posting the rule refused — who is not in this chat and
# has been waiting since. MSG_UNVERIFIED_RULE_ADMIN_ASKED promised them exactly this moment, so
# the message names the rule (they may have hit more than one) and repeats the one tap that is left.
MSG_RULE_VERIFIED_FOR_REQUESTER = (
	"✅ «{rule}» дүрэм баталгаажлаа. Энэ дүрмээс болж зогссон баримтынхаа карт дээрх «Батлах» "
	"товчийг дахин дарна уу; зургийг дахин илгээх шаардлагагүй."
)
# The same news after an *acceptance*, which clears the rule for one company only — so the
# sentence names that company instead of claiming the rule is now good everywhere.
MSG_RULE_ACCEPTED_FOR_REQUESTER = (
	"✅ «{rule}» дүрмийг {company}-д хамаарна гэж хүлээн зөвшөөрлөө. Энэ дүрмээс болж зогссон "
	"баримтынхаа карт дээрх «Батлах» товчийг дахин дарна уу; баримтаа дахин илгээх шаардлагагүй."
)
MSG_RULE_LEFT = "Дүрмийг баталгаажуулаагүй үлдээлээ; энэ дүрмээр бичилт хийгдэхгүй хэвээр."
MSG_RULE_VERIFY_IN_DESK = (
	"Энэ дүрмийн кодыг товчинд багтаах боломжгүй тул ERPNext дэсктээс баталгаажуулна уу: {rule}"
)
# --- the refusal, answered where the reader already is ------------------------------------------
# MSG_UNVERIFIED_RULE_BLOCKED plus the way out, which differs by who is reading it. The
# accountant — the main user, and the person whose signature the entry carries — decides it here
# and now; a site admin may still verify the global row; an owner is told which person decides.
MSG_UNVERIFIED_RULE_ACCOUNTANT_CAN_ACCEPT = (
	"Та {company}-ийн нягтлан тул дүрмийг уншаад эндээс хүлээн зөвшөөрч болно. "
	"Хүлээн зөвшөөрмөгц зогссон бичилт үргэлжилнэ; баримтаа дахин илгээх шаардлагагүй."
)
MSG_UNVERIFIED_RULE_ADMIN_CAN_VERIFY = "Та сайтын админ тул энэ дүрмийг сайт даяар баталгаажуулж бас болно."
MSG_RULE_ACCEPTED = (
	"✅ «{rule}» дүрмийг {company}-д хамаарна гэж бүртгэлээ.\nХүлээн зөвшөөрсөн: {user} · {when}"
)
MSG_RULE_ALREADY_ACCEPTED = (
	"Энэ дүрмийг {company}-д аль хэдийн хүлээн зөвшөөрсөн байна: {rule}\nХүлээн зөвшөөрсөн: {user} · {when}"
)
MSG_RULE_ACCEPTED_RETRY = (
	"Энэ дүрмээр бичилт хийх боломжтой боллоо. Хүлээж байсан баримтын карт дээрх «Батлах» "
	"товчийг дахин дарна уу; баримтаа дахин илгээх шаардлагагүй."
)
# The continuation: the accountant's own [Батлах] tap was refused minutes ago on this very
# proposal, and the acceptance removed the only thing standing between it and the ledger, so
# Nyabo finishes what they asked for instead of asking them to press the same button twice.
MSG_RULE_ACCEPTED_POSTING = "Хүлээгдэж байсан бичилтийг үргэлжлүүлж байна…"
MSG_RULE_ACCEPT_FAILED = (
	"«{rule}» дүрмийг хүлээн зөвшөөрөх үед алдаа гарлаа. Дүрэм хүлээн зөвшөөрөгдөөгүй хэвээр байна. "
	"Дахин оролдоод, давтагдвал Нябог тохируулсан хүнд хандана уу."
)
MSG_RULE_ACCEPT_NO_COMPANY = (
	"Идэвхтэй компани сонгогдоогүй байна. Дүрэм компани тус бүрээр хүлээн зөвшөөрөгддөг тул "
	"/компани командаар компаниа сонгоод дахин оролдоно уу."
)
# An owner tapping [Батлах] under an auto-approve policy: the rule is a professional judgement,
# so it is not theirs. The sentence names the person who decides, not a role nobody can find.
MSG_UNVERIFIED_RULE_ACCOUNTANT_ASKED = (
	"Энэ дүрмийг танай компанийн нягтлан хүлээн зөвшөөрнө. Хүсэлтийг бүртгэж, нягтланд "
	"мэдэгдэл илгээлээ. Дараа нь энэ картын «Батлах» товчийг дахин дарахад бичилт хийгдэнэ."
)
# ...and when there is nobody to tell, the promise is not made. The request is on record either
# way, and the next step is named for the person reading it.
MSG_UNVERIFIED_RULE_NO_ACCOUNTANT = (
	"«{rule}» дүрмийг хүлээн зөвшөөрөх нягтлан Нябод холбогдоогүй байна. Хүсэлтийг бүртгэлээ, "
	"гэхдээ мэдэгдэл очих хүн алга. Нягтлангаа Нябод холбуулсны дараа тэр /дүрэм командаар "
	"дүрмийг хүлээн зөвшөөрнө; тэгсний дараа энэ картын «Батлах» товчийг дахин дарна уу."
)
MSG_ACCOUNTANT_RULE_ACCEPT_REQUEST = (
	"🔒 {company}: «{rule}» дүрэм баталгаажаагүй тул бичилт зогслоо. /дүрэм командаар дүрмийг "
	"үзэж, компанидаа хамаарах эсэхийг шийднэ үү."
)
MSG_ADMIN_RULE_VERIFY_REQUEST = (
	"🔒 {company}: «{rule}» дүрэм баталгаажаагүй тул бичилт зогслоо. Тухайн компанийн нягтлан "
	"өөрөө хүлээн зөвшөөрч болно; сайт даяар хүчинтэй ишлэл олдвол /дүрэм командаар баталгаажуулна уу."
)

# --- evals + simulator (nyabo_mn.evals, nyabo_mn.simulator) -----------------------------------------
SIM_TITLE = "🧪 Симуляци · {case}"
SIM_REGIME_VAT_PAYER = "НӨАТ төлөгч"
SIM_REGIME_SIMPLIFIED = "Хялбаршуулсан 1% (НӨАТ төлөгч бус)"
SIM_COLUMN_HEADER = "{regime} · {date}"
SIM_DOCUMENT_KIND = {
	"purchase_invoice": "Худалдан авалтын нэхэмжлэх",
	"journal_entry": "Ерөнхий журналын бичилт",
}
SIM_LINE = "{side} {code} {name} {amount}₮"
SIM_VAT_LINE = "НӨАТ: {treatment}"
SIM_NO_ENTRY = "Бичилт үүсгэсэнгүй: {reason}"
SIM_NEEDS_ACCOUNTANT = "⚠️ Нягтлан батална"
SIM_AUTO_OK = "Эзэмшигч батлах боломжтой"
SIM_EXPLANATION = "Тайлбар: {explanation}"
SIM_CITATION = "📜 {citation}"
SIM_STATEMENT_TITLE = "🏦 Хуулгын симуляци · {path}"
SIM_STATEMENT_LINE = "{date} · {amount}₮ · «{description}» → {result}"
SIM_STATEMENT_NO_LAYOUT = "Хуулгын форматыг танисангүй; баганын утгыг нягтлан зааж өгнө."
SIM_COMPANY_CLEANUP_FAILED = "Түр компанийг ({company}) устгаж чадсангүй: {error}"
EVAL_FLAG_LABELS = {
	"low_confidence": "танилт тодорхойгүй",
	"injection_suspected": "гадны заавар илэрсэн",
	"new_supplier": "шинэ харилцагч",
	"unverified_rule": "дүрэм баталгаажаагүй",
	"no_ebarimt": "и-баримтгүй баримт",
	"duplicate": "давхардсан баримт",
	"wrong_company": "өөр компанийн баримт",
	"foreign_currency": "гадаад валютын гүйлгээ",
	"seller_not_vat_payer": "худалдагч НӨАТ төлөгч бус",
	"vat_inconsistent": "НӨАТ-ын дүн зөрүүтэй",
	"entry_invalid": "бичилт шалгалтад тэнцсэнгүй",
	"low_classification_confidence": "дансны сонголт тодорхойгүй",
}
EVAL_NIGHTLY_REASON = "{day} өдрийн залруулгаас {created} үнэлгээний тохиолдол үүсгэв."
MSG_EVAL_CASE_BAD_JSON = "«{field}» талбарын JSON буруу байна: {error}"
MSG_EVAL_CASE_REGIME_REQUIRED = "«{kind}» төрлийн тохиолдолд татварын горим заавал хэрэгтэй."
