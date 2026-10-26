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
    """Facts a rule for ``case_type`` may use. Common (None) facts belong to customer-service types only."""
    return [
        k
        for k, f in FIELDS.items()
        if (f["case_types"] is None and case_type in CASE_TYPES) or (f["case_types"] and case_type in f["case_types"])
    ]


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


# --------------------------------------------------------------------------- workplace policies
# Internal HR policies evaluated on daily time-clock records and supervisor observations.
# Same rule language and approval workflow as the customer-service controls.
WORKPLACE_TYPES: dict[str, dict] = {
    "attendance": {
        "label": ("Attendance & working time", "الحضور ووقت العمل"),
        "source": ("Daily time-clock record", "سجل ساعة الدوام اليومي"),
    },
    "dress_code": {
        "label": ("Dress code & appearance", "اللباس والمظهر المهني"),
        "source": ("Supervisor observation", "ملاحظة المشرف"),
    },
}

WEEKDAYS = [
    ("sat", "Saturday", "السبت"),
    ("sun", "Sunday", "الأحد"),
    ("mon", "Monday", "الاثنين"),
    ("tue", "Tuesday", "الثلاثاء"),
    ("wed", "Wednesday", "الأربعاء"),
    ("thu", "Thursday", "الخميس"),
    ("fri", "Friday", "الجمعة"),
]

FIELDS.update(
    {
        "minutes_late": {
            "type": "number",
            "label": ("Minutes late at check-in", "دقائق التأخر عند تسجيل الدخول"),
            "case_types": ["attendance"],
            "unit": ("min", "دقيقة"),
            "min": 0,
            "max": 600,
        },
        "early_leave_minutes": {
            "type": "number",
            "label": ("Minutes left before end of shift", "دقائق المغادرة قبل نهاية الدوام"),
            "case_types": ["attendance"],
            "unit": ("min", "دقيقة"),
            "min": 0,
            "max": 600,
        },
        "missing_check_in": {
            "type": "bool",
            "label": ("Check-in missing", "تسجيل الدخول مفقود"),
            "case_types": ["attendance"],
        },
        "missing_check_out": {
            "type": "bool",
            "label": ("Check-out missing", "تسجيل الخروج مفقود"),
            "case_types": ["attendance"],
        },
        "unapproved_absence": {
            "type": "bool",
            "label": ("Absent without approved leave", "غياب دون إجازة معتمدة"),
            "case_types": ["attendance"],
        },
        "break_minutes": {
            "type": "number",
            "label": ("Total break time", "مجموع وقت الاستراحة"),
            "case_types": ["attendance"],
            "unit": ("min", "دقيقة"),
            "min": 0,
            "max": 600,
        },
        "break_overrun_minutes": {
            "type": "number",
            "label": ("Break time beyond the allowance", "وقت الاستراحة الزائد عن المسموح"),
            "case_types": ["attendance"],
            "unit": ("min", "دقيقة"),
            "min": 0,
            "max": 600,
        },
        "break_count": {
            "type": "number",
            "label": ("Number of breaks", "عدد الاستراحات"),
            "case_types": ["attendance"],
            "min": 0,
            "max": 20,
        },
        "weekday": {
            "type": "enum",
            "label": ("Day of the week", "يوم الأسبوع"),
            "case_types": ["attendance"],
            "options": WEEKDAYS,
        },
        "customer_facing": {
            "type": "bool",
            "label": ("Customer-facing role", "وظيفة تتعامل مع العملاء"),
            "case_types": ["attendance", "dress_code"],
        },
        "dress_item": {
            "type": "enum",
            "label": ("Area observed", "البند الملاحَظ"),
            "case_types": ["dress_code"],
            "options": [
                ("formal_attire", "Formal business attire", "اللباس الرسمي"),
                ("id_badge", "Staff ID badge worn", "ارتداء بطاقة الموظف"),
                ("uniform", "Branch uniform", "الزي الموحد للفرع"),
                ("grooming", "Grooming & presentation", "المظهر العام"),
            ],
        },
        "dress_compliant": {
            "type": "bool",
            "label": ("Dress code met", "الالتزام بقواعد اللباس"),
            "case_types": ["dress_code"],
        },
        "prior_dress_issues_90d": {
            "type": "number",
            "label": ("Earlier dress-code issues (90 days)", "ملاحظات لباس سابقة (90 يوماً)"),
            "case_types": ["dress_code"],
            "min": 0,
            "max": 50,
        },
    }
)

# Policies and rules shipped with the demo (rule code -> definition). Thresholds are illustrative.
WORKPLACE_POLICIES: dict[str, dict] = {
    "HR-01": {
        "title": ("Working hours & attendance", "ساعات العمل والحضور"),
        "summary": (
            "Staff check in by the start of their scheduled shift and check out at its end using the time clock. "
            "Absence requires approved leave; a missing check-in or check-out must be corrected with the line "
            "manager the same day.",
            "يسجّل الموظفون دخولهم عند بداية الدوام المقرر وخروجهم عند نهايته عبر ساعة الدوام. ويتطلب الغياب "
            "إجازة معتمدة، ويجب تصحيح أي تسجيل دخول أو خروج مفقود مع المدير المباشر في اليوم نفسه.",
        ),
    },
    "HR-02": {
        "title": ("Breaks", "الاستراحات"),
        "summary": (
            "Breaks are taken within the daily allowance of 60 minutes and scheduled so that counters and "
            "phones stay covered during opening hours.",
            "تؤخذ الاستراحات ضمن الحد اليومي المسموح البالغ 60 دقيقة، وتُنظَّم بحيث تبقى الشبابيك والهواتف "
            "مغطاة خلال ساعات العمل.",
        ),
    },
    "HR-03": {
        "title": ("Dress code & professional appearance", "قواعد اللباس والمظهر المهني"),
        "summary": (
            "Staff wear formal business attire or the branch uniform and display their staff ID badge at all "
            "times; customer-facing staff are held to this standard at the counter.",
            "يرتدي الموظفون اللباس الرسمي أو الزي الموحد للفرع ويُظهرون بطاقة الموظف في جميع الأوقات، "
            "ويلتزم موظفو الواجهة بهذا المعيار عند الشباك.",
        ),
    },
}

WORKPLACE_RULES: dict[str, dict] = {
    "HR_LATE_ARRIVAL": {
        "policy": "HR-01",
        "category": "attendance",
        "severity": "low",
        "name": ("Late check-in beyond the grace period", "تأخر في تسجيل الدخول بعد فترة السماح"),
        "description": (
            "Arriving after the shift starts leaves counters and phones uncovered and delays customers.",
            "الوصول بعد بدء الدوام يترك الشبابيك والهواتف دون تغطية ويؤخر خدمة العملاء.",
        ),
        "expected": ("Check in by the scheduled start time.", "تسجيل الدخول بحلول موعد بدء الدوام المقرر."),
        "observed": ("Check-in recorded after the grace period.", "سُجّل الدخول بعد انتهاء فترة السماح."),
        "conditions": {"match": "all", "conditions": [{"field": "minutes_late", "op": "gt", "value": 10}]},
    },
    "HR_EARLY_LEAVE": {
        "policy": "HR-01",
        "category": "attendance",
        "severity": "low",
        "name": ("Check-out before the end of shift", "تسجيل الخروج قبل نهاية الدوام"),
        "description": (
            "Leaving early reduces cover at closing time, when queues and cash balancing peak.",
            "المغادرة المبكرة تقلل التغطية وقت الإغلاق حين تبلغ الطوابير وتسوية النقد ذروتها.",
        ),
        "expected": (
            "Stay until the scheduled end of shift unless approved.",
            "البقاء حتى نهاية الدوام ما لم تكن المغادرة معتمدة.",
        ),
        "observed": ("Check-out recorded before the end of shift.", "سُجّل الخروج قبل نهاية الدوام."),
        "conditions": {"match": "all", "conditions": [{"field": "early_leave_minutes", "op": "gt", "value": 10}]},
    },
    "HR_MISSING_PUNCH": {
        "policy": "HR-01",
        "category": "attendance",
        "severity": "medium",
        "name": ("Missing check-in or check-out", "تسجيل دخول أو خروج مفقود"),
        "description": (
            "A missing record breaks the working-time trail used for payroll and branch security.",
            "السجل المفقود يقطع أثر وقت العمل المستخدم في الرواتب وأمن الفرع.",
        ),
        "expected": (
            "Record both check-in and check-out on the time clock.",
            "تسجيل الدخول والخروج كليهما على ساعة الدوام.",
        ),
        "observed": ("One of the day's time-clock records is missing.", "أحد سجلات ساعة الدوام لليوم مفقود."),
        "conditions": {
            "match": "any",
            "conditions": [
                {"field": "missing_check_in", "op": "is_true", "value": None},
                {"field": "missing_check_out", "op": "is_true", "value": None},
            ],
        },
    },
    "HR_UNAPPROVED_ABSENCE": {
        "policy": "HR-01",
        "category": "attendance",
        "severity": "high",
        "name": ("Absence without approved leave", "غياب دون إجازة معتمدة"),
        "description": (
            "Unplanned absence leaves the unit understaffed without notice.",
            "الغياب غير المخطط يترك الوحدة دون كادر كافٍ ودون إشعار.",
        ),
        "expected": (
            "Request and obtain leave approval before being absent.",
            "طلب الإجازة والحصول على الموافقة قبل الغياب.",
        ),
        "observed": (
            "No attendance and no approved leave for a scheduled day.",
            "لا حضور ولا إجازة معتمدة في يوم دوام مقرر.",
        ),
        "conditions": {"match": "all", "conditions": [{"field": "unapproved_absence", "op": "is_true", "value": None}]},
    },
    "HR_BREAK_OVERRUN": {
        "policy": "HR-02",
        "category": "attendance",
        "severity": "low",
        "name": ("Break time over the allowance", "تجاوز وقت الاستراحة المسموح"),
        "description": (
            "Long breaks reduce counter cover and lengthen customer waiting times.",
            "الاستراحات الطويلة تقلل تغطية الشبابيك وتطيل انتظار العملاء.",
        ),
        "expected": (
            "Keep total breaks within the 60-minute daily allowance.",
            "إبقاء مجموع الاستراحات ضمن 60 دقيقة يومياً.",
        ),
        "observed": ("Total break time exceeded the allowance.", "تجاوز مجموع وقت الاستراحة الحد المسموح."),
        "conditions": {"match": "all", "conditions": [{"field": "break_overrun_minutes", "op": "gt", "value": 10}]},
    },
    "HR_DRESS_CODE": {
        "policy": "HR-03",
        "category": "dress_code",
        "severity": "low",
        "name": ("Dress code not met", "عدم الالتزام بقواعد اللباس"),
        "description": (
            "Professional appearance and a visible ID badge are part of customer trust and branch security.",
            "المظهر المهني وظهور بطاقة الموظف جزء من ثقة العملاء وأمن الفرع.",
        ),
        "expected": (
            "Wear formal attire or the uniform and display the staff ID badge.",
            "ارتداء اللباس الرسمي أو الزي الموحد وإظهار بطاقة الموظف.",
        ),
        "observed": ("Supervisor recorded that the dress code was not met.", "سجّل المشرف عدم الالتزام بقواعد اللباس."),
        "conditions": {"match": "all", "conditions": [{"field": "dress_compliant", "op": "is_false", "value": None}]},
    },
}
