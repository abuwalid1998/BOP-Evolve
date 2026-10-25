"""rules engine: case facts, rule conditions and approval workflow

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25 20:10:00
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Default definitions for the demo rules shipped in 0001. Inlined so the migration does
# not change when the application catalogue does.
DEFAULTS = json.loads(r"""
{
    "KYC_DOC_CHECK": {
        "name": [
            "Identity verified before account activation",
            "التحقق من الهوية قبل تفعيل الحساب"
        ],
        "observed": [
            "Account activated; verification step recorded after activation.",
            "تم تفعيل الحساب وتسجيل خطوة التحقق بعد التفعيل."
        ],
        "conditions": {
            "1": {
                "match": "all",
                "conditions": [
                    {
                        "field": "id_verified_before_activation",
                        "op": "is_false",
                        "value": null
                    }
                ]
            },
            "2": {
                "match": "all",
                "conditions": [
                    {
                        "field": "id_verified_before_activation",
                        "op": "is_false",
                        "value": null
                    }
                ]
            }
        }
    },
    "CASH_DUAL_APPROVAL": {
        "name": [
            "Dual control on large cash withdrawals",
            "الرقابة المزدوجة على السحوبات النقدية الكبيرة"
        ],
        "observed": [
            "Payout completed; second approval missing in the transaction log.",
            "تم الصرف مع غياب الموافقة الثانية في سجل المعاملة."
        ],
        "conditions": {
            "1": {
                "match": "all",
                "conditions": [
                    {
                        "field": "transaction_kind",
                        "op": "eq",
                        "value": "withdrawal"
                    },
                    {
                        "field": "amount_ils",
                        "op": "gt",
                        "value": 25000
                    },
                    {
                        "field": "second_approval_recorded",
                        "op": "is_false",
                        "value": null
                    }
                ]
            },
            "2": {
                "match": "all",
                "conditions": [
                    {
                        "field": "transaction_kind",
                        "op": "eq",
                        "value": "withdrawal"
                    },
                    {
                        "field": "amount_ils",
                        "op": "gt",
                        "value": 20000
                    },
                    {
                        "field": "second_approval_recorded",
                        "op": "is_false",
                        "value": null
                    }
                ]
            }
        }
    },
    "COMPLAINT_ACK_SLA": {
        "name": [
            "Complaint acknowledged within two business days",
            "الإقرار بالشكوى خلال يومي عمل"
        ],
        "observed": [
            "Acknowledgement sent on business day four.",
            "تم إرسال الإقرار في يوم العمل الرابع."
        ],
        "conditions": {
            "1": {
                "match": "all",
                "conditions": [
                    {
                        "field": "ack_business_days",
                        "op": "gt",
                        "value": 3
                    }
                ]
            },
            "2": {
                "match": "all",
                "conditions": [
                    {
                        "field": "ack_business_days",
                        "op": "gt",
                        "value": 2
                    }
                ]
            }
        }
    },
    "CARD_FEE_DISCLOSURE": {
        "name": [
            "Card fees disclosed before issuance",
            "الإفصاح عن رسوم البطاقة قبل الإصدار"
        ],
        "observed": [
            "Card issued; disclosure checklist incomplete.",
            "تم إصدار البطاقة وقائمة الإفصاح غير مكتملة."
        ],
        "conditions": {
            "1": {
                "match": "all",
                "conditions": [
                    {
                        "field": "fees_disclosed",
                        "op": "is_false",
                        "value": null
                    }
                ]
            },
            "2": {
                "match": "any",
                "conditions": [
                    {
                        "field": "fees_disclosed",
                        "op": "is_false",
                        "value": null
                    },
                    {
                        "field": "customer_acknowledgement_recorded",
                        "op": "is_false",
                        "value": null
                    }
                ]
            }
        }
    },
    "TRF_BENEFICIARY_READBACK": {
        "name": [
            "Beneficiary read-back before transfer",
            "تأكيد بيانات المستفيد قبل الحوالة"
        ],
        "observed": [
            "Transfer submitted without a recorded read-back step.",
            "تم إرسال الحوالة دون تسجيل خطوة القراءة والتأكيد."
        ],
        "conditions": {
            "1": {
                "match": "all",
                "conditions": [
                    {
                        "field": "beneficiary_readback",
                        "op": "is_false",
                        "value": null
                    }
                ]
            },
            "2": {
                "match": "all",
                "conditions": [
                    {
                        "field": "beneficiary_readback",
                        "op": "is_false",
                        "value": null
                    }
                ]
            }
        }
    },
    "INFO_ACCURACY": {
        "name": [
            "Advice based on the current product sheet",
            "الإرشاد وفق نشرة المنتج السارية"
        ],
        "observed": [
            "Outdated rate quoted from a superseded product sheet.",
            "تم ذكر سعر قديم من نشرة منتج ملغاة."
        ],
        "conditions": {
            "1": {
                "match": "all",
                "conditions": [
                    {
                        "field": "product_sheet_current",
                        "op": "is_false",
                        "value": null
                    }
                ]
            },
            "2": {
                "match": "all",
                "conditions": [
                    {
                        "field": "product_sheet_current",
                        "op": "is_false",
                        "value": null
                    }
                ]
            }
        }
    },
    "LOAN_AFFORDABILITY_QS": {
        "name": [
            "Affordability assessed before financing advice",
            "تقييم القدرة على السداد قبل عرض التمويل"
        ],
        "observed": [
            "Financing options presented; affordability checklist not started.",
            "تم عرض خيارات التمويل دون البدء بقائمة القدرة على السداد."
        ],
        "conditions": {
            "1": {
                "match": "all",
                "conditions": [
                    {
                        "field": "financing_discussed",
                        "op": "is_true",
                        "value": null
                    },
                    {
                        "field": "affordability_checked",
                        "op": "is_false",
                        "value": null
                    }
                ]
            },
            "2": {
                "match": "all",
                "conditions": [
                    {
                        "field": "financing_discussed",
                        "op": "is_true",
                        "value": null
                    },
                    {
                        "field": "affordability_checked",
                        "op": "is_false",
                        "value": null
                    }
                ]
            }
        }
    }
}
""")


def _user_fk(column: str, table: str) -> sa.Column:
    return sa.Column(
        column, sa.String(length=32), sa.ForeignKey("users.id", name=f"fk_{table}_{column}_users"), nullable=True
    )


def upgrade() -> None:
    op.add_column("service_cases", sa.Column("attributes", sa.JSON(), nullable=True))
    op.add_column("findings", sa.Column("matched_conditions", sa.JSON(), nullable=True))

    op.add_column("policy_versions", sa.Column("status", sa.String(length=20), server_default="active", nullable=False))
    op.add_column("policy_versions", _user_fk("created_by", "policy_versions"))
    op.add_column("policy_versions", sa.Column("created_at", app.db.UTCDateTime(timezone=True), nullable=True))
    op.add_column("policy_versions", _user_fk("submitted_by", "policy_versions"))
    op.add_column("policy_versions", sa.Column("submitted_at", app.db.UTCDateTime(timezone=True), nullable=True))
    op.add_column("policy_versions", _user_fk("approved_by", "policy_versions"))
    op.add_column("policy_versions", sa.Column("review_note", sa.Text(), nullable=True))
    op.create_check_constraint(
        "status", "policy_versions", "status IN ('draft','pending_approval','active','superseded','retired')"
    )

    op.add_column("mistake_rules", sa.Column("name", sa.String(length=160), server_default="", nullable=False))
    op.add_column("mistake_rules", sa.Column("name_ar", sa.String(length=160), server_default="", nullable=False))
    op.add_column("mistake_rules", sa.Column("kind", sa.String(length=16), server_default="breach", nullable=False))
    op.add_column("mistake_rules", sa.Column("observed_action", sa.Text(), nullable=True))
    op.add_column("mistake_rules", sa.Column("observed_action_ar", sa.Text(), nullable=True))
    op.add_column("mistake_rules", sa.Column("conditions", sa.JSON(), nullable=True))
    op.add_column("mistake_rules", sa.Column("base_confidence", sa.Float(), server_default="0.8", nullable=False))
    op.add_column("mistake_rules", sa.Column("status", sa.String(length=20), server_default="draft", nullable=False))
    op.add_column("mistake_rules", _user_fk("created_by", "mistake_rules"))
    op.add_column("mistake_rules", sa.Column("created_at", app.db.UTCDateTime(timezone=True), nullable=True))
    op.add_column("mistake_rules", _user_fk("submitted_by", "mistake_rules"))
    op.add_column("mistake_rules", sa.Column("submitted_at", app.db.UTCDateTime(timezone=True), nullable=True))
    op.add_column("mistake_rules", _user_fk("approved_by", "mistake_rules"))
    op.add_column("mistake_rules", sa.Column("approved_at", app.db.UTCDateTime(timezone=True), nullable=True))
    op.add_column("mistake_rules", sa.Column("retired_at", app.db.UTCDateTime(timezone=True), nullable=True))
    op.add_column("mistake_rules", sa.Column("review_note", sa.Text(), nullable=True))
    op.create_index(op.f("ix_mistake_rules_status"), "mistake_rules", ["status"], unique=False)
    op.create_check_constraint("status", "mistake_rules", "status IN ('draft','pending_approval','active','retired')")
    op.create_check_constraint("kind", "mistake_rules", "kind IN ('breach','early_warning')")
    op.create_check_constraint("base_confidence", "mistake_rules", "base_confidence >= 0 AND base_confidence <= 1")

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE policy_versions SET status = CASE WHEN effective_to IS NULL THEN 'active' ELSE 'superseded' END, "
            "created_at = approved_at"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE mistake_rules SET status = CASE WHEN active THEN 'active' ELSE 'retired' END, "
            "approved_at = (SELECT p.approved_at FROM policy_versions p WHERE p.id = mistake_rules.policy_version_id), "
            "created_at = (SELECT p.approved_at FROM policy_versions p WHERE p.id = mistake_rules.policy_version_id)"
        )
    )
    rules = sa.table(
        "mistake_rules",
        sa.column("rule_code", sa.String),
        sa.column("version", sa.String),
        sa.column("name", sa.String),
        sa.column("name_ar", sa.String),
        sa.column("observed_action", sa.Text),
        sa.column("observed_action_ar", sa.Text),
        sa.column("conditions", sa.JSON),
    )
    for code, spec in DEFAULTS.items():
        for version, conditions in spec["conditions"].items():
            bind.execute(
                rules.update()
                .where(rules.c.rule_code == code, rules.c.version == version)
                .values(
                    name=spec["name"][0],
                    name_ar=spec["name"][1],
                    observed_action=spec["observed"][0],
                    observed_action_ar=spec["observed"][1],
                    conditions=conditions,
                )
            )
    op.drop_column("mistake_rules", "active")


def downgrade() -> None:
    op.add_column("mistake_rules", sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.get_bind().execute(sa.text("UPDATE mistake_rules SET active = (status = 'active')"))
    op.drop_constraint(op.f("ck_mistake_rules_base_confidence"), "mistake_rules", type_="check")
    op.drop_constraint(op.f("ck_mistake_rules_kind"), "mistake_rules", type_="check")
    op.drop_constraint(op.f("ck_mistake_rules_status"), "mistake_rules", type_="check")
    op.drop_index(op.f("ix_mistake_rules_status"), table_name="mistake_rules")
    for column in (
        "review_note",
        "retired_at",
        "approved_at",
        "approved_by",
        "submitted_at",
        "submitted_by",
        "created_at",
        "created_by",
        "status",
        "base_confidence",
        "conditions",
        "observed_action_ar",
        "observed_action",
        "kind",
        "name_ar",
        "name",
    ):
        op.drop_column("mistake_rules", column)
    op.drop_constraint(op.f("ck_policy_versions_status"), "policy_versions", type_="check")
    for column in ("review_note", "approved_by", "submitted_at", "submitted_by", "created_at", "created_by", "status"):
        op.drop_column("policy_versions", column)
    op.drop_column("findings", "matched_conditions")
    op.drop_column("service_cases", "attributes")
