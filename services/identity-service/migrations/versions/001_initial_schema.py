"""Initial schema — all identity service tables + seed data

Revision ID: 001
Revises:
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── departments ──────────────────────────────────────────
    op.create_table(
        "departments",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column("parent_dept_id", sa.String(32), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── roles ────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column("name", sa.String(50), primary_key=True),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("parent_role", sa.String(50), sa.ForeignKey("roles.name"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # ── users ────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("dept_id", sa.String(32), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="dept_viewer"),
        sa.Column("clearance_level", sa.Integer, nullable=False, server_default="2"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_mfa_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_dept_role", "users", ["dept_id", "role"])

    # ── permissions ──────────────────────────────────────────
    op.create_table(
        "permissions",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )

    # ── role_permissions ─────────────────────────────────────
    op.create_table(
        "role_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("role_name", sa.String(50), sa.ForeignKey("roles.name"), nullable=False),
        sa.Column("permission_id", sa.String(128), sa.ForeignKey("permissions.id"), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("role_name", "permission_id", name="uq_role_permission"),
    )
    op.create_index("ix_role_permissions_role", "role_permissions", ["role_name"])

    # ── role_assignments ─────────────────────────────────────
    op.create_table(
        "role_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role_name", sa.String(50), sa.ForeignKey("roles.name"), nullable=False),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revocation_reason", sa.String(512), nullable=True),
    )
    op.create_index("ix_role_assignments_user_active", "role_assignments", ["user_id", "revoked_at"])

    # ── abac_policies ────────────────────────────────────────
    op.create_table(
        "abac_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), unique=True, nullable=False),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("condition_yaml", sa.Text, nullable=False),
        sa.Column("applies_to", sa.String(512), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # ── audit_logs ───────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("actor_role", sa.String(50), nullable=False),
        sa.Column("actor_dept_id", sa.String(32), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
    )
    op.create_index("ix_audit_actor_ts", "audit_logs", ["actor_id", "timestamp"])
    op.create_index("ix_audit_resource", "audit_logs", ["resource_type", "resource_id"])
    op.create_index("ix_audit_action_ts", "audit_logs", ["action", "timestamp"])
    op.create_index("ix_audit_trace", "audit_logs", ["trace_id"])

    # ── Seed: default roles ───────────────────────────────────
    op.execute("""
        INSERT INTO roles (name, description) VALUES
        ('city_admin',       'Full access to all city systems and departments'),
        ('dept_admin',       'Department administrator — manages their own department'),
        ('dept_analyst',     'Department analyst — read access to KPIs and reports'),
        ('dept_viewer',      'Department viewer — read-only dashboard access'),
        ('auditor',          'Read-only access to all audit logs and governance data'),
        ('ai_reviewer',      'Reviews and approves AI-generated recommendations'),
        ('system_operator',  'Infrastructure monitoring — no access to municipal data')
        ON CONFLICT DO NOTHING
    """)

    # ── Seed: default departments ─────────────────────────────
    op.execute("""
        INSERT INTO departments (id, name, description) VALUES
        ('WATER',      'Water & Sanitation Department',   'Water supply, wastewater, and sanitation services'),
        ('TRANSPORT',  'Transportation Department',       'Roads, public transit, and traffic management'),
        ('HEALTH',     'Health Department',               'Public health, clinics, and medical services'),
        ('FINANCE',    'Finance Department',              'Municipal budget, billing, and financial services'),
        ('EDUCATION',  'Education Department',            'Schools, libraries, and educational programs'),
        ('IT',         'Information Technology',          'City IT infrastructure and digital services'),
        ('PLANNING',   'Urban Planning Department',       'Land use, permits, and city development'),
        ('SECURITY',   'Public Safety Department',        'Police, fire, and emergency services')
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("abac_policies")
    op.drop_table("role_assignments")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("departments")
