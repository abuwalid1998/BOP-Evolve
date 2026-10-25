"""Synthetic catalogue of case types, policies and rules used by the seed and the simulated connectors.

Everything here is fictional demo content. It is not the Bank of Palestine's
actual policy wording and must be replaced by policy-owner-approved rules.
"""

CASE_TYPES: dict[str, dict] = {
    "account_opening": {
        "policy": ("KYC-01", "Customer identification & verification", "التحقق من هوية العميل"),
        "rule": "KYC_DOC_CHECK",
        "severity": "high",
        "description": (
            "Identity document verification not completed before account activation.",
            "لم يتم استكمال التحقق من وثيقة الهوية قبل تفعيل الحساب.",
        ),
        "expected": (
            "Verify the original ID document and record the verification step before activating the account.",
            "التحقق من وثيقة الهوية الأصلية وتسجيل خطوة التحقق قبل تفعيل الحساب.",
        ),
        "observed": (
            "Account activated; verification step recorded after activation.",
            "تم تفعيل الحساب وتسجيل خطوة التحقق بعد التفعيل.",
        ),
        "factors": {"individual_action": 0.55, "process_design": 0.2, "system_issue": 0.15, "workload": 0.1},
    },
    "cash_transaction": {
        "policy": ("CASH-04", "Cash transaction limits & dual control", "حدود المعاملات النقدية والرقابة المزدوجة"),
        "rule": "CASH_DUAL_APPROVAL",
        "severity": "high",
        "description": (
            "Cash withdrawal above the threshold processed without second approval.",
            "تمت معالجة سحب نقدي يتجاوز الحد دون موافقة ثانية.",
        ),
        "expected": (
            "Obtain and record a second authoriser's approval before paying out above the threshold.",
            "الحصول على موافقة مفوض ثانٍ وتسجيلها قبل صرف مبلغ يتجاوز الحد.",
        ),
        "observed": (
            "Payout completed; second approval missing in the transaction log.",
            "تم الصرف مع غياب الموافقة الثانية في سجل المعاملة.",
        ),
        "factors": {"individual_action": 0.6, "workload": 0.25, "system_issue": 0.15},
    },
    "complaint_handling": {
        "policy": ("CMP-02", "Complaint acknowledgement & resolution", "استلام الشكاوى ومعالجتها"),
        "rule": "COMPLAINT_ACK_SLA",
        "severity": "medium",
        "description": (
            "Complaint not acknowledged within two business days.",
            "لم يتم الإقرار باستلام الشكوى خلال يومي عمل.",
        ),
        "expected": (
            "Acknowledge the complaint and share the reference number within two business days.",
            "الإقرار باستلام الشكوى وإبلاغ رقمها المرجعي خلال يومي عمل.",
        ),
        "observed": (
            "Acknowledgement sent on business day four.",
            "تم إرسال الإقرار في يوم العمل الرابع.",
        ),
        "factors": {"individual_action": 0.35, "workload": 0.35, "process_design": 0.2, "policy_ambiguity": 0.1},
    },
    "card_services": {
        "policy": ("CRD-03", "Card issuance disclosures", "الإفصاح عند إصدار البطاقات"),
        "rule": "CARD_FEE_DISCLOSURE",
        "severity": "medium",
        "description": (
            "Card fees and key terms not disclosed before issuance.",
            "لم يتم الإفصاح عن رسوم البطاقة وشروطها الأساسية قبل الإصدار.",
        ),
        "expected": (
            "Explain fees and key terms and record the customer's acknowledgement before issuance.",
            "شرح الرسوم والشروط الأساسية وتسجيل إقرار العميل قبل الإصدار.",
        ),
        "observed": (
            "Card issued; disclosure checklist incomplete.",
            "تم إصدار البطاقة وقائمة الإفصاح غير مكتملة.",
        ),
        "factors": {"individual_action": 0.45, "policy_ambiguity": 0.35, "process_design": 0.2},
    },
    "transfers": {
        "policy": ("TRF-01", "Transfer beneficiary confirmation", "تأكيد بيانات المستفيد في الحوالات"),
        "rule": "TRF_BENEFICIARY_READBACK",
        "severity": "high",
        "description": (
            "Beneficiary details not read back to the customer before submission.",
            "لم تتم قراءة بيانات المستفيد للعميل قبل إرسال الحوالة.",
        ),
        "expected": (
            "Read back beneficiary name and account and obtain confirmation before submitting.",
            "قراءة اسم المستفيد ورقم حسابه والحصول على تأكيد العميل قبل الإرسال.",
        ),
        "observed": (
            "Transfer submitted without a recorded read-back step.",
            "تم إرسال الحوالة دون تسجيل خطوة القراءة والتأكيد.",
        ),
        "factors": {"individual_action": 0.5, "system_issue": 0.3, "workload": 0.2},
    },
    "general_inquiry": {
        "policy": ("SRV-05", "Product information accuracy", "دقة معلومات المنتجات"),
        "rule": "INFO_ACCURACY",
        "severity": "low",
        "description": (
            "Product information provided did not match the current product sheet.",
            "المعلومات المقدمة لم تطابق نشرة المنتج الحالية.",
        ),
        "expected": (
            "Use the current product sheet and confirm details before advising the customer.",
            "استخدام نشرة المنتج الحالية والتأكد من التفاصيل قبل إرشاد العميل.",
        ),
        "observed": (
            "Outdated rate quoted from a superseded product sheet.",
            "تم ذكر سعر قديم من نشرة منتج ملغاة.",
        ),
        "factors": {"individual_action": 0.4, "policy_ambiguity": 0.25, "process_design": 0.35},
    },
    "loan_inquiry": {
        "policy": ("LND-02", "Responsible lending conversation", "المحادثة الإقراضية المسؤولة"),
        "rule": "LOAN_AFFORDABILITY_QS",
        "severity": "medium",
        "description": (
            "Affordability questions not asked before discussing a financing product.",
            "لم تُطرح أسئلة القدرة على السداد قبل مناقشة منتج تمويلي.",
        ),
        "expected": (
            "Complete the affordability questions before recommending a financing product.",
            "استكمال أسئلة القدرة على السداد قبل التوصية بمنتج تمويلي.",
        ),
        "observed": (
            "Financing options presented; affordability checklist not started.",
            "تم عرض خيارات التمويل دون البدء بقائمة القدرة على السداد.",
        ),
        "factors": {"individual_action": 0.5, "policy_ambiguity": 0.3, "workload": 0.2},
    },
}

INTERACTION_TYPES = ("branch_counter", "phone", "chat", "email")

ACTION_TEMPLATES = {
    "coaching": ("One-to-one coaching on the expected procedure", "جلسة توجيه فردية حول الإجراء المتوقع"),
    "training": ("Complete the refresher module and knowledge check", "إكمال وحدة التنشيط واختبار المعرفة"),
    "job_aid": ("Use the step-by-step job aid for the next 20 cases", "استخدام دليل العمل خطوة بخطوة لأول 20 حالة"),
    "practice": ("Role-play practice scenario with team lead", "تمرين محاكاة مع قائد الفريق"),
    "policy_clarification": ("Request clarification from the policy owner", "طلب توضيح من مالك السياسة"),
    "system_fix": ("Raise a system change request for the missing control", "رفع طلب تعديل نظام للضابط المفقود"),
}


def explanation(case_type: str, policy_version: str, lang: str) -> str:
    spec = CASE_TYPES[case_type]
    i = 0 if lang == "en" else 1
    code = spec["policy"][0]
    if lang == "en":
        return (
            f"Control rule {spec['rule']} flagged this case under policy {code} v{policy_version}. "
            f"{spec['description'][i]} Expected: {spec['expected'][i]}"
        )
    return (
        f"رصدت قاعدة الضبط {spec['rule']} هذه الحالة بموجب السياسة {code} الإصدار {policy_version}. "
        f"{spec['description'][i]} المتوقع: {spec['expected'][i]}"
    )


# --------------------------------------------------------------------------- rules engine
# Procedural facts recorded on each synthetic case. Rules are conditions over these facts.
# Each field: type, EN/AR label, the case types it applies to (None = every case type),
# enum options or numeric unit and bounds.
FIELDS: dict[str, dict] = {
    "interaction_type": {
        "type": "enum",
        "label": ("Service channel", "قناة الخدمة"),
        "case_types": None,
        "options": [
            ("branch_counter", "Branch counter", "شباك الفرع"),
            ("phone", "Phone", "الهاتف"),
            ("chat", "Digital chat", "المحادثة الرقمية"),
            ("email", "Email", "البريد الإلكتروني"),
        ],
    },
    "complexity_band": {
        "type": "enum",
        "label": ("Case complexity", "درجة تعقيد الحالة"),
        "case_types": None,
        "options": [("low", "Low", "منخفضة"), ("medium", "Medium", "متوسطة"), ("high", "High", "مرتفعة")],
    },
    "hour_of_day": {
        "type": "number",
        "label": ("Hour of service (24h)", "ساعة تقديم الخدمة (24 ساعة)"),
        "case_types": None,
        "unit": ("h", "س"),
        "min": 0,
        "max": 23,
    },
    "queue_wait_minutes": {
        "type": "number",
        "label": ("Customer waiting time", "مدة انتظار العميل"),
        "case_types": None,
        "unit": ("min", "دقيقة"),
        "min": 0,
        "max": 240,
    },
    "id_verified_before_activation": {
        "type": "bool",
        "label": ("ID verified before account activation", "التحقق من الهوية قبل تفعيل الحساب"),
        "case_types": ["account_opening"],
    },
    "customer_segment": {
        "type": "enum",
        "label": ("Customer segment", "شريحة العميل"),
        "case_types": ["account_opening"],
        "options": [
            ("individual", "Individual", "أفراد"),
            ("sme", "Small business", "منشآت صغيرة"),
            ("corporate", "Corporate", "شركات"),
        ],
    },
    "customer_risk_rating": {
        "type": "enum",
        "label": ("Customer risk rating (KYC)", "تصنيف مخاطر العميل (اعرف عميلك)"),
        "case_types": ["account_opening"],
        "options": [("low", "Low", "منخفض"), ("medium", "Medium", "متوسط"), ("high", "High", "مرتفع")],
    },
    "transaction_kind": {
        "type": "enum",
        "label": ("Cash transaction type", "نوع المعاملة النقدية"),
        "case_types": ["cash_transaction"],
        "options": [("withdrawal", "Withdrawal", "سحب"), ("deposit", "Deposit", "إيداع")],
    },
    "amount_ils": {
        "type": "number",
        "label": ("Amount (ILS equivalent)", "المبلغ (بما يعادل الشيكل)"),
        "case_types": ["cash_transaction", "transfers"],
        "unit": ("ILS", "شيكل"),
        "min": 0,
        "max": 1_000_000,
    },
    "second_approval_recorded": {
        "type": "bool",
        "label": ("Second authoriser approval recorded", "تسجيل موافقة المفوض الثاني"),
        "case_types": ["cash_transaction"],
    },
    "ack_business_days": {
        "type": "number",
        "label": ("Business days to acknowledge", "أيام العمل حتى الإقرار بالاستلام"),
        "case_types": ["complaint_handling"],
        "unit": ("days", "يوم"),
        "min": 0,
        "max": 30,
    },
    "reference_shared": {
        "type": "bool",
        "label": ("Complaint reference shared with customer", "إبلاغ العميل بالرقم المرجعي للشكوى"),
        "case_types": ["complaint_handling"],
    },
    "card_product": {
        "type": "enum",
        "label": ("Card product", "نوع البطاقة"),
        "case_types": ["card_services"],
        "options": [
            ("debit", "Debit", "مدينة"),
            ("credit", "Credit", "ائتمانية"),
            ("prepaid", "Prepaid", "مسبقة الدفع"),
        ],
    },
    "fees_disclosed": {
        "type": "bool",
        "label": ("Fees and key terms disclosed", "الإفصاح عن الرسوم والشروط الأساسية"),
        "case_types": ["card_services"],
    },
    "customer_acknowledgement_recorded": {
        "type": "bool",
        "label": ("Customer acknowledgement recorded", "تسجيل إقرار العميل"),
        "case_types": ["card_services"],
    },
    "transfer_scope": {
        "type": "enum",
        "label": ("Transfer type", "نوع الحوالة"),
        "case_types": ["transfers"],
        "options": [("domestic", "Domestic", "محلية"), ("international", "International", "خارجية")],
    },
    "new_beneficiary": {
        "type": "bool",
        "label": ("First transfer to this beneficiary", "أول حوالة لهذا المستفيد"),
        "case_types": ["transfers"],
    },
    "beneficiary_readback": {
        "type": "bool",
        "label": ("Beneficiary details read back and confirmed", "قراءة بيانات المستفيد وتأكيدها"),
        "case_types": ["transfers"],
    },
    "inquiry_topic": {
        "type": "enum",
        "label": ("Inquiry topic", "موضوع الاستفسار"),
        "case_types": ["general_inquiry"],
        "options": [
            ("rates", "Rates & returns", "الأسعار والعوائد"),
            ("fees", "Fees & charges", "الرسوم والعمولات"),
            ("products", "Product features", "خصائص المنتجات"),
            ("services", "Branch & digital services", "خدمات الفروع والخدمات الرقمية"),
        ],
    },
    "product_sheet_current": {
        "type": "bool",
        "label": ("Current product sheet used", "استخدام نشرة المنتج السارية"),
        "case_types": ["general_inquiry"],
    },
    "financing_discussed": {
        "type": "bool",
        "label": ("Financing product discussed", "مناقشة منتج تمويلي"),
        "case_types": ["loan_inquiry"],
    },
    "affordability_checked": {
        "type": "bool",
        "label": ("Affordability assessment completed", "استكمال تقييم القدرة على السداد"),
        "case_types": ["loan_inquiry"],
    },
}

OPERATORS: dict[str, dict] = {
    "eq": {"types": ("enum", "number"), "label": ("equals", "يساوي")},
    "neq": {"types": ("enum", "number"), "label": ("does not equal", "لا يساوي")},
    "in": {"types": ("enum",), "label": ("is one of", "أحد القيم")},
    "not_in": {"types": ("enum",), "label": ("is none of", "ليس من القيم")},
    "gt": {"types": ("number",), "label": ("is greater than", "أكبر من")},
    "gte": {"types": ("number",), "label": ("is at least", "لا يقل عن")},
    "lt": {"types": ("number",), "label": ("is less than", "أقل من")},
    "lte": {"types": ("number",), "label": ("is at most", "لا يزيد عن")},
    "is_true": {"types": ("bool",), "label": ("= Yes", "= نعم")},
    "is_false": {"types": ("bool",), "label": ("= No", "= لا")},
}

RULE_NAMES: dict[str, tuple[str, str]] = {
    "KYC_DOC_CHECK": ("Identity verified before account activation", "التحقق من الهوية قبل تفعيل الحساب"),
    "CASH_DUAL_APPROVAL": ("Dual control on large cash withdrawals", "الرقابة المزدوجة على السحوبات النقدية الكبيرة"),
    "COMPLAINT_ACK_SLA": ("Complaint acknowledged within two business days", "الإقرار بالشكوى خلال يومي عمل"),
    "CARD_FEE_DISCLOSURE": ("Card fees disclosed before issuance", "الإفصاح عن رسوم البطاقة قبل الإصدار"),
    "TRF_BENEFICIARY_READBACK": ("Beneficiary read-back before transfer", "تأكيد بيانات المستفيد قبل الحوالة"),
    "INFO_ACCURACY": ("Advice based on the current product sheet", "الإرشاد وفق نشرة المنتج السارية"),
    "LOAN_AFFORDABILITY_QS": (
        "Affordability assessed before financing advice",
        "تقييم القدرة على السداد قبل عرض التمويل",
    ),
}


def _c(field: str, op: str, value=None) -> dict:
    return {"field": field, "op": op, "value": value}


# Version "1" applied under the superseded policy, version "2" under the current one.
DEFAULT_CONDITIONS: dict[str, dict[str, dict]] = {
    "KYC_DOC_CHECK": {
        "1": {"match": "all", "conditions": [_c("id_verified_before_activation", "is_false")]},
        "2": {"match": "all", "conditions": [_c("id_verified_before_activation", "is_false")]},
    },
    "CASH_DUAL_APPROVAL": {
        "1": {
            "match": "all",
            "conditions": [
                _c("transaction_kind", "eq", "withdrawal"),
                _c("amount_ils", "gt", 25000),
                _c("second_approval_recorded", "is_false"),
            ],
        },
        "2": {
            "match": "all",
            "conditions": [
                _c("transaction_kind", "eq", "withdrawal"),
                _c("amount_ils", "gt", 20000),
                _c("second_approval_recorded", "is_false"),
            ],
        },
    },
    "COMPLAINT_ACK_SLA": {
        "1": {"match": "all", "conditions": [_c("ack_business_days", "gt", 3)]},
        "2": {"match": "all", "conditions": [_c("ack_business_days", "gt", 2)]},
    },
    "CARD_FEE_DISCLOSURE": {
        "1": {"match": "all", "conditions": [_c("fees_disclosed", "is_false")]},
        "2": {
            "match": "any",
            "conditions": [_c("fees_disclosed", "is_false"), _c("customer_acknowledgement_recorded", "is_false")],
        },
    },
    "TRF_BENEFICIARY_READBACK": {
        "1": {"match": "all", "conditions": [_c("beneficiary_readback", "is_false")]},
        "2": {"match": "all", "conditions": [_c("beneficiary_readback", "is_false")]},
    },
    "INFO_ACCURACY": {
        "1": {"match": "all", "conditions": [_c("product_sheet_current", "is_false")]},
        "2": {"match": "all", "conditions": [_c("product_sheet_current", "is_false")]},
    },
    "LOAN_AFFORDABILITY_QS": {
        "1": {
            "match": "all",
            "conditions": [_c("financing_discussed", "is_true"), _c("affordability_checked", "is_false")],
        },
        "2": {
            "match": "all",
            "conditions": [_c("financing_discussed", "is_true"), _c("affordability_checked", "is_false")],
        },
    },
}


def fields_for(case_type: str) -> list[str]:
    return [k for k, f in FIELDS.items() if f["case_types"] is None or case_type in f["case_types"]]


def generate_attributes(case_type: str, interaction_type: str, complexity_band: str, rng, breach: bool = False) -> dict:
    """Synthetic procedural facts for one case.

    ``breach`` produces facts that deviate from the procedure the case type's default
    rule checks; otherwise the facts are compliant (with realistic near misses, such as a
    large withdrawal that *did* get its second approval). Breaches skew towards longer
    queues and late hours so behavioural early-warning rules have a signal to find.
    """
    attrs: dict = {
        "interaction_type": interaction_type,
        "complexity_band": complexity_band,
        "hour_of_day": rng.choice((15, 16, 16, 17)) if breach and rng.random() < 0.45 else rng.randint(8, 16),
        "queue_wait_minutes": int(min(240, rng.lognormvariate(2.9 if breach else 2.0, 0.6))),
    }
    if case_type == "account_opening":
        attrs["customer_segment"] = rng.choices(("individual", "sme", "corporate"), (8, 3, 1))[0]
        attrs["customer_risk_rating"] = rng.choices(("low", "medium", "high"), (6, 3, 1))[0]
        attrs["id_verified_before_activation"] = not breach
    elif case_type == "cash_transaction":
        if breach:
            attrs["transaction_kind"] = "withdrawal"
            attrs["amount_ils"] = rng.randrange(26000, 80000, 500)
            attrs["second_approval_recorded"] = False
        else:
            attrs["transaction_kind"] = rng.choice(("withdrawal", "deposit"))
            attrs["amount_ils"] = int(min(150000, rng.lognormvariate(8.6, 1.1)))
            # Above the threshold, compliant withdrawals carry the second approval.
            attrs["second_approval_recorded"] = attrs["amount_ils"] > 20000 or rng.random() < 0.1
    elif case_type == "complaint_handling":
        attrs["ack_business_days"] = rng.randint(4, 7) if breach else rng.choices((0, 1, 2), (4, 4, 2))[0]
        attrs["reference_shared"] = (not breach) or rng.random() < 0.5
    elif case_type == "card_services":
        attrs["card_product"] = rng.choices(("debit", "credit", "prepaid"), (5, 3, 2))[0]
        attrs["fees_disclosed"] = not breach
        attrs["customer_acknowledgement_recorded"] = (not breach) or rng.random() < 0.3
    elif case_type == "transfers":
        attrs["transfer_scope"] = rng.choices(("domestic", "international"), (7, 3))[0]
        attrs["amount_ils"] = int(min(250000, rng.lognormvariate(8.0, 1.2)))
        attrs["new_beneficiary"] = rng.random() < (0.6 if breach else 0.25)
        attrs["beneficiary_readback"] = not breach
    elif case_type == "general_inquiry":
        attrs["inquiry_topic"] = rng.choice(("rates", "fees", "products", "services"))
        attrs["product_sheet_current"] = not breach
    elif case_type == "loan_inquiry":
        attrs["financing_discussed"] = breach or rng.random() < 0.6
        attrs["affordability_checked"] = (not breach) and attrs["financing_discussed"]
    return attrs
