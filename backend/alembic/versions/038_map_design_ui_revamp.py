"""Map Design UI Revamp — structure locked, audits, boundary overlap

Adds all database schema changes from rounds R5-R7, S11, S14:
- structure_locked columns + structure_lock_audits table
- boundary_status columns + pending_boundary_submissions table
- forest_boundary_audits and boundary_disputes tables
- geometry_audits table
- has_submitted_op denormalized column + triggers
- submitted_by on operational_plans
- calculation_id/deleted_at/created_by on activity_drawn_features
- Various partial indexes

Revision ID: 038_map_design_ui_revamp
Revises: 032_add_performance_indexes, 037_allow_compartment_sampling
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "038_map_design_ui_revamp"
down_revision = ("032_add_performance_indexes", "037_allow_compartment_sampling")


def upgrade() -> None:
    # =========================================================================
    # PART 1: Calculations columns — structure_locked
    # =========================================================================
    op.add_column("calculations", sa.Column("structure_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("calculations", sa.Column("structure_locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("calculations", sa.Column("structure_locked_by", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_calculations_structure_locked_by", "calculations", "users", ["structure_locked_by"], ["id"])
    op.create_index("idx_calculations_structure_locked", "calculations", ["structure_locked"], postgresql_where=sa.text("structure_locked = TRUE"))

    # has_submitted_op — denormalized flag for partial index filtering
    op.add_column("calculations", sa.Column("has_submitted_op", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("idx_calculations_has_submitted_op", "calculations", ["has_submitted_op"], postgresql_where=sa.text("has_submitted_op = TRUE"))

    # =========================================================================
    # PART 2: Calculations columns — boundary_status
    # =========================================================================
    op.add_column("calculations", sa.Column("boundary_status", sa.String(20), nullable=False, server_default="draft"))
    op.add_column("calculations", sa.Column("boundary_status_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("calculations", sa.Column("boundary_status_changed_by", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_calculations_boundary_status_changed_by", "calculations", "users", ["boundary_status_changed_by"], ["id"])
    op.create_index("idx_calculations_boundary_status", "calculations", ["boundary_status"], postgresql_where=sa.text("boundary_status IN ('draft', 'disputed')"))

    # =========================================================================
    # PART 3: structure_lock_audits table
    # =========================================================================
    op.create_table("structure_lock_audits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("calculation_id", UUID(as_uuid=True), sa.ForeignKey("public.calculations.id"), nullable=False, index=True),
        sa.Column("transition", sa.String(30), nullable=False),
        sa.Column("from_state", sa.Boolean(), nullable=False),
        sa.Column("to_state", sa.Boolean(), nullable=False),
        sa.Column("triggered_by_user_id", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=False),
        sa.Column("reason_np", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )
    op.create_index("idx_sla_created_at", "structure_lock_audits", ["created_at"], postgresql_using=None)

    # =========================================================================
    # PART 4: boundary_disputes table (must be created before forest_boundary_audits FK)
    # =========================================================================
    op.create_table("boundary_disputes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("filed_by_user_id", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=False),
        sa.Column("forest_id_1", UUID(as_uuid=True), sa.ForeignKey("public.calculations.id"), nullable=False, index=True),
        sa.Column("forest_id_2", UUID(as_uuid=True), sa.ForeignKey("public.calculations.id"), nullable=False, index=True),
        sa.Column("dispute_reason_np", sa.Text(), nullable=False),
        sa.Column("forest_1_boundary", sa.Text(), nullable=True),
        sa.Column("forest_2_proposed", sa.Text(), nullable=True),
        sa.Column("forest_2_clipped", sa.Text(), nullable=True),
        sa.Column("overlap_area", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("assigned_to_dfo_id", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=True),
        sa.Column("resolved_by_user_id", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=True),
        sa.Column("resolution_type", sa.String(20), nullable=True),
        sa.Column("resolution_notes_np", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )

    # =========================================================================
    # PART 5: forest_boundary_audits table
    # =========================================================================
    op.create_table("forest_boundary_audits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("forest_id", UUID(as_uuid=True), sa.ForeignKey("public.calculations.id"), nullable=False, index=True),
        sa.Column("submitted_geometry", sa.Text(), nullable=True),
        sa.Column("submitted_area_ha", sa.Numeric(10, 4), nullable=True),
        sa.Column("submitted_by_user_id", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_geometry", sa.Text(), nullable=True),
        sa.Column("resolved_area_ha", sa.Numeric(10, 4), nullable=True),
        sa.Column("overlap_removed_ha", sa.Numeric(10, 4), nullable=True),
        sa.Column("overlap_with_forest_ids", sa.ARRAY(UUID(as_uuid=True)), nullable=True),
        sa.Column("resolution_method", sa.String(30), nullable=True),
        sa.Column("user_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("user_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispute_id", sa.Integer(), nullable=True),
        sa.Column("dfo_user_id", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=True),
        sa.Column("dfo_reason_np", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )
    op.create_foreign_key("fk_fba_dispute_id", "forest_boundary_audits", "boundary_disputes", ["dispute_id"], ["id"], deferrable=True, initially="DEFERRED")

    # =========================================================================
    # PART 6: pending_boundary_submissions table (concurrent overlap prevention)
    # =========================================================================
    op.create_table("pending_boundary_submissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("forest_id", UUID(as_uuid=True), sa.ForeignKey("public.calculations.id"), nullable=False, unique=True),
        sa.Column("submitted_geometry", sa.Text(), nullable=False),
        sa.Column("submitted_by_user_id", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=False),
        sa.Column("preview_data", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )
    op.create_index("idx_pbs_expires_at", "pending_boundary_submissions", ["expires_at"], postgresql_using=None)

    # =========================================================================
    # PART 7: geometry_audits table
    # =========================================================================
    op.create_table("geometry_audits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("calculation_id", UUID(as_uuid=True), sa.ForeignKey("public.calculations.id"), nullable=False, index=True),
        sa.Column("layer_type", sa.String(50), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("feature_id", sa.String(100), nullable=True),
        sa.Column("previous_geometry", sa.JSON(), nullable=True),
        sa.Column("new_geometry", sa.JSON(), nullable=True),
        sa.Column("previous_properties", sa.JSON(), nullable=True),
        sa.Column("new_properties", sa.JSON(), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=False),
        sa.Column("session_id", sa.String(100), nullable=True),
        sa.Column("undo_stack_id", sa.String(100), nullable=True),
        sa.Column("undoable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )
    op.create_index("idx_geometry_audits_layer_type", "geometry_audits", ["layer_type"], postgresql_using=None)
    op.create_index("idx_geometry_audits_operation", "geometry_audits", ["operation"], postgresql_using=None)
    op.create_index("idx_geometry_audits_created_at", "geometry_audits", ["created_at"], postgresql_using=None)

    # =========================================================================
    # PART 8: activity_drawn_features — new columns
    # =========================================================================
    op.add_column("activity_drawn_features", sa.Column("calculation_id", UUID(as_uuid=True), sa.ForeignKey("public.calculations.id"), nullable=True, index=True))
    op.add_column("activity_drawn_features", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("activity_drawn_features", sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=True))
    op.create_index("idx_activity_features_calculation", "activity_drawn_features", ["calculation_id"], postgresql_using=None)
    op.create_index("idx_activity_features_geometry_gist", "activity_drawn_features", ["geometry"], postgresql_using="gist")

    # =========================================================================
    # PART 9: operational_plans — submitted_by
    # =========================================================================
    op.add_column("operational_plans", sa.Column("submitted_by", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=True))

    # =========================================================================
    # PART 10: Triggers
    # =========================================================================

    # Trigger: auto-lock structure on OP submission
    op.execute("""
        CREATE OR REPLACE FUNCTION public.fn_auto_lock_structure_on_op_submit()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.status = 'submitted' AND (OLD.status IS DISTINCT FROM 'submitted') THEN
                UPDATE public.calculations
                SET structure_locked = TRUE
                WHERE id = NEW.calculation_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_auto_lock_structure ON public.operational_plans;
        CREATE TRIGGER trg_auto_lock_structure
        AFTER UPDATE OF status ON public.operational_plans
        FOR EACH ROW
        EXECUTE FUNCTION public.fn_auto_lock_structure_on_op_submit();
    """)

    # Trigger: keep has_submitted_op in sync
    op.execute("""
        CREATE OR REPLACE FUNCTION public.fn_update_has_submitted_op()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.status = 'submitted' AND (OLD.status IS DISTINCT FROM 'submitted') THEN
                UPDATE public.calculations SET has_submitted_op = TRUE WHERE id = NEW.calculation_id;
            ELSIF OLD.status = 'submitted' AND (NEW.status IS DISTINCT FROM 'submitted') THEN
                UPDATE public.calculations SET has_submitted_op = FALSE WHERE id = NEW.calculation_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_update_has_submitted_op ON public.operational_plans;
        CREATE TRIGGER trg_update_has_submitted_op
        AFTER UPDATE OF status ON public.operational_plans
        FOR EACH ROW
        EXECUTE FUNCTION public.fn_update_has_submitted_op();
    """)

    # Trigger: audit structure_locked changes
    op.execute("""
        CREATE OR REPLACE FUNCTION public.fn_audit_structure_lock_change()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.structure_locked IS DISTINCT FROM NEW.structure_locked THEN
                INSERT INTO public.structure_lock_audits (
                    calculation_id, transition,
                    from_state, to_state,
                    triggered_by_user_id,
                    created_at
                ) VALUES (
                    NEW.id,
                    CASE
                        WHEN NEW.structure_locked = TRUE THEN 'auto_lock'
                        ELSE 'admin_unlock'
                    END,
                    OLD.structure_locked,
                    NEW.structure_locked,
                    COALESCE(current_setting('app.current_user_id', TRUE)::uuid, NEW.structure_locked_by, (SELECT id FROM public.users LIMIT 1)),
                    NOW()
                );
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_audit_structure_lock ON public.calculations;
        CREATE TRIGGER trg_audit_structure_lock
        AFTER UPDATE OF structure_locked ON public.calculations
        FOR EACH ROW
        EXECUTE FUNCTION public.fn_audit_structure_lock_change();
    """)


def downgrade() -> None:
    # Triggers
    op.execute("DROP TRIGGER IF EXISTS trg_audit_structure_lock ON public.calculations")
    op.execute("DROP FUNCTION IF EXISTS public.fn_audit_structure_lock_change()")
    op.execute("DROP TRIGGER IF EXISTS trg_update_has_submitted_op ON public.operational_plans")
    op.execute("DROP TRIGGER IF EXISTS trg_auto_lock_structure ON public.operational_plans")
    op.execute("DROP FUNCTION IF EXISTS public.fn_update_has_submitted_op()")
    op.execute("DROP FUNCTION IF EXISTS public.fn_auto_lock_structure_on_op_submit()")

    # Tables — child before parent.
    # H1.12 / S1-12: boundary_disputes was dropped before forest_boundary_audits,
    # which holds fk_fba_dispute_id referencing it, so `downgrade base` failed
    # with DependentObjectsStillExist. Latent because no one had run the
    # downgrade path end to end.
    op.drop_table("geometry_audits", schema="public")
    op.drop_table("pending_boundary_submissions", schema="public")
    op.drop_table("forest_boundary_audits", schema="public")
    op.drop_table("boundary_disputes", schema="public")
    op.drop_table("structure_lock_audits", schema="public")

    # Columns — operational_plans
    op.drop_column("operational_plans", "submitted_by")

    # Columns — activity_drawn_features
    op.drop_index("idx_activity_features_geometry_gist", table_name="activity_drawn_features")
    op.drop_index("idx_activity_features_calculation", table_name="activity_drawn_features")
    op.drop_column("activity_drawn_features", "created_by")
    op.drop_column("activity_drawn_features", "deleted_at")
    op.drop_column("activity_drawn_features", "calculation_id")

    # Columns — calculations
    op.drop_index("idx_calculations_boundary_status", table_name="calculations")
    op.drop_index("idx_calculations_has_submitted_op", table_name="calculations")
    op.drop_index("idx_calculations_structure_locked", table_name="calculations")
    op.drop_constraint("fk_calculations_boundary_status_changed_by", "calculations", type_="foreignkey")
    op.drop_constraint("fk_calculations_structure_locked_by", "calculations", type_="foreignkey")
    op.drop_column("calculations", "has_submitted_op")
    op.drop_column("calculations", "boundary_status_changed_by")
    op.drop_column("calculations", "boundary_status_changed_at")
    op.drop_column("calculations", "boundary_status")
    op.drop_column("calculations", "structure_locked_by")
    op.drop_column("calculations", "structure_locked_at")
    op.drop_column("calculations", "structure_locked")
