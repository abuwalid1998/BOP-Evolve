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
            f"Rule {spec['rule']} flagged this case under policy {code} v{policy_version}. "
            f"{spec['description'][i]} Expected: {spec['expected'][i]}"
        )
    return (
        f"رصدت القاعدة {spec['rule']} هذه الحالة بموجب السياسة {code} الإصدار {policy_version}. "
        f"{spec['description'][i]} المتوقع: {spec['expected'][i]}"
    )
