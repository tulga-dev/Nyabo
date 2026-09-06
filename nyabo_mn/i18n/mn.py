"""Every user-facing string in one place (Mongolian Cyrillic, polite form).

Edit wording here; code refers to names, never to literal text. Phase 0 seeds the
accounting names and the common buttons; each phase adds its own section.
"""

from __future__ import annotations

# --- Product ---------------------------------------------------------------
PRODUCT_NAME = "Нябо"

# --- Buttons (state changes; the LLM never generates these) -----------------
BTN_APPROVE = "Батлах"
BTN_CHANGE_ACCOUNT = "Данс солих"
BTN_REJECT = "Татгалзах"
BTN_LATER = "Дараа"
BTN_FIND_DOCUMENT = "Баримт хайх"
BTN_RECORD_EXPENSE = "Зардал бүртгэх"
BTN_CONFIRM = "Баталгаажуулах"
BTN_CANCEL = "Цуцлах"

# --- Rejection reasons (one tap) --------------------------------------------
REJECT_PERSONAL = "Хувийн зардал"
REJECT_DUPLICATE = "Давхардсан"
REJECT_WRONG_COMPANY = "Буруу компани"
REJECT_OTHER = "Бусад"

# --- Generic messages -------------------------------------------------------
MSG_DUPLICATE_DOCUMENT = "Энэ баримт өмнө нь илгээгдсэн."
MSG_POSTED = "✅ Бүртгэлээ: {doc_name}"
MSG_NOT_LINKED = "Таны Telegram хаяг Нябо-д холбогдоогүй байна. Админаас холболтын код авна уу."
MSG_ERROR_GENERIC = "Уучлаарай, алдаа гарлаа. Дахин оролдоно уу."

# --- Accounting vocabulary (from the glossary; used on cards and in reports) --
VAT = "НӨАТ"
VAT_PAYER = "НӨАТ төлөгч"
VAT_NON_PAYER = "НӨАТ төлөгч бус"
VAT_WITHHELD = "суутгана"
VAT_IN_EXPENSE = "зардалд орно"
EBARIMT = "И-баримт"
EBARIMT_VERIFIED = "ebarimt ✓"
EBARIMT_UNVERIFIED = "ebarimt ✗"
TRIAL_BALANCE = "Гүйлгээ баланс"
CHART_OF_ACCOUNTS = "Дансны төлөвлөгөө"
ACCOUNT = "Данс"
SUPPLIER = "Харилцагч"
AMOUNT = "Дүн"
DATE = "Огноо"
RULE = "дүрэм"
EXPLANATION = "Тайлбар"

# --- Custom field labels on ERPNext documents --------------------------------
LBL_SECTION_EBARIMT = "Нябо · И-баримт"
LBL_EBARIMT_RECEIPT_ID = "И-баримтын дугаар"
LBL_EBARIMT_LOTTERY_NO = "Сугалааны дугаар"
LBL_EBARIMT_DATETIME = "И-баримтын огноо, цаг"
LBL_EBARIMT_VERIFIED = "И-баримт баталгаажсан"
LBL_EBARIMT_QR_DATA = "QR өгөгдөл"
LBL_EBARIMT_CUSTOMER_TIN = "Худалдан авагчийн ТТД / РД"
LBL_SOURCE_DOCUMENT = "Эх баримт (Нябо)"
LBL_NYABO_PROPOSAL = "Нябо санал"
LBL_NYABO_EXPLANATION = "Тайлбар (Нябо)"
LBL_NYABO_PROMPT_VERSION = "Промптын хувилбар"
LBL_REGISTER_NO = "Регистрийн дугаар"
LBL_TIN = "ТТД (TIN)"

# --- Tax template titles (used by nyabo_mn.setup.taxes) ----------------------
TAX_SALES_VAT_10 = "НӨАТ 10%"
TAX_PURCHASE_VAT_10 = "Татан суутгах НӨАТ 10%"
TAX_ITEM_EXEMPT = "НӨАТ-аас чөлөөлөгдсөн"
TAX_ITEM_ZERO = "Тэг хувийн НӨАТ"
